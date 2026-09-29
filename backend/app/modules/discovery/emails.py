"""Saved-search alert and digest emails (rendered with the shared, autoescaped Jinja2 environment).

Subjects are static strings, so no user text (search names, bounty titles) reaches a mail header. Every search in
an email carries its own signed unsubscribe link.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings, get_settings
from app.core.money import display_amount
from app.modules.bounties.models import Bounty
from app.modules.discovery.models import AlertFrequency, SavedSearch
from app.modules.discovery.tokens import make_unsubscribe_token
from app.modules.notifications import email as mail

ALERT_TEMPLATE = "saved_search_alert"
DIGEST_TEMPLATE = "saved_search_digest"

UNSUBSCRIBE_PATH = "/saved-searches/unsubscribe"
MANAGE_PATH = "/app/saved"


@dataclass(frozen=True)
class BountyLine:
    title: str
    url: str
    summary: str
    reward: str
    skills: str
    closes: str | None


@dataclass(frozen=True)
class SearchSection:
    name: str
    open_url: str
    unsubscribe_url: str
    bounties: tuple[BountyLine, ...]


def _date(value: datetime | None) -> str | None:
    return value.strftime("%d %b %Y") if value else None


def bounty_line(bounty: Bounty, settings: Settings | None = None) -> BountyLine:
    return BountyLine(
        title=bounty.title,
        url=mail.frontend_url(f"/bounties/{bounty.slug}", settings=settings),
        summary=bounty.short_description,
        reward=display_amount(bounty.reward_amount, bounty.reward_asset or "XLM"),
        skills=", ".join(bounty.skill_names[:6]),
        closes=_date(bounty.application_deadline or bounty.completion_deadline),
    )


def unsubscribe_url(search: SavedSearch, settings: Settings | None = None) -> str:
    token = make_unsubscribe_token(search.id, search.user_id, (settings or get_settings()).jwt_secret)
    return mail.frontend_url(UNSUBSCRIBE_PATH, {"token": token}, settings)


def open_url(search: SavedSearch, settings: Settings | None = None) -> str:
    return mail.frontend_url(MANAGE_PATH, {"tab": "searches", "open": str(search.id)}, settings)


def section(search: SavedSearch, bounties: list[Bounty], settings: Settings | None = None) -> SearchSection:
    return SearchSection(
        name=search.name,
        open_url=open_url(search, settings),
        unsubscribe_url=unsubscribe_url(search, settings),
        bounties=tuple(bounty_line(b, settings) for b in bounties),
    )


def render_alert(
    *, recipient_name: str, bounty: Bounty, searches: list[SavedSearch], settings: Settings | None = None
) -> mail.RenderedEmail:
    settings = settings or get_settings()
    line = bounty_line(bounty, settings)
    return mail.render(
        ALERT_TEMPLATE,
        f"New bounty for your saved search | {settings.app_name}",
        {
            "recipient_name": recipient_name,
            "bounty": line,
            "searches": [section(s, [], settings) for s in searches],
            "action_url": line.url,
            "action_label": "View bounty",
            "preferences_url": mail.frontend_url(mail.PREFERENCES_PATH, settings=settings),
            "manage_url": mail.frontend_url(MANAGE_PATH, {"tab": "searches"}, settings),
        },
        settings,
    )


def render_digest(
    *,
    recipient_name: str,
    frequency: AlertFrequency,
    sections: list[SearchSection],
    settings: Settings | None = None,
) -> mail.RenderedEmail:
    settings = settings or get_settings()
    period = "weekly" if frequency == AlertFrequency.WEEKLY else "daily"
    total = sum(len(s.bounties) for s in sections)
    return mail.render(
        DIGEST_TEMPLATE,
        f"Your {period} bounty digest | {settings.app_name}",
        {
            "recipient_name": recipient_name,
            "period": period,
            "total": total,
            "sections": sections,
            "action_url": mail.frontend_url(MANAGE_PATH, {"tab": "searches"}, settings),
            "action_label": "Open saved searches",
            "preferences_url": mail.frontend_url(mail.PREFERENCES_PATH, settings=settings),
        },
        settings,
    )
