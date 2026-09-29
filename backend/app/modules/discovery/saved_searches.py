"""Saved searches: management, matching published or funded bounties, alerts, digests, and unsubscribing.

Matching uses the marketplace's own query builder (``bounties.repository.marketplace_query``): a saved search
matches a bounty exactly when the marketplace, given the search's filters at that moment, would list it. A bounty
matches a search at most once (the match row's primary key), never alerts on the searcher's own bounties, and a
match is only recorded from ``bounty.published`` / ``bounty.funded`` events, so "new since you last looked" counts
bounties that actually became available.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, func, literal, select, tuple_, union_all, update
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.security import utcnow
from app.messaging.events import EventType
from app.messaging.outbox import add_event
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties.models import Bounty
from app.modules.bounties.schemas import MarketplaceFilters
from app.modules.discovery.models import (
    DIGEST_FREQUENCIES,
    AlertFrequency,
    MatchDelivery,
    SavedSearch,
    SavedSearchMatch,
)
from app.modules.discovery.schemas import (
    MAX_SAVED_SEARCHES,
    DigestRunResult,
    SavedSearchCreate,
    SavedSearchFilters,
    SavedSearchOut,
    SavedSearchUpdate,
    UnsubscribeResult,
)
from app.modules.discovery.tokens import read_unsubscribe_token
from app.modules.notifications import preferences as prefs
from app.modules.notifications import repository as notification_repo
from app.modules.notifications.models import NotificationPreference, NotificationType
from app.modules.notifications.service import create_notification
from app.modules.users.models import User

logger = get_logger(__name__)

MATCH_BATCH = 50
DIGEST_BATCH = 500
SAVED_SEARCHES_LINK = "/app/saved?tab=searches"


# --- Filters and schedule -------------------------------------------------------------------


def match_clause(filters: MarketplaceFilters) -> ColumnElement[bool]:
    """The WHERE clause the marketplace applies for ``filters``, taken from the repository's own query builder so
    saved searches can never drift from what the marketplace lists."""
    _, count = bounty_repo.marketplace_query(filters)
    clause = count.whereclause
    assert clause is not None  # the marketplace always restricts to public, listed bounties
    return clause


def search_filters(search: SavedSearch) -> SavedSearchFilters:
    return SavedSearchFilters.from_stored(search.filters)


def next_digest_time(frequency: AlertFrequency, after: datetime, hour: int | None = None) -> datetime | None:
    """The next digest slot strictly after ``after``: daily at ``hour`` UTC, weekly on Mondays at ``hour``."""
    if frequency not in DIGEST_FREQUENCIES:
        return None
    hour = get_settings().discovery_digest_hour_utc if hour is None else hour
    after = after.astimezone(UTC)
    slot = after.replace(hour=hour, minute=0, second=0, microsecond=0)
    if frequency == AlertFrequency.DAILY:
        return slot if slot > after else slot + timedelta(days=1)
    slot += timedelta(days=(0 - slot.weekday()) % 7)
    return slot if slot > after else slot + timedelta(days=7)


# --- Management -------------------------------------------------------------------------------


def _search_id(search: SavedSearch) -> Any:
    """The search's id as a typed SQL literal, so a UNION ALL branch can label which search it came from."""
    return literal(search.id, type_=PG_UUID(as_uuid=True))


async def _union_all(session: AsyncSession, branches: list[Any]) -> Sequence[Any]:
    """Run one statement per batch of branches (each branch is one saved search's clause) and return every row."""
    rows: list[Any] = []
    for start in range(0, len(branches), MATCH_BATCH):
        chunk = branches[start : start + MATCH_BATCH]
        query: Any = chunk[0]
        if len(chunk) > 1:
            query = union_all(*chunk)
        rows.extend((await session.execute(query)).all())
    return rows


