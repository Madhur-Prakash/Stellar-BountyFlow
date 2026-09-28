"""Regression tests for residual-risk hardening: storage-rejected input, and escrow state never downgraded."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.blockchain.reconciliation import apply_snapshot
from app.modules.payments.models import BountyEscrow, EscrowState
from tests.integration.api.conftest import bounty_payload, register


async def test_nul_bytes_in_free_text_are_a_client_error_not_a_crash(client_factory: Any) -> None:
    client = client_factory()
    await register(client)
    response = await client.request(
        "POST", "/bounties", json=bounty_payload(title="Escrow widget \x00 with a NUL byte")
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    admin_like = await client.request("GET", "/bounties", params={"q": "abc\x00def"})
    assert admin_like.status_code == 200


def _escrow(state: EscrowState, funded: str) -> BountyEscrow:
    return BountyEscrow(
        bounty_id=None,
        network="testnet",
        onchain_bounty_id="ab" * 32,
        asset_identifier="native",
        reward_per_position=Decimal("5"),
        positions=1,
        required_amount=Decimal("5"),
        funded_amount=Decimal(funded),
        paid_out_amount=Decimal("0"),
        refunded_amount=Decimal("0"),
        state=state,
    )


def test_missing_onchain_read_never_downgrades_a_known_escrow() -> None:
    funded = _escrow(EscrowState.FUNDED, "5")
    assert apply_snapshot(funded, None) == []
    assert funded.state == EscrowState.FUNDED
    assert funded.funded_amount == Decimal("5")

    fresh = _escrow(EscrowState.NOT_CREATED, "0")
    apply_snapshot(fresh, None)
    assert fresh.state == EscrowState.NOT_CREATED
