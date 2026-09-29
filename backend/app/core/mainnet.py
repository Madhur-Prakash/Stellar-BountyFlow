"""Mainnet configuration guard.

Stellar mainnet moves real money, so ``STELLAR_NETWORK=mainnet`` (or ``BLOCKCHAIN_MODE=mainnet``) is refused
unless every requirement below holds. ``Settings`` calls ``mainnet_problems`` while validating, so the API, the
worker and every script refuse to start and print the complete list, and an operator can fix everything in one
pass. See docs/deployment.md (Mainnet) and docs/runbooks/mainnet-launch-checklist.md.

Three contracts are part of the deployed surface and each needs an entry in the audited-deployments file with
its audit report: the escrow (``SOROBAN_CONTRACT_ID``), the SEP-45 web-auth contract
(``WEB_AUTH_CONTRACT_ID``, only when smart-wallet sign-in is configured) and the attestation registry
(``ATTESTATION_CONTRACT_ID``, only when attestations are configured). Escrows created on an older escrow
contract keep serving on it (``bounty_escrows.contract_id``), so the guard checks the configured id for *new*
escrows and leaves per-escrow ids alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from app.core.config import Settings

MAINNET_PASSPHRASE = "Public Global Stellar Network ; September 2015"

# backend/app/core/mainnet.py -> repository root (source checkout) and backend root (container: /app).
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Values that ship in .env.example or docker-compose for local development.
_DEV_DATABASE_PASSWORDS = ("bountyflow-local-dev-password", ":bountyflow@")
_INSECURE_MARKERS = ("change-me", "changeme", "replace", "dev-only", "example", "insecure")
MIN_SECRET_LENGTH = 32
MIN_METRICS_TOKEN_LENGTH = 24
# A Stellar secret seed: 56 characters starting with S.
STELLAR_SECRET_LENGTH = 56

# Secret keys that must hold a real value before mainnet: (setting, env var, what it signs, is a Stellar seed).
SIGNING_SECRETS: tuple[tuple[str, str, str, bool], ...] = (
    ("jwt_secret", "JWT_SECRET", "session tokens and data-export download links", False),
    (
        "wallet_challenge_signing_secret",
        "WALLET_CHALLENGE_SIGNING_SECRET",
        "wallet ownership challenges",
        True,
    ),
    ("stellar_sponsor_secret", "STELLAR_SPONSOR_SECRET", "sponsored network fees", True),
    ("stellar_attester_secret", "STELLAR_ATTESTER_SECRET", "on-chain completion attestations", True),
    ("credential_issuer_secret", "CREDENTIAL_ISSUER_SECRET", "verifiable credentials", True),
)


def _is_https(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _weak(secret: str | None, minimum: int = MIN_SECRET_LENGTH) -> bool:
    return not secret or len(secret) < minimum or any(m in secret.lower() for m in _INSECURE_MARKERS)


def _weak_stellar_secret(secret: str | None) -> bool:
    """A Stellar secret seed is a fixed-length ``S…`` string; anything else is a placeholder."""
    if not secret:
        return True
    value = secret.strip()
    return (
        len(value) != STELLAR_SECRET_LENGTH
        or not value.startswith("S")
        or any(m in value.lower() for m in _INSECURE_MARKERS)
    )


def resolve_path(value: str) -> Path:
    """An absolute path, or a path relative to the repository root (source checkout) or the backend root
    (container image, where the backend is /app)."""
    path = Path(value)
    if path.is_absolute():
        return path
    for root in (_REPO_ROOT, _BACKEND_ROOT):
        candidate = root / path
        if candidate.exists():
            return candidate
    return _REPO_ROOT / path


def audited_contract_ids(path: Path, network: str = "mainnet") -> set[str]:
    """Contract ids listed for ``network`` in the audited-deployments file (see deploy/audited-deployments.json).
    Raises ``ValueError`` when the file is missing or malformed."""
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"the audited-deployments file {path} does not exist") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"the audited-deployments file {path} is not valid JSON") from exc
    entries = data.get(network) if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ValueError(f"the audited-deployments file {path} has no '{network}' list")
    ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        contract_id = entry.get("contract_id")
        audit = entry.get("audit")
        # An entry counts only with the audit it came from; an id alone is not evidence of a review.
        if isinstance(contract_id, str) and isinstance(audit, dict) and audit.get("report_url"):
            ids.add(contract_id)
    return ids


def _contract_problems(settings: Settings) -> list[str]:
    """Every contract the deployment calls must be an audited mainnet deployment."""
    required: list[tuple[str, str | None, bool]] = [
        # (env var, configured id, required even when empty)
        ("SOROBAN_CONTRACT_ID", settings.soroban_contract_id, True),
        # Optional features: only checked when they are switched on.
        ("WEB_AUTH_CONTRACT_ID", settings.web_auth_contract_id, False),
        ("ATTESTATION_CONTRACT_ID", settings.attestation_contract_id, False),
    ]
    missing = [name for name, value, needed in required if needed and not value]
    if missing:
        return [f"{name} is required" for name in missing]
    configured = [(name, value) for name, value, _ in required if value]
    try:
        audited = audited_contract_ids(resolve_path(settings.audited_deployments_file))
    except ValueError as exc:
        return [f"AUDITED_DEPLOYMENTS_FILE: {exc}"]
    return [
        f"{name} {value} is not an audited mainnet deployment in {settings.audited_deployments_file}"
        for name, value in configured
        if value not in audited
    ]


def mainnet_problems(settings: Settings) -> list[str]:
    """Everything that stops this configuration from running on mainnet (empty when it may)."""
    problems: list[str] = []

    if not settings.allow_mainnet:
        problems.append("ALLOW_MAINNET must be set to true (an explicit opt-in to real funds)")
    if settings.stellar_network != "mainnet" or settings.blockchain_mode != "mainnet":
        problems.append("STELLAR_NETWORK and BLOCKCHAIN_MODE must both be mainnet")
    if settings.stellar_network_passphrase != MAINNET_PASSPHRASE:
        problems.append("STELLAR_NETWORK_PASSPHRASE must be the mainnet passphrase")
    if settings.app_env != "production":
        problems.append("APP_ENV must be production")

    problems.extend(_contract_problems(settings))

    # Disputes must need more than one key.
    signers = [s for s in settings.stellar_arbiter_addresses if s]
    threshold = settings.stellar_arbiter_threshold
    if threshold < 2:
        problems.append("STELLAR_ARBITER_THRESHOLD must be at least 2 (a multisig arbiter)")
    if len(set(signers)) < max(threshold, 2):
        problems.append(
            "STELLAR_ARBITER_ADDRESSES must list at least STELLAR_ARBITER_THRESHOLD distinct signers"
        )

    # Transport.
    if not _is_https(settings.frontend_url):
        problems.append("FRONTEND_URL must be an https:// URL")
    if not _is_https(settings.public_api_url):
        problems.append("PUBLIC_API_URL must be set to the API's https:// URL")
    if any(not _is_https(origin) for origin in settings.cors_origins):
        problems.append("CORS_ORIGINS must only list https:// origins")
    for name, url in (
        ("STELLAR_HORIZON_URL", settings.stellar_horizon_url),
        ("STELLAR_SOROBAN_RPC_URL", settings.stellar_soroban_rpc_url),
        ("STELLAR_EXPLORER_BASE_URL", settings.stellar_explorer_base_url),
    ):
        if not _is_https(url) or "testnet" in url:
            problems.append(f"{name} must be a mainnet https:// endpoint")
    if not settings.cookie_secure:
        problems.append("COOKIE_SECURE must be true")

    # Secrets must be real, not the development defaults.
    for field, env_var, purpose, is_seed in SIGNING_SECRETS:
        value: str | None = getattr(settings, field)
        if _weak_stellar_secret(value) if is_seed else _weak(value):
            problems.append(f"{env_var} must be set to a real key (it signs {purpose})")
    if any(marker in settings.database_url for marker in _DEV_DATABASE_PASSWORDS):
        problems.append("DATABASE_URL uses the development database password")
    if _weak(settings.metrics_token, MIN_METRICS_TOKEN_LENGTH):
        problems.append(f"METRICS_TOKEN must be set (at least {MIN_METRICS_TOKEN_LENGTH} random characters)")

    # Fee sponsorship spends real XLM: the caps must be deliberate, not the development defaults.
    if settings.sponsor_daily_tx_limit <= 0 or settings.sponsor_daily_fee_limit_stroops <= 0:
        problems.append(
            "SPONSOR_DAILY_TX_LIMIT and SPONSOR_DAILY_FEE_LIMIT_STROOPS must be positive "
            "(set STELLAR_SPONSOR_SECRET empty to switch sponsorship off instead)"
        )
    if settings.sponsor_min_balance_xlm <= 0:
        problems.append("SPONSOR_MIN_BALANCE_XLM must be positive (the floor that stops sponsoring)")
    if settings.sponsor_low_balance_xlm <= settings.sponsor_min_balance_xlm:
        problems.append(
            "SPONSOR_LOW_BALANCE_XLM must be above SPONSOR_MIN_BALANCE_XLM (warn before stopping)"
        )

    # Operations that must not run against real accounts.
    if settings.seed_on_startup:
        problems.append("SEED_ON_STARTUP must be false")
    if settings.github_fixture_transport:
        problems.append("GITHUB_FIXTURE_TRANSPORT must be false (it serves recorded GitHub responses)")
    if settings.discovery_digest_trigger_enabled:
        problems.append("DISCOVERY_DIGEST_TRIGGER_ENABLED must be false (it sends digests on demand)")
    if settings.escrow_min_review_window_seconds < 86_400:
        problems.append("ESCROW_MIN_REVIEW_WINDOW_SECONDS must be at least one day (86400)")
    if not settings.sanctions_screening_enabled:
        problems.append("SANCTIONS_SCREENING_ENABLED must be true")
    if not (settings.sanctions_list_path or settings.sanctions_list_url):
        problems.append("SANCTIONS_LIST_PATH or SANCTIONS_LIST_URL must point at a sanctions list")
    return problems


def format_problems(problems: list[str]) -> str:
    lines = "\n".join(f"  - {p}" for p in problems)
    return f"Refusing to start on Stellar mainnet. Fix the following:\n{lines}"