async def _new_counts(
    session: AsyncSession, searches: Sequence[SavedSearch], now: datetime
) -> dict[uuid.UUID, int]:
    """Bounties that matched each search since it was last opened and that it still lists, counted in SQL:
    one aggregate branch per search, unioned into a single statement per batch (never a query per search)."""
    if not searches:
        return {}
    branches = [
        select(
            _search_id(search).label("saved_search_id"),
            func.count(SavedSearchMatch.bounty_id).label("new_count"),
        )
        .select_from(SavedSearchMatch)
        .join(Bounty, Bounty.id == SavedSearchMatch.bounty_id)
        .where(
            SavedSearchMatch.saved_search_id == search.id,
            SavedSearchMatch.matched_at > search.last_viewed_at,
            match_clause(search_filters(search).to_marketplace(now)),
        )
        for search in searches
    ]
    counts = {search.id: 0 for search in searches}
    for search_id, new_count in await _union_all(session, branches):
        counts[search_id] = int(new_count or 0)
    return counts


def _out(search: SavedSearch, new_count: int) -> SavedSearchOut:
    return SavedSearchOut(
        id=search.id,
        name=search.name,
        filters=search_filters(search),
        alert_frequency=search.alert_frequency,
        notify_in_app=search.notify_in_app,
        notify_email=search.notify_email,
        is_paused=search.is_paused,
        new_count=new_count,
        last_viewed_at=search.last_viewed_at,
        next_digest_at=search.next_digest_at,
        created_at=search.created_at,
        updated_at=search.updated_at,
    )


async def _owned(
    session: AsyncSession, user: User, search_id: uuid.UUID, *, for_update: bool = False
) -> SavedSearch:
    stmt = select(SavedSearch).where(SavedSearch.id == search_id, SavedSearch.user_id == user.id)
    if for_update:
        stmt = stmt.with_for_update(of=SavedSearch).execution_options(populate_existing=True)
    search = await session.scalar(stmt)
    if search is None:
        raise NotFound("Saved search not found.")
    return search


async def _opt_in_to_email(session: AsyncSession, user: User) -> None:
    """Choosing email for a saved search is an explicit opt-in, so it turns on saved-search emails in the user's
    notification settings (the global email switch is left as the user set it)."""
    preference = await notification_repo.get_preference(session, user.id)
    stored = dict(preference.types) if preference else {}
    if prefs.merge_preferences(stored)[NotificationType.SAVED_SEARCH_MATCH.value]["email"]:
        return
    stored = prefs.apply_update(stored, {NotificationType.SAVED_SEARCH_MATCH.value: {"email": True}})
    await notification_repo.upsert_preference(
        session,
        user.id,
        email_enabled=preference.email_enabled if preference else prefs.DEFAULT_EMAIL_ENABLED,
        types=stored,
    )


async def _skip_pending(session: AsyncSession, search_id: uuid.UUID) -> None:
    await session.execute(
        update(SavedSearchMatch)
        .where(
            SavedSearchMatch.saved_search_id == search_id, SavedSearchMatch.delivery == MatchDelivery.PENDING
        )
        .values(delivery=MatchDelivery.SKIPPED)
    )


async def list_searches(session: AsyncSession, user: User) -> list[SavedSearchOut]:
    searches = (
        await session.scalars(
            select(SavedSearch).where(SavedSearch.user_id == user.id).order_by(SavedSearch.created_at.desc())
        )
    ).all()
    counts = await _new_counts(session, searches, utcnow())
    return [_out(s, counts.get(s.id, 0)) for s in searches]


async def get_search(session: AsyncSession, user: User, search_id: uuid.UUID) -> SavedSearchOut:
    search = await _owned(session, user, search_id)
    counts = await _new_counts(session, [search], utcnow())
    return _out(search, counts[search.id])


