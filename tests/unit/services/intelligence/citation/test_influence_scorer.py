"""Tests for InfluenceScorer (Issue #129, REQ-9.2.4)."""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import structlog
import structlog.testing

from src.services.intelligence.citation import influence_repository as repo_module
from src.services.intelligence.citation import influence_scorer as scorer_module
from src.services.intelligence.citation.influence_repository import (
    CitationInfluenceRepository,
)
from src.services.intelligence.citation.influence_scorer import (
    DEFAULT_CACHE_TTL,
    MAX_GRAPH_NODES_FOR_HITS,
    InfluenceMetrics,
    InfluenceScorer,
)
from src.services.intelligence.citation.models import (
    CitationEdge,
    CitationNode,
    make_paper_node_id,
)
from src.services.intelligence.models import EdgeType
from src.storage.intelligence_graph import SQLiteGraphStore

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@pytest.fixture
def store(temp_db):
    s = SQLiteGraphStore(temp_db)
    s.initialize()
    return s


def _node(
    raw_id: str,
    *,
    citation_count: int = 0,
    year: int | None = None,
    publication_date: date | None = None,
) -> CitationNode:
    return CitationNode(
        paper_id=make_paper_node_id("s2", raw_id),
        title=f"Paper {raw_id}",
        external_ids={"s2": raw_id},
        citation_count=citation_count,
        year=year,
        publication_date=publication_date,
    )


def _persist_chain(store, *citation_nodes):
    """Insert the given nodes and an A → B → C chain of CITES edges."""
    for n in citation_nodes:
        store.add_node(
            n.paper_id, n.to_graph_node().node_type, n.to_graph_node().properties
        )
    for i in range(len(citation_nodes) - 1):
        edge = CitationEdge(
            citing_paper_id=citation_nodes[i].paper_id,
            cited_paper_id=citation_nodes[i + 1].paper_id,
            source="s2",
        ).to_graph_edge()
        store.add_edge(
            edge.edge_id,
            edge.source_id,
            edge.target_id,
            edge.edge_type,
            edge.properties,
        )


def _frozen_scorer(store, now: datetime, cache_ttl=DEFAULT_CACHE_TTL):
    return InfluenceScorer(store=store, cache_ttl=cache_ttl, now=now)


# ---------------------------------------------------------------------------
# Constructor / factory
# ---------------------------------------------------------------------------


def test_from_paths_factory_initialises_store(temp_db):
    s = InfluenceScorer.from_paths(db_path=temp_db)
    assert isinstance(s.store, SQLiteGraphStore)
    assert s.cache_ttl == DEFAULT_CACHE_TTL


def test_from_paths_factory_constructs_repo(temp_db):
    """``from_paths`` must build the repository alongside the store
    (issue #134) so callers don't need to know the cache table exists.
    """
    s = InfluenceScorer.from_paths(db_path=temp_db)
    assert isinstance(s._repo, CitationInfluenceRepository)
    # And it should be initialised (record_metrics doesn't raise
    # "not initialized").
    s._repo.record_metrics(InfluenceMetrics(paper_id="paper:s2:from-paths-test"))


def test_constructor_accepts_custom_now(store):
    fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s = InfluenceScorer(store=store, now=fixed)
    assert s._now() == fixed


def test_now_defaults_to_real_clock(store):
    s = InfluenceScorer(store=store)
    now = s._now()
    # Check we get a real datetime within reason.
    assert isinstance(now, datetime)
    # Must be timezone-aware (UTC) so callers can compare with
    # timezone-aware timestamps without TypeError.
    assert now.tzinfo is not None


def test_init_accepts_injected_repo(store):
    """DI seam (issue #134): callers may inject their own repo
    (tests, alternative backends) and the scorer must use that
    instance verbatim instead of constructing a default.
    """
    repo = CitationInfluenceRepository.from_path(store.db_path)
    s = InfluenceScorer(store=store, repo=repo)
    assert s._repo is repo


