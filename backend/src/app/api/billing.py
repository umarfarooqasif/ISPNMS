import uuid
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import collector_of, get_visible_customer, has_perm, require
from app.api.schemas import (
    AdjustmentCreate, InvoiceCreate, InvoiceLineOut, InvoiceOut, LedgerEntryOut, PaymentCreate,
    PaymentOut, PaymentVoid, ReceiptOut, RefundCreate, StatementOut, AllocationOut,
)
from app.core.db import get_db
from app.models import BillingAccount, Invoice, Payment, Receipt, User
from app.services import audit
from app.services import billing as svc

router = APIRouter(tags=["billing"])


# ------------------------------------------------------------------ builders
def _customer_id_of(db: Session, account_id: uuid.UUID) -> uuid.UUID:
    return db.get(BillingAccount, account_id).customer_id


def _invoice_out(db: Session, inv: Invoice, paid=None, outstanding=None, status=None) -> InvoiceOut:
    if paid is None:
        s = svc.invoice_summary(db, inv)
        paid, outstanding, status = s["paid"], s["outstanding"], s["status"]
    return InvoiceOut(
        id=inv.id, invoice_number=inv.invoice_number,
        customer_id=_customer_id_of(db, inv.billing_account_id), issue_date=inv.issue_date,
        due_date=inv.due_date, period=inv.period, total=inv.total, paid=paid,
        outstanding=outstanding, status=status, notes=inv.notes,
        lines=[InvoiceLineOut.model_validate(ln) for ln in inv.lines],
    )


def _payment_out(db: Session, o: svc.PaymentOutcome) -> PaymentOut:
    p = o.payment
    return PaymentOut(
        id=p.id, customer_id=_customer_id_of(db, p.billing_account_id), amount=p.amount,
        method=p.method, status=p.status, collector_id=p.collector_id,
        client_txn_id=p.client_txn_id, collected_at=p.collected_at, received_at=p.received_at,
        receipt_number=o.receipt.receipt_number if o.receipt else None,
        receipt_status=o.receipt.status if o.receipt else None,
        allocations=[AllocationOut.model_validate(a) for a in p.allocations],
        unallocated=o.credit, balance=o.balance, replayed=o.replay, void_reason=p.void_reason,
    )


def _payment_scope(db: Session, user: User):
    """None = all payments; otherwise a condition limiting to the collector's own payments."""
    if has_perm(user, "payment.view"):
        return None
    if has_perm(user, "collection.view_own"):
        collector = collector_of(db, user)
        return Payment.id.in_([]) if collector is None else Payment.collector_id == collector.id
    raise HTTPException(403, "Permission denied")


# ------------------------------------------------------------------ invoices
@router.post("/invoices", response_model=InvoiceOut, status_code=201)
def create_invoice(body: InvoiceCreate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require("invoice.create"))):
    get_visible_customer(db, user, body.customer_id)
    invoice = svc.create_invoice(
        db, customer_id=body.customer_id,
        lines=[svc.LineIn(l.charge_type, l.amount, l.description, l.connection_id) for l in body.lines],
        issue_date=body.issue_date, due_date=body.due_date, period=body.period, notes=body.notes,
        user_id=user.id,
    )
    audit.log(db, user_id=user.id, action="invoice.create", entity="invoice", entity_id=invoice.id,
              after={"invoice_number": invoice.invoice_number, "customer_id": body.customer_id,
                     "total": invoice.total, "lines": [l.model_dump() for l in body.lines]},
              request=request)
    db.commit()
    return _invoice_out(db, invoice)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(require("invoice.view", "customer.view_assigned"))):
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "Invoice not found")
    get_visible_customer(db, user, _customer_id_of(db, inv.billing_account_id))
    return _invoice_out(db, inv)


@router.get("/customers/{customer_id}/statement", response_model=StatementOut)
def customer_statement(customer_id: uuid.UUID, db: Session = Depends(get_db),
                       user: User = Depends(require("invoice.view", "customer.view_assigned"))):
    get_visible_customer(db, user, customer_id)
    s = svc.statement(db, customer_id)
    db.commit()  # the statement may have created the (empty) billing account
    return StatementOut(
        customer_id=customer_id, balance=s["balance"], amount_due=s["amount_due"],
        credit=s["credit"],
        open_invoices=[
            _invoice_out(db, r["invoice"], r["paid"], r["outstanding"], r["status"])
            for r in s["open_invoices"]
        ],
        recent_entries=[LedgerEntryOut.model_validate(e) for e in s["recent_entries"]],
    )


