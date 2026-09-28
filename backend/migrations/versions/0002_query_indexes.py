"""query indexes: dispute contributor lookups and marketplace newest-first sort

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_disputes_contributor_id", "disputes", ["contributor_id"])
    op.create_index(
        "ix_bounties_listed_at",
        "bounties",
        [sa.text("coalesce(published_at, created_at) DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_bounties_listed_at", table_name="bounties")
    op.drop_index("ix_disputes_contributor_id", table_name="disputes")
