"""Bounty lifecycle: every chain action end-to-end (real signed transactions executed by the `FakeStellarChain` escrow
model), partial funding, multi-position bounties, cancellation with on-chain assignments, every dispute resolution
path, and expiry."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utcnow
from app.modules.bounties.models import Bounty
from tests.integration.api.conftest import drain_events
from tests.integration.bugs.helpers import (
    action,
    arbiter,
    assign,
    assign_onchain,
    contributor,
    fund,
    funded,
    moderator,
    payout,
    published,
    requester,
    signed,
    status_of,
    submit_work,
)
from tests.support.fake_chain import FakeStellarChain


async def test_partial_funding_then_top_up(client_factory: Any, outbox_mail: Any) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req, reward_amount="10")
    bid = bounty["id"]
    first = await fund(req, bid, wallet, amount="4")
    assert first["transaction_type"] == "ESCROW_CREATE" and first["amount"] == "4.0000000"
    partial = await req.get(f"/bounties/{bid}")
    assert partial["status"] == "OPEN" and partial["funding_status"] == "PARTIALLY_FUNDED"
    assert (
        partial["escrow"]["state"] == "AWAITING_FUNDING" and partial["escrow"]["funded_amount"] == "4.0000000"
    )
    over = await req.request(
        "POST", f"/bounties/{bid}/funding/prepare", json={"wallet_address": wallet, "amount": "7"}
    )
    assert over.status_code == 422
    rest = await fund(req, bid, wallet)  # no amount: the remainder
    assert rest["transaction_type"] == "ESCROW_FUND" and rest["amount"] == "6.0000000"
    done = await req.get(f"/bounties/{bid}")
    assert done["status"] == "FUNDED" and done["funding_status"] == "FUNDED"
    assert done["escrow"]["funded_amount"] == "10.0000000"
    funding = await req.get(f"/bounties/{bid}/funding")
    assert funding["funding_status"] == "FUNDED" and len(funding["transactions"]) == 2


async def test_partially_funded_open_bounty_can_be_cancelled_and_refunded(
    client_factory: Any, outbox_mail: Any
) -> None:
    """BUG: OPEN -> CANCEL_REQUESTED was not a legal transition, so a partially funded bounty could not be
    cancelled at all and its deposit stayed locked (forever, if the bounty had no deadline)."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req, reward_amount="10")
    bid = bounty["id"]
    await fund(req, bid, wallet, amount="4")
    cancelled = await req.post(f"/bounties/{bid}/cancel", {"reason": "Budget was cut"})
    assert cancelled["status"] == "CANCEL_REQUESTED" and cancelled["funding_status"] == "REFUND_PENDING"
    refund = await action(req, bid, "REFUND", wallet)
    assert refund["amount"] == "4.0000000"
    final = await req.get(f"/bounties/{bid}")
    assert final["status"] == "CANCELLED" and final["funding_status"] == "REFUNDED"
    assert final["escrow"]["refunded_amount"] == "4.0000000"


async def test_multi_position_bounty_pays_each_contributor(client_factory: Any, outbox_mail: Any) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet, reward_amount="5", positions_available=2)
    bid = bounty["id"]
    assert bounty["total_reward"] == "10.0000000" and bounty["escrow"]["funded_amount"] == "10.0000000"
    alice, alice_wallet = await contributor(client_factory, "alice")
    bob, bob_wallet = await contributor(client_factory, "bob")
    alice_assignment = await assign(req, alice, bid)
    await assign(req, bob, bid)
    await assign_onchain(req, bid, wallet, alice_assignment)
    assert (await req.get(f"/bounties/{bid}"))["positions_filled"] == 2

    sub_a = await submit_work(alice, bid)
    await req.post(f"/submissions/{sub_a['id']}/approve", {})
    tx = await payout(req, bid, wallet, sub_a["id"])
    assert tx["destination_address"] == alice_wallet
    mid = await req.get(f"/bounties/{bid}")
    assert mid["status"] == "IN_PROGRESS"  # Bob still works
    assert mid["escrow"]["paid_out_amount"] == "5.0000000" and mid["funding_status"] == "FUNDED"

    sub_b = await submit_work(bob, bid)
    assert await status_of(req, bid) == "UNDER_REVIEW"
    await req.post(f"/submissions/{sub_b['id']}/approve", {})
    tx = await payout(req, bid, wallet, sub_b["id"])
    assert tx["destination_address"] == bob_wallet  # released directly (never assigned on-chain)
    final = await req.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED" and final["funding_status"] == "SETTLED"
    assert final["escrow"]["paid_out_amount"] == "10.0000000"


