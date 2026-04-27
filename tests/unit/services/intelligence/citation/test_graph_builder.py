"""Tests for CitationGraphBuilder (Milestone 9.2 — Week 1.5).

Mocked S2 + OpenAlex clients combined with a real ``SQLiteGraphStore``
(tempfile-backed, isolated per test) so persistence + idempotency
behavior is verified end-to-end without any real HTTP traffic.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.services.intelligence.citation.graph_builder import (
    CitationGraphBuilder,
    GraphBuildResult,
)
from src.services.intelligence.citation.models import (
    CitationDirection,
    CitationEdge,
    CitationNode,
    make_citation_edge_id,
    make_paper_node_id,
)
from src.services.intelligence.citation.openalex_client import (
    OpenAlexCitationClient,
)
from src.services.intelligence.citation.semantic_scholar_client import (
    SemanticScholarCitationClient,
)
from src.services.intelligence.models import (
    EdgeType,
    GraphStoreError,
    NodeType,
)
from src.services.providers.base import APIError, RateLimitError
from src.storage.intelligence_graph import SQLiteGraphStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db():
    """Tempfile-backed db path; cleaned up after the test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    try:
        path.unlink()
    except FileNotFoundError:  # pragma: no cover - belt-and-suspenders
        pass


@pytest.fixture
def store(temp_db):
    s = SQLiteGraphStore(temp_db)
    s.initialize()
    return s


@pytest.fixture
def s2_client():
    """Mock S2 client; tests override get_references / get_citations."""
    return AsyncMock(spec=SemanticScholarCitationClient)


@pytest.fixture
def oa_client():
    """Mock OpenAlex client; tests override get_references / get_citations."""
    return AsyncMock(spec=OpenAlexCitationClient)


@pytest.fixture
def builder(store, s2_client, oa_client):
    return CitationGraphBuilder(
        store=store, s2_client=s2_client, openalex_client=oa_client
    )


def _node(provider: str, raw_id: str, **kwargs) -> CitationNode:
    return CitationNode(
        paper_id=make_paper_node_id(provider, raw_id),
        title=kwargs.pop("title", f"Paper {raw_id}"),
        external_ids={provider: raw_id},
        citation_count=kwargs.pop("citation_count", 0),
        reference_count=kwargs.pop("reference_count", 0),
        **kwargs,
    )


def _edge(
    citing: CitationNode, cited: CitationNode, source: str = "s2"
) -> CitationEdge:
    return CitationEdge(
        citing_paper_id=citing.paper_id,
        cited_paper_id=cited.paper_id,
        source=source,
    )


# ---------------------------------------------------------------------------
# Constructor + input validation
# ---------------------------------------------------------------------------


def test_constructor_assigns_dependencies(store, s2_client, oa_client):
    b = CitationGraphBuilder(store, s2_client, oa_client)
    assert b.store is store
    assert b.s2_client is s2_client
    assert b.openalex_client is oa_client


@pytest.mark.asyncio
async def test_build_rejects_depth_other_than_one(builder):
    with pytest.raises(ValueError, match="depth=1 only"):
        await builder.build_for_paper("paper:s2:abc", depth=2)


@pytest.mark.asyncio
async def test_build_rejects_empty_paper_id(builder):
    with pytest.raises(ValueError, match="non-empty"):
        await builder.build_for_paper("", depth=1)


@pytest.mark.asyncio
async def test_build_rejects_whitespace_paper_id(builder):
    with pytest.raises(ValueError, match="non-empty"):
        await builder.build_for_paper("   ", depth=1)


@pytest.mark.asyncio
async def test_build_rejects_zero_max_results(builder):
    with pytest.raises(ValueError, match="max_results must be"):
        await builder.build_for_paper("paper:s2:abc", max_results=0)


# ---------------------------------------------------------------------------
# S2 success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_out_with_s2_success(builder, s2_client, oa_client, store):
    seed = _node("s2", "seed1", citation_count=10, reference_count=2)
    refs = [_node("s2", "ref1"), _node("s2", "ref2")]
    edges = [_edge(seed, refs[0]), _edge(seed, refs[1])]

    s2_client.get_references.return_value = (seed, refs, edges)

    result = await builder.build_for_paper("seed1")

    assert isinstance(result, GraphBuildResult)
    assert result.seed_paper_id == "seed1"
    assert result.nodes_added == 3
    assert result.edges_added == 2
    assert result.provider_used == "s2"
    assert result.errors == []

    s2_client.get_references.assert_awaited_once_with("seed1", max_results=200)
    oa_client.get_references.assert_not_awaited()

    # Verify persistence
    assert store.get_node(seed.paper_id) is not None
    assert store.get_node(refs[0].paper_id) is not None
    edge_id = make_citation_edge_id(seed.paper_id, refs[0].paper_id)
    assert store.get_edge(edge_id) is not None


