"""Tests for :class:`CouplingAnalyzer` (Issue #128 / REQ-9.2.3).

Covers:
- Exact spec example: A:[R1..R5], B:[R2,R3,R4,R6,R7] → 3/7 ≈ 0.4286
- No-overlap pair (strength 0.0)
- Identical reference sets (strength 1.0)
- Self-pair rejection
- Zero-reference papers (handles 0/0 gracefully → 0.0)
- analyze_for_paper top-k ordering and k-cap
- Cache hit / miss (via injected repo mock)
- Invalid paper id pattern
- DoS guards: MAX_CANDIDATES, MAX_TOP_K
- Tie-break determinism (L-5)
- DEFAULT_MAX_AGE_DAYS TTL linkage (L-3)
- Structured-log events via ``capture_logs()`` with the canonical
  "rebind logger before capture" pattern (CLAUDE.md §Test Authoring
  Conventions).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest
import structlog
import structlog.testing

import src.services.intelligence.citation.coupling_analyzer as analyzer_mod
from src.services.intelligence.citation.coupling_analyzer import (
    MAX_CANDIDATES,
    MAX_TOP_K,
    CouplingAnalyzer,
)
from src.services.intelligence.citation.coupling_repository import (
    DEFAULT_MAX_AGE_DAYS,
    CitationCouplingRepository,
)
from src.services.intelligence.models import EdgeType, GraphEdge
from src.storage.intelligence_graph import SQLiteGraphStore

# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

PAPER_A = "paper:s2:alpha"
PAPER_B = "paper:s2:beta"
PAPER_C = "paper:s2:gamma"

# Spec example reference sets (REQ-9.2.3 §617)
REFS_A = [
    "paper:s2:r1",
    "paper:s2:r2",
    "paper:s2:r3",
    "paper:s2:r4",
    "paper:s2:r5",
]
REFS_B = [
    "paper:s2:r2",
    "paper:s2:r3",
    "paper:s2:r4",
    "paper:s2:r6",
    "paper:s2:r7",
]


def _make_edge(source: str, target: str) -> GraphEdge:
    """Build a minimal CITES GraphEdge for testing."""
    return GraphEdge(
        edge_id=f"edge:cites:{source}-{target}",
        edge_type=EdgeType.CITES,
        source_id=source,
        target_id=target,
        properties={},
    )


def _mock_store_with_refs(
    refs_map: dict[str, list[str]],
    citers_map: dict[str, list[str]] | None = None,
) -> MagicMock:
    """Return a mock SQLiteGraphStore whose get_edges returns controlled data.

    ``refs_map`` maps paper_id → list of cited paper_ids (outgoing CITES).

    ``citers_map`` optionally maps paper_id → list of papers that cite it
    (inbound CITES).  When omitted, all inbound-citer counts return 0 and
    ``get_papers_citing_both`` returns an empty set — preserving the existing
    test semantics for tests that only care about Jaccard coupling.
    """
    store = MagicMock(spec=SQLiteGraphStore)

    def _get_edges(
        node_id: str,
        direction: str = "both",
        edge_type: EdgeType | None = None,
    ) -> list[GraphEdge]:
        if direction == "outgoing" and edge_type == EdgeType.CITES:
            return [_make_edge(node_id, ref) for ref in refs_map.get(node_id, [])]
        return []

    store.get_edges.side_effect = _get_edges

    effective_citers: dict[str, list[str]] = citers_map or {}

    def _get_inbound_citer_count(paper_id: str) -> int:
        return len(effective_citers.get(paper_id, []))

    def _get_papers_citing_both(a_id: str, b_id: str) -> set[str]:
        citers_a = set(effective_citers.get(a_id, []))
        citers_b = set(effective_citers.get(b_id, []))
        return citers_a & citers_b

    def _count_papers_citing_both(a_id: str, b_id: str) -> int:
        return len(_get_papers_citing_both(a_id, b_id))

    store.get_inbound_citer_count.side_effect = _get_inbound_citer_count
    store.get_papers_citing_both.side_effect = _get_papers_citing_both
    store.count_papers_citing_both.side_effect = _count_papers_citing_both

    return store


@pytest.fixture
def db_path() -> Iterator[Path]:
    """Temporary SQLite file cleaned up after each test."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    path.unlink(missing_ok=True)
    yield path
    path.unlink(missing_ok=True)


