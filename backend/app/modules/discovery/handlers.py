"""Event handlers for saved searches.

* ``discovery-worker`` (``bounty.events``): a published or newly funded bounty is matched against every saved
  search, and instant alerts are raised in the same transaction.
* ``email-worker`` (``notification.events``): alert and digest emails. Everything is re-checked at send time (the
  search still exists and still wants email, the user allows saved-search email, the bounty is still listed), and
  each email is sent at most once per event (``send_once``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.messaging.events import EventEnvelope, EventType, Topics
from app.messaging.registry import on
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties.models import Bounty, BountyStatus, Visibility
from app.modules.discovery import emails
from app.modules.discovery.models import AlertFrequency, SavedSearch
from app.modules.discovery.saved_searches import match_bounty
from app.modules.notifications import email as mail
from app.modules.notifications import email_handlers
from app.modules.notifications.models import NotificationPreference, NotificationType
from app.modules.users.models import User

logger = get_logger(__name__)

CONSUMER = "discovery-worker"
TOPICS = [Topics.BOUNTY]


@on(CONSUMER, TOPICS, EventType.BOUNTY_PUBLISHED, EventType.BOUNTY_FUNDED)
async def handle_bounty_listed(session: AsyncSession, envelope: EventEnvelope) -> None:
    await match_bounty(
        session,
        uuid.UUID(str(envelope.payload["bounty_id"])),
        trigger_event=envelope.event_type,
        source_event_id=envelope.event_id,
    )


async def _recipient(session: AsyncSession, payload: dict[str, Any]) -> User | None:
    user = await session.get(User, uuid.UUID(str(payload["user_id"])))
    if user is None:
        return None
    preference = await session.get(NotificationPreference, user.id)
    if not email_handlers.should_email_notification(user, preference, NotificationType.SAVED_SEARCH_MATCH):
        logger.info("saved_search_email_skipped_by_preferences", user_id=str(user.id))
        return None
    return user


async def _searches(
    session: AsyncSession, user: User, ids: list[Any], frequency: AlertFrequency
) -> list[SavedSearch]:
    rows = (
        await session.scalars(
            select(SavedSearch).where(
                SavedSearch.id.in_([uuid.UUID(str(i)) for i in ids]),
                SavedSearch.user_id == user.id,
                SavedSearch.notify_email.is_(True),
                SavedSearch.is_paused.is_(False),
                SavedSearch.alert_frequency == frequency,
            )
        )
    ).all()
    return sorted(rows, key=lambda s: s.name.lower())


def _listed(bounty: Bounty | None) -> bool:
    return (
        bounty is not None
        and bounty.visibility == Visibility.PUBLIC
        and not bounty.is_hidden
        and bounty.status != BountyStatus.DRAFT
    )


@on(email_handlers.CONSUMER, email_handlers.TOPICS, EventType.SAVED_SEARCH_ALERT)
async def handle_alert_email(session: AsyncSession, envelope: EventEnvelope) -> None:
    payload = envelope.payload
    user = await _recipient(session, payload)
    if user is None:
        return
    searches = await _searches(session, user, payload["saved_search_ids"], AlertFrequency.INSTANT)
    bounty = await bounty_repo.get(session, uuid.UUID(str(payload["bounty_id"])))
    if not searches or bounty is None or not _listed(bounty):
        return
    rendered = emails.render_alert(recipient_name=user.display_name, bounty=bounty, searches=searches)
    unsubscribe = emails.unsubscribe_url(searches[0])

    async def prepare(_: AsyncSession) -> mail.RenderedEmail:
        return rendered

    await email_handlers.send_once(
        key=email_handlers.idempotency_key(envelope.event_id, emails.ALERT_TEMPLATE),
        user_id=user.id,
        to=user.email,
        template=emails.ALERT_TEMPLATE,
        prepare=prepare,
        headers={"List-Unsubscribe": f"<{unsubscribe}>"},
    )


@on(email_handlers.CONSUMER, email_handlers.TOPICS, EventType.SAVED_SEARCH_DIGEST)
async def handle_digest_email(session: AsyncSession, envelope: EventEnvelope) -> None:
    payload = envelope.payload
    user = await _recipient(session, payload)
    if user is None:
        return
    frequency = AlertFrequency(payload["frequency"])
    wanted = {uuid.UUID(str(s["saved_search_id"])): s["bounty_ids"] for s in payload["sections"]}
    searches = await _searches(session, user, list(wanted), frequency)
    bounty_ids = {uuid.UUID(str(b)) for ids in wanted.values() for b in ids}
    found = (await session.scalars(select(Bounty).where(Bounty.id.in_(bounty_ids)))).unique().all()
    bounties = {b.id: b for b in found if _listed(b)}
    sections = []
    for search in searches:
        listed = [bounties[b] for b in (uuid.UUID(str(i)) for i in wanted[search.id]) if b in bounties]
        if listed:
            sections.append(emails.section(search, listed))
    if not sections:
        return
    rendered = emails.render_digest(recipient_name=user.display_name, frequency=frequency, sections=sections)

    async def prepare(_: AsyncSession) -> mail.RenderedEmail:
        return rendered

    await email_handlers.send_once(
        key=email_handlers.idempotency_key(envelope.event_id, emails.DIGEST_TEMPLATE),
        user_id=user.id,
        to=user.email,
        template=emails.DIGEST_TEMPLATE,
        prepare=prepare,
        headers={"List-Unsubscribe": f"<{sections[0].unsubscribe_url}>"},
    )
