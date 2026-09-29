"""Recommendation ranking (pure functions, no I/O).

1. **Seeds.** What the user is into, as weighted skills: their profile skills, then the skills of bounties they
   completed, applied to and bookmarked, each source counting less than the one before. A bounty's tags count half
   as much as its required skills.
2. **Proximity.** Each skill a bounty asks for gets an affinity: the seed weight if the user has it, otherwise the
   best ``seed weight x edge weight x RELATED_DISCOUNT`` over the user's seeds (one hop in the skill graph). The
   bounty's proximity is the weighted mean affinity of its skills, in [0, 1].
3. **Blend.** Only bounties with some proximity are recommended. Their score blends proximity with the reward,
   the time left to apply, and whether the escrow is verifiably funded.

**Multiple assets.** Rewards are never compared across assets: 100 USDC and 100 XLM are different amounts of
different things, and BountyFlow has no price feed to convert them. A bounty's reward score is its amount against
the largest reward *of the same asset* among the candidates (keyed by asset identifier, so two "USDC" from
different issuers stay apart), which makes the reward part a rank within its own asset. Amounts are never summed
across assets.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.modules.discovery.graph import SkillGraph
from app.modules.discovery.skills import normalize_all

# Seed weight by source.
PROFILE_WEIGHT = 1.0
COMPLETED_WEIGHT = 0.8
APPLIED_WEIGHT = 0.6
BOOKMARKED_WEIGHT = 0.4
TAG_FACTOR = 0.5  # a tag says less about the work than a required skill

RELATED_DISCOUNT = 0.7  # a neighbouring skill is never worth as much as the skill itself

# Blend of the final score.
W_PROXIMITY = 0.6
W_REWARD = 0.15
W_DEADLINE = 0.15
W_FUNDING = 0.10

DEADLINE_HORIZON_DAYS = 14.0  # more time than this to apply scores the same
NO_DEADLINE_SCORE = 0.6

FUNDING_SCORES: Mapping[str, float] = {
    "FUNDED": 1.0,
    "PARTIALLY_FUNDED": 0.6,
    "PENDING": 0.5,
    "UNFUNDED": 0.3,
}


@dataclass(frozen=True)
class SkillSet:
    """A bounty's skills: required skills and tags, as written."""

    required: Sequence[str] = ()
    tags: Sequence[str] = ()

    def weighted(self) -> dict[str, float]:
        """Normalised skill -> weight (a skill that is both required and a tag keeps the higher weight)."""
        out: dict[str, float] = {}
        for name in normalize_all(self.tags):
            out[name] = TAG_FACTOR
        for name in normalize_all(self.required):
            out[name] = 1.0
        return out


@dataclass(frozen=True)
class UserSignals:
    profile: Sequence[str] = ()
    completed: Sequence[SkillSet] = ()
    applied: Sequence[SkillSet] = ()
    bookmarked: Sequence[SkillSet] = ()


def seed_weights(signals: UserSignals) -> dict[str, float]:
    """Normalised skill -> how strongly it describes the user, in (0, 1]. The strongest source wins."""
    seeds: dict[str, float] = {}

    def add(name: str, weight: float) -> None:
        if weight > seeds.get(name, 0.0):
            seeds[name] = weight

    for name in normalize_all(signals.profile):
        add(name, PROFILE_WEIGHT)
    for source, weight in (
        (signals.completed, COMPLETED_WEIGHT),
        (signals.applied, APPLIED_WEIGHT),
        (signals.bookmarked, BOOKMARKED_WEIGHT),
    ):
        for skill_set in source:
            for name, factor in skill_set.weighted().items():
                add(name, weight * factor)
    return seeds


@dataclass(frozen=True)
class RelatedMatch:
    skill: str  # the bounty's skill
    via: str  # the user's skill it is connected to


@dataclass(frozen=True)
class Proximity:
    score: float
    matched: tuple[str, ...]  # bounty skills the user has directly (strongest first)
    related: tuple[RelatedMatch, ...]  # bounty skills reached through the graph


NO_PROXIMITY = Proximity(0.0, (), ())


@dataclass(frozen=True)
class Reach:
    """Everything a user's seeds reach in one hop: skill -> (affinity, the seed it comes from)."""

    seeds: Mapping[str, float]
    via: Mapping[str, tuple[float, str]]

    @property
    def skills(self) -> set[str]:
        return set(self.seeds) | set(self.via)