@pytest.fixture
def repo(db_path: Path) -> CitationCouplingRepository:
    return CitationCouplingRepository.connect(db_path)


# ---------------------------------------------------------------------------
# 1. Core Jaccard computation
# ---------------------------------------------------------------------------


class TestAnalyzePairJaccard:
    @pytest.mark.asyncio
    async def test_coupling_jaccard_exact_example_from_spec(self) -> None:
        """Spec example: A:[R1..R5], B:[R2,R3,R4,R6,R7] → 3/7 ≈ 0.4286.

        Pinned with pytest.approx per REQ-9.2.3 §617.  The mock has no
        shared citers so co_citation_count is 0.
        """
        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(3 / 7, rel=1e-6)
        assert sorted(result.shared_references) == sorted(
            ["paper:s2:r2", "paper:s2:r3", "paper:s2:r4"]
        )
        assert result.paper_a_id == PAPER_A
        assert result.paper_b_id == PAPER_B
        assert result.co_citation_count == 0  # no shared citers in mock

    @pytest.mark.asyncio
    async def test_coupling_no_overlap(self) -> None:
        """Papers with entirely disjoint reference sets → strength 0.0."""
        store = _mock_store_with_refs(
            {
                PAPER_A: ["paper:s2:r1", "paper:s2:r2"],
                PAPER_B: ["paper:s2:r3", "paper:s2:r4"],
            }
        )
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(0.0)
        assert result.shared_references == []

    @pytest.mark.asyncio
    async def test_coupling_identical_refs(self) -> None:
        """Papers with identical reference sets → strength 1.0."""
        refs = ["paper:s2:r1", "paper:s2:r2", "paper:s2:r3"]
        store = _mock_store_with_refs({PAPER_A: refs, PAPER_B: refs})
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(1.0)
        assert sorted(result.shared_references) == sorted(refs)

    @pytest.mark.asyncio
    async def test_coupling_paper_with_no_refs(self) -> None:
        """Both papers have zero references → strength 0.0, no ZeroDivisionError."""
        store = _mock_store_with_refs({})  # no refs for either paper
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(0.0)
        assert result.shared_references == []

    @pytest.mark.asyncio
    async def test_coupling_one_paper_no_refs(self) -> None:
        """One paper has refs, the other has none → strength 0.0."""
        store = _mock_store_with_refs(
            {PAPER_A: ["paper:s2:r1", "paper:s2:r2"], PAPER_B: []}
        )
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(0.0)
        assert result.shared_references == []


# ---------------------------------------------------------------------------
# 2. Validation / error paths
# ---------------------------------------------------------------------------


class TestAnalyzePairValidation:
    @pytest.mark.asyncio
    async def test_coupling_self_pair_raises(self) -> None:
        """analyze_pair with paper_a_id == paper_b_id raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="must differ"):
            await analyzer.analyze_pair(PAPER_A, PAPER_A)

    @pytest.mark.asyncio
    async def test_invalid_paper_id_pattern_raises(self) -> None:
        """analyze_pair with an id containing disallowed chars raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="Invalid paper_id format"):
            await analyzer.analyze_pair("paper:s2:a b c", PAPER_B)

    @pytest.mark.asyncio
    async def test_invalid_paper_id_empty_raises(self) -> None:
        """analyze_pair with an empty id raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="non-empty string"):
            await analyzer.analyze_pair("", PAPER_B)

    @pytest.mark.asyncio
    async def test_invalid_paper_id_too_long_raises(self) -> None:
        """analyze_pair with an id exceeding the length cap raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)
        long_id = "paper:s2:" + "a" * 600

        with pytest.raises(ValueError, match="exceeds max"):
            await analyzer.analyze_pair(long_id, PAPER_B)


# ---------------------------------------------------------------------------
# 3. analyze_for_paper ordering and top-k
# ---------------------------------------------------------------------------


