"""wallets: multi-wallet connections, passkey smart wallets and fee sponsorship

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PASSKEY_STATUSES = ("DEPLOYING", "ACTIVE", "FAILED")
_KINDS = ("FEE_BUMP", "RELAY")
_SPONSOR_STATUSES = ("SUBMITTED", "CONFIRMED", "FAILED")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    # Which wallet app signed the ownership proof, how it was proven, and the chosen payout wallet.
    op.add_column("wallets", sa.Column("wallet_app", sa.String(length=32), nullable=True))
    op.add_column("wallets", sa.Column("proof_method", sa.String(length=16), nullable=True))
    op.add_column(
        "wallets", sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    # Every wallet verified before this revision proved ownership with a SEP-10 challenge transaction.
    op.execute("UPDATE wallets SET proof_method = 'sep10' WHERE proof_method IS NULL")

    op.create_table(
        "passkey_wallets",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("contract_id", sa.String(length=56), nullable=False),
        sa.Column("key_id", sa.String(length=1400), nullable=False),
        sa.Column("public_key", sa.String(length=130), nullable=False),
        sa.Column("wasm_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_PASSKEY_STATUSES, name="passkey_wallet_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("deploy_tx_hash", sa.String(length=64), nullable=True),
        sa.Column("creation_ledger", sa.Integer(), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            _in("status", _PASSKEY_STATUSES), name=op.f("ck_passkey_wallets_passkey_wallet_status")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_passkey_wallets_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_passkey_wallets")),
        sa.UniqueConstraint("network", "contract_id", name="uq_passkey_wallets_network_contract"),
        sa.UniqueConstraint("network", "key_id", name="uq_passkey_wallets_network_key"),
    )
    op.create_index(op.f("ix_passkey_wallets_user_id"), "passkey_wallets", ["user_id"], unique=False)

    op.create_table(
        "sponsored_transactions",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("blockchain_transaction_id", sa.UUID(), nullable=True),
        sa.Column("passkey_wallet_id", sa.UUID(), nullable=True),
        sa.Column(
            "kind", sa.Enum(*_KINDS, name="sponsorship_kind", native_enum=False, length=32), nullable=False
        ),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("sponsor_address", sa.String(length=56), nullable=False),
        sa.Column("source_address", sa.String(length=56), nullable=True),
        sa.Column("inner_hash", sa.String(length=64), nullable=True),
        sa.Column("envelope_hash", sa.String(length=64), nullable=False),
        sa.Column("contract_id", sa.String(length=56), nullable=True),
        sa.Column("function_name", sa.String(length=64), nullable=True),
        sa.Column("max_fee_stroops", sa.BigInteger(), nullable=False),
        sa.Column("fee_charged_stroops", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*_SPONSOR_STATUSES, name="sponsorship_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("ledger_sequence", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(_in("kind", _KINDS), name=op.f("ck_sponsored_transactions_sponsorship_kind")),
        sa.CheckConstraint(
            _in("status", _SPONSOR_STATUSES), name=op.f("ck_sponsored_transactions_sponsorship_status")
        ),
        sa.ForeignKeyConstraint(
            ["blockchain_transaction_id"],
            ["blockchain_transactions.id"],
            name=op.f("fk_sponsored_transactions_blockchain_transaction_id_blockchain_transactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["passkey_wallet_id"],
            ["passkey_wallets.id"],
            name=op.f("fk_sponsored_transactions_passkey_wallet_id_passkey_wallets"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_sponsored_transactions_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sponsored_transactions")),
        sa.UniqueConstraint("network", "envelope_hash", name="uq_sponsored_transactions_network_envelope"),
    )
    op.create_index(
        op.f("ix_sponsored_transactions_blockchain_transaction_id"),
        "sponsored_transactions",
        ["blockchain_transaction_id"],
        unique=False,
    )
    op.create_index(
        "ix_sponsored_transactions_created", "sponsored_transactions", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_sponsored_transactions_passkey_wallet_id"),
        "sponsored_transactions",
        ["passkey_wallet_id"],
        unique=False,
    )
    op.create_index(
        "ix_sponsored_transactions_user_created",
        "sponsored_transactions",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sponsored_transactions_user_created", table_name="sponsored_transactions")
    op.drop_index(op.f("ix_sponsored_transactions_passkey_wallet_id"), table_name="sponsored_transactions")
    op.drop_index("ix_sponsored_transactions_created", table_name="sponsored_transactions")
    op.drop_index(
        op.f("ix_sponsored_transactions_blockchain_transaction_id"), table_name="sponsored_transactions"
    )
    op.drop_table("sponsored_transactions")
    op.drop_index(op.f("ix_passkey_wallets_user_id"), table_name="passkey_wallets")
    op.drop_table("passkey_wallets")
    op.drop_column("wallets", "is_primary")
    op.drop_column("wallets", "proof_method")
    op.drop_column("wallets", "wallet_app")
