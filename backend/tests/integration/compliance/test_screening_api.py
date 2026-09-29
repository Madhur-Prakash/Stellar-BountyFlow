"""Sanctions screening at wallet verification and before chain actions, the admin list, and list sync."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from stellar_sdk import Keypair

from app.core.config import get_settings
from app.modules.compliance import screening
from app.modules.compliance.models import ScreeningEntry, ScreeningSource
from app.modules.users.models import Role
from tests.integration.api.conftest import KEYRING, chain_action, link_wallet, register, sign_xdr
from tests.integration.compliance.helpers import approved_submission, handle, published, requester, staff
from worker.jobs import compliance as jobs


async def _verify(client: Any, keypair: Keypair) -> Any:
    KEYRING[keypair.public_key] = keypair
    challenge = await client.post("/wallets/challenge", {"public_address": keypair.public_key})
    return await client.request(
        "POST",
        "/wallets/verify",
        json={
            "public_address": keypair.public_key,
            "signed_challenge_xdr": sign_xdr(challenge["challenge_xdr"], keypair.public_key),
        },
    )


async def test_a_listed_wallet_cannot_be_verified_and_staff_see_why(
    client_factory: Any, db_session: AsyncSession
) -> None:
    admin = await staff(client_factory, db_session)
    listed = Keypair.random()
    entry = await admin.post(
        "/admin/compliance/screening/entries",
        {"address": listed.public_key, "reason": "Linked to a sanctioned exchange (case 42)"},
        expected=201,
    )
    assert entry["source"] == "MANUAL" and entry["added_by"]["username"] == admin.me["username"]
    duplicate = await admin.request(
        "POST", "/admin/compliance/screening/entries", json={"address": listed.public_key, "reason": "again"}
    )
    assert duplicate.status_code == 409
    invalid = await admin.request(
        "POST", "/admin/compliance/screening/entries", json={"address": "G" + "A" * 55, "reason": "typo"}
    )
    assert invalid.status_code == 422

    user = client_factory()
    await register(user, handle("screened"))
    blocked = await _verify(user, listed)
    assert blocked.status_code == 403
    error = blocked.json()["error"]
    assert error["code"] == "screening_blocked" and error["message"] == screening.BLOCKED_MESSAGE
    assert "case 42" not in blocked.text
    assert await user.get("/wallets") == []

    decisions = await admin.get("/admin/compliance/screening/decisions")
    decision = decisions["items"][0]
    assert decision["result"] == "blocked" and decision["address"] == listed.public_key
    assert (
        decision["context"] == "wallet_verification" and decision["user"]["username"] == user.me["username"]
    )
    assert decision["matches"][0]["reason"] == "Linked to a sanctioned exchange (case 42)"

    await link_wallet(user)  # a clean wallet is cleared, and that decision is logged too
    cleared = await admin.get("/admin/compliance/screening/decisions", params={"result": "cleared"})
    assert cleared["total"] == 1

    moderator = await staff(client_factory, db_session, Role.MODERATOR)
    assert (await moderator.get("/admin/compliance/screening/entries"))["total"] == 1
    forbidden = await moderator.request(
        "POST", f"/admin/compliance/screening/entries/{entry['id']}/remove", json={"note": "not mine"}
    )
    assert forbidden.status_code == 403

    removed = await admin.post(
        f"/admin/compliance/screening/entries/{entry['id']}/remove", {"note": "Cleared after review"}
    )
    assert removed["removed_at"] and removed["removal_note"] == "Cleared after review"
    assert (await _verify(user, listed)).status_code == 200
    status = await admin.get("/admin/compliance/screening/status")
    assert status["enabled"] is True and status["provider"] == "denylist" and status["manual_entries"] == 0


async def test_contract_addresses_are_screened_too(client_factory: Any, db_session: AsyncSession) -> None:
    """A passkey smart wallet is a C… contract account; it receives money and must be screened like any other."""
    admin = await staff(client_factory, db_session)
    smart_wallet = "CB3GXQ2BW2AHSIWUITLVBKODKPUHIK5DLEPWIIWTKLTKLA6TE24PLSZX"
    await admin.post(
        "/admin/compliance/screening/entries",
        {"address": smart_wallet, "reason": "Smart wallet on a sanctions list"},
        expected=201,
    )
    entries = await admin.get("/admin/compliance/screening/entries", params={"q": smart_wallet})
    assert [e["address"] for e in entries["items"]] == [smart_wallet]

    result = await screening.get_provider().screen(db_session, [smart_wallet])
    assert result[smart_wallet].blocked


async def test_screening_runs_before_funding_and_before_payout(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    admin = await staff(client_factory, db_session)
    owner, owner_wallet = await requester(client_factory, outbox_mail, "funder")
    bounty = await published(owner, reward_amount="3")

    entry = await admin.post(
        "/admin/compliance/screening/entries",
        {"address": owner_wallet, "reason": "Court order 7"},
        expected=201,
    )
    refused = await owner.request(
        "POST", f"/bounties/{bounty['id']}/funding/prepare", json={"wallet_address": owner_wallet}
    )
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "screening_blocked"
    decision = (await admin.get("/admin/compliance/screening/decisions"))["items"][0]
    assert decision["context"] == "chain:FUND" and decision["bounty_id"] == bounty["id"]

    await admin.post(f"/admin/compliance/screening/entries/{entry['id']}/remove", {"note": "Order lifted"})
    await chain_action(owner, f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": owner_wallet})

    _, contributor_wallet, submission = await approved_submission(client_factory, owner, bounty["id"])
    await admin.post(
        "/admin/compliance/screening/entries",
        {"address": contributor_wallet, "reason": "SDN match"},
        expected=201,
    )
    payout = await owner.request(
        "POST",
        f"/bounties/{bounty['id']}/payouts/prepare",
        json={"wallet_address": owner_wallet, "submission_id": submission["id"]},
    )
    assert payout.status_code == 403 and payout.json()["error"]["code"] == "screening_blocked"
    decision = (await admin.get("/admin/compliance/screening/decisions"))["items"][0]
    assert decision["context"] == "chain:PAYOUT" and decision["address"] == contributor_wallet


async def test_the_configured_list_syncs_and_fails_static(
    client_factory: Any, db_session: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = Keypair.random().public_key, Keypair.random().public_key
    sdn = tmp_path / "sdn.csv"
    sdn.write_text(
        f'36,"EXAMPLE EXCHANGE","-0- ",... "Digital Currency Address - XBT 1BoatSLRHtKNngkdXEeobR76b53LETtpyT; '
        f'Digital Currency Address - XLM {first}; alt. Digital Currency Address - ETH 0xabc."\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SANCTIONS_LIST_PATH", str(sdn))
    monkeypatch.setenv("SANCTIONS_LIST_NAME", "OFAC SDN")
    get_settings.cache_clear()

    status = await jobs.run_sanctions_once()
    assert status["format"] == "ofac-sdn" and status["added"] == 1 and status["error"] is None
    entry = await db_session.scalar(select(ScreeningEntry).where(ScreeningEntry.address == first))
    assert entry is not None and entry.source == ScreeningSource.LIST and entry.list_name == "OFAC SDN"

    user = client_factory()
    await register(user, handle("listed"))
    keypair = Keypair.random()
    sdn.write_text(f"# refreshed list\n{keypair.public_key}  # added\n{second}\n", encoding="utf-8")
    status = await jobs.run_sanctions_once()
    assert status["added"] == 2 and status["removed"] == 1
    assert (await _verify(user, keypair)).status_code == 403

    sdn.write_text("# nothing\n", encoding="utf-8")  # an empty download keeps the previous entries
    status = await jobs.run_sanctions_once()
    assert status["error"] and status["entries"] == 2
    active = await db_session.scalar(
        select(func.count(ScreeningEntry.id)).where(
            ScreeningEntry.source == ScreeningSource.LIST, ScreeningEntry.removed_at.is_(None)
        )
    )
    assert active == 2

    sdn.unlink()  # unreadable: kept as well, and reported
    status = await jobs.run_sanctions_once()
    assert "cannot read" in status["error"]
    admin = await staff(client_factory, db_session)
    shown = await admin.get("/admin/compliance/screening/status")
    assert shown["list"]["configured"] is True and shown["list_entries"] == 2 and shown["list"]["error"]
