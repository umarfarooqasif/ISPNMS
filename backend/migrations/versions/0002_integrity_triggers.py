"""sequences, trigram indexes, and database-level immutability rules

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SEQUENCES = ["customer_code_seq", "connection_code_seq", "invoice_number_seq", "receipt_number_seq"]

# Tables where rows may never be updated or deleted (financial history, audit trail).
APPEND_ONLY = ["ledger_entries", "audit_logs", "payment_allocations", "invoice_lines", "invoices"]
# Tables where rows may never be deleted (master/financial records are archived, not removed).
NO_DELETE = ["payments", "receipts", "billing_accounts", "customers", "connections"]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    for seq in SEQUENCES:
        op.execute(f"CREATE SEQUENCE {seq} START 1")

    # Fuzzy name/address matching for duplicate detection and search.
    op.execute("CREATE INDEX ix_customers_full_name_trgm ON customers USING gin (full_name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_customers_address_trgm ON customers USING gin (address gin_trgm_ops)")

    op.execute(
        """
        CREATE FUNCTION forbid_update_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% on % is not allowed: table is append-only', TG_OP, TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION forbid_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'DELETE on % is not allowed: archive/void instead', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for t in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} "
            f"FOR EACH ROW EXECUTE FUNCTION forbid_update_delete()"
        )
    for t in NO_DELETE:
        op.execute(
            f"CREATE TRIGGER {t}_no_delete BEFORE DELETE ON {t} "
            f"FOR EACH ROW EXECUTE FUNCTION forbid_delete()"
        )

    # A payment's money fields are immutable; only its status/void metadata may change, one way.
    op.execute(
        """
        CREATE FUNCTION payments_guard() RETURNS trigger AS $$
        BEGIN
            IF NEW.amount <> OLD.amount
               OR NEW.billing_account_id <> OLD.billing_account_id
               OR NEW.method <> OLD.method
               OR NEW.collected_at <> OLD.collected_at
               OR NEW.collector_id IS DISTINCT FROM OLD.collector_id
               OR NEW.client_txn_id IS DISTINCT FROM OLD.client_txn_id
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
    )
    op.execute(
        "CREATE TRIGGER payments_guard_update BEFORE UPDATE ON payments "
        "FOR EACH ROW EXECUTE FUNCTION payments_guard()"
    )

    op.execute(
        """
        CREATE FUNCTION receipts_guard() RETURNS trigger AS $$
        BEGIN
            IF NEW.receipt_number <> OLD.receipt_number OR NEW.payment_id <> OLD.payment_id THEN
                RAISE EXCEPTION 'receipt number/payment are immutable' USING ERRCODE = 'restrict_violation';
            END IF;
            IF OLD.status = 'VOID' AND NEW.status <> 'VOID' THEN
                RAISE EXCEPTION 'a void receipt cannot be reinstated' USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER receipts_guard_update BEFORE UPDATE ON receipts "
        "FOR EACH ROW EXECUTE FUNCTION receipts_guard()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS receipts_guard_update ON receipts")
    op.execute("DROP FUNCTION IF EXISTS receipts_guard()")
    op.execute("DROP TRIGGER IF EXISTS payments_guard_update ON payments")
    op.execute("DROP FUNCTION IF EXISTS payments_guard()")
    for t in NO_DELETE:
        op.execute(f"DROP TRIGGER IF EXISTS {t}_no_delete ON {t}")
    for t in APPEND_ONLY:
        op.execute(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t}")
    op.execute("DROP FUNCTION IF EXISTS forbid_delete()")
    op.execute("DROP FUNCTION IF EXISTS forbid_update_delete()")
    op.execute("DROP INDEX IF EXISTS ix_customers_address_trgm")
    op.execute("DROP INDEX IF EXISTS ix_customers_full_name_trgm")
    for seq in SEQUENCES:
        op.execute(f"DROP SEQUENCE IF EXISTS {seq}")
    # pg_trgm is intentionally left installed (it may be shared with other databases' tooling).
