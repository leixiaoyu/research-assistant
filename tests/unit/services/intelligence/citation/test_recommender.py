"""Tests for CitationRecommender (Issue #130, REQ-9.2.5).

Conventions (from CLAUDE.md and PR #143 lessons):
- Use ``monkeypatch.setattr(target_module, "logger", structlog.get_logger())``
  *before* entering ``capture_logs()`` to rebind the cached logger.
- All ``pytest.raises`` calls include ``match=``.
- Mock ``CouplingAnalyzerProtocol``, ``CitationCrawler``, and ``InfluenceScorer``
  at the module's *namespace* boundary (NOT patch internal methods).
- ``pytest.mark.asyncio`` on every async test (asyncio_mode = "strict").
- Use ``assert_called_once_with(...)`` — never bare ``assert_called_once()``.
- No bare ``assert_called_once()``.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
import structlog.testing

from src.services.intelligence.citation import recommender as recommender_module
from src.services.intelligence.citation.models import CouplingResult
from src.services.intelligence.citation.influence_scorer import InfluenceMetrics
from src.services.intelligence.citation.models import (
    EdgeType,
    Recommendation,
    RecommendationStrategy,
)
from src.services.intelligence.citation.recommender import (
    CitationRecommender,
    _normalize_scores,
    _validate_paper_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEED = "paper:s2:seed001"
_P1 = "paper:s2:cand001"
_P2 = "paper:s2:cand002"
_P3 = "paper:s2:cand003"
_P4 = "paper:s2:cand004"
_P5 = "paper:s2:cand005"


def _make_metrics(
    paper_id: str,
    *,
    pagerank: float = 0.1,
    velocity: float = 5.0,
    citation_count: int = 10,
) -> InfluenceMetrics:
    return InfluenceMetrics(
        paper_id=paper_id,
        pagerank_score=pagerank,
        citation_velocity=velocity,
        citation_count=citation_count,
        computed_at=datetime.now(timezone.utc),
    )


def _coupling_result(
    seed: str,
    other: str,
    strength: float = 0.5,
    shared: int = 5,
) -> CouplingResult:
    return CouplingResult(
        paper_a_id=seed,
        paper_b_id=other,
        coupling_strength=strength,
        shared_references=[f"paper:s2:ref{i:03d}" for i in range(shared)],
    )


def _make_graph_node(node_id: str, year: int | None = None) -> MagicMock:
    node = MagicMock()
    node.node_id = node_id
    props: dict[str, Any] = {}
    if year is not None:
        props["year"] = year
    node.properties = props
    return node


def _build_recommender(
    *,
    traverse_returns: list[Any] | None = None,
    coupling_results: list[CouplingResult] | None = None,
    metrics_map: dict[str, InfluenceMetrics] | None = None,
    get_node_returns: dict[str, Any] | None = None,
) -> tuple[CitationRecommender, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build a CitationRecommender with mocked collaborators.

    Returns:
        (recommender, mock_coupling, mock_crawler, mock_scorer, mock_store)
    """
    mock_coupling = AsyncMock()
    mock_coupling.analyze_for_paper = AsyncMock(return_value=coupling_results or [])

    mock_crawler = MagicMock()

    mock_scorer = AsyncMock()

    # Build metrics list from map
    m_map = metrics_map or {}

    async def _compute_for_graph(node_ids: list[str]) -> list[InfluenceMetrics]:
        return [m_map.get(nid, _make_metrics(nid)) for nid in node_ids]

    mock_scorer.compute_for_graph = _compute_for_graph

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(return_value=traverse_returns or [])

    g_n = get_node_returns or {}
    mock_store.get_node = MagicMock(side_effect=lambda nid: g_n.get(nid))

    rec = CitationRecommender(
        coupling=mock_coupling,
        crawler=mock_crawler,
        scorer=mock_scorer,
        store=mock_store,
    )
    return rec, mock_coupling, mock_crawler, mock_scorer, mock_store


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


def test_validate_paper_id_accepts_valid() -> None:
    """Valid canonical paper ids should not raise."""
    _validate_paper_id("paper:s2:abc123")
    _validate_paper_id("paper:s2:abc-def_ghi.jkl")


def test_validate_paper_id_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        _validate_paper_id("")


def test_validate_paper_id_rejects_too_long() -> None:
    with pytest.raises(ValueError, match="exceeds max"):
        _validate_paper_id("a" * 513)


def test_validate_paper_id_rejects_slash() -> None:
    with pytest.raises(ValueError, match="Invalid paper_id format"):
        _validate_paper_id("paper/slash")


def test_normalize_scores_empty() -> None:
    assert _normalize_scores({}) == {}


def test_normalize_scores_all_zero() -> None:
    assert _normalize_scores({"a": 0.0, "b": 0.0}) == {"a": 0.0, "b": 0.0}


def test_normalize_scores_scales_to_one() -> None:
    result = _normalize_scores({"a": 2.0, "b": 4.0, "c": 1.0})
    assert result["b"] == pytest.approx(1.0)
    assert result["a"] == pytest.approx(0.5)
    assert result["c"] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Recommendation model tests
# ---------------------------------------------------------------------------


