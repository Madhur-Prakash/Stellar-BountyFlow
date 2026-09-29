"""Offline evaluation of skill-graph recommendations against held-out applications.

    uv run python -m app.scripts.evaluate_recommendations              # k = 1, 3, 5, 10; 20% held out
    uv run python -m app.scripts.evaluate_recommendations --k 5 --holdout 0.3

Reads the database named by DATABASE_URL (read-only), builds the skill graph from its bounties and profiles,
hides each user's most recent applications and reports precision@k, recall@k and hit rate@k for the ranking and
two baselines. The method is described in docs/discovery.md.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from app.cache.redis import close_redis
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.runtime import run_async
from app.db.session import dispose_engine, get_sessionmaker
from app.modules.applications.models import AssignmentStatus, BountyApplication, BountyAssignment
from app.modules.bounties import repository as bounty_repo
from app.modules.bounties import service as bounty_service
from app.modules.bounties.models import Bounty, BountyBookmark
from app.modules.discovery import ranking
from app.modules.discovery.evaluation import EvalBounty, EvalReport, EvalUser, evaluate, format_report
from app.modules.discovery.graph import SkillGraph
from app.modules.discovery.graph_store import compute_graph
from app.modules.users.models import User


async def load() -> tuple[list[EvalUser], list[EvalBounty], SkillGraph]:
    async with get_sessionmaker()() as session:
        graph = await compute_graph(session)
        bounties = (await session.scalars(select(Bounty).where(bounty_repo.public_filter()))).unique().all()
        escrows = await bounty_repo.escrows(session, [b.id for b in bounties])
        pool = [
            EvalBounty(
                id=b.id,
                requester_id=b.requester_id,
                skills=ranking.SkillSet(required=b.skill_names, tags=b.tag_names),
                reward=b.reward_amount,
                asset=b.reward_asset_identifier or "native",
                deadline=b.application_deadline or b.completion_deadline,
                funding_status=bounty_service.funding_status(b, escrows.get(b.id)).value,
                listed_at=b.published_at or b.created_at,
                applications=b.applications_count,
            )
            for b in bounties
        ]
        applications: dict[uuid.UUID, list[tuple[uuid.UUID, datetime]]] = defaultdict(list)
        for contributor, bounty_id, created in (
            await session.execute(
                select(
                    BountyApplication.contributor_id,
                    BountyApplication.bounty_id,
                    BountyApplication.created_at,
                )
            )
        ).all():
            applications[contributor].append((bounty_id, created))
        bookmarks: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for user_id, bounty_id in (
            await session.execute(select(BountyBookmark.user_id, BountyBookmark.bounty_id))
        ).all():
            bookmarks[user_id].append(bounty_id)
        completed: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for user_id, bounty_id in (
            await session.execute(
                select(BountyAssignment.contributor_id, BountyAssignment.bounty_id).where(
                    BountyAssignment.status == AssignmentStatus.COMPLETED
                )
            )
        ).all():
            completed[user_id].append(bounty_id)
        users = (
            await session.scalars(
                select(User).where(User.id.in_(list(applications)), User.is_active.is_(True))
            )
        ).all()
        evaluated = [
            EvalUser(
                id=u.id,
                profile=u.skill_names,
                applications=applications[u.id],
                bookmarks=bookmarks.get(u.id, []),
                completed=completed.get(u.id, []),
            )
            for u in users
        ]
    return evaluated, pool, graph


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate skill-graph recommendations offline.")
    parser.add_argument("--k", type=int, action="append", help="cut-off (repeatable; default 1, 3, 5, 10)")
    parser.add_argument(
        "--holdout", type=float, default=0.2, help="share of each user's applications held out"
    )
    args = parser.parse_args(argv)
    if not 0 < args.holdout < 1:
        parser.error("--holdout must be between 0 and 1")
    settings = get_settings()
    configure_logging("WARNING", settings.log_json, service="evaluate")

    async def _run() -> list[EvalReport]:
        try:
            users, pool, graph = await load()
            return [
                evaluate(users, pool, graph, k=k, holdout=args.holdout) for k in (args.k or [1, 3, 5, 10])
            ]
        finally:
            await close_redis()
            await dispose_engine()

    reports = run_async(_run())
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
    stream.write(format_report(reports) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