async def create_search(session: AsyncSession, user: User, data: SavedSearchCreate) -> SavedSearchOut:
    existing = int(
        await session.scalar(select(func.count(SavedSearch.id)).where(SavedSearch.user_id == user.id)) or 0
    )
    if existing >= MAX_SAVED_SEARCHES:
        raise Conflict(f"You can keep up to {MAX_SAVED_SEARCHES} saved searches. Delete one to save another.")
    now = utcnow()
    search = SavedSearch(
        id=uuid.uuid4(),
        user_id=user.id,
        name=data.name,
        filters=data.filters.stored(),
        alert_frequency=data.alert_frequency,
        notify_in_app=data.notify_in_app,
        notify_email=data.notify_email,
        is_paused=False,
        last_viewed_at=now,
        next_digest_at=next_digest_time(data.alert_frequency, now),
    )
    session.add(search)
    if data.notify_email and data.alert_frequency != AlertFrequency.OFF:
        await _opt_in_to_email(session, user)
    await session.commit()
    await session.refresh(search)
    logger.info(
        "saved_search_created", saved_search_id=str(search.id), frequency=search.alert_frequency.value
    )
    return _out(search, 0)


async def update_search(
    session: AsyncSession, user: User, search_id: uuid.UUID, data: SavedSearchUpdate
) -> SavedSearchOut:
    # One transaction: the row is locked, its matches are re-marked and the preference opt-in is written, then a
    # single commit at the end.
    search = await _owned(session, user, search_id, for_update=True)
    changes = data.model_dump(exclude_unset=True)
    now = utcnow()
    if changes.get("name") is not None:
        search.name = changes["name"]
    if data.filters is not None:
        search.filters = data.filters.stored()
    for flag in ("notify_in_app", "notify_email", "is_paused"):
        if changes.get(flag) is not None:
            setattr(search, flag, changes[flag])
    frequency = changes.get("alert_frequency")
    if frequency is not None and frequency != search.alert_frequency:
        if search.alert_frequency in DIGEST_FREQUENCIES:
            await _skip_pending(session, search.id)  # a digest that will no longer be sent
        search.alert_frequency = frequency
        search.next_digest_at = next_digest_time(frequency, now)
    if changes.get("is_paused") is True:
        await _skip_pending(session, search.id)
    if search.alert_frequency in DIGEST_FREQUENCIES and search.next_digest_at is None:
        search.next_digest_at = next_digest_time(search.alert_frequency, now)
    email_now_on = changes.get("notify_email") is True or (
        frequency is not None and frequency != AlertFrequency.OFF
    )
    if email_now_on and search.notify_email and search.alerts_active:
        await _opt_in_to_email(session, user)
    await session.commit()
    await session.refresh(search)
    counts = await _new_counts(session, [search], now)
    return _out(search, counts[search.id])


async def delete_search(session: AsyncSession, user: User, search_id: uuid.UUID) -> None:
    search = await _owned(session, user, search_id, for_update=True)
    await session.delete(search)  # its matches cascade
    await session.commit()


async def mark_viewed(session: AsyncSession, user: User, search_id: uuid.UUID) -> SavedSearchOut:
    search = await _owned(session, user, search_id, for_update=True)
    search.last_viewed_at = utcnow()
    await session.commit()
    await session.refresh(search)
    return _out(search, 0)


async def unsubscribe(session: AsyncSession, token: str) -> UnsubscribeResult:
    """Turns a search's alerts off from the signed link in an alert email (no session needed; idempotent)."""
    claims = read_unsubscribe_token(token)
    if claims is None:
        raise ValidationFailed(
            "This unsubscribe link is not valid.", details=[{"field": "token", "message": "Invalid token"}]
        )
    search = await session.scalar(
        select(SavedSearch)
        .where(SavedSearch.id == claims.saved_search_id, SavedSearch.user_id == claims.user_id)
        .with_for_update(of=SavedSearch)
    )
    if search is None:
        raise NotFound("This saved search no longer exists.")
    if search.alert_frequency != AlertFrequency.OFF:
        if search.alert_frequency in DIGEST_FREQUENCIES:
            await _skip_pending(session, search.id)
        search.alert_frequency = AlertFrequency.OFF
        search.next_digest_at = None
        logger.info("saved_search_unsubscribed", saved_search_id=str(search.id))
    await session.commit()
    return UnsubscribeResult(
        saved_search_id=search.id, name=search.name, alert_frequency=search.alert_frequency
    )


