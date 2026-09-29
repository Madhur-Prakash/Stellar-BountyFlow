"""Verifiable credentials for attested completions: issuing, revocation (Bitstring Status List) and verification.

Format: W3C Verifiable Credentials 2.0 secured with a Data Integrity proof, cryptosuite ``eddsa-jcs-2022``. The
issuer is the site's ``did:web``; the subject is the Stellar account that was paid (``did:pkh:stellar:…``).

* A completion credential states one attestation: the bounty, the amount and asset, the payout transaction and
  the attestation's id in the on-chain registry. It is issued only for a completion confirmed on-chain.
* A summary credential lists every standing attested completion of the contributor at issue time.
* Revoking an attestation revokes every credential that states it, by setting its bit in the public status list.
* ``verify`` checks the format, the issuer, the signature, the validity period and the revocation status, then
  reads each stated attestation from the contract and compares it with the credential's claims.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.assets import parse_identifier
from app.blockchain.transactions import ChainUnavailable
from app.cache import keys
from app.cache.redis import cache_delete, cached_json
from app.core.config import get_settings
from app.core.exceptions import InvalidStateTransition, NotFound, ServiceUnavailable
from app.core.logging import get_logger
from app.core.money import display_amount, fmt, to_stroops
from app.core.security import utcnow
from app.modules.admin import audit
from app.modules.credentials import data_integrity, status_list
from app.modules.credentials.issuer import (
    ISSUER_NAME,
    VC_CONTEXT,
    Issuer,
    address_from_subject,
    did_document,
    get_issuer,
    subject_did,
)
from app.modules.credentials.models import CredentialKind, IssuedCredential
from app.modules.credentials.schemas import (
    CheckId,
    CheckStatus,
    CredentialOut,
    IssuedCredentialOut,
    IssuerInfo,
    IssuerRef,
    VerificationCheck,
    VerificationReport,
    VerifiedAttestation,
)
from app.modules.escrow.models import BountyMilestone
from app.modules.payments.models import PaymentRecord, PaymentStatus
from app.modules.reputation.chain import AttestationError, OnchainAttestation, get_chain
from app.modules.reputation.chain import get_config as attestation_config
from app.modules.reputation.models import AttestationStatus, ChainCheck, CompletionAttestation
from app.modules.users.models import User

logger = get_logger(__name__)

COMPLETION_TYPE = "BountyCompletionCredential"
SUMMARY_TYPE = "ContributorReputationCredential"
MAX_SUMMARY_ITEMS = 100
MAX_VERIFY_READS = 25
CLOCK_SKEW = timedelta(minutes=5)
STATUS_LIST_TTL = 30
STATUS_LIST_KEY = f"{keys.PREFIX}:credentials:status-list"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def require_issuer() -> Issuer:
    issuer = get_issuer()
    if issuer is None:
        raise ServiceUnavailable(
            "Verifiable credentials are not set up on this server (CREDENTIAL_ISSUER_SECRET).",
            code="credentials_disabled",
        )
    return issuer


def issuer_info() -> IssuerInfo:
    issuer = get_issuer()
    if issuer is None:
        return IssuerInfo(
            enabled=False, did=None, verification_method=None, did_document_url=None, status_list_url=None
        )
    return IssuerInfo(
        enabled=True,
        did=issuer.did,
        verification_method=issuer.key_id,
        did_document_url=issuer.did_document_url,
        status_list_url=issuer.status_list_url,
    )


def issuer_did_document() -> dict[str, Any] | None:
    issuer = get_issuer()
    return did_document(issuer) if issuer else None


# --- Building credentials ------------------------------------------------------------------


def _site_url(path: str) -> str:
    return get_settings().frontend_url.rstrip("/") + path


def _caip2(network: str) -> str:
    return f"stellar:{'pubnet' if network == 'mainnet' else network}"


def _asset_json(identifier: str, token_contract: str) -> dict[str, Any]:
    ref = parse_identifier(identifier)
    asset: dict[str, Any] = {"code": ref.code, "contract": token_contract}
    if ref.issuer:
        asset["issuer"] = ref.issuer
    return asset


def _payment_evidence(
    payments: Sequence[PaymentRecord], milestones: Mapping[uuid.UUID, str]
) -> list[dict[str, Any]]:
    """The transfers that paid one completion: a single release, several milestones, or a batch leg."""
    evidence = []
    for p in payments:
        item: dict[str, Any] = {"amount": fmt(p.amount)}
        if p.settled_at:
            item["settledAt"] = _iso(p.settled_at)
        if p.transaction is not None and p.transaction.transaction_hash:
            item["transaction"] = p.transaction.transaction_hash
            item["kind"] = p.transaction.transaction_type.value
        if p.milestone_id is not None:
            item["milestone"] = milestones.get(p.milestone_id, "")
        evidence.append(item)
    return evidence


def _completion_claim(
    row: CompletionAttestation, payments: Sequence[PaymentRecord], milestones: Mapping[uuid.UUID, str]
) -> dict[str, Any]:
    """What the credential states: the completion, the amount in the bounty's asset, and the payments behind it."""
    bounty = row.bounty
    claim: dict[str, Any] = {
        "type": "BountyCompletion",
        "bounty": {"id": str(bounty.id), "title": bounty.title, "url": _site_url(f"/bounties/{bounty.slug}")},
        "amount": fmt(row.amount),
        "asset": _asset_json(row.asset_identifier, row.token_contract_id),
        "payments": _payment_evidence(payments, milestones),
        "completedAt": _iso(row.completed_at),
        "network": _caip2(row.network),
        "recipient": row.contributor_address,
        "payoutTransaction": row.payout_tx_hash,
        "escrowContract": row.escrow_contract_id,
        "escrowBountyId": row.onchain_bounty_id,
        "attestation": {
            "contract": row.contract_id,
            "id": row.onchain_id,
            "transaction": row.attestation_tx_hash,
            "attestedAt": _iso(row.attested_at) if row.attested_at else None,
            "url": _site_url(f"/attestations/{row.onchain_id}"),
        },
    }
    if not claim["payments"]:
        del claim["payments"]
    if claim["attestation"]["transaction"] is None:
        del claim["attestation"]["transaction"]
    if claim["attestation"]["attestedAt"] is None:
        del claim["attestation"]["attestedAt"]
    return claim


