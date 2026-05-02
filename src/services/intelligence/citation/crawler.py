"""BFS citation chain crawler (Milestone 9.2 — REQ-9.2.2 / Issue #127).

This module walks the citation graph **breadth-first** from a seed paper,
expanding each visited paper's references / citations one provider hop
at a time. Per spec Section 5.2:

- Bounded by ``max_depth`` (1-3) and ``max_papers_per_level`` (10-200).
- Direction filter: forward (papers citing the seed), backward
  (papers cited by the seed), or both.
- Ranking inside a level: ``influentialCitationCount`` DESC, then
  ``citationCount`` DESC, then ``publication_date`` (year fallback)
  DESC. Deterministic so re-runs are reproducible.
- Per-crawl API budget: ``MAX_API_CALLS_PER_CRAWL`` (default 1000) —
  emit a single ``citation_crawl_budget_exhausted`` event and stop.
- Concurrency cap: ``asyncio.Semaphore(10)`` so a single crawl cannot
  open more than ten in-flight provider requests at once.

Failure semantics — codified from PR #124's silent-data-loss incident
(see CLAUDE.md "Orchestration Patterns"):

- **Per-paper provider failures** (``APIError`` from S2 / OpenAlex on
  one node) are *fail-soft*: log ``citation_crawl_provider_failed_skipping_node``,
  drop that node from the queue, and keep crawling. This is the
  "Fail-Soft Boundary across independent peers" pattern — one bad
  paper must not poison the entire crawl.
- **Persistence failures** (``GraphStoreError`` on
  ``add_nodes_batch`` / ``add_edges_batch``) are *fail-hard*: log
  ``citation_crawl_persistence_failed_aborting`` and ABORT the entire
  crawl immediately. No further API calls are made; no further nodes
  are persisted. This preserves the "Checked Success" gating —
  expanding a paper whose neighbors we could not persist would corrupt
  the graph silently and leave dangling references.

Reuse, not rebuild
------------------
The crawler **composes** the existing
:class:`SemanticScholarCitationClient` and
:class:`OpenAlexCitationClient` for per-paper expansion. It does not
re-implement HTTP, caching, rate-limiting, SSRF defense, or paging.
For persistence it goes directly to ``GraphStore.add_nodes_batch`` /
``add_edges_batch`` (the bulk APIs the spec mandates), bypassing the
``CitationGraphBuilder`` because the builder's depth=1 fallback /
provider-tagging logic does not match BFS's "one paper at a time"
expansion shape.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import date
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.services.intelligence.citation._id_validation import (
    PAPER_ID_MAX_LENGTH as _PAPER_ID_MAX_LENGTH,
    RAW_PROVIDER_ID_PATTERN as _PAPER_ID_PATTERN,
)
from src.services.intelligence.citation.models import (
    CitationEdge,
    CitationNode,
    CrawlDirection,
)
from src.services.intelligence.citation.openalex_client import (
    OpenAlexCitationClient,
)
from src.services.intelligence.citation.semantic_scholar_client import (
    SemanticScholarCitationClient,
)
from src.services.intelligence.models import GraphStoreError
from src.services.providers.base import APIError
from src.storage.intelligence_graph import GraphStore, SQLiteGraphStore

logger = structlog.get_logger(__name__)


# Hard cap on the total number of provider calls a single ``crawl()`` may
# issue. Defends against runaway expansion when the per-level cap and
# depth cap are both set high. When this is hit the crawler emits a
# single ``citation_crawl_budget_exhausted`` event and stops.
MAX_API_CALLS_PER_CRAWL = 1000

# Concurrency bound on in-flight provider requests within a single
# crawl. The spec's per-level cap (50 by default) and depth cap (2) make
# 10 a comfortable bound: high enough to amortize round-trips, low
# enough to not overwhelm the provider's rate limiter.
_MAX_CONCURRENT_REQUESTS = 10


# Strict allow-list and length cap imported from the canonical single
# source of truth in _id_validation.py (H-A1).  The aliases above
# (``_PAPER_ID_PATTERN`` and ``_PAPER_ID_MAX_LENGTH``) retain the
# underscore-prefixed module-private names so existing call sites
# inside this module need no further changes.


class CrawlConfig(BaseModel):
    """Configuration for one ``CitationCrawler.crawl()`` invocation.

    Defaults match the spec:
    - depth=2, level cap=50, both directions, no citation/year filter.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    max_depth: int = Field(default=2, ge=1, le=3)
    max_papers_per_level: int = Field(default=50, ge=10, le=200)
    direction: CrawlDirection = Field(default=CrawlDirection.BOTH)
    filter_min_citations: int = Field(default=0, ge=0)
    filter_year_min: Optional[int] = Field(default=None, ge=1800, le=2100)