def test_recommendation_score_bounded_zero_to_one() -> None:
    """All recommendations must have score in [0.0, 1.0] (fuzz test)."""
    rng = random.Random(42)
    for _ in range(50):
        score = rng.uniform(0.0, 1.0)
        rec = Recommendation(
            paper_id=_P1,
            score=score,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="test",
            seed_paper_id=_SEED,
        )
        assert 0.0 <= rec.score <= 1.0


def test_recommendation_rejects_self_recommendation() -> None:
    """seed_paper_id == paper_id must raise a validation error."""
    with pytest.raises(Exception, match="must differ"):
        Recommendation(
            paper_id=_SEED,
            score=0.5,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="bad",
            seed_paper_id=_SEED,
        )


def test_recommendation_rejects_empty_reasoning() -> None:
    with pytest.raises(Exception, match="at least 1 character"):
        Recommendation(
            paper_id=_P1,
            score=0.5,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="",
            seed_paper_id=_SEED,
        )


def test_recommendation_rejects_invalid_paper_id() -> None:
    with pytest.raises(Exception, match="Invalid paper id format"):
        Recommendation(
            paper_id="bad/id",
            score=0.5,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="ok",
            seed_paper_id=_SEED,
        )


def test_recommendation_rejects_whitespace_only_paper_id() -> None:
    """Empty (whitespace) paper_id should raise 'paper id cannot be empty'."""
    with pytest.raises(Exception, match="paper id cannot be empty"):
        Recommendation(
            paper_id="   ",
            score=0.5,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="ok",
            seed_paper_id=_SEED,
        )


# ---------------------------------------------------------------------------
# CouplingResult model tests
# ---------------------------------------------------------------------------


def test_coupling_result_rejects_invalid_id() -> None:
    with pytest.raises(Exception, match="Invalid paper_id format"):
        CouplingResult(
            paper_a_id="bad/id",
            paper_b_id=_P1,
            coupling_strength=0.5,
        )


def test_coupling_result_rejects_out_of_range_strength() -> None:
    with pytest.raises(Exception, match="less than or equal to 1"):
        CouplingResult(
            paper_a_id=_SEED,
            paper_b_id=_P1,
            coupling_strength=1.5,
        )


# ---------------------------------------------------------------------------
# recommend_similar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_similar_returns_top_k_by_coupling(monkeypatch) -> None:
    """recommend_similar returns recommendations ordered by coupling_strength."""
    coupling_results = [
        _coupling_result(_SEED, _P1, strength=0.9, shared=10),
        _coupling_result(_SEED, _P2, strength=0.6, shared=6),
        _coupling_result(_SEED, _P3, strength=0.3, shared=3),
    ]
    traverse_nodes = [
        _make_graph_node(_P1),
        _make_graph_node(_P2),
        _make_graph_node(_P3),
    ]
    rec, mock_coupling, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        coupling_results=coupling_results,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_similar(_SEED, k=2)

    assert len(results) == 2
    assert results[0].paper_id == _P1
    assert results[0].score == pytest.approx(0.9)
    assert results[0].strategy == RecommendationStrategy.SIMILAR
    assert "Jaccard=0.90" in results[0].reasoning
    assert results[1].paper_id == _P2

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_complete" in events

    mock_coupling.analyze_for_paper.assert_called_once_with(
        _SEED, [_P1, _P2, _P3], top_k=2
    )


@pytest.mark.asyncio
async def test_recommend_similar_with_isolated_seed_returns_empty(monkeypatch) -> None:
    """When the BFS finds no neighbors, return [] and log seed_isolated."""
    rec, _, _, _, _ = _build_recommender(traverse_returns=[])

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_similar(_SEED, k=10)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


@pytest.mark.asyncio
async def test_recommend_similar_invalid_seed_raises() -> None:
    """Malformed seed id raises ValueError before any I/O."""
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match="Invalid paper_id format"):
        await rec.recommend_similar("bad/seed", k=5)


@pytest.mark.asyncio
async def test_recommend_similar_k_zero_raises() -> None:
    """M-3: k=0 must raise (after H-2 cap requiring k in [1, 100])."""
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match=r"k must be in \[1, 100\]"):
        await rec.recommend_similar(_SEED, k=0)


@pytest.mark.asyncio
async def test_recommend_similar_k_above_cap_raises() -> None:
    """M-3 / H-2: k > 100 must raise."""
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match=r"k must be in \[1, 100\]"):
        await rec.recommend_similar(_SEED, k=101)


@pytest.mark.asyncio
async def test_recommend_similar_k_exceeds_candidates_returns_all() -> None:
    """M-3: k larger than available candidates returns all available, not k entries."""
    coupling_results = [
        _coupling_result(_SEED, _P1, strength=0.9, shared=10),
        _coupling_result(_SEED, _P2, strength=0.6, shared=6),
    ]
    traverse_nodes = [_make_graph_node(_P1), _make_graph_node(_P2)]
    rec, _, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        coupling_results=coupling_results,
    )

    results = await rec.recommend_similar(_SEED, k=10)

    assert len(results) == 2
    assert results[0].paper_id == _P1
    assert results[1].paper_id == _P2


