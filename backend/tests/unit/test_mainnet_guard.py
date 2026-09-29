"""The mainnet configuration guard: STELLAR_NETWORK=mainnet starts only with every requirement met."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from stellar_sdk import Keypair

from app.core.config import MAINNET_PASSPHRASE, Settings
from app.core.mainnet import audited_contract_ids, mainnet_problems

ESCROW = "CBCXG46FJPYBPWYZ24BWFVNJ6G2ILFAXHX2COETDNXYE6C5IJWAZ3M4C"
WEB_AUTH = "CB3GXQ2BW2AHSIWUITLVBKODKPUHIK5DLEPWIIWTKLTKLA6TE24PLSZX"
ATTESTATIONS = "CBXJVFUQHWECJZQSEBAFGHXLHP72PCPUX7XES42KVEMVAMZ26D5CZ33N"
SIGNERS = [Keypair.random().public_key for _ in range(3)]


def _audited(tmp_path: Path, *contract_ids: str, report: str | None = "https://audits.example/r.pdf") -> Path:
    """An audited-deployments file listing every given contract id (with an audit unless ``report`` is None)."""
    entries: list[dict[str, Any]] = []
    for contract_id in contract_ids or (ESCROW, WEB_AUTH, ATTESTATIONS):
        entry: dict[str, Any] = {"contract_id": contract_id, "wasm_hash": "ab" * 32}
        if report:
            entry["audit"] = {"firm": "Example Audits", "report_url": report}
        entries.append(entry)
    path = tmp_path / f"audited-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps({"testnet": [], "mainnet": entries}), encoding="utf-8")
    return path


def _valid(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """A configuration that satisfies every requirement; each test breaks exactly one thing."""
    values: dict[str, Any] = {
        "_env_file": None,
        "app_env": "production",
        "allow_mainnet": True,
        "stellar_network": "mainnet",
        "blockchain_mode": "mainnet",
        "stellar_network_passphrase": MAINNET_PASSPHRASE,
        "stellar_horizon_url": "https://horizon.stellar.org",
        "stellar_soroban_rpc_url": "https://rpc.mainnet.example.org",
        "stellar_explorer_base_url": "https://stellar.expert/explorer/public",
        "soroban_contract_id": ESCROW,
        "web_auth_contract_id": WEB_AUTH,
        "attestation_contract_id": ATTESTATIONS,
        "stellar_native_asset_contract_id": None,  # derived for the network
        "audited_deployments_file": str(_audited(tmp_path)),
        "stellar_arbiter_address": SIGNERS[0],
        "stellar_arbiter_addresses": SIGNERS,
        "stellar_arbiter_threshold": 2,
        "frontend_url": "https://bountyflow.example",
        "public_api_url": "https://api.bountyflow.example",
        "cors_origins": ["https://bountyflow.example"],
        "cookie_secure": True,
        "jwt_secret": "k" * 20 + "Q9x" * 10,
        "wallet_challenge_signing_secret": Keypair.random().secret,
        "stellar_sponsor_secret": Keypair.random().secret,
        "stellar_attester_secret": Keypair.random().secret,
        "credential_issuer_secret": Keypair.random().secret,
        "database_url": "postgresql+psycopg://bountyflow:s3cure-prod-pw@db.internal:5432/bountyflow",
        "metrics_token": "t" * 40,
        "seed_on_startup": False,
        "run_migrations_on_startup": False,
        "github_fixture_transport": False,
        "discovery_digest_trigger_enabled": False,
        "escrow_min_review_window_seconds": 86_400,
        "sanctions_list_url": "https://sanctions.example/sdn.csv",
        "kafka_enabled": True,
    }
    values.update(overrides)
    return values


def test_a_complete_mainnet_configuration_starts(tmp_path: Path) -> None:
    settings = Settings(**_valid(tmp_path))
    assert settings.stellar_network == "mainnet"
    assert mainnet_problems(settings) == []


def test_mainnet_with_defaults_refuses_with_the_whole_list(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(
            _env_file=None,
            stellar_network="mainnet",
            blockchain_mode="mainnet",
            stellar_network_passphrase=MAINNET_PASSPHRASE,
            stellar_native_asset_contract_id=None,
            soroban_contract_id=None,
            jwt_secret="dev-only-insecure-jwt-secret-change-me-0000000000",
            wallet_challenge_signing_secret=None,
            metrics_token=None,
            frontend_url="http://localhost:5173",
            audited_deployments_file=str(tmp_path / "missing.json"),
        )
    message = str(caught.value)
    assert "Refusing to start on Stellar mainnet" in message
    for fragment in (
        "ALLOW_MAINNET",
        "APP_ENV must be production",
        "SOROBAN_CONTRACT_ID is required",
        "STELLAR_ARBITER_THRESHOLD",
        "FRONTEND_URL must be an https:// URL",
        "PUBLIC_API_URL",
        "JWT_SECRET",
        "WALLET_CHALLENGE_SIGNING_SECRET",
        "STELLAR_SPONSOR_SECRET",
        "STELLAR_ATTESTER_SECRET",
        "CREDENTIAL_ISSUER_SECRET",
        "METRICS_TOKEN",
        "SANCTIONS_LIST_PATH or SANCTIONS_LIST_URL",
    ):
        assert fragment in message, fragment


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"allow_mainnet": False}, "ALLOW_MAINNET must be set to true"),
        ({"stellar_arbiter_threshold": 1}, "at least 2"),
        ({"stellar_arbiter_addresses": [SIGNERS[0], SIGNERS[0]]}, "distinct signers"),
        ({"frontend_url": "http://bountyflow.example"}, "FRONTEND_URL"),
        ({"public_api_url": None}, "PUBLIC_API_URL"),
        ({"cors_origins": ["http://bountyflow.example"]}, "CORS_ORIGINS"),
        ({"stellar_soroban_rpc_url": "https://soroban-testnet.stellar.org"}, "STELLAR_SOROBAN_RPC_URL"),
        (
            {"stellar_explorer_base_url": "https://stellar.expert/explorer/testnet"},
            "STELLAR_EXPLORER_BASE_URL",
        ),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"jwt_secret": "REPLACE-with-a-long-random-secret-dev-only"}, "JWT_SECRET"),
        (
            {"database_url": "postgresql+psycopg://bountyflow:bountyflow-local-dev-password@db:5432/x"},
            "DATABASE_URL",
        ),
        ({"metrics_token": None}, "METRICS_TOKEN"),
        ({"seed_on_startup": True}, "SEED_ON_STARTUP"),
        ({"github_fixture_transport": True}, "GITHUB_FIXTURE_TRANSPORT"),
        ({"discovery_digest_trigger_enabled": True}, "DISCOVERY_DIGEST_TRIGGER_ENABLED"),
        ({"escrow_min_review_window_seconds": 3600}, "ESCROW_MIN_REVIEW_WINDOW_SECONDS"),
        ({"sanctions_screening_enabled": False}, "SANCTIONS_SCREENING_ENABLED"),
        ({"sponsor_daily_tx_limit": 0}, "SPONSOR_DAILY_TX_LIMIT"),
        ({"sponsor_min_balance_xlm": 0}, "SPONSOR_MIN_BALANCE_XLM"),
        ({"sponsor_low_balance_xlm": 5, "sponsor_min_balance_xlm": 5}, "SPONSOR_LOW_BALANCE_XLM"),
    ],
)
def test_each_requirement_is_enforced(tmp_path: Path, overrides: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValidationError) as caught:
        Settings(**_valid(tmp_path, **overrides))
    assert fragment in str(caught.value)


@pytest.mark.parametrize(
    ("field", "env_var"),
    [
        ("stellar_sponsor_secret", "STELLAR_SPONSOR_SECRET"),
        ("stellar_attester_secret", "STELLAR_ATTESTER_SECRET"),
        ("credential_issuer_secret", "CREDENTIAL_ISSUER_SECRET"),
        ("wallet_challenge_signing_secret", "WALLET_CHALLENGE_SIGNING_SECRET"),
    ],
)
def test_every_signing_key_must_be_a_real_stellar_seed(tmp_path: Path, field: str, env_var: str) -> None:
    for value in (None, "", "REPLACE-me", "SNOTAREALSEED"):
        with pytest.raises(ValidationError) as caught:
            Settings(**_valid(tmp_path, **{field: value}))
        assert env_var in str(caught.value)


def test_every_configured_contract_must_be_audited(tmp_path: Path) -> None:
    only_escrow = str(_audited(tmp_path, ESCROW))
    with pytest.raises(ValidationError) as caught:
        Settings(**_valid(tmp_path, audited_deployments_file=only_escrow))
    message = str(caught.value)
    assert f"WEB_AUTH_CONTRACT_ID {WEB_AUTH} is not an audited mainnet deployment" in message
    assert f"ATTESTATION_CONTRACT_ID {ATTESTATIONS} is not an audited mainnet deployment" in message

    # Features that are switched off are not checked: only the escrow contract is mandatory.
    settings = Settings(
        **_valid(
            tmp_path,
            audited_deployments_file=only_escrow,
            web_auth_contract_id=None,
            attestation_contract_id=None,
            stellar_attester_secret=Keypair.random().secret,
        )
    )
    assert mainnet_problems(settings) == []


def test_the_superseded_escrow_contract_is_not_accepted_for_new_escrows(tmp_path: Path) -> None:
    """Escrows created on v1 keep using it (bounty_escrows.contract_id), but new ones must use the audited id."""
    v1 = "CDX6FN2MIGLHCMUJOU6C7FYP3QTNDL6BVIPEG4B5HAUEPU7NI4SFY4CY"
    with pytest.raises(ValidationError) as caught:
        Settings(**_valid(tmp_path, soroban_contract_id=v1))
    assert f"SOROBAN_CONTRACT_ID {v1} is not an audited mainnet deployment" in str(caught.value)


def test_audited_deployments_need_an_audit_report(tmp_path: Path) -> None:
    assert audited_contract_ids(_audited(tmp_path, ESCROW)) == {ESCROW}
    assert audited_contract_ids(_audited(tmp_path, ESCROW, report=None)) == set()
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        audited_contract_ids(broken)
    with pytest.raises(ValueError, match="does not exist"):
        audited_contract_ids(tmp_path / "nope.json")


def test_the_repository_registry_lists_no_mainnet_deployment_yet() -> None:
    """Nothing is audited yet, so the guard refuses every contract id until an audit lands."""
    registry = Path(__file__).resolve().parents[3] / "deploy" / "audited-deployments.json"
    assert audited_contract_ids(registry) == set()


def test_testnet_is_unaffected(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, audited_deployments_file=str(tmp_path / "missing.json"))
    assert settings.stellar_network == "testnet"
    assert mainnet_problems(settings) != []  # the same settings would be refused on mainnet
