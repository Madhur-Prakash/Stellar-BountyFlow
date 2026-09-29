"""Extension points for modules that hold personal data of their own.

A module adds its records to data exports, takes part in account anonymisation, or blocks a deletion while it
still has unsettled work, by registering a function here (at import time, from its own module):

    from app.modules.compliance import registry

    @registry.export_section("saved_searches")
    async def _saved_searches(session, user): ...

    @registry.anonymiser
    async def _forget_saved_searches(session, user): ...

    @registry.deletion_blocker
    async def _open_threads(session, user_id): return [Blocker(...)]

The core tables (profile, bounties, applications, submissions, payments, wallets, notifications, audit entries)
are handled in ``exports.py`` and ``deletion.py`` directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.models import User


@dataclass(frozen=True)
class Blocker:
    """Something that must be settled before an account can be deleted."""

    kind: str
    message: str
    count: int = 1
    links: list[str] = field(default_factory=list)


ExportSection = Callable[[AsyncSession, User], Awaitable[Any]]
Anonymiser = Callable[[AsyncSession, User], Awaitable[None]]
DeletionBlocker = Callable[[AsyncSession, uuid.UUID], Awaitable[list[Blocker]]]

EXPORT_SECTIONS: dict[str, ExportSection] = {}
ANONYMISERS: list[Anonymiser] = []
DELETION_BLOCKERS: list[DeletionBlocker] = []


def export_section(name: str) -> Callable[[ExportSection], ExportSection]:
    def register(fn: ExportSection) -> ExportSection:
        EXPORT_SECTIONS[name] = fn
        return fn

    return register


def anonymiser(fn: Anonymiser) -> Anonymiser:
    if fn not in ANONYMISERS:
        ANONYMISERS.append(fn)
    return fn


def deletion_blocker(fn: DeletionBlocker) -> DeletionBlocker:
    if fn not in DELETION_BLOCKERS:
        DELETION_BLOCKERS.append(fn)
    return fn


def load_sections() -> None:
    """Import the module that registers the feature modules' sections (idempotent).

    Exports and deletions call this first, so a registration can never be missed because of import order."""
    import app.modules.compliance.sections  # noqa: F401
