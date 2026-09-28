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

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)  # JSON list form
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        if self.blockchain_mode == "mainnet" and self.stellar_network_passphrase != MAINNET_PASSPHRASE:
            raise ValueError("BLOCKCHAIN_MODE=mainnet requires the mainnet network passphrase")
        if self.blockchain_mode == "testnet" and self.stellar_network_passphrase != TESTNET_PASSPHRASE:
            raise ValueError("BLOCKCHAIN_MODE=testnet requires the testnet network passphrase")
        if "*" in self.cors_origins:
            # Security: CORS runs with allow_credentials=True; Starlette then reflects *any* Origin, letting every
            # website read authenticated API responses. Origins must always be listed explicitly.
            raise ValueError("CORS_ORIGINS must list explicit origins ('*' is not allowed with credentials)")
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