class CrawlResult(BaseModel):
    """Outcome of one crawl. All counters are post-deduplication."""

    model_config = ConfigDict(extra="forbid")

    papers_visited: int = Field(default=0, ge=0)
    levels_reached: int = Field(default=0, ge=0)
    edges_added: int = Field(default=0, ge=0)
    dropped_by_filter: dict[str, int] = Field(default_factory=dict)
    api_calls_made: int = Field(default=0, ge=0)
    budget_exhausted: bool = Field(default=False)
    persistence_aborted: bool = Field(default=False)


class _ExpandResult:
    """Internal DTO from ``_expand_paper``.

    Keeps backward (references) and forward (citations) candidates
    separate so the BFS loop can apply ``top_k`` per direction
    independently (spec REQ-9.2.2 §574-592 — C-3 fix).
    """

    __slots__ = (
        "parent_node",
        "backward_nodes",
        "backward_edges",
        "forward_nodes",
        "forward_edges",
    )

    def __init__(
        self,
        parent_node: Optional[CitationNode],
        backward_nodes: list[CitationNode],
        backward_edges: list[CitationEdge],
        forward_nodes: list[CitationNode],
        forward_edges: list[CitationEdge],
    ) -> None:
        self.parent_node = parent_node
        self.backward_nodes = backward_nodes
        self.backward_edges = backward_edges
        self.forward_nodes = forward_nodes
        self.forward_edges = forward_edges


def sort_by_influence(papers: list[CitationNode]) -> list[CitationNode]:
    """Deterministic ranking for top-k selection within a BFS level.

    Per spec REQ-9.2.2:
    1. ``influentialCitationCount`` DESC (None treated as 0)
    2. ``citationCount`` DESC
    3. ``publication_date`` DESC, falling back to ``year`` (None / missing
       treated as ``date.min`` so unknown-date papers sort last)
    """

    def _key(p: CitationNode) -> tuple[int, int, date]:
        # publication_date is preferred; fall back to year-only papers
        # by synthesising a Jan-1 date so the comparison stays
        # well-typed. None / missing → date.min so the paper sorts last.
        if p.publication_date is not None:
            sort_date = p.publication_date
        elif p.year is not None:
            sort_date = date(p.year, 1, 1)
        else:
            sort_date = date.min
        return (
            p.influential_citation_count or 0,
            p.citation_count or 0,
            sort_date,
        )

    return sorted(papers, key=_key, reverse=True)


