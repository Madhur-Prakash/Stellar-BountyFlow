"""Sanctions screening of Stellar wallet addresses.

Screening runs when a wallet is verified and before any on-chain action is prepared (funding, assignments,
payouts, refunds, disputes): the signing wallet and, where the action pays or binds another account, that account
too. A match blocks the action with a neutral message; staff see the matching entry and its reason in the admin
console. Every decision, cleared or blocked, is written to the audit log in its own short transaction, so a
blocked attempt is recorded even though the action itself is rolled back.

The provider is pluggable (``ScreeningProvider``). The default ``DenylistProvider`` matches against
``screening_entries``: entries admins add by hand, plus the entries the worker's ``sanctions-list-refresh`` job
syncs from ``SANCTIONS_LIST_PATH`` / ``SANCTIONS_LIST_URL`` (for example the OFAC SDN list's XLM addresses).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import keys
from app.cache.redis import get_redis
from app.core.config import get_settings
from app.core.exceptions import Conflict, Forbidden, NotFound, ValidationFailed
from app.core.logging import get_logger
from app.core.security import utcnow
from app.db.session import get_sessionmaker
from app.modules.admin import audit
from app.modules.compliance import sanctions_list
from app.modules.compliance.models import ScreeningEntry, ScreeningSource

logger = get_logger(__name__)

# Shown to the person whose wallet matched. It never says why: the reason is for staff only.
BLOCKED_MESSAGE = "This wallet can’t be used on BountyFlow. Contact support if you think this is a mistake."
BLOCKED_CODE = "screening_blocked"

WALLET_VERIFICATION = "wallet_verification"
PASSKEY_DEPLOYMENT = "passkey_deployment"
LIST_STATUS_KEY = f"{keys.PREFIX}:ops:sanctions-list"


def chain_context(action: str) -> str:
    return f"chain:{action}"


def chain_addresses(
    wallet: str, destination: str | None, metadata: Mapping[str, Any] | None = None
) -> list[str | None]:
    """Every address a prepared chain action touches: the signing wallet, the account it pays or binds, and —
    for a batch payout, which settles atomically — the payee of every leg. One sanctioned leg blocks the batch,
    because the contract pays all of them or none."""
    legs = (metadata or {}).get("legs")
    payees = (
        [leg.get("contributor") for leg in legs if isinstance(leg, Mapping)] if isinstance(legs, list) else []
    )
    return [wallet, destination, *payees]


@dataclass(frozen=True)
class ScreeningMatch:
    entry_id: uuid.UUID
    source: str
    list_name: str
    reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "source": self.source,
            "list_name": self.list_name,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ScreeningResult:
    address: str
    provider: str
    matches: tuple[ScreeningMatch, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.matches)


class ScreeningProvider(Protocol):
    name: str

    async def screen(self, session: AsyncSession, addresses: Sequence[str]) -> dict[str, ScreeningResult]: ...


class DenylistProvider:
    """Matches addresses against the active entries in ``screening_entries``."""

    name = "denylist"

    async def screen(self, session: AsyncSession, addresses: Sequence[str]) -> dict[str, ScreeningResult]:
        rows = (
            await session.scalars(
                select(ScreeningEntry).where(
                    ScreeningEntry.address.in_(list(addresses)), ScreeningEntry.removed_at.is_(None)
                )
            )
        ).all()
        by_address: dict[str, list[ScreeningMatch]] = {a: [] for a in addresses}
        for row in rows:
            by_address.setdefault(row.address, []).append(
                ScreeningMatch(row.id, row.source.value, row.list_name, row.reason)
            )
        return {a: ScreeningResult(a, self.name, tuple(m)) for a, m in by_address.items()}


_provider: ScreeningProvider | None = None


def get_provider() -> ScreeningProvider:
    return _provider or DenylistProvider()


def set_provider(provider: ScreeningProvider | None) -> None:
    """Install another provider (a commercial screening API, or a test double)."""
    global _provider
    _provider = provider


def _screenable(addresses: Sequence[str | None]) -> list[str]:
    """Distinct Stellar addresses to screen, in the order given.

    Both account ids (``G…``) and contract addresses (``C…``) count: a passkey smart wallet is a contract
    account that holds and receives funds exactly like an account id does. Empty values are skipped."""
    seen: list[str] = []
    for address in addresses:
        if address and address[0] in ("G", "C") and address not in seen:
            seen.append(address)
    return seen


async def _screen_and_record(
    targets: Sequence[str],
    *,
    user_id: uuid.UUID | None,
    context: str,
    bounty_id: uuid.UUID | None,
) -> list[ScreeningResult]:
    """Screen ``targets`` and write one audit entry per address, in a session of its own.

    Two reasons for the separate session, both deliberate:

    * the caller usually holds row locks (a bounty being funded, an escrow being paid out) and a provider may
      call out over the network, so screening must never run inside that transaction;
    * the decision is a compliance record in its own right. It commits even when the action it gated is rolled
      back, so a blocked attempt is always on file.

    The entry keeps the bounty id in its metadata rather than the ``bounty_id`` foreign key, because a foreign
    key check from this second transaction would wait on the caller's lock on that very row."""
    provider = get_provider()
    async with get_sessionmaker()() as session:
        results = list((await provider.screen(session, targets)).values())
        for result in results:
            audit.record(
                session,
                actor_id=user_id,
                action="screening.blocked" if result.blocked else "screening.cleared",
                entity_type="screening",
                entity_id=user_id or uuid.UUID(int=0),
                metadata={
                    "address": result.address,
                    "context": context,
                    "provider": result.provider,
                    "matches": [m.as_dict() for m in result.matches],
                    **({"bounty_id": str(bounty_id)} if bounty_id else {}),
                },
                is_public=False,
            )
        await session.commit()
    return results


