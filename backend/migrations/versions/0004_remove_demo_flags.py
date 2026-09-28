"""remove demo flags: seeded accounts and bounties are ordinary records

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("bounties", "is_demo")
    op.drop_column("users", "is_demo")


def downgrade() -> None:
    op.add_column("users", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("bounties", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")))
