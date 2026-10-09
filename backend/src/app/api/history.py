"""A customer's full money history: every ledger entry with a running balance, and every invoice."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.billing import _invoice_out
from app.api.deps import get_visible_customer, require
from app.api.schemas import InvoiceOut, LedgerRowOut
from app.core.db import get_db
from app.models import BillingAccount, Invoice, LedgerEntry, Receipt, User
from app.services import billing as svc

router = APIRouter(tags=["history"])


def _account(db: Session, customer_id: uuid.UUID) -> BillingAccount | None:
    return db.scalar(select(BillingAccount).where(BillingAccount.customer_id == customer_id))


@router.get("/customers/{customer_id}/ledger", response_model=list[LedgerRowOut])
def customer_ledger(customer_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                    db: Session = Depends(get_db),
                    user: User = Depends(require("invoice.view", "customer.view_assigned"))):
    """Every bill, payment, adjustment and refund, newest first, with the balance after each one."""
    get_visible_customer(db, user, customer_id)
    acct = _account(db, customer_id)
    if acct is None:
        return []
    # The running balance is computed over the WHOLE history, then the page is cut from it.
    running = func.sum(LedgerEntry.amount).over(order_by=(LedgerEntry.posted_at, LedgerEntry.id))
    inner = (
        select(LedgerEntry.id.label("id"), LedgerEntry.entry_type, LedgerEntry.amount, LedgerEntry.description,
               LedgerEntry.ref_type, LedgerEntry.ref_id, LedgerEntry.effective_date, LedgerEntry.posted_at,
               LedgerEntry.reverses_entry_id, running.label("balance"))
        .where(LedgerEntry.billing_account_id == acct.id)
        .subquery()
    )
    rows = db.execute(
        select(inner).order_by(inner.c.posted_at.desc(), inner.c.id.desc()).limit(limit).offset(offset)
    ).all()

    invoice_ids = {r.ref_id for r in rows if r.ref_type == "INVOICE" and r.ref_id}
    payment_ids = {r.ref_id for r in rows if r.ref_type == "PAYMENT" and r.ref_id}
    numbers: dict[uuid.UUID, str] = {}
    if invoice_ids:
        numbers.update(dict(db.execute(select(Invoice.id, Invoice.invoice_number).where(Invoice.id.in_(invoice_ids))).all()))
    if payment_ids:
        numbers.update(dict(db.execute(select(Receipt.payment_id, Receipt.receipt_number)
                                       .where(Receipt.payment_id.in_(payment_ids))).all()))
    return [
        LedgerRowOut(
            id=r.id, entry_type=r.entry_type, amount=r.amount, description=r.description, ref_type=r.ref_type,
            ref_id=r.ref_id, reference=numbers.get(r.ref_id) if r.ref_id else None,
            effective_date=r.effective_date, posted_at=r.posted_at, reverses_entry_id=r.reverses_entry_id,
            balance=Decimal(r.balance).quantize(Decimal("0.01")),
        )
        for r in rows
    ]


@router.get("/customers/{customer_id}/invoices", response_model=list[InvoiceOut])
def customer_invoices(customer_id: uuid.UUID, limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
                      db: Session = Depends(get_db),
                      user: User = Depends(require("invoice.view", "customer.view_assigned"))):
    """Every invoice (paid or not), newest first, with what was paid and what is still owed."""
    get_visible_customer(db, user, customer_id)
    acct = _account(db, customer_id)
    if acct is None:
        return []
    invoices = list(db.scalars(
        select(Invoice).where(Invoice.billing_account_id == acct.id)
        .order_by(Invoice.issue_date.desc(), Invoice.invoice_number.desc()).limit(limit).offset(offset)))
    paid = svc.paid_by_invoice(db, [i.id for i in invoices])
    today = svc.local_today()
    out = []
    for inv in invoices:
        got = paid.get(inv.id, svc.ZERO)
        out.append(_invoice_out(db, inv, got, inv.total - got, svc.derive_invoice_status(inv.total, got, inv.due_date, today)))
    return out
