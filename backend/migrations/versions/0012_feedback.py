"""feedback: notes sent from the floating form, and the staff queue that reads them

One table. A note keeps its sender (a user id, or an address a signed-out sender chose to leave), the route and
window size the form declared it was capturing, and the User-Agent of the request. No IP address is stored.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FEEDBACK_KIND = ("BUG", "IDEA", "PRAISE", "OTHER")
FEEDBACK_STATUS = ("NEW", "HANDLED")


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def _check(table: str, column: str, name: str, *values: str) -> sa.CheckConstraint:
    listed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({listed})", name=op.f(f"ck_{table}_{name}"))


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("kind", _enum("feedback_kind", *FEEDBACK_KIND), nullable=False),
        sa.Column("status", _enum("feedback_status", *FEEDBACK_STATUS), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("path", sa.String(length=200), nullable=True),
        sa.Column("viewport_width", sa.Integer(), nullable=True),
        sa.Column("viewport_height", sa.Integer(), nullable=True),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("handled_by_id", sa.UUID(), nullable=True),
        sa.Column("handled_note", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _check("feedback", "kind", "feedback_kind", *FEEDBACK_KIND),
        _check("feedback", "status", "feedback_status", *FEEDBACK_STATUS),
        # A closed account's note stays readable, without its author.
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_feedback_user_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["handled_by_id"],
            ["users.id"],
            name=op.f("fk_feedback_handled_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )
    op.create_index(op.f("ix_feedback_user_id"), "feedback", ["user_id"], unique=False)
    # The queue is always newest first: unfiltered, filtered by status, filtered by kind.
    op.create_index("ix_feedback_created", "feedback", ["created_at"], unique=False)
    op.create_index("ix_feedback_status_created", "feedback", ["status", "created_at"], unique=False)
    op.create_index("ix_feedback_kind_created", "feedback", ["kind", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_feedback_kind_created", table_name="feedback")
    op.drop_index("ix_feedback_status_created", table_name="feedback")
    op.drop_index("ix_feedback_created", table_name="feedback")
    op.drop_index(op.f("ix_feedback_user_id"), table_name="feedback")
    op.drop_table("feedback")
