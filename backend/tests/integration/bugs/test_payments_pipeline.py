"""Payments pipeline regressions: RPC outages while polling, concurrent writes during submit/verify, failed
contract execution, expired unsigned transactions, invalid input, the sweep job, and concurrent prepares."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis import get_redis
from app.core.security import utcnow
from app.db.session import get_sessionmaker
from app.modules.payments.models import BlockchainTransaction, PaymentRecord, PaymentStatus, TxStatus
from tests.integration.bugs.helpers import (
    assign,
    contributor,
    fund,
    funded,
    payout,
    published,
    requester,
    signed,
    status_of,
    submit_work,
)
from tests.support.fake_chain import FakeStellarChain


async def _bump_bounty(bid: str) -> None:
    """A concurrent writer (e.g. someone bookmarking) bumps the bounty's optimistic version."""
    async with get_sessionmaker()() as other:
        await other.execute(
            text(
                "UPDATE bounties SET version_id = version_id + 1, bookmarks_count = bookmarks_count + 1 "
                "WHERE id = :id"
            ),
            {"id": bid},
        )
        await other.commit()


async def test_transaction_poll_survives_rpc_outage(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    """BUG: GET /transactions/{id} rolled back on ChainUnavailable and then read the expired ORM row
    (MissingGreenlet -> 500). A poll during an RPC outage must return the SUBMITTED transaction."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    chain.outcomes_down = True
    prepared = await req.post(f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    submitted = await req.post(
        f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet)
    )
    assert submitted["status"] == "SUBMITTED"
    polled = await req.get(f"/transactions/{submitted['id']}")
    assert polled["status"] == "SUBMITTED"
    assert await status_of(req, bounty["id"]) == "FUNDING_PENDING"

    chain.outcomes_down = False
    polled = await req.get(f"/transactions/{submitted['id']}")
    assert polled["status"] == "CONFIRMED"
    assert await status_of(req, bounty["id"]) == "FUNDED"


async def test_submit_and_verify_survive_concurrent_bounty_writes(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    """BUG: locked re-reads of the bounty returned the stale identity-map copy (loaded via the transaction's
    joined relationship before the network round trip), so a concurrent write in that window made the commit
    fail with StaleDataError -> 500 *after* the transaction was already submitted to the chain."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    bid = bounty["id"]

    async def race() -> None:
        await _bump_bounty(bid)

    chain.on_submit = race
    chain.on_outcome = race
    prepared = await req.post(f"/bounties/{bid}/funding/prepare", {"wallet_address": wallet})
    tx = await req.post(f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet))
    assert tx["status"] == "CONFIRMED"
    detail = await req.get(f"/bounties/{bid}")
    assert detail["status"] == "FUNDED" and detail["funding_status"] == "FUNDED"


