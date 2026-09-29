"""Application settings, loaded from environment variables and validated at startup."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

TESTNET_PASSPHRASE = "Test SDF Network ; September 2015"
MAINNET_PASSPHRASE = "Public Global Stellar Network ; September 2015"

_INSECURE_SECRET_MARKERS = ("change-me", "changeme", "replace", "dev-only", "example")

# Repository-root .env (backend/app/core/config.py -> repo root), resolved independently of the CWD.
_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV_FILE, ".env"),  # later files take priority
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application -----------------------------------------------------
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_name: str = "BountyFlow"
    app_version: str = "0.1.0"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:5173"
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:5173"])
    log_level: str = "INFO"
    log_json: bool = False
    log_output: Literal["console", "file", "both", "none"] = "console"

    # --- Startup automation --------------------------------------------------
    # Apply Alembic migrations when the API process starts (guarded by a Postgres advisory lock).
    run_migrations_on_startup: bool = False
    # Run the idempotent seed script on every startup (inserts only what is missing).
    seed_on_startup: bool = False
    max_request_body_bytes: int = 1_048_576
    # Number of trusted reverse proxies in front of the API that append to X-Forwarded-For. The client IP used
    # for rate limiting is the entry appended by the outermost trusted proxy (right-most minus hops-1); anything
    # to its left is client-controlled. 1 = the bundled nginx (docker-compose). Use 0 when the API is exposed
    # directly (X-Forwarded-For is then ignored).
    trusted_proxy_hops: int = Field(default=1, ge=0, le=10)

    # --- Data stores -------------------------------------------------------
    database_url: str = "postgresql+psycopg://bountyflow:bountyflow@localhost:5432/bountyflow"
    database_pool_size: int = 10
    database_max_overflow: int = 10
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # --- Kafka ---------------------------------------------------------------
    kafka_enabled: bool = True
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_consumer_group: str = "bountyflow-workers"
    kafka_topic_prefix: str = ""
    outbox_poll_interval_seconds: float = 1.0
    outbox_batch_size: int = 100
    worker_max_retries: int = 5

    # --- Auth ----------------------------------------------------------------
    jwt_secret: str = "dev-only-insecure-jwt-secret-change-me-0000000000"
    # Security: pinned to HMAC algorithms. The verifier holds a shared secret, so "none" or an asymmetric
    # algorithm must never be configurable (algorithm-confusion / unsigned-token acceptance).
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_ttl: int = 900  # seconds
    refresh_token_ttl: int = 60 * 60 * 24 * 30  # seconds
    email_verification_ttl: int = 60 * 60 * 24
    password_reset_ttl: int = 60 * 60
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    cookie_domain: str | None = None
    # Password given to accounts created by the development seed (never used outside development/test).
    seed_user_password: str = "BountyFlow!2026"

    # --- Email -----------------------------------------------------------------
    email_backend: Literal["smtp", "console"] = "smtp"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    email_from: str = "BountyFlow <no-reply@bountyflow.local>"

    # --- Stellar / Soroban -------------------------------------------------
    blockchain_mode: Literal["testnet", "mainnet"] = "testnet"
    stellar_network: Literal["testnet", "mainnet"] = "testnet"
    stellar_network_passphrase: str = TESTNET_PASSPHRASE
    stellar_horizon_url: str = "https://horizon-testnet.stellar.org"
    stellar_soroban_rpc_url: str = "https://soroban-testnet.stellar.org"
    stellar_explorer_base_url: str = "https://stellar.expert/explorer/testnet"
    soroban_contract_id: str | None = None
    stellar_native_asset_contract_id: str | None = None
    stellar_arbiter_address: str | None = None
    stellar_base_fee: int = 100_000
    stellar_tx_timeout_seconds: int = 300
    blockchain_confirmation_timeout: int = 120
    blockchain_rpc_timeout_seconds: float = 15.0
    wallet_challenge_ttl: int = 300
    wallet_challenge_home_domain: str = "bountyflow.local"
    wallet_challenge_signing_secret: str | None = None

    # --- Escrow v2: contract version and review window ----------------------------
    # Interface version of SOROBAN_CONTRACT_ID (2: milestones, review window, M-of-N arbiters, batch payouts).
    # Escrows keep the contract id and version they were created on (bounty_escrows.contract_id).
    soroban_contract_version: int = Field(default=2, ge=1, le=2)
    # Review window new bounties get, and the range a requester may choose from, in seconds. Lower the minimum
    # only for end-to-end tests (e.g. 60); staging and production refuse less than one day. The contract
    # deployment enforces its own floor (`min_review_window()`, 60 seconds on the Testnet deployment).
    escrow_default_review_window_seconds: int = Field(default=604_800, ge=60, le=2_592_000)
    escrow_min_review_window_seconds: int = Field(default=86_400, ge=60, le=604_800)
    escrow_max_review_window_seconds: int = Field(default=2_592_000, ge=60, le=2_592_000)

    # --- Wallets: passkey smart wallets and fee sponsorship --------------------
    # SEP-45 web auth contract (contracts/web_auth) used to prove control of contract accounts (C...). Public.
    web_auth_contract_id: str | None = None
    # Smart-wallet WASM that passkey wallets are created from (passkey-kit v1.1 wallet, already on Testnet).
    passkey_wallet_wasm_hash: str = "97ce047884106b1c6c3bb40b8973cc48db1c4dad95c9e20462bf2c701daa764e"
    # Platform sponsor account: pays network fees for eligible transactions (fee bumps) and is the source of
    # relayed smart-wallet transactions. Everything sponsored is off when it is empty.
    stellar_sponsor_secret: str | None = None
    sponsor_max_fee_stroops: int = Field(default=5_000_000, ge=10_000)
    sponsor_daily_tx_limit: int = Field(default=25, ge=0)
    sponsor_daily_fee_limit_stroops: int = Field(default=50_000_000, ge=0)
    sponsor_low_balance_xlm: int = Field(default=100, ge=0)
    sponsor_min_balance_xlm: int = Field(default=5, ge=0)
    # Contracts besides SOROBAN_CONTRACT_ID, and contributor-side functions, whose calls may be fee-bumped.
    sponsor_allowed_contracts: Annotated[list[str], NoDecode] = Field(default_factory=list)
    sponsor_allowed_functions: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["consent_cancel", "raise_dispute", "submit_work", "claim"]
    )
    # Classic assets (CODE:ISSUER) whose trustlines may be sponsored.
    sponsor_allowed_assets: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["USDC:GBBD47IF6LWK7P7MDEVSCWR7DPUWV3NY3DTQEVFL4NAT4AQH3ZLLFLA5"]
    )

    # --- GitHub (account linking and pull request verification) -------------
    github_api_url: str = "https://api.github.com"
    github_oauth_url: str = "https://github.com"
    # Optional. Raises the REST API limit from 60 to 5,000 requests an hour; only public data is read, so a
    # fine-grained token with no repository permissions is enough. Without it, responses are cached and the
    # client backs off when the limit is reached.
    github_token: str | None = None
    # Optional "Connect with GitHub" (an OAuth app). Gist verification works without them.
    github_client_id: str | None = None
    github_client_secret: str | None = None
    # Optional webhook that re-checks pull requests when they change (HMAC-SHA256). Off when empty.
    github_webhook_secret: str | None = None
    github_timeout_seconds: float = 10.0
    # Test mode only: serve recorded GitHub API responses (backend/tests/fixtures/github) instead of calling
    # GitHub. Refused in staging and production.
    github_fixture_transport: bool = False

    # --- Mainnet guard (see app/core/mainnet.py) -----------------------------
    # STELLAR_NETWORK=mainnet refuses to start unless ALLOW_MAINNET=true and every other requirement holds.
    allow_mainnet: bool = False
    # JSON file listing audited deployments per network (absolute, or relative to the repository root).
    audited_deployments_file: str = "deploy/audited-deployments.json"
    # Public HTTPS URL of the API (e.g. https://api.example.com). Required on mainnet.
    public_api_url: str | None = None
    # M-of-N dispute arbiter: the signer addresses and the approvals a resolution needs (mainnet needs >= 2).
    stellar_arbiter_addresses: Annotated[list[str], NoDecode] = Field(default_factory=list)
    stellar_arbiter_threshold: int = Field(default=1, ge=1, le=10)

    # --- Compliance (data export, account deletion, sanctions screening) ------
    data_export_ttl_hours: int = Field(default=168, ge=1, le=720)
    account_deletion_grace_days: int = Field(default=14, ge=1, le=90)
    sanctions_screening_enabled: bool = True
    # A sanctions list of Stellar addresses: a file path or an https URL. Plain lists (one address per line, or a
    # JSON array) and the OFAC SDN CSV ("Digital Currency Address - XLM" remarks) are recognised.
    sanctions_list_path: str | None = None
    sanctions_list_url: str | None = None
    sanctions_list_name: str = "Sanctions list"
    sanctions_list_refresh_seconds: int = Field(default=21_600, ge=300)

    # --- Reputation: on-chain completion attestations and verifiable credentials --
    # Attestation registry (contracts/attestations). Public; see contracts/deployments/attestations-testnet.json.
    attestation_contract_id: str | None = None
    # Platform attester key (a Stellar secret seed). It signs attestations of verified payouts; attestations are
    # off when it is empty.
    stellar_attester_secret: str | None = None
    # Ed25519 key (a Stellar secret seed) that signs W3C verifiable credentials. Credentials are off when empty.
    credential_issuer_secret: str | None = None
    # Host of the did:web issuer, port included (default: the FRONTEND_URL host).
    credential_issuer_domain: str | None = None

    # --- Discovery: saved-search alerts and skill-graph recommendations ------------
    # UTC hour at which saved-search digests go out: daily ones every day, weekly ones on Mondays.
    discovery_digest_hour_utc: int = Field(default=8, ge=0, le=23)
    # How often the worker rebuilds the skill graph from bounties and profiles.
    discovery_graph_refresh_seconds: int = Field(default=1800, ge=60)
    # Enables POST /admin/discovery/digests/run (admins only), which sends pending digests immediately for
    # end-to-end tests and operators. Off by default; the route answers 404 while it is off.
    discovery_digest_trigger_enabled: bool = False

    # --- Operations -----------------------------------------------------------
    metrics_enabled: bool = True
    # Bearer token for GET /metrics. Without one, /metrics answers only direct loopback requests.
    metrics_token: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)  # JSON list form
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator(
        "sponsor_allowed_contracts", "sponsor_allowed_functions", "sponsor_allowed_assets", mode="before"
    )
    @classmethod
    def _split_sponsor_lists(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("stellar_arbiter_addresses", mode="before")
    @classmethod
    def _split_arbiters(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [address.strip() for address in stripped.split(",") if address.strip()]
        return value

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.stellar_network == "mainnet" or self.blockchain_mode == "mainnet":
            from app.core.mainnet import format_problems, mainnet_problems

            mainnet = mainnet_problems(self)
            if mainnet:
                raise ValueError(format_problems(mainnet))
        if self.blockchain_mode == "mainnet" and self.stellar_network_passphrase != MAINNET_PASSPHRASE:
            raise ValueError("BLOCKCHAIN_MODE=mainnet requires the mainnet network passphrase")
        if self.blockchain_mode == "testnet" and self.stellar_network_passphrase != TESTNET_PASSPHRASE:
            raise ValueError("BLOCKCHAIN_MODE=testnet requires the testnet network passphrase")
        if self.stellar_native_asset_contract_id:
            from app.blockchain.assets import native_contract_id  # stellar_sdk only, no app imports

            expected = native_contract_id(self.stellar_network_passphrase)
            if self.stellar_native_asset_contract_id != expected:
                raise ValueError(
                    "STELLAR_NATIVE_ASSET_CONTRACT_ID is not the native XLM asset contract of this network "
                    f"(expected {expected}). Leave it empty to derive it."
                )
        if "*" in self.cors_origins:
            # Security: CORS runs with allow_credentials=True; Starlette then reflects *any* Origin, letting every
            # website read authenticated API responses. Origins must always be listed explicitly.
            raise ValueError("CORS_ORIGINS must list explicit origins ('*' is not allowed with credentials)")
        if self.github_fixture_transport and self.app_env not in ("development", "test"):
            raise ValueError("GITHUB_FIXTURE_TRANSPORT is only allowed in development and test")
        if not (
            self.escrow_min_review_window_seconds
            <= self.escrow_default_review_window_seconds
            <= self.escrow_max_review_window_seconds
        ):
            raise ValueError(
                "ESCROW_MIN_REVIEW_WINDOW_SECONDS <= ESCROW_DEFAULT_REVIEW_WINDOW_SECONDS <= "
                "ESCROW_MAX_REVIEW_WINDOW_SECONDS must hold"
            )
        if self.stellar_arbiter_addresses and self.stellar_arbiter_threshold > len(
            self.stellar_arbiter_addresses
        ):
            raise ValueError(
                "STELLAR_ARBITER_THRESHOLD cannot exceed the number of STELLAR_ARBITER_ADDRESSES"
            )
        if self.is_production:
            problems: list[str] = []
            if len(self.jwt_secret) < 32 or any(
                m in self.jwt_secret.lower() for m in _INSECURE_SECRET_MARKERS
            ):
                problems.append("JWT_SECRET must be a strong random value (>= 32 chars)")
            if not self.cookie_secure:
                problems.append("COOKIE_SECURE must be true in production")
            if not self.soroban_contract_id:
                problems.append("SOROBAN_CONTRACT_ID is required")
            if not self.wallet_challenge_signing_secret:
                problems.append("WALLET_CHALLENGE_SIGNING_SECRET is required")
            if self.escrow_min_review_window_seconds < 86_400:
                problems.append("ESCROW_MIN_REVIEW_WINDOW_SECONDS must be at least one day (86400)")
            if problems:
                raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env in ("production", "staging")

    @property
    def network_label(self) -> str:
        return self.stellar_network

    def topic(self, name: str) -> str:
        return f"{self.kafka_topic_prefix}{name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