# --- Matching (worker) ---------------------------------------------------------------------------


def _quote(value: str) -> str:
    return f"“{value}”"


async def matching_pairs(
    session: AsyncSession,
    candidates: Sequence[tuple[SavedSearch, Sequence[uuid.UUID]]],
    now: datetime,
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """For each (saved search, candidate bounty ids), the ids the marketplace would still list for that search.

    Every search's clause becomes one branch of a UNION ALL, so a whole batch is decided by the database in a
    single statement instead of one query per search."""
    branches = [
        select(_search_id(search).label("saved_search_id"), Bounty.id.label("bounty_id")).where(
            Bounty.id.in_(list(ids)), match_clause(search_filters(search).to_marketplace(now))
        )
        for search, ids in candidates
        if ids
    ]
    matched: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for search_id, bounty_id in await _union_all(session, branches):
        matched[search_id].append(bounty_id)
    return matched


async def match_bounty(
    session: AsyncSession, bounty_id: uuid.UUID, *, trigger_event: str, source_event_id: uuid.UUID | None
) -> list[uuid.UUID]:
    """Records which saved searches this bounty now matches and alerts the instant ones; returns the searches
    matched for the first time. Runs inside the event handler's transaction, so the matches, the in-app
    notifications and the staged email events commit together with the processed-event marker."""
    bounty = await bounty_repo.get(session, bounty_id)
    if bounty is None:
        return []
    now = utcnow()
    # One query for every candidate search (joined to its owner), then one batched statement to decide which of
    # them the bounty matches. A search is never matched against its own owner's bounty.
    searches = (
        await session.scalars(
            select(SavedSearch)
            .join(User, User.id == SavedSearch.user_id)
            .where(SavedSearch.user_id != bounty.requester_id, User.is_active.is_(True))
            .order_by(SavedSearch.id)
        )
    ).all()
    if not searches:
        return []
    matched = set(await matching_pairs(session, [(s, [bounty.id]) for s in searches], now))
    if not matched:
        return []
    by_id = {s.id: s for s in searches}
    rows: list[dict[str, Any]] = []
    for search_id in sorted(matched, key=str):  # deterministic insert order across concurrent handlers
        search = by_id[search_id]
        if not search.alerts_active:
            delivery, delivered = MatchDelivery.SKIPPED, None
        elif search.alert_frequency == AlertFrequency.INSTANT:
            delivery, delivered = MatchDelivery.ALERTED, now
        else:
            delivery, delivered = MatchDelivery.PENDING, None
        rows.append(
            {
                "saved_search_id": search_id,
                "bounty_id": bounty.id,
                "matched_at": now,
                "trigger_event": trigger_event,
                "source_event_id": source_event_id,
                "delivery": delivery,
                "delivered_at": delivered,
            }
        )
    inserted = set(
        (
            await session.scalars(
                insert(SavedSearchMatch)
                .values(rows)
                .on_conflict_do_nothing(index_elements=["saved_search_id", "bounty_id"])
                .returning(SavedSearchMatch.saved_search_id)
            )
        ).all()
    )
    instant: dict[uuid.UUID, list[SavedSearch]] = defaultdict(list)
    for search_id in sorted(inserted, key=str):
        search = by_id[search_id]
        if search.alerts_active and search.alert_frequency == AlertFrequency.INSTANT:
            instant[search.user_id].append(search)
    await _preload_preferences(session, list(instant))
    for user_id, user_searches in instant.items():
        await _instant_alert(session, user_id, bounty, user_searches, source_event_id)
    logger.info(
        "saved_search_matches_recorded",
        bounty_id=str(bounty.id),
        matched=len(inserted),
        instant_alerts=len(instant),
        trigger=trigger_event,
    )
    return sorted(inserted, key=str)


async def _preload_preferences(session: AsyncSession, user_ids: Sequence[uuid.UUID]) -> None:
    """Load every recipient's notification preference in one query. ``create_notification`` then reads each one
    from the session's identity map instead of issuing a query per recipient."""
    if user_ids:
        await session.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id.in_(list(user_ids)))
        )


