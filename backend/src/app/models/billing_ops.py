"""Billing operations: bill runs, late fees, opening balances.

Invoices, lines and ledger rows stay append-only (Phase 1). These tables only record *why* and
*when* the billing engine produced them, and give the engine its idempotency guarantees.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core import constants as C
from app.models.base import Base, Money, uuid_pk
from app.models.masters import _in


class BillingRun(Base):
    """One execution of the monthly bill run or the late-fee run (previews are never stored)."""

    __tablename__ = "billing_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    params: Mapped[dict | None] = mapped_column(JSONB)
    invoices_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_billed: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0)
    summary: Mapped[dict | None] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint(_in("kind", C.BILLING_RUN_KINDS), name="kind"),)


class BillingRunItem(Base):
    """What a run did for one connection/customer. Nothing a run skips or fails is silent."""

    __tablename__ = "billing_run_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("billing_runs.id"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("connections.id"))
    cycle_due_date: Mapped[date | None] = mapped_column(Date)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("invoices.id"))
    message: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("outcome", C.BILLING_RUN_ITEM_OUTCOMES), name="outcome"),
        # The database itself refuses to invoice the same connection cycle twice.
        Index(
            "uq_billing_run_items_invoiced_cycle", "connection_id", "cycle_due_date",
            unique=True, postgresql_where=text("outcome = 'INVOICED'"),
        ),
    )


class LateFee(Base):
    """A late fee was charged for this invoice. UNIQUE(invoice_id): at most one fee per invoice."""

    __tablename__ = "late_fees"

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id"), unique=True, nullable=False
    )
    fee_invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("billing_runs.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)

    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)


class OpeningBalance(Base):
    """Optional starting balance (amount owed) carried over from the old system. One per customer."""

    __tablename__ = "opening_balances"

    id: Mapped[uuid.UUID] = uuid_pk()
    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id"), unique=True, nullable=False
    )
    # Becomes a normal invoice, so payments allocate against it like any other.
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)