@pytest.mark.asyncio
async def test_build_in_with_s2_success(builder, s2_client, store):
    seed = _node("s2", "seed1")
    citers = [_node("s2", "cite1")]
    edges = [_edge(citers[0], seed)]

    s2_client.get_citations.return_value = (seed, citers, edges)

    result = await builder.build_for_paper("seed1", direction=CitationDirection.IN)

    assert result.provider_used == "s2"
    assert result.nodes_added == 2
    assert result.edges_added == 1
    s2_client.get_citations.assert_awaited_once_with("seed1", max_results=200)

    # Persisted edge points citer → seed
    edge_id = make_citation_edge_id(citers[0].paper_id, seed.paper_id)
    persisted = store.get_edge(edge_id)
    assert persisted is not None
    assert persisted.source_id == citers[0].paper_id
    assert persisted.target_id == seed.paper_id


@pytest.mark.asyncio
async def test_build_with_zero_related_does_not_fall_back(
    builder, s2_client, oa_client, store
):
    """S2 returns the seed but no references → success, no fallback."""
    seed = _node("s2", "seed1")
    s2_client.get_references.return_value = (seed, [], [])

    result = await builder.build_for_paper("seed1")

    assert result.provider_used == "s2"
    assert result.nodes_added == 1
    assert result.edges_added == 0
    assert result.errors == []
    oa_client.get_references.assert_not_awaited()


@pytest.mark.asyncio
async def test_build_max_results_propagates(builder, s2_client):
    seed = _node("s2", "seed1")
    s2_client.get_references.return_value = (seed, [], [])

    await builder.build_for_paper("seed1", max_results=42)

    s2_client.get_references.assert_awaited_once_with("seed1", max_results=42)


# ---------------------------------------------------------------------------
# Fallback path: S2 fails → OpenAlex
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s2_api_error_falls_back_to_openalex(
    builder, s2_client, oa_client, store
):
    s2_client.get_references.side_effect = APIError("boom")

    seed = _node("openalex", "W1")
    refs = [_node("openalex", "W101")]
    edges = [_edge(seed, refs[0], source="openalex")]
    oa_client.get_references.return_value = (seed, refs, edges)

    result = await builder.build_for_paper("seed1")

    assert result.provider_used == "openalex"
    assert result.nodes_added == 2
    assert result.edges_added == 1
    assert any("s2" in e for e in result.errors)
    oa_client.get_references.assert_awaited_once_with("seed1", max_results=200)


@pytest.mark.asyncio
async def test_s2_rate_limit_falls_back_to_openalex(builder, s2_client, oa_client):
    """RateLimitError is a subclass of APIError → also triggers fallback."""
    s2_client.get_references.side_effect = RateLimitError("slow down")

    seed = _node("openalex", "W1")
    oa_client.get_references.return_value = (seed, [], [])

    result = await builder.build_for_paper("seed1")
    assert result.provider_used == "openalex"


