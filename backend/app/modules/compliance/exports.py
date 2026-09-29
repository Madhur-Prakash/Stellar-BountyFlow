"""Personal data exports (the right of access and data portability).

A user asks for an export; the worker's ``data-exports`` job builds a JSON archive of everything BountyFlow holds
about them, stores it gzip-compressed, and tells them by email and in the app. The archive is served through a
short-lived signed link, only to the signed-in owner, until it expires (``DATA_EXPORT_TTL_HOURS``); expiry deletes
the archive.

Screening decisions are left out of the archive: they can relate to sanctions obligations whose disclosure needs
a case-by-case legal review (see docs/compliance.md).
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.blockchain.config import get_network
from app.core.config import get_settings
from app.core.exceptions import Conflict, Forbidden, NotFound
from app.core.logging import get_logger
from app.core.money import fmt
from app.core.rate_limit import hit
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.admin import audit
from app.modules.admin.models import AuditLog, UserReport
from app.modules.applications.models import BountyApplication, BountyAssignment
from app.modules.auth.models import UserSession
from app.modules.bounties.models import Bounty, BountyBookmark
from app.modules.compliance import registry
from app.modules.compliance.models import (
    AccountDeletionRequest,
    DataExport,
    ExportStatus,
    LegalAcceptance,
    LegalDocumentVersion,
)
from app.modules.compliance.schemas import DataExportOut
from app.modules.disputes.models import Dispute
from app.modules.notifications.models import (
    EmailDelivery,
    Notification,
    NotificationPreference,
    NotificationType,
)
from app.modules.notifications.service import create_notification
from app.modules.payments.models import BlockchainTransaction, BountyEscrow, PaymentRecord
from app.modules.submissions.models import BountySubmission, SubmissionRevision
from app.modules.users.models import User, Wallet

logger = get_logger(__name__)

FORMAT_VERSION = 1
LINK_TTL_SECONDS = 600
MAX_ATTEMPTS = 3
STALE_PROCESSING = timedelta(minutes=15)
PRIVACY_PAGE = "/app/privacy"
_LINK_KEY_LABEL = b"bountyflow:data-export-link:v1"


# --- Signed links --------------------------------------------------------------------------


def _link_key() -> bytes:
    # A key of its own, derived from JWT_SECRET: rotating JWT_SECRET also invalidates outstanding links.
    return hmac.new(get_settings().jwt_secret.encode(), _LINK_KEY_LABEL, hashlib.sha256).digest()


def _signature(export_id: uuid.UUID, user_id: uuid.UUID, expires: int) -> str:
    message = f"{export_id}:{user_id}:{expires}".encode()
    return hmac.new(_link_key(), message, hashlib.sha256).hexdigest()


def signed_download_path(export: DataExport, now: float | None = None) -> str:
    expires = int((now or time.time()) + LINK_TTL_SECONDS)
    signature = _signature(export.id, export.user_id, expires)
    prefix = get_settings().api_prefix
    return f"{prefix}/privacy/exports/{export.id}/download?expires={expires}&signature={signature}"


def verify_signature(export: DataExport, expires: int, signature: str) -> bool:
    if expires < int(time.time()):
        return False
    return hmac.compare_digest(_signature(export.id, export.user_id, expires), signature)


def serialize(export: DataExport) -> DataExportOut:
    out = DataExportOut.model_validate(export)
    if export.status == ExportStatus.READY and export.expires_at and export.expires_at > utcnow():
        out.download_url = signed_download_path(export)
    return out


# --- User actions --------------------------------------------------------------------------


async def list_exports(session: AsyncSession, user: User) -> list[DataExportOut]:
    rows = (
        await session.scalars(
            select(DataExport)
            .where(DataExport.user_id == user.id)
            .order_by(DataExport.created_at.desc())
            .limit(10)
        )
    ).all()
    return [serialize(e) for e in rows]


async def request_export(session: AsyncSession, user: User) -> DataExportOut:
    in_progress = await session.scalar(
        select(DataExport).where(
            DataExport.user_id == user.id,
            DataExport.status.in_([ExportStatus.PENDING, ExportStatus.PROCESSING]),
        )
    )
    if in_progress is not None:
        raise Conflict("An export is already being prepared. You will be told when it is ready.")
    await hit("privacy:export", str(user.id), 3, 86_400)
    export = DataExport(user_id=user.id, status=ExportStatus.PENDING)
    session.add(export)
    await session.flush()
    audit.record(
        session,
        actor_id=user.id,
        action="privacy.export_requested",
        entity_type="data_export",
        entity_id=export.id,
        is_public=False,
    )
    await session.commit()
    await session.refresh(export)
    return serialize(export)


async def download(
    session: AsyncSession, user: User, export_id: uuid.UUID, expires: int, signature: str
) -> tuple[str, bytes]:
    export = await session.get(DataExport, export_id, with_for_update=True)
    if export is None or export.user_id != user.id:
        raise NotFound("Export not found.")
    if not verify_signature(export, expires, signature):
        raise Forbidden("This download link has expired. Open your privacy settings for a new one.")
    if export.status != ExportStatus.READY or export.archive is None or not export.expires_at:
        raise NotFound("This export is no longer available.")
    if export.expires_at <= utcnow():
        raise NotFound("This export has expired. Request a new one.")
    body = gzip.decompress(export.archive)
    export.download_count += 1
    export.last_downloaded_at = utcnow()
    audit.record(
        session,
        actor_id=user.id,
        action="privacy.export_downloaded",
        entity_type="data_export",
        entity_id=export.id,
        is_public=False,
    )
    await session.commit()
    stamp = (export.completed_at or utcnow()).strftime("%Y-%m-%d")
    return f"bountyflow-data-{user.username}-{stamp}.json", body


# --- Building the archive -----------------------------------------------------------------


def _value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return fmt(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list | tuple):
        return [_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _value(v) for k, v in value.items()}
    return value


def row_values(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    """The named attributes of one ORM row, JSON-ready. Shared with ``sections.py``."""
    return {f: _value(getattr(obj, f)) for f in fields}


_row = row_values


async def _all(session: AsyncSession, stmt: Any) -> list[Any]:
    return list((await session.scalars(stmt)).unique().all())


async def build_archive(session: AsyncSession, user: User, export: DataExport) -> dict[str, Any]:
    uid = user.id
    network = get_network()
    bounties = await _all(
        session, select(Bounty).where(Bounty.requester_id == uid).order_by(Bounty.created_at)
    )
    bounty_ids = [b.id for b in bounties]
    submissions = await _all(
        session,
        select(BountySubmission)
        .where(BountySubmission.contributor_id == uid)
        .order_by(BountySubmission.created_at),
    )
    revisions = await _all(
        session,
        select(SubmissionRevision)
        .where(SubmissionRevision.submission_id.in_([s.id for s in submissions]))
        .order_by(SubmissionRevision.created_at),
    )
    transactions = await _all(
        session,
        select(BlockchainTransaction)
        .where(BlockchainTransaction.user_id == uid)
        .order_by(BlockchainTransaction.created_at),
    )
    disputes = await _all(
        session,
        select(Dispute)
        .where(
            or_(Dispute.raised_by_id == uid, Dispute.contributor_id == uid, Dispute.bounty_id.in_(bounty_ids))
        )
        .order_by(Dispute.created_at),
    )
    audit_entries = await _all(
        session,
        select(AuditLog)
        .where(
            or_(AuditLog.actor_id == uid, AuditLog.entity_id == uid),
            AuditLog.action.not_like("screening.%"),
        )
        .order_by(AuditLog.created_at),
    )
    preferences = await session.get(NotificationPreference, uid)

    archive: dict[str, Any] = {
        "export": {
            "format_version": FORMAT_VERSION,
            "export_id": str(export.id),
            "generated_at": utcnow().isoformat(),
            "user_id": str(uid),
            "network": network.network,
            "note": (
                "Everything BountyFlow holds about your account. Blockchain transactions are also public on the "
                "Stellar network and cannot be changed or removed there."
            ),
        },
        "profile": {
            **_row(
                user,
                (
                    "id",
                    "email",
                    "username",
                    "display_name",
                    "avatar_url",
                    "bio",
                    "github_url",
                    "portfolio_url",
                    "role",
                    "is_active",
                    "wants_to_request",
                    "wants_to_contribute",
                    "created_at",
                    "updated_at",
                    "email_verified_at",
                    "onboarding_completed_at",
                    "last_login_at",
                ),
            ),
            "interests": list(user.interests or []),
            "skills": user.skill_names,
        },
        "sessions": [
            _row(
                s,
                ("id", "created_at", "last_used_at", "expires_at", "revoked_at", "user_agent", "ip_address"),
            )
            for s in await _all(
                session,
                select(UserSession).where(UserSession.user_id == uid).order_by(UserSession.created_at),
            )
        ],
        "wallets": [
            _row(w, ("id", "public_address", "network", "verification_status", "verified_at", "revoked_at"))
            for w in await _all(
                session, select(Wallet).where(Wallet.user_id == uid).order_by(Wallet.created_at)
            )
        ],
        "bounties": [
            _row(
                b,
                (
                    "id",
                    "slug",
                    "title",
                    "short_description",
                    "description",
                    "category",
                    "difficulty",
                    "status",
                    "reward_amount",
                    "positions_available",
                    "created_at",
                    "published_at",
                    "completed_at",
                    "cancelled_at",
                ),
            )
            for b in bounties
        ],
        "escrows": [
            _row(
                e,
                (
                    "bounty_id",
                    "network",
                    "contract_id",
                    "onchain_bounty_id",
                    "asset_identifier",
                    "state",
                    "required_amount",
                    "funded_amount",
                    "paid_out_amount",
                    "refunded_amount",
                    "requester_address",
                    "last_reconciled_at",
                ),
            )
            for e in await _all(session, select(BountyEscrow).where(BountyEscrow.bounty_id.in_(bounty_ids)))
        ],
        "bookmarks": [
            _row(b, ("bounty_id", "created_at"))
            for b in await _all(session, select(BountyBookmark).where(BountyBookmark.user_id == uid))
        ],
        "applications": [
            _row(
                a,
                (
                    "id",
                    "bounty_id",
                    "status",
                    "cover_message",
                    "relevant_experience",
                    "work_samples",
                    "created_at",
                    "reviewed_at",
                ),
            )
            for a in await _all(
                session,
                select(BountyApplication)
                .where(BountyApplication.contributor_id == uid)
                .order_by(BountyApplication.created_at),
            )
        ],
        "assignments": [
            _row(
                a,
                (
                    "id",
                    "bounty_id",
                    "status",
                    "onchain_assigned",
                    "assigned_at",
                    "completed_at",
                    "released_at",
                ),
            )
            for a in await _all(
                session, select(BountyAssignment).where(BountyAssignment.contributor_id == uid)
            )
        ],
        "submissions": [
            {
                **_row(
                    s,
                    (
                        "id",
                        "bounty_id",
                        "version",
                        "status",
                        "description",
                        "evidence_url",
                        "evidence_links",
                        "review_feedback",
                        "created_at",
                        "reviewed_at",
                    ),
                ),
                "revisions": [
                    _row(r, ("version", "description", "evidence_url", "evidence_links", "created_at"))
                    for r in revisions
                    if r.submission_id == s.id
                ],
            }
            for s in submissions
        ],
        "payments_received": [
            _row(
                p,
                (
                    "id",
                    "bounty_id",
                    "amount",
                    "asset_identifier",
                    "payment_status",
                    "created_at",
                    "settled_at",
                ),
            )
            for p in await _all(
                session,
                select(PaymentRecord)
                .where(PaymentRecord.contributor_id == uid)
                .order_by(PaymentRecord.created_at),
            )
        ],
        "payouts_made": [
            _row(
                p,
                (
                    "id",
                    "bounty_id",
                    "contributor_id",
                    "amount",
                    "asset_identifier",
                    "payment_status",
                    "created_at",
                    "settled_at",
                ),
            )
            for p in await _all(
                session,
                select(PaymentRecord)
                .where(PaymentRecord.bounty_id.in_(bounty_ids))
                .order_by(PaymentRecord.created_at),
            )
        ],
        "transactions": [
            {
                **_row(
                    t,
                    (
                        "id",
                        "bounty_id",
                        "transaction_type",
                        "status",
                        "network",
                        "transaction_hash",
                        "amount",
                        "asset_identifier",
                        "source_address",
                        "destination_address",
                        "contract_id",
                        "function_name",
                        "fee_stroops",
                        "ledger_sequence",
                        "created_at",
                        "submitted_at",
                        "confirmed_at",
                        "failure_reason",
                    ),
                ),
                "explorer_url": network.tx_url(t.transaction_hash) if t.submitted_at else None,
            }
            for t in transactions
        ],
        "disputes": [
            {
                **_row(
                    d,
                    (
                        "id",
                        "bounty_id",
                        "status",
                        "reason",
                        "resolution",
                        "resolution_note",
                        "created_at",
                        "resolved_at",
                    ),
                ),
                "raised_by_you": d.raised_by_id == uid,
                "your_evidence": [
                    _row(e, ("description", "url", "created_at"))
                    for e in d.evidence
                    if e.submitted_by_id == uid
                ],
            }
            for d in disputes
        ],
        "reports_filed": [
            _row(r, ("id", "target_type", "target_id", "reason", "status", "created_at", "resolved_at"))
            for r in await _all(session, select(UserReport).where(UserReport.reporter_id == uid))
        ],
        "notifications": [
            _row(n, ("id", "notification_type", "title", "message", "link", "created_at", "read_at"))
            for n in await _all(
                session,
                select(Notification).where(Notification.user_id == uid).order_by(Notification.created_at),
            )
        ],
        "notification_preferences": (
            {"email_enabled": preferences.email_enabled, "types": preferences.types} if preferences else None
        ),
        "emails_sent": [
            _row(e, ("template", "subject", "to_address", "status", "created_at", "sent_at"))
            for e in await _all(
                session,
                select(EmailDelivery).where(EmailDelivery.user_id == uid).order_by(EmailDelivery.created_at),
            )
        ],
        "legal_acceptances": [
            {
                "document": a.document.value,
                "version": v.version,
                "accepted_at": a.accepted_at.isoformat(),
                "source": a.source,
            }
            for a, v in (
                await session.execute(
                    select(LegalAcceptance, LegalDocumentVersion)
                    .join(LegalDocumentVersion, LegalDocumentVersion.id == LegalAcceptance.version_id)
                    .where(LegalAcceptance.user_id == uid)
                    .order_by(LegalAcceptance.accepted_at)
                )
            ).all()
        ],
        "privacy_requests": {
            "exports": [
                _row(e, ("id", "status", "created_at", "completed_at", "expires_at", "download_count"))
                for e in await _all(session, select(DataExport).where(DataExport.user_id == uid))
            ],
            "deletions": [
                _row(d, ("id", "status", "created_at", "scheduled_for", "cancelled_at", "completed_at"))
                for d in await _all(
                    session, select(AccountDeletionRequest).where(AccountDeletionRequest.user_id == uid)
                )
            ],
        },
        "audit_entries": [
            _row(
                a,
                ("created_at", "action", "entity_type", "entity_id", "bounty_id", "metadata_", "request_id"),
            )
            for a in audit_entries
        ],
    }
    registry.load_sections()
    for name, section in registry.EXPORT_SECTIONS.items():
        archive[name] = _value(await section(session, user))
    return archive


def compress(archive: dict[str, Any]) -> bytes:
    body = json.dumps(archive, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    return gzip.compress(body, compresslevel=6)


# --- Worker --------------------------------------------------------------------------------


async def _claim_next(session: AsyncSession) -> DataExport | None:
    now = utcnow()
    export = await session.scalar(
        select(DataExport)
        .where(
            or_(
                DataExport.status == ExportStatus.PENDING,
                (DataExport.status == ExportStatus.PROCESSING)
                & (DataExport.started_at < now - STALE_PROCESSING),
            )
        )
        .order_by(DataExport.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if export is None:
        return None
    export.status = ExportStatus.PROCESSING
    export.started_at = now
    export.attempts += 1
    await session.commit()
    return export


async def _record_failure(session: AsyncSession, export_id: uuid.UUID, exc: Exception) -> None:
    """Keep the error and either retry the export later or give up, in one transaction of its own."""
    await session.rollback()
    failed = await session.get(DataExport, export_id, with_for_update=True)
    if failed is not None:
        failed.failure_reason = f"{type(exc).__name__}: {exc}"[:500]
        failed.status = ExportStatus.FAILED if failed.attempts >= MAX_ATTEMPTS else ExportStatus.PENDING
        await session.commit()
    logger.exception("data_export_failed", export_id=str(export_id))


async def process_next(session: AsyncSession) -> bool:
    """Builds one pending export. Returns False when there was nothing to do.

    Three transactions, deliberately: claim the row, then read the archive with nothing locked (it walks most
    of the schema and can take a while), then write the result. Only the first and last hold a row lock, so a
    large export never blocks the user's own writes."""
    export = await _claim_next(session)
    if export is None:
        return False
    export_id, user_id = export.id, export.user_id

    try:
        user = await session.get(User, user_id)
        if user is None:
            raise RuntimeError("the account no longer exists")
        archive = compress(await build_archive(session, user, export))
        display_name, size_bytes = user.display_name, len(gzip.decompress(archive))
    except Exception as exc:
        await _record_failure(session, export_id, exc)
        return True
    finally:
        # Close the read transaction the archive build opened before taking any write lock.
        await session.rollback()

    now = utcnow()
    expires_at = now + timedelta(hours=get_settings().data_export_ttl_hours)
    try:
        ready = await session.get(DataExport, export_id, with_for_update=True)
        if ready is None or ready.status != ExportStatus.PROCESSING:
            # Another worker claimed it after this one's lease went stale; its result wins.
            await session.rollback()
            logger.info("data_export_superseded", export_id=str(export_id))
            return True
        ready.status = ExportStatus.READY
        ready.archive = archive
        ready.archive_sha256 = hashlib.sha256(archive).hexdigest()
        ready.size_bytes = size_bytes
        ready.completed_at = now
        ready.expires_at = expires_at
        ready.failure_reason = None
        await create_notification(
            session,
            user_id=user_id,
            notification_type=NotificationType.SYSTEM,
            title="Your data export is ready",
            message="Download it from your privacy settings before the link expires.",
            link=PRIVACY_PAGE,
            payload={"export_id": str(export_id), "transactional_email": True},
            source_event_id=export_id,
        )
        add_event(
            session,
            event_type=EventType.DATA_EXPORT_READY,
            aggregate_type="user",
            aggregate_id=user_id,
            payload={"user_id": user_id, "export_id": export_id, "expires_at": expires_at.isoformat()},
        )
        await session.commit()
    except Exception as exc:
        await _record_failure(session, export_id, exc)
        return True
    logger.info("data_export_ready", export_id=str(export_id), size_bytes=size_bytes, user=display_name)
    return True


async def expire_ready(session: AsyncSession) -> int:
    result = await session.execute(
        update(DataExport)
        .where(DataExport.status == ExportStatus.READY, DataExport.expires_at <= utcnow())
        .values(status=ExportStatus.EXPIRED, archive=None)
        .returning(DataExport.id)
    )
    expired = len(result.all())
    await session.commit()
    return expired
