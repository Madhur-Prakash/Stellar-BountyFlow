"""collaboration: threaded bounty Q&A and GitHub pull request verification

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOTIFICATION_TYPES = ("QUESTION_RECEIVED", "QUESTION_REPLY", "ANSWER_ACCEPTED", "PULL_REQUEST_UPDATE")
REPORT_TARGETS = ("QA_POST",)

PR_VERIFICATION = (
    "PENDING",
    "VERIFIED",
    "NOT_FOUND",
    "REPO_MISMATCH",
    "AUTHOR_MISMATCH",
    "AUTHOR_NOT_LINKED",
    "UNAVAILABLE",
)
PR_STATE = ("OPEN", "CLOSED", "MERGED")
PR_CHECKS = ("SUCCESS", "FAILURE", "PENDING", "NONE")
LINK_METHODS = ("GIST", "OAUTH")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _enum(values: Sequence[str], name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def _enum_checks(table: str, column: str) -> list[tuple[str, list[str]]]:
    """The CHECK constraints on ``table`` that list the allowed values of ``column``, with those values. Found by
    column rather than by name, so values added by other migrations are kept whatever they named the constraint."""
    rows = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype = 'c'"
            ),
            {"table": table},
        )
        .all()
    )
    return [
        (name, re.findall(r"'([A-Z_]+)'", definition))
        for name, definition in rows
        if re.search(rf"\b{column}\b", definition) and "'" in definition
    ]


def _set_allowed(
    table: str, column: str, constraint: str, add: Sequence[str] = (), remove: Sequence[str] = ()
) -> None:
    existing = _enum_checks(table, column)
    allowed: list[str] = []
    for _, values in existing:
        allowed += [v for v in values if v not in allowed]
    allowed = [v for v in allowed if v not in remove] + [v for v in add if v not in allowed]
    for name, _ in existing:
        op.execute(sa.text(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"'))
    op.create_check_constraint(op.f(constraint), table, _in(column, allowed))


def upgrade() -> None:
    # --- Bounty setting -------------------------------------------------------------------------
    op.add_column(
        "bounties", sa.Column("require_merged_pr", sa.Boolean(), server_default="false", nullable=False)
    )

    # --- Q&A --------------------------------------------------------------------------------------
    op.create_table(
        "bounty_qa_posts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("bounty_id", sa.UUID(), nullable=False),
        sa.Column("author_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_pinned", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_accepted", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("upvotes_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_by_id", sa.UUID(), nullable=True),
        sa.Column("hidden_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "parent_id IS NULL OR NOT is_pinned", name=op.f("ck_bounty_qa_posts_replies_not_pinned")
        ),
        sa.CheckConstraint(
            "parent_id IS NOT NULL OR NOT is_accepted", name=op.f("ck_bounty_qa_posts_questions_not_accepted")
        ),
        sa.CheckConstraint("upvotes_count >= 0", name=op.f("ck_bounty_qa_posts_upvotes_non_negative")),
        sa.ForeignKeyConstraint(
            ["bounty_id"],
            ["bounties.id"],
            name=op.f("fk_bounty_qa_posts_bounty_id_bounties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name=op.f("fk_bounty_qa_posts_author_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["bounty_qa_posts.id"],
            name=op.f("fk_bounty_qa_posts_parent_id_bounty_qa_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["hidden_by_id"],
            ["users.id"],
            name=op.f("fk_bounty_qa_posts_hidden_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bounty_qa_posts")),
    )
    op.create_index(op.f("ix_bounty_qa_posts_bounty_id"), "bounty_qa_posts", ["bounty_id"], unique=False)
    op.create_index(op.f("ix_bounty_qa_posts_author_id"), "bounty_qa_posts", ["author_id"], unique=False)
    op.create_index(op.f("ix_bounty_qa_posts_parent_id"), "bounty_qa_posts", ["parent_id"], unique=False)
    op.create_index(
        "ix_bounty_qa_posts_bounty_thread",
        "bounty_qa_posts",
        ["bounty_id", "parent_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_bounty_qa_posts_visible_questions",
        "bounty_qa_posts",
        ["bounty_id"],
        unique=False,
        postgresql_where=sa.text("parent_id IS NULL AND deleted_at IS NULL AND hidden_at IS NULL"),
    )
    op.create_index(
        "uq_bounty_qa_posts_accepted_reply",
        "bounty_qa_posts",
        ["parent_id"],
        unique=True,
        postgresql_where=sa.text("is_accepted"),
    )

    op.create_table(
        "bounty_qa_votes",
        sa.Column("post_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["bounty_qa_posts.id"],
            name=op.f("fk_bounty_qa_votes_post_id_bounty_qa_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_bounty_qa_votes_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("post_id", "user_id", name=op.f("pk_bounty_qa_votes")),
    )
    op.create_index(op.f("ix_bounty_qa_votes_user_id"), "bounty_qa_votes", ["user_id"], unique=False)

    # --- GitHub -----------------------------------------------------------------------------------
    op.create_table(
        "github_accounts",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("login", sa.String(length=39), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("method", _enum(LINK_METHODS, "github_link_method"), nullable=False),
        sa.Column("proof_url", sa.String(length=500), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_in("method", LINK_METHODS), name=op.f("ck_github_accounts_github_link_method")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_github_accounts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_github_accounts")),
        sa.UniqueConstraint("github_id", name=op.f("uq_github_accounts_github_id")),
    )

    op.create_table(
        "submission_pull_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("submission_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("repo_owner", sa.String(length=100), nullable=False),
        sa.Column("repo_name", sa.String(length=100), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("verification", _enum(PR_VERIFICATION, "pr_verification"), nullable=False),
        sa.Column("state", _enum(PR_STATE, "pr_state"), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("author_login", sa.String(length=39), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("base_repo", sa.String(length=200), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("head_sha", sa.String(length=40), nullable=True),
        sa.Column("checks", _enum(PR_CHECKS, "pr_checks_status"), nullable=True),
        sa.Column("checks_passed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checks_failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("checks_pending", sa.Integer(), server_default="0", nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            _in("verification", PR_VERIFICATION), name=op.f("ck_submission_pull_requests_pr_verification")
        ),
        sa.CheckConstraint(_in("state", PR_STATE), name=op.f("ck_submission_pull_requests_pr_state")),
        sa.CheckConstraint(
            _in("checks", PR_CHECKS), name=op.f("ck_submission_pull_requests_pr_checks_status")
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["bounty_submissions.id"],
            name=op.f("fk_submission_pull_requests_submission_id_bounty_submissions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submission_pull_requests")),
        sa.UniqueConstraint(
            "submission_id", "repo_owner", "repo_name", "number", name=op.f("uq_submission_pull_requests_pr")
        ),
    )
    op.create_index(
        op.f("ix_submission_pull_requests_submission_id"),
        "submission_pull_requests",
        ["submission_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_submission_pull_requests_head_sha"), "submission_pull_requests", ["head_sha"], unique=False
    )
    op.create_index(
        "ix_submission_pull_requests_repo_number",
        "submission_pull_requests",
        ["repo_owner", "repo_name", "number"],
        unique=False,
    )
    op.create_index(
        "ix_submission_pull_requests_next_check_at",
        "submission_pull_requests",
        ["next_check_at"],
        unique=False,
    )

    # --- Shared enums: new notification types and a new report target -----------------------------------
    _set_allowed(
        "notifications", "notification_type", "ck_notifications_notification_type", add=NOTIFICATION_TYPES
    )
    _set_allowed("user_reports", "target_type", "ck_user_reports_report_target", add=REPORT_TARGETS)


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM notifications WHERE notification_type IN :types").bindparams(
            sa.bindparam("types", value=list(NOTIFICATION_TYPES), expanding=True)
        )
    )
    op.execute(
        sa.text("DELETE FROM user_reports WHERE target_type IN :targets").bindparams(
            sa.bindparam("targets", value=list(REPORT_TARGETS), expanding=True)
        )
    )
    _set_allowed("user_reports", "target_type", "ck_user_reports_report_target", remove=REPORT_TARGETS)
    _set_allowed(
        "notifications", "notification_type", "ck_notifications_notification_type", remove=NOTIFICATION_TYPES
    )

    op.drop_index("ix_submission_pull_requests_next_check_at", table_name="submission_pull_requests")
    op.drop_index("ix_submission_pull_requests_repo_number", table_name="submission_pull_requests")
    op.drop_index(op.f("ix_submission_pull_requests_head_sha"), table_name="submission_pull_requests")
    op.drop_index(op.f("ix_submission_pull_requests_submission_id"), table_name="submission_pull_requests")
    op.drop_table("submission_pull_requests")
    op.drop_table("github_accounts")
    op.drop_index(op.f("ix_bounty_qa_votes_user_id"), table_name="bounty_qa_votes")
    op.drop_table("bounty_qa_votes")
    op.drop_index("uq_bounty_qa_posts_accepted_reply", table_name="bounty_qa_posts")
    op.drop_index("ix_bounty_qa_posts_visible_questions", table_name="bounty_qa_posts")
    op.drop_index("ix_bounty_qa_posts_bounty_thread", table_name="bounty_qa_posts")
    op.drop_index(op.f("ix_bounty_qa_posts_parent_id"), table_name="bounty_qa_posts")
    op.drop_index(op.f("ix_bounty_qa_posts_author_id"), table_name="bounty_qa_posts")
    op.drop_index(op.f("ix_bounty_qa_posts_bounty_id"), table_name="bounty_qa_posts")
    op.drop_table("bounty_qa_posts")
    op.drop_column("bounties", "require_merged_pr")