async def enforce(
    *,
    user_id: uuid.UUID | None,
    addresses: Sequence[str | None],
    context: str,
    bounty_id: uuid.UUID | None = None,
) -> None:
    """Screens ``addresses`` and raises ``Forbidden`` (``screening_blocked``) when any of them matches.

    Call this *before* the transaction that acts on the result, or from one that holds no locks: it runs in a
    session of its own (see ``_screen_and_record``)."""
    if not get_settings().sanctions_screening_enabled:
        return
    targets = _screenable(addresses)
    if not targets:
        return
    results = await _screen_and_record(targets, user_id=user_id, context=context, bounty_id=bounty_id)
    blocked = [r for r in results if r.blocked]
    if blocked:
        logger.warning(
            "screening_blocked",
            context=context,
            user_id=str(user_id) if user_id else None,
            matches=sum(len(r.matches) for r in blocked),
        )
        raise Forbidden(BLOCKED_MESSAGE, code=BLOCKED_CODE)


# --- Admin: manual entries ------------------------------------------------------------------


async def add_manual_entry(
    session: AsyncSession, actor_id: uuid.UUID, address: str, reason: str
) -> ScreeningEntry:
    address = address.strip()
    if not sanctions_list.is_screenable_address(address):
        raise ValidationFailed(
            "Enter a valid Stellar address (G… account or C… contract).",
            details=[{"field": "address", "message": "Not a Stellar address"}],
        )
    existing = await session.scalar(
        select(ScreeningEntry).where(
            ScreeningEntry.address == address,
            ScreeningEntry.source == ScreeningSource.MANUAL,
            ScreeningEntry.removed_at.is_(None),
        )
    )
    if existing is not None:
        raise Conflict("This address is already on the manual list.")
    entry = ScreeningEntry(
        address=address,
        source=ScreeningSource.MANUAL,
        list_name="Manual",
        reason=reason.strip(),
        added_by_id=actor_id,
    )
    session.add(entry)
    await session.flush()
    audit.record(
        session,
        actor_id=actor_id,
        action="screening.entry_added",
        entity_type="screening_entry",
        entity_id=entry.id,
        metadata={"address": address, "source": entry.source.value},
        is_public=False,
    )
    await session.commit()
    await session.refresh(entry)
    return entry


