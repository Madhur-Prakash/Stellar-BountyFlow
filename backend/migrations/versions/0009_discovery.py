"""discovery: saved searches with alerts and skill-graph recommendations

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-29
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_CHECK = "ck_notifications_notification_type"
SAVED_SEARCH_MATCH = "SAVED_SEARCH_MATCH"


def _notification_types() -> list[str]:
    """The values the notification_type CHECK allows right now. Read from the database rather than hard-coded, so
    this migration only adds its own value and keeps whatever other migrations allow."""
    definition = (
        op.get_bind()
        .execute(
            sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
            {"name": NOTIFICATION_CHECK},
        )
        .scalar()
    )
    return re.findall(r"'([A-Z_]+)'", definition or "")


def _set_notification_types(values: list[str]) -> None:
    # The name is already rendered, so it goes through op.f(): a bare string would have the metadata naming
    # convention applied a second time (ck_notifications_ck_notifications_notification_type).
    op.drop_constraint(op.f(NOTIFICATION_CHECK), "notifications", type_="check")
    allowed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(op.f(NOTIFICATION_CHECK), "notifications", f"notification_type IN ({allowed})")


def upgrade() -> None:
    op.create_table(
        "saved_searches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "alert_frequency",
            sa.Enum("INSTANT", "DAILY", "WEEKLY", "OFF", name="saved_search_alert_frequency", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("notify_in_app", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notify_email", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_paused", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("next_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_digest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "alert_frequency IN ('INSTANT', 'DAILY', 'WEEKLY', 'OFF')",
            name=op.f("ck_saved_searches_saved_search_alert_frequency"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_saved_searches_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_searches")),
    )
    op.create_index(op.f("ix_saved_searches_user_id"), "saved_searches", ["user_id"], unique=False)
    op.create_index(
        "ix_saved_searches_digest_due", "saved_searches", ["alert_frequency", "next_digest_at"], unique=False
    )

    op.create_table(
        "saved_search_matches",
        sa.Column("saved_search_id", sa.UUID(), nullable=False),
        sa.Column("bounty_id", sa.UUID(), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("trigger_event", sa.String(length=64), nullable=False),
        sa.Column("source_event_id", sa.UUID(), nullable=True),
        sa.Column(
            "delivery",
            sa.Enum(
                "PENDING", "ALERTED", "DIGESTED", "SKIPPED",
                name="saved_search_match_delivery", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "delivery IN ('PENDING', 'ALERTED', 'DIGESTED', 'SKIPPED')",
            name=op.f("ck_saved_search_matches_saved_search_match_delivery"),
        ),
        sa.ForeignKeyConstraint(
            ["bounty_id"], ["bounties.id"], name=op.f("fk_saved_search_matches_bounty_id_bounties"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["saved_search_id"],
            ["saved_searches.id"],
            name=op.f("fk_saved_search_matches_saved_search_id_saved_searches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("saved_search_id", "bounty_id", name=op.f("pk_saved_search_matches")),
    )
    op.create_index(op.f("ix_saved_search_matches_bounty_id"), "saved_search_matches", ["bounty_id"], unique=False)
    # "New since you last looked" counts matches of one search after a timestamp.
    op.create_index(
        "ix_saved_search_matches_search_matched",
        "saved_search_matches",
        ["saved_search_id", "matched_at"],
        unique=False,
    )
    # The digest job reads only the undelivered matches of the searches that are due; most rows are delivered, so
    # the index is partial.
    op.create_index(
        "ix_saved_search_matches_pending",
        "saved_search_matches",
        ["saved_search_id", "matched_at"],
        unique=False,
        postgresql_where=sa.text("delivery = 'PENDING'"),
    )

    op.create_table(
        "skill_nodes",
        sa.Column("skill", sa.String(length=40), nullable=False),
        sa.Column("doc_count", sa.Integer(), nullable=False),
        sa.Column("bounty_forms", postgresql.ARRAY(sa.String(length=40)), server_default="{}", nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("skill", name=op.f("pk_skill_nodes")),
    )
    op.create_table(
        "skill_edges",
        sa.Column("skill", sa.String(length=40), nullable=False),
        sa.Column("related", sa.String(length=40), nullable=False),
        sa.Column("co_count", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("skill", "related", name=op.f("pk_skill_edges")),
    )

    # Recommendation candidates are found by the normalised skill name ("JS" and "javascript" are one key), so
    # the plain indexes on skill_name / tag cannot serve them. These expression indexes match the SQL the
    # candidate query emits (app/modules/discovery/recommendations.py::_normalised_name).
    for name, table, column in (
        ("ix_bounty_skills_normalized", "bounty_skills", "skill_name"),
        ("ix_bounty_tags_normalized", "bounty_tags", "tag"),
        ("ix_user_skills_normalized", "user_skills", "skill_name"),
    ):
        op.execute(
            sa.text(
                f"CREATE INDEX {name} ON {table} "
                f"(regexp_replace(lower(btrim({column})), '[\\s_-]+', ' ', 'g'))"
            )
        )

    allowed = _notification_types()
    if allowed and SAVED_SEARCH_MATCH not in allowed:
        _set_notification_types([*allowed, SAVED_SEARCH_MATCH])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM notifications WHERE notification_type = :t").bindparams(t=SAVED_SEARCH_MATCH))
    allowed = _notification_types()
    if SAVED_SEARCH_MATCH in allowed:
        _set_notification_types([v for v in allowed if v != SAVED_SEARCH_MATCH])
    for name in ("ix_user_skills_normalized", "ix_bounty_tags_normalized", "ix_bounty_skills_normalized"):
        op.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
    op.drop_table("skill_edges")
    op.drop_table("skill_nodes")
    op.drop_index("ix_saved_search_matches_pending", table_name="saved_search_matches")
    op.drop_index("ix_saved_search_matches_search_matched", table_name="saved_search_matches")
    op.drop_index(op.f("ix_saved_search_matches_bounty_id"), table_name="saved_search_matches")
    op.drop_table("saved_search_matches")
    op.drop_index("ix_saved_searches_digest_due", table_name="saved_searches")
    op.drop_index(op.f("ix_saved_searches_user_id"), table_name="saved_searches")
    op.drop_table("saved_searches")
