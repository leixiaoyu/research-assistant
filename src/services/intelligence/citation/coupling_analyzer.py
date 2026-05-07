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
``analyze_for_paper`` uses the cache indirectly — each underlying
``analyze_pair`` call checks the cache and writes the result if a repo
is wired in.

Async safety
------------
Both public methods are ``async def`` wrapping sync DB/graph work via
``asyncio.to_thread`` — the canonical pattern from CLAUDE.md "SQLite
write retry" and mirroring :meth:`InfluenceScorer.compute_for_paper`.
``analyze_for_paper`` fans out concurrent pair evaluations using
``asyncio.gather`` with a bounded semaphore (concurrency 10).

Failure semantics
-----------------
- Zero-reference paper → ``coupling_strength = 0.0``, no exception.
- Invalid paper id → :class:`ValueError` with a clear message.
- Cache write failure → swallowed (logged at ERROR level), in-memory
  result still returned.
- ``candidates`` exceeds :data:`MAX_CANDIDATES` → :class:`ValueError`.
- ``top_k`` exceeds :data:`MAX_TOP_K` → clamped to ``MAX_TOP_K``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

import structlog

from src.services.intelligence.citation._id_validation import (
    CANONICAL_NODE_ID_PATTERN,
    PAPER_ID_MAX_LENGTH,
)
from src.services.intelligence.citation.models import CouplingResult
from src.services.intelligence.models import EdgeType
from src.storage.intelligence_graph import SQLiteGraphStore
from src.storage.intelligence_graph.connection import _trunc

if TYPE_CHECKING:
    from src.services.intelligence.citation.coupling_repository import (
        CitationCouplingRepository,
    )

logger = structlog.get_logger(__name__)

# Strict allow-list mirrored from _id_validation (single source of truth).
_PAPER_ID_PATTERN = CANONICAL_NODE_ID_PATTERN
_PAPER_ID_MAX_LENGTH = PAPER_ID_MAX_LENGTH

# DoS guard: maximum number of candidates accepted by analyze_for_paper.
MAX_CANDIDATES: int = 10_000

# DoS guard: maximum top_k that may be requested.
MAX_TOP_K: int = 1_000

# Bounded concurrency for analyze_for_paper fan-out (mirrors MultiProviderMonitor).
_ANALYZE_FOR_PAPER_CONCURRENCY: int = 10

# DoS guard: cap on the number of outgoing CITES edges fetched per paper.
# Reference sets larger than this are truncated after emitting an audit log.
_MAX_REFERENCES: int = 50_000