async def test_prepare_rejects_malformed_amount_with_422(client_factory: Any, outbox_mail: Any) -> None:
    """BUG: a malformed/over-precise/negative `amount` raised ValueError inside planning -> 500."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req, reward_amount="10")
    for amount in ("abc", "-5", "1.123456789", "0", "NaN"):
        response = await req.request(
            "POST",
            f"/bounties/{bounty['id']}/funding/prepare",
            json={"wallet_address": wallet, "amount": amount},
        )
        assert response.status_code == 422, (amount, response.text)
        assert response.json()["error"]["code"] == "validation_error"
    over = await req.request(
        "POST", f"/bounties/{bounty['id']}/funding/prepare", json={"wallet_address": wallet, "amount": "11"}
    )
    assert over.status_code == 422


async def test_failed_funding_execution_reopens_bounty(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    bid = bounty["id"]
    chain.fail_next_execution = 5
    prepared = await req.post(f"/bounties/{bid}/funding/prepare", {"wallet_address": wallet})
    tx = await req.post(f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet))
    assert tx["status"] == "FAILED" and tx["failure_reason"]
    detail = await req.get(f"/bounties/{bid}")
    assert detail["status"] == "OPEN" and detail["funding_status"] == "UNFUNDED"
    # A fresh attempt succeeds.
    await fund(req, bid, wallet)
    assert await status_of(req, bid) == "FUNDED"


async def test_failed_payout_marks_payment_failed_and_retry_succeeds(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)
    sub = await submit_work(dev, bid)
    await req.post(f"/submissions/{sub['id']}/approve", {})

    chain.fail_next_execution = 11
    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    tx = await req.post(f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet))
    assert tx["status"] == "FAILED"
    after = await req.get(f"/submissions/{sub['id']}")
    assert after["payment"]["payment_status"] == "FAILED"
    assert await status_of(req, bid) == "UNDER_REVIEW"  # approved, still unpaid

    await payout(req, bid, wallet, sub["id"])
    final = await req.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED" and final["funding_status"] == "SETTLED"


async def test_expired_unsigned_transaction_is_refused(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, chain: FakeStellarChain
) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    prepared = await req.post(f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    tx_id = prepared["transaction"]["id"]
    await db_session.execute(
        update(BlockchainTransaction)
        .where(BlockchainTransaction.id == tx_id)
        .values(expires_at=utcnow() - timedelta(minutes=5))
    )
    await db_session.commit()
    body = signed(prepared, wallet)  # a valid signature does not revive an expired transaction
    late = await req.request("POST", f"/transactions/{tx_id}/submit", json=body)
    assert late.status_code == 409
    assert (await req.get(f"/transactions/{tx_id}"))["status"] == "EXPIRED"
    assert await status_of(req, bounty["id"]) == "OPEN"
    again = await req.request("POST", f"/transactions/{tx_id}/submit", json=body)
    assert again.status_code == 409
    assert chain.submitted == []


async def test_sweep_job_expires_unsigned_and_verifies_submitted(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, chain: FakeStellarChain
) -> None:
    from worker.jobs.reconciliation import run_reconciliation_once

    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)
    sub = await submit_work(dev, bid)
    await req.post(f"/submissions/{sub['id']}/approve", {})

    # 1. An unsigned payout that is never signed: the sweep expires it and re-arms the payment record.
    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    stale_id = prepared["transaction"]["id"]
    assert (await req.get(f"/submissions/{sub['id']}"))["payment"]["payment_status"] == "SIGNATURE_REQUIRED"
    await db_session.execute(
        update(BlockchainTransaction)
        .where(BlockchainTransaction.id == stale_id)
        .values(expires_at=utcnow() - timedelta(minutes=1))
    )
    await db_session.commit()
    assert await run_reconciliation_once() >= 1
    assert (await req.get(f"/transactions/{stale_id}"))["status"] == "EXPIRED"
    assert (await req.get(f"/submissions/{sub['id']}"))["payment"]["payment_status"] == "CREATED"

    # 2. A payout submitted during an RPC outage stays SUBMITTED until the sweep verifies it.
    chain.outcomes_down = True
    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    tx = await req.post(f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet))
    assert tx["status"] == "SUBMITTED"
    assert await run_reconciliation_once() == 0  # outage: deferred, nothing lost
    chain.outcomes_down = False
    assert await run_reconciliation_once() == 1
    final = await req.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED"
    payment = await db_session.scalar(
        select(PaymentRecord)
        .where(PaymentRecord.submission_id == sub["id"])
        .execution_options(populate_existing=True)
    )
    assert payment is not None and payment.payment_status == PaymentStatus.CONFIRMED


async def test_concurrent_fund_prepares_never_500(client_factory: Any, outbox_mail: Any) -> None:
    """BUG: two simultaneous first prepares both inserted the escrow row -> IntegrityError -> 500."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    results = await asyncio.gather(
        *[
            req.request("POST", f"/bounties/{bounty['id']}/funding/prepare", json={"wallet_address": wallet})
            for _ in range(3)
        ]
    )
    codes = sorted(r.status_code for r in results)
    assert all(code in (200, 409) for code in codes), [r.text for r in results]
    assert 200 in codes


async def test_identical_prepare_reuses_the_unsigned_transaction(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, chain: FakeStellarChain
) -> None:
    """BUG: identical inputs (same wallet sequence number, contract arguments and one-second time bounds: a double
    click on "prepare", or preparing again right after the sweep expired the unsigned transaction) build a
    byte-identical Stellar transaction. Its hash is unique per network, so the second prepare crashed with an
    IntegrityError (500). The same unsigned transaction is now handed out again, and is signed and applied once."""
    from worker.jobs.reconciliation import run_reconciliation_once

    req, wallet = await requester(client_factory, outbox_mail)
    deadline = (utcnow() + timedelta(days=10)).isoformat()  # fixes the escrow deadline argument
    bounty = await published(req, completion_deadline=deadline)
    bid = bounty["id"]
    chain.freeze_clock()  # identical time bounds however long the steps below take
    path = f"/bounties/{bid}/funding/prepare"
    first = await req.post(path, {"wallet_address": wallet})
    tx_id = first["transaction"]["id"]
    double_click = await req.post(path, {"wallet_address": wallet})
    assert double_click["transaction"]["id"] == tx_id
    assert double_click["transaction"]["transaction_hash"] == first["transaction"]["transaction_hash"]
    assert double_click["transaction"]["status"] == "SIGNATURE_REQUIRED"
    burst = await asyncio.gather(
        *[req.request("POST", path, json={"wallet_address": wallet}) for _ in range(3)]
    )
    assert all(r.status_code in (200, 409) for r in burst), [r.text for r in burst]
    assert {r.json()["transaction"]["id"] for r in burst if r.status_code == 200} <= {tx_id}

    # Never signed: the sweep expires it; preparing again re-arms the very same transaction.
    await db_session.execute(
        update(BlockchainTransaction)
        .where(BlockchainTransaction.id == tx_id)
        .values(expires_at=utcnow() - timedelta(minutes=1))
    )
    await db_session.commit()
    await run_reconciliation_once()
    assert (await req.get(f"/transactions/{tx_id}"))["status"] == "EXPIRED"
    again = await req.post(path, {"wallet_address": wallet})
    assert again["transaction"]["id"] == tx_id and again["transaction"]["status"] == "SIGNATURE_REQUIRED"
    rows = await db_session.scalar(
        select(func.count(BlockchainTransaction.id)).where(BlockchainTransaction.bounty_id == bid)
    )
    assert rows == 1

    tx = await req.post(f"/transactions/{tx_id}/submit", signed(again, wallet))
    assert tx["status"] == "CONFIRMED"
    assert chain.submitted == [first["transaction"]["transaction_hash"]]
    assert await status_of(req, bid) == "FUNDED"