@pytest.mark.asyncio
async def test_recommend_similar_ties_broken_deterministically() -> None:
    """M-3: Tied coupling_strength → results are consistently ordered.

    Tie-break stability matters because recommend_all and downstream UI
    must produce stable output across cache-cold and cache-warm calls.
    """
    coupling_results = [
        _coupling_result(_SEED, _P3, strength=0.5, shared=5),
        _coupling_result(_SEED, _P1, strength=0.5, shared=5),
        _coupling_result(_SEED, _P2, strength=0.5, shared=5),
    ]
    traverse_nodes = [
        _make_graph_node(_P1),
        _make_graph_node(_P2),
        _make_graph_node(_P3),
    ]
    rec, _, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        coupling_results=coupling_results,
    )

    # Two consecutive calls produce the same order (deterministic).
    results_a = await rec.recommend_similar(_SEED, k=3)
    results_b = await rec.recommend_similar(_SEED, k=3)

    assert [r.paper_id for r in results_a] == [r.paper_id for r in results_b]


def test_recommendation_rejects_extra_fields() -> None:
    """M-1: Recommendation model_config has extra='forbid'.

    Future refactor that drops the strict config would silently accept
    spurious fields and not be caught without this pin.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Recommendation(
            paper_id=_P1,
            score=0.5,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="test",
            seed_paper_id=_SEED,
            spurious_field="should be rejected",  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# recommend_influential_predecessors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_influential_predecessors_uses_backward_crawl(
    monkeypatch,
) -> None:
    """Influential predecessors are ranked by pagerank_score descending."""
    metrics_map = {
        _P1: _make_metrics(_P1, pagerank=0.8),
        _P2: _make_metrics(_P2, pagerank=0.4),
        _P3: _make_metrics(_P3, pagerank=0.1),
    }
    traverse_nodes = [
        _make_graph_node(_P1),
        _make_graph_node(_P2),
        _make_graph_node(_P3),
    ]
    rec, _, _, _, mock_store = _build_recommender(
        traverse_returns=traverse_nodes,
        metrics_map=metrics_map,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_influential_predecessors(_SEED, k=3)

    assert len(results) == 3
    assert results[0].paper_id == _P1
    assert results[0].score == pytest.approx(0.8)
    assert results[0].strategy == RecommendationStrategy.INFLUENTIAL_PREDECESSOR
    assert "PageRank=0.8000" in results[0].reasoning
    assert results[1].paper_id == _P2

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_complete" in events

    # Store called with correct args (H-5: assert_called_with not bare .called)
    mock_store.traverse.assert_called_with(
        _SEED,
        edge_types=[EdgeType.CITES],
        max_depth=2,
        direction="outgoing",
    )


@pytest.mark.asyncio
async def test_recommend_influential_predecessors_isolated_returns_empty(
    monkeypatch,
) -> None:
    rec, _, _, _, _ = _build_recommender(traverse_returns=[])

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_influential_predecessors(_SEED, k=5)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


# ---------------------------------------------------------------------------
# recommend_active_successors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_active_successors_filters_by_year(monkeypatch) -> None:
    """Only papers published within the last 2 years are returned."""
    from src.services.intelligence.citation import recommender as rm

    current_year = rm._current_year()
    cutoff = current_year - 2

    old_node = _make_graph_node(_P1, year=cutoff - 1)  # too old
    new_node = _make_graph_node(_P2, year=current_year)  # recent

    metrics_map = {
        _P2: _make_metrics(_P2, velocity=10.0),
    }
    traverse_nodes = [old_node, new_node]
    get_node_returns = {
        _P1: old_node,
        _P2: new_node,
    }
    rec, _, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        metrics_map=metrics_map,
        get_node_returns=get_node_returns,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_active_successors(_SEED, k=10)

    # Only the recent paper makes it through.
    paper_ids = [r.paper_id for r in results]
    assert _P2 in paper_ids
    assert _P1 not in paper_ids

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_complete" in events


@pytest.mark.asyncio
async def test_recommend_active_successors_ranks_by_velocity(monkeypatch) -> None:
    """Active successors are sorted by normalized citation_velocity."""
    from src.services.intelligence.citation import recommender as rm

    current_year = rm._current_year()

    n1 = _make_graph_node(_P1, year=current_year)
    n2 = _make_graph_node(_P2, year=current_year)
    n3 = _make_graph_node(_P3, year=current_year)

    metrics_map = {
        _P1: _make_metrics(_P1, velocity=5.0),
        _P2: _make_metrics(_P2, velocity=20.0),  # highest
        _P3: _make_metrics(_P3, velocity=10.0),
    }
    get_node_returns = {_P1: n1, _P2: n2, _P3: n3}
    traverse_nodes = [n1, n2, n3]

    rec, _, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        metrics_map=metrics_map,
        get_node_returns=get_node_returns,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    results = await rec.recommend_active_successors(_SEED, k=3)

    assert len(results) == 3
    assert results[0].paper_id == _P2  # highest velocity
    assert results[0].score == pytest.approx(1.0)  # normalized
    assert results[1].paper_id == _P3
    assert results[2].paper_id == _P1


@pytest.mark.asyncio
async def test_recommend_active_successors_no_recent_papers(monkeypatch) -> None:
    """All papers older than cutoff → empty result, log seed_isolated."""
    from src.services.intelligence.citation import recommender as rm

    current_year = rm._current_year()
    old_node = _make_graph_node(_P1, year=current_year - 10)
    get_node_returns = {_P1: old_node}

    rec, _, _, _, _ = _build_recommender(
        traverse_returns=[old_node],
        get_node_returns=get_node_returns,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_active_successors(_SEED, k=10)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


# ---------------------------------------------------------------------------
# recommend_bridge_papers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_bridge_papers_identifies_connectors(monkeypatch) -> None:
    """Papers co-cited by ≥2 distant papers are identified as bridges."""
    # BFS radius-2 neighbors of seed: [P1, P2, P3]
    # BFS radius-3 additional distant nodes: [P4, P5] (not in r2)
    # P4 and P5 both reference P1 → P1 is a bridge with count=2.
    # P4 references P2 → P2 has count=1 (below threshold).

    r2_nodes = [_make_graph_node(_P1), _make_graph_node(_P2), _make_graph_node(_P3)]
    r3_nodes = r2_nodes + [_make_graph_node(_P4), _make_graph_node(_P5)]

    # Store.traverse is called twice:
    # 1st call: radius=2 outgoing → r2_nodes (candidates)
    # 2nd call: radius=3 outgoing → r3_nodes (frontier)
    # Then _list_outgoing_edges_for_nodes is called once with [P4, P5]:
    #   P4 → [P1, P2], P5 → [P1]

    call_count = [0]

    def _traverse_side_effect(node_id, edge_types, max_depth, direction="both"):
        call_count[0] += 1
        c = call_count[0]
        if c == 1:
            return r2_nodes
        elif c == 2:
            return r3_nodes
        return []

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=_traverse_side_effect)
    mock_store.get_node = MagicMock(return_value=None)
    # Bulk query: P4 cites P1+P2, P5 cites P1
    mock_store._list_outgoing_edges_for_nodes = MagicMock(
        return_value={_P4: [_P1, _P2], _P5: [_P1]}
    )

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_bridge_papers(_SEED, k=5)

    paper_ids = [r.paper_id for r in results]
    assert _P1 in paper_ids  # co-cited by P4 and P5 (count=2 ≥ threshold)
    assert _P2 not in paper_ids  # only co-cited by P4 (count=1 < threshold)

    assert results[0].strategy == RecommendationStrategy.BRIDGE
    assert results[0].score == pytest.approx(1.0)  # P1 is the only bridge → max

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_complete" in events


@pytest.mark.asyncio
async def test_recommend_bridge_papers_isolated_seed(monkeypatch) -> None:
    """Seed with no neighbors returns empty."""
    rec, _, _, _, _ = _build_recommender(traverse_returns=[])

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_bridge_papers(_SEED, k=5)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


@pytest.mark.asyncio
async def test_recommend_bridge_papers_no_bridges_below_threshold(
    monkeypatch,
) -> None:
    """No candidate meets the min-distant-co-citers threshold → empty + log."""
    r2_nodes = [_make_graph_node(_P1), _make_graph_node(_P2)]
    r3_nodes = r2_nodes + [_make_graph_node(_P4)]

    call_count = [0]

    def _traverse_se(node_id, edge_types, max_depth, direction="both"):
        call_count[0] += 1
        c = call_count[0]
        if c == 1:
            return r2_nodes
        elif c == 2:
            return r3_nodes
        return []

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=_traverse_se)
    mock_store.get_node = MagicMock(return_value=None)
    # P4 only references P1 once (count=1 < threshold of 2)
    mock_store._list_outgoing_edges_for_nodes = MagicMock(return_value={_P4: [_P1]})

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_bridge_papers(_SEED, k=5)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


# ---------------------------------------------------------------------------
# recommend_all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_all_returns_per_strategy(monkeypatch) -> None:
    """recommend_all returns a dict with all four strategy keys."""
    traverse_nodes = [_make_graph_node(_P1)]
    coupling_results = [_coupling_result(_SEED, _P1)]
    current_year = recommender_module._current_year()
    get_node_returns = {_P1: _make_graph_node(_P1, year=current_year)}

    rec, _, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        coupling_results=coupling_results,
        get_node_returns=get_node_returns,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    result = await rec.recommend_all(_SEED, k_per_strategy=1)

    assert set(result.keys()) == set(RecommendationStrategy)
    for strategy in RecommendationStrategy:
        assert isinstance(result[strategy], list)


@pytest.mark.asyncio
async def test_recommend_all_runs_strategies_concurrently(monkeypatch) -> None:
    """recommend_all invokes asyncio.gather (concurrent execution)."""
    rec, _, _, _, _ = _build_recommender(traverse_returns=[])

    gather_calls: list[Any] = []
    original_gather = asyncio.gather

    async def _mock_gather(*coros, **kwargs):
        gather_calls.append(coros)
        return await original_gather(*coros, **kwargs)

    monkeypatch.setattr(recommender_module.asyncio, "gather", _mock_gather)
    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())

    await rec.recommend_all(_SEED, k_per_strategy=3)

    # gather must have been called exactly once (the recommend_all call)
    assert len(gather_calls) == 1
    # It must have received exactly 4 coroutines (one per strategy)
    assert len(gather_calls[0]) == 4

    # L-7: verify the result dict contains all four strategies in the
    # canonical order (SIMILAR, INFLUENTIAL_PREDECESSOR, ACTIVE_SUCCESSOR, BRIDGE).
    # recommend_all(...) with empty traverse returns empty lists for all.
    all_result = await rec.recommend_all(_SEED, k_per_strategy=3)
    assert list(all_result.keys()) == [
        RecommendationStrategy.SIMILAR,
        RecommendationStrategy.INFLUENTIAL_PREDECESSOR,
        RecommendationStrategy.ACTIVE_SUCCESSOR,
        RecommendationStrategy.BRIDGE,
    ]


@pytest.mark.asyncio
async def test_recommend_all_invalid_seed_raises() -> None:
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match="Invalid paper_id format"):
        await rec.recommend_all("bad/seed", k_per_strategy=5)


# ---------------------------------------------------------------------------
# invalid seed id tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_seed_id_raises_similar() -> None:
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match="Invalid paper_id format"):
        await rec.recommend_similar("bad/seed")


@pytest.mark.asyncio
async def test_invalid_seed_id_raises_predecessors() -> None:
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match="Invalid paper_id format"):
        await rec.recommend_influential_predecessors("bad/seed")


@pytest.mark.asyncio
async def test_invalid_seed_id_raises_successors() -> None:
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match="Invalid paper_id format"):
        await rec.recommend_active_successors("bad/seed")


@pytest.mark.asyncio
async def test_invalid_seed_id_raises_bridge() -> None:
    rec, _, _, _, _ = _build_recommender()
    with pytest.raises(ValueError, match="Invalid paper_id format"):
        await rec.recommend_bridge_papers("bad/seed")


# ---------------------------------------------------------------------------
# Log event tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_strategy_logs_failure_and_propagates(monkeypatch) -> None:
    """When a strategy raises, ``recommender_strategy_failed`` is logged and
    the exception propagates to the caller."""
    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=RuntimeError("graph DB down"))

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        with pytest.raises(RuntimeError, match="graph DB down"):
            await rec.recommend_similar(_SEED, k=5)

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_failed" in events


@pytest.mark.asyncio
async def test_recommend_strategy_complete_logged_on_success(monkeypatch) -> None:
    """``recommender_strategy_complete`` is emitted on a successful strategy run."""
    traverse_nodes = [_make_graph_node(_P1)]
    coupling_results = [_coupling_result(_SEED, _P1)]

    rec, _, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        coupling_results=coupling_results,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        await rec.recommend_similar(_SEED, k=5)

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_complete" in events


# ---------------------------------------------------------------------------
# Score normalization fuzz test
# ---------------------------------------------------------------------------


def test_score_normalization_within_zero_one() -> None:
    """Fuzz test: _normalize_scores always produces values in [0.0, 1.0]."""
    rng = random.Random(1234)
    for _ in range(100):
        n = rng.randint(1, 20)
        raw = {f"paper:s2:p{i}": rng.uniform(0.0, 100.0) for i in range(n)}
        normalized = _normalize_scores(raw)
        for k, v in normalized.items():
            assert 0.0 <= v <= 1.0, f"Score for {k} is {v}, expected in [0.0, 1.0]"


def test_score_normalization_preserves_ordering() -> None:
    """Normalization must not reorder scores."""
    scores = {"a": 3.0, "b": 1.5, "c": 0.5}
    normalized = _normalize_scores(scores)
    ranked_before = sorted(scores, key=lambda k: scores[k], reverse=True)
    ranked_after = sorted(normalized, key=lambda k: normalized[k], reverse=True)
    assert ranked_before == ranked_after


# ---------------------------------------------------------------------------
# Integration-style: bridge heuristic with no distant nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_bridge_no_distant_nodes(monkeypatch) -> None:
    """When radius-3 frontier equals radius-2 (no distant nodes), return empty."""
    r2_nodes = [_make_graph_node(_P1), _make_graph_node(_P2)]
    # r3 == r2 → no distant nodes → _list_outgoing_edges_for_nodes called with []
    call_count = [0]

    def _traverse_se(node_id, edge_types, max_depth, direction="both"):
        call_count[0] += 1
        if call_count[0] <= 2:
            return r2_nodes
        return []

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=_traverse_se)
    mock_store.get_node = MagicMock(return_value=None)
    mock_store._list_outgoing_edges_for_nodes = MagicMock(return_value={})

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_bridge_papers(_SEED, k=5)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


# ---------------------------------------------------------------------------
# Coverage gap: recommend_similar — seed appears as paper_b_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_similar_skips_when_other_id_equals_seed(monkeypatch) -> None:
    """When other_id resolves to seed_id, the coupling entry is skipped.

    The skip branch (other_id == seed_id) is triggered via mock objects:
    paper_a_id == seed → other = paper_b_id = seed → skip.
    """
    # Valid coupling result (other_id = P1, not seed)
    mock_cr = MagicMock()
    mock_cr.paper_a_id = _P1
    mock_cr.paper_b_id = _SEED
    mock_cr.coupling_strength = 0.8
    mock_cr.shared_references = [f"paper:s2:ref{i:03d}" for i in range(6)]

    # This coupling result has paper_a_id == seed → other = paper_b_id = seed → SKIP
    mock_cr_skip = MagicMock()
    mock_cr_skip.paper_a_id = _SEED  # == seed → other = paper_b_id
    mock_cr_skip.paper_b_id = _SEED  # other == seed → skipped
    mock_cr_skip.coupling_strength = 0.9
    mock_cr_skip.shared_references = [f"paper:s2:ref{i:03d}" for i in range(8)]

    traverse_nodes = [_make_graph_node(_P1)]

    mock_coupling = AsyncMock()
    mock_coupling.analyze_for_paper = AsyncMock(return_value=[mock_cr_skip, mock_cr])
    mock_store = MagicMock()
    mock_store.traverse = MagicMock(return_value=traverse_nodes)
    mock_store.get_node = MagicMock(return_value=None)

    rec = CitationRecommender(
        coupling=mock_coupling,
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    results = await rec.recommend_similar(_SEED, k=5)

    # mock_cr_skip should be skipped; mock_cr other_id = P1 (not seed)
    paper_ids = [r.paper_id for r in results]
    assert _SEED not in paper_ids


# ---------------------------------------------------------------------------
# Coverage gap: exception propagation in other strategies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_influential_predecessors_logs_failure(monkeypatch) -> None:
    """Failures in influential_predecessors log and propagate."""
    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=RuntimeError("store error"))

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        with pytest.raises(RuntimeError, match="store error"):
            await rec.recommend_influential_predecessors(_SEED, k=5)

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_failed" in events


@pytest.mark.asyncio
async def test_recommend_active_successors_logs_failure(monkeypatch) -> None:
    """Failures in active_successors log and propagate."""
    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=RuntimeError("db error"))

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        with pytest.raises(RuntimeError, match="db error"):
            await rec.recommend_active_successors(_SEED, k=5)

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_failed" in events


@pytest.mark.asyncio
async def test_recommend_bridge_papers_logs_failure(monkeypatch) -> None:
    """Failures in bridge_papers log and propagate."""
    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=RuntimeError("bridge error"))

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        with pytest.raises(RuntimeError, match="bridge error"):
            await rec.recommend_bridge_papers(_SEED, k=5)

    events = [e["event"] for e in cap_logs]
    assert "recommender_strategy_failed" in events


# ---------------------------------------------------------------------------
# Coverage gap: _filter_by_year — publication_date fallback path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_active_successors_uses_publication_date_fallback(
    monkeypatch,
) -> None:
    """_filter_by_year falls back to publication_date when year is missing."""
    from src.services.intelligence.citation import recommender as rm

    current_year = rm._current_year()

    # A node with no 'year' but a 'publication_date' string
    node_with_pub_date = MagicMock()
    node_with_pub_date.node_id = _P1
    node_with_pub_date.properties = {"publication_date": f"{current_year}-06-01"}

    # A node with no year and no publication_date → excluded
    node_no_date = MagicMock()
    node_no_date.node_id = _P2
    node_no_date.properties = {}

    metrics_map = {
        _P1: _make_metrics(_P1, velocity=8.0),
    }

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(return_value=[node_with_pub_date, node_no_date])
    mock_store.get_node = MagicMock(
        side_effect=lambda nid: {
            _P1: node_with_pub_date,
            _P2: node_no_date,
        }.get(nid)
    )

    async def _compute_for_graph(node_ids):
        return [metrics_map.get(nid, _make_metrics(nid)) for nid in node_ids]

    mock_scorer = AsyncMock()
    mock_scorer.compute_for_graph = _compute_for_graph

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=mock_scorer,
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    results = await rec.recommend_active_successors(_SEED, k=5)

    paper_ids = [r.paper_id for r in results]
    assert _P1 in paper_ids
    assert _P2 not in paper_ids


@pytest.mark.asyncio
async def test_recommend_active_successors_bad_publication_date_excluded(
    monkeypatch,
) -> None:
    """Nodes with unparsable publication_date are excluded from active successors."""
    node_bad_date = MagicMock()
    node_bad_date.node_id = _P1
    node_bad_date.properties = {"publication_date": "not-a-date"}

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(return_value=[node_bad_date])
    mock_store.get_node = MagicMock(return_value=node_bad_date)

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_active_successors(_SEED, k=5)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


@pytest.mark.asyncio
async def test_recommend_active_successors_bad_year_value_excluded(
    monkeypatch,
) -> None:
    """Nodes with non-integer year values are excluded from active successors."""
    node_bad_year = MagicMock()
    node_bad_year.node_id = _P1
    node_bad_year.properties = {"year": "not-a-year"}

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(return_value=[node_bad_year])
    mock_store.get_node = MagicMock(return_value=node_bad_year)

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_active_successors(_SEED, k=5)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


def test_coupling_result_model_post_init_rejects_bad_a_id() -> None:
    """CouplingResult rejects bad paper_a_id via field validator."""
    with pytest.raises(Exception, match="Invalid paper_id format"):
        CouplingResult(
            paper_a_id="bad/id",
            paper_b_id=_P1,
            coupling_strength=0.5,
        )


def test_coupling_result_model_post_init_rejects_bad_b_id() -> None:
    """CouplingResult rejects bad paper_b_id via field validator."""
    with pytest.raises(Exception, match="Invalid paper_id format"):
        CouplingResult(
            paper_a_id=_P1,
            paper_b_id="bad/id",
            coupling_strength=0.5,
        )


# ---------------------------------------------------------------------------
# Coverage gap: Recommendation model — score out of range
# ---------------------------------------------------------------------------


def test_recommendation_rejects_score_above_one() -> None:
    """score > 1.0 must fail validation."""
    with pytest.raises(Exception, match="less than or equal to 1"):
        Recommendation(
            paper_id=_P1,
            score=1.1,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="test",
            seed_paper_id=_SEED,
        )


def test_recommendation_rejects_score_below_zero() -> None:
    """score < 0.0 must fail validation."""
    with pytest.raises(Exception, match="greater than or equal to 0"):
        Recommendation(
            paper_id=_P1,
            score=-0.1,
            strategy=RecommendationStrategy.SIMILAR,
            reasoning="test",
            seed_paper_id=_SEED,
        )


# ---------------------------------------------------------------------------
# Coverage gap: _filter_by_year — node is None in store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_active_successors_node_not_in_store(monkeypatch) -> None:
    """Nodes whose get_node returns None are excluded from active successors."""
    traverse_node = _make_graph_node(_P1)

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(return_value=[traverse_node])
    # get_node returns None for any id → the `continue` at line 638 fires
    mock_store.get_node = MagicMock(return_value=None)

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_active_successors(_SEED, k=5)

    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


# ---------------------------------------------------------------------------
# Coverage gap: bridge — cited node NOT in r2_set (the false branch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommend_bridge_distant_cites_outside_r2_ignored(
    monkeypatch,
) -> None:
    """When distant nodes cite papers NOT in r2_set, those are not counted."""
    # r2 = [P1]; distant = [P4]; P4 references P5 (NOT in r2) → count stays 0
    r2_nodes = [_make_graph_node(_P1)]
    r3_nodes = r2_nodes + [_make_graph_node(_P4)]

    call_count = [0]

    def _traverse_se(node_id, edge_types, max_depth, direction="both"):
        call_count[0] += 1
        c = call_count[0]
        if c == 1:
            return r2_nodes
        elif c == 2:
            return r3_nodes
        return []

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=_traverse_se)
    mock_store.get_node = MagicMock(return_value=None)
    # P4 cites P5 only (not in r2) → count stays 0
    mock_store._list_outgoing_edges_for_nodes = MagicMock(return_value={_P4: [_P5]})

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        results = await rec.recommend_bridge_papers(_SEED, k=5)

    # No bridges found because P5 not in r2 and count < threshold
    assert results == []
    events = [e["event"] for e in cap_logs]
    assert "recommender_seed_isolated_returns_empty" in events


# ---------------------------------------------------------------------------
# Coverage gap closures (paying down debt — recommender.py was at 92.10%)
# ---------------------------------------------------------------------------


def test_connect_wires_real_collaborators(monkeypatch, tmp_path) -> None:
    """connect() factory wires SQLiteGraphStore + crawler + scorer correctly.

    Patches the constructors at the namespace boundary to avoid real network
    clients and verifies the wiring graph (covers lines 215-239).
    """
    db_path = tmp_path / "graph.db"
    captured: dict[str, object] = {}

    def _fake_store(p):
        captured["store"] = p
        return MagicMock(name="SQLiteGraphStore")

    def _fake_s2():
        return MagicMock(name="SemanticScholarCitationClient")

    def _fake_oa():
        return MagicMock(name="OpenAlexCitationClient")

    def _fake_crawler(*, store, s2_client, openalex_client):
        captured["crawler_store"] = store
        return MagicMock(name="CitationCrawler")

    def _fake_scorer(*, store):
        captured["scorer_store"] = store
        return MagicMock(name="InfluenceScorer")

    monkeypatch.setattr(recommender_module, "SQLiteGraphStore", _fake_store)
    monkeypatch.setattr(
        "src.services.intelligence.citation.crawler.CitationCrawler", _fake_crawler
    )
    monkeypatch.setattr(
        "src.services.intelligence.citation.openalex_client.OpenAlexCitationClient",
        _fake_oa,
    )
    monkeypatch.setattr(
        "src.services.intelligence.citation.semantic_scholar_client."
        "SemanticScholarCitationClient",
        _fake_s2,
    )
    monkeypatch.setattr(recommender_module, "InfluenceScorer", _fake_scorer)

    rec = CitationRecommender.connect(db_path=db_path)

    assert isinstance(rec, CitationRecommender)
    assert captured["store"] == db_path
    # Default coupling is _NullCouplingAdapter when no coupling injected.
    from src.services.intelligence.citation.recommender import _NullCouplingAdapter

    assert isinstance(rec._coupling, _NullCouplingAdapter)


def test_connect_uses_injected_coupling(monkeypatch, tmp_path) -> None:
    """connect() uses the injected coupling analyzer when provided."""
    monkeypatch.setattr(recommender_module, "SQLiteGraphStore", lambda p: MagicMock())
    monkeypatch.setattr(
        "src.services.intelligence.citation.crawler.CitationCrawler",
        lambda **kw: MagicMock(),
    )
    monkeypatch.setattr(
        "src.services.intelligence.citation.openalex_client.OpenAlexCitationClient",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "src.services.intelligence.citation.semantic_scholar_client."
        "SemanticScholarCitationClient",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        recommender_module, "InfluenceScorer", lambda *, store: MagicMock()
    )

    custom_coupling = AsyncMock()
    rec = CitationRecommender.connect(
        db_path=tmp_path / "graph.db", coupling=custom_coupling
    )
    assert rec._coupling is custom_coupling


@pytest.mark.asyncio
async def test_recommend_similar_caps_candidates_at_max(monkeypatch) -> None:
    """When candidates > _MAX_CANDIDATES, the list is truncated (line 287)."""
    # Force a tiny cap so we can prove the truncation path runs without
    # constructing 500+ MagicMock GraphNode objects.
    monkeypatch.setattr(recommender_module, "_MAX_CANDIDATES", 3)

    traverse_nodes = [_make_graph_node(f"paper:s2:cap{i:03d}") for i in range(10)]
    rec, mock_coupling, _, _, _ = _build_recommender(
        traverse_returns=traverse_nodes,
        coupling_results=[],
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    await rec.recommend_similar(_SEED, k=2)

    # Exactly _MAX_CANDIDATES (=3) ids should be passed to the analyzer.
    call_args = mock_coupling.analyze_for_paper.call_args
    passed_candidates = call_args[0][1]
    assert len(passed_candidates) == 3


@pytest.mark.asyncio
async def test_recommend_bridge_papers_caps_distant_frontier(monkeypatch) -> None:
    """When distant_nodes > _BRIDGE_MAX_DISTANT, frontier is truncated +
    a recommender_bridge_frontier_truncated event is emitted (lines 588-594)."""
    monkeypatch.setattr(recommender_module, "_BRIDGE_MAX_DISTANT", 2)

    # Build a graph: SEED → P1 → P2; r2 = {P1, P2}; r3 = many distant nodes.
    distant_ids = [f"paper:s2:dist{i:03d}" for i in range(10)]

    def _traverse_se(node_id, *, edge_types, max_depth, direction):
        if max_depth == 1:
            return [_make_graph_node(_P1)]  # r1 = {P1}
        if max_depth == 2:
            return [_make_graph_node(_P1), _make_graph_node(_P2)]  # r2 = {P1, P2}
        if max_depth == 3:
            return [_make_graph_node(_P1), _make_graph_node(_P2)] + [
                _make_graph_node(d) for d in distant_ids
            ]
        return []

    mock_store = MagicMock()
    mock_store.traverse = MagicMock(side_effect=_traverse_se)
    mock_store.get_node = MagicMock(return_value=None)
    mock_store._list_outgoing_edges_for_nodes = MagicMock(return_value={})

    rec = CitationRecommender(
        coupling=AsyncMock(),
        crawler=MagicMock(),
        scorer=AsyncMock(),
        store=mock_store,
    )

    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())
    with structlog.testing.capture_logs() as cap_logs:
        await rec.recommend_bridge_papers(_SEED, k=3)

    truncate_events = [
        e for e in cap_logs if e.get("event") == "recommender_bridge_frontier_truncated"
    ]
    assert len(truncate_events) == 1
    assert truncate_events[0]["cap"] == 2
    # Bulk query receives only the capped set (2 nodes), not all 10.
    bulk_call = mock_store._list_outgoing_edges_for_nodes.call_args
    # First positional arg is distant_nodes (capped to _BRIDGE_MAX_DISTANT=2).
    assert len(bulk_call.args[0]) == 2


@pytest.mark.asyncio
async def test_recommend_all_strategy_failure_logs_and_returns_empty(
    monkeypatch,
) -> None:
    """recommend_all logs strategy failures and returns [] for failed strategies
    (lines 718-724). The other 3 strategies still produce results."""
    rec, _, _, _, mock_store = _build_recommender(traverse_returns=[])

    # Make recommend_similar blow up; others should return [] from
    # the empty-traverse fixture cleanly.
    async def _failing_similar(seed_id, k):
        raise RuntimeError("simulated coupling outage")

    monkeypatch.setattr(rec, "recommend_similar", _failing_similar)
    monkeypatch.setattr(recommender_module, "logger", structlog.get_logger())

    with structlog.testing.capture_logs() as cap_logs:
        result = await rec.recommend_all(_SEED, k_per_strategy=3)

    # Failed strategy: empty list, error logged.
    assert result[RecommendationStrategy.SIMILAR] == []
    failure_events = [
        e
        for e in cap_logs
        if e.get("event") == "recommender_strategy_failed_in_recommend_all"
    ]
    assert len(failure_events) == 1
    assert failure_events[0]["strategy"] == RecommendationStrategy.SIMILAR.value
    assert "simulated coupling outage" in failure_events[0]["error"]

    # Other strategies: present (empty since no traverse), not raised.
    assert result[RecommendationStrategy.INFLUENTIAL_PREDECESSOR] == []
    assert result[RecommendationStrategy.ACTIVE_SUCCESSOR] == []
    assert result[RecommendationStrategy.BRIDGE] == []


@pytest.mark.asyncio
async def test_null_coupling_adapter_analyze_pair_returns_none() -> None:
    """_NullCouplingAdapter.analyze_pair returns None (line 808 default impl)."""
    from src.services.intelligence.citation.recommender import _NullCouplingAdapter

    adapter = _NullCouplingAdapter()
    result = await adapter.analyze_pair("paper:s2:a", "paper:s2:b")
    assert result is None


@pytest.mark.asyncio
async def test_null_coupling_adapter_analyze_for_paper_returns_empty() -> None:
    """_NullCouplingAdapter.analyze_for_paper returns [] (line 817 default impl)."""
    from src.services.intelligence.citation.recommender import _NullCouplingAdapter

    adapter = _NullCouplingAdapter()
    result = await adapter.analyze_for_paper("paper:s2:seed", ["paper:s2:c1"], top_k=5)
    assert result == []
