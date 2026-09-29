"""Terms and privacy notice versions, and who accepted which.

* Staff publish a version with a short summary of what changed and the date it takes effect. A version scheduled
  for the future is announced in the workspace ahead of time and can be withdrawn until then.
* Once a version is in effect, the workspace is gated until the user accepts it (the API reports
  ``needs_acceptance``; the SPA shows the gate).
* Signing up is acceptance of the versions in effect at that moment (the registration form requires the terms
  box), so an account created after a version took effect is not asked again. The worker also records that
  acceptance explicitly from the ``user.registered`` event (``source="registration"``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.logging import get_context
from app.core.security import utcnow
from app.modules.admin import audit
from app.modules.compliance.models import LegalAcceptance, LegalDocument, LegalDocumentVersion
from app.modules.compliance.schemas import (
    LegalDocumentStatus,
    LegalStatusOut,
    LegalVersionCreate,
    LegalVersionOut,
)
from app.modules.users.models import User

# A publish "now" may carry a timestamp a little behind the server clock.
_CLOCK_SKEW = timedelta(minutes=5)


async def _db_now(session: AsyncSession) -> datetime:
    """The database clock. Account creation times come from it too, so "signed up after the version took
    effect" never depends on the skew between the API host and the database."""
    now = await session.scalar(select(func.now()))
    return now if isinstance(now, datetime) else utcnow()


async def _live_versions(session: AsyncSession) -> list[LegalDocumentVersion]:
    return list(
        (
            await session.scalars(
                select(LegalDocumentVersion)
                .where(LegalDocumentVersion.withdrawn_at.is_(None))
                .order_by(LegalDocumentVersion.effective_at.desc(), LegalDocumentVersion.created_at.desc())
            )
        ).all()
    )


def _split(
    versions: list[LegalDocumentVersion], document: LegalDocument, now: datetime
) -> tuple[LegalDocumentVersion | None, LegalDocumentVersion | None]:
    """(version in effect, the next scheduled version) for one document."""
    mine = [v for v in versions if v.document == document]
    current = next((v for v in mine if v.effective_at <= now), None)
    scheduled = sorted((v for v in mine if v.effective_at > now), key=lambda v: v.effective_at)
    return current, scheduled[0] if scheduled else None


async def current_versions(session: AsyncSession) -> list[LegalVersionOut]:
    now = await _db_now(session)
    versions = await _live_versions(session)
    out: list[LegalVersionOut] = []
    for document in LegalDocument:
        current, _ = _split(versions, document, now)
        if current is not None:
            out.append(LegalVersionOut.model_validate(current))
    return out


async def status(session: AsyncSession, user: User) -> LegalStatusOut:
    now = await _db_now(session)
    versions = await _live_versions(session)
    accepted = {
        row.version_id: row.accepted_at
        for row in (
            await session.scalars(select(LegalAcceptance).where(LegalAcceptance.user_id == user.id))
        ).all()
    }
    documents: list[LegalDocumentStatus] = []
    for document in LegalDocument:
        current, upcoming = _split(versions, document, now)
        # Signing up after a version took effect is acceptance of it (the form requires the terms box).
        accepted_current = current is not None and (
            current.id in accepted or user.created_at >= current.effective_at
        )
        accepted_upcoming = upcoming is not None and upcoming.id in accepted
        documents.append(
            LegalDocumentStatus(
                document=document,
                current=LegalVersionOut.model_validate(current) if current else None,
                upcoming=LegalVersionOut.model_validate(upcoming) if upcoming else None,
                accepted_current=accepted_current,
                accepted_upcoming=accepted_upcoming,
                accepted_at=accepted.get(current.id) if current else None,
            )
        )
    return LegalStatusOut(
        documents=documents,
        needs_acceptance=any(d.current is not None and not d.accepted_current for d in documents),
        upcoming_pending=any(d.upcoming is not None and not d.accepted_upcoming for d in documents),
    )