class TestAnalyzeForPaper:
    @pytest.mark.asyncio
    async def test_analyze_for_paper_top_k_ordering(self) -> None:
        """analyze_for_paper returns results sorted DESC by coupling_strength."""
        # PAPER_A is the query paper.
        # PAPER_B shares 2 refs with A (out of 3), PAPER_C shares 1 (out of 3).
        store = _mock_store_with_refs(
            {
                PAPER_A: ["paper:s2:r1", "paper:s2:r2", "paper:s2:r3"],
                PAPER_B: ["paper:s2:r1", "paper:s2:r2", "paper:s2:r4"],  # 2/4
                PAPER_C: ["paper:s2:r1", "paper:s2:r5"],  # 1/4
            }
        )
        analyzer = CouplingAnalyzer(store)
        results = await analyzer.analyze_for_paper(
            PAPER_A, [PAPER_B, PAPER_C], top_k=10
        )

        assert len(results) == 2
        # B has higher coupling than C.
        assert results[0].paper_b_id == PAPER_B
        assert results[1].paper_b_id == PAPER_C
        assert results[0].coupling_strength > results[1].coupling_strength

    @pytest.mark.asyncio
    async def test_analyze_for_paper_respects_top_k(self) -> None:
        """analyze_for_paper returns at most top_k results."""
        papers = [f"paper:s2:cand{i:03d}" for i in range(20)]
        # All candidates share the same 1 ref → equal strength; top_k=5.
        store = _mock_store_with_refs(
            {
                PAPER_A: ["paper:s2:ref001"],
                **{p: ["paper:s2:ref001"] for p in papers},
            }
        )
        analyzer = CouplingAnalyzer(store)
        results = await analyzer.analyze_for_paper(PAPER_A, papers, top_k=5)

        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_analyze_for_paper_invalid_top_k_raises(self) -> None:
        """analyze_for_paper with top_k < 1 raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="top_k must be >= 1"):
            await analyzer.analyze_for_paper(PAPER_A, [PAPER_B], top_k=0)

    @pytest.mark.asyncio
    async def test_analyze_for_paper_empty_candidates(self) -> None:
        """analyze_for_paper with empty candidate list returns empty list."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        results = await analyzer.analyze_for_paper(PAPER_A, [], top_k=10)

        assert results == []

    @pytest.mark.asyncio
    async def test_analyze_for_paper_exceeds_max_candidates_raises(self) -> None:
        """analyze_for_paper raises ValueError when candidates > MAX_CANDIDATES."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)
        too_many = [f"paper:s2:c{i:06d}" for i in range(MAX_CANDIDATES + 1)]

        with pytest.raises(ValueError, match="MAX_CANDIDATES"):
            await analyzer.analyze_for_paper(PAPER_A, too_many, top_k=10)

    @pytest.mark.asyncio
    async def test_analyze_for_paper_clamps_top_k_to_max(self) -> None:
        """analyze_for_paper silently clamps top_k > MAX_TOP_K."""
        papers = [f"paper:s2:c{i:04d}" for i in range(5)]
        store = _mock_store_with_refs(
            {PAPER_A: ["paper:s2:r1"], **{p: ["paper:s2:r1"] for p in papers}}
        )
        analyzer = CouplingAnalyzer(store)
        # top_k above MAX_TOP_K should be accepted (no raise) and clamped.
        results = await analyzer.analyze_for_paper(
            PAPER_A, papers, top_k=MAX_TOP_K + 999
        )
        # We only have 5 candidates, so max 5 results returned.
        assert len(results) <= 5

    @pytest.mark.asyncio
    async def test_analyze_for_paper_ties_broken_by_paper_b_id_ascending(
        self,
    ) -> None:
        """L-5: Equal coupling_strength ties are broken by paper_b_id ascending."""
        # All candidates share the same single reference → equal strength.
        papers = [
            "paper:s2:zzz",
            "paper:s2:aaa",
            "paper:s2:mmm",
        ]
        store = _mock_store_with_refs(
            {
                PAPER_A: ["paper:s2:shared"],
                **{p: ["paper:s2:shared"] for p in papers},
            }
        )
        analyzer = CouplingAnalyzer(store)
        results = await analyzer.analyze_for_paper(PAPER_A, papers, top_k=10)

        # All strengths equal → alphabetical ascending on paper_b_id.
        b_ids = [r.paper_b_id for r in results]
        assert b_ids == sorted(b_ids)


# ---------------------------------------------------------------------------
# 4. Structured-log event assertions
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    @pytest.mark.asyncio
    async def test_pair_computed_event_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``coupling_analyzer_pair_computed`` event is logged on each compute."""
        # Rebind logger BEFORE entering capture_logs() per CLAUDE.md §Test
        # Authoring Conventions (cache_logger_on_first_use pattern).
        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        store = _mock_store_with_refs(
            {PAPER_A: ["paper:s2:r1"], PAPER_B: ["paper:s2:r1", "paper:s2:r2"]}
        )
        analyzer = CouplingAnalyzer(store)

        with structlog.testing.capture_logs() as logs:
            await analyzer.analyze_pair(PAPER_A, PAPER_B)

        events = [
            e for e in logs if e.get("event") == "coupling_analyzer_pair_computed"
        ]
        assert len(events) == 1
        assert events[0]["paper_a_id"] == PAPER_A
        assert events[0]["paper_b_id"] == PAPER_B
        assert events[0]["shared"] == 1
        assert events[0]["union"] == 2

    @pytest.mark.asyncio
    async def test_skipped_no_refs_event_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``coupling_analyzer_skipped_no_refs`` is logged when both have 0 refs."""
        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with structlog.testing.capture_logs() as logs:
            await analyzer.analyze_pair(PAPER_A, PAPER_B)

        events = [
            e for e in logs if e.get("event") == "coupling_analyzer_skipped_no_refs"
        ]
        assert len(events) == 1
        assert events[0]["paper_a_id"] == PAPER_A
        assert events[0]["paper_b_id"] == PAPER_B


# ---------------------------------------------------------------------------
# 5. Cache integration (repo wired in)
# ---------------------------------------------------------------------------


class TestCacheIntegration:
    @pytest.mark.asyncio
    async def test_persistence_cache_hit(
        self, repo: CitationCouplingRepository
    ) -> None:
        """Second call within TTL returns the cached row without re-computing."""
        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store, repo=repo)

        first = await analyzer.analyze_pair(PAPER_A, PAPER_B)
        # Reset the store mock so a second store call would be detectable.
        store.get_edges.reset_mock()

        second = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        # Values must match.
        assert second.coupling_strength == pytest.approx(first.coupling_strength)
        assert second.shared_references == first.shared_references
        # The store must NOT have been called again (cache hit path).
        store.get_edges.assert_not_called()

    @pytest.mark.asyncio
    async def test_persistence_cache_miss_after_ttl(
        self,
        repo: CitationCouplingRepository,
        db_path: Path,
    ) -> None:
        """Stale row (older than TTL) triggers recompute, not a cache hit."""
        from src.storage.intelligence_graph.connection import open_connection

        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store, repo=repo)

        # Insert a row with an old timestamp directly so we can control staleness.
        old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        # Canonicalize pair for insert.
        canon_a = min(PAPER_A, PAPER_B)
        canon_b = max(PAPER_A, PAPER_B)
        with open_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO citation_coupling"
                " (paper_a_id, paper_b_id, coupling_strength,"
                "  shared_references_json, co_citation_count, computed_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (canon_a, canon_b, 0.5, "[]", 0, old_ts),
            )
            conn.commit()

        # Verify: direct repo.get with max_age_days=30 treats old row as stale.
        cached = repo.get(PAPER_A, PAPER_B, max_age_days=30)
        assert cached is None  # stale row → cache miss

        # Re-run via the analyzer; the store WILL be called (M-8 pattern).
        store.get_edges.reset_mock()
        await analyzer.analyze_pair(PAPER_A, PAPER_B)
        store.get_edges.assert_any_call(
            PAPER_A, direction="outgoing", edge_type=EdgeType.CITES
        )

    @pytest.mark.asyncio
    async def test_cache_write_failure_swallowed(self, db_path: Path) -> None:
        """A repo write failure does not propagate to the caller."""
        failing_repo = MagicMock(spec=CitationCouplingRepository)
        failing_repo.get.return_value = None  # always cache miss
        failing_repo.record.side_effect = Exception("disk full")

        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store, repo=failing_repo)

        # Must not raise even though repo.record raises.
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)
        assert result.coupling_strength == pytest.approx(3 / 7, rel=1e-6)

    @pytest.mark.asyncio
    async def test_cache_write_failure_logs_error(
        self,
        db_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A repo write failure emits ``coupling_analyzer_cache_write_failed``."""
        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        failing_repo = MagicMock(spec=CitationCouplingRepository)
        failing_repo.get.return_value = None
        failing_repo.record.side_effect = Exception("disk full")

        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store, repo=failing_repo)

        with structlog.testing.capture_logs() as logs:
            await analyzer.analyze_pair(PAPER_A, PAPER_B)

        events = [
            e for e in logs if e.get("event") == "coupling_analyzer_cache_write_failed"
        ]
        assert len(events) == 1
        assert "disk full" in events[0]["error"]

    def test_analyzer_uses_default_ttl_from_repo(self) -> None:
        """L-3: DEFAULT_MAX_AGE_DAYS from the repo module is a stable constant.

        The analyzer's cache lookups rely on the repo's TTL default.
        This test pins that the constant is reachable and positive so
        any future accidental rename/removal fails loudly here.
        """
        assert DEFAULT_MAX_AGE_DAYS > 0
        assert isinstance(DEFAULT_MAX_AGE_DAYS, int)