async def test_duplicate_submit_is_idempotent(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    prepared = await req.post(f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    tx_id = prepared["transaction"]["id"]
    body = signed(prepared, wallet)
    results = await asyncio.gather(
        *[req.request("POST", f"/transactions/{tx_id}/submit", json=body) for _ in range(3)]
    )
    assert all(r.status_code in (200, 409) for r in results), [r.text for r in results]
    again = await req.post(f"/transactions/{tx_id}/submit", body)
    assert again["status"] == "CONFIRMED"
    detail = await req.get(f"/bounties/{bounty['id']}")
    assert detail["escrow"]["funded_amount"] == detail["total_reward"]
    # The network received and applied the transaction exactly once.
    assert chain.submitted == [prepared["transaction"]["transaction_hash"]]
    assert chain.submit_calls == 1


async def test_verification_is_applied_once_even_with_a_stale_session_copy(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    """BUG: `_load_tx(for_update=True)` returned the caller's stale identity-map copy of the transaction, so a
    poll that had read the row as SUBMITTED re-applied a verification another worker had already committed
    (second PAYMENT_CONFIRMED event -> duplicate notifications and emails)."""
    from app.modules.payments.service import verify_transaction

    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)
    sub = await submit_work(dev, bid)
    await req.post(f"/submissions/{sub['id']}/approve", {})
    chain.outcomes_down = True
    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    tx = await req.post(f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet))
    assert tx["status"] == "SUBMITTED"
    chain.outcomes_down = False

    import uuid as _uuid

    tx_id = _uuid.UUID(tx["id"])
    async with get_sessionmaker()() as poller, get_sessionmaker()() as worker:
        seen = await poller.get(BlockchainTransaction, tx_id)
        assert seen is not None and seen.status == TxStatus.SUBMITTED
        await poller.commit()  # the poller's copy stays in its identity map (expire_on_commit=False)
        assert await verify_transaction(worker, tx_id) == TxStatus.CONFIRMED
        assert await verify_transaction(poller, tx_id) == TxStatus.CONFIRMED

    async with get_sessionmaker()() as check:
        confirmations = (
            await check.execute(
                text("SELECT count(*) FROM outbox_events WHERE event_type = 'payment.confirmed'")
            )
        ).scalar_one()
    assert confirmations == 1


async def _approved_submission(client_factory: Any, outbox_mail: Any) -> tuple[Any, str, str, dict[str, Any]]:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    dev, _ = await contributor(client_factory)
    await assign(req, dev, bid)
    sub = await submit_work(dev, bid)
    await req.post(f"/submissions/{sub['id']}/approve", {})
    return req, wallet, bid, sub


async def test_retry_after_lost_submit_response_is_not_marked_failed(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    """BUG: when the RPC accepted a transaction but the response was lost, the retry was rejected as a
    duplicate (txBAD_SEQ) and the row was marked FAILED although the payout had happened on-chain; a new payout
    then failed with AlreadyPaid, so the bounty could never complete."""
    req, wallet, bid, sub = await _approved_submission(client_factory, outbox_mail)
    calls_before = chain.submit_calls
    chain.lose_next_submit_response = True
    chain.reject_duplicates = True
    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    tx_id = prepared["transaction"]["id"]
    body = signed(prepared, wallet)
    lost = await req.request("POST", f"/transactions/{tx_id}/submit", json=body)
    assert lost.status_code == 502
    retried = await req.post(f"/transactions/{tx_id}/submit", body)  # the re-send is answered with txBAD_SEQ
    assert retried["status"] == "CONFIRMED", retried
    tx_hash = prepared["transaction"]["transaction_hash"]
    assert chain.submit_calls - calls_before == 2 and chain.submitted.count(tx_hash) == 1
    final = await req.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED" and final["funding_status"] == "SETTLED"


async def test_sweep_does_not_expire_a_transaction_that_landed(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, chain: FakeStellarChain
) -> None:
    """BUG: the sweep expired stale SIGNATURE_REQUIRED rows without asking the network, losing transactions
    whose submit response was lost (the payment was re-armed and could never be paid again)."""
    from worker.jobs.reconciliation import run_reconciliation_once

    req, wallet, bid, sub = await _approved_submission(client_factory, outbox_mail)
    chain.lose_next_submit_response = True
    prepared = await req.post(
        f"/bounties/{bid}/payouts/prepare", {"wallet_address": wallet, "submission_id": sub["id"]}
    )
    tx_id = prepared["transaction"]["id"]
    lost = await req.request("POST", f"/transactions/{tx_id}/submit", json=signed(prepared, wallet))
    assert lost.status_code == 502
    await db_session.execute(
        update(BlockchainTransaction)
        .where(BlockchainTransaction.id == tx_id)
        .values(expires_at=utcnow() - timedelta(minutes=1))
    )
    await db_session.commit()
    await run_reconciliation_once()
    assert (await req.get(f"/transactions/{tx_id}"))["status"] == "CONFIRMED"
    final = await req.get(f"/bounties/{bid}")
    assert final["status"] == "COMPLETED"
    assert (await req.get(f"/submissions/{sub['id']}"))["payment"]["payment_status"] == "CONFIRMED"


async def test_submit_after_expiry_recovers_a_transaction_that_landed(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession, chain: FakeStellarChain
) -> None:
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    chain.lose_next_submit_response = True
    prepared = await req.post(f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    tx_id = prepared["transaction"]["id"]
    body = signed(prepared, wallet)
    lost = await req.request("POST", f"/transactions/{tx_id}/submit", json=body)
    assert lost.status_code == 502
    await db_session.execute(
        update(BlockchainTransaction)
        .where(BlockchainTransaction.id == tx_id)
        .values(expires_at=utcnow() - timedelta(minutes=1))
    )
    await db_session.commit()
    recovered = await req.post(f"/transactions/{tx_id}/submit", body)
    assert recovered["status"] == "CONFIRMED"
    assert chain.submit_calls == 1  # recovered from the network's record, never re-sent
    assert await status_of(req, bounty["id"]) == "FUNDED"


async def test_fund_prepare_heals_bounty_whose_escrow_is_already_funded(
    client_factory: Any, outbox_mail: Any, db_session: AsyncSession
) -> None:
    """BUG: if the escrow was funded on-chain but the bounty row stayed OPEN (a funding transaction that the
    database lost track of), every FUND prepare answered "already fully funded" and the bounty stayed OPEN
    forever. The prepare now reconciles the bounty from the verified escrow state."""
    from app.modules.bounties.models import Bounty

    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await funded(req, wallet)
    bid = bounty["id"]
    await db_session.execute(update(Bounty).where(Bounty.id == bid).values(status="OPEN"))
    await db_session.commit()
    await get_redis().flushall()  # drop the cached detail: the row was changed behind the API's back
    assert await status_of(req, bid) == "OPEN"
    again = await req.request("POST", f"/bounties/{bid}/funding/prepare", json={"wallet_address": wallet})
    assert again.status_code == 409
    assert await status_of(req, bid) == "FUNDED"


async def test_pending_outcome_is_not_treated_as_success(
    client_factory: Any, outbox_mail: Any, chain: FakeStellarChain
) -> None:
    """BUG: verify_transaction treated any outcome other than NOT_FOUND/FAILED as success, so a PENDING
    report would have been recorded as CONFIRMED before the network settled it."""
    req, wallet = await requester(client_factory, outbox_mail)
    bounty = await published(req)
    chain.report_pending = True
    prepared = await req.post(f"/bounties/{bounty['id']}/funding/prepare", {"wallet_address": wallet})
    tx = await req.post(f"/transactions/{prepared['transaction']['id']}/submit", signed(prepared, wallet))
    assert tx["status"] == "SUBMITTED"
    assert (await req.get(f"/transactions/{tx['id']}"))["status"] == "SUBMITTED"
    chain.report_pending = False
    assert (await req.get(f"/transactions/{tx['id']}"))["status"] == "CONFIRMED"