def reach(seeds: Mapping[str, float], graph: SkillGraph) -> Reach:
    via: dict[str, tuple[float, str]] = {}
    for seed, weight in sorted(seeds.items()):
        for edge in graph.neighbors.get(seed, ()):
            affinity = weight * edge.weight * RELATED_DISCOUNT
            if affinity > via.get(edge.related, (0.0, ""))[0]:
                via[edge.related] = (affinity, seed)
    return Reach(seeds=dict(seeds), via=via)


def proximity(skills: SkillSet, user: Reach) -> Proximity:
    weighted = skills.weighted()
    if not weighted or not user.seeds:
        return NO_PROXIMITY
    total = sum(weighted.values())
    gained = 0.0
    direct: list[tuple[float, str]] = []
    related: list[tuple[float, RelatedMatch]] = []
    for skill, importance in weighted.items():
        own = user.seeds.get(skill, 0.0)
        via_score, via_skill = user.via.get(skill, (0.0, ""))
        affinity = max(own, via_score)
        if affinity <= 0:
            continue
        gained += importance * affinity
        if own >= via_score:
            direct.append((importance * own, skill))
        else:
            related.append((importance * via_score, RelatedMatch(skill, via_skill)))
    direct.sort(key=lambda x: (-x[0], x[1]))
    related.sort(key=lambda x: (-x[0], x[1].skill))
    return Proximity(
        score=gained / total if total else 0.0,
        matched=tuple(s for _, s in direct),
        related=tuple(r for _, r in related),
    )


def reward_score(amount: Decimal, best: Decimal) -> float:
    if amount <= 0 or best <= 0:
        return 0.0
    return min(1.0, math.log1p(float(amount)) / math.log1p(float(best)))


def deadline_score(deadline: datetime | None, now: datetime) -> float:
    if deadline is None:
        return NO_DEADLINE_SCORE
    days = (deadline - now).total_seconds() / 86400
    if days <= 0:
        return 0.0
    return 0.1 + 0.9 * min(1.0, days / DEADLINE_HORIZON_DAYS)


def funding_score(funding_status: str) -> float:
    return FUNDING_SCORES.get(funding_status, FUNDING_SCORES["UNFUNDED"])


@dataclass(frozen=True)
class Candidate:
    bounty_id: uuid.UUID
    skills: SkillSet
    reward: Decimal
    asset: (
        str  # the reward asset's identifier ("native" or "CODE:ISSUER"), the key rewards are compared within
    )
    deadline: datetime | None  # the application deadline (else the completion deadline)
    funding_status: str
    listed_at: datetime


@dataclass(frozen=True)
class Ranked:
    bounty_id: uuid.UUID
    score: float
    proximity: Proximity
    parts: Mapping[str, float] = field(default_factory=dict)


def rank(
    candidates: Iterable[Candidate],
    user: Reach,
    now: datetime,
    *,
    min_proximity: float = 1e-9,
) -> list[Ranked]:
    """Scores and orders candidates; bounties with no skill proximity are left out. Ties go to the newest."""
    scored: list[tuple[Candidate, Proximity]] = []
    best_reward: dict[str, Decimal] = {}  # per asset identifier: rewards never compare across assets
    for c in candidates:
        p = proximity(c.skills, user)
        if p.score < min_proximity:
            continue
        scored.append((c, p))
        if c.reward > best_reward.get(c.asset, Decimal(0)):
            best_reward[c.asset] = c.reward
    ranked: list[tuple[Ranked, datetime]] = []
    for c, p in scored:
        parts = {
            "proximity": p.score,
            "reward": reward_score(c.reward, best_reward.get(c.asset, c.reward)),
            "deadline": deadline_score(c.deadline, now),
            "funding": funding_score(c.funding_status),
        }
        score = (
            W_PROXIMITY * parts["proximity"]
            + W_REWARD * parts["reward"]
            + W_DEADLINE * parts["deadline"]
            + W_FUNDING * parts["funding"]
        )
        ranked.append((Ranked(c.bounty_id, round(score, 6), p, parts), c.listed_at))
    ranked.sort(key=lambda x: (-x[0].score, -x[1].timestamp(), str(x[0].bounty_id)))
    return [r for r, _ in ranked]
