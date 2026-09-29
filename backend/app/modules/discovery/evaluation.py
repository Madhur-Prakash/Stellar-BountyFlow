"""Offline evaluation of the recommendation ranking (pure functions, no I/O).

For every user with applications, the most recent ones (``holdout`` of them, at least one) are hidden. The user's
seeds are rebuilt from what is left (profile skills, earlier applications, bookmarks, completed work), every
bounty they did not post or apply to (before the split) is ranked, and the hidden applications are the relevant
items:

    precision@k = |top k  and  held out| / k        recall@k = |top k  and  held out| / |held out|
    hit rate@k  = share of users with at least one held-out bounty in their top k

The same split is scored for two baselines: *popularity* (applications from other users) and *skill overlap*
(required skills shared with the profile, the previous dashboard rule). ``app.scripts.evaluate_recommendations``
loads the data and prints the report; see docs/discovery.md.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.modules.discovery import ranking
from app.modules.discovery.graph import SkillGraph
from app.modules.discovery.skills import normalize_all


@dataclass(frozen=True)
class EvalBounty:
    id: uuid.UUID
    requester_id: uuid.UUID
    skills: ranking.SkillSet
    reward: Decimal
    asset: str
    deadline: datetime | None
    funding_status: str
    listed_at: datetime
    applications: int = 0

    def candidate(self) -> ranking.Candidate:
        return ranking.Candidate(
            bounty_id=self.id,
            skills=self.skills,
            reward=self.reward,
            asset=self.asset,
            deadline=self.deadline,
            funding_status=self.funding_status,
            listed_at=self.listed_at,
        )


@dataclass(frozen=True)
class EvalUser:
    id: uuid.UUID
    profile: Sequence[str]
    applications: Sequence[tuple[uuid.UUID, datetime]]  # (bounty, applied at)
    bookmarks: Sequence[uuid.UUID] = ()
    completed: Sequence[uuid.UUID] = ()


@dataclass(frozen=True)
class Metrics:
    precision: float
    recall: float
    hit_rate: float


@dataclass(frozen=True)
class EvalReport:
    k: int
    users: int
    held_out: int
    model: Metrics
    baselines: Mapping[str, Metrics] = field(default_factory=dict)


Ranker = Callable[[EvalUser, set[uuid.UUID], list[EvalBounty], datetime], list[uuid.UUID]]


def split(user: EvalUser, holdout: float) -> tuple[list[uuid.UUID], list[uuid.UUID], datetime] | None:
    """(train applications, held-out applications, when the first held-out one was made), or None when the user
    has nothing to learn from or nothing to hold out."""
    ordered = sorted(user.applications, key=lambda a: a[1])
    if not ordered:
        return None
    n_test = max(1, math.ceil(len(ordered) * holdout))
    train, test = ordered[:-n_test], ordered[-n_test:]
    if not train and not normalize_all(user.profile):
        return None
    return [b for b, _ in train], [b for b, _ in test], test[0][1]


def skill_graph_ranker(graph: SkillGraph) -> Ranker:
    def rank_for(
        user: EvalUser, train: set[uuid.UUID], pool: list[EvalBounty], now: datetime
    ) -> list[uuid.UUID]:
        known = {b.id: b for b in pool}
        held = {b for b, _ in user.applications} - train
        signals = ranking.UserSignals(
            profile=user.profile,
            # Nothing about a held-out bounty may leak in: not its completion, not a bookmark of it.
            completed=[known[b].skills for b in user.completed if b in train and b in known],
            applied=[known[b].skills for b in train if b in known],
            bookmarked=[known[b].skills for b in user.bookmarks if b in known and b not in held],
        )
        reach = ranking.reach(ranking.seed_weights(signals), graph)
        candidates = [b.candidate() for b in pool if b.requester_id != user.id and b.id not in train]
        return [r.bounty_id for r in ranking.rank(candidates, reach, now)]

    return rank_for


def popularity_ranker(
    user: EvalUser, train: set[uuid.UUID], pool: list[EvalBounty], now: datetime
) -> list[uuid.UUID]:
    mine = {b for b, _ in user.applications}
    candidates = [b for b in pool if b.requester_id != user.id and b.id not in train]
    # The user's own held-out application is not evidence of popularity: leave it out of the count.
    candidates.sort(key=lambda b: (-(b.applications - (1 if b.id in mine else 0)), -b.listed_at.timestamp()))
    return [b.id for b in candidates]


def skill_overlap_ranker(
    user: EvalUser, train: set[uuid.UUID], pool: list[EvalBounty], now: datetime
) -> list[uuid.UUID]:
    profile = set(normalize_all(user.profile))
    candidates = [b for b in pool if b.requester_id != user.id and b.id not in train]
    candidates.sort(
        key=lambda b: (-len(profile & set(normalize_all(b.skills.required))), -b.listed_at.timestamp())
    )
    return [b.id for b in candidates]


def _score(
    users: Iterable[EvalUser], pool: list[EvalBounty], ranker: Ranker, k: int, holdout: float
) -> tuple[Metrics, int, int]:
    precision = recall = hits = 0.0
    evaluated = held = 0
    for user in users:
        parts = split(user, holdout)
        if parts is None:
            continue
        train, test, now = parts
        relevant = set(test)
        top = ranker(user, set(train), pool, now)[:k]
        found = len(relevant.intersection(top))
        precision += found / k
        recall += found / len(relevant)
        hits += 1.0 if found else 0.0
        evaluated += 1
        held += len(relevant)
    if not evaluated:
        return Metrics(0.0, 0.0, 0.0), 0, 0
    return Metrics(precision / evaluated, recall / evaluated, hits / evaluated), evaluated, held


def evaluate(
    users: Sequence[EvalUser],
    pool: Sequence[EvalBounty],
    graph: SkillGraph,
    *,
    k: int = 5,
    holdout: float = 0.2,
) -> EvalReport:
    bounties = list(pool)
    model, evaluated, held = _score(users, bounties, skill_graph_ranker(graph), k, holdout)
    baselines = {
        "popularity": _score(users, bounties, popularity_ranker, k, holdout)[0],
        "skill overlap": _score(users, bounties, skill_overlap_ranker, k, holdout)[0],
    }
    return EvalReport(k=k, users=evaluated, held_out=held, model=model, baselines=baselines)


def format_report(reports: Sequence[EvalReport]) -> str:
    """A Markdown table: one row per k and ranker."""
    lines = [
        "| k | Ranker | Precision@k | Recall@k | Hit rate@k |",
        "|---|---|---|---|---|",
    ]
    for report in reports:
        rows = [("skill graph", report.model), *report.baselines.items()]
        for name, m in rows:
            lines.append(f"| {report.k} | {name} | {m.precision:.3f} | {m.recall:.3f} | {m.hit_rate:.3f} |")
    if reports:
        lines.append("")
        lines.append(f"Users evaluated: {reports[0].users}. Held-out applications: {reports[0].held_out}.")
    return "\n".join(lines)