async def _completion_payments(
    session: AsyncSession, row: CompletionAttestation
) -> tuple[Sequence[PaymentRecord], Mapping[uuid.UUID, str]]:
    """The confirmed payments of one completion, with their transactions joined (never a query per row)."""
    payments = list(
        (
            await session.scalars(
                select(PaymentRecord)
                .where(
                    PaymentRecord.bounty_id == row.bounty_id,
                    PaymentRecord.contributor_id == row.contributor_id,
                    PaymentRecord.payment_status == PaymentStatus.CONFIRMED,
                )
                .order_by(PaymentRecord.settled_at.asc().nulls_last())
            )
        )
        .unique()
        .all()
    )
    ids = [p.milestone_id for p in payments if p.milestone_id is not None]
    titles: dict[uuid.UUID, str] = {}
    if ids:
        titles = {
            mid: title
            for mid, title in (
                await session.execute(
                    select(BountyMilestone.id, BountyMilestone.title).where(BountyMilestone.id.in_(ids))
                )
            ).all()
        }
    return payments, titles


def _subject(user: User, did: str) -> dict[str, Any]:
    return {
        "id": did,
        "name": user.display_name,
        "username": user.username,
        "profile": _site_url(f"/u/{user.username}"),
    }


async def _allocate_status_index(session: AsyncSession) -> int:
    """A random, unused index: random allocation keeps an entry's position from revealing issue order."""
    for _ in range(64):
        candidate = secrets.randbelow(status_list.LIST_LENGTH)
        taken = await session.scalar(
            select(IssuedCredential.id).where(IssuedCredential.status_index == candidate)
        )
        if taken is None:
            return candidate
    raise ServiceUnavailable("The credential status list is full.")