async def test_cancel_with_onchain_assignment_requires_consent(client_factory: Any, outbox_mail: Any) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet, reward_amount="8")
    bid = bounty["id"]
    dev, dev_wallet = await contributor(client_factory)
    assignment_id = await assign(req, dev, bid)
    await assign_onchain(req, bid, wallet, assignment_id)
    withdraw = await dev.request(
        "POST", f"/applications/{(await dev.get('/applications/me'))['items'][0]['id']}/withdraw"
    )
    assert withdraw.status_code == 409  # locked on-chain

    await req.post(f"/bounties/{bid}/cancel", {"reason": "Priorities changed"})
    early_consent = await dev.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "CONSENT_CANCEL", "wallet_address": dev_wallet},
    )
    assert early_consent.status_code == 409  # not requested on-chain yet
    await action(req, bid, "REQUEST_CANCEL", wallet)
    blocked = await req.request(
        "POST", f"/bounties/{bid}/chain/prepare", json={"action": "REFUND", "wallet_address": wallet}
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["details"]["contract_error"] == "AssignmentsOutstanding"

    await action(dev, bid, "CONSENT_CANCEL", dev_wallet)
    refund = await action(req, bid, "REFUND", wallet)
    assert refund["amount"] == "8.0000000"
    final = await req.get(f"/bounties/{bid}")
    assert final["status"] == "CANCELLED" and final["funding_status"] == "REFUNDED"
    assert final["positions_filled"] == 0


async def _disputed_onchain(
    client_factory: Any, outbox_mail: Any, *, positions: int = 1
) -> tuple[Any, str, Any, str, str, dict[str, Any], dict[str, Any]]:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet, reward_amount="6", positions_available=positions)
    bid = bounty["id"]
    dev, dev_wallet = await contributor(client_factory)
    assignment_id = await assign(req, dev, bid)
    await assign_onchain(req, bid, wallet, assignment_id)
    sub = await submit_work(dev, bid)
    dispute = await dev.post(
        f"/bounties/{bid}/disputes",
        {"reason": "The requester has ignored my submission for weeks."},
        expected=201,
    )
    await action(dev, bid, "RAISE_DISPUTE", dev_wallet, dispute_id=dispute["id"])
    frozen = await req.get(f"/disputes/{dispute['id']}")
    assert frozen["escrow_frozen_onchain"] is True
    return req, wallet, dev, dev_wallet, bid, sub, dispute


