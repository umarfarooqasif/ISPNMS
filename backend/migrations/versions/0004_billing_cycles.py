"""billing cycles: next due date, bill runs, late fees, opening balances

Revision ID: 0004
Revises: 0003

The Wasooli "Recharge Date" is the NEXT DUE DATE (confirmed by the ISP owner). It becomes
connections.next_due_date, which drives monthly billing. billing_day is widened to 1-31 and is
back-filled from the due date so month-end customers stay on their day.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("next_due_date", sa.Date(), nullable=True))
    op.create_index(op.f("ix_connections_next_due_date"), "connections", ["next_due_date"], unique=False)
    op.execute("UPDATE connections SET next_due_date = source_recharge_date WHERE source_recharge_date IS NOT NULL")
    op.execute(
        "UPDATE connections SET billing_day = EXTRACT(DAY FROM next_due_date)::smallint "
        "WHERE billing_day IS NULL AND next_due_date IS NOT NULL"
    )
    # Raw SQL: the project's naming convention would otherwise be applied to the name a second time.
    op.execute("ALTER TABLE connections DROP CONSTRAINT ck_connections_billing_day")
    op.execute(
        "ALTER TABLE connections ADD CONSTRAINT ck_connections_billing_day "
        "CHECK (billing_day IS NULL OR billing_day BETWEEN 1 AND 31)"
    )

    op.create_table(
        "billing_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("invoices_created", sa.Integer(), nullable=False),
        sa.Column("total_billed", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('MONTHLY', 'LATE_FEES')", name=op.f("ck_billing_runs_kind")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_billing_runs_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_runs")),
    )
    op.create_table(
        "billing_run_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("cycle_due_date", sa.Date(), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('INVOICED', 'FREE_SKIPPED', 'ZERO_PRICE', 'CYCLES_SKIPPED', 'NO_DUE_DATE', 'LATE_FEE', 'ERROR')",
            name=op.f("ck_billing_run_items_outcome"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["billing_runs.id"], name=op.f("fk_billing_run_items_run_id_billing_runs")),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name=op.f("fk_billing_run_items_customer_id_customers")),
        sa.ForeignKeyConstraint(["connection_id"], ["connections.id"], name=op.f("fk_billing_run_items_connection_id_connections")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_billing_run_items_invoice_id_invoices")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_run_items")),
    )
    op.create_index(op.f("ix_billing_run_items_run_id"), "billing_run_items", ["run_id"], unique=False)
    op.create_index(op.f("ix_billing_run_items_customer_id"), "billing_run_items", ["customer_id"], unique=False)
    op.create_index(
        "uq_billing_run_items_invoiced_cycle", "billing_run_items", ["connection_id", "cycle_due_date"],
        unique=True, postgresql_where=sa.text("outcome = 'INVOICED'"),
    )
    op.create_table(
        "late_fees",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("fee_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_late_fees_amount_positive")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_late_fees_invoice_id_invoices")),
        sa.ForeignKeyConstraint(["fee_invoice_id"], ["invoices.id"], name=op.f("fk_late_fees_fee_invoice_id_invoices")),
        sa.ForeignKeyConstraint(["run_id"], ["billing_runs.id"], name=op.f("fk_late_fees_run_id_billing_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_late_fees")),
        sa.UniqueConstraint("invoice_id", name=op.f("uq_late_fees_invoice_id")),
    )
    op.create_table(
        "opening_balances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_opening_balances_amount_positive")),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name=op.f("fk_opening_balances_customer_id_customers")),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], name=op.f("fk_opening_balances_invoice_id_invoices")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_opening_balances_created_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opening_balances")),
        sa.UniqueConstraint("customer_id", name=op.f("uq_opening_balances_customer_id")),
    )


def downgrade() -> None:
    op.drop_table("opening_balances")
    op.drop_table("late_fees")
    op.drop_table("billing_run_items")
    op.drop_table("billing_runs")
    # Restoring the old 1-28 limit would fail on rows using 29-31, so clamp them first.
    op.execute("UPDATE connections SET billing_day = 28 WHERE billing_day > 28")
    op.execute("ALTER TABLE connections DROP CONSTRAINT ck_connections_billing_day")
    op.execute(
        "ALTER TABLE connections ADD CONSTRAINT ck_connections_billing_day "
        "CHECK (billing_day IS NULL OR billing_day BETWEEN 1 AND 28)"
    )
    op.drop_index(op.f("ix_connections_next_due_date"), table_name="connections")
    op.drop_column("connections", "next_due_date")
