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
from src.services.intelligence.citation.coupling_analyzer import CouplingAnalyzer
from src.services.intelligence.citation.coupling_repository import (
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


def _mock_store_with_refs(refs_map: dict[str, list[str]]) -> MagicMock:
    """Return a mock SQLiteGraphStore whose get_edges returns controlled data.

    ``refs_map`` maps paper_id → list of cited paper_ids (outgoing CITES).
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
    def test_coupling_jaccard_exact_example_from_spec(self) -> None:
        """Spec example: A:[R1..R5], B:[R2,R3,R4,R6,R7] → 3/7 ≈ 0.4286.

        Pinned with pytest.approx per REQ-9.2.3 §617.
        """
        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store)
        result = analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(3 / 7, rel=1e-6)
        assert sorted(result.shared_references) == sorted(
            ["paper:s2:r2", "paper:s2:r3", "paper:s2:r4"]
        )
        assert result.paper_a_id == PAPER_A
        assert result.paper_b_id == PAPER_B

    def test_coupling_no_overlap(self) -> None:
        """Papers with entirely disjoint reference sets → strength 0.0."""
        store = _mock_store_with_refs(
            {
                PAPER_A: ["paper:s2:r1", "paper:s2:r2"],
                PAPER_B: ["paper:s2:r3", "paper:s2:r4"],
            }
        )
        analyzer = CouplingAnalyzer(store)
        result = analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(0.0)
        assert result.shared_references == []

    def test_coupling_identical_refs(self) -> None:
        """Papers with identical reference sets → strength 1.0."""
        refs = ["paper:s2:r1", "paper:s2:r2", "paper:s2:r3"]
        store = _mock_store_with_refs({PAPER_A: refs, PAPER_B: refs})
        analyzer = CouplingAnalyzer(store)
        result = analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(1.0)
        assert sorted(result.shared_references) == sorted(refs)

    def test_coupling_paper_with_no_refs(self) -> None:
        """Both papers have zero references → strength 0.0, no ZeroDivisionError."""
        store = _mock_store_with_refs({})  # no refs for either paper
        analyzer = CouplingAnalyzer(store)
        result = analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(0.0)
        assert result.shared_references == []

    def test_coupling_one_paper_no_refs(self) -> None:
        """One paper has refs, the other has none → strength 0.0."""
        store = _mock_store_with_refs(
            {PAPER_A: ["paper:s2:r1", "paper:s2:r2"], PAPER_B: []}
        )
        analyzer = CouplingAnalyzer(store)
        result = analyzer.analyze_pair(PAPER_A, PAPER_B)

        assert result.coupling_strength == pytest.approx(0.0)
        assert result.shared_references == []


# ---------------------------------------------------------------------------
# 2. Validation / error paths
# ---------------------------------------------------------------------------


class TestAnalyzePairValidation:
    def test_coupling_self_pair_raises(self) -> None:
        """analyze_pair with paper_a_id == paper_b_id raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="must differ"):
            analyzer.analyze_pair(PAPER_A, PAPER_A)

    def test_invalid_paper_id_pattern_raises(self) -> None:
        """analyze_pair with an id containing disallowed chars raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="Invalid paper_id format"):
            analyzer.analyze_pair("paper:s2:a b c", PAPER_B)

    def test_invalid_paper_id_empty_raises(self) -> None:
        """analyze_pair with an empty id raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="non-empty string"):
            analyzer.analyze_pair("", PAPER_B)

    def test_invalid_paper_id_too_long_raises(self) -> None:
        """analyze_pair with an id exceeding the length cap raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)
        long_id = "paper:s2:" + "a" * 600

        with pytest.raises(ValueError, match="exceeds max"):
            analyzer.analyze_pair(long_id, PAPER_B)


# ---------------------------------------------------------------------------
# 3. analyze_for_paper ordering and top-k
# ---------------------------------------------------------------------------


class TestAnalyzeForPaper:
    def test_analyze_for_paper_top_k_ordering(self) -> None:
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
        results = analyzer.analyze_for_paper(PAPER_A, [PAPER_B, PAPER_C], top_k=10)

        assert len(results) == 2
        # B has higher coupling than C.
        assert results[0].paper_b_id == PAPER_B
        assert results[1].paper_b_id == PAPER_C
        assert results[0].coupling_strength > results[1].coupling_strength

    def test_analyze_for_paper_respects_top_k(self) -> None:
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
        results = analyzer.analyze_for_paper(PAPER_A, papers, top_k=5)

        assert len(results) == 5

    def test_analyze_for_paper_invalid_top_k_raises(self) -> None:
        """analyze_for_paper with top_k < 1 raises ValueError."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with pytest.raises(ValueError, match="top_k must be >= 1"):
            analyzer.analyze_for_paper(PAPER_A, [PAPER_B], top_k=0)

    def test_analyze_for_paper_empty_candidates(self) -> None:
        """analyze_for_paper with empty candidate list returns empty list."""
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        results = analyzer.analyze_for_paper(PAPER_A, [], top_k=10)

        assert results == []


