"""remove the simulated development chain: BountyFlow runs on real Stellar networks only

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES_WITH_FLAG = ("wallets", "bounty_escrows", "blockchain_transactions", "payment_records")


def upgrade() -> None:
    # Any rows produced by the removed development adapter are not real chain activity.
    op.execute("DELETE FROM payment_records WHERE is_simulated")
    op.execute("DELETE FROM blockchain_transactions WHERE is_simulated")
    op.execute("DELETE FROM bounty_escrows WHERE is_simulated")
    op.execute("DELETE FROM wallets WHERE is_simulated")
    for table in _TABLES_WITH_FLAG:
        op.drop_column(table, "is_simulated")
    op.drop_table("simulated_ledger_entries")


def downgrade() -> None:
    op.create_table(
        "simulated_ledger_entries",
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_simulated_ledger_entries")),
    )
    for table in _TABLES_WITH_FLAG:
        op.add_column(
            table, sa.Column("is_simulated", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