def test_init_builds_default_repo_when_none_passed(store):
    """Backward compatibility (issue #134): callers that haven't
    migrated to explicit injection must keep working -- the scorer
    constructs a repo against ``store.db_path`` and initialises it.
    """
    s = InfluenceScorer(store=store)
    assert isinstance(s._repo, CitationInfluenceRepository)
    # And the constructed repo points at the store's DB.
    assert s._repo.db_path == store.db_path
    # And it is initialised (record_metrics doesn't raise
    # "not initialized").
    s._repo.record_metrics(InfluenceMetrics(paper_id="paper:s2:default-repo-test"))


def test_max_age_days_rounds_up_from_subday_ttl(store):
    """``cache_ttl`` is a ``timedelta`` (legacy); the repo expects an
    integer day count. ``_max_age_days`` ceiling-divides so a 7-day
    TTL doesn't reject a 7-day-old row, and any sub-day TTL still
    satisfies the repo's ``max_age_days > 0`` precondition.
    """
    s = InfluenceScorer(store=store, cache_ttl=timedelta(seconds=10))
    assert s._max_age_days() == 1
    s = InfluenceScorer(store=store, cache_ttl=timedelta(days=7))
    assert s._max_age_days() == 7
    s = InfluenceScorer(store=store, cache_ttl=timedelta(days=7, seconds=1))
    assert s._max_age_days() == 8


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_paper_id_raises_value_error(store):
    s = InfluenceScorer(store=store)
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await s.compute_for_paper("bad space id")


@pytest.mark.asyncio
async def test_empty_paper_id_raises(store):
    s = InfluenceScorer(store=store)
    with pytest.raises(ValueError, match="non-empty"):
        await s.compute_for_paper("   ")


@pytest.mark.asyncio
async def test_oversized_paper_id_raises(store):
    s = InfluenceScorer(store=store)
    with pytest.raises(ValueError, match="exceeds max"):
        await s.compute_for_paper("a" * 600)


