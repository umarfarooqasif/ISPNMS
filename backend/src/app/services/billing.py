"""Server-side billing core.

Rules enforced here (and backed by DB constraints/triggers):
- Money is Decimal / NUMERIC(12,2). Amounts with more than 2 decimal places are rejected, not rounded.
- Balance = SUM(ledger_entries.amount). Positive = customer owes, negative = credit.
- Ledger, invoices, invoice lines and allocations are append-only. Corrections post reversing entries.
- Every financial write locks the billing account row so concurrent writes serialise.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    BillingAccount,
    Connection,
    Customer,
    Invoice,
    InvoiceLine,
    LedgerEntry,
    Payment,
    PaymentAllocation,
    Receipt,
)

ZERO = Decimal("0.00")
CENT = Decimal("0.01")


class BillingError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------- helpers


def money(value) -> Decimal:
    """Exact 2-dp Decimal. Refuses floats and anything needing rounding."""
    if isinstance(value, float):
        raise BillingError("floating point amounts are not accepted", 422)
    d = Decimal(value)
    if d != d.quantize(CENT):
        raise BillingError("amounts may have at most 2 decimal places", 422)
    return d.quantize(CENT)


def local_today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def _next_number(db: Session, seq: str, prefix: str) -> str:
    n = db.execute(text(f"SELECT nextval('{seq}')")).scalar_one()
    return f"{prefix}-{n:06d}"


def get_or_create_account(db: Session, customer_id: uuid.UUID) -> BillingAccount:
    acct = db.scalar(select(BillingAccount).where(BillingAccount.customer_id == customer_id))
    if acct:
        return acct
    try:
        with db.begin_nested():
            acct = BillingAccount(customer_id=customer_id)
            db.add(acct)
            db.flush()
        return acct
    except IntegrityError:  # created concurrently
        return db.scalar(select(BillingAccount).where(BillingAccount.customer_id == customer_id))


def lock_account(db: Session, account_id: uuid.UUID) -> BillingAccount:
    acct = db.scalar(
        select(BillingAccount).where(BillingAccount.id == account_id).with_for_update()
    )
    if acct is None:
        raise BillingError("billing account not found", 404)
    return acct


def balance(db: Session, account_id: uuid.UUID) -> Decimal:
    total = db.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.billing_account_id == account_id
        )
    )
    return Decimal(total).quantize(CENT)


def _check_connection(db: Session, customer_id: uuid.UUID, connection_id: uuid.UUID | None):
    if connection_id is None:
        return
    conn = db.get(Connection, connection_id)
    if conn is None or conn.customer_id != customer_id:
        raise BillingError("connection does not belong to this customer", 422)


def _ledger(db, *, account_id, entry_type, amount, user_id, effective_date, description=None,
            ref_type=None, ref_id=None, connection_id=None, reverses=None) -> LedgerEntry:
    entry = LedgerEntry(
        billing_account_id=account_id,
        connection_id=connection_id,
        entry_type=entry_type,
        amount=amount,
        description=description,
        ref_type=ref_type,
        ref_id=ref_id,
        effective_date=effective_date,
        posted_by=user_id,
        reverses_entry_id=reverses,
    )
    db.add(entry)
    return entry


# ---------------------------------------------------------------- invoices


def derive_invoice_status(total: Decimal, paid: Decimal, due_date: date, today: date) -> str:
    """PAID / PARTIAL / DUE / OVERDUE / FREE. Overdue takes precedence over partial when past due."""
    if total == ZERO:
        return "FREE"
    outstanding = total - paid
    if outstanding <= ZERO:
        return "PAID"
    if due_date < today:
        return "OVERDUE"
    if paid > ZERO:
        return "PARTIAL"
    return "DUE"


def paid_by_invoice(db: Session, invoice_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
    if not invoice_ids:
        return {}
    rows = db.execute(
        select(PaymentAllocation.invoice_id, func.sum(PaymentAllocation.amount))
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(PaymentAllocation.invoice_id.in_(invoice_ids), Payment.status != "VOID")
        .group_by(PaymentAllocation.invoice_id)
    ).all()
    return {inv_id: Decimal(total) for inv_id, total in rows}


def invoice_summary(db: Session, invoice: Invoice) -> dict:
    paid = paid_by_invoice(db, [invoice.id]).get(invoice.id, ZERO)
    return {
        "invoice": invoice,
        "paid": paid,
        "outstanding": invoice.total - paid,
        "status": derive_invoice_status(invoice.total, paid, invoice.due_date, local_today()),
    }


def open_invoices(db: Session, account_id: uuid.UUID) -> list[tuple[Invoice, Decimal]]:
    """Invoices with an outstanding amount, oldest due first. Returns (invoice, paid)."""
    invoices = list(
        db.scalars(
            select(Invoice)
            .where(Invoice.billing_account_id == account_id, Invoice.total > 0)
            .order_by(Invoice.due_date, Invoice.issue_date, Invoice.created_at, Invoice.id)
        )
    )
    paid = paid_by_invoice(db, [i.id for i in invoices])
    return [(i, paid.get(i.id, ZERO)) for i in invoices if i.total - paid.get(i.id, ZERO) > 0]


@dataclass
class LineIn:
    charge_type: str
    amount: Decimal
    description: str | None = None
    connection_id: uuid.UUID | None = None


def create_invoice(
    db: Session, *, customer_id: uuid.UUID, lines: list[LineIn], issue_date: date | None,
    due_date: date, period: date | None, notes: str | None, user_id: uuid.UUID | None,
) -> Invoice:
    if not lines:
        raise BillingError("an invoice needs at least one line", 422)
    issue_date = issue_date or local_today()
    if due_date < issue_date:
        raise BillingError("due date cannot be before issue date", 422)

    acct = lock_account(db, get_or_create_account(db, customer_id).id)

    clean: list[LineIn] = []
    for ln in lines:
        amt = money(ln.amount)
        if ln.charge_type == "DISCOUNT" and amt > ZERO:
            raise BillingError("discount lines must be negative", 422)
        if ln.charge_type != "DISCOUNT" and amt < ZERO:
            raise BillingError("only discount lines may be negative", 422)
        _check_connection(db, customer_id, ln.connection_id)
        clean.append(LineIn(ln.charge_type, amt, ln.description, ln.connection_id))

    total = sum((ln.amount for ln in clean), ZERO)
    if total < ZERO:
        raise BillingError("discounts cannot exceed charges on one invoice", 422)

    invoice = Invoice(
        invoice_number=_next_number(db, "invoice_number_seq", get_settings().invoice_prefix),
        billing_account_id=acct.id,
        period=period,
        issue_date=issue_date,
        due_date=due_date,
        total=total,
        notes=notes,
        created_by=user_id,
    )
    db.add(invoice)
    db.flush()

    for ln in clean:
        db.add(
            InvoiceLine(
                invoice_id=invoice.id, connection_id=ln.connection_id,
                charge_type=ln.charge_type, description=ln.description, amount=ln.amount,
            )
        )
        if ln.amount != ZERO:  # zero-amount lines (e.g. FREE connections) stay visible, no ledger row
            _ledger(
                db, account_id=acct.id,
                entry_type="DISCOUNT" if ln.charge_type == "DISCOUNT" else "CHARGE",
                amount=ln.amount, user_id=user_id, effective_date=issue_date,
                description=ln.description or ln.charge_type, ref_type="INVOICE",
                ref_id=invoice.id, connection_id=ln.connection_id,
            )
    db.flush()
    db.refresh(invoice)
    return invoice


# ---------------------------------------------------------------- payments


@dataclass
class PaymentOutcome:
    payment: Payment
    receipt: Receipt
    allocated: Decimal
    credit: Decimal  # part of this payment not applied to any invoice (advance)
    balance: Decimal
    replay: bool = False


def _outcome(db: Session, payment: Payment, replay: bool) -> PaymentOutcome:
    allocated = sum((a.amount for a in payment.allocations), ZERO)
    receipt = db.scalar(select(Receipt).where(Receipt.payment_id == payment.id))
    return PaymentOutcome(
        payment=payment, receipt=receipt, allocated=allocated,
        credit=payment.amount - allocated, balance=balance(db, payment.billing_account_id),
        replay=replay,
    )


def payment_outcome(db: Session, payment: Payment) -> PaymentOutcome:
    """Read-side view of an existing payment (allocations, receipt, current balance)."""
    return _outcome(db, payment, replay=False)


def _replay_or_conflict(db, existing: Payment, account_id, amount, method) -> PaymentOutcome:
    if (
        existing.billing_account_id != account_id
        or existing.amount != amount
        or existing.method != method
    ):
        raise BillingError("client_txn_id was already used for a different payment", 409)
    return _outcome(db, existing, replay=True)


def record_payment(
    db: Session, *, customer_id: uuid.UUID, amount, method: str, user_id: uuid.UUID | None,
    collector_id: uuid.UUID | None = None, connection_id: uuid.UUID | None = None,
    client_txn_id: str | None = None, collected_at: datetime | None = None,
    notes: str | None = None, status: str = "POSTED",
) -> PaymentOutcome:
    amount = money(amount)
    if amount <= ZERO:
        raise BillingError("payment amount must be positive", 422)
    if client_txn_id is not None and collector_id is None:
        raise BillingError("client_txn_id requires a collector", 422)

    customer = db.get(Customer, customer_id)
    if customer is None:
        raise BillingError("customer not found", 404)
    acct = lock_account(db, get_or_create_account(db, customer_id).id)
    _check_connection(db, customer_id, connection_id)

    if client_txn_id is not None:
        existing = db.scalar(
            select(Payment).where(
                Payment.collector_id == collector_id, Payment.client_txn_id == client_txn_id
            )
        )
        if existing:
            return _replay_or_conflict(db, existing, acct.id, amount, method)

    payment = Payment(
        billing_account_id=acct.id, connection_id=connection_id, amount=amount, method=method,
        collector_id=collector_id, client_txn_id=client_txn_id,
        collected_at=collected_at or datetime.now(UTC), status=status, notes=notes,
        created_by=user_id,
    )
    try:
        with db.begin_nested():
            db.add(payment)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(Payment).where(
                Payment.collector_id == collector_id, Payment.client_txn_id == client_txn_id
            )
        )
        if existing is None:
            raise
        return _replay_or_conflict(db, existing, acct.id, amount, method)

    # Oldest-due-first allocation; any remainder stays as credit (advance payment).
    remaining = amount
    for invoice, paid in open_invoices(db, acct.id):
        if remaining <= ZERO:
            break
        take = min(invoice.total - paid, remaining)
        db.add(PaymentAllocation(payment_id=payment.id, invoice_id=invoice.id, amount=take))
        remaining -= take

    _ledger(
        db, account_id=acct.id, entry_type="PAYMENT", amount=-amount, user_id=user_id,
        effective_date=local_today(), description=f"Payment ({method})", ref_type="PAYMENT",
        ref_id=payment.id, connection_id=connection_id,
    )
    receipt = Receipt(
        receipt_number=_next_number(db, "receipt_number_seq", get_settings().receipt_prefix),
        payment_id=payment.id, issued_by=user_id,
    )
    db.add(receipt)
    db.flush()
    db.refresh(payment)
    return _outcome(db, payment, replay=False)


def void_payment(
    db: Session, *, payment_id: uuid.UUID, reason: str, user_id: uuid.UUID | None
) -> PaymentOutcome:
    if not reason or not reason.strip():
        raise BillingError("a void reason is required", 422)
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise BillingError("payment not found", 404)
    lock_account(db, payment.billing_account_id)
    db.refresh(payment)
    if payment.status == "VOID":
        raise BillingError("payment is already void", 409)

    original = db.scalar(
        select(LedgerEntry).where(
            LedgerEntry.ref_type == "PAYMENT", LedgerEntry.ref_id == payment.id,
            LedgerEntry.entry_type == "PAYMENT",
        )
    )
    payment.status = "VOID"
    payment.void_reason = reason.strip()
    payment.voided_by = user_id
    payment.voided_at = datetime.now(UTC)
    receipt = db.scalar(select(Receipt).where(Receipt.payment_id == payment.id))
    if receipt:
        receipt.status = "VOID"
    _ledger(
        db, account_id=payment.billing_account_id, entry_type="PAYMENT_REVERSAL",
        amount=payment.amount, user_id=user_id, effective_date=local_today(),
        description=f"Void: {reason.strip()}", ref_type="PAYMENT", ref_id=payment.id,
        connection_id=payment.connection_id, reverses=original.id if original else None,
    )
    db.flush()
    return _outcome(db, payment, replay=False)


# ---------------------------------------------------------------- adjustments / refunds


def post_adjustment(
    db: Session, *, customer_id: uuid.UUID, amount, reason: str, user_id: uuid.UUID | None,
    connection_id: uuid.UUID | None = None,
) -> LedgerEntry:
    amount = money(amount)
    if amount == ZERO:
        raise BillingError("adjustment amount cannot be zero", 422)
    if not reason or not reason.strip():
        raise BillingError("an adjustment reason is required", 422)
    acct = lock_account(db, get_or_create_account(db, customer_id).id)
    _check_connection(db, customer_id, connection_id)
    entry = _ledger(
        db, account_id=acct.id, entry_type="ADJUSTMENT", amount=amount, user_id=user_id,
        effective_date=local_today(), description=reason.strip(), ref_type="ADJUSTMENT",
        connection_id=connection_id,
    )
    db.flush()
    return entry


def issue_refund(
    db: Session, *, customer_id: uuid.UUID, amount, reason: str, user_id: uuid.UUID | None
) -> LedgerEntry:
    amount = money(amount)
    if amount <= ZERO:
        raise BillingError("refund amount must be positive", 422)
    if not reason or not reason.strip():
        raise BillingError("a refund reason is required", 422)
    acct = lock_account(db, get_or_create_account(db, customer_id).id)
    credit = -balance(db, acct.id)
    if amount > credit:
        raise BillingError(
            f"refund exceeds the customer's available credit ({max(credit, ZERO)})", 409
        )
    entry = _ledger(
        db, account_id=acct.id, entry_type="REFUND", amount=amount, user_id=user_id,
        effective_date=local_today(), description=reason.strip(), ref_type="REFUND",
    )
    db.flush()
    return entry


def statement(db: Session, customer_id: uuid.UUID, recent: int = 50) -> dict:
    acct = get_or_create_account(db, customer_id)
    bal = balance(db, acct.id)
    today = local_today()
    open_rows = []
    for inv, paid in open_invoices(db, acct.id):
        open_rows.append(
            {
                "invoice": inv, "paid": paid, "outstanding": inv.total - paid,
                "status": derive_invoice_status(inv.total, paid, inv.due_date, today),
            }
        )
    entries = list(
        db.scalars(
            select(LedgerEntry)
            .where(LedgerEntry.billing_account_id == acct.id)
            .order_by(LedgerEntry.posted_at.desc(), LedgerEntry.id.desc())
            .limit(recent)
        )
    )
    return {
        "customer_id": customer_id,
        "balance": bal,
        "amount_due": max(bal, ZERO),
        "credit": max(-bal, ZERO),
        "open_invoices": open_rows,
        "recent_entries": entries,
    }
