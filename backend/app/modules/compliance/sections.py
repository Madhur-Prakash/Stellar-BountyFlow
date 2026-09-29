"""Compliance coverage for the modules that hold personal data of their own.

Each feature module keeps its own models; this module says, in one place, what happens to their rows when a
user exercises a right: what goes into a data export, what stops an account being deleted, and what
anonymisation does. It registers through ``compliance.registry`` at import time (``app.db.models`` imports it,
so the registrations exist wherever the models do).

Keeping it here rather than in each feature module means one file to review against docs/compliance.md, and it
is the file to extend when a module starts holding personal data.

Every query below is a single statement with its joins; nothing loops over rows issuing more queries.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.security import utcnow
from app.modules.compliance import registry
from app.modules.compliance.exports import row_values as _rows
from app.modules.compliance.registry import Blocker
from app.modules.credentials.models import IssuedCredential
from app.modules.discovery.models import SavedSearch
from app.modules.escrow.models import BountyMilestone, DisputeVote
from app.modules.github.models import GitHubAccount, SubmissionPullRequest
from app.modules.qa.models import BountyQAPost, BountyQAVote
from app.modules.reputation.models import AttestationStatus, CompletionAttestation
from app.modules.submissions.models import BountySubmission, SubmissionStatus
from app.modules.users.models import User
from app.modules.wallets.models import PasskeyWallet, SponsoredTransaction

logger = get_logger(__name__)

# The account holder asked to be forgotten; posts keep their place in the thread with the body cleared.
REMOVED = "[removed at the account holder's request]"
DELETION_REASON = "The account holder asked for their account to be deleted."

# Attestation states with a transaction in flight: the contributor's address is about to be written to, or
# removed from, the registry. Deleting the account underneath that would leave the chain and the database
# disagreeing about who was attested.
_IN_FLIGHT = (AttestationStatus.PENDING, AttestationStatus.SUBMITTED, AttestationStatus.REVOKING)


# --- Export sections ------------------------------------------------------------------------


@registry.export_section("milestones")
async def _milestones(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Milestones of the user's own bounties (one join, not a query per bounty)."""
    from app.modules.bounties.models import Bounty

    rows = (
        await session.scalars(
            select(BountyMilestone)
            .join(Bounty, Bounty.id == BountyMilestone.bounty_id)
            .where(Bounty.requester_id == user.id)
            .order_by(BountyMilestone.bounty_id, BountyMilestone.position)
        )
    ).all()
    return [
        _rows(m, ("id", "bounty_id", "position", "title", "description", "amount", "status", "paid_at"))
        for m in rows
    ]


@registry.export_section("passkey_wallets")
async def _passkey_wallets(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(PasskeyWallet).where(PasskeyWallet.user_id == user.id).order_by(PasskeyWallet.created_at)
        )
    ).all()
    return [
        _rows(
            w,
            (
                "id",
                "network",
                "contract_id",
                "key_id",
                "public_key",
                "status",
                "deploy_tx_hash",
                "deployed_at",
                "created_at",
            ),
        )
        for w in rows
    ]


@registry.export_section("sponsored_transactions")
async def _sponsored(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Network fees the platform paid on this user's behalf."""
    rows = (
        await session.scalars(
            select(SponsoredTransaction)
            .where(SponsoredTransaction.user_id == user.id)
            .order_by(SponsoredTransaction.created_at)
        )
    ).all()
    return [
        _rows(
            t,
            (
                "id",
                "kind",
                "purpose",
                "network",
                "sponsor_address",
                "source_address",
                "contract_id",
                "function_name",
                "max_fee_stroops",
                "fee_charged_stroops",
                "status",
                "envelope_hash",
                "inner_hash",
                "ledger_sequence",
                "confirmed_at",
                "created_at",
            ),
        )
        for t in rows
    ]


@registry.export_section("attestations")
async def _attestations(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(CompletionAttestation)
            .where(CompletionAttestation.contributor_id == user.id)
            .order_by(CompletionAttestation.created_at)
        )
    ).all()
    return [
        _rows(
            a,
            (
                "id",
                "bounty_id",
                "status",
                "network",
                "contract_id",
                "contributor_address",
                "onchain_id",
                "onchain_bounty_id",
                "amount",
                "asset_identifier",
                "payments_count",
                "completed_at",
                "attestation_tx_hash",
                "attested_at",
                "confirmed_at",
                "revoked_at",
                "revocation_reason",
                "created_at",
            ),
        )
        for a in rows
    ]


