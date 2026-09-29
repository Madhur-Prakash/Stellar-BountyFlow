"""reputation: on-chain completion attestations and verifiable credentials

Adds ``completion_attestations`` (one row per completed (bounty, contributor) pair, tracking its record in the
on-chain attestation registry) and ``verifiable_credentials`` (issued W3C credentials with their status list
index).

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = ("PENDING", "SUBMITTED", "CONFIRMED", "REVOKING", "REVOKED", "FAILED")
_CHECKS = ("MATCH", "MISMATCH", "MISSING")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "completion_attestations",
        sa.Column("bounty_id", sa.UUID(), nullable=False),
        sa.Column("contributor_id", sa.UUID(), nullable=False),
        sa.Column("assignment_id", sa.UUID(), nullable=True),
        sa.Column("payout_transaction_id", sa.UUID(), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("contract_id", sa.String(length=56), nullable=False),
        sa.Column("contributor_address", sa.String(length=56), nullable=False),
        sa.Column("onchain_bounty_id", sa.String(length=64), nullable=False),
        sa.Column("escrow_contract_id", sa.String(length=56), nullable=False),
        sa.Column("payout_tx_hash", sa.String(length=64), nullable=False),
        sa.Column("asset_identifier", sa.String(length=80), nullable=False),
        sa.Column("token_contract_id", sa.String(length=56), nullable=False),
        sa.Column("amount", sa.Numeric(precision=20, scale=7), nullable=False),
        sa.Column("payments_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_STATUSES, name="attestation_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("onchain_id", sa.BigInteger(), nullable=True),
        sa.Column("attestation_tx_hash", sa.String(length=64), nullable=True),
        sa.Column("attestation_ledger", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("revocation_reason", sa.String(length=200), nullable=True),
        sa.Column("revocation_tx_hash", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "chain_check",
            sa.Enum(*_CHECKS, name="attestation_chain_check", native_enum=False, length=32),
            nullable=True,
        ),
        sa.Column("chain_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_completion_attestations_amount_positive")),
        sa.CheckConstraint("payments_count > 0", name=op.f("ck_completion_attestations_payments_counted")),
        sa.CheckConstraint(
            _in("status", _STATUSES), name=op.f("ck_completion_attestations_attestation_status")
        ),
        sa.CheckConstraint(
            _in("chain_check", _CHECKS), name=op.f("ck_completion_attestations_attestation_chain_check")
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["bounty_assignments.id"],
            name=op.f("fk_completion_attestations_assignment_id_bounty_assignments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["bounty_id"],
            ["bounties.id"],
            name=op.f("fk_completion_attestations_bounty_id_bounties"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["contributor_id"],
            ["users.id"],
            name=op.f("fk_completion_attestations_contributor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payout_transaction_id"],
            ["blockchain_transactions.id"],
            name=op.f("fk_completion_attestations_payout_transaction_id_blockchain_transactions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_id"],
            ["users.id"],
            name=op.f("fk_completion_attestations_revoked_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_completion_attestations")),
        sa.UniqueConstraint(
            "bounty_id", "contributor_id", name="uq_completion_attestations_bounty_contributor"
        ),
        sa.UniqueConstraint(
            "network", "contract_id", "onchain_id", name="uq_completion_attestations_onchain"
        ),
    )
    op.create_index(op.f("ix_completion_attestations_bounty_id"), "completion_attestations", ["bounty_id"])
    op.create_index(
        op.f("ix_completion_attestations_payout_transaction_id"),
        "completion_attestations",
        ["payout_transaction_id"],
    )
    # The contributor's public list and the owner's workspace list.
    op.create_index(
        "ix_completion_attestations_contributor_status",
        "completion_attestations",
        ["contributor_id", "status"],
    )
    # The pipeline job's "what is due" scan.
    op.create_index(
        "ix_completion_attestations_due", "completion_attestations", ["status", "next_attempt_at"]
    )
    # The reconciliation job's "least recently checked" scan.
    op.create_index(
        "ix_completion_attestations_checked", "completion_attestations", ["status", "chain_checked_at"]
    )

    op.create_table(
        "verifiable_credentials",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("COMPLETION", "SUMMARY", name="credential_kind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("attestation_id", sa.UUID(), nullable=True),
        sa.Column("attestation_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject_did", sa.String(length=120), nullable=False),
        sa.Column("issuer_did", sa.String(length=200), nullable=False),
        sa.Column("status_index", sa.Integer(), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(length=200), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('COMPLETION', 'SUMMARY')", name=op.f("ck_verifiable_credentials_credential_kind")
        ),
        sa.ForeignKeyConstraint(
            ["attestation_id"],
            ["completion_attestations.id"],
            name=op.f("fk_verifiable_credentials_attestation_id_completion_attestations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_verifiable_credentials_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verifiable_credentials")),
        sa.UniqueConstraint("status_index", name=op.f("uq_verifiable_credentials_status_index")),
    )
    op.create_index("ix_verifiable_credentials_user_kind", "verifiable_credentials", ["user_id", "kind"])
    # At most one standing completion credential per attestation; re-issuing returns the existing one.
    op.create_index(
        "uq_verifiable_credentials_active_completion",
        "verifiable_credentials",
        ["attestation_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'COMPLETION' AND revoked_at IS NULL"),
    )
    # The public revocation status list is built from the revoked indexes of one issuer.
    op.create_index(
        "ix_verifiable_credentials_revoked",
        "verifiable_credentials",
        ["issuer_did", "status_index"],
        postgresql_where=sa.text("revoked_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_verifiable_credentials_revoked", table_name="verifiable_credentials")
    op.drop_index("uq_verifiable_credentials_active_completion", table_name="verifiable_credentials")
    op.drop_index("ix_verifiable_credentials_user_kind", table_name="verifiable_credentials")
    op.drop_table("verifiable_credentials")
    op.drop_index("ix_completion_attestations_checked", table_name="completion_attestations")
    op.drop_index("ix_completion_attestations_due", table_name="completion_attestations")
    op.drop_index("ix_completion_attestations_contributor_status", table_name="completion_attestations")
    op.drop_index(
        op.f("ix_completion_attestations_payout_transaction_id"), table_name="completion_attestations"
    )
    op.drop_index(op.f("ix_completion_attestations_bounty_id"), table_name="completion_attestations")
    op.drop_table("completion_attestations")