async def _instant_alert(
    session: AsyncSession,
    user_id: uuid.UUID,
    bounty: Bounty,
    searches: list[SavedSearch],
    source_event_id: uuid.UUID | None,
) -> None:
    searches.sort(key=lambda s: s.name.lower())
    if any(s.notify_in_app for s in searches):
        in_app = [s for s in searches if s.notify_in_app]
        target = (
            f"your saved search {_quote(in_app[0].name)}"
            if len(in_app) == 1
            else f"{len(in_app)} of your saved searches"
        )
        await create_notification(
            session,
            user_id=user_id,
            notification_type=NotificationType.SAVED_SEARCH_MATCH,
            title="New bounty matches your saved search",
            message=f"{_quote(bounty.title)} matches {target}.",
            link=f"/bounties/{bounty.slug}",
            payload={
                "bounty_id": str(bounty.id),
                "saved_search_id": str(in_app[0].id),
                "saved_search_ids": [str(s.id) for s in in_app],
            },
            source_event_id=source_event_id,
            send_email=False,  # the saved-search email below carries the unsubscribe links
        )
    emailed = [s for s in searches if s.notify_email]
    if emailed:
        add_event(
            session,
            event_type=EventType.SAVED_SEARCH_ALERT,
            aggregate_type="saved_search",
            aggregate_id=emailed[0].id,
            payload={
                "user_id": user_id,
                "bounty_id": bounty.id,
                "saved_search_ids": [s.id for s in emailed],
            },
        )


# --- Digests (worker) ---------------------------------------------------------------------------


async def _mark_delivered(
    session: AsyncSession,
    pairs: Sequence[tuple[uuid.UUID, uuid.UUID]],
    delivery: MatchDelivery,
    delivered_at: datetime | None,
) -> None:
    """One UPDATE for every (search, bounty) pair of a delivery outcome, across the whole digest run."""
    if not pairs:
        return
    await session.execute(
        update(SavedSearchMatch)
        .where(tuple_(SavedSearchMatch.saved_search_id, SavedSearchMatch.bounty_id).in_(list(pairs)))
        .values(delivery=delivery, delivered_at=delivered_at)
    )