@pytest.mark.asyncio
async def test_non_string_paper_id_raises(store):
    s = InfluenceScorer(store=store)
    with pytest.raises(ValueError, match="non-empty string"):
        await s.compute_for_paper(None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_compute_for_graph_validates_each_id(store):
    s = InfluenceScorer(store=store)
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await s.compute_for_graph(["paper:s2:ok", "bad space"])


# ---------------------------------------------------------------------------
# PageRank delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagerank_delegates_to_graph_algorithms(store):
    """Verify GraphAlgorithms.pagerank is the single source of truth."""
    a = _node("a", citation_count=1, year=2020)
    _persist_chain(store, a)
    s = InfluenceScorer(store=store)

    with patch.object(
        scorer_module.GraphAlgorithms,
        "pagerank",
        wraps=scorer_module.GraphAlgorithms.pagerank,
    ) as mock_pr:
        await s.compute_for_paper(a.paper_id)
    mock_pr.assert_called_once()
    # Verify the edge_types argument is the typed enum value.
    _, kwargs = mock_pr.call_args
    assert kwargs.get("edge_types") == [EdgeType.CITES.value]


@pytest.mark.asyncio
async def test_pagerank_isolated_node_returns_baseline_score(store):
    """An isolated node still gets a non-zero PageRank baseline."""
    iso = _node("iso", year=2020)
    _persist_chain(store, iso)  # one node, no edges
    s = InfluenceScorer(store=store)
    metrics = await s.compute_for_paper(iso.paper_id)
    # PageRank baseline = 1/n; for a single node, n=1, so score=1.0
    # after clamp.
    assert 0.0 < metrics.pagerank_score <= 1.0


@pytest.mark.asyncio
async def test_pagerank_simple_chain_a_b_c_known_values(store):
    """A → B → C with damping=0.85: rank_C > rank_B > rank_A."""
    a = _node("a", citation_count=0, year=2020)
    b = _node("b", citation_count=1, year=2020)
    c = _node("c", citation_count=1, year=2020)
    _persist_chain(store, a, b, c)

    s = InfluenceScorer(store=store)
    metrics_a = await s.compute_for_paper(a.paper_id)
    metrics_b = await s.compute_for_paper(b.paper_id)
    metrics_c = await s.compute_for_paper(c.paper_id)

    # In a chain, the deepest node (C) gets the highest PageRank
    # because it accumulates all upstream rank.
    assert metrics_c.pagerank_score > metrics_b.pagerank_score
    assert metrics_b.pagerank_score > metrics_a.pagerank_score


# ---------------------------------------------------------------------------
# HITS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hits_authority_higher_than_hub_for_cited_paper(store):
    """In an A → B graph, B has high authority, A has high hub score."""
    a = _node("a", year=2020)
    b = _node("b", year=2020)
    _persist_chain(store, a, b)

    s = InfluenceScorer(store=store)
    metrics_a = await s.compute_for_paper(a.paper_id)
    metrics_b = await s.compute_for_paper(b.paper_id)

    assert metrics_b.authority_score > metrics_a.authority_score
    assert metrics_a.hub_score > metrics_b.hub_score


@pytest.mark.asyncio
async def test_hits_convergence_within_max_iter(store):
    """HITS converges quickly on small graphs (<<100 iters)."""
    nodes = [_node(f"n{i}", year=2020) for i in range(5)]
    _persist_chain(store, *nodes)
    s = InfluenceScorer(store=store)
    # Should not raise / hang. Convergence is internal; the smoke test
    # is that compute_for_graph returns sensible metrics for all nodes.
    out = await s.compute_for_graph([n.paper_id for n in nodes])
    assert len(out) == 5
    # All scores should be normalised → sum of squares ≈ 1.
    auth_sq = sum(m.authority_score**2 for m in out)
    assert 0.99 < auth_sq < 1.01


@pytest.mark.asyncio
async def test_hits_skipped_for_oversize_graph_logs_event(store, monkeypatch):
    """Above MAX_GRAPH_NODES_FOR_HITS, HITS is skipped (logs event)."""
    monkeypatch.setattr(scorer_module, "MAX_GRAPH_NODES_FOR_HITS", 1)
    monkeypatch.setattr(scorer_module, "logger", structlog.get_logger())

    a = _node("a", citation_count=1, year=2020)
    b = _node("b", citation_count=1, year=2020)
    _persist_chain(store, a, b)
    s = InfluenceScorer(store=store)

    with structlog.testing.capture_logs() as logs:
        metrics = await s.compute_for_paper(a.paper_id)

    # PageRank still ran (non-zero), but HITS was skipped.
    assert metrics.pagerank_score > 0
    assert metrics.hub_score == 0.0
    assert metrics.authority_score == 0.0
    skip_events = [
        e
        for e in logs
        if e.get("event") == "influence_scorer_hits_skipped_oversize_graph"
    ]
    assert len(skip_events) >= 1
    assert skip_events[0].get("limit") == 1


def test_hits_empty_graph_returns_empty(store):
    s = InfluenceScorer(store=store)
    hubs, authorities = s._compute_hits()
    assert hubs == {}
    assert authorities == {}


# ---------------------------------------------------------------------------
# Velocity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_citation_velocity_known_paper_fixed_date_math(store):
    """citations / years_since_publication, with frozen 'now'."""
    n = _node("v", citation_count=100, publication_date=date(2020, 1, 1))
    _persist_chain(store, n)
    fixed_now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    s = _frozen_scorer(store, fixed_now)
    metrics = await s.compute_for_paper(n.paper_id)
    # 5 years between 2020 and 2025 → 100/5 = 20.
    assert metrics.citation_velocity == 20.0


@pytest.mark.asyncio
async def test_citation_velocity_year_only_fallback(store):
    n = _node("y", citation_count=10, year=2020)
    _persist_chain(store, n)
    fixed_now = datetime(2022, 6, 1, tzinfo=timezone.utc)
    s = _frozen_scorer(store, fixed_now)
    metrics = await s.compute_for_paper(n.paper_id)
    # 2022 - 2020 = 2 years → 10/2 = 5.0
    assert metrics.citation_velocity == 5.0


@pytest.mark.asyncio
async def test_citation_velocity_same_year_clamps_to_one(store):
    """Papers from the current year still get a velocity (years=max(1,0))."""
    n = _node("recent", citation_count=5, year=2025)
    _persist_chain(store, n)
    fixed_now = datetime(2025, 6, 1, tzinfo=timezone.utc)
    s = _frozen_scorer(store, fixed_now)
    metrics = await s.compute_for_paper(n.paper_id)
    assert metrics.citation_velocity == 5.0


@pytest.mark.asyncio
async def test_citation_velocity_missing_publication_date_returns_zero_with_event(
    store, monkeypatch
):
    monkeypatch.setattr(scorer_module, "logger", structlog.get_logger())
    n = _node("no_date", citation_count=10)  # no year, no publication_date
    _persist_chain(store, n)

    s = InfluenceScorer(store=store)
    with structlog.testing.capture_logs() as logs:
        metrics = await s.compute_for_paper(n.paper_id)

    assert metrics.citation_velocity == 0.0
    skip_events = [
        e
        for e in logs
        if e.get("event") == "influence_scorer_velocity_skipped_missing_date"
    ]
    assert len(skip_events) == 1
    assert skip_events[0].get("paper_id") == n.paper_id


@pytest.mark.asyncio
async def test_citation_velocity_unknown_node_returns_zero(store):
    """A paper id with no node row in the graph yields zero velocity."""
    s = InfluenceScorer(store=store)
    # Node was never persisted, but compute_for_paper should still
    # return a baseline metric.
    out = await s.compute_for_paper(make_paper_node_id("s2", "ghost"))
    assert out.citation_velocity == 0.0
    assert out.citation_count == 0


def test_velocity_helper_handles_invalid_publication_date(store):
    """Corrupt publication_date string in properties is ignored, fallback to year."""
    s = InfluenceScorer(store=store, now=datetime(2025, 1, 1, tzinfo=timezone.utc))

    class _FakeNode:
        properties = {
            "publication_date": "not-a-date",
            "year": 2020,
            "citation_count": 4,
        }

    # 2025 - 2020 = 5 years → 4/5 = 0.8
    assert s._compute_velocity(_FakeNode(), "x") == pytest.approx(0.8)


def test_velocity_helper_handles_invalid_year(store):
    s = InfluenceScorer(store=store, now=datetime(2025, 1, 1, tzinfo=timezone.utc))

    class _FakeNode:
        properties = {"year": "not-a-year", "citation_count": 4}

    assert s._compute_velocity(_FakeNode(), "x") == 0.0


# ---------------------------------------------------------------------------
# Cache TTL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persistence_cache_hit_within_ttl(store):
    """Second call within TTL reuses cached row; PageRank not re-invoked.

    The cache is now owned by ``CitationInfluenceRepository``; when the
    repo returns a fresh row the scorer must short-circuit before
    invoking ``GraphAlgorithms.pagerank``.
    """
    n = _node("c1", citation_count=5, year=2020)
    _persist_chain(store, n)

    # ``now`` defaults to the real clock so the row written on the
    # first call is genuinely "fresh" (within max_age_days=7) on the
    # second call -- the repo's TTL filter is wall-clock based.
    s = InfluenceScorer(store=store)

    first = await s.compute_for_paper(n.paper_id)

    # Patch GraphAlgorithms.pagerank: if the second call invokes it,
    # we'll know the cache short-circuit failed.
    with patch.object(scorer_module.GraphAlgorithms, "pagerank") as mock_pr:
        second = await s.compute_for_paper(n.paper_id)
    mock_pr.assert_not_called()
    # Cached values returned verbatim.
    assert second.pagerank_score == first.pagerank_score
    assert second.citation_velocity == first.citation_velocity
    assert second.computed_at == first.computed_at


@pytest.mark.asyncio
async def test_persistence_cache_miss_after_ttl_recomputes(store):
    n = _node("c2", citation_count=5, year=2020)
    _persist_chain(store, n)

    initial_now = datetime(2025, 1, 1, tzinfo=timezone.utc)
    s_initial = _frozen_scorer(store, initial_now)
    first = await s_initial.compute_for_paper(n.paper_id)
    assert first.computed_at == initial_now

    # Advance "now" past the 7-day TTL.
    later = initial_now + DEFAULT_CACHE_TTL + timedelta(seconds=1)
    s_later = _frozen_scorer(store, later)
    with patch.object(
        scorer_module.GraphAlgorithms,
        "pagerank",
        wraps=scorer_module.GraphAlgorithms.pagerank,
    ) as mock_pr:
        second = await s_later.compute_for_paper(n.paper_id)
    mock_pr.assert_called_once()
    assert second.computed_at == later


@pytest.mark.asyncio
async def test_persistence_cache_miss_when_no_row(store):
    """Compute path runs when no cache row exists yet."""
    n = _node("c3", citation_count=2, year=2020)
    _persist_chain(store, n)
    s = InfluenceScorer(store=store)
    metrics = await s.compute_for_paper(n.paper_id)
    assert metrics.citation_count == 2


# ---------------------------------------------------------------------------
# Bulk path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_for_graph_bulk_efficient(store):
    """One PageRank invocation covers all requested nodes."""
    nodes = [_node(f"b{i}", citation_count=i, year=2020) for i in range(5)]
    _persist_chain(store, *nodes)
    s = InfluenceScorer(store=store)

    with patch.object(
        scorer_module.GraphAlgorithms,
        "pagerank",
        wraps=scorer_module.GraphAlgorithms.pagerank,
    ) as mock_pr:
        out = await s.compute_for_graph([n.paper_id for n in nodes])

    mock_pr.assert_called_once()
    assert len(out) == 5
    assert {m.paper_id for m in out} == {n.paper_id for n in nodes}


@pytest.mark.asyncio
async def test_compute_for_graph_empty_input(store):
    s = InfluenceScorer(store=store)
    assert await s.compute_for_graph([]) == []


@pytest.mark.asyncio
async def test_compute_for_graph_includes_unknown_node_with_zeros(store):
    n = _node("known", citation_count=2, year=2020)
    _persist_chain(store, n)
    s = InfluenceScorer(store=store)

    ghost_id = make_paper_node_id("s2", "ghost")
    out = await s.compute_for_graph([n.paper_id, ghost_id])
    assert len(out) == 2
    ghost = next(m for m in out if m.paper_id == ghost_id)
    assert ghost.citation_count == 0
    assert ghost.citation_velocity == 0.0


@pytest.mark.asyncio
async def test_compute_for_paper_unknown_node_returns_baseline(store):
    """compute_for_paper for an unknown id returns baseline metrics."""
    s = InfluenceScorer(store=store)
    out = await s.compute_for_paper(make_paper_node_id("s2", "ghost2"))
    assert out.citation_count == 0
    # PageRank dict will not contain ghost → 0.0
    assert out.pagerank_score == 0.0


# ---------------------------------------------------------------------------
# Cache write failure (audit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_write_failure_logs_event_but_returns_metrics(store, monkeypatch):
    """A repository write failure must NOT bubble to the scorer caller.

    The new repository owns the failure-path logging; the scorer just
    delegates. Verify that when ``open_connection`` raises a non-contention
    ``sqlite3.Error`` on BEGIN IMMEDIATE (propagates straight through the
    retry helper, lands in the repo's outer ``try``, is logged via
    ``citation_influence_repo_write_failed``, and is swallowed) the scorer
    caller still receives its in-memory metrics.

    Mirrors ``test_record_metrics_propagates_non_lock_sqlite_error`` in
    ``test_influence_repository.py`` -- patches ``open_connection`` with
    a non-BUSY error so the full retry/failure path is exercised rather
    than bypassing ``retry_on_lock_contention`` via a private-method patch.
    """
    n = _node("cw", citation_count=1, year=2020)
    _persist_chain(store, n)

    repo = CitationInfluenceRepository.from_path(store.db_path)
    monkeypatch.setattr(repo_module, "logger", structlog.get_logger())

    from contextlib import contextmanager
    from pathlib import Path
    from src.storage.intelligence_graph import connection as conn_mod_scorer

    real_open = conn_mod_scorer.open_connection
    write_attempts: list[int] = []

    class _FailProxy:
        def __init__(self, real_conn: sqlite3.Connection) -> None:
            self._real = real_conn

        def execute(self, sql: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if sql == "BEGIN IMMEDIATE":
                write_attempts.append(1)
                raise sqlite3.OperationalError("disk full")
            return self._real.execute(sql, *args, **kwargs)

        def executemany(  # type: ignore[no-untyped-def]
            self, sql: str, *args, **kwargs
        ):
            return self._real.executemany(sql, *args, **kwargs)

        def commit(self) -> None:
            self._real.commit()

        def rollback(self) -> None:
            self._real.rollback()

    @contextmanager
    def fake_open(p: Path):  # type: ignore[no-untyped-def]
        with real_open(p) as conn:
            yield _FailProxy(conn)

    monkeypatch.setattr(repo_module, "open_connection", fake_open)
    s = InfluenceScorer(store=store, repo=repo)

    with structlog.testing.capture_logs() as logs:
        metrics = await s.compute_for_paper(n.paper_id)
    # Caller still receives in-memory metrics.
    assert metrics.paper_id == n.paper_id
    # Repo's failure-path event must be present.
    assert any(e.get("event") == "citation_influence_repo_write_failed" for e in logs)


# ---------------------------------------------------------------------------
# Async wrapping (issue #134)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_for_paper_wraps_writes_in_to_thread(store, monkeypatch):
    """``record_metrics`` is sync (uses ``time.sleep`` for retry); the
    scorer MUST wrap it in ``asyncio.to_thread`` so contention backoff
    does not block the event loop. Spy on ``asyncio.to_thread`` to
    confirm the write goes through the thread pool.
    """
    n = _node("at1", citation_count=1, year=2020)
    _persist_chain(store, n)

    repo = CitationInfluenceRepository.from_path(store.db_path)
    s = InfluenceScorer(store=store, repo=repo)

    record_calls: list[object] = []
    real_to_thread = scorer_module.asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        # Bound-method identity (``func is repo.record_metrics``) is
        # unreliable because Python rebuilds the bound method on every
        # attribute access; compare ``__func__`` against the unbound
        # method instead.
        underlying = getattr(func, "__func__", func)
        if underlying is CitationInfluenceRepository.record_metrics:
            record_calls.append(args[0])
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(scorer_module.asyncio, "to_thread", spy_to_thread)
    await s.compute_for_paper(n.paper_id)
    # The repo's record_metrics was invoked exactly once via
    # asyncio.to_thread.
    assert len(record_calls) == 1
    assert record_calls[0].paper_id == n.paper_id


@pytest.mark.asyncio
async def test_compute_for_paper_wraps_reads_in_to_thread(store, monkeypatch):
    """``get_metrics`` is sync; the scorer MUST wrap the cache lookup
    in ``asyncio.to_thread`` for the same reason -- a colliding writer
    could hold the lock long enough to matter on the read path too.
    """
    n = _node("at2", citation_count=1, year=2020)
    _persist_chain(store, n)

    repo = CitationInfluenceRepository.from_path(store.db_path)
    s = InfluenceScorer(store=store, repo=repo)

    get_calls: list[object] = []
    real_to_thread = scorer_module.asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        underlying = getattr(func, "__func__", func)
        if underlying is CitationInfluenceRepository.get_metrics:
            get_calls.append(args[0])
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(scorer_module.asyncio, "to_thread", spy_to_thread)
    await s.compute_for_paper(n.paper_id)
    # The repo's get_metrics was invoked exactly once via
    # asyncio.to_thread.
    assert get_calls == [n.paper_id]


@pytest.mark.asyncio
async def test_compute_for_graph_wraps_each_write_in_to_thread(store, monkeypatch):
    """``compute_for_graph`` writes one row per requested paper -- each
    must be wrapped in ``asyncio.to_thread``.
    """
    nodes = [_node(f"atg{i}", citation_count=i, year=2020) for i in range(3)]
    _persist_chain(store, *nodes)

    repo = CitationInfluenceRepository.from_path(store.db_path)
    s = InfluenceScorer(store=store, repo=repo)

    record_calls: list[object] = []
    real_to_thread = scorer_module.asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        underlying = getattr(func, "__func__", func)
        if underlying is CitationInfluenceRepository.record_metrics:
            record_calls.append(args[0])
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(scorer_module.asyncio, "to_thread", spy_to_thread)
    await s.compute_for_graph([n.paper_id for n in nodes])
    assert len(record_calls) == 3
    assert {m.paper_id for m in record_calls} == {n.paper_id for n in nodes}


@pytest.mark.asyncio
async def test_compute_for_paper_uses_repo_get_metrics(store):
    """The cache hit path must come from ``repo.get_metrics`` -- not
    a private scorer method. Inject a mock repo whose ``get_metrics``
    returns a recognizable sentinel and verify the scorer returns
    that exact instance.
    """
    n = _node("rg", citation_count=1, year=2020)
    _persist_chain(store, n)

    sentinel = InfluenceMetrics(
        paper_id=n.paper_id,
        citation_count=999,
        citation_velocity=88.0,
        pagerank_score=0.42,
        hub_score=0.5,
        authority_score=0.6,
        computed_at=datetime.now(timezone.utc),
    )
    mock_repo = MagicMock(spec=CitationInfluenceRepository)
    mock_repo.get_metrics.return_value = sentinel
    s = InfluenceScorer(store=store, repo=mock_repo)

    out = await s.compute_for_paper(n.paper_id)
    assert out is sentinel
    mock_repo.get_metrics.assert_called_once_with(n.paper_id, s._max_age_days())
    # Cache HIT path: record_metrics must NOT be called.
    mock_repo.record_metrics.assert_not_called()


@pytest.mark.asyncio
async def test_compute_for_paper_calls_repo_record_metrics_on_miss(store):
    """On cache miss the scorer must call ``repo.record_metrics`` --
    not any private write method on itself. Inject a mock repo that
    returns ``None`` (miss) and verify ``record_metrics`` is invoked.
    """
    n = _node("rm", citation_count=2, year=2020)
    _persist_chain(store, n)

    mock_repo = MagicMock(spec=CitationInfluenceRepository)
    mock_repo.get_metrics.return_value = None  # cache miss
    s = InfluenceScorer(store=store, repo=mock_repo)

    out = await s.compute_for_paper(n.paper_id)
    mock_repo.record_metrics.assert_called_once()
    written = mock_repo.record_metrics.call_args.args[0]
    assert written.paper_id == n.paper_id
    # Returned metrics match what was just written.
    assert out.paper_id == n.paper_id


# ---------------------------------------------------------------------------
# InfluenceMetrics model
# ---------------------------------------------------------------------------


def test_influence_metrics_defaults():
    m = InfluenceMetrics(paper_id="paper:s2:x")
    assert m.citation_count == 0
    assert m.citation_velocity == 0.0
    assert m.pagerank_score == 0.0
    assert m.hub_score == 0.0
    assert m.authority_score == 0.0
    assert isinstance(m.computed_at, datetime)


def test_influence_metrics_pagerank_clamped_to_one():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="pagerank_score"):
        InfluenceMetrics(paper_id="paper:s2:x", pagerank_score=1.5)


def test_influence_metrics_rejects_extra_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InfluenceMetrics(paper_id="paper:s2:x", foo=1)


# ---------------------------------------------------------------------------
# PageRank score clamp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagerank_score_clamped_to_one(store, monkeypatch):
    """If GraphAlgorithms.pagerank returns >1.0, the scorer clamps to 1.0."""
    n = _node("p", citation_count=1, year=2020)
    _persist_chain(store, n)

    def fake_pagerank(*args, **kwargs):
        return {n.paper_id: 5.0}  # pathological

    monkeypatch.setattr(scorer_module.GraphAlgorithms, "pagerank", fake_pagerank)

    s = InfluenceScorer(store=store)
    metrics = await s.compute_for_paper(n.paper_id)
    assert metrics.pagerank_score == 1.0


@pytest.mark.asyncio
async def test_pagerank_score_clamped_to_zero(store, monkeypatch):
    n = _node("pn", citation_count=1, year=2020)
    _persist_chain(store, n)

    def fake_pagerank(*args, **kwargs):
        return {n.paper_id: -0.1}

    monkeypatch.setattr(scorer_module.GraphAlgorithms, "pagerank", fake_pagerank)

    s = InfluenceScorer(store=store)
    metrics = await s.compute_for_paper(n.paper_id)
    assert metrics.pagerank_score == 0.0


# ---------------------------------------------------------------------------
# Constants surface
# ---------------------------------------------------------------------------


def test_module_constants():
    assert MAX_GRAPH_NODES_FOR_HITS == 10_000
    assert DEFAULT_CACHE_TTL == timedelta(days=7)


def test_hits_filters_edges_to_unknown_nodes(store, monkeypatch):
    """An edge whose source/target is not in the queried node set is dropped.

    This exercises the filter branch in _compute_hits — covers the
    false branch of `if source in node_set and target in node_set:`.
    """
    a = _node("a", year=2020)
    b = _node("b", year=2020)
    _persist_chain(store, a, b)

    s = InfluenceScorer(store=store)
    # Inject a phantom edge into the algorithm input by patching
    # _list_edges_by_types to return an extra (ghost, ghost) tuple that
    # is not in the node_set.
    real_list_edges = s.store._list_edges_by_types

    def fake_list_edges(types):
        edges = list(real_list_edges(types))
        edges.append(("paper:s2:ghost1", "paper:s2:ghost2"))
        edges.append(("paper:s2:ghost1", a.paper_id))  # only target valid
        edges.append((a.paper_id, "paper:s2:ghost2"))  # only source valid
        return edges

    monkeypatch.setattr(s.store, "_list_edges_by_types", fake_list_edges)
    hubs, authorities = s._compute_hits()
    # Only the valid a -> b edge contributed; ghost edges were filtered.
    assert authorities[b.paper_id] > 0
    assert "paper:s2:ghost1" not in hubs


def test_hits_runs_all_iterations_without_convergence(store, monkeypatch):
    """Force HITS to skip the early-break: convergence threshold = -inf.

    Covers the loop-exit-without-break branch of the for/range loop.
    """
    a = _node("a", year=2020)
    b = _node("b", year=2020)
    _persist_chain(store, a, b)

    # Cap iterations at 1 so we exit the loop normally (no break) and
    # set epsilon to -1 so the convergence test never fires.
    monkeypatch.setattr(scorer_module, "_HITS_MAX_ITERATIONS", 1)
    monkeypatch.setattr(scorer_module, "_HITS_EPSILON", -1.0)

    s = InfluenceScorer(store=store)
    hubs, authorities = s._compute_hits()
    # We exited via "all iterations done" (no break). The function must
    # still return well-formed score vectors.
    assert set(hubs.keys()) == {a.paper_id, b.paper_id}
    assert set(authorities.keys()) == {a.paper_id, b.paper_id}


# ---------------------------------------------------------------------------
# H-S2: PageRank node-count gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagerank_skipped_when_graph_exceeds_limit(store, monkeypatch):
    """PageRank must be skipped and an audit event emitted when graph is too large.

    Monkeypatch MAX_GRAPH_NODES_FOR_PAGERANK to 2, insert 3 nodes, verify the
    warning is logged and the returned pagerank_score is 0.0 (empty dict fallback).
    """
    # Rebind logger before capture_logs() so the cached production
    # logger picks up the testing processor swap (mirrors line 302 pattern
    # from test_hits_skipped_for_oversize_graph_logs_event).
    monkeypatch.setattr(scorer_module, "logger", structlog.get_logger())
    # Lower the limit so 3 nodes trip it.
    monkeypatch.setattr(scorer_module, "MAX_GRAPH_NODES_FOR_PAGERANK", 2)

    a = _node("a", year=2020)
    b = _node("b", year=2020)
    c = _node("c", year=2020)
    _persist_chain(store, a, b)
    # Insert c separately (no edge needed — we just need the node count to hit 3)
    store.add_nodes_batch([c.to_graph_node()])

    s = InfluenceScorer(store=store)
    with structlog.testing.capture_logs() as logs:
        metrics_list = await s.compute_for_graph([a.paper_id, b.paper_id, c.paper_id])

    # The PageRank skip event must have been emitted.
    skip_events = [
        e
        for e in logs
        if e.get("event") == "influence_scorer_pagerank_skipped_oversize_graph"
    ]
    assert len(skip_events) == 1
    assert skip_events[0]["node_count"] == 3
    assert skip_events[0]["limit"] == 2

    # All metrics must still be returned (with pagerank_score == 0.0).
    assert len(metrics_list) == 3
    for m in metrics_list:
        assert m.pagerank_score == 0.0
