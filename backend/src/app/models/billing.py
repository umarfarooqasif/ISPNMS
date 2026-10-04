import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core import constants as C
from app.models.base import Base, Money, TimestampMixin, uuid_pk
from app.models.masters import _in


class BillingAccount(Base, TimestampMixin):
    """One per customer. The balance is SUM(ledger_entries), never a stored column."""

    __tablename__ = "billing_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), unique=True, nullable=False
    )


class LedgerEntry(Base):
    """Append-only (enforced by DB trigger). Positive = customer owes, negative = credit/payment."""

    __tablename__ = "ledger_entries"

    id: Mapped[uuid.UUID] = uuid_pk()
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billing_accounts.id"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connections.id"))
    entry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    ref_type: Mapped[str | None] = mapped_column(String(24))
    ref_id: Mapped[uuid.UUID | None] = mapped_column()
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    posted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reverses_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ledger_entries.id"), unique=True
    )

    __table_args__ = (
        CheckConstraint(_in("entry_type", C.LEDGER_ENTRY_TYPES), name="entry_type"),
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        Index("ix_ledger_entries_ref", "ref_type", "ref_id"),
    )


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billing_accounts.id"), nullable=False
    )
    period: Mapped[date | None] = mapped_column(Date)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    lines: Mapped[list["InvoiceLine"]] = relationship(lazy="selectin", order_by="InvoiceLine.id")

    __table_args__ = (
        CheckConstraint("total >= 0", name="total_non_negative"),
        CheckConstraint("due_date >= issue_date", name="due_after_issue"),
        Index("ix_invoices_account_due", "billing_account_id", "due_date"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connections.id"))
    charge_type: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)

    __table_args__ = (
        CheckConstraint(_in("charge_type", C.CHARGE_TYPES), name="charge_type"),
        CheckConstraint(
            "(charge_type = 'DISCOUNT' AND amount <= 0) OR (charge_type <> 'DISCOUNT' AND amount >= 0)",
            name="sign_matches_type",
        ),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = uuid_pk()
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billing_accounts.id"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connections.id"))
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    collector_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("collectors.id"), index=True)
    client_txn_id: Mapped[str | None] = mapped_column(String(64))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="POSTED")
    notes: Mapped[str | None] = mapped_column(Text)
    void_reason: Mapped[str | None] = mapped_column(Text)
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    receipt: Mapped["Receipt | None"] = relationship(back_populates="payment", uselist=False)
    allocations: Mapped[list["PaymentAllocation"]] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(_in("method", C.PAYMENT_METHODS), name="method"),
        CheckConstraint(_in("status", C.PAYMENT_STATUSES), name="status"),
        # Idempotency for offline sync: same collector + same client txn id = same payment.
        UniqueConstraint("collector_id", "client_txn_id"),
    )


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"

    id: Mapped[uuid.UUID] = uuid_pk()
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)

    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = uuid_pk()
    receipt_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("payments.id"), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ISSUED")
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    issued_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))

    payment: Mapped[Payment] = relationship(back_populates="receipt")

    __table_args__ = (CheckConstraint(_in("status", C.RECEIPT_STATUSES), name="status"),)
