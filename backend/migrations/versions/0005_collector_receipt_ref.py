"""offline receipts: keep the receipt number the phone printed before sync

Revision ID: 0005
Revises: 0004

A collector can print a provisional receipt while offline. The number printed on the paper is stored
on the payment when it syncs, so the paper receipt can always be matched to the permanent record.
It is unique per collector and immutable like the other payment identity fields.
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_GUARD = """
CREATE OR REPLACE FUNCTION payments_guard() RETURNS trigger AS $$
BEGIN
    IF NEW.amount <> OLD.amount
       OR NEW.billing_account_id <> OLD.billing_account_id
       OR NEW.method <> OLD.method
       OR NEW.collected_at <> OLD.collected_at
       OR NEW.collector_id IS DISTINCT FROM OLD.collector_id
       OR NEW.client_txn_id IS DISTINCT FROM OLD.client_txn_id
       {extra}
       OR NEW.connection_id IS DISTINCT FROM OLD.connection_id THEN
        RAISE EXCEPTION 'payment money fields are immutable' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.status = 'VOID' AND NEW.status <> 'VOID' THEN
        RAISE EXCEPTION 'a voided payment cannot be reinstated' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    op.add_column("payments", sa.Column("client_receipt_no", sa.String(length=40), nullable=True))
    op.create_unique_constraint(
        op.f("uq_payments_collector_receipt"), "payments", ["collector_id", "client_receipt_no"]
    )
    op.execute(_GUARD.format(extra="OR NEW.client_receipt_no IS DISTINCT FROM OLD.client_receipt_no"))


def downgrade() -> None:
    op.execute(_GUARD.format(extra=""))
    op.drop_constraint(op.f("uq_payments_collector_receipt"), "payments", type_="unique")
    op.drop_column("payments", "client_receipt_no")
