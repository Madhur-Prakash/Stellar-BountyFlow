"""escrow v2: milestones, review-timeout release, multisig arbiters and batch payouts

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-29
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The v1 Testnet escrow contract (contracts/deployments/testnet.json -> superseded_deployments). Every escrow row
# created before this revision lives there; new escrows use SOROBAN_CONTRACT_ID (the v2 deployment).
V1_TESTNET_CONTRACT_ID = "CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY"

TX_TYPES = (
    "MILESTONE_PAYOUT",
    "BATCH_PAYOUT",
    "SUBMIT_WORK",
    "REQUEST_CHANGES",
    "REJECT_SUBMISSION",
    "CLAIM",
    "DISPUTE_VOTE",
)
NOTIFICATION_TYPES = ("CLAIM_AVAILABLE", "MILESTONE_PAID", "ARBITER_VOTE")
RESOLUTIONS = ("SPLIT",)
MILESTONE_STATUSES = ("OPEN", "PAID", "SETTLED")
ONCHAIN_REVIEW_STATES = ("PENDING", "CHANGES_REQUESTED", "REJECTED", "PAID")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _enum(values: Sequence[str], name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, length=32)


def _enum_checks(table: str, column: str) -> list[tuple[str, list[str]]]:
    """The CHECK constraints on ``table`` that list the allowed values of ``column``, with those values. Read from
    the database, so values other revisions added are kept whatever order the revisions run in."""
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
    # --- Escrows keep the contract they were created on ---------------------------------------------
    op.execute(
        sa.text(
            "UPDATE bounty_escrows SET contract_id = :v1 WHERE contract_id IS NULL AND network = 'testnet'"
        ).bindparams(v1=V1_TESTNET_CONTRACT_ID)
    )
    op.add_column(
        "bounty_escrows",
        sa.Column("contract_version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("bounty_escrows", sa.Column("review_window_seconds", sa.Integer(), nullable=True))
    op.add_column(
        "bounty_escrows",
        sa.Column(
            "arbiter_addresses",
            postgresql.ARRAY(sa.String(length=56)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "bounty_escrows",
        sa.Column("arbiter_threshold", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "bounty_escrows",
        sa.Column("dispute_round", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("bounty_escrows", sa.Column("clock_reset_at", sa.BigInteger(), nullable=True))
    op.execute(
        "UPDATE bounty_escrows SET arbiter_addresses = ARRAY[arbiter_address] "
        "WHERE arbiter_address IS NOT NULL AND cardinality(arbiter_addresses) = 0"
    )

    # --- Review window chosen for a bounty ------------------------------------------------------------
    op.add_column("bounties", sa.Column("review_window_seconds", sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f("ck_bounties_review_window_range"),
        "bounties",
        "review_window_seconds IS NULL OR (review_window_seconds >= 60 AND review_window_seconds <= 2592000)",
    )

    # --- Milestones -------------------------------------------------------------------------------------
    op.create_table(
        "bounty_milestones",
        sa.Column("bounty_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=7), nullable=False),
        sa.Column("status", _enum(MILESTONE_STATUSES, "milestone_status"), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payout_transaction_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("amount > 0", name=op.f("ck_bounty_milestones_amount_positive")),
        sa.CheckConstraint(
            "position >= 0 AND position < 20", name=op.f("ck_bounty_milestones_position_range")
        ),
        sa.CheckConstraint(
            _in("status", MILESTONE_STATUSES), name=op.f("ck_bounty_milestones_milestone_status")
        ),
        sa.ForeignKeyConstraint(
            ["bounty_id"],
            ["bounties.id"],
            name=op.f("fk_bounty_milestones_bounty_id_bounties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payout_transaction_id"],
            ["blockchain_transactions.id"],
            name=op.f("fk_bounty_milestones_payout_tx_blockchain_transactions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bounty_milestones")),
        sa.UniqueConstraint("bounty_id", "position", name="uq_bounty_milestones_bounty_position"),
    )
    op.create_index(op.f("ix_bounty_milestones_bounty_id"), "bounty_milestones", ["bounty_id"], unique=False)

    # --- Submissions: milestone and the on-chain review clock ---------------------------------------
    op.add_column("bounty_submissions", sa.Column("milestone_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_bounty_submissions_milestone_id_bounty_milestones"),
        "bounty_submissions",
        "bounty_milestones",
        ["milestone_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_bounty_submissions_milestone_id"), "bounty_submissions", ["milestone_id"], unique=False
    )
    op.add_column(
        "bounty_submissions",
        sa.Column("onchain_state", _enum(ONCHAIN_REVIEW_STATES, "onchain_review_state"), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_bounty_submissions_onchain_review_state"),
        "bounty_submissions",
        _in("onchain_state", ONCHAIN_REVIEW_STATES),
    )
    op.add_column(
        "bounty_submissions", sa.Column("onchain_submitted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("bounty_submissions", sa.Column("claimable_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "bounty_submissions", sa.Column("claim_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_bounty_submissions_claimable",
        "bounty_submissions",
        ["claimable_at"],
        unique=False,
        postgresql_where=sa.text("onchain_state = 'PENDING' AND claim_notified_at IS NULL"),
    )

    # --- Payments: one per milestone on milestone bounties ------------------------------------------
    op.add_column("payment_records", sa.Column("milestone_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_payment_records_milestone_id_bounty_milestones"),
        "payment_records",
        "bounty_milestones",
        ["milestone_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("uq_payment_records_bounty_contributor", "payment_records", type_="unique")
    op.create_index(
        "uq_payment_records_bounty_contributor",
        "payment_records",
        ["bounty_id", "contributor_id"],
        unique=True,
        postgresql_where=sa.text("milestone_id IS NULL"),
    )
    op.create_index(
        "uq_payment_records_milestone",
        "payment_records",
        ["milestone_id"],
        unique=True,
        postgresql_where=sa.text("milestone_id IS NOT NULL"),
    )

    # --- Disputes: split resolutions and the arbiters' on-chain approvals ----------------------------
    op.add_column(
        "disputes", sa.Column("contributor_amount", sa.Numeric(precision=20, scale=7), nullable=True)
    )
    _set_allowed("disputes", "resolution", "ck_disputes_dispute_resolution", add=RESOLUTIONS)
    op.create_table(
        "dispute_votes",
        sa.Column("dispute_id", sa.UUID(), nullable=False),
        sa.Column("bounty_id", sa.UUID(), nullable=False),
        sa.Column("arbiter_address", sa.String(length=56), nullable=False),
        sa.Column("voter_id", sa.UUID(), nullable=True),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("contributor_amount", sa.Numeric(precision=20, scale=7), nullable=False),
        sa.Column("transaction_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["dispute_id"],
            ["disputes.id"],
            name=op.f("fk_dispute_votes_dispute_id_disputes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["bounty_id"],
            ["bounties.id"],
            name=op.f("fk_dispute_votes_bounty_id_bounties"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["voter_id"], ["users.id"], name=op.f("fk_dispute_votes_voter_id_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["blockchain_transactions.id"],
            name=op.f("fk_dispute_votes_transaction_id_blockchain_transactions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dispute_votes")),
        sa.UniqueConstraint("dispute_id", "arbiter_address", "round", name="uq_dispute_votes_arbiter_round"),
    )
    op.create_index(op.f("ix_dispute_votes_dispute_id"), "dispute_votes", ["dispute_id"], unique=False)

    # --- New transaction kinds and notification types ------------------------------------------------
    _set_allowed(
        "blockchain_transactions", "transaction_type", "ck_blockchain_transactions_tx_type", add=TX_TYPES
    )
    _set_allowed(
        "notifications", "notification_type", "ck_notifications_notification_type", add=NOTIFICATION_TYPES
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM notifications WHERE notification_type IN :types").bindparams(
            sa.bindparam("types", value=list(NOTIFICATION_TYPES), expanding=True)
        )
    )
    _set_allowed(
        "notifications", "notification_type", "ck_notifications_notification_type", remove=NOTIFICATION_TYPES
    )
    op.execute(
        sa.text("DELETE FROM blockchain_transactions WHERE transaction_type IN :types").bindparams(
            sa.bindparam("types", value=list(TX_TYPES), expanding=True)
        )
    )
    _set_allowed(
        "blockchain_transactions", "transaction_type", "ck_blockchain_transactions_tx_type", remove=TX_TYPES
    )

    op.drop_index(op.f("ix_dispute_votes_dispute_id"), table_name="dispute_votes")
    op.drop_table("dispute_votes")
    op.execute("UPDATE disputes SET resolution = 'RELEASE_TO_CONTRIBUTOR' WHERE resolution = 'SPLIT'")
    _set_allowed("disputes", "resolution", "ck_disputes_dispute_resolution", remove=RESOLUTIONS)
    op.drop_column("disputes", "contributor_amount")

    op.execute("DELETE FROM payment_records WHERE milestone_id IS NOT NULL")
    op.drop_index("uq_payment_records_milestone", table_name="payment_records")
    op.drop_index("uq_payment_records_bounty_contributor", table_name="payment_records")
    op.create_unique_constraint(
        "uq_payment_records_bounty_contributor", "payment_records", ["bounty_id", "contributor_id"]
    )
    op.drop_constraint(
        op.f("fk_payment_records_milestone_id_bounty_milestones"), "payment_records", type_="foreignkey"
    )
    op.drop_column("payment_records", "milestone_id")

    op.drop_index("ix_bounty_submissions_claimable", table_name="bounty_submissions")
    op.drop_column("bounty_submissions", "claim_notified_at")
    op.drop_column("bounty_submissions", "claimable_at")
    op.drop_column("bounty_submissions", "onchain_submitted_at")
    op.drop_constraint(
        op.f("ck_bounty_submissions_onchain_review_state"), "bounty_submissions", type_="check"
    )
    op.drop_column("bounty_submissions", "onchain_state")
    op.drop_index(op.f("ix_bounty_submissions_milestone_id"), table_name="bounty_submissions")
    op.drop_constraint(
        op.f("fk_bounty_submissions_milestone_id_bounty_milestones"), "bounty_submissions", type_="foreignkey"
    )
    op.drop_column("bounty_submissions", "milestone_id")

    op.drop_index(op.f("ix_bounty_milestones_bounty_id"), table_name="bounty_milestones")
    op.drop_table("bounty_milestones")

    op.drop_constraint(op.f("ck_bounties_review_window_range"), "bounties", type_="check")
    op.drop_column("bounties", "review_window_seconds")

    for column in (
        "clock_reset_at",
        "dispute_round",
        "arbiter_threshold",
        "arbiter_addresses",
        "review_window_seconds",
        "contract_version",
    ):
        op.drop_column("bounty_escrows", column)