@pytest.mark.asyncio
async def test_both_providers_fail_returns_empty_result(builder, s2_client, oa_client):
    s2_client.get_references.side_effect = APIError("s2 down")
    oa_client.get_references.side_effect = APIError("openalex down")

    result = await builder.build_for_paper("seed1")

    assert result.provider_used == "none"
    assert result.nodes_added == 0
    assert result.edges_added == 0
    assert len(result.errors) == 2
    assert any("s2:" in e for e in result.errors)
    assert any("openalex:" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Direction.BOTH path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_both_directions_success(builder, s2_client, store):
    seed = _node("s2", "seed1")
    refs = [_node("s2", "ref1")]
    citers = [_node("s2", "cite1")]
    out_edges = [_edge(seed, refs[0])]
    in_edges = [_edge(citers[0], seed)]

    s2_client.get_references.return_value = (seed, refs, out_edges)
    s2_client.get_citations.return_value = (seed, citers, in_edges)

    result = await builder.build_for_paper("seed1", direction=CitationDirection.BOTH)

    assert result.provider_used == "s2"
    # seed (1) + ref (1) + citer (1) = 3 unique nodes
    assert result.nodes_added == 3
    # 2 unique edges
    assert result.edges_added == 2

    s2_client.get_references.assert_awaited_once()
    s2_client.get_citations.assert_awaited_once()


@pytest.mark.asyncio
async def test_both_directions_mixed_providers(builder, s2_client, oa_client):
    """OUT succeeds via S2, IN falls back to OpenAlex → provider='both'."""
    seed = _node("s2", "seed1")
    refs = [_node("s2", "ref1")]
    s2_client.get_references.return_value = (seed, refs, [_edge(seed, refs[0])])

    s2_client.get_citations.side_effect = APIError("s2 citations down")
    oa_seed = _node("openalex", "W1")
    citers = [_node("openalex", "W201")]
    oa_client.get_citations.return_value = (
        oa_seed,
        citers,
        [_edge(citers[0], oa_seed, source="openalex")],
    )

    result = await builder.build_for_paper("seed1", direction=CitationDirection.BOTH)

    assert result.provider_used == "both"
    # OUT seed + 1 ref + IN seed (different id) + 1 citer = 4
    assert result.nodes_added == 4
    assert result.edges_added == 2


@pytest.mark.asyncio
async def test_both_directions_one_side_fails_only(builder, s2_client, oa_client):
    """OUT succeeds, IN fails entirely (both providers fail) → still persists OUT."""
    seed = _node("s2", "seed1")
    refs = [_node("s2", "ref1")]
    s2_client.get_references.return_value = (seed, refs, [_edge(seed, refs[0])])

    s2_client.get_citations.side_effect = APIError("s2 down")
    oa_client.get_citations.side_effect = APIError("openalex down")

    result = await builder.build_for_paper("seed1", direction=CitationDirection.BOTH)

    # OUT succeeded via s2; IN was lost. provider_used reflects what worked.
    assert result.provider_used == "s2"
    assert result.nodes_added == 2  # seed + ref
    assert result.edges_added == 1
    assert any("s2:" in e for e in result.errors)
    assert any("openalex:" in e for e in result.errors)


@pytest.mark.asyncio
async def test_both_directions_all_fail(builder, s2_client, oa_client):
    s2_client.get_references.side_effect = APIError("a")
    s2_client.get_citations.side_effect = APIError("b")
    oa_client.get_references.side_effect = APIError("c")
    oa_client.get_citations.side_effect = APIError("d")

    result = await builder.build_for_paper("seed1", direction=CitationDirection.BOTH)

    assert result.provider_used == "none"
    assert result.nodes_added == 0
    assert result.edges_added == 0
    assert len(result.errors) == 4


# ---------------------------------------------------------------------------
# Idempotency: re-running for the same paper at depth=1 must not corrupt.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_re_call_same_seed(builder, s2_client, store):
    seed = _node("s2", "seed1")
    refs = [_node("s2", "ref1"), _node("s2", "ref2")]
    edges = [_edge(seed, refs[0]), _edge(seed, refs[1])]
    s2_client.get_references.return_value = (seed, refs, edges)

    r1 = await builder.build_for_paper("seed1")
    r2 = await builder.build_for_paper("seed1")

    assert r1.errors == []
    assert r2.errors == []
    # First call inserted everything via bulk; second call hit the
    # per-row recovery path and saw all duplicates → 0 new rows.
    assert r1.nodes_added == 3
    assert r1.edges_added == 2
    assert r2.nodes_added == 0
    assert r2.edges_added == 0


@pytest.mark.asyncio
async def test_idempotent_partial_overlap(builder, s2_client, store):
    """A second seed shares one reference with the first; only the new
    node should land."""
    seed1 = _node("s2", "seed1")
    shared = _node("s2", "shared")
    s2_client.get_references.return_value = (seed1, [shared], [_edge(seed1, shared)])
    r1 = await builder.build_for_paper("seed1")
    assert r1.nodes_added == 2

    seed2 = _node("s2", "seed2")
    new_ref = _node("s2", "new")
    s2_client.get_references.return_value = (
        seed2,
        [shared, new_ref],
        [_edge(seed2, shared), _edge(seed2, new_ref)],
    )
    r2 = await builder.build_for_paper("seed2")

    # Per-row fallback inserts: seed2 (new) + shared (dup) + new (new) = 2
    assert r2.nodes_added == 2
    # Both edges point seed2→X and are new → both inserted
    assert r2.edges_added == 2


# ---------------------------------------------------------------------------
# Deduplication within a single call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deduplicates_repeated_related_nodes(builder, s2_client, store):
    """A reference list that lists the same paper twice must not break
    the bulk insert."""
    seed = _node("s2", "seed1")
    dup = _node("s2", "dup")
    s2_client.get_references.return_value = (
        seed,
        [dup, dup],
        [_edge(seed, dup), _edge(seed, dup)],
    )

    result = await builder.build_for_paper("seed1")

    assert result.errors == []
    assert result.nodes_added == 2  # seed + dup
    assert result.edges_added == 1  # one edge id (deterministic hash)


@pytest.mark.asyncio
async def test_seed_appears_in_related_list_no_duplicate(builder, s2_client, store):
    """If a provider mistakenly returns the seed inside ``related``, dedupe wins."""
    seed = _node("s2", "seed1")
    other = _node("s2", "other")
    s2_client.get_references.return_value = (
        seed,
        [seed, other],
        [_edge(seed, other)],
    )

    result = await builder.build_for_paper("seed1")
    assert result.nodes_added == 2  # seed + other (seed dedup'd)


# ---------------------------------------------------------------------------
# Persistence error handling (non-duplicate failure)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_per_row_recovery_records_unrecoverable_error(
    builder, s2_client, store, monkeypatch
):
    """
    Force the bulk insert to fail, then make per-row also fail with a
    non-duplicate error, so the unrecoverable path is exercised.
    """
    seed = _node("s2", "seed1")
    s2_client.get_references.return_value = (seed, [], [])

    def boom_batch(_nodes):
        raise GraphStoreError("synthetic batch failure")

    def boom_row(node_id, node_type, properties):
        raise GraphStoreError("synthetic row failure")

    monkeypatch.setattr(store, "add_nodes_batch", boom_batch)
    monkeypatch.setattr(store, "add_node", boom_row)

    result = await builder.build_for_paper("seed1")

    assert result.nodes_added == 0
    assert any("synthetic row failure" in e for e in result.errors)


