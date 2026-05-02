"""Citation influence scorer (Milestone 9.2 — REQ-9.2.4 / Issue #129).

Computes per-paper influence metrics over the citation graph:

- ``citation_count`` — direct from the stored CitationNode.
- ``citation_velocity`` — citations per year since publication.
- ``pagerank_score`` — delegated to
  :func:`GraphAlgorithms.pagerank` (the single source of truth for
  PageRank in this codebase). We never reimplement PageRank here.
- ``hub_score`` / ``authority_score`` — HITS power iteration on the
  citation adjacency matrix. Skipped (zeros) when the graph exceeds
  ``MAX_GRAPH_NODES_FOR_HITS`` to bound CPU.

Persistence
-----------
Results are cached in the ``citation_influence_metrics`` table
introduced by V4 of the migration manager. ``compute_for_paper`` checks
the cache first; if the row's ``computed_at`` is within ``CACHE_TTL``
(7 days), the cached row is returned and the expensive PageRank /
HITS work is skipped. ``compute_for_graph`` is the bulk variant: a
single PageRank invocation covers all requested nodes, then the rows
are upserted in one ``BEGIN IMMEDIATE`` transaction so partial-write
recovery is straightforward.

Failure semantics
-----------------
- HITS skip on oversize graph emits
  ``influence_scorer_hits_skipped_oversize_graph`` (audit-write so ops
  can grep) and returns hub/authority = 0.0. PageRank still runs.
- Missing publication date emits
  ``influence_scorer_velocity_skipped_missing_date`` and returns
  velocity = 0.0.
- Cache write failures DO NOT cause the API call to fail — the
  computed metrics are still returned to the caller. The cache miss
  is logged via ``influence_scorer_cache_write_failed`` so ops can
  investigate disk pressure / migration drift.
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.services.intelligence.models import EdgeType, NodeType
from src.storage.intelligence_graph import (
    GraphAlgorithms,
    SQLiteGraphStore,
    open_connection,
)

logger = structlog.get_logger(__name__)


# Hard cap on the graph size for which HITS is computed inline. Above
# this threshold we skip HITS (returning 0.0 for hub/authority) to
# bound CPU; PageRank is still computed because GraphAlgorithms.pagerank
# uses a fixed-iteration count and scales linearly. 10K nodes is the
# documented soft cap for the SQLite-backed graph (see
# MigrationManager.NODE_COUNT_WARNING_THRESHOLD = 75K) — well below the
# point where SQLite becomes the bottleneck, well above realistic
# Phase-9 corpora.
MAX_GRAPH_NODES_FOR_HITS = 10_000

# Cached InfluenceMetrics rows are returned without recomputation if
# their ``computed_at`` is within this window. Spec REQ-9.2.4 calls for
# 7 days; tests pass smaller values via the constructor.
DEFAULT_CACHE_TTL = timedelta(days=7)

# HITS convergence parameters. Standard values for power iteration —
# 100 iterations is well above what HITS needs to converge on a
# realistic citation graph (typically <30), and 1e-6 is the precision
# at which downstream consumers (recommender) cannot tell the
# difference.
_HITS_MAX_ITERATIONS = 100
_HITS_EPSILON = 1e-6

# Strict allow-list mirroring the providers' / crawler's paper_id
# pattern. Defense-in-depth at the scorer boundary.
_PAPER_ID_PATTERN = re.compile(r"^[A-Za-z0-9:._-]+$")
_PAPER_ID_MAX_LENGTH = 512


class InfluenceMetrics(BaseModel):
    """Influence metrics for a single paper (REQ-9.2.4)."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str = Field(..., min_length=1, max_length=512)
    citation_count: int = Field(default=0, ge=0)
    citation_velocity: float = Field(default=0.0, ge=0.0)
    pagerank_score: float = Field(default=0.0, ge=0.0, le=1.0)
    hub_score: float = Field(default=0.0, ge=0.0)
    authority_score: float = Field(default=0.0, ge=0.0)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InfluenceScorer:
    """Compute and cache per-paper influence metrics.

    Caching contract: ``compute_for_paper`` consults the
    ``citation_influence_metrics`` table first. Rows whose
    ``computed_at`` is within :data:`CACHE_TTL` are returned verbatim
    (PageRank / HITS NOT re-invoked). Older rows are recomputed and
    upserted.
    """

    def __init__(
        self,
        store: SQLiteGraphStore,
        *,
        cache_ttl: timedelta = DEFAULT_CACHE_TTL,
        now: Optional[datetime] = None,
    ) -> None:
        """Initialise the scorer.

        Args:
            store: A ``SQLiteGraphStore`` whose schema is at V4 or later.
                We rely on ``citation_influence_metrics`` (V4) and on
                ``GraphAlgorithms``-friendly read primitives
                (``_list_node_ids``, ``_list_edges_by_types``).
            cache_ttl: How long a cached row remains valid. Default is
                7 days per spec.
            now: Injectable "current time" for tests. Defaults to
                ``datetime.now(timezone.utc)`` evaluated on each lookup.
        """
        self.store = store
        self.cache_ttl = cache_ttl
        self._now_override = now

    @classmethod
    def from_paths(
        cls,
        *,
        db_path: Path | str,
        cache_ttl: timedelta = DEFAULT_CACHE_TTL,
    ) -> "InfluenceScorer":
        """Convenience factory mirroring CitationCrawler.from_paths."""
        store = SQLiteGraphStore(db_path)
        store.initialize()
        return cls(store=store, cache_ttl=cache_ttl)

    def _now(self) -> datetime:
        """Return the current UTC time, honoring the test override."""
        if self._now_override is not None:
            return self._now_override
        return datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compute_for_paper(self, paper_id: str) -> InfluenceMetrics:
        """Compute (or return cached) influence metrics for one paper.

        Cache hit: returns the stored row without invoking PageRank.
        Cache miss: runs PageRank + HITS over the whole graph, writes
        the row, and returns the computed metrics.

        Raises:
            ValueError: If ``paper_id`` is malformed.
        """
        self._validate_paper_id(paper_id)

        cached = self._read_cache(paper_id)
        if cached is not None and self._is_fresh(cached.computed_at):
            return cached

        # Cache miss → compute over the whole graph (PageRank is
        # graph-global; computing it for one node alone would be
        # nonsensical). HITS is also global; skipped on oversize.
        all_metrics = await self._compute_metrics_for_graph(target_ids={paper_id})
        metrics = all_metrics.get(
            paper_id,
            InfluenceMetrics(paper_id=paper_id, computed_at=self._now()),
        )
        self._write_cache([metrics])
        return metrics

    async def compute_for_graph(self, node_ids: list[str]) -> list[InfluenceMetrics]:
        """Bulk compute metrics for a set of papers.

        One PageRank invocation; one HITS invocation; one batched
        upsert. Returns metrics in the same order as ``node_ids``.

        Raises:
            ValueError: If any ``node_id`` is malformed.
        """
        for nid in node_ids:
            self._validate_paper_id(nid)
        if not node_ids:
            return []

        target_set = set(node_ids)
        computed = await self._compute_metrics_for_graph(target_ids=target_set)
        # Ensure every requested id has a row; missing ones get a
        # baseline-zero metric so callers don't have to special-case
        # "node not in graph yet".
        out: list[InfluenceMetrics] = []
        for nid in node_ids:
            metrics = computed.get(
                nid,
                InfluenceMetrics(paper_id=nid, computed_at=self._now()),
            )
            out.append(metrics)
        self._write_cache(out)
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_paper_id(paper_id: str) -> None:
        if not isinstance(paper_id, str) or not paper_id.strip():
            raise ValueError("paper_id must be a non-empty string")
        if len(paper_id) > _PAPER_ID_MAX_LENGTH:
            raise ValueError(
                f"paper_id length {len(paper_id)} exceeds max "
                f"{_PAPER_ID_MAX_LENGTH}"
            )
        if not _PAPER_ID_PATTERN.match(paper_id):
            raise ValueError(
                f"Invalid paper_id format: {paper_id!r}. "
                "Allowed: alphanumeric, colons, periods, hyphens, underscores."
            )

    def _is_fresh(self, computed_at: datetime) -> bool:
        """True iff ``computed_at`` is within the TTL window."""
        return self._now() - computed_at < self.cache_ttl

    async def _compute_metrics_for_graph(
        self, target_ids: set[str]
    ) -> dict[str, InfluenceMetrics]:
        """Run PageRank + HITS over the graph; assemble per-paper metrics.

        Only nodes in ``target_ids`` end up in the returned dict — the
        graph-global computations cover every node, but we project to
        the requested subset to keep the cache write batch small.

        PageRank delegates to ``GraphAlgorithms.pagerank`` (the single
        source of truth for PageRank in this codebase). HITS is
        implemented inline because no shared algorithm exists yet — and
        is wrapped in ``asyncio.to_thread`` so its O(N*iter) inner loop
        does not stall the event loop.
        """
        # PageRank delegation. Single source of truth.
        pagerank = await asyncio.to_thread(
            GraphAlgorithms.pagerank,
            self.store,
            edge_types=[EdgeType.CITES.value],
            damping=0.85,
            node_type=NodeType.PAPER,
        )

        # HITS — skipped on oversize graphs.
        node_count = self.store.get_node_count(node_type=NodeType.PAPER)
        if node_count > MAX_GRAPH_NODES_FOR_HITS:
            logger.warning(
                "influence_scorer_hits_skipped_oversize_graph",
                node_count=node_count,
                limit=MAX_GRAPH_NODES_FOR_HITS,
            )
            hub_scores: dict[str, float] = {}
            authority_scores: dict[str, float] = {}
        else:
            hub_scores, authority_scores = await asyncio.to_thread(self._compute_hits)

        out: dict[str, InfluenceMetrics] = {}
        for paper_id in target_ids:
            node = self.store.get_node(paper_id)
            citation_count = self._extract_citation_count(node)
            velocity = self._compute_velocity(node, paper_id)
            # PageRank scores from GraphAlgorithms can mathematically
            # exceed 1.0 for tiny graphs (e.g. a single isolated node
            # gets 1.0/n = 1.0 + (1-d)/n adjustments per iter). Clamp to
            # [0.0, 1.0] for the InfluenceMetrics contract; the relative
            # ordering is preserved.
            pr = min(1.0, max(0.0, pagerank.get(paper_id, 0.0)))
            out[paper_id] = InfluenceMetrics(
                paper_id=paper_id,
                citation_count=citation_count,
                citation_velocity=velocity,
                pagerank_score=pr,
                hub_score=hub_scores.get(paper_id, 0.0),
                authority_score=authority_scores.get(paper_id, 0.0),
                computed_at=self._now(),
            )
        return out

    def _compute_hits(self) -> tuple[dict[str, float], dict[str, float]]:
        """HITS power iteration on the CITES adjacency.

        Convergence: max ``_HITS_MAX_ITERATIONS`` iterations or
        per-iteration delta below ``_HITS_EPSILON`` (whichever first).
        Empty graphs return ({}, {}).
        """
        node_ids = self.store._list_node_ids(node_type=NodeType.PAPER)
        if not node_ids:
            return {}, {}

        edges = self.store._list_edges_by_types([EdgeType.CITES.value])
        node_set = set(node_ids)
        # incoming[v] = list of u where u -> v (citing -> cited)
        # outgoing[u] = list of v where u -> v
        incoming: dict[str, list[str]] = {nid: [] for nid in node_ids}
        outgoing: dict[str, list[str]] = {nid: [] for nid in node_ids}
        for source, target in edges:
            if source in node_set and target in node_set:
                outgoing[source].append(target)
                incoming[target].append(source)

        hubs: dict[str, float] = {nid: 1.0 for nid in node_ids}
        authorities: dict[str, float] = {nid: 1.0 for nid in node_ids}

        for _ in range(_HITS_MAX_ITERATIONS):
            # Authority update: a(v) = sum of h(u) for all u -> v
            new_authorities: dict[str, float] = {}
            for nid in node_ids:
                new_authorities[nid] = sum(hubs[u] for u in incoming[nid])
            # Hub update: h(u) = sum of a(v) for all u -> v
            new_hubs: dict[str, float] = {}
            for nid in node_ids:
                new_hubs[nid] = sum(new_authorities[v] for v in outgoing[nid])

            # L2 normalize to prevent score blow-up.
            auth_norm = self._l2_norm(new_authorities)
            hub_norm = self._l2_norm(new_hubs)
            if auth_norm > 0:
                new_authorities = {k: v / auth_norm for k, v in new_authorities.items()}
            if hub_norm > 0:
                new_hubs = {k: v / hub_norm for k, v in new_hubs.items()}

            # Convergence check on max delta across either vector.
            delta = max(
                max(abs(new_authorities[nid] - authorities[nid]) for nid in node_ids),
                max(abs(new_hubs[nid] - hubs[nid]) for nid in node_ids),
            )
            authorities = new_authorities
            hubs = new_hubs
            if delta < _HITS_EPSILON:
                break

        return hubs, authorities

    @staticmethod
    def _l2_norm(scores: dict[str, float]) -> float:
        """L2 norm of a score vector."""
        total: float = sum(v * v for v in scores.values())
        return float(total**0.5)

    def _compute_velocity(
        self, node, paper_id: str  # noqa: ANN001  - GraphNode | None
    ) -> float:
        """Citations per year since publication.

        Returns 0.0 (with audit-trail log event) when the publication
        date / year is unknown — there is no defensible velocity to
        report in that case, but downstream consumers don't want to
        special-case None.
        """
        if node is None:
            return 0.0
        props = node.properties or {}
        # Prefer publication_date (full date), fall back to year-only.
        pub_date_str = props.get("publication_date")
        year = props.get("year")
        citation_count = int(props.get("citation_count") or 0)

        pub_date: Optional[date] = None
        if pub_date_str:
            try:
                pub_date = date.fromisoformat(pub_date_str)
            except (TypeError, ValueError):
                pub_date = None
        if pub_date is None and year is not None:
            try:
                pub_date = date(int(year), 1, 1)
            except (TypeError, ValueError):
                pub_date = None

        if pub_date is None:
            logger.warning(
                "influence_scorer_velocity_skipped_missing_date",
                paper_id=paper_id,
            )
            return 0.0

        today = self._now().date()
        # Whole years only — fractional years would make the metric
        # noisier than it deserves, and the spec says "per year".
        years_since = max(1, today.year - pub_date.year)
        return citation_count / years_since

    @staticmethod
    def _extract_citation_count(node) -> int:  # noqa: ANN001 - GraphNode | None
        """Pull citation_count out of a node's properties dict."""
        if node is None:
            return 0
        return int((node.properties or {}).get("citation_count") or 0)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _read_cache(self, paper_id: str) -> Optional[InfluenceMetrics]:
        """Read a cached metrics row by paper_id; None if absent."""
        with open_connection(self.store.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT paper_id, citation_count, citation_velocity,
                       pagerank_score, hub_score, authority_score,
                       computed_at
                FROM citation_influence_metrics
                WHERE paper_id = ?
                """,
                (paper_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return InfluenceMetrics(
            paper_id=row["paper_id"],
            citation_count=row["citation_count"],
            citation_velocity=row["citation_velocity"],
            pagerank_score=row["pagerank_score"],
            hub_score=row["hub_score"],
            authority_score=row["authority_score"],
            computed_at=datetime.fromisoformat(row["computed_at"]),
        )

    def _write_cache(self, rows: list[InfluenceMetrics]) -> None:
        """Upsert metrics rows in a single BEGIN IMMEDIATE transaction.

        Failure here is logged but does NOT propagate — the computed
        metrics are still returned to the caller. The next read will
        see the cache miss and recompute.
        """
        if not rows:
            return
        payload = [
            (
                m.paper_id,
                m.citation_count,
                m.citation_velocity,
                m.pagerank_score,
                m.hub_score,
                m.authority_score,
                m.computed_at.isoformat(),
            )
            for m in rows
        ]
        try:
            with open_connection(self.store.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.executemany(
                    """
                    INSERT INTO citation_influence_metrics (
                        paper_id, citation_count, citation_velocity,
                        pagerank_score, hub_score, authority_score,
                        computed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(paper_id) DO UPDATE SET
                        citation_count = excluded.citation_count,
                        citation_velocity = excluded.citation_velocity,
                        pagerank_score = excluded.pagerank_score,
                        hub_score = excluded.hub_score,
                        authority_score = excluded.authority_score,
                        computed_at = excluded.computed_at
                    """,
                    payload,
                )
                conn.commit()
        except sqlite3.Error as exc:
            # Audit-write the failure path so ops can grep for cache
            # write outages. Returning the in-memory metrics preserves
            # observability for the caller.
            logger.error(
                "influence_scorer_cache_write_failed",
                row_count=len(rows),
                error=str(exc),
            )