class CitationCrawler:
    """BFS citation chain crawler.

    Constructor takes a :class:`GraphStore` and (at least one) provider
    client. The :meth:`from_paths` factory wires the standard collaborators
    for callers that just have a ``db_path``.
    """

    def __init__(
        self,
        store: GraphStore,
        s2_client: Optional[SemanticScholarCitationClient] = None,
        openalex_client: Optional[OpenAlexCitationClient] = None,
    ) -> None:
        if s2_client is None and openalex_client is None:
            raise ValueError(
                "CitationCrawler requires at least one provider client "
                "(s2_client or openalex_client)"
            )
        self.store = store
        self.s2_client = s2_client
        self.openalex_client = openalex_client

    @classmethod
    def from_paths(
        cls,
        *,
        db_path: Path | str,
        s2_client: Optional[SemanticScholarCitationClient] = None,
        openalex_client: Optional[OpenAlexCitationClient] = None,
    ) -> "CitationCrawler":
        """Convenience factory that initialises the SQLite graph store.

        Mirrors :meth:`MonitoringRunner.from_paths` so CLI / scheduler
        callers don't need to remember the two-phase
        construct-then-initialize idiom.
        """
        if s2_client is None and openalex_client is None:
            # Default wiring: build a Semantic Scholar client on demand.
            # API key (if any) is read from the standard env var inside
            # the client constructor.
            s2_client = SemanticScholarCitationClient()
        store = SQLiteGraphStore(db_path)
        store.initialize()
        return cls(
            store=store,
            s2_client=s2_client,
            openalex_client=openalex_client,
        )

    async def crawl(self, seed_paper_id: str, config: CrawlConfig) -> CrawlResult:
        """Walk the citation graph breadth-first from ``seed_paper_id``.

        Args:
            seed_paper_id: The provider-recognized paper id to start from
                (validated against ``_PAPER_ID_PATTERN``).
            config: Crawl configuration (depth, level cap, direction,
                filters).

        Returns:
            A :class:`CrawlResult` summarising what happened.

        Raises:
            ValueError: If ``seed_paper_id`` fails the strict allow-list.
        """
        self._validate_seed(seed_paper_id)

        result = CrawlResult()
        visited: set[str] = {seed_paper_id}
        # Track every node id we have already inserted (or attempted to
        # insert) into the graph. Used to dedupe persistence batches
        # across BFS layers — the seed re-appears as the ``seed_node``
        # of every expansion, and shared neighbours can resurface across
        # branches. Without this, ``add_nodes_batch`` would raise a
        # UNIQUE-constraint error on the duplicate row and abort the
        # crawl unnecessarily.
        persisted_node_ids: set[str] = set()
        # BFS queue stores (paper_id, depth_of_paper). The seed is at
        # depth 0; its neighbours land at depth 1.
        queue: deque[tuple[str, int]] = deque([(seed_paper_id, 0)])

        semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)
        # Per-filter drop counters are surfaced in the result so ops can
        # tell at a glance whether the filter was too aggressive. We
        # track separately for each direction so the ops team can see
        # backward vs. forward attrition (C-3 fix).
        dropped: dict[str, int] = {
            "min_citations_backward": 0,
            "year_min_backward": 0,
            "min_citations_forward": 0,
            "year_min_forward": 0,
        }

        while queue:
            paper_id, depth = queue.popleft()
            # Per spec: process only nodes whose depth is strictly less
            # than max_depth. The seed (depth 0) expands once when
            # max_depth=1, twice when max_depth=2, etc.
            if depth >= config.max_depth:
                continue

            # Budget check BEFORE issuing any provider call for this
            # paper. We may need 1 (single direction) or 2 (BOTH) calls;
            # check conservatively against 1 so we never make a partial
            # set of calls beyond the budget — see issue #127 acceptance.
            if result.api_calls_made >= MAX_API_CALLS_PER_CRAWL:
                result.budget_exhausted = True
                logger.warning(
                    "citation_crawl_budget_exhausted",
                    seed_paper_id=seed_paper_id,
                    api_calls_made=result.api_calls_made,
                    budget=MAX_API_CALLS_PER_CRAWL,
                )
                break

            try:
                expanded = await self._expand_paper(
                    paper_id=paper_id,
                    direction=config.direction,
                    semaphore=semaphore,
                    counter=result,
                )
            except _BudgetExhausted:
                # Budget hit mid-expansion (BOTH directions). Mark and
                # exit the BFS loop. We deliberately do NOT persist
                # whatever partial neighbours came back — the caller's
                # ``budget_exhausted=True`` is the contract.
                result.budget_exhausted = True
                logger.warning(
                    "citation_crawl_budget_exhausted",
                    seed_paper_id=seed_paper_id,
                    api_calls_made=result.api_calls_made,
                    budget=MAX_API_CALLS_PER_CRAWL,
                )
                break
            except APIError as exc:
                # Fail-soft: one paper's provider failure must not abort
                # the whole crawl. Log and skip — the BFS continues with
                # whatever's already in the queue.
                logger.warning(
                    "citation_crawl_provider_failed_skipping_node",
                    seed_paper_id=seed_paper_id,
                    paper_id=paper_id,
                    error=repr(str(exc)[:512]),
                )
                continue

            parent_node = expanded.parent_node

            # Apply filters + rank + cap INDEPENDENTLY per direction
            # (spec REQ-9.2.2 §574-592, C-3 fix). Doing it on the union
            # would let a direction with many candidates starve the other.
            top_k: list[CitationNode] = []
            top_k_edges: list[CitationEdge] = []

            if expanded.backward_nodes:
                bw_kept, bw_kept_edges = self._apply_filters_directional(
                    expanded.backward_nodes,
                    expanded.backward_edges,
                    config,
                    dropped,
                    prefix="backward",
                )
                bw_ranked = sort_by_influence(bw_kept)
                bw_top = bw_ranked[: config.max_papers_per_level]
                bw_ids = {n.paper_id for n in bw_top}
                top_k.extend(bw_top)
                top_k_edges.extend(
                    e
                    for e in bw_kept_edges
                    if e.citing_paper_id in bw_ids or e.cited_paper_id in bw_ids
                )

            if expanded.forward_nodes:
                fw_kept, fw_kept_edges = self._apply_filters_directional(
                    expanded.forward_nodes,
                    expanded.forward_edges,
                    config,
                    dropped,
                    prefix="forward",
                )
                fw_ranked = sort_by_influence(fw_kept)
                fw_top = fw_ranked[: config.max_papers_per_level]
                fw_ids = {n.paper_id for n in fw_top}
                top_k.extend(fw_top)
                top_k_edges.extend(
                    e
                    for e in fw_kept_edges
                    if e.citing_paper_id in fw_ids or e.cited_paper_id in fw_ids
                )

            # Persist this layer. CHECKED SUCCESS: if persistence fails
            # we MUST abort the whole crawl, not just skip the layer —
            # otherwise the next BFS hop would expand a paper we never
            # successfully wrote, leaving dangling edges.
            #
            # ``parent_node`` is the canonical CitationNode the API
            # returned for the paper we're expanding. It must be
            # included so its node row exists in the graph BEFORE the
            # outgoing edges are inserted (FOREIGN KEY constraint). We
            # dedupe via ``persisted_node_ids`` so re-encountering the
            # parent across BFS layers does not raise a UNIQUE error.
            persistence_ok = self._persist_layer(
                paper_id=paper_id,
                parent_node=parent_node,
                related_nodes=top_k,
                edges=top_k_edges,
                seed_paper_id=seed_paper_id,
                persisted_node_ids=persisted_node_ids,
            )
            if not persistence_ok:
                result.persistence_aborted = True
                break

            # Update visited / queue with the kept nodes only. Counters
            # below reflect what actually made it into the graph.
            new_at_this_layer = 0
            for node in top_k:
                if node.paper_id in visited:
                    continue
                visited.add(node.paper_id)
                queue.append((node.paper_id, depth + 1))
                new_at_this_layer += 1

            result.papers_visited += new_at_this_layer
            result.levels_reached = max(result.levels_reached, depth + 1)
            result.edges_added += len(top_k_edges)

        result.dropped_by_filter = dropped
        logger.info(
            "citation_crawl_complete",
            seed_paper_id=seed_paper_id,
            papers_visited=result.papers_visited,
            levels_reached=result.levels_reached,
            edges_added=result.edges_added,
            api_calls_made=result.api_calls_made,
            budget_exhausted=result.budget_exhausted,
            persistence_aborted=result.persistence_aborted,
            dropped=dropped,
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_seed(seed_paper_id: str) -> None:
        """Reject malformed seed ids before issuing any provider call.

        The providers re-validate too; doing it here keeps the bad-id
        error close to the caller and avoids burning a provider hit on
        a guaranteed-to-fail request.
        """
        if not isinstance(seed_paper_id, str) or not seed_paper_id.strip():
            raise ValueError("seed_paper_id must be a non-empty string")
        if len(seed_paper_id) > _PAPER_ID_MAX_LENGTH:
            raise ValueError(
                f"seed_paper_id length {len(seed_paper_id)} exceeds max "
                f"{_PAPER_ID_MAX_LENGTH}"
            )
        if not _PAPER_ID_PATTERN.match(seed_paper_id):
            raise ValueError(
                f"Invalid seed_paper_id format: {seed_paper_id!r}. "
                "Allowed: alphanumeric, colon, period, slash, underscore, hyphen."
            )

    async def _expand_paper(
        self,
        paper_id: str,
        direction: CrawlDirection,
        semaphore: asyncio.Semaphore,
        counter: CrawlResult,
    ) -> _ExpandResult:
        """Fetch references / citations for one paper, applying budget.

        Honors the BFS direction:
        - BACKWARD → references only
        - FORWARD → citations only
        - BOTH → both, in that order

        Each provider call is wrapped in the shared semaphore so the
        in-flight count never exceeds ``_MAX_CONCURRENT_REQUESTS``.

        Returns an :class:`_ExpandResult` that keeps BACKWARD (references)
        and FORWARD (citations) candidates separate so the BFS loop can
        apply ``top_k`` per direction independently (C-3 fix: spec
        REQ-9.2.2 §574-592). Combining them before capping would allow
        a direction with many high-quality candidates to starve the other.

        ``parent_node`` is the canonical :class:`CitationNode` the
        provider returned for ``paper_id``. The crawler must persist it
        so outgoing edges have a valid FK target. ``parent_node`` is
        ``None`` only when no provider call was made (e.g. an unknown
        ``CrawlDirection`` value, defensive).
        """
        parent: Optional[CitationNode] = None
        backward_nodes: list[CitationNode] = []
        backward_edges: list[CitationEdge] = []
        forward_nodes: list[CitationNode] = []
        forward_edges: list[CitationEdge] = []

        if direction in (CrawlDirection.BACKWARD, CrawlDirection.BOTH):
            if counter.api_calls_made >= MAX_API_CALLS_PER_CRAWL:
                raise _BudgetExhausted()
            counter.api_calls_made += 1
            async with semaphore:
                seed, refs, ref_edges = await self._call_references(paper_id)
            parent = seed
            backward_nodes.extend(refs)
            backward_edges.extend(ref_edges)

        if direction in (CrawlDirection.FORWARD, CrawlDirection.BOTH):
            if counter.api_calls_made >= MAX_API_CALLS_PER_CRAWL:
                raise _BudgetExhausted()
            counter.api_calls_made += 1
            async with semaphore:
                seed, cites, cite_edges = await self._call_citations(paper_id)
            # FORWARD-only: parent is the citations seed. BOTH: keep the
            # references seed (semantically identical paper; either is
            # fine — the persistence layer will dedupe by node_id).
            if parent is None:
                parent = seed
            forward_nodes.extend(cites)
            forward_edges.extend(cite_edges)

        return _ExpandResult(
            parent_node=parent,
            backward_nodes=backward_nodes,
            backward_edges=backward_edges,
            forward_nodes=forward_nodes,
            forward_edges=forward_edges,
        )

    async def _call_references(
        self, paper_id: str
    ) -> tuple[CitationNode, list[CitationNode], list[CitationEdge]]:
        """Dispatch to whichever provider is configured for references."""
        client = self.s2_client or self.openalex_client
        # Constructor enforced that at least one client is set.
        assert client is not None
        return await client.get_references(paper_id)

    async def _call_citations(
        self, paper_id: str
    ) -> tuple[CitationNode, list[CitationNode], list[CitationEdge]]:
        """Dispatch to whichever provider is configured for citations."""
        client = self.s2_client or self.openalex_client
        assert client is not None
        return await client.get_citations(paper_id)

    @staticmethod
    def _apply_filters_directional(
        nodes: list[CitationNode],
        edges: list[CitationEdge],
        config: CrawlConfig,
        dropped: dict[str, int],
        prefix: str,
    ) -> tuple[list[CitationNode], list[CitationEdge]]:
        """Drop nodes that fail min_citations / year_min; mirror to edges.

        Per-filter drop counts are accumulated into ``dropped`` under
        direction-specific keys (``{prefix}_min_citations`` /
        ``{prefix}_year_min``) so ops can diagnose backward vs. forward
        attrition independently (C-3 fix).

        Args:
            nodes: Candidate nodes for this direction.
            edges: All edges associated with this direction's candidates.
            config: Crawl configuration (filters).
            dropped: Running drop counters dict (mutated in-place).
            prefix: ``"backward"`` or ``"forward"``.
        """
        min_cit_key = f"min_citations_{prefix}"
        year_min_key = f"year_min_{prefix}"
        kept_nodes: list[CitationNode] = []
        for n in nodes:
            if n.citation_count < config.filter_min_citations:
                dropped[min_cit_key] = dropped.get(min_cit_key, 0) + 1
                continue
            if config.filter_year_min is not None:
                # Papers without a known year are dropped when the
                # filter is set, otherwise we can't honor the contract.
                if n.year is None or n.year < config.filter_year_min:
                    dropped[year_min_key] = dropped.get(year_min_key, 0) + 1
                    continue
            kept_nodes.append(n)

        kept_ids = {n.paper_id for n in kept_nodes}
        kept_edges = [
            e
            for e in edges
            if e.cited_paper_id in kept_ids or e.citing_paper_id in kept_ids
        ]
        return kept_nodes, kept_edges

    @staticmethod
    def _apply_filters(
        nodes: list[CitationNode],
        edges: list[CitationEdge],
        config: CrawlConfig,
        dropped: dict[str, int],
    ) -> tuple[list[CitationNode], list[CitationEdge]]:
        """Legacy single-direction filter (kept for backward compatibility).

        Delegates to ``_apply_filters_directional`` with prefix ``""``.
        ``dropped`` keys will be ``"min_citations_"`` / ``"year_min_"``
        which are not standard; call sites inside ``crawl()`` use the
        directional variant directly. This shim exists so any test or
        caller that patches ``_apply_filters`` still works.
        """
        min_cit_key = "min_citations"
        year_min_key = "year_min"
        kept_nodes: list[CitationNode] = []
        for n in nodes:
            if n.citation_count < config.filter_min_citations:
                dropped[min_cit_key] = dropped.get(min_cit_key, 0) + 1
                continue
            if config.filter_year_min is not None:
                if n.year is None or n.year < config.filter_year_min:
                    dropped[year_min_key] = dropped.get(year_min_key, 0) + 1
                    continue
            kept_nodes.append(n)

        kept_ids = {n.paper_id for n in kept_nodes}
        kept_edges = [
            e
            for e in edges
            if e.cited_paper_id in kept_ids or e.citing_paper_id in kept_ids
        ]
        return kept_nodes, kept_edges

    def _persist_layer(
        self,
        paper_id: str,
        parent_node: Optional[CitationNode],
        related_nodes: list[CitationNode],
        edges: list[CitationEdge],
        seed_paper_id: str,
        persisted_node_ids: set[str],
    ) -> bool:
        """Bulk-insert one layer's nodes + edges. Return False on failure.

        Parent is included in the same batch as its related nodes so
        the FK constraint on the outgoing edges is satisfied even on
        the very first hop (the seed paper has not yet been written to
        the graph at that point).

        CHECKED SUCCESS gate: the caller must abort the BFS on a
        ``False`` return value. We log the structured event here so the
        audit trail is unambiguous (#127 + GEMINI.md §5).
        """
        # Build the dedup'd batch. Order matters: parent first so any
        # related-node that happens to share the parent's id (rare but
        # possible if a paper is in its own reference list) only
        # appears once.
        batch_nodes: list[CitationNode] = []
        if parent_node is not None and parent_node.paper_id not in persisted_node_ids:
            batch_nodes.append(parent_node)
        for n in related_nodes:
            if n.paper_id in persisted_node_ids:
                continue
            # The current batch may already contain this id if a node
            # appears twice in the same level (e.g. references + citations
            # under BOTH direction). Check the in-flight set too.
            if any(b.paper_id == n.paper_id for b in batch_nodes):
                continue
            batch_nodes.append(n)

        if not batch_nodes and not edges:
            return True

        graph_nodes = [n.to_graph_node() for n in batch_nodes]
        graph_edges = [e.to_graph_edge() for e in edges]

        try:
            self.store.add_nodes_batch(graph_nodes)
            self.store.add_edges_batch(graph_edges)
        except GraphStoreError as exc:
            logger.error(
                "citation_crawl_persistence_failed_aborting",
                seed_paper_id=seed_paper_id,
                expanding_paper_id=paper_id,
                node_count=len(graph_nodes),
                edge_count=len(graph_edges),
                error=str(exc),
            )
            return False

        # Update the persisted set only after a successful batch.
        for n in batch_nodes:
            persisted_node_ids.add(n.paper_id)
        return True


class _BudgetExhausted(Exception):
    """Internal signal: the crawl hit ``MAX_API_CALLS_PER_CRAWL``.

    Raised inside ``_expand_paper`` and caught at the BFS loop so the
    loop can exit cleanly with ``budget_exhausted=True``. Not part of
    the public surface.
    """