async def remove_manual_entry(
    session: AsyncSession, actor_id: uuid.UUID, entry_id: uuid.UUID, note: str
) -> ScreeningEntry:
    entry = await session.get(ScreeningEntry, entry_id, with_for_update=True)
    if entry is None or entry.removed_at is not None:
        raise NotFound("Screening entry not found.")
    if entry.source != ScreeningSource.MANUAL:
        raise Conflict("Entries from the sanctions list change only when the list does.")
    entry.removed_at = utcnow()
    entry.removed_by_id = actor_id
    entry.removal_note = note.strip()
    audit.record(
        session,
        actor_id=actor_id,
        action="screening.entry_removed",
        entity_type="screening_entry",
        entity_id=entry.id,
        metadata={"address": entry.address, "note": entry.removal_note},
        is_public=False,
    )
    await session.commit()
    await session.refresh(entry)
    return entry


# --- The configured list ----------------------------------------------------------------------


async def sync_configured_list(session: AsyncSession) -> dict[str, Any]:
    """Brings the LIST entries in line with the configured sanctions list. On any error, or when a list that had
    entries suddenly comes back empty, the current entries are kept (fail static) and the error is reported."""
    settings = get_settings()
    now = utcnow()
    status: dict[str, Any] = {
        "configured": bool(settings.sanctions_list_path or settings.sanctions_list_url),
        "name": settings.sanctions_list_name,
        "checked_at": now.isoformat(),
    }
    active = (
        await session.scalars(
            select(ScreeningEntry).where(
                ScreeningEntry.source == ScreeningSource.LIST, ScreeningEntry.removed_at.is_(None)
            )
        )
    ).all()
    try:
        loaded = await sanctions_list.load(settings.sanctions_list_path, settings.sanctions_list_url)
    except ValueError as exc:
        logger.error("sanctions_list_load_failed", error=str(exc))
        status.update(error=str(exc), entries=len(active))
        await _save_status(status, keep_loaded_at=True)
        return status
    if loaded is None:
        wanted: frozenset[str] = frozenset()
        source = None
    else:
        if not loaded.addresses and active and loaded.format == "text":
            message = "the list came back empty, so the previous entries were kept"
            logger.error("sanctions_list_suspiciously_empty", source=loaded.source)
            status.update(error=message, entries=len(active), source=loaded.source)
            await _save_status(status, keep_loaded_at=True)
            return status
        wanted, source = loaded.addresses, loaded.source
    current = {e.address: e for e in active}
    added = 0
    for address in sorted(wanted - current.keys()):
        session.add(
            ScreeningEntry(
                address=address,
                source=ScreeningSource.LIST,
                list_name=settings.sanctions_list_name[:120],
                reason=f"Listed in {settings.sanctions_list_name}",
            )
        )
        added += 1
    removed = 0
    for address, entry in current.items():
        if address not in wanted:
            entry.removed_at = now
            entry.removal_note = "No longer on the configured sanctions list"
            removed += 1
    await session.commit()
    status.update(
        source=source,
        format=loaded.format if loaded else None,
        entries=len(wanted),
        added=added,
        removed=removed,
        loaded_at=now.isoformat() if loaded else None,
        error=None,
    )
    if added or removed:
        logger.info("sanctions_list_synced", added=added, removed=removed, entries=len(wanted))
    await _save_status(status, keep_loaded_at=loaded is None)
    return status


async def _save_status(status: dict[str, Any], *, keep_loaded_at: bool) -> None:
    try:
        redis = get_redis()
        if keep_loaded_at and not status.get("loaded_at"):
            previous = await redis.get(LIST_STATUS_KEY)
            if previous:
                status["loaded_at"] = json.loads(previous).get("loaded_at")
        await redis.set(LIST_STATUS_KEY, json.dumps(status, default=str))
    except Exception as exc:
        logger.warning("sanctions_list_status_unavailable", error=str(exc))


async def list_status() -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(LIST_STATUS_KEY)
    except Exception:
        return None
    return json.loads(raw) if raw else None


async def entry_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(ScreeningEntry.source, func.count(ScreeningEntry.id))
            .where(ScreeningEntry.removed_at.is_(None))
            .group_by(ScreeningEntry.source)
        )
    ).all()
    counts = {s.value: 0 for s in ScreeningSource}
    for source, count in rows:
        counts[source.value] = int(count)
    return counts