async def _create(
    session: AsyncSession,
    *,
    user: User,
    kind: CredentialKind,
    subject: dict[str, Any],
    types: list[str],
    name: str,
    description: str,
    attestation_id: uuid.UUID | None,
    attestation_ids: list[str],
) -> IssuedCredential:
    issuer = require_issuer()
    for _ in range(5):
        credential_uuid = uuid.uuid4()
        index = await _allocate_status_index(session)
        now = utcnow()
        document: dict[str, Any] = {
            "@context": [VC_CONTEXT],
            "id": f"urn:uuid:{credential_uuid}",
            "type": ["VerifiableCredential", *types],
            "name": name,
            "description": description,
            "issuer": {"id": issuer.did, "name": ISSUER_NAME, "url": issuer.origin},
            "validFrom": _iso(now),
            "credentialSubject": subject,
            "credentialStatus": {
                "id": f"{issuer.status_list_url}#{index}",
                "type": "BitstringStatusListEntry",
                "statusPurpose": "revocation",
                "statusListIndex": str(index),
                "statusListCredential": issuer.status_list_url,
            },
        }
        signed = data_integrity.sign(
            document, seed=issuer.seed, verification_method=issuer.key_id, created=_iso(now)
        )
        row = IssuedCredential(
            id=credential_uuid,
            user_id=user.id,
            kind=kind,
            attestation_id=attestation_id,
            attestation_ids=attestation_ids,
            subject_did=subject["id"],
            issuer_did=issuer.did,
            status_index=index,
            document=signed,
            issued_at=now,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            continue  # a concurrent issue took the index (or the active completion slot); try again
        audit.record(
            session,
            actor_id=user.id,
            action="credential.issued",
            entity_type="credential",
            entity_id=row.id,
            metadata={"kind": kind.value, "status_index": index, "attestations": len(attestation_ids)},
            is_public=False,
        )
        return row
    raise ServiceUnavailable("The credential could not be issued. Please try again.")


def _signed_with_current_key(row: IssuedCredential, issuer: Issuer) -> bool:
    proof = row.document.get("proof") or {}
    return isinstance(proof, dict) and proof.get("verificationMethod") == issuer.key_id


async def _supersede(session: AsyncSession, row: IssuedCredential, reason: str) -> None:
    row.revoked_at = utcnow()
    row.revocation_reason = reason
    await session.flush()


def _standing(stmt: Any) -> Any:
    return stmt.where(
        CompletionAttestation.status == AttestationStatus.CONFIRMED,
        (CompletionAttestation.chain_check.is_(None))
        | (CompletionAttestation.chain_check == ChainCheck.MATCH),
    )


async def issue_completion(
    session: AsyncSession, user: User, attestation_id: uuid.UUID
) -> IssuedCredentialOut:
    issuer = require_issuer()
    row = await session.scalar(
        select(CompletionAttestation).where(
            CompletionAttestation.id == attestation_id, CompletionAttestation.contributor_id == user.id
        )
    )
    if row is None:
        raise NotFound("Attestation not found.")
    standing = await session.scalar(
        _standing(select(CompletionAttestation.id)).where(CompletionAttestation.id == row.id)
    )
    if standing is None or row.onchain_id is None:
        raise InvalidStateTransition("A credential can be issued only for a completion confirmed on-chain.")
    existing = await session.scalar(
        select(IssuedCredential).where(
            IssuedCredential.attestation_id == row.id,
            IssuedCredential.kind == CredentialKind.COMPLETION,
            IssuedCredential.revoked_at.is_(None),
        )
    )
    if existing is not None and _signed_with_current_key(existing, issuer):
        return _out(existing, with_document=True)
    if existing is not None:
        await _supersede(session, existing, "Reissued with the issuer's current key")
    payments, milestones = await _completion_payments(session, row)
    title = row.bounty.title
    amount = display_amount(row.amount, parse_identifier(row.asset_identifier).code)
    credential = await _create(
        session,
        user=user,
        kind=CredentialKind.COMPLETION,
        subject={
            **_subject(user, subject_did(row.contributor_address, row.network)),
            "completion": _completion_claim(row, payments, milestones),
        },
        types=[COMPLETION_TYPE],
        name="Bounty completion",
        description=f"Completed “{title}” on BountyFlow and was paid {amount} from escrow on Stellar.",
        attestation_id=row.id,
        attestation_ids=[str(row.id)],
    )
    await session.commit()
    return _out(credential, with_document=True)


async def issue_summary(session: AsyncSession, user: User) -> IssuedCredentialOut:
    issuer = require_issuer()
    rows = (
        (
            await session.scalars(
                _standing(select(CompletionAttestation))
                .where(
                    CompletionAttestation.contributor_id == user.id,
                    CompletionAttestation.onchain_id.is_not(None),
                )
                .order_by(CompletionAttestation.completed_at.desc())
                .limit(MAX_SUMMARY_ITEMS)
            )
        )
        .unique()
        .all()
    )
    rows = [r for r in rows if not r.bounty.is_hidden]
    if not rows:
        raise InvalidStateTransition("There are no completions confirmed on-chain to summarise yet.")
    ids = sorted(str(r.id) for r in rows)
    latest = await session.scalar(
        select(IssuedCredential)
        .where(
            IssuedCredential.user_id == user.id,
            IssuedCredential.kind == CredentialKind.SUMMARY,
            IssuedCredential.revoked_at.is_(None),
        )
        .order_by(IssuedCredential.issued_at.desc())
        .limit(1)
    )
    if (
        latest is not None
        and sorted(latest.attestation_ids) == ids
        and _signed_with_current_key(latest, issuer)
    ):
        return _out(latest, with_document=True)
    # The subject is the account that received the money most recently (a classic G… account or a passkey
    # smart-wallet contract C…). Each attestation below still names the address that completion was paid to.
    address = rows[0].contributor_address
    totals: dict[str, Decimal] = {}
    for r in rows:
        totals[r.asset_identifier] = totals.get(r.asset_identifier, Decimal(0)) + r.amount
    earned = [
        {
            "amount": fmt(amount),
            "asset": _asset_json(
                identifier, next(r.token_contract_id for r in rows if r.asset_identifier == identifier)
            ),
        }
        for identifier, amount in sorted(totals.items(), key=lambda kv: (kv[0] != "native", kv[0]))
    ]
    claim = {
        "type": "AttestedCompletions",
        "network": _caip2(rows[0].network),
        "attestationContract": rows[0].contract_id,
        "completions": len(rows),
        "earned": earned,
        "firstCompletedAt": _iso(min(r.completed_at for r in rows)),
        "lastCompletedAt": _iso(max(r.completed_at for r in rows)),
        "attestations": [
            {
                "id": r.onchain_id,
                "bounty": r.bounty.title,
                "recipient": r.contributor_address,
                "amount": fmt(r.amount),
                "asset": _asset_json(r.asset_identifier, r.token_contract_id),
                "completedAt": _iso(r.completed_at),
                "payoutTransaction": r.payout_tx_hash,
                "escrowContract": r.escrow_contract_id,
                "escrowBountyId": r.onchain_bounty_id,
            }
            for r in rows
        ],
    }
    count = len(rows)
    credential = await _create(
        session,
        user=user,
        kind=CredentialKind.SUMMARY,
        subject={**_subject(user, subject_did(address, rows[0].network)), "reputation": claim},
        types=[SUMMARY_TYPE],
        name="Attested bounty completions",
        description=f"{count} bounty completion{'s' if count != 1 else ''} on BountyFlow, each recorded in the "
        "on-chain attestation registry on Stellar.",
        attestation_id=None,
        attestation_ids=ids,
    )
    await session.commit()
    return _out(credential, with_document=True)


def _out(row: IssuedCredential, *, with_document: bool = False) -> Any:
    data = {
        "id": row.id,
        "credential_id": str(row.document.get("id", f"urn:uuid:{row.id}")),
        "kind": row.kind,
        "attestation_id": row.attestation_id,
        "attestation_count": len(row.attestation_ids or []),
        "subject_did": row.subject_did,
        "issuer_did": row.issuer_did,
        "issued_at": row.issued_at,
        "revoked_at": row.revoked_at,
        "revocation_reason": row.revocation_reason,
    }
    if with_document:
        return IssuedCredentialOut(**data, document=row.document)
    return CredentialOut(**data)


async def my_credentials(session: AsyncSession, user: User) -> list[CredentialOut]:
    rows = (
        await session.scalars(
            select(IssuedCredential)
            .where(IssuedCredential.user_id == user.id)
            .order_by(IssuedCredential.issued_at.desc())
            .limit(200)
        )
    ).all()
    return [_out(r) for r in rows]


async def get_mine(session: AsyncSession, user: User, credential_id: uuid.UUID) -> IssuedCredentialOut:
    row = await session.get(IssuedCredential, credential_id)
    if row is None or row.user_id != user.id:
        raise NotFound("Credential not found.")
    return _out(row, with_document=True)


# --- Revocation and the status list -------------------------------------------------------------


async def revoke_for_attestation(session: AsyncSession, attestation_id: uuid.UUID, reason: str) -> int:
    """Revokes every standing credential that states this attestation (in the caller's transaction)."""
    result = await session.execute(
        update(IssuedCredential)
        .where(
            IssuedCredential.revoked_at.is_(None),
            or_(
                IssuedCredential.attestation_id == attestation_id,
                IssuedCredential.attestation_ids.contains([str(attestation_id)]),
            ),
        )
        .values(revoked_at=utcnow(), revocation_reason=reason[:200])
    )
    await cache_delete(STATUS_LIST_KEY)
    count = int(getattr(result, "rowcount", 0) or 0)
    if count:
        logger.info("credentials_revoked", attestation_id=str(attestation_id), count=count)
    return count


async def status_list_credential(session: AsyncSession) -> dict[str, Any]:
    """The signed BitstringStatusListCredential for revocation (regenerated at most every 30 seconds)."""
    issuer = require_issuer()

    async def load() -> dict[str, Any]:
        revoked = (
            await session.scalars(
                select(IssuedCredential.status_index).where(
                    IssuedCredential.revoked_at.is_not(None), IssuedCredential.issuer_did == issuer.did
                )
            )
        ).all()
        now = utcnow()
        document = {
            "@context": [VC_CONTEXT],
            "id": issuer.status_list_url,
            "type": ["VerifiableCredential", "BitstringStatusListCredential"],
            "issuer": issuer.did,
            "validFrom": _iso(now),
            "credentialSubject": {
                "id": f"{issuer.status_list_url}#list",
                "type": "BitstringStatusList",
                "statusPurpose": "revocation",
                "encodedList": status_list.encode(revoked),
            },
        }
        return data_integrity.sign(
            document, seed=issuer.seed, verification_method=issuer.key_id, created=_iso(now)
        )

    return await cached_json(STATUS_LIST_KEY, STATUS_LIST_TTL, load)


# --- Verification ---------------------------------------------------------------------------


class _Report:
    def __init__(self) -> None:
        self.checks: list[VerificationCheck] = []

    def add(self, check: CheckId, label: str, status: CheckStatus, detail: str) -> None:
        self.checks.append(VerificationCheck(id=check, label=label, status=status, detail=detail))

    def skip(self, *checks: tuple[CheckId, str], detail: str) -> None:
        for check, label in checks:
            self.add(check, label, "skip", detail)

    @property
    def failed(self) -> bool:
        return any(c.status == "fail" for c in self.checks)


LABELS: dict[CheckId, str] = {
    "format": "Credential format",
    "issuer": "Issuer",
    "signature": "Signature",
    "validity": "Validity period",
    "status": "Revocation status",
    "attestation": "On-chain attestation",
}


def _issuer_id(document: dict[str, Any]) -> tuple[str | None, str | None]:
    value = document.get("issuer")
    if isinstance(value, str):
        return value, None
    if isinstance(value, dict):
        name = value.get("name")
        return (value.get("id") if isinstance(value.get("id"), str) else None), (
            name if isinstance(name, str) else None
        )
    return None, None


def _format_problem(document: dict[str, Any]) -> str | None:
    context = document.get("@context")
    if not isinstance(context, list) or not context or context[0] != VC_CONTEXT:
        return f"The first @context must be {VC_CONTEXT} (Verifiable Credentials 2.0)."
    types = document.get("type")
    if not isinstance(types, list) or "VerifiableCredential" not in types:
        return "The type must include VerifiableCredential."
    if _issuer_id(document)[0] is None:
        return "The credential names no issuer."
    if not isinstance(document.get("credentialSubject"), dict):
        return "The credential has no credentialSubject object."
    if "proof" not in document:
        return "The credential has no proof, so it is not verifiable."
    return None


def _claimed_completions(
    document: dict[str, Any],
) -> tuple[Literal["completion", "summary"] | None, list[dict[str, Any]], str | None]:
    """(kind, attestation claims, attestation contract) stated by one of our credential types."""
    types = document.get("type") or []
    subject = document.get("credentialSubject") or {}
    parsed = address_from_subject(subject["id"]) if isinstance(subject.get("id"), str) else None
    subject_address = parsed[1] if parsed else None
    if COMPLETION_TYPE in types and isinstance(subject.get("completion"), dict):
        c = subject["completion"]
        attestation = c.get("attestation") if isinstance(c.get("attestation"), dict) else {}
        claim = {
            "id": attestation.get("id"),
            "recipient": c.get("recipient") or subject_address,
            "amount": c.get("amount"),
            "asset": c.get("asset"),
            "completedAt": c.get("completedAt"),
            "payoutTransaction": c.get("payoutTransaction"),
            "escrowContract": c.get("escrowContract"),
            "escrowBountyId": c.get("escrowBountyId"),
        }
        return "completion", [claim], attestation.get("contract")
    if SUMMARY_TYPE in types and isinstance(subject.get("reputation"), dict):
        r = subject["reputation"]
        items = [i for i in (r.get("attestations") or []) if isinstance(i, dict)]
        return "summary", items, r.get("attestationContract")
    return None, [], None


def _mismatch(claim: dict[str, Any], record: OnchainAttestation) -> str | None:
    asset: dict[str, Any] = claim["asset"] if isinstance(claim.get("asset"), dict) else {}
    completed = _parse_time(claim.get("completedAt"))
    try:
        amount = to_stroops(Decimal(str(claim.get("amount"))))
    except (InvalidOperation, ValueError):
        return "the amount is not a decimal"
    expected = {
        "recipient": (claim.get("recipient"), record.contributor),
        "bounty": (claim.get("escrowBountyId"), record.bounty_id),
        "payout transaction": (claim.get("payoutTransaction"), record.payout_tx),
        "escrow contract": (claim.get("escrowContract"), record.escrow_contract),
        "token": (asset.get("contract"), record.token),
        "amount": (amount, record.amount),
        "completion time": (int(completed.timestamp()) if completed else None, record.completed_at),
    }
    for label, (claimed, onchain) in expected.items():
        if claimed != onchain:
            return f"the {label} differs from the contract"
    return None


async def _check_attestations(
    session: AsyncSession, claims: list[dict[str, Any]], contract: str | None
) -> tuple[CheckStatus, str, list[VerifiedAttestation]]:
    config = attestation_config()
    base = config.network.explorer_base_url.rstrip("/")
    if not config.reads_enabled:
        return "skip", "The attestation registry is not configured on this server.", []
    if not claims:
        return "fail", "The credential states no attestation.", []
    if contract != config.contract_id:
        return "fail", f"The attestations are in another registry ({contract}).", []
    chain = get_chain()
    checked = claims[:MAX_VERIFY_READS]
    ids: list[int] = []
    for claim in checked:
        onchain_id = claim.get("id")
        if not isinstance(onchain_id, int) or isinstance(onchain_id, bool) or onchain_id <= 0:
            return "fail", "An attestation id is missing or invalid.", []
        ids.append(onchain_id)
    # One query for every attestation the credential states, never one per claim.
    known = {
        row.onchain_id: row
        for row in (
            await session.scalars(
                select(CompletionAttestation).where(
                    CompletionAttestation.onchain_id.in_(ids),
                    CompletionAttestation.contract_id == contract,
                )
            )
        )
        .unique()
        .all()
    }
    results: list[VerifiedAttestation] = []
    for claim, onchain_id in zip(checked, ids, strict=True):
        try:
            record = await chain.get(onchain_id)
        except (ChainUnavailable, AttestationError) as exc:
            return "fail", f"The contract could not be read right now ({exc}). Try again shortly.", results
        row = known.get(onchain_id)
        if record is None:
            detail, matches, revoked = f"Attestation #{onchain_id} does not exist on-chain.", False, False
        else:
            problem = _mismatch(claim, record)
            matches, revoked = problem is None, record.revoked
            if problem:
                detail = f"Attestation #{onchain_id}: {problem}."
            elif revoked:
                detail = f"Attestation #{onchain_id} was revoked on-chain: {record.revocation_reason}"
            else:
                detail = f"Attestation #{onchain_id} matches the contract."
        results.append(
            VerifiedAttestation(
                onchain_id=onchain_id,
                contract_id=contract,
                matches=matches,
                revoked=revoked,
                detail=detail,
                attestation_path=f"/attestations/{onchain_id}" if row is not None else None,
                explorer_url=f"{base}/tx/{row.attestation_tx_hash}"
                if row and row.attestation_tx_hash
                else None,
                contract_explorer_url=f"{base}/contract/{contract}",
            )
        )
    bad = [r for r in results if not r.matches or r.revoked]
    if bad:
        return "fail", bad[0].detail, results
    if len(claims) > MAX_VERIFY_READS:
        return (
            "pass",
            f"The first {MAX_VERIFY_READS} of {len(claims)} attestations match the contract.",
            results,
        )
    if len(results) == 1:
        return "pass", results[0].detail, results
    return "pass", f"All {len(results)} attestations match the contract.", results


async def verify(session: AsyncSession, document: dict[str, Any]) -> VerificationReport:
    issuer = require_issuer()
    report = _Report()
    issuer_id, issuer_name = _issuer_id(document)
    credential_id = document.get("id") if isinstance(document.get("id"), str) else None
    kind, claims, contract = _claimed_completions(document)
    subject = document.get("credentialSubject")
    subject_id = (
        subject.get("id") if isinstance(subject, dict) and isinstance(subject.get("id"), str) else None
    )
    valid_from = document.get("validFrom") if isinstance(document.get("validFrom"), str) else None
    attestations: list[VerifiedAttestation] = []
    rest: list[tuple[CheckId, str]] = [
        (c, LABELS[c]) for c in ("issuer", "signature", "validity", "status", "attestation")
    ]

    problem = _format_problem(document)
    if problem:
        report.add("format", LABELS["format"], "fail", problem)
        report.skip(*rest, detail="Skipped: the document is not a verifiable credential.")
    else:
        kinds = {"completion": "a bounty completion", "summary": "a summary of attested completions"}
        report.add(
            "format",
            LABELS["format"],
            "pass",
            f"Verifiable Credential 2.0 stating {kinds[kind]}." if kind else "Verifiable Credential 2.0.",
        )
        if issuer_id != issuer.did:
            report.add(
                "issuer", LABELS["issuer"], "fail", f"Issued by {issuer_id}, not by this site ({issuer.did})."
            )
            report.skip(*rest[1:], detail="Skipped: only credentials this site issued can be checked here.")
        else:
            report.add("issuer", LABELS["issuer"], "pass", f"Issued by BountyFlow ({issuer.did}).")
            await _verify_issued(session, report, document, issuer, credential_id)
            status, detail, attestations = await _check_attestations(session, claims, contract)
            if kind is None:
                status, detail = "fail", "The credential does not state a BountyFlow completion."
            report.add("attestation", LABELS["attestation"], status, detail)

    signature_ok = any(c.id == "signature" and c.status == "pass" for c in report.checks)
    return VerificationReport(
        verified=signature_ok and not report.failed,
        checks=report.checks,
        credential_id=credential_id,
        kind=kind,
        issuer=IssuerRef(id=issuer_id, name=issuer_name, is_this_site=issuer_id == issuer.did),
        subject=subject_id,
        valid_from=valid_from,
        attestations=attestations,
        checked_at=utcnow(),
    )


async def _verify_issued(
    session: AsyncSession,
    report: _Report,
    document: dict[str, Any],
    issuer: Issuer,
    credential_id: str | None,
) -> None:
    # Signature
    try:
        _proof, info = data_integrity.read_proof(document)
        if info.verification_method != issuer.key_id:
            raise data_integrity.ProofError(
                f"The proof names the key {info.verification_method}, which is not in the issuer's DID document."
            )
        if info.proof_purpose != "assertionMethod":
            raise data_integrity.ProofError("The proof's purpose is not assertionMethod.")
        data_integrity.verify_proof(document, issuer.public_key)
        report.add(
            "signature",
            LABELS["signature"],
            "pass",
            f"The eddsa-jcs-2022 proof verifies with {issuer.public_multikey[:12]}…, the issuer's key.",
        )
    except data_integrity.ProofError as exc:
        report.add("signature", LABELS["signature"], "fail", str(exc))

    # Validity period
    now = utcnow()
    valid_from = _parse_time(document.get("validFrom"))
    valid_until = _parse_time(document.get("validUntil")) if "validUntil" in document else None
    if valid_from is None:
        report.add(
            "validity", LABELS["validity"], "fail", "validFrom is missing or not a date-time with a zone."
        )
    elif valid_from > now + CLOCK_SKEW:
        report.add("validity", LABELS["validity"], "fail", f"Not valid until {_iso(valid_from)}.")
    elif "validUntil" in document and (valid_until is None or valid_until <= now):
        report.add("validity", LABELS["validity"], "fail", "The credential has expired.")
    else:
        report.add("validity", LABELS["validity"], "pass", f"Valid since {_iso(valid_from)}.")

    # Revocation status
    status = document.get("credentialStatus")
    if not isinstance(status, dict):
        report.add(
            "status", LABELS["status"], "fail", "The credential has no status entry, so it cannot be revoked."
        )
        return
    index_text = status.get("statusListIndex")
    if (
        status.get("type") != "BitstringStatusListEntry"
        or status.get("statusPurpose") != "revocation"
        or status.get("statusListCredential") != issuer.status_list_url
        or not isinstance(index_text, str)
        or not index_text.isdigit()
    ):
        report.add(
            "status",
            LABELS["status"],
            "fail",
            "The status entry does not point at this site's revocation list.",
        )
        return
    row = await session.scalar(
        select(IssuedCredential).where(IssuedCredential.status_index == int(index_text))
    )
    if row is None or row.document.get("id") != credential_id:
        report.add("status", LABELS["status"], "fail", "This credential is not in the issuer's records.")
    elif row.revoked_at is not None:
        report.add(
            "status",
            LABELS["status"],
            "fail",
            f"Revoked on {_iso(row.revoked_at)[:10]}: {row.revocation_reason or 'no reason given'}.",
        )
    else:
        report.add("status", LABELS["status"], "pass", "Not revoked.")