@registry.export_section("credentials")
async def _credentials(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Issued verifiable credentials, with the signed document: it is the user's to keep and re-present."""
    rows = (
        await session.scalars(
            select(IssuedCredential)
            .where(IssuedCredential.user_id == user.id)
            .order_by(IssuedCredential.issued_at)
        )
    ).all()
    return [
        {
            **_rows(
                c,
                (
                    "id",
                    "kind",
                    "attestation_id",
                    "subject_did",
                    "issuer_did",
                    "status_index",
                    "issued_at",
                    "revoked_at",
                    "revocation_reason",
                ),
            ),
            "document": c.document,
        }
        for c in rows
    ]


@registry.export_section("saved_searches")
async def _saved_searches(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.created_at)
        )
    ).all()
    return [
        {
            **_rows(
                s,
                (
                    "id",
                    "name",
                    "alert_frequency",
                    "notify_in_app",
                    "notify_email",
                    "is_paused",
                    "last_viewed_at",
                    "last_digest_at",
                    "created_at",
                ),
            ),
            "filters": s.filters,
        }
        for s in rows
    ]


@registry.export_section("qa_posts")
async def _qa_posts(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(BountyQAPost).where(BountyQAPost.author_id == user.id).order_by(BountyQAPost.created_at)
        )
    ).all()
    return [
        _rows(
            p,
            (
                "id",
                "bounty_id",
                "parent_id",
                "body",
                "is_pinned",
                "is_accepted",
                "upvotes_count",
                "created_at",
                "edited_at",
                "deleted_at",
                "hidden_at",
            ),
        )
        for p in rows
    ]


@registry.export_section("qa_votes")
async def _qa_votes(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(
            select(BountyQAVote).where(BountyQAVote.user_id == user.id).order_by(BountyQAVote.created_at)
        )
    ).all()
    return [_rows(v, ("post_id", "created_at")) for v in rows]


@registry.export_section("github_account")
async def _github_account(session: AsyncSession, user: User) -> dict[str, Any] | None:
    account = await session.get(GitHubAccount, user.id)
    if account is None:
        return None
    return _rows(
        account, ("github_id", "login", "avatar_url", "method", "proof_url", "verified_at", "created_at")
    )