# DoS cap: if either paper has more inbound CITES edges than this, the full
# co-citation walk is skipped entirely and 0 is returned as a sentinel.
# Rationale: 50K edges × ~100 bytes ≈ 5MB join; SQLite degrades >1s past this
# point.  No useful estimate can be produced without an expensive subset query
# that defeats the purpose of the guard.
MAX_INBOUND_CITERS_FOR_CO_CITATION: int = 50_000


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

    async def analyze_pair(
        self,
        paper_a_id: str,
        paper_b_id: str,
    ) -> CouplingResult:
        """Compute (or return cached) coupling between two papers.

        Reads ``EdgeType.CITES`` outgoing edges for each paper from the
        graph store to obtain their reference sets, then computes the
        Jaccard similarity.

        Async safety:
            All repository and graph-store calls are wrapped in
            ``asyncio.to_thread`` so synchronous DB/graph work does not
            stall the event loop — mirrors
            :meth:`InfluenceScorer.compute_for_paper`.

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
            cached = await asyncio.to_thread(self._repo.get, paper_a_id, paper_b_id)
            if cached is not None:
                return cached

        result = await asyncio.to_thread(self._compute_pair, paper_a_id, paper_b_id)

        # Persist to cache (swallow errors so the caller still gets the result).
        if self._repo is not None:
            try:
                await asyncio.to_thread(self._repo.record, result)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "coupling_analyzer_cache_write_failed",
                    paper_a_id=paper_a_id,
                    paper_b_id=paper_b_id,
                    error=_trunc(exc),
                )

        return result

    async def analyze_for_paper(
        self,
        paper_id: str,
        candidates: list[str],
        top_k: int = 10,
    ) -> list[CouplingResult]:
        """Find the top-K most coupled papers from a candidate list.

        Computes ``analyze_pair(paper_id, candidate)`` for each entry in
        ``candidates`` concurrently (bounded to
        :data:`_ANALYZE_FOR_PAPER_CONCURRENCY` simultaneous tasks via a
        semaphore), then returns the ``top_k`` results sorted descending
        by ``coupling_strength``.

        Papers whose coupling strength is 0.0 are included in the sort
        so the caller has full visibility; it is their responsibility to
        filter if they want only meaningful couplings.

        Args:
            paper_id: The paper to compare against.
            candidates: Other papers to compare with. Must not contain
                ``paper_id`` itself (each element is validated; the
                self-pair check in ``analyze_pair`` will raise if one
                slips through). Must not exceed :data:`MAX_CANDIDATES`.
            top_k: Maximum number of results to return. Must be >= 1.
                Values above :data:`MAX_TOP_K` are clamped silently.

        Returns:
            Up to ``top_k`` :class:`CouplingResult` objects sorted by
            ``coupling_strength`` descending, then by ``paper_b_id``
            ascending for a stable tie-break.

        Raises:
            ValueError: If ``paper_id`` is malformed, ``top_k < 1``, or
                ``len(candidates)`` exceeds :data:`MAX_CANDIDATES`.
        """
        _validate_paper_id(paper_id)
        if top_k < 1:
            raise ValueError(f"top_k must be >= 1, got {top_k}")
        if len(candidates) > MAX_CANDIDATES:
            raise ValueError(
                f"candidates length {len(candidates)} exceeds MAX_CANDIDATES "
                f"({MAX_CANDIDATES})"
            )
        top_k = min(top_k, MAX_TOP_K)

        sem = asyncio.Semaphore(_ANALYZE_FOR_PAPER_CONCURRENCY)

        async def _bounded(candidate: str) -> CouplingResult:
            async with sem:
                return await self.analyze_pair(paper_id, candidate)

        results: list[CouplingResult] = list(
            await asyncio.gather(*[_bounded(c) for c in candidates])
        )

        results.sort(key=lambda r: (-r.coupling_strength, r.paper_b_id))
        return results[:top_k]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_co_citation_count(
        self,
        paper_a_id: str,
        paper_b_id: str,
    ) -> int:
        """Count distinct papers that cite both ``paper_a_id`` and ``paper_b_id``.

        Implements the reverse-edge walk for co-citation (Issue #148).
        Delegates the SQL to :meth:`SQLiteGraphStore.get_papers_citing_both`
        so no raw SQL lives in the analyzer layer.

        DoS guard:
            If either paper has > :data:`MAX_INBOUND_CITERS_FOR_CO_CITATION`
            inbound CITES edges, the walk is **skipped entirely** and ``0`` is
            returned as a sentinel value.  A
            ``coupling_co_citation_truncated`` audit event is emitted so
            operators can monitor truncation frequency.

            The previous implementation fetched the full shared-citer set
            anyway and applied sampling math that reduced to an identity
            (``round(sample_size * len(shared) / sample_size) == len(shared)``).
            That approach provided no DoS protection.  The correct fix is to
            skip the expensive ``get_papers_citing_both`` call entirely when
            the DoS cap is exceeded; no useful estimate can be produced without
            running an expensive subset query that defeats the purpose of the
            guard.

        Args:
            paper_a_id: First paper (already validated, != paper_b_id).
            paper_b_id: Second paper (already validated).

        Returns:
            Count of third-party papers that cite both inputs.  0 when either
            paper has no inbound citations, when no shared citer exists, or
            when the DoS cap is exceeded (sentinel).
        """
        count_a = self.store.get_inbound_citer_count(paper_a_id)
        count_b = self.store.get_inbound_citer_count(paper_b_id)

        offending_count = max(count_a, count_b)
        if offending_count > MAX_INBOUND_CITERS_FOR_CO_CITATION:
            logger.warning(
                "coupling_co_citation_truncated",
                paper_a_id=paper_a_id,
                paper_b_id=paper_b_id,
                inbound_count=offending_count,
                cap=MAX_INBOUND_CITERS_FOR_CO_CITATION,
            )
            # Skip the expensive walk entirely — return 0 as a sentinel.
            # Callers are expected to treat 0 under truncation as
            # "count unavailable" rather than "no co-citation".
            return 0

        return self.store.count_papers_citing_both(paper_a_id, paper_b_id)

    def _get_references(self, paper_id: str) -> frozenset[str]:
        """Return the set of paper ids that ``paper_id`` references.

        Reads outgoing ``CITES`` edges from the graph store.  Each such
        edge's ``target_id`` is one reference.

        If the edge count exceeds :data:`_MAX_REFERENCES`, the list is
        truncated and a ``coupling_references_truncated`` audit event is
        emitted so operators can monitor unexpectedly dense reference
        sets.

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
        if len(edges) > _MAX_REFERENCES:
            logger.warning(
                "coupling_references_truncated",
                paper_id=paper_id,
                fetched=len(edges),
                cap=_MAX_REFERENCES,
            )
            edges = edges[:_MAX_REFERENCES]
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

        co_citation_count = self._compute_co_citation_count(paper_a_id, paper_b_id)

        logger.info(
            "coupling_analyzer_pair_computed",
            paper_a_id=paper_a_id,
            paper_b_id=paper_b_id,
            shared=len(shared),
            union=len(union),
            coupling_strength=strength,
            co_citation_count=co_citation_count,
        )

        return CouplingResult(
            paper_a_id=paper_a_id,
            paper_b_id=paper_b_id,
            shared_references=sorted(shared),
            coupling_strength=strength,
            co_citation_count=co_citation_count,
        )