async def run_digests(
    session: AsyncSession, frequency: AlertFrequency, now: datetime | None = None, *, force: bool = False
) -> DigestRunResult:
    """Sends every due digest of one frequency: one email (and one in-app notification) per user, listing each
    search's pending matches that still match. ``force`` ignores the schedule (operators and end-to-end tests).
    Commits once; the emails are staged as outbox events for the email worker."""
    if frequency not in DIGEST_FREQUENCIES:
        raise ValueError(f"{frequency} is not a digest frequency")
    now = now or utcnow()
    conditions: list[Any] = [
        SavedSearch.alert_frequency == frequency,
        SavedSearch.is_paused.is_(False),
        User.is_active.is_(True),
    ]
    if not force:
        conditions.append(and_(SavedSearch.next_digest_at.is_not(None), SavedSearch.next_digest_at <= now))
    due = (
        await session.scalars(
            select(SavedSearch)
            .join(User, User.id == SavedSearch.user_id)
            .where(*conditions)
            .order_by(SavedSearch.user_id, SavedSearch.created_at)
            .with_for_update(of=SavedSearch, skip_locked=True)
            .limit(DIGEST_BATCH)
        )
    ).all()
    if not due:
        return DigestRunResult(frequency=frequency.value, users=0, searches=0, matches=0)
    by_user: dict[uuid.UUID, list[SavedSearch]] = defaultdict(list)
    for search in due:
        by_user[search.user_id].append(search)

    # Everything the run needs, in three statements: the pending matches of every due search, which of them each
    # search still lists, and each recipient's notification preference.
    pending: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for search_id, bounty_id in (
        await session.execute(
            select(SavedSearchMatch.saved_search_id, SavedSearchMatch.bounty_id)
            .where(
                SavedSearchMatch.saved_search_id.in_([s.id for s in due]),
                SavedSearchMatch.delivery == MatchDelivery.PENDING,
            )
            .order_by(SavedSearchMatch.matched_at)
        )
    ).all():
        pending[search_id].append(bounty_id)
    still = await matching_pairs(session, [(s, pending.get(s.id, [])) for s in due], now)
    await _preload_preferences(session, list(by_user))

    digested: list[tuple[uuid.UUID, uuid.UUID]] = []
    skipped: list[tuple[uuid.UUID, uuid.UUID]] = []
    keeps: dict[uuid.UUID, list[uuid.UUID]] = {}
    for search in due:
        candidates = pending.get(search.id, [])
        kept = set(still.get(search.id, []))
        keeps[search.id] = [b for b in candidates if b in kept]
        digested += [(search.id, b) for b in candidates if b in kept]
        # Closed, hidden or edited out of the search since it matched: never sent, but still counted as new.
        skipped += [(search.id, b) for b in candidates if b not in kept]
        if keeps[search.id]:
            search.last_digest_at = now
        search.next_digest_at = next_digest_time(frequency, now)
    await _mark_delivered(session, digested, MatchDelivery.DIGESTED, now)
    await _mark_delivered(session, skipped, MatchDelivery.SKIPPED, None)

    users = matches = 0
    for user_id, searches in by_user.items():
        sections: list[dict[str, Any]] = [
            {"saved_search_id": s.id, "bounty_ids": keeps[s.id]} for s in searches if keeps[s.id]
        ]
        if not sections:
            continue
        users += 1
        matches += sum(len(s["bounty_ids"]) for s in sections)
        envelope = None
        by_id = {s.id: s for s in searches}
        if any(by_id[s["saved_search_id"]].notify_email for s in sections):
            envelope = add_event(
                session,
                event_type=EventType.SAVED_SEARCH_DIGEST,
                aggregate_type="saved_search",
                aggregate_id=sections[0]["saved_search_id"],
                payload={
                    "user_id": user_id,
                    "frequency": frequency.value,
                    "sections": [s for s in sections if by_id[s["saved_search_id"]].notify_email],
                },
            )
        in_app = [s for s in sections if by_id[s["saved_search_id"]].notify_in_app]
        if in_app:
            count = sum(len(s["bounty_ids"]) for s in in_app)
            first = by_id[in_app[0]["saved_search_id"]]
            target = (
                f"your saved search {_quote(first.name)}"
                if len(in_app) == 1
                else f"{len(in_app)} of your saved searches"
            )
            await create_notification(
                session,
                user_id=user_id,
                notification_type=NotificationType.SAVED_SEARCH_MATCH,
                title="New bounties match your saved searches",
                message=f"{count} new {'bounty matches' if count == 1 else 'bounties match'} {target}.",
                link=SAVED_SEARCHES_LINK,
                payload={
                    "saved_search_id": str(first.id),
                    "saved_search_ids": [str(s["saved_search_id"]) for s in in_app],
                    "digest": frequency.value,
                },
                source_event_id=envelope.event_id if envelope else uuid.uuid4(),
                send_email=False,
            )
    await session.commit()  # one commit: delivery marks, schedules, notifications and email events together
    logger.info(
        "saved_search_digests_run", frequency=frequency.value, users=users, searches=len(due), matches=matches
    )
    return DigestRunResult(frequency=frequency.value, users=users, searches=len(due), matches=matches)