# ---------------------------------------------------------------------------
# 6. References truncation guard (M-10)
# ---------------------------------------------------------------------------


class TestReferencesTruncation:
    @pytest.mark.asyncio
    async def test_references_truncated_event_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """coupling_references_truncated warning is emitted when refs exceed cap.

        M-10: _get_references caps the edge list at _MAX_REFERENCES and
        emits an audit event so operators can detect unexpectedly dense
        reference sets.
        """
        from src.services.intelligence.citation.coupling_analyzer import (
            _MAX_REFERENCES,
        )

        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        # Produce _MAX_REFERENCES + 1 edges for PAPER_A to trigger the cap.
        oversized_refs = [f"paper:s2:r{i:06d}" for i in range(_MAX_REFERENCES + 1)]
        store = _mock_store_with_refs({PAPER_A: oversized_refs, PAPER_B: []})
        analyzer = CouplingAnalyzer(store)

        with structlog.testing.capture_logs() as logs:
            result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        trunc_events = [
            e for e in logs if e.get("event") == "coupling_references_truncated"
        ]
        assert len(trunc_events) >= 1
        assert trunc_events[0]["paper_id"] == PAPER_A
        assert trunc_events[0]["fetched"] == _MAX_REFERENCES + 1
        assert trunc_events[0]["cap"] == _MAX_REFERENCES
        # Computation still succeeds; PAPER_B has no refs so strength=0.
        assert result.coupling_strength == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 7. Co-citation count (Issue #148)
# ---------------------------------------------------------------------------


PAPER_X = "paper:s2:citer001"
PAPER_Y = "paper:s2:citer002"
PAPER_Z = "paper:s2:citer003"


class TestCoCitationCount:
    @pytest.mark.asyncio
    async def test_co_citation_count_zero_when_no_overlap(self) -> None:
        """Papers with no shared citers → co_citation_count == 0."""
        # PAPER_X cites PAPER_A only; PAPER_Y cites PAPER_B only.
        store = _mock_store_with_refs(
            {PAPER_A: REFS_A, PAPER_B: REFS_B},
            citers_map={PAPER_A: [PAPER_X], PAPER_B: [PAPER_Y]},
        )
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.co_citation_count == 0

    @pytest.mark.asyncio
    async def test_co_citation_count_correct_for_two_shared_citers(self) -> None:
        """Two shared citers → co_citation_count == 2."""
        # PAPER_X and PAPER_Y both cite PAPER_A and PAPER_B.
        # PAPER_Z cites only PAPER_A, so does not count.
        store = _mock_store_with_refs(
            {PAPER_A: REFS_A, PAPER_B: REFS_B},
            citers_map={
                PAPER_A: [PAPER_X, PAPER_Y, PAPER_Z],
                PAPER_B: [PAPER_X, PAPER_Y],
            },
        )
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.co_citation_count == 2

    @pytest.mark.asyncio
    async def test_co_citation_count_excludes_self_loops(self) -> None:
        """A paper that cites itself (self-loop) should not count toward co-citations.

        The shared-citer intersection is computed by get_papers_citing_both
        in the storage layer.  Here we verify that PAPER_A appearing in its
        own citer list does not inflate the result — the result must match
        only genuine third-party papers.
        """
        # PAPER_A is in its own citer list (self-loop scenario).
        # Only PAPER_X is a genuine shared citer of both.
        store = _mock_store_with_refs(
            {PAPER_A: REFS_A, PAPER_B: REFS_B},
            citers_map={
                PAPER_A: [PAPER_X, PAPER_A],  # self-loop: PAPER_A cites itself
                PAPER_B: [PAPER_X],
            },
        )
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        # Only PAPER_X is in the intersection — PAPER_A is not in PAPER_B's
        # citer list so the intersection is exactly {PAPER_X}.
        assert result.co_citation_count == 1

    @pytest.mark.asyncio
    async def test_co_citation_count_handles_one_paper_with_no_inbound_citers(
        self,
    ) -> None:
        """If one paper has no inbound CITES edges, co_citation_count == 0."""
        store = _mock_store_with_refs(
            {PAPER_A: REFS_A, PAPER_B: REFS_B},
            citers_map={PAPER_A: [PAPER_X, PAPER_Y]},
            # PAPER_B has no citers → intersection is empty
        )
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.co_citation_count == 0

    @pytest.mark.asyncio
    async def test_co_citation_count_truncates_at_max(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When inbound-citer count exceeds cap, truncation audit event is emitted.

        We patch MAX_INBOUND_CITERS_FOR_CO_CITATION to a tiny value (3) so
        the test doesn't need to insert 50,001 rows.  The mock returns > 3
        citers for PAPER_A, triggering the DoS guard.
        """
        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        monkeypatch.setattr(analyzer_mod, "MAX_INBOUND_CITERS_FOR_CO_CITATION", 3)

        # 4 citers for PAPER_A > cap of 3; 2 shared citers (PAPER_X, PAPER_Y).
        citer_ids = [f"paper:s2:cit{i:04d}" for i in range(4)]
        store = _mock_store_with_refs(
            {PAPER_A: REFS_A, PAPER_B: REFS_B},
            citers_map={
                PAPER_A: citer_ids,
                PAPER_B: citer_ids[:2],  # first 2 are shared
            },
        )
        analyzer = CouplingAnalyzer(store)

        with structlog.testing.capture_logs() as logs:
            result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        trunc_events = [
            e for e in logs if e.get("event") == "coupling_co_citation_truncated"
        ]
        assert len(trunc_events) == 1
        assert trunc_events[0]["paper_a_id"] == PAPER_A
        assert trunc_events[0]["paper_b_id"] == PAPER_B
        assert trunc_events[0]["inbound_count"] == 4
        assert trunc_events[0]["cap"] == 3
        # When truncation fires, the sentinel value 0 is returned — the
        # expensive get_papers_citing_both walk is skipped entirely.
        assert result.co_citation_count == 0

    @pytest.mark.asyncio
    async def test_compute_pair_populates_co_citation_count(self) -> None:
        """Integration: analyze_pair returns non-zero co_citation_count."""
        store = _mock_store_with_refs(
            {PAPER_A: REFS_A, PAPER_B: REFS_B},
            citers_map={
                PAPER_A: [PAPER_X, PAPER_Y, PAPER_Z],
                PAPER_B: [PAPER_X, PAPER_Z],
            },
        )
        analyzer = CouplingAnalyzer(store)
        result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        # PAPER_X and PAPER_Z both cite A and B → co_citation_count == 2.
        assert result.co_citation_count == 2
        assert result.coupling_strength == pytest.approx(3 / 7, rel=1e-6)

    @pytest.mark.asyncio
    async def test_co_citation_count_truncation_skips_walk_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When DoS cap is exceeded, get_papers_citing_both is never called.

        Sampling has been removed (H-1 fix): the old broken math was an
        algebraic identity ``round(n * len(shared) / n) == len(shared)``.
        The correct behaviour is to skip the expensive walk entirely and
        return 0 as a sentinel.  This test verifies that
        ``count_papers_citing_both`` is not called when the cap fires.
        """
        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        monkeypatch.setattr(analyzer_mod, "MAX_INBOUND_CITERS_FOR_CO_CITATION", 2)

        # 3 citers for PAPER_A (> cap of 2) → truncation fires.
        citer_ids = [f"paper:s2:cit{i:04d}" for i in range(3)]
        store = _mock_store_with_refs(
            {PAPER_A: REFS_A, PAPER_B: REFS_B},
            citers_map={
                PAPER_A: citer_ids,
                PAPER_B: citer_ids,
            },
        )
        analyzer = CouplingAnalyzer(store)

        with structlog.testing.capture_logs() as logs:
            result = await analyzer.analyze_pair(PAPER_A, PAPER_B)

        trunc_events = [
            e for e in logs if e.get("event") == "coupling_co_citation_truncated"
        ]
        assert len(trunc_events) == 1
        # Sentinel 0 returned; the expensive walk was NOT executed.
        assert result.co_citation_count == 0
        # Verify count_papers_citing_both was never called (DoS guard works).
        store.count_papers_citing_both.assert_not_called()
        store.get_papers_citing_both.assert_not_called()
