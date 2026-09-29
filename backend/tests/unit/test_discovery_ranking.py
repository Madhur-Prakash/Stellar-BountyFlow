"""Skill normalisation, the skill graph, recommendation ranking and the offline evaluation (pure functions)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.modules.discovery import ranking
from app.modules.discovery.evaluation import EvalBounty, EvalUser, evaluate, format_report, split
from app.modules.discovery.graph import build_graph, edge_weight, npmi, related_skills
from app.modules.discovery.skills import match_keys, normalize_all, normalize_skill

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _graph(*docs: list[str]):  # type: ignore[no-untyped-def]
    return build_graph(docs)


# --- Normalisation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("JS", "javascript"),
        ("  Java Script ", "javascript"),
        ("ts", "typescript"),
        ("golang", "go"),
        ("Postgres", "postgresql"),
        ("smart-contracts", "smart contracts"),
        ("smart_contract", "smart contracts"),
        ("#rust", "rust"),
        ("wasm", "webassembly"),
        ("docs", "documentation"),
        ("Unknown-Skill_Name", "unknown skill name"),
        ("   ", ""),
    ],
)
def test_normalize_skill_maps_aliases_and_separators(raw: str, expected: str) -> None:
    assert normalize_skill(raw) == expected


def test_normalize_all_deduplicates_in_order() -> None:
    assert normalize_all(["JS", "javascript", "Rust", "rustlang", ""]) == ["javascript", "rust"]


def test_match_keys_cover_every_spelling() -> None:
    keys = match_keys(["javascript"])
    assert {"javascript", "js", "java script", "es6"} <= set(keys)


# --- Graph -------------------------------------------------------------------------------


def test_npmi_is_one_for_perfect_association_and_negative_for_avoidance() -> None:
    assert npmi(co=5, count_a=5, count_b=5, documents=10) == pytest.approx(1.0)
    assert npmi(co=1, count_a=9, count_b=9, documents=10) < 0
    assert npmi(co=0, count_a=3, count_b=3, documents=10) == -1.0


def test_edge_weight_shrinks_rare_pairs() -> None:
    once = edge_weight(co=1, count_a=1, count_b=1, documents=20)
    often = edge_weight(co=10, count_a=10, count_b=10, documents=20)
    assert 0 < once < often <= 1


def test_graph_links_co_occurring_skills_and_normalises_names() -> None:
    graph = _graph(
        ["rust", "soroban"],
        ["Rust", "soroban", "security"],
        ["rustlang", "soroban"],
        ["react", "typescript"],
        ["react", "ts"],
        ["python", "postgres"],
    )
    assert graph.documents == 6
    assert graph.doc_counts["rust"] == 3 and graph.doc_counts["typescript"] == 2
    assert graph.weight("rust", "soroban") > graph.weight("rust", "security") > 0
    assert graph.weight("soroban", "rust") == graph.weight("rust", "soroban")  # stored both ways
    assert graph.weight("rust", "react") == 0.0  # never together
    assert all(e.weight > 0 for edges in graph.neighbors.values() for e in edges)


def test_graph_round_trips_through_json() -> None:
    graph = build_graph([["rust", "soroban"], ["rust", "soroban"]], bounty_skill_names=["Rust", "rust"])
    again = type(graph).from_json(graph.to_json())
    assert again.weight("rust", "soroban") == pytest.approx(graph.weight("rust", "soroban"))
    assert again.bounty_forms["rust"] == ("rust",)


def test_related_skills_excludes_inputs_and_explains_the_link() -> None:
    graph = _graph(
        *[["rust", "soroban"]] * 4,
        ["rust", "wasm"],
        ["soroban", "stellar"],
        ["go"],
        ["python"],
        ["python", "django"],
        ["figma"],
    )
    related = related_skills(graph, ["rust"], limit=5)
    names = [r.skill for r in related]
    assert names[0] == "soroban"
    assert "rust" not in names and "go" not in names
    assert related[0].via == ("rust",)
    both = related_skills(graph, ["rust", "soroban"])
    assert {r.skill for r in both} == {"webassembly", "stellar"}


# --- Seeds and proximity -----------------------------------------------------------------


def test_seed_weights_rank_sources_and_discount_tags() -> None:
    seeds = ranking.seed_weights(
        ranking.UserSignals(
            profile=["Rust"],
            completed=[ranking.SkillSet(required=["soroban"])],
            applied=[ranking.SkillSet(required=["rust", "wasm"], tags=["audit"])],
            bookmarked=[ranking.SkillSet(required=["figma"])],
        )
    )
    assert seeds["rust"] == ranking.PROFILE_WEIGHT  # the strongest source wins
    assert seeds["soroban"] == ranking.COMPLETED_WEIGHT
    assert seeds["webassembly"] == ranking.APPLIED_WEIGHT
    assert seeds["audit"] == pytest.approx(ranking.APPLIED_WEIGHT * ranking.TAG_FACTOR)
    assert seeds["figma"] == ranking.BOOKMARKED_WEIGHT


def test_proximity_prefers_direct_matches_and_explains_related_ones() -> None:
    graph = _graph(["rust", "soroban"], ["rust", "soroban"], ["rust", "soroban", "wasm"])
    user = ranking.reach({"rust": 1.0}, graph)
    direct = ranking.proximity(ranking.SkillSet(required=["rust"]), user)
    related = ranking.proximity(ranking.SkillSet(required=["soroban"]), user)
    unrelated = ranking.proximity(ranking.SkillSet(required=["figma"]), user)
    assert direct.score == pytest.approx(1.0) and direct.matched == ("rust",)
    assert 0 < related.score < direct.score
    assert (
        related.matched == () and related.related[0].skill == "soroban" and related.related[0].via == "rust"
    )
    assert unrelated.score == 0.0


def test_proximity_is_a_weighted_mean_over_the_bounty_skills() -> None:
    user = ranking.reach({"rust": 1.0}, _graph())
    half = ranking.proximity(ranking.SkillSet(required=["rust", "figma"]), user)
    assert half.score == pytest.approx(0.5)
    tag_only = ranking.proximity(ranking.SkillSet(required=["figma"], tags=["rust"]), user)
    assert tag_only.score == pytest.approx(ranking.TAG_FACTOR / (1 + ranking.TAG_FACTOR))


# --- Ranking -------------------------------------------------------------------------------


def _candidate(
    skills: list[str],
    *,
    reward: str = "100",
    asset: str = "XLM",
    funding: str = "FUNDED",
    days_left: float | None = 20,
    age_hours: float = 1,
) -> ranking.Candidate:
    return ranking.Candidate(
        bounty_id=uuid.uuid4(),
        skills=ranking.SkillSet(required=skills),
        reward=Decimal(reward),
        asset=asset,
        deadline=NOW + timedelta(days=days_left) if days_left is not None else None,
        funding_status=funding,
        listed_at=NOW - timedelta(hours=age_hours),
    )


def test_rank_orders_by_skill_proximity_first() -> None:
    graph = _graph(["rust", "soroban"], ["rust", "soroban"])
    user = ranking.reach({"rust": 1.0}, graph)
    exact = _candidate(["rust"], reward="10", funding="UNFUNDED")
    near = _candidate(["soroban"], reward="5000")
    none = _candidate(["figma"], reward="9000")
    ranked = ranking.rank([none, near, exact], user, NOW)
    assert [r.bounty_id for r in ranked] == [exact.bounty_id, near.bounty_id]  # no proximity: left out


def test_rank_blends_funding_reward_and_deadline_between_equal_matches() -> None:
    user = ranking.reach({"rust": 1.0}, _graph())
    funded = _candidate(["rust"], funding="FUNDED")
    unfunded = _candidate(["rust"], funding="UNFUNDED")
    assert [r.bounty_id for r in ranking.rank([unfunded, funded], user, NOW)] == [
        funded.bounty_id,
        unfunded.bounty_id,
    ]

    rich = _candidate(["rust"], reward="1000")
    poor = _candidate(["rust"], reward="10")
    assert ranking.rank([poor, rich], user, NOW)[0].bounty_id == rich.bounty_id

    roomy = _candidate(["rust"], days_left=30)
    closing = _candidate(["rust"], days_left=0.5)
    assert ranking.rank([closing, roomy], user, NOW)[0].bounty_id == roomy.bounty_id


def test_rewards_are_compared_within_their_asset() -> None:
    user = ranking.reach({"rust": 1.0}, _graph())
    xlm = _candidate(["rust"], reward="1000", asset="XLM")
    usdc = _candidate(["rust"], reward="50", asset="USDC")
    parts = {r.bounty_id: r.parts for r in ranking.rank([xlm, usdc], user, NOW)}
    assert parts[xlm.bounty_id]["reward"] == pytest.approx(1.0)
    assert parts[usdc.bounty_id]["reward"] == pytest.approx(1.0)  # the best USDC reward, not 50/1000


def test_rank_breaks_ties_by_newest() -> None:
    user = ranking.reach({"rust": 1.0}, _graph())
    older = _candidate(["rust"], age_hours=48)
    newer = _candidate(["rust"], age_hours=1)
    assert ranking.rank([older, newer], user, NOW)[0].bounty_id == newer.bounty_id


def test_score_parts_stay_in_range() -> None:
    assert ranking.deadline_score(None, NOW) == ranking.NO_DEADLINE_SCORE
    assert ranking.deadline_score(NOW - timedelta(days=1), NOW) == 0.0
    assert ranking.deadline_score(NOW + timedelta(days=365), NOW) == pytest.approx(1.0)
    assert ranking.reward_score(Decimal(0), Decimal(10)) == 0.0
    assert ranking.funding_score("REFUNDED") == ranking.FUNDING_SCORES["UNFUNDED"]


# --- Offline evaluation -------------------------------------------------------------------


def test_split_holds_out_the_most_recent_applications() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    user = EvalUser(
        id=uuid.uuid4(),
        profile=[],
        applications=[(b, NOW - timedelta(days=1)), (a, NOW - timedelta(days=3)), (c, NOW)],
    )
    train, test, when = split(user, 0.34)  # type: ignore[misc]
    assert train == [a] and test == [b, c] and when == NOW - timedelta(days=1)
    assert split(EvalUser(id=uuid.uuid4(), profile=[], applications=[(a, NOW)]), 0.2) is None


def test_evaluation_rewards_skill_relevance_over_popularity() -> None:
    requester = uuid.uuid4()

    def bounty(skills: list[str], applications: int, age: int) -> EvalBounty:
        return EvalBounty(
            id=uuid.uuid4(),
            requester_id=requester,
            skills=ranking.SkillSet(required=skills),
            reward=Decimal(100),
            asset="XLM",
            deadline=None,
            funding_status="FUNDED",
            listed_at=NOW - timedelta(days=age),
            applications=applications,
        )

    rust = [bounty(["rust", "soroban"], 1, i) for i in range(4)]
    design = [bounty(["figma", "ui design"], 20, i) for i in range(4)]
    users = [
        EvalUser(
            id=uuid.uuid4(),
            profile=["rust"],
            applications=[(rust[0].id, NOW - timedelta(days=2)), (rust[i].id, NOW - timedelta(hours=i))],
        )
        for i in (1, 2, 3)
    ]
    graph = build_graph([b.skills.required for b in rust + design])
    report = evaluate(users, rust + design, graph, k=3, holdout=0.5)
    assert report.users == 3 and report.held_out == 3
    assert report.model.hit_rate == pytest.approx(1.0)  # every held-out rust bounty is in the top 3
    assert report.baselines["popularity"].hit_rate == 0.0  # the busy design bounties crowd them out
    assert report.model.precision > report.baselines["popularity"].precision
    table = format_report([report])
    assert "| 3 | skill graph |" in table and "Users evaluated: 3" in table