async def test_onchain_dispute_release_settles_submission(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    """BUG: a verified on-chain RESOLVE_DISPUTE payout left the submission SUBMITTED, which kept the bounty
    UNDER_REVIEW (still reviewable after payment) instead of settling it."""
    req, _wallet, dev, _dev_wallet, bid, sub, dispute = await _disputed_onchain(
        client_factory, outbox_mail, positions=2
    )
    mod = await moderator(client_factory, db_session)
    dismissed = await mod.request(
        "POST",
        f"/disputes/{dispute['id']}/resolve",
        json={"resolution": "DISMISSED", "note": "Frozen on-chain."},
    )
    assert dismissed.status_code == 422  # a frozen escrow must be routed
    resolved = await mod.post(
        f"/disputes/{dispute['id']}/resolve",
        {"resolution": "RELEASE_TO_CONTRIBUTOR", "note": "The work meets every acceptance criterion."},
    )
    assert resolved["requires_onchain_execution"] is True
    assert await status_of(req, bid) == "DISPUTED"
    tx = await action(mod, bid, "RESOLVE_DISPUTE", await arbiter(mod), dispute_id=dispute["id"])
    assert tx["amount"] == "6.0000000"

    detail = await req.get(f"/bounties/{bid}")
    assert detail["escrow"]["paid_out_amount"] == "6.0000000"
    assert detail["status"] == "FUNDED"  # one of two positions paid; nobody is working
    paid = await dev.get(f"/submissions/{sub['id']}")
    assert paid["status"] == "APPROVED" and paid["payment"]["payment_status"] == "CONFIRMED"
    again = await req.request("POST", f"/submissions/{sub['id']}/approve", json={})
    assert again.status_code == 409


async def test_onchain_dispute_refund_releases_claim(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    req, wallet, dev, _dev_wallet, bid, sub, dispute = await _disputed_onchain(client_factory, outbox_mail)
    mod = await moderator(client_factory, db_session)
    await mod.post(
        f"/disputes/{dispute['id']}/resolve",
        {"resolution": "REFUND_TO_REQUESTER", "note": "The submission does not meet the scope at all."},
    )
    await action(mod, bid, "RESOLVE_DISPUTE", await arbiter(mod), dispute_id=dispute["id"])
    detail = await req.get(f"/bounties/{bid}")
    assert detail["status"] == "FUNDED" and detail["positions_filled"] == 0
    rejected = await dev.get(f"/submissions/{sub['id']}")
    assert rejected["status"] == "REJECTED"
    # The requester can now cancel and refund without anyone's consent.
    await req.post(f"/bounties/{bid}/cancel", {"reason": "Closing after the dispute"})
    await action(req, bid, "REQUEST_CANCEL", wallet)
    refund = await action(req, bid, "REFUND", wallet)
    assert refund["amount"] == "6.0000000"
    assert await status_of(req, bid) == "CANCELLED"


async def test_onchain_dispute_during_cancellation_restores_cancel_request(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    """BUG: when the dispute was raised during an (off-chain) cancellation request, the verified on-chain
    resolution put the bounty back to FUNDED/IN_PROGRESS and silently dropped the cancellation."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet, reward_amount="6")
    bid = bounty["id"]
    dev, dev_wallet = await contributor(client_factory)
    assignment_id = await assign(req, dev, bid)
    await assign_onchain(req, bid, wallet, assignment_id)
    await req.post(f"/bounties/{bid}/cancel", {"reason": "We no longer need this feature"})
    dispute = await dev.post(
        f"/bounties/{bid}/disputes",
        {"reason": "I already did most of the work before the cancellation."},
        expected=201,
    )
    await action(dev, bid, "RAISE_DISPUTE", dev_wallet, dispute_id=dispute["id"])
    mod = await moderator(client_factory, db_session)
    await mod.post(
        f"/disputes/{dispute['id']}/resolve",
        {"resolution": "REFUND_TO_REQUESTER", "note": "No deliverable was ever submitted for review."},
    )
    await action(mod, bid, "RESOLVE_DISPUTE", await arbiter(mod), dispute_id=dispute["id"])
    assert await status_of(req, bid) == "CANCEL_REQUESTED"
    await action(req, bid, "REQUEST_CANCEL", wallet)
    await action(req, bid, "REFUND", wallet)
    assert await status_of(req, bid) == "CANCELLED"


async def test_raise_dispute_onchain_requires_onchain_assignment(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    """BUG: the escrow could be frozen on-chain for a contributor who was never assigned on-chain. The contract
    can only leave `Disputed` through resolve_dispute for an *assigned* contributor, so the funds were locked
    forever. The backend must refuse the freeze."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)  # accepted, but not assigned on-chain
    dispute = await req.post(
        f"/bounties/{bid}/disputes", {"reason": "The contributor stopped responding entirely."}, expected=201
    )
    refused = await req.request(
        "POST",
        f"/bounties/{bid}/chain/prepare",
        json={"action": "RAISE_DISPUTE", "wallet_address": wallet, "dispute_id": dispute["id"]},
    )
    assert refused.status_code == 409, refused.text
    # The off-chain path still works: dismiss and continue.
    mod = await moderator(client_factory, db_session)
    await mod.post(
        f"/disputes/{dispute['id']}/resolve", {"resolution": "DISMISSED", "note": "Please keep talking."}
    )
    assert await status_of(req, bid) == "IN_PROGRESS"


async def test_offchain_dispute_refund_and_dismiss_paths(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)
    sub = await submit_work(dev, bid)
    mod = await moderator(client_factory, db_session)

    first = await req.post(
        f"/bounties/{bid}/disputes",
        {"reason": "The submission ignores the acceptance criteria."},
        expected=201,
    )
    await mod.post(f"/disputes/{first['id']}/assign")
    await mod.post(f"/disputes/{first['id']}/resolve", {"resolution": "DISMISSED", "note": "Keep reviewing."})
    assert await status_of(req, bid) == "UNDER_REVIEW"

    second = await req.post(
        f"/bounties/{bid}/disputes", {"reason": "Still not meeting the acceptance criteria."}, expected=201
    )
    await mod.post(
        f"/disputes/{second['id']}/resolve",
        {"resolution": "REFUND_TO_REQUESTER", "note": "The work is out of scope entirely."},
    )
    assert (await dev.get(f"/submissions/{sub['id']}"))["status"] == "REJECTED"
    detail = await req.get(f"/bounties/{bid}")
    assert detail["status"] == "FUNDED" and detail["positions_filled"] == 0


async def test_expiry_job_and_refund_of_expired_funded_bounty(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    from worker.jobs.lifecycle import run_lifecycle_once

    req, wallet = await requester(client_factory, outbox_mail)
    open_bounty = await published(req)
    funded_idle = await funded(req, wallet, reward_amount="3")
    funded_busy = await funded(req, wallet, reward_amount="4")
    applicant, _ = await contributor(client_factory, "late")
    app = await applicant.post(
        f"/bounties/{open_bounty['id']}/applications",
        {"cover_message": "I would love to take this one on right away."},
        expected=201,
    )
    worker, _ = await contributor(client_factory, "busy")
    await assign(req, worker, funded_busy["id"])
    past = utcnow() - timedelta(minutes=5)
    await db_session.execute(
        update(Bounty)
        .where(Bounty.id.in_([open_bounty["id"], funded_idle["id"], funded_busy["id"]]))
        .values(application_deadline=past)
    )
    await db_session.commit()

    results = await run_lifecycle_once()
    assert results["expired"] == 2
    assert await status_of(req, open_bounty["id"]) == "EXPIRED"
    assert await status_of(req, funded_idle["id"]) == "EXPIRED"
    assert await status_of(req, funded_busy["id"]) == "IN_PROGRESS"
    assert (await applicant.get("/applications/me"))["items"][0]["status"] == "REJECTED"
    assert app["status"] == "PENDING"

    await drain_events()
    notes = await applicant.get("/notifications")
    assert "BOUNTY_EXPIRED" in {n["notification_type"] for n in notes["items"]}

    # The idle funded bounty's escrow can be refunded straight from EXPIRED.
    await action(req, funded_idle["id"], "REQUEST_CANCEL", wallet)
    refund = await action(req, funded_idle["id"], "REFUND", wallet)
    assert refund["amount"] == "3.0000000"
    assert await status_of(req, funded_idle["id"]) == "CANCELLED"
    # Running again is a no-op.
    assert (await run_lifecycle_once())["expired"] == 0


async def test_expiry_limit_is_not_starved_by_ineligible_bounties(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    """BUG: the job locked the first N overdue OPEN/FUNDED rows and only then skipped those with live
    assignments, so N bounties with a (completed) assignment could starve every eligible bounty forever."""
    from app.modules.bounties.service import expire_overdue

    req, wallet = await requester(client_factory, outbox_mail)
    busy = []
    for _ in range(2):
        bounty = await funded(req, wallet, reward_amount="2")
        dev, _ = await contributor(client_factory)
        await assign(req, dev, bounty["id"])
        busy.append(bounty["id"])
    idle = await published(req)
    now = utcnow()
    await db_session.execute(
        update(Bounty).where(Bounty.id.in_(busy)).values(application_deadline=now - timedelta(days=2))
    )
    await db_session.execute(
        update(Bounty).where(Bounty.id == idle["id"]).values(application_deadline=now - timedelta(hours=1))
    )
    # Mark the busy bounties FUNDED again (as if their only position was paid and nobody else joined).
    await db_session.execute(update(Bounty).where(Bounty.id.in_(busy)).values(status="FUNDED"))
    await db_session.commit()
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as session:
        expired = await expire_overdue(session, limit=2)
    assert expired == 1
    assert await status_of(req, idle["id"]) == "EXPIRED"


async def test_cancellation_notifies_contributors_and_applicants(
    client_factory: Any, outbox_mail: Any
) -> None:
    """BUG: the cancel/expiry/deadline events never carried `contributor_ids` / `applicant_ids`, so the
    notification worker could only ever tell the requester."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet, positions_available=2, reward_amount="2")
    bid = bounty["id"]
    worker, _ = await contributor(client_factory, "worker")
    await assign(req, worker, bid)
    waiting, _ = await contributor(client_factory, "waiting")
    await waiting.post(
        f"/bounties/{bid}/applications",
        {"cover_message": "Happy to help with the second position."},
        expected=201,
    )
    await req.post(f"/bounties/{bid}/cancel", {"reason": "The project was shelved"})
    await drain_events()
    worker_notes = await worker.get("/notifications")
    assert "BOUNTY_CANCELLED" in {n["notification_type"] for n in worker_notes["items"]}
    waiting_notes = await waiting.get("/notifications")
    assert "BOUNTY_CANCELLED" in {n["notification_type"] for n in waiting_notes["items"]}

    await action(req, bid, "REQUEST_CANCEL", wallet)
    await action(req, bid, "REFUND", wallet)
    await drain_events()
    worker_notes = await worker.get("/notifications")
    titles = [n["title"] for n in worker_notes["items"] if n["notification_type"] == "BOUNTY_CANCELLED"]
    assert "Bounty cancelled" in titles


async def test_deadline_reminder_reaches_assigned_contributors(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    from app.db.session import get_sessionmaker
    from app.modules.bounties.service import notify_deadlines

    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bounty["id"])
    await db_session.execute(
        update(Bounty)
        .where(Bounty.id == bounty["id"])
        .values(application_deadline=None, completion_deadline=utcnow() + timedelta(hours=3))
    )
    await db_session.commit()
    async with get_sessionmaker()() as session:
        assert await notify_deadlines(session) == 1
    async with get_sessionmaker()() as session:
        assert await notify_deadlines(session) == 0  # once per bounty
    await drain_events()
    notes = await dev.get("/notifications")
    assert any(n["title"] == "Deadline approaching" for n in notes["items"])


async def test_escrow_freeze_is_refused_once_the_dispute_is_closed(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, chain: FakeStellarChain
) -> None:
    """BUG: a RAISE_DISPUTE prepared while the dispute was open could still be submitted after a moderator
    closed the dispute off-chain. The escrow was then frozen on-chain with no open dispute to route it (a
    DISMISSED dispute can never be executed on-chain), locking the funds."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, dev_wallet = await contributor(client_factory)
    assignment_id = await assign(req, dev, bid)
    await assign_onchain(req, bid, wallet, assignment_id)
    dispute = await dev.post(
        f"/bounties/{bid}/disputes",
        {"reason": "The requester is unresponsive to every message."},
        expected=201,
    )
    prepared = await dev.post(
        f"/bounties/{bid}/chain/prepare",
        {"action": "RAISE_DISPUTE", "wallet_address": dev_wallet, "dispute_id": dispute["id"]},
    )
    mod = await moderator(client_factory, db_session)
    await mod.post(
        f"/disputes/{dispute['id']}/resolve", {"resolution": "DISMISSED", "note": "Resolved by chat."}
    )
    late = await dev.request(
        "POST", f"/transactions/{prepared['transaction']['id']}/submit", json=signed(prepared, dev_wallet)
    )
    assert late.status_code == 409, late.text
    assert prepared["transaction"]["transaction_hash"] not in chain.submitted  # never sent to the network
    detail = await req.get(f"/bounties/{bid}")
    assert detail["escrow"]["state"] == "FUNDED" and detail["status"] == "IN_PROGRESS"


async def test_dispute_can_be_closed_after_an_in_flight_payout_completes_the_bounty(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, chain: FakeStellarChain
) -> None:
    """BUG: a payout submitted before the dispute was raised can confirm while the bounty is DISPUTED, which
    completes the bounty. Resolving the still-open dispute then tried COMPLETED -> previous status (illegal),
    so the dispute could never be closed (409 forever)."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)
    sub = await submit_work(dev, bid)
    await req.post(f"/submissions/{sub['id']}/approve", {})
    chain.outcomes_down = True  # the payout lands on-chain, but its outcome cannot be read yet
    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    tx = await req.post(f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet))
    assert tx["status"] == "SUBMITTED"
    dispute = await dev.post(
        f"/bounties/{bid}/disputes",
        {"reason": "Raising a dispute while my payout is in flight."},
        expected=201,
    )
    chain.outcomes_down = False
    assert (await req.get(f"/transactions/{tx['id']}"))["status"] == "CONFIRMED"
    assert await status_of(req, bid) == "COMPLETED"
    mod = await moderator(client_factory, db_session)
    resolved = await mod.post(
        f"/disputes/{dispute['id']}/resolve",
        {"resolution": "DISMISSED", "note": "Already paid out on-chain."},
    )
    assert resolved["status"] == "DISMISSED"
    assert await status_of(req, bid) == "COMPLETED"
