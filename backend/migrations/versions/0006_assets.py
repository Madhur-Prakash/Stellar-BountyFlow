"""assets: reward assets (USDC and other SAC tokens) and trustline checks

Adds the reward asset registry (enabled per network, seeded with XLM and Circle's USDC), the wallet-signed asset
operations (trustlines and Stellar Asset Contract deployments), each bounty's reward asset, and room for per-asset
daily metric names.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The registry's defaults per network. Contract ids are each asset's Stellar Asset Contract, derived from the asset
# and the network passphrase (`stellar contract id asset --asset <asset> --network <network>`); both are deployed.
_DEFAULTS = [
    ("testnet", "native", "NATIVE", "XLM", None, "CDLZFC3SYJYDZT7K67VZ75HPJVIEUVNIXF47ZG2FB2RMQQVU2HHGCYSC",
     "Stellar Lumens", "native", 0),
    ("testnet", "USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5", "CLASSIC", "USDC",
     "GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5", "CBIELTK6YBZJU5UP2WWQEUCYKLPU6AUNZ2BQ4WWFEIE3USCIHMXQDAMA",
     "USD Coin", "USDC", 10),
    ("mainnet", "native", "NATIVE", "XLM", None, "CAS3J7GYLGXMF6TDJBBYYSE3HQ6BBSMLNUQ34T6TZMYMW2EVH34XOWMA",
     "Stellar Lumens", "native", 0),
    ("mainnet", "USDC:GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN", "CLASSIC", "USDC",
     "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN", "CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75",
     "USD Coin", "USDC", 10),
]


def upgrade() -> None:
    op.create_table(
        "reward_assets",
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("identifier", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.Enum("NATIVE", "CLASSIC", name="reward_asset_kind", native_enum=False, length=32),
                  nullable=False),
        sa.Column("code", sa.String(length=12), nullable=False),
        sa.Column("issuer", sa.String(length=56), nullable=True),
        sa.Column("contract_id", sa.String(length=56), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("decimals", sa.Integer(), server_default="7", nullable=False),
        sa.Column("contract_status", sa.Enum("DEPLOYED", "NOT_DEPLOYED", name="reward_asset_contract_status",
                                             native_enum=False, length=32), nullable=False),
        sa.Column("issuer_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="100", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('NATIVE', 'CLASSIC')", name=op.f("ck_reward_assets_reward_asset_kind")),
        sa.CheckConstraint("contract_status IN ('DEPLOYED', 'NOT_DEPLOYED')",
                           name=op.f("ck_reward_assets_reward_asset_contract_status")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_reward_assets_created_by_id_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reward_assets")),
        sa.UniqueConstraint("network", "contract_id", name="uq_reward_assets_network_contract"),
        sa.UniqueConstraint("network", "identifier", name="uq_reward_assets_network_identifier"),
    )
    op.create_index("ix_reward_assets_network_enabled", "reward_assets", ["network", "is_enabled"], unique=False)

    op.create_table(
        "asset_operations",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Enum("TRUSTLINE", "DEPLOY_CONTRACT", name="asset_operation_kind", native_enum=False,
                                  length=32), nullable=False),
        sa.Column("status", sa.Enum("SIGNATURE_REQUIRED", "SUBMITTED", "CONFIRMED", "FAILED", "EXPIRED",
                                    name="asset_operation_status", native_enum=False, length=32), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("source_address", sa.String(length=56), nullable=False),
        sa.Column("transaction_hash", sa.String(length=64), nullable=False),
        sa.Column("unsigned_xdr", sa.Text(), nullable=True),
        sa.Column("submitted_xdr", sa.Text(), nullable=True),
        sa.Column("sponsorship_id", sa.UUID(), nullable=True),
        sa.Column("fee_stroops", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ledger_sequence", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("result_code", sa.String(length=40), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('TRUSTLINE', 'DEPLOY_CONTRACT')",
                           name=op.f("ck_asset_operations_asset_operation_kind")),
        sa.CheckConstraint("status IN ('SIGNATURE_REQUIRED', 'SUBMITTED', 'CONFIRMED', 'FAILED', 'EXPIRED')",
                           name=op.f("ck_asset_operations_asset_operation_status")),
        sa.ForeignKeyConstraint(["asset_id"], ["reward_assets.id"], name=op.f("fk_asset_operations_asset_id_reward_assets"),
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sponsorship_id"], ["sponsored_transactions.id"],
                                name=op.f("fk_asset_operations_sponsorship_id_sponsored_transactions"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_asset_operations_user_id_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_asset_operations")),
        sa.UniqueConstraint("network", "transaction_hash", name="uq_asset_operations_network_hash"),
    )
    op.create_index(op.f("ix_asset_operations_asset_id"), "asset_operations", ["asset_id"], unique=False)
    op.create_index("ix_asset_operations_status", "asset_operations", ["status"], unique=False)
    op.create_index("ix_asset_operations_user_created", "asset_operations", ["user_id", "created_at"], unique=False)

    op.add_column(
        "bounties",
        sa.Column("reward_asset_identifier", sa.String(length=80), server_default="native", nullable=False),
    )
    op.create_index(op.f("ix_bounties_reward_asset_identifier"), "bounties", ["reward_asset_identifier"], unique=False)
    op.alter_column("daily_metrics", "metric", type_=sa.String(length=128), existing_type=sa.String(length=64),
                    existing_nullable=False)

    registry = sa.table(
        "reward_assets",
        sa.column("id", sa.UUID()),
        sa.column("network", sa.String()),
        sa.column("identifier", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("code", sa.String()),
        sa.column("issuer", sa.String()),
        sa.column("contract_id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("symbol", sa.String()),
        sa.column("decimals", sa.Integer()),
        sa.column("contract_status", sa.String()),
        sa.column("issuer_flags", postgresql.JSONB()),
        sa.column("is_enabled", sa.Boolean()),
        sa.column("is_default", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        registry,
        [
            {
                "id": uuid.uuid4(),
                "network": network,
                "identifier": identifier,
                "kind": kind,
                "code": code,
                "issuer": issuer,
                "contract_id": contract_id,
                "name": name,
                "symbol": symbol,
                "decimals": 7,
                "contract_status": "DEPLOYED",
                "issuer_flags": {},
                "is_enabled": True,
                "is_default": True,
                "sort_order": sort_order,
            }
            for network, identifier, kind, code, issuer, contract_id, name, symbol, sort_order in _DEFAULTS
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM daily_metrics WHERE metric LIKE 'payout_volume:%'")
    op.alter_column("daily_metrics", "metric", type_=sa.String(length=64), existing_type=sa.String(length=128),
                    existing_nullable=False)
    op.drop_index(op.f("ix_bounties_reward_asset_identifier"), table_name="bounties")
    op.drop_column("bounties", "reward_asset_identifier")
    op.drop_index("ix_asset_operations_user_created", table_name="asset_operations")
    op.drop_index("ix_asset_operations_status", table_name="asset_operations")
    op.drop_index(op.f("ix_asset_operations_asset_id"), table_name="asset_operations")
    op.drop_table("asset_operations")
    op.drop_index("ix_reward_assets_network_enabled", table_name="reward_assets")
    op.drop_table("reward_assets")
