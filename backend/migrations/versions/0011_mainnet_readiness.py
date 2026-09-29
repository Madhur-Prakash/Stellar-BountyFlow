"""mainnet readiness: compliance: data export and deletion requests, sanctions screening

Adds personal-data exports, account deletion requests, sanctions screening entries, and terms / privacy notice
versions with their acceptances. The versions of the terms and privacy notice already published on the site
("2026-09", in effect since the first release) are recorded as the baseline, so existing accounts are not asked to
accept them again.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-29
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASELINE_VERSION = "2026-09"
BASELINE_EFFECTIVE = datetime(2026, 9, 1, tzinfo=UTC)
BASELINE_IDS = {
    "TERMS": "6f1f3c1e-0d43-4c4b-9a55-2b1d7b0e9a01",
    "PRIVACY": "6f1f3c1e-0d43-4c4b-9a55-2b1d7b0e9a02",
}


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def _check(table: str, column: str, name: str, *values: str) -> sa.CheckConstraint:
    listed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({listed})", name=op.f(f"ck_{table}_{name}"))


EXPORT_STATUS = ("PENDING", "PROCESSING", "READY", "FAILED", "EXPIRED")
DELETION_STATUS = ("SCHEDULED", "CANCELLED", "COMPLETED")
SCREENING_SOURCE = ("LIST", "MANUAL")
LEGAL_DOCUMENT = ("TERMS", "PRIVACY")


def upgrade() -> None:
    op.create_table(
        "data_exports",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", _enum("export_status", *EXPORT_STATUS), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive", sa.LargeBinary(), nullable=True),
        sa.Column("archive_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("download_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _check("data_exports", "status", "export_status", *EXPORT_STATUS),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_data_exports_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_exports")),
    )
    op.create_index("ix_data_exports_status", "data_exports", ["status"], unique=False)
    op.create_index("ix_data_exports_user_created", "data_exports", ["user_id", "created_at"], unique=False)

    op.create_table(
        "account_deletion_requests",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", _enum("deletion_status", *DELETION_STATUS), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("pseudonym", sa.String(length=30), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _check("account_deletion_requests", "status", "deletion_status", *DELETION_STATUS),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_account_deletion_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_deletion_requests")),
    )
    op.create_index(
        op.f("ix_account_deletion_requests_user_id"), "account_deletion_requests", ["user_id"], unique=False
    )
    op.create_index(
        "ix_account_deletion_requests_status_due",
        "account_deletion_requests",
        ["status", "scheduled_for"],
        unique=False,
    )
    op.create_index(
        "uq_account_deletion_requests_one_scheduled",
        "account_deletion_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SCHEDULED'"),
    )

    op.create_table(
        "screening_entries",
        sa.Column("address", sa.String(length=56), nullable=False),
        sa.Column("source", _enum("screening_source", *SCREENING_SOURCE), nullable=False),
        sa.Column("list_name", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("added_by_id", sa.UUID(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_id", sa.UUID(), nullable=True),
        sa.Column("removal_note", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _check("screening_entries", "source", "screening_source", *SCREENING_SOURCE),
        sa.ForeignKeyConstraint(
            ["added_by_id"],
            ["users.id"],
            name=op.f("fk_screening_entries_added_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["removed_by_id"],
            ["users.id"],
            name=op.f("fk_screening_entries_removed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_screening_entries")),
    )
    op.create_index("ix_screening_entries_address", "screening_entries", ["address"], unique=False)
    op.create_index(
        "uq_screening_entries_active",
        "screening_entries",
        ["address", "source"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )

    op.create_table(
        "legal_document_versions",
        sa.Column("document", _enum("legal_document", *LEGAL_DOCUMENT), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by_id", sa.UUID(), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        _check("legal_document_versions", "document", "legal_document", *LEGAL_DOCUMENT),
        sa.ForeignKeyConstraint(
            ["published_by_id"],
            ["users.id"],
            name=op.f("fk_legal_document_versions_published_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["withdrawn_by_id"],
            ["users.id"],
            name=op.f("fk_legal_document_versions_withdrawn_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_document_versions")),
        sa.UniqueConstraint("document", "version", name="uq_legal_document_versions_document_version"),
    )
    op.create_index(
        "ix_legal_document_versions_document_effective",
        "legal_document_versions",
        ["document", "effective_at"],
        unique=False,
    )

    op.create_table(
        "legal_acceptances",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("document", _enum("legal_document", *LEGAL_DOCUMENT), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        _check("legal_acceptances", "document", "legal_document", *LEGAL_DOCUMENT),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_legal_acceptances_user_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["legal_document_versions.id"],
            name=op.f("fk_legal_acceptances_version_id_legal_document_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_acceptances")),
        sa.UniqueConstraint("user_id", "version_id", name="uq_legal_acceptances_user_version"),
    )
    op.create_index(op.f("ix_legal_acceptances_user_id"), "legal_acceptances", ["user_id"], unique=False)

    versions = sa.table(
        "legal_document_versions",
        sa.column("id", sa.UUID()),
        sa.column("document", sa.String()),
        sa.column("version", sa.String()),
        sa.column("summary", sa.Text()),
        sa.column("effective_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        versions,
        [
            {
                "id": BASELINE_IDS["TERMS"],
                "document": "TERMS",
                "version": BASELINE_VERSION,
                "summary": "The terms as first published.",
                "effective_at": BASELINE_EFFECTIVE,
            },
            {
                "id": BASELINE_IDS["PRIVACY"],
                "document": "PRIVACY",
                "version": BASELINE_VERSION,
                "summary": "The privacy notice as first published.",
                "effective_at": BASELINE_EFFECTIVE,
            },
        ],
    )

    # Indexes for the queries compliance and ops add to existing tables.
    # The screening decision list and the export's audit section both filter audit_logs by action.
    op.create_index(
        "ix_audit_logs_screening",
        "audit_logs",
        ["action", "created_at"],
        unique=False,
        postgresql_where=sa.text("action LIKE 'screening.%'"),
    )
    # Attestations per contributor and status are already covered by
    # ix_completion_attestations_contributor_status (migration 0008), which the deletion blocker uses as is.
    # The export reads a user's standing credentials; anonymisation revokes exactly those.
    op.create_index(
        "ix_verifiable_credentials_user_standing",
        "verifiable_credentials",
        ["user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    # The export and the Q&A anonymiser both walk a user's posts oldest first.
    op.create_index("ix_bounty_qa_posts_author_created", "bounty_qa_posts", ["author_id", "created_at"])
    # Milestones of a requester's bounties, in one join ordered by bounty and position.
    op.create_index("ix_bounty_milestones_bounty_position", "bounty_milestones", ["bounty_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_bounty_milestones_bounty_position", table_name="bounty_milestones")
    op.drop_index("ix_bounty_qa_posts_author_created", table_name="bounty_qa_posts")
    op.drop_index("ix_verifiable_credentials_user_standing", table_name="verifiable_credentials")
    op.drop_index("ix_audit_logs_screening", table_name="audit_logs")
    op.drop_index(op.f("ix_legal_acceptances_user_id"), table_name="legal_acceptances")
    op.drop_table("legal_acceptances")
    op.drop_index("ix_legal_document_versions_document_effective", table_name="legal_document_versions")
    op.drop_table("legal_document_versions")
    op.drop_index("uq_screening_entries_active", table_name="screening_entries")
    op.drop_index("ix_screening_entries_address", table_name="screening_entries")
    op.drop_table("screening_entries")
    op.drop_index("uq_account_deletion_requests_one_scheduled", table_name="account_deletion_requests")
    op.drop_index("ix_account_deletion_requests_status_due", table_name="account_deletion_requests")
    op.drop_index(op.f("ix_account_deletion_requests_user_id"), table_name="account_deletion_requests")
    op.drop_table("account_deletion_requests")
    op.drop_index("ix_data_exports_user_created", table_name="data_exports")
    op.drop_index("ix_data_exports_status", table_name="data_exports")
    op.drop_table("data_exports")