@pytest.mark.asyncio
async def test_edge_per_row_recovery_records_unrecoverable_error(
    builder, s2_client, store, monkeypatch
):
    seed = _node("s2", "seed1")
    ref = _node("s2", "ref1")
    s2_client.get_references.return_value = (seed, [ref], [_edge(seed, ref)])

    def boom_batch(_edges):
        raise GraphStoreError("synthetic edge batch failure")

    def boom_row(*args, **kwargs):
        raise GraphStoreError("synthetic edge row failure")

    monkeypatch.setattr(store, "add_edges_batch", boom_batch)
    monkeypatch.setattr(store, "add_edge", boom_row)

    result = await builder.build_for_paper("seed1")

    # Nodes still got persisted via the normal path
    assert result.nodes_added == 2
    # Edges all failed to insert
    assert result.edges_added == 0
    assert any("synthetic edge row failure" in e for e in result.errors)


@pytest.mark.asyncio
async def test_node_per_row_recovery_skips_duplicates_silently(
    builder, s2_client, store, monkeypatch
):
    """
    Bulk insert fails, but per-row hits 'already exists' for some rows.
    Those should NOT be reported as errors.
    """
    seed = _node("s2", "seed1")
    ref = _node("s2", "ref1")
    s2_client.get_references.return_value = (seed, [ref], [])

    # Pre-insert seed so bulk fails on duplicate, then per-row sees
    # seed-already-exists and inserts ref normally.
    store.add_node(seed.paper_id, NodeType.PAPER, {"title": seed.title})

    result = await builder.build_for_paper("seed1")

    # ref is new; seed dup
    assert result.nodes_added == 1
    assert result.errors == []


@pytest.mark.asyncio
async def test_edge_per_row_recovery_inserts_new_edges_after_duplicate(
    builder, s2_client, store, temp_db
):
    """Bulk fails on a single duplicate edge; per-row should still
    insert the genuinely new edges (exercises the inserted += 1 path
    in the edge recovery branch)."""
    seed = _node("s2", "seed1")
    ref1 = _node("s2", "ref1")
    ref2 = _node("s2", "ref2")
    s2_client.get_references.return_value = (
        seed,
        [ref1, ref2],
        [_edge(seed, ref1), _edge(seed, ref2)],
    )

    # First call inserts everything cleanly.
    r1 = await builder.build_for_paper("seed1")
    assert r1.nodes_added == 3
    assert r1.edges_added == 2

    # Now extend the response with a brand-new edge to ref3 — bulk
    # will fail because edge1/edge2 are duplicates, then per-row will
    # skip the dups and insert the new edge.
    ref3 = _node("s2", "ref3")
    s2_client.get_references.return_value = (
        seed,
        [ref1, ref2, ref3],
        [_edge(seed, ref1), _edge(seed, ref2), _edge(seed, ref3)],
    )

    r2 = await builder.build_for_paper("seed1")
    assert r2.errors == []
    # Exactly one new edge inserted via the per-row recovery path
    assert r2.edges_added == 1