# ---------------------------------------------------------------------------
# 4. Structured-log event assertions
# ---------------------------------------------------------------------------


class TestStructuredLogging:
    def test_pair_computed_event_emitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``coupling_analyzer_pair_computed`` event is logged on each compute."""
        # Rebind logger BEFORE entering capture_logs() per CLAUDE.md §Test
        # Authoring Conventions (cache_logger_on_first_use pattern).
        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        store = _mock_store_with_refs(
            {PAPER_A: ["paper:s2:r1"], PAPER_B: ["paper:s2:r1", "paper:s2:r2"]}
        )
        analyzer = CouplingAnalyzer(store)

        with structlog.testing.capture_logs() as logs:
            analyzer.analyze_pair(PAPER_A, PAPER_B)

        events = [
            e for e in logs if e.get("event") == "coupling_analyzer_pair_computed"
        ]
        assert len(events) == 1
        assert events[0]["paper_a_id"] == PAPER_A
        assert events[0]["paper_b_id"] == PAPER_B
        assert events[0]["shared"] == 1
        assert events[0]["union"] == 2

    def test_skipped_no_refs_event_emitted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``coupling_analyzer_skipped_no_refs`` is logged when both have 0 refs."""
        monkeypatch.setattr(analyzer_mod, "logger", structlog.get_logger())
        store = _mock_store_with_refs({})
        analyzer = CouplingAnalyzer(store)

        with structlog.testing.capture_logs() as logs:
            analyzer.analyze_pair(PAPER_A, PAPER_B)

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
    def test_persistence_cache_hit(self, repo: CitationCouplingRepository) -> None:
        """Second call within TTL returns the cached row without re-computing."""
        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store, repo=repo)

        first = analyzer.analyze_pair(PAPER_A, PAPER_B)
        # Reset the store mock so a second store call would be detectable.
        store.get_edges.reset_mock()

        second = analyzer.analyze_pair(PAPER_A, PAPER_B)

        # Values must match.
        assert second.coupling_strength == pytest.approx(first.coupling_strength)
        assert second.shared_references == first.shared_references
        # The store must NOT have been called again (cache hit path).
        store.get_edges.assert_not_called()

    def test_persistence_cache_miss_after_ttl(
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

        # Re-run via the analyzer; the store WILL be called.
        store.get_edges.reset_mock()
        analyzer.analyze_pair(PAPER_A, PAPER_B)
        assert store.get_edges.called

    def test_cache_write_failure_swallowed(self, db_path: Path) -> None:
        """A repo write failure does not propagate to the caller."""
        failing_repo = MagicMock(spec=CitationCouplingRepository)
        failing_repo.get.return_value = None  # always cache miss
        failing_repo.record.side_effect = Exception("disk full")

        store = _mock_store_with_refs({PAPER_A: REFS_A, PAPER_B: REFS_B})
        analyzer = CouplingAnalyzer(store, repo=failing_repo)

        # Must not raise even though repo.record raises.
        result = analyzer.analyze_pair(PAPER_A, PAPER_B)
        assert result.coupling_strength == pytest.approx(3 / 7, rel=1e-6)

    def test_cache_write_failure_logs_error(
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
            analyzer.analyze_pair(PAPER_A, PAPER_B)

        events = [
            e for e in logs if e.get("event") == "coupling_analyzer_cache_write_failed"
        ]
        assert len(events) == 1
        assert "disk full" in events[0]["error"]
