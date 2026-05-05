"""Bibliographic coupling analyzer (Milestone 9.2 — REQ-9.2.3 / Issue #128).

Computes Jaccard similarity over shared references to identify related papers:

    coupling_strength = |shared_refs(A) ∩ shared_refs(B)|
                        ─────────────────────────────────
                        |shared_refs(A) ∪ shared_refs(B)|

The degenerate case where both papers have zero references is handled
gracefully: ``coupling_strength = 0.0`` rather than raising a
``ZeroDivisionError``.

Persistence
-----------
Computed pairs are cached in the ``citation_coupling`` table introduced by
``MIGRATION_V6_CITATION_COUPLING_CACHE``. Cache CRUD is delegated to
:class:`CitationCouplingRepository` so the analyzer never touches the
DB schema directly.  ``analyze_pair`` checks the cache first; a cache
miss computes Jaccard and upserts the result via the repository.
``analyze_for_paper`` does not consult the cache (it is a bulk scatter
call; caching is left to the underlying ``analyze_pair`` calls if the
caller wishes to compose them).

Failure semantics
-----------------
- Zero-reference paper → ``coupling_strength = 0.0``, no exception.
- Invalid paper id → :class:`ValueError` with a clear message.
- Cache write failure → swallowed (logged at ERROR level), in-memory
  result still returned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

from src.services.intelligence.citation._id_validation import (
    CANONICAL_NODE_ID_PATTERN,
    PAPER_ID_MAX_LENGTH,
)
from src.services.intelligence.citation.models import CouplingResult
from src.services.intelligence.models import EdgeType
from src.storage.intelligence_graph import SQLiteGraphStore

if TYPE_CHECKING:
    from src.services.intelligence.citation.coupling_repository import (
        CitationCouplingRepository,
    )

logger = structlog.get_logger(__name__)

# Strict allow-list mirrored from _id_validation (single source of truth).
_PAPER_ID_PATTERN = CANONICAL_NODE_ID_PATTERN
_PAPER_ID_MAX_LENGTH = PAPER_ID_MAX_LENGTH


def _validate_paper_id(paper_id: str) -> None:
    """Validate a canonical node id at the analyzer boundary.

    Mirrors :meth:`InfluenceScorer._validate_paper_id` exactly so the
    two analyzers present a consistent public contract.

    Args:
        paper_id: Caller-supplied paper id.

    Raises:
        ValueError: If the id is empty, too long, or contains illegal chars.
    """
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("paper_id must be a non-empty string")
    if len(paper_id) > _PAPER_ID_MAX_LENGTH:
        raise ValueError(
            f"paper_id length {len(paper_id)} exceeds max {_PAPER_ID_MAX_LENGTH}"
        )
    if not _PAPER_ID_PATTERN.match(paper_id):
        raise ValueError(
            f"Invalid paper_id format: {paper_id!r}. "
            "Allowed: alphanumeric, colons, periods, hyphens, underscores."
        )


class CouplingAnalyzer:
    """Compute bibliographic coupling scores between papers.

    Uses :class:`~src.storage.intelligence_graph.SQLiteGraphStore` as the
    source of reference edges (``EdgeType.CITES`` outgoing from a paper
    represent what it references).

    Args:
        store: Graph store providing edge lookups.
        repo: Optional :class:`CitationCouplingRepository` for caching.
            When ``None``, results are computed but not persisted.

    Example::

        store = SQLiteGraphStore("data/graph.db")
        store.initialize()
        analyzer = CouplingAnalyzer(store)
        result = analyzer.analyze_pair("paper:s2:aaa", "paper:s2:bbb")
        print(result.coupling_strength)
    """

    def __init__(
        self,
        store: SQLiteGraphStore,
        *,
        repo: Optional["CitationCouplingRepository"] = None,
    ) -> None:
        self.store = store
        self._repo = repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_pair(
        self,
        paper_a_id: str,
        paper_b_id: str,
    ) -> CouplingResult:
        """Compute (or return cached) coupling between two papers.

        Reads ``EdgeType.CITES`` outgoing edges for each paper from the
        graph store to obtain their reference sets, then computes the
        Jaccard similarity.

        Args:
            paper_a_id: Canonical node id of the first paper.
            paper_b_id: Canonical node id of the second paper.

        Returns:
            A :class:`CouplingResult` with the Jaccard strength and the
            sorted list of shared reference ids.

        Raises:
            ValueError: If either id is malformed, or if
                ``paper_a_id == paper_b_id`` (self-pair).
        """
        _validate_paper_id(paper_a_id)
        _validate_paper_id(paper_b_id)
        if paper_a_id == paper_b_id:
            raise ValueError(
                f"paper_a_id and paper_b_id must differ; got {paper_a_id!r} for both."
            )

        # Consult cache first (if a repo is wired in).
        if self._repo is not None:
            cached = self._repo.get(paper_a_id, paper_b_id)
            if cached is not None:
                return cached

        result = self._compute_pair(paper_a_id, paper_b_id)

        # Persist to cache (swallow errors so the caller still gets the result).
        if self._repo is not None:
            try:
                self._repo.record(result)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "coupling_analyzer_cache_write_failed",
                    paper_a_id=paper_a_id,
                    paper_b_id=paper_b_id,
                    error=str(exc)[:200],
                )

        return result

    def analyze_for_paper(
        self,
        paper_id: str,
        candidates: list[str],
        top_k: int = 10,
    ) -> list[CouplingResult]:
        """Find the top-K most coupled papers from a candidate list.

        Computes ``analyze_pair(paper_id, candidate)`` for each entry in
        ``candidates``, then returns the ``top_k`` results sorted
        descending by ``coupling_strength``.

        Papers whose coupling strength is 0.0 are included in the sort
        so the caller has full visibility; it is their responsibility to
        filter if they want only meaningful couplings.

        Args:
            paper_id: The paper to compare against.
            candidates: Other papers to compare with. Must not contain
                ``paper_id`` itself (each element is validated; the
                self-pair check in ``analyze_pair`` will raise if one
                slips through).
            top_k: Maximum number of results to return. Must be >= 1.

        Returns:
            Up to ``top_k`` :class:`CouplingResult` objects sorted by
            ``coupling_strength`` descending, then by ``paper_b_id``
            ascending for a stable tie-break.

        Raises:
            ValueError: If ``paper_id`` is malformed, or ``top_k < 1``.
        """
        _validate_paper_id(paper_id)
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")

        results: list[CouplingResult] = []
        for candidate in candidates:
            result = self.analyze_pair(paper_id, candidate)
            results.append(result)

        results.sort(key=lambda r: (-r.coupling_strength, r.paper_b_id))
        return results[:top_k]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_references(self, paper_id: str) -> frozenset[str]:
        """Return the set of paper ids that ``paper_id`` references.

        Reads outgoing ``CITES`` edges from the graph store.  Each such
        edge's ``target_id`` is one reference.

        Args:
            paper_id: Canonical node id.

        Returns:
            Frozenset of referenced paper ids.  Empty if the paper has
            no outgoing citation edges.
        """
        edges = self.store.get_edges(
            paper_id,
            direction="outgoing",
            edge_type=EdgeType.CITES,
        )
        return frozenset(edge.target_id for edge in edges)

    def _compute_pair(
        self,
        paper_a_id: str,
        paper_b_id: str,
    ) -> CouplingResult:
        """Core Jaccard computation (always runs, no cache interaction).

        Args:
            paper_a_id: First paper (already validated, != paper_b_id).
            paper_b_id: Second paper (already validated).

        Returns:
            A :class:`CouplingResult` with the computed metrics.
        """
        refs_a = self._get_references(paper_a_id)
        refs_b = self._get_references(paper_b_id)

        shared = refs_a & refs_b
        union = refs_a | refs_b

        if not union:
            # Both papers have zero references — coupling is undefined;
            # return 0.0 per spec and emit an audit event.
            logger.info(
                "coupling_analyzer_skipped_no_refs",
                paper_a_id=paper_a_id,
                paper_b_id=paper_b_id,
            )
            strength = 0.0
        else:
            strength = len(shared) / len(union)

        logger.info(
            "coupling_analyzer_pair_computed",
            paper_a_id=paper_a_id,
            paper_b_id=paper_b_id,
            shared=len(shared),
            union=len(union),
            coupling_strength=strength,
        )

        return CouplingResult(
            paper_a_id=paper_a_id,
            paper_b_id=paper_b_id,
            shared_references=sorted(shared),
            coupling_strength=strength,
            co_citation_count=0,
        )