@pytest.mark.asyncio
async def test_persist_skipped_when_only_seed_with_no_other_data(
    builder, s2_client, store
):
    """A seed-only build still inserts the seed (covers the empty-edges
    no-op path in _bulk_insert_edges)."""
    seed = _node("s2", "seed_alone")
    s2_client.get_references.return_value = (seed, [], [])

    result = await builder.build_for_paper("seed_alone")
    assert result.nodes_added == 1
    assert result.edges_added == 0


def test_bulk_insert_nodes_empty_is_noop(builder):
    """Direct unit test for the empty-nodes early return path."""
    errors: list[str] = []
    inserted = builder._bulk_insert_nodes([], errors)
    assert inserted == 0
    assert errors == []


def test_bulk_insert_edges_empty_is_noop(builder):
    """Direct unit test for the empty-edges early return path."""
    errors: list[str] = []
    inserted = builder._bulk_insert_edges([], errors)
    assert inserted == 0
    assert errors == []


# ---------------------------------------------------------------------------
# Storage-engine agnostic: the builder must not import sqlite3 directly.
# ---------------------------------------------------------------------------


def test_builder_does_not_import_sqlite3():
    import src.services.intelligence.citation.graph_builder as gb_mod

    src = Path(gb_mod.__file__).read_text(encoding="utf-8")
    # Allow comments containing the word, but not an actual import line
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "import sqlite3" not in stripped


# ---------------------------------------------------------------------------
# Combined-provider tag helper
# ---------------------------------------------------------------------------


def test_combine_providers_both_none():
    assert CitationGraphBuilder._combine_providers("none", "none") == "none"


def test_combine_providers_one_none_uses_other():
    assert CitationGraphBuilder._combine_providers("none", "s2") == "s2"
    assert CitationGraphBuilder._combine_providers("openalex", "none") == "openalex"


def test_combine_providers_same_value():
    assert CitationGraphBuilder._combine_providers("s2", "s2") == "s2"


def test_combine_providers_mixed_returns_both():
    assert CitationGraphBuilder._combine_providers("s2", "openalex") == "both"


# ---------------------------------------------------------------------------
# _call_provider direct tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_provider_out_dispatches_to_get_references(s2_client):
    s2_client.get_references.return_value = ("seed", [], [])
    await CitationGraphBuilder._call_provider(
        s2_client, "X", CitationDirection.OUT, max_results=5
    )
    s2_client.get_references.assert_awaited_once_with("X", max_results=5)


@pytest.mark.asyncio
async def test_call_provider_in_dispatches_to_get_citations(s2_client):
    s2_client.get_citations.return_value = ("seed", [], [])
    await CitationGraphBuilder._call_provider(
        s2_client, "X", CitationDirection.IN, max_results=5
    )
    s2_client.get_citations.assert_awaited_once_with("X", max_results=5)


# ---------------------------------------------------------------------------
# GraphBuildResult dataclass behavior
# ---------------------------------------------------------------------------


def test_result_is_frozen_dataclass():
    r = GraphBuildResult(
        seed_paper_id="x",
        nodes_added=1,
        edges_added=2,
        provider_used="s2",
    )
    with pytest.raises((AttributeError, Exception)):
        r.nodes_added = 99  # type: ignore[misc]


def test_result_default_errors_is_empty_list():
    r = GraphBuildResult(
        seed_paper_id="x", nodes_added=0, edges_added=0, provider_used="none"
    )
    assert r.errors == []


# ---------------------------------------------------------------------------
# End-to-end persistence sanity check via real store rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persisted_edges_have_cites_type_and_metadata(
    builder, s2_client, store, temp_db
):
    seed = _node("s2", "seed1")
    ref = _node("s2", "ref1")
    s2_client.get_references.return_value = (
        seed,
        [ref],
        [
            CitationEdge(
                citing_paper_id=seed.paper_id,
                cited_paper_id=ref.paper_id,
                context="see Section 3.1",
                section="Methodology",
                is_influential=True,
                source="semantic_scholar",
            )
        ],
    )

    await builder.build_for_paper("seed1")

    # Inspect raw row
    conn = sqlite3.connect(str(temp_db))
    try:
        row = conn.execute(
            "SELECT edge_type, source_id, target_id, properties " "FROM edges LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert row[0] == EdgeType.CITES.value
    assert row[1] == seed.paper_id
    assert row[2] == ref.paper_id
    assert "Section 3.1" in row[3]
    assert "Methodology" in row[3]