async def _record(
    session: AsyncSession,
    user_id: uuid.UUID,
    version: LegalDocumentVersion,
    source: str,
    accepted_at: datetime | None = None,
) -> bool:
    stmt = (
        insert(LegalAcceptance)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            version_id=version.id,
            document=version.document,
            accepted_at=accepted_at or utcnow(),
            source=source,
            request_id=get_context().get("request_id"),
        )
        .on_conflict_do_nothing(constraint="uq_legal_acceptances_user_version")
        .returning(LegalAcceptance.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def accept(session: AsyncSession, user: User, version_ids: list[uuid.UUID]) -> LegalStatusOut:
    """Records acceptance of versions that are in effect or scheduled (never of withdrawn or superseded ones)."""
    now = await _db_now(session)
    versions = await _live_versions(session)
    acceptable: dict[uuid.UUID, LegalDocumentVersion] = {}
    for document in LegalDocument:
        current, upcoming = _split(versions, document, now)
        for v in (current, upcoming):
            if v is not None:
                acceptable[v.id] = v
    unknown = [str(v) for v in version_ids if v not in acceptable]
    if unknown:
        raise ValidationFailed(
            "These versions are not current. Reload the page and try again.", details={"version_ids": unknown}
        )
    recorded = []
    for version_id in dict.fromkeys(version_ids):
        version = acceptable[version_id]
        if await _record(session, user.id, version, "prompt"):
            recorded.append({"document": version.document.value, "version": version.version})
    if recorded:
        audit.record(
            session,
            actor_id=user.id,
            action="legal.accepted",
            entity_type="user",
            entity_id=user.id,
            metadata={"versions": recorded},
            is_public=False,
        )
    await session.commit()
    return await status(session, user)


async def record_registration(session: AsyncSession, user_id: uuid.UUID, registered_at: datetime) -> int:
    """Explicit acceptance rows for the versions in effect when the account was created."""
    versions = await _live_versions(session)
    count = 0
    for document in LegalDocument:
        current, _ = _split(versions, document, registered_at)
        if current is not None and await _record(session, user_id, current, "registration", registered_at):
            count += 1
    return count


# --- Staff ---------------------------------------------------------------------------------


async def list_versions(session: AsyncSession) -> list[tuple[LegalDocumentVersion, int]]:
    counts = dict(
        (
            await session.execute(
                select(LegalAcceptance.version_id, func.count(LegalAcceptance.id)).group_by(
                    LegalAcceptance.version_id
                )
            )
        ).all()
    )
    rows = (
        await session.scalars(
            select(LegalDocumentVersion).order_by(
                LegalDocumentVersion.effective_at.desc(), LegalDocumentVersion.created_at.desc()
            )
        )
    ).all()
    return [(v, int(counts.get(v.id, 0))) for v in rows]


async def publish(session: AsyncSession, actor: User, data: LegalVersionCreate) -> LegalDocumentVersion:
    now = await _db_now(session)
    effective_at = data.effective_at or now
    if effective_at.tzinfo is None:
        raise ValidationFailed(
            "Give the effective date with a time zone.",
            details=[{"field": "effective_at", "message": "Needs a time zone"}],
        )
    if effective_at < now - _CLOCK_SKEW:
        raise ValidationFailed(
            "A new version cannot take effect in the past.",
            details=[{"field": "effective_at", "message": "In the past"}],
        )
    effective_at = max(effective_at, now)
    exists = await session.scalar(
        select(LegalDocumentVersion.id).where(
            LegalDocumentVersion.document == data.document, LegalDocumentVersion.version == data.version
        )
    )
    if exists is not None:
        raise Conflict(
            "That version label is already used for this document.",
            details=[{"field": "version", "message": "Already used"}],
        )
    version = LegalDocumentVersion(
        document=data.document,
        version=data.version,
        summary=data.summary.strip(),
        effective_at=effective_at,
        published_by_id=actor.id,
    )
    session.add(version)
    await session.flush()
    audit.record(
        session,
        actor_id=actor.id,
        action="legal.version_published",
        entity_type="legal_version",
        entity_id=version.id,
        metadata={
            "document": data.document.value,
            "version": data.version,
            "effective_at": effective_at.isoformat(),
        },
        is_public=False,
    )
    await session.commit()
    await session.refresh(version)
    return version


async def withdraw(session: AsyncSession, actor: User, version_id: uuid.UUID) -> LegalDocumentVersion:
    version = await session.get(LegalDocumentVersion, version_id, with_for_update=True)
    if version is None or version.withdrawn_at is not None:
        raise NotFound("Version not found.")
    if version.effective_at <= await _db_now(session):
        raise Conflict("This version is already in effect. Publish a newer version instead.")
    version.withdrawn_at = utcnow()
    version.withdrawn_by_id = actor.id
    audit.record(
        session,
        actor_id=actor.id,
        action="legal.version_withdrawn",
        entity_type="legal_version",
        entity_id=version.id,
        metadata={"document": version.document.value, "version": version.version},
        is_public=False,
    )
    await session.commit()
    await session.refresh(version)
    return version
