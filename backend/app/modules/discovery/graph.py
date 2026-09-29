"""The skill graph (pure functions, no I/O).

Nodes are normalised skills. A *document* is one set of skills that belong together: a bounty's required skills
plus its tags, or one user's profile skills. Two skills that appear in the same document co-occur, and an edge's
weight says how much more often they co-occur than chance would predict:

    npmi(a, b) = ln(p(a, b) / (p(a) p(b))) / -ln p(a, b)          (normalised PMI, in [-1, 1])
    weight(a, b) = max(0, npmi(a, b)) * c(a, b) / (c(a, b) + SHRINK)

The second factor damps pairs seen together only once or twice, which raw PMI rates as highly as pairs seen a
hundred times. Only positive associations are kept, and each node keeps its ``top_k`` strongest neighbours.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from typing import Any

from app.modules.discovery.skills import normalize_all

SHRINK = 1.0
TOP_K = 20
MIN_WEIGHT = 0.01


@dataclass(frozen=True)
class Edge:
    related: str
    weight: float
    co_count: int


@dataclass(frozen=True)
class SkillGraph:
    documents: int
    doc_counts: Mapping[str, int]
    neighbors: Mapping[str, tuple[Edge, ...]]  # strongest first
    # Raw names as written on bounties (required skills), most used first.
    bounty_forms: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    computed_at: datetime | None = None

    def weight(self, a: str, b: str) -> float:
        for edge in self.neighbors.get(a, ()):
            if edge.related == b:
                return edge.weight
        return 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "documents": self.documents,
            "doc_counts": dict(self.doc_counts),
            "neighbors": {
                s: [[e.related, round(e.weight, 6), e.co_count] for e in edges]
                for s, edges in self.neighbors.items()
            },
            "bounty_forms": {s: list(forms) for s, forms in self.bounty_forms.items()},
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> SkillGraph:
        computed = data.get("computed_at")
        return cls(
            documents=int(data.get("documents", 0)),
            doc_counts={str(k): int(v) for k, v in (data.get("doc_counts") or {}).items()},
            neighbors={
                str(s): tuple(Edge(str(r), float(w), int(c)) for r, w, c in edges)
                for s, edges in (data.get("neighbors") or {}).items()
            },
            bounty_forms={str(s): tuple(forms) for s, forms in (data.get("bounty_forms") or {}).items()},
            computed_at=datetime.fromisoformat(computed) if computed else None,
        )


EMPTY_GRAPH = SkillGraph(documents=0, doc_counts={}, neighbors={})


def npmi(co: int, count_a: int, count_b: int, documents: int) -> float:
    """Normalised pointwise mutual information of two skills over ``documents`` documents."""
    if co <= 0 or documents <= 0:
        return -1.0
    p_ab = co / documents
    if p_ab >= 1.0:
        return 1.0  # every document holds both: perfectly associated
    pmi = math.log(p_ab / ((count_a / documents) * (count_b / documents)))
    return max(-1.0, min(1.0, pmi / -math.log(p_ab)))


def edge_weight(co: int, count_a: int, count_b: int, documents: int, shrink: float = SHRINK) -> float:
    return max(0.0, npmi(co, count_a, count_b, documents)) * co / (co + shrink)


def build_graph(
    documents: Iterable[Iterable[str]],
    *,
    bounty_skill_names: Iterable[str] = (),
    top_k: int = TOP_K,
    shrink: float = SHRINK,
    computed_at: datetime | None = None,
) -> SkillGraph:
    """Builds the graph from raw skill lists (normalised here). ``bounty_skill_names`` are the raw required-skill
    names of bounties, recorded per node so a skill can link to the marketplace's exact-name filter."""
    counts: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    total = 0
    for raw in documents:
        doc = sorted(set(normalize_all(raw)))
        if not doc:
            continue
        total += 1
        counts.update(doc)
        pairs.update(combinations(doc, 2))

    adjacency: dict[str, list[Edge]] = {}
    for (a, b), co in pairs.items():
        w = edge_weight(co, counts[a], counts[b], total, shrink)
        if w < MIN_WEIGHT:
            continue
        adjacency.setdefault(a, []).append(Edge(b, w, co))
        adjacency.setdefault(b, []).append(Edge(a, w, co))
    neighbors = {
        s: tuple(sorted(edges, key=lambda e: (-e.weight, -e.co_count, e.related))[:top_k])
        for s, edges in adjacency.items()
    }

    forms: dict[str, Counter[str]] = {}
    for raw_name in bounty_skill_names:
        name = raw_name.strip().lower()
        canonical = normalize_all([name])
        if canonical:
            forms.setdefault(canonical[0], Counter())[name] += 1
    bounty_forms = {
        s: tuple(n for n, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))) for s, c in forms.items()
    }
    return SkillGraph(
        documents=total,
        doc_counts=dict(counts),
        neighbors=neighbors,
        bounty_forms=bounty_forms,
        computed_at=computed_at,
    )


@dataclass(frozen=True)
class Related:
    skill: str
    weight: float
    via: tuple[str, ...]  # the input skills it is connected to, strongest first


def related_skills(graph: SkillGraph, skills: Iterable[str], limit: int = 8) -> list[Related]:
    """Skills most associated with ``skills`` (normalised here), excluding the inputs themselves. A candidate's
    score is its strongest edge to any input; the edges it has to the others break ties."""
    inputs = normalize_all(skills)
    given = set(inputs)
    best: dict[str, list[tuple[float, str]]] = {}
    for source in inputs:
        for edge in graph.neighbors.get(source, ()):
            if edge.related in given:
                continue
            best.setdefault(edge.related, []).append((edge.weight, source))
    ranked = sorted(
        best.items(),
        key=lambda kv: (-max(w for w, _ in kv[1]), -sum(w for w, _ in kv[1]), kv[0]),
    )
    result: list[Related] = []
    for skill, links in ranked[:limit]:
        links.sort(key=lambda x: (-x[0], x[1]))
        result.append(Related(skill, max(w for w, _ in links), tuple(s for _, s in links)))
    return result