# ------------------------------------------------------------------ payments
@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(body: PaymentCreate, request: Request, response: Response,
                   db: Session = Depends(get_db), user: User = Depends(require("payment.create"))):
    get_visible_customer(db, user, body.customer_id)  # collectors: assigned customers only
    collector = collector_of(db, user)
    if collector is not None and collector.status != "ACTIVE":
        raise HTTPException(403, "Collector account is inactive")
    if body.client_txn_id and collector is None:
        raise HTTPException(422, "client_txn_id is only valid for collector accounts")

    outcome = svc.record_payment(
        db, customer_id=body.customer_id, amount=body.amount, method=body.method,
        user_id=user.id, collector_id=collector.id if collector else None,
        connection_id=body.connection_id, client_txn_id=body.client_txn_id,
        collected_at=body.collected_at, notes=body.notes,
    )
    if outcome.replay:
        response.status_code = 200  # idempotent replay: same payment, nothing new written
        return _payment_out(db, outcome)

    audit.log(
        db, user_id=user.id, action="payment.create", entity="payment", entity_id=outcome.payment.id,
        after={"customer_id": body.customer_id, "amount": outcome.payment.amount,
               "method": body.method, "receipt_number": outcome.receipt.receipt_number,
               "collector_id": outcome.payment.collector_id,
               "client_txn_id": body.client_txn_id},
        request=request,
    )
    db.commit()
    return _payment_out(db, outcome)


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(
    customer_id: uuid.UUID | None = None, collector_id: uuid.UUID | None = None,
    status: str | None = None, date_from: date | None = None, date_to: date | None = None,
    limit: int = 50, offset: int = 0, db: Session = Depends(get_db),
    user: User = Depends(require("payment.view", "collection.view_own")),
):
    stmt = select(Payment).order_by(Payment.received_at.desc(), Payment.id.desc())
    scope = _payment_scope(db, user)
    if scope is not None:
        stmt = stmt.where(scope)
    if customer_id:
        acct = db.scalar(select(BillingAccount).where(BillingAccount.customer_id == customer_id))
        stmt = stmt.where(Payment.billing_account_id == (acct.id if acct else None))
    if collector_id:
        stmt = stmt.where(Payment.collector_id == collector_id)
    if status:
        stmt = stmt.where(Payment.status == status)
    if date_from:
        stmt = stmt.where(Payment.collected_at >= datetime.combine(date_from, time.min).astimezone())
    if date_to:
        stmt = stmt.where(Payment.collected_at <= datetime.combine(date_to, time.max).astimezone())
    stmt = stmt.limit(min(max(limit, 1), 200)).offset(max(offset, 0))
    return [_payment_out(db, svc.payment_outcome(db, p)) for p in db.scalars(stmt)]


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: uuid.UUID, db: Session = Depends(get_db),
                user: User = Depends(require("payment.view", "collection.view_own"))):
    stmt = select(Payment).where(Payment.id == payment_id)
    scope = _payment_scope(db, user)
    if scope is not None:
        stmt = stmt.where(scope)
    payment = db.scalar(stmt)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    return _payment_out(db, svc.payment_outcome(db, payment))


@router.post("/payments/{payment_id}/void", response_model=PaymentOut)
def void_payment(payment_id: uuid.UUID, body: PaymentVoid, request: Request,
                 db: Session = Depends(get_db), user: User = Depends(require("payment.void"))):
    before_payment = db.get(Payment, payment_id)
    before = {"status": before_payment.status} if before_payment else None
    outcome = svc.void_payment(db, payment_id=payment_id, reason=body.reason, user_id=user.id)
    audit.log(db, user_id=user.id, action="payment.void", entity="payment", entity_id=payment_id,
              before=before, after={"status": "VOID", "reason": body.reason,
                                    "receipt_number": outcome.receipt.receipt_number},
              request=request)
    db.commit()
    return _payment_out(db, outcome)


# ------------------------------------------------------------------ adjustments / refunds
@router.post("/adjustments", response_model=LedgerEntryOut, status_code=201)
def create_adjustment(body: AdjustmentCreate, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require("billing.adjust"))):
    get_visible_customer(db, user, body.customer_id)
    entry = svc.post_adjustment(
        db, customer_id=body.customer_id, amount=body.amount, reason=body.reason,
        user_id=user.id, connection_id=body.connection_id,
    )
    audit.log(db, user_id=user.id, action="billing.adjustment", entity="ledger_entry",
              entity_id=entry.id, after={"customer_id": body.customer_id, "amount": entry.amount,
                                         "reason": body.reason}, request=request)
    db.commit()
    return entry


@router.post("/refunds", response_model=LedgerEntryOut, status_code=201)
def create_refund(body: RefundCreate, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(require("billing.refund"))):
    get_visible_customer(db, user, body.customer_id)
    entry = svc.issue_refund(
        db, customer_id=body.customer_id, amount=body.amount, reason=body.reason, user_id=user.id
    )
    audit.log(db, user_id=user.id, action="billing.refund", entity="ledger_entry",
              entity_id=entry.id, after={"customer_id": body.customer_id, "amount": entry.amount,
                                         "reason": body.reason}, request=request)
    db.commit()
    return entry


# ------------------------------------------------------------------ receipts
@router.get("/receipts/{receipt_number}", response_model=ReceiptOut)
def get_receipt(receipt_number: str, db: Session = Depends(get_db),
                user: User = Depends(require("receipt.view"))):
    receipt = db.scalar(select(Receipt).where(Receipt.receipt_number == receipt_number))
    if receipt is None:
        raise HTTPException(404, "Receipt not found")
    scope = _payment_scope(db, user)
    stmt = select(Payment).where(Payment.id == receipt.payment_id)
    if scope is not None:
        stmt = stmt.where(scope)
    payment = db.scalar(stmt)
    if payment is None:
        raise HTTPException(404, "Receipt not found")
    return ReceiptOut(
        receipt_number=receipt.receipt_number, status=receipt.status, issued_at=receipt.issued_at,
        payment=_payment_out(db, svc.payment_outcome(db, payment)),
    )