@registry.export_section("pull_requests")
async def _pull_requests(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Pull requests linked to the user's submissions, with the verification snapshot each one was judged on
    (one join through submissions, not a query per submission)."""
    rows = (
        await session.scalars(
            select(SubmissionPullRequest)
            .join(BountySubmission, BountySubmission.id == SubmissionPullRequest.submission_id)
            .where(BountySubmission.contributor_id == user.id)
            .order_by(SubmissionPullRequest.created_at)
        )
    ).all()
    return [
        {
            **_rows(
                pr,
                (
                    "id",
                    "submission_id",
                    "url",
                    "repo_owner",
                    "repo_name",
                    "number",
                    "verification",
                    "state",
                    "title",
                    "author_login",
                    "merged_at",
                    "head_sha",
                    "checks",
                    "checks_passed",
                    "checks_failed",
                    "detail",
                    "last_checked_at",
                    "created_at",
                ),
            ),
            "snapshot": pr.snapshot,
        }
        for pr in rows
    ]


@registry.export_section("dispute_votes")
async def _dispute_votes(session: AsyncSession, user: User) -> list[dict[str, Any]]:
    """Arbiter votes the user cast (staff only; empty for everyone else)."""
    rows = (
        await session.scalars(
            select(DisputeVote).where(DisputeVote.voter_id == user.id).order_by(DisputeVote.created_at)
        )
    ).all()
    return [
        _rows(
            v,
            ("id", "dispute_id", "bounty_id", "arbiter_address", "round", "contributor_amount", "created_at"),
        )
        for v in rows
    ]


# --- Deletion blockers ----------------------------------------------------------------------


@registry.deletion_blocker
async def _attestations_in_flight(session: AsyncSession, user_id: uuid.UUID) -> list[Blocker]:
    """An attestation being written to, or removed from, the registry names this contributor's address."""
    count = int(
        await session.scalar(
            select(func.count(CompletionAttestation.id)).where(
                CompletionAttestation.contributor_id == user_id,
                CompletionAttestation.status.in_(_IN_FLIGHT),
            )
        )
        or 0
    )
    if not count:
        return []
    return [
        Blocker(
            "attestation_in_flight",
            "An on-chain completion attestation is still settling. This finishes on its own shortly.",
            count,
            ["/app/reputation"],
        )
    ]


# --- Anonymisation --------------------------------------------------------------------------


@registry.anonymiser
async def _forget_credentials(session: AsyncSession, user: User) -> None:
    """Revoke every standing credential and clear its document.

    A credential is a signed statement about a named person that the holder may have copied anywhere, and its
    status is public through the Bitstring Status List. Erasure here means two things: the status list flips
    the credential's bit to revoked, so any verifier that checks it (as the spec requires) now fails it, and
    BountyFlow's own copy of the signed document, which carries the personal data, is cleared. Copies already
    downloaded cannot be recalled — docs/compliance.md says so plainly."""
    result = await session.execute(
        update(IssuedCredential)
        .where(IssuedCredential.user_id == user.id, IssuedCredential.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revocation_reason=DELETION_REASON[:200])
    )
    await session.execute(
        update(IssuedCredential)
        .where(IssuedCredential.user_id == user.id)
        .values(document={}, subject_did="")
    )
    revoked = int(getattr(result, "rowcount", 0) or 0)
    if revoked:
        # The published status list is derived from these rows. Its cache is dropped after the transaction
        # commits (deletion.execute_next), so no Redis call happens while the account's rows are locked.
        logger.info("credentials_revoked_for_deletion", user_id=str(user.id), count=revoked)


@registry.anonymiser
async def _forget_qa(session: AsyncSession, user: User) -> None:
    """Soft-delete the user's posts the way the Q&A module does, so threads keep their shape."""
    now = utcnow()
    await session.execute(
        update(BountyQAPost)
        .where(BountyQAPost.author_id == user.id, BountyQAPost.deleted_at.is_(None))
        .values(deleted_at=now, body="", is_pinned=False, is_accepted=False)
    )
    # A vote is an opinion tied to a person; the post keeps its count, which is not personal data.
    await session.execute(delete(BountyQAVote).where(BountyQAVote.user_id == user.id))


@registry.anonymiser
async def _forget_discovery(session: AsyncSession, user: User) -> None:
    """Saved searches are a preference, not a record: they go entirely (matches cascade with them)."""
    await session.execute(delete(SavedSearch).where(SavedSearch.user_id == user.id))


@registry.anonymiser
async def _forget_github(session: AsyncSession, user: User) -> None:
    """Unlink the third-party identity, and drop the GitHub identity from pull requests on unpaid work.

    Pull requests attached to approved (paid) submissions stay: they are the evidence of what was delivered
    and paid for, the same rule the submissions themselves follow."""
    await session.execute(delete(GitHubAccount).where(GitHubAccount.user_id == user.id))
    unpaid = select(BountySubmission.id).where(
        BountySubmission.contributor_id == user.id, BountySubmission.status != SubmissionStatus.APPROVED
    )
    await session.execute(
        update(SubmissionPullRequest)
        .where(SubmissionPullRequest.submission_id.in_(unpaid))
        .values(author_login=None, author_id=None, title=None, detail=None, snapshot={})
    )


@registry.anonymiser
async def _forget_passkeys(session: AsyncSession, user: User) -> None:
    """Clear the WebAuthn credential identifiers (they identify the person's device).

    The contract address and its deployment transaction stay: they are on-chain facts, and the sponsored fee
    that paid for the deployment is a financial record."""
    await session.execute(
        update(PasskeyWallet).where(PasskeyWallet.user_id == user.id).values(key_id="", public_key="")
    )


@registry.anonymiser
async def _forget_sponsorship_addresses(session: AsyncSession, user: User) -> None:
    """Sponsored-fee rows are financial records and stay, but the free-text purpose can name the person."""
    await session.execute(
        update(SponsoredTransaction)
        .where(SponsoredTransaction.user_id == user.id)
        .values(details={}, purpose="deleted account")
    )


@registry.anonymiser
async def _release_dispute_votes(session: AsyncSession, user: User) -> None:
    """A vote stays as the record of how a dispute was decided; who cast it is no longer named."""
    await session.execute(update(DisputeVote).where(DisputeVote.voter_id == user.id).values(voter_id=None))
