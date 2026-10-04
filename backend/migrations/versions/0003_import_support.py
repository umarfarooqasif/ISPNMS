"""keep the source system's recharge date on the connection

Revision ID: 0003
Revises: 0002

The Wasooli export has a "Recharge Date" column whose exact meaning (last recharge vs next due
date) has not been confirmed. It is stored unchanged under a neutral name so Phase 3 billing can
decide how to use it without re-importing.
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("connections", sa.Column("source_recharge_date", sa.Date(), nullable=True))



def downgrade() -> None:
    op.drop_column("connections", "source_recharge_date")
