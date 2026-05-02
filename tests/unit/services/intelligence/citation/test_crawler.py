"""Tests for CitationCrawler (Issue #127, REQ-9.2.2)."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
import structlog.testing

from src.services.intelligence.citation import crawler as crawler_module
from src.services.intelligence.citation.crawler import (
    CitationCrawler,
    CrawlConfig,
    CrawlDirection,
    CrawlResult,
    sort_by_influence,
)
from src.services.intelligence.citation.models import (
    CitationEdge,
    CitationNode,
    make_paper_node_id,
)
from src.services.intelligence.citation.openalex_client import (
    OpenAlexCitationClient,
)
from src.services.intelligence.citation.semantic_scholar_client import (
    SemanticScholarCitationClient,
)
from src.services.intelligence.models import GraphStoreError
from src.services.providers.base import APIError
from src.storage.intelligence_graph import SQLiteGraphStore

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _node(
    raw_id: str,
    *,
    citation_count: int = 0,
    influential_citation_count: Optional[int] = None,
    year: Optional[int] = None,
    publication_date: Optional[date] = None,
    title: Optional[str] = None,
) -> CitationNode:
    return CitationNode(
        paper_id=make_paper_node_id("s2", raw_id),
        title=title or f"Paper {raw_id}",
        external_ids={"s2": raw_id},
        citation_count=citation_count,
        influential_citation_count=influential_citation_count,
        year=year,
        publication_date=publication_date,
    )


def _edge(citing: CitationNode, cited: CitationNode) -> CitationEdge:
    return CitationEdge(
        citing_paper_id=citing.paper_id,
        cited_paper_id=cited.paper_id,
        source="semantic_scholar",
    )


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


@pytest.fixture
def s2_client():
    return AsyncMock(spec=SemanticScholarCitationClient)


@pytest.fixture
def oa_client():
    return AsyncMock(spec=OpenAlexCitationClient)


@pytest.fixture
def crawler(store, s2_client):
    return CitationCrawler(store=store, s2_client=s2_client)


def _wire_references(client, mapping: dict[str, list[CitationNode]]) -> None:
    """Configure ``client.get_references`` to return per-id results."""

    async def _impl(paper_id, *args, **kwargs):
        seed = _node(paper_id.split(":")[-1] if ":" in paper_id else paper_id)
        related = mapping.get(paper_id, [])
        edges = [_edge(seed, n) for n in related]
        return seed, related, edges

    client.get_references.side_effect = _impl


def _wire_citations(client, mapping: dict[str, list[CitationNode]]) -> None:
    """Configure ``client.get_citations`` to return per-id results."""

    async def _impl(paper_id, *args, **kwargs):
        seed = _node(paper_id.split(":")[-1] if ":" in paper_id else paper_id)
        related = mapping.get(paper_id, [])
        edges = [_edge(n, seed) for n in related]
        return seed, related, edges

    client.get_citations.side_effect = _impl


# ---------------------------------------------------------------------------
# Constructor / factory
# ---------------------------------------------------------------------------


def test_constructor_requires_at_least_one_client(store):
    with pytest.raises(ValueError, match="at least one provider"):
        CitationCrawler(store=store)


def test_from_paths_factory_initialises_store(temp_db, s2_client):
    c = CitationCrawler.from_paths(db_path=temp_db, s2_client=s2_client)
    assert isinstance(c.store, SQLiteGraphStore)
    assert c.s2_client is s2_client


def test_from_paths_factory_defaults_to_s2_client(temp_db, monkeypatch):
    """When no client is provided, the factory builds a default S2 client."""
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "test-key")
    c = CitationCrawler.from_paths(db_path=temp_db)
    assert isinstance(c.s2_client, SemanticScholarCitationClient)


def test_from_paths_factory_accepts_only_openalex(temp_db, oa_client):
    c = CitationCrawler.from_paths(
        db_path=temp_db, s2_client=None, openalex_client=oa_client
    )
    assert c.s2_client is None
    assert c.openalex_client is oa_client


# ---------------------------------------------------------------------------
# Seed validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_invalid_seed_id_raises(crawler):
    with pytest.raises(ValueError, match="Invalid seed_paper_id"):
        await crawler.crawl("bad seed!", CrawlConfig())


@pytest.mark.asyncio
async def test_crawl_empty_seed_id_raises(crawler):
    with pytest.raises(ValueError, match="non-empty"):
        await crawler.crawl("   ", CrawlConfig())


@pytest.mark.asyncio
async def test_crawl_oversized_seed_id_raises(crawler):
    with pytest.raises(ValueError, match="exceeds max"):
        await crawler.crawl("a" * 600, CrawlConfig())


@pytest.mark.asyncio
async def test_crawl_non_string_seed_id_raises(crawler):
    with pytest.raises(ValueError, match="non-empty string"):
        await crawler.crawl(None, CrawlConfig())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Empty / zero-neighbour case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_seed_with_zero_neighbors_returns_empty_result(crawler, s2_client):
    _wire_references(s2_client, {"seed1": []})
    _wire_citations(s2_client, {"seed1": []})

    result = await crawler.crawl("seed1", CrawlConfig())
    assert isinstance(result, CrawlResult)
    assert result.papers_visited == 0
    assert result.edges_added == 0
    assert result.api_calls_made == 2  # one per direction (BOTH)
    assert result.budget_exhausted is False
    assert result.persistence_aborted is False


# ---------------------------------------------------------------------------
# Depth gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_depth_limit(crawler, s2_client, store):
    """max_depth=2: the seed expands → its children expand → grandchildren do NOT."""
    seed_refs = [_node("L1")]
    l1_refs = [_node("L2")]
    l2_refs = [_node("L3")]  # this should never be visited
    _wire_references(
        s2_client,
        {
            "seed": seed_refs,
            seed_refs[0].paper_id: l1_refs,
            l1_refs[0].paper_id: l2_refs,
        },
    )

    config = CrawlConfig(max_depth=2, direction=CrawlDirection.BACKWARD)
    result = await crawler.crawl("seed", config)

    # Two papers visited (L1, L2). L3 must not appear.
    assert result.papers_visited == 2
    assert result.levels_reached == 2
    assert store.get_node(l1_refs[0].paper_id) is not None
    assert store.get_node(l2_refs[0].paper_id) is None


@pytest.mark.asyncio
async def test_crawl_max_depth_one_visits_only_first_layer(crawler, s2_client):
    seed_refs = [_node("L1a"), _node("L1b")]
    l1a_refs = [_node("L2a")]
    _wire_references(
        s2_client,
        {
            "seed": seed_refs,
            seed_refs[0].paper_id: l1a_refs,
        },
    )

    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BACKWARD)
    result = await crawler.crawl("seed", config)

    assert result.papers_visited == 2  # both L1 nodes
    assert result.levels_reached == 1
    # Only the seed got expanded, not L1a → exactly 1 API call.
    assert result.api_calls_made == 1


# ---------------------------------------------------------------------------
# Direction filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_direction_forward_only(crawler, s2_client):
    """FORWARD: only get_citations is called; get_references is never invoked."""
    cites = [_node("citer1")]
    _wire_citations(s2_client, {"seed": cites})

    config = CrawlConfig(max_depth=1, direction=CrawlDirection.FORWARD)
    result = await crawler.crawl("seed", config)

    assert result.papers_visited == 1
    s2_client.get_citations.assert_awaited()
    s2_client.get_references.assert_not_awaited()


@pytest.mark.asyncio
async def test_crawl_direction_backward_only(crawler, s2_client):
    refs = [_node("ref1")]
    _wire_references(s2_client, {"seed": refs})

    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BACKWARD)
    result = await crawler.crawl("seed", config)

    assert result.papers_visited == 1
    s2_client.get_references.assert_awaited()
    s2_client.get_citations.assert_not_awaited()


@pytest.mark.asyncio
async def test_crawl_direction_both(crawler, s2_client):
    refs = [_node("ref1")]
    cites = [_node("citer1")]
    _wire_references(s2_client, {"seed": refs})
    _wire_citations(s2_client, {"seed": cites})

    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BOTH)
    result = await crawler.crawl("seed", config)

    assert result.papers_visited == 2
    s2_client.get_references.assert_awaited()
    s2_client.get_citations.assert_awaited()


# ---------------------------------------------------------------------------
# Top-K + ranking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_top_k_per_level(crawler, s2_client, store):
    """100 candidates with max_papers_per_level=50 → only top 50 by influence."""
    candidates = [
        _node(f"c{i}", influential_citation_count=i, citation_count=i)
        for i in range(100)
    ]
    _wire_references(s2_client, {"seed": candidates})

    config = CrawlConfig(
        max_depth=1,
        max_papers_per_level=50,
        direction=CrawlDirection.BACKWARD,
    )
    result = await crawler.crawl("seed", config)
    assert result.papers_visited == 50
    # Top 50 by influential_citation_count = ids 50..99
    for i in range(50, 100):
        assert store.get_node(make_paper_node_id("s2", f"c{i}")) is not None
    for i in range(0, 50):
        assert store.get_node(make_paper_node_id("s2", f"c{i}")) is None


def test_sort_by_influence_ranking_exact():
    """Pin the (influential, citations, date) ordering precisely."""
    a = _node(
        "a",
        influential_citation_count=10,
        citation_count=100,
        publication_date=date(2020, 1, 1),
    )
    b = _node(
        "b",
        influential_citation_count=10,
        citation_count=200,
        publication_date=date(2019, 1, 1),
    )
    c = _node(
        "c",
        influential_citation_count=20,
        citation_count=5,
        publication_date=date(2010, 1, 1),
    )
    d = _node(
        "d",
        influential_citation_count=10,
        citation_count=200,
        publication_date=date(2021, 1, 1),
    )
    # Year-only fallback (no publication_date) should be treated as Jan-1.
    e = _node("e", influential_citation_count=5, citation_count=300, year=2023)
    # Missing year + missing date → date.min, sorts last among same scores.
    f = _node("f", influential_citation_count=5, citation_count=300)

    ranked = sort_by_influence([a, b, c, d, e, f])
    # Expected order:
    # c (influential=20)
    # then influential=10 group, ordered by citations desc, date desc:
    #   d (200, 2021), b (200, 2019), a (100, 2020)
    # then influential=5 group, ordered by citations desc, date desc:
    #   e (300, 2023-1-1), f (300, date.min)
    assert [n.paper_id.split(":")[-1] for n in ranked] == [
        "c",
        "d",
        "b",
        "a",
        "e",
        "f",
    ]


def test_sort_by_influence_handles_none_influential_as_zero():
    a = _node("a", influential_citation_count=None, citation_count=10)
    b = _node("b", influential_citation_count=0, citation_count=5)
    ranked = sort_by_influence([a, b])
    # Both have influential=0 → tiebreak on citations desc → a first.
    assert ranked[0].paper_id.endswith("a")


# ---------------------------------------------------------------------------
# Visited dedupe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_visited_dedupe(crawler, s2_client, store):
    """The same paper appearing as a neighbour in two chains is visited once."""
    shared = _node("shared")
    a = _node("a")
    b = _node("b")
    _wire_references(
        s2_client,
        {
            "seed": [a, b],
            a.paper_id: [shared],
            b.paper_id: [shared],
        },
    )

    config = CrawlConfig(max_depth=2, direction=CrawlDirection.BACKWARD)
    result = await crawler.crawl("seed", config)

    # a, b, shared = 3 unique nodes.
    assert result.papers_visited == 3
    # ``shared`` was returned by both a and b but is only enqueued once.
    # After a's expansion adds it (depth=2), b's expansion finds it
    # already-visited and doesn't re-enqueue. depth=2 is at the cap so
    # ``shared`` is never expanded itself — verify by checking
    # get_references was called for seed, a, b only (3 calls).
    refs_calls = s2_client.get_references.await_count
    assert refs_calls == 3


# ---------------------------------------------------------------------------
# Budget cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_budget_cap_emits_event_and_stops(crawler, s2_client, monkeypatch):
    """Cap MAX_API_CALLS_PER_CRAWL=2 → crawl stops after 2 calls + emits event."""
    monkeypatch.setattr(crawler_module, "MAX_API_CALLS_PER_CRAWL", 2)
    # Ensure the production logger picks up the patched processor swap
    # used by capture_logs (see CLAUDE.md: cache_logger_on_first_use=True).
    monkeypatch.setattr(crawler_module, "logger", structlog.get_logger())

    # Seed → 5 children, each with their own children. With BACKWARD only
    # and budget=2, we expand seed (1 call) + L1[0] (2 calls), then exit.
    children = [_node(f"L1_{i}") for i in range(5)]
    grandchildren = [_node(f"L2_{i}") for i in range(3)]
    mapping = {
        "seed": children,
        children[0].paper_id: grandchildren,
        children[1].paper_id: grandchildren,
        children[2].paper_id: grandchildren,
    }
    _wire_references(s2_client, mapping)

    config = CrawlConfig(max_depth=3, direction=CrawlDirection.BACKWARD)
    with structlog.testing.capture_logs() as logs:
        result = await crawler.crawl("seed", config)

    assert result.budget_exhausted is True
    assert result.api_calls_made == 2
    # Expanded only seed + first L1.
    assert s2_client.get_references.await_count == 2
    events = [e.get("event") for e in logs]
    assert "citation_crawl_budget_exhausted" in events


@pytest.mark.asyncio
async def test_crawl_budget_cap_mid_both_direction(store, s2_client, monkeypatch):
    """BOTH direction: budget hit between BACKWARD and FORWARD on same paper."""
    monkeypatch.setattr(crawler_module, "MAX_API_CALLS_PER_CRAWL", 1)
    monkeypatch.setattr(crawler_module, "logger", structlog.get_logger())

    _wire_references(s2_client, {"seed": [_node("a")]})
    _wire_citations(s2_client, {"seed": [_node("b")]})

    crawler = CitationCrawler(store=store, s2_client=s2_client)
    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BOTH)
    with structlog.testing.capture_logs() as logs:
        result = await crawler.crawl("seed", config)

    # First call (BACKWARD) succeeds; FORWARD hits budget.
    assert result.budget_exhausted is True
    assert result.api_calls_made == 1
    # No persistence happened because budget hit before we tried to
    # finalise the layer.
    assert any(e.get("event") == "citation_crawl_budget_exhausted" for e in logs)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_filter_min_citations(crawler, s2_client, store):
    keepers = [_node("k1", citation_count=10), _node("k2", citation_count=20)]
    droppers = [_node("d1", citation_count=0), _node("d2", citation_count=4)]
    _wire_references(s2_client, {"seed": keepers + droppers})

    config = CrawlConfig(
        max_depth=1,
        direction=CrawlDirection.BACKWARD,
        filter_min_citations=5,
    )
    result = await crawler.crawl("seed", config)

    assert result.papers_visited == 2
    # C-3: dropped counters are now per-direction (backward here)
    assert result.dropped_by_filter["min_citations_backward"] == 2
    for k in keepers:
        assert store.get_node(k.paper_id) is not None
    for d in droppers:
        assert store.get_node(d.paper_id) is None


@pytest.mark.asyncio
async def test_crawl_filter_year_min(crawler, s2_client, store):
    new_paper = _node("new", year=2022, citation_count=1)
    old_paper = _node("old", year=2010, citation_count=1)
    no_year = _node("noyear", citation_count=1)  # year=None
    _wire_references(s2_client, {"seed": [new_paper, old_paper, no_year]})

    config = CrawlConfig(
        max_depth=1,
        direction=CrawlDirection.BACKWARD,
        filter_year_min=2020,
    )
    result = await crawler.crawl("seed", config)

    assert result.papers_visited == 1
    # C-3: dropped counters are now per-direction (backward here)
    assert result.dropped_by_filter["year_min_backward"] == 2
    assert store.get_node(new_paper.paper_id) is not None
    assert store.get_node(old_paper.paper_id) is None
    assert store.get_node(no_year.paper_id) is None


# ---------------------------------------------------------------------------
# Failure semantics — provider failure (fail-soft)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_provider_failure_skips_node(
    crawler, s2_client, store, monkeypatch
):
    monkeypatch.setattr(crawler_module, "logger", structlog.get_logger())

    # Seed expands fine; one of its children raises on expansion.
    a = _node("a")
    b = _node("b")
    a_refs = [_node("a_ref")]

    async def refs_impl(paper_id, *args, **kwargs):
        if paper_id == "seed":
            return (
                _node("seed"),
                [a, b],
                [_edge(_node("seed"), a), _edge(_node("seed"), b)],
            )
        if paper_id == a.paper_id:
            return _node("a"), a_refs, [_edge(a, a_refs[0])]
        if paper_id == b.paper_id:
            raise APIError("boom on b")
        return _node(paper_id), [], []

    s2_client.get_references.side_effect = refs_impl

    config = CrawlConfig(max_depth=2, direction=CrawlDirection.BACKWARD)
    with structlog.testing.capture_logs() as logs:
        result = await crawler.crawl("seed", config)

    # a + b at L1, a_ref at L2 = 3 visited despite b's failure.
    assert result.papers_visited == 3
    skip_events = [
        e
        for e in logs
        if e.get("event") == "citation_crawl_provider_failed_skipping_node"
    ]
    assert len(skip_events) == 1
    assert skip_events[0].get("paper_id") == b.paper_id
    # H-S1: error is repr(str(exc)[:512]) — check message content is present
    assert "boom on b" in skip_events[0].get("error", "")


# ---------------------------------------------------------------------------
# Failure semantics — persistence failure (fail-hard, abort)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_persistence_failure_aborts_cycle(s2_client, monkeypatch):
    """Persistence error must abort BFS and skip subsequent API calls."""
    # Real store wrapped in a Mock so add_nodes_batch raises on first call.
    fake_store = MagicMock()
    fake_store.add_nodes_batch.side_effect = GraphStoreError("disk full")
    fake_store.add_edges_batch = MagicMock()

    monkeypatch.setattr(crawler_module, "logger", structlog.get_logger())

    # Seed → two children, each with their own children. We must NOT
    # see any get_references call for the children after persistence
    # fails on the seed's expansion.
    a = _node("a")
    b = _node("b")
    _wire_references(
        s2_client,
        {
            "seed": [a, b],
            a.paper_id: [_node("aa")],
            b.paper_id: [_node("bb")],
        },
    )

    crawler = CitationCrawler(store=fake_store, s2_client=s2_client)
    config = CrawlConfig(max_depth=3, direction=CrawlDirection.BACKWARD)
    with structlog.testing.capture_logs() as logs:
        result = await crawler.crawl("seed", config)

    assert result.persistence_aborted is True
    abort_events = [
        e
        for e in logs
        if e.get("event") == "citation_crawl_persistence_failed_aborting"
    ]
    assert len(abort_events) == 1
    assert "disk full" in abort_events[0].get("error", "")
    # Critical: only the seed's expansion happened. Children were NOT
    # expanded. This is the negative-path test required by GEMINI.md §5.
    assert s2_client.get_references.await_count == 1


@pytest.mark.asyncio
async def test_crawl_persistence_edge_failure_aborts(s2_client, monkeypatch):
    """Edge insert failure (after node insert succeeds) also aborts."""
    fake_store = MagicMock()
    fake_store.add_nodes_batch = MagicMock()
    fake_store.add_edges_batch.side_effect = GraphStoreError("fk violation")

    monkeypatch.setattr(crawler_module, "logger", structlog.get_logger())

    _wire_references(
        s2_client,
        {
            "seed": [_node("a")],
            make_paper_node_id("s2", "a"): [_node("aa")],
        },
    )

    crawler = CitationCrawler(store=fake_store, s2_client=s2_client)
    config = CrawlConfig(max_depth=3, direction=CrawlDirection.BACKWARD)
    result = await crawler.crawl("seed", config)
    assert result.persistence_aborted is True
    assert s2_client.get_references.await_count == 1


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_concurrency_bound_via_semaphore(store, s2_client):
    """In-flight provider calls must never exceed _MAX_CONCURRENT_REQUESTS."""
    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def slow_refs(paper_id, *args, **kwargs):
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        # Yield enough times to allow other coroutines to enter.
        await asyncio.sleep(0)
        async with lock:
            in_flight -= 1
        return _node(paper_id), [], []

    s2_client.get_references.side_effect = slow_refs
    s2_client.get_citations.side_effect = slow_refs

    crawler = CitationCrawler(store=store, s2_client=s2_client)
    # Build a wide first layer so many expansions are queued.
    children = [_node(f"c{i}") for i in range(30)]

    async def seed_refs(paper_id, *args, **kwargs):
        if paper_id == "seed":
            return _node("seed"), children, []
        return _node(paper_id), [], []

    s2_client.get_references.side_effect = seed_refs

    # First trigger the wide expansion, then re-wire to slow_refs and
    # spawn many concurrent gathers manually for the bound check.
    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BACKWARD)
    await crawler.crawl("seed", config)

    # Now exercise the semaphore directly via _expand_paper.
    s2_client.get_references.side_effect = slow_refs
    counter = CrawlResult()
    sem = asyncio.Semaphore(crawler_module._MAX_CONCURRENT_REQUESTS)
    await asyncio.gather(
        *[
            crawler._expand_paper(
                paper_id=f"p{i}",
                direction=CrawlDirection.BACKWARD,
                semaphore=sem,
                counter=counter,
            )
            for i in range(50)
        ]
    )
    assert peak <= crawler_module._MAX_CONCURRENT_REQUESTS
    assert peak > 0  # sanity: we did exercise concurrency


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def test_crawl_config_defaults_match_spec():
    cfg = CrawlConfig()
    assert cfg.max_depth == 2
    assert cfg.max_papers_per_level == 50
    assert cfg.direction == CrawlDirection.BOTH
    assert cfg.filter_min_citations == 0
    assert cfg.filter_year_min is None


def test_crawl_config_rejects_extra_fields():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CrawlConfig(max_depth=2, foo="bar")


def test_crawl_config_validates_bounds():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CrawlConfig(max_depth=0)
    with pytest.raises(ValidationError):
        CrawlConfig(max_depth=4)
    with pytest.raises(ValidationError):
        CrawlConfig(max_papers_per_level=5)
    with pytest.raises(ValidationError):
        CrawlConfig(max_papers_per_level=300)


def test_crawl_result_defaults():
    r = CrawlResult()
    assert r.papers_visited == 0
    assert r.dropped_by_filter == {}
    assert r.budget_exhausted is False
    assert r.persistence_aborted is False


@pytest.mark.asyncio
async def test_crawl_budget_zero_blocks_first_call(crawler, monkeypatch):
    """MAX=0 → budget check fires before the first BACKWARD call too."""
    monkeypatch.setattr(crawler_module, "MAX_API_CALLS_PER_CRAWL", 0)
    monkeypatch.setattr(crawler_module, "logger", structlog.get_logger())
    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BACKWARD)
    with structlog.testing.capture_logs() as logs:
        result = await crawler.crawl("seed", config)
    assert result.budget_exhausted is True
    assert result.api_calls_made == 0
    assert any(e.get("event") == "citation_crawl_budget_exhausted" for e in logs)


@pytest.mark.asyncio
async def test_crawl_both_dedupes_node_appearing_in_refs_and_cites(
    crawler, s2_client, store
):
    """A paper that is both a reference and a citer appears once in the graph."""
    shared = _node("shared")
    _wire_references(s2_client, {"seed": [shared]})
    _wire_citations(s2_client, {"seed": [shared]})

    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BOTH)
    result = await crawler.crawl("seed", config)
    assert result.papers_visited == 1  # ``shared`` counted once
    assert store.get_node(shared.paper_id) is not None


@pytest.mark.asyncio
async def test_expand_paper_backward_branch_budget_exhausted(crawler, monkeypatch):
    """Direct test: budget hit on the BACKWARD-only entry to _expand_paper."""
    from src.services.intelligence.citation.crawler import _BudgetExhausted

    monkeypatch.setattr(crawler_module, "MAX_API_CALLS_PER_CRAWL", 0)
    counter = CrawlResult()
    sem = asyncio.Semaphore(1)
    with pytest.raises(_BudgetExhausted):
        await crawler._expand_paper(
            paper_id="x",
            direction=CrawlDirection.BACKWARD,
            semaphore=sem,
            counter=counter,
        )


@pytest.mark.asyncio
async def test_crawl_persist_layer_no_op_when_empty(crawler):
    """Direct call to _persist_layer with empty inputs is a true no-op."""
    persisted: set[str] = set()
    ok = crawler._persist_layer(
        paper_id="seed",
        parent_node=None,
        related_nodes=[],
        edges=[],
        seed_paper_id="seed",
        persisted_node_ids=persisted,
    )
    assert ok is True
    assert persisted == set()


# ---------------------------------------------------------------------------
# H-S1: Error message truncation in fail-soft provider path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_provider_error_is_truncated_in_log(crawler, s2_client):
    """A long provider error string must be truncated to ≤512 chars in the log."""
    long_error = "X" * 10_000  # way over 512 chars

    async def refs_fail(paper_id, *args, **kwargs):
        raise APIError(long_error)

    s2_client.get_references.side_effect = refs_fail

    config = CrawlConfig(max_depth=1, direction=CrawlDirection.BACKWARD)
    with structlog.testing.capture_logs() as logs:
        await crawler.crawl("seed", config)

    fail_events = [
        e
        for e in logs
        if e.get("event") == "citation_crawl_provider_failed_skipping_node"
    ]
    assert len(fail_events) == 1
    # repr(str(exc)[:512]) is at most repr("X"*512) = "'XXX...'" (514 chars)
    # but the inner str slice is guaranteed ≤512 chars.
    logged_error = fail_events[0].get("error", "")
    # The repr wrapper adds surrounding quotes, but the inner content is ≤512
    assert len(logged_error) <= 520  # repr overhead is at most ~8 chars


# ---------------------------------------------------------------------------
# C-3: Per-direction top_k (spec REQ-9.2.2 §574-592)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_both_direction_applies_top_k_per_direction(store, s2_client):
    """Each direction gets its own top_k cap, not a shared cap on the union.

    100 refs + 100 cites per expansion, max_papers_per_level=50 → exactly
    50 backward nodes AND 50 forward nodes should be visited (100 total),
    not 50 total split across both directions.
    """
    crawler = CitationCrawler(store=store, s2_client=s2_client)

    bw_nodes = [_node(f"bw{i}", citation_count=i) for i in range(100)]
    fw_nodes = [_node(f"fw{i}", citation_count=i) for i in range(100)]

    async def fake_get_references(paper_id, *args, **kwargs):
        seed = _node("seed")
        return seed, bw_nodes, [_edge(seed, n) for n in bw_nodes]

    async def fake_get_citations(paper_id, *args, **kwargs):
        seed = _node("seed")
        return seed, fw_nodes, [_edge(n, seed) for n in fw_nodes]

    s2_client.get_references.side_effect = fake_get_references
    s2_client.get_citations.side_effect = fake_get_citations

    config = CrawlConfig(
        max_depth=1,
        max_papers_per_level=50,
        direction=CrawlDirection.BOTH,
    )
    result = await crawler.crawl("seed", config)

    # 50 backward + 50 forward = 100 papers visited (not 50 total)
    assert result.papers_visited == 100


@pytest.mark.asyncio
async def test_crawl_both_direction_starvation_regression(store, s2_client):
    """Backward direction must not be starved when forward has many candidates.

    backward=5 candidates, forward=200 candidates, max_papers_per_level=50.
    Under the old union-then-cap logic all 5 backward candidates would be
    dropped (the top-50 from the 205-paper union would all be forward).
    Under the per-direction cap, all 5 backward candidates are preserved.
    """
    crawler = CitationCrawler(store=store, s2_client=s2_client)

    # 5 backward nodes with high citation counts so they'd normally rank well
    bw_nodes = [_node(f"bw{i}", citation_count=1000 + i) for i in range(5)]
    # 200 forward nodes with even higher citation counts to starve backward
    fw_nodes = [_node(f"fw{i}", citation_count=2000 + i) for i in range(200)]

    async def fake_get_references(paper_id, *args, **kwargs):
        seed = _node("seed")
        return seed, bw_nodes, [_edge(seed, n) for n in bw_nodes]

    async def fake_get_citations(paper_id, *args, **kwargs):
        seed = _node("seed")
        return seed, fw_nodes, [_edge(n, seed) for n in fw_nodes]

    s2_client.get_references.side_effect = fake_get_references
    s2_client.get_citations.side_effect = fake_get_citations

    config = CrawlConfig(
        max_depth=1,
        max_papers_per_level=50,
        direction=CrawlDirection.BOTH,
    )
    result = await crawler.crawl("seed", config)

    # All 5 backward nodes must have been visited; 50 forward nodes
    assert result.papers_visited == 55  # 5 backward + 50 forward
