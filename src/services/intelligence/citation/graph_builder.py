"""Citation graph builder (Milestone 9.2 — Week 1.5).

Composes :class:`SemanticScholarCitationClient` (primary) and
:class:`OpenAlexCitationClient` (fallback) and persists the resulting
nodes/edges via the :class:`GraphStore` Protocol from
``src.storage.intelligence_graph``. The builder is best-effort and
storage-engine-agnostic — it never imports ``sqlite3`` or any other
backend module, so swapping in a Neo4j store later is a constructor
change.

Scope of this PR (REQ-9.2.1, descoped Week 1.5):
- ``depth=1`` only. The BFS crawler that walks beyond direct neighbors
  is a separate Week-2 deliverable.
- Two persistence calls per ``build_for_paper``: one
  :meth:`GraphStore.add_nodes_batch`, one
  :meth:`GraphStore.add_edges_batch`. Per-row inserts are explicitly
  *not* used — the bulk APIs from PR #105 give us atomic rollback on
  any constraint violation, which is what the spec requires.
- Idempotent: edge ids are SHA-256-hashed (post PR #107 round 1) so
  re-running ``build_for_paper`` for the same seed at depth=1 is safe;
  duplicate-edge inserts are detected by the unique constraint and
  retried via per-edge insert as a recovery path.
- Provider strategy: try S2 first; if S2 returns *empty results* OR
  raises ``APIError`` / ``RateLimitError``, fall back to OpenAlex. The
  builder swallows provider errors and reports them via
  ``GraphBuildResult.errors`` rather than propagating, because callers
  will frequently process many seeds at once and one bad paper must
  not abort the batch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import structlog
from pydantic import BaseModel, ConfigDict, Field

from src.services.intelligence.citation.models import (
    CitationDirection,
    CitationEdge,
    CitationNode,
)
from src.services.intelligence.citation.openalex_client import (
    OpenAlexCitationClient,
)
from src.services.intelligence.citation.semantic_scholar_client import (
    SemanticScholarCitationClient,
)
from src.services.intelligence.models import (
    GraphEdge,
    GraphNode,
    GraphStoreDuplicateError,
    GraphStoreError,
)
from src.services.providers.base import APIError
from src.storage.intelligence_graph import GraphStore

logger = structlog.get_logger(__name__)


class ProviderTag(str, Enum):
    """Typed label for which provider supplied a build's data (#S6).

    Inherits from ``str`` so JSON serialisation (and existing string
    comparisons in tests / log enrichment) keep working unchanged. The
    enum gives mypy and exhaustive-switch consumers a real type instead
    of a free-form string.
    """

    NONE = "none"
    S2 = "s2"
    OPENALEX = "openalex"
    BOTH = "both"


# Hard cap on the size of error messages we forward into ``errors[]``
# and structlog records. Bounds memory, cuts log spend, and keeps a
# misbehaving upstream from exploding our DB row size if errors land in
# a persistence path later.
_MAX_FORWARDED_ERROR_LENGTH = 200


def _sanitize_error_msg(msg: str, max_len: int = _MAX_FORWARDED_ERROR_LENGTH) -> str:
    """Strip CR/LF/control chars and cap length to prevent log injection.

    A hostile upstream (or a buggy provider) could embed CRLF or other
    control bytes inside an error message; if we forwarded that
    verbatim into a log line or a structured ``errors[]`` field, the
    bytes could split the log record (log injection) or smuggle ANSI
    escape sequences into operator terminals. Replacing every
    non-printable byte with ``?`` is a one-pass defense and keeps the
    message human-readable for legitimate input (#N4).
    """
    cleaned = "".join(c if c.isprintable() else "?" for c in msg)
    return cleaned[:max_len]


class BuildForPaperRequest(BaseModel):
    """Pydantic input model for ``CitationGraphBuilder.build_for_paper`` (#S9).

    Defense-in-depth on the builder boundary: a future caller bypassing
    the providers' own validation would otherwise reach URL
    interpolation with whatever ``paper_id`` they pass. The Pydantic
    model enforces a strict allow-list and length cap before any
    provider call is issued.

    The pattern (``[A-Za-z0-9:./_\\-]+``) intentionally allows the
    punctuation needed for legitimate external id forms — DOIs
    (``10.x/y``), arxiv ids (``arxiv:1706.03762``), and S2 / OpenAlex
    native ids — while excluding URL/CRLF/path-traversal metacharacters.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    paper_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9:./_\-]+$")
    # depth>1 is the Week-2 BFS deliverable; ``ge=1, le=1`` keeps the
    # surface honest until the crawler ships.
    depth: int = Field(default=1, ge=1, le=1)
    direction: CitationDirection = CitationDirection.OUT


@dataclass(frozen=True)
class GraphBuildResult:
    """Outcome of one :meth:`CitationGraphBuilder.build_for_paper` call.

    Attributes:
        seed_paper_id: The paper id passed to ``build_for_paper`` (raw,
            before any provider-specific normalization).
        nodes_added: Count of nodes inserted into the graph store. Note
            this counts *attempts*, not unique rows — duplicates from a
            re-run still count here because the bulk insert was issued.
        edges_added: Count of edges inserted into the graph store, with
            the same caveat as ``nodes_added``.
        provider_used: Which provider supplied the data, as a
            :class:`ProviderTag` enum (#S6). String comparison still
            works because the enum inherits from ``str``.
        errors: Sanitized human-readable error messages collected during
            the call (see ``_sanitize_error_msg``). Empty on success.
            Populated when a provider failed but the builder kept going
            (e.g. S2 errored → fell back to OpenAlex), or when both
            providers failed.
    """

    seed_paper_id: str
    nodes_added: int
    edges_added: int
    provider_used: ProviderTag
    errors: list[str] = field(default_factory=list)


class CitationGraphBuilder:
    """Compose citation clients and persist results into a ``GraphStore``.

    The builder is constructed with a single :class:`GraphStore`
    instance and one client per provider. Both clients are required so
    the fallback path is always available — pass them explicitly so
    tests can inject mocks and so callers stay in control of API keys
    / polite-pool emails.
    """

    def __init__(
        self,
        store: GraphStore,
        s2_client: SemanticScholarCitationClient,
        openalex_client: OpenAlexCitationClient,
    ) -> None:
        self.store = store
        self.s2_client = s2_client
        self.openalex_client = openalex_client

    async def build_for_paper(
        self,
        paper_id: str,
        depth: int = 1,
        direction: CitationDirection = CitationDirection.OUT,
        max_results: int = 200,
    ) -> GraphBuildResult:
        """Fetch and persist the depth-1 citation graph around a seed.

        Args:
            paper_id: Provider-recognized paper id. For S2 this can be
                the S2 native id, a DOI, or an arxiv id; for OpenAlex
                this should be the OpenAlex work id (``W123…``) — but
                the fallback only triggers if S2 fails, so callers
                normally pass the S2-friendly form and rely on the
                primary path. Validated against ``BuildForPaperRequest``
                before any provider call (#S9).
            depth: Currently must be ``1``. Higher values raise
                ``pydantic.ValidationError`` — BFS crawl is the Week-2
                follow-up.
            direction: ``OUT`` for references, ``IN`` for citations,
                ``BOTH`` for both directions (one round-trip per side).
            max_results: Per-direction cap on returned rows. Defaults
                to 200 to match both clients' built-in cap.

        Returns:
            A :class:`GraphBuildResult` describing what was persisted
            and which provider supplied the data.
        """
        # Defense-in-depth input validation (#S9). The Pydantic model
        # rejects empty / oversized / regex-failing paper_ids and any
        # depth > 1 BEFORE we ever reach a provider call.
        request = BuildForPaperRequest(
            paper_id=paper_id, depth=depth, direction=direction
        )
        paper_id = request.paper_id
        depth = request.depth
        direction = request.direction
        if max_results < 1:
            raise ValueError("max_results must be >= 1")

        errors: list[str] = []

        seeds: list[CitationNode] = []
        related_lists: list[list[CitationNode]] = []
        edge_lists: list[list[CitationEdge]] = []

        if direction == CitationDirection.BOTH:
            # Two provider-strategy passes — one per direction. Each
            # pass independently chooses S2-then-OpenAlex.
            out_seed, out_related, out_edges, out_provider, out_errors = (
                await self._fetch_with_fallback(
                    paper_id, CitationDirection.OUT, max_results
                )
            )
            in_seed, in_related, in_edges, in_provider, in_errors = (
                await self._fetch_with_fallback(
                    paper_id, CitationDirection.IN, max_results
                )
            )
            errors.extend(out_errors)
            errors.extend(in_errors)

            # Both seeds are persisted — they may differ when one
            # direction had to fall back to OpenAlex (which produces a
            # paper:openalex:Wxxx id) while the other succeeded via S2
            # (paper:s2:xxx). Without both, the IN edges would be
            # orphans referencing a missing target node.
            if out_seed is not None:
                seeds.append(out_seed)
                related_lists.append(out_related)
                edge_lists.append(out_edges)
            if in_seed is not None:
                seeds.append(in_seed)
                related_lists.append(in_related)
                edge_lists.append(in_edges)
            provider_used = self._combine_providers(out_provider, in_provider)
        else:
            seed, related, edges, provider_used, dir_errors = (
                await self._fetch_with_fallback(paper_id, direction, max_results)
            )
            errors.extend(dir_errors)
            if seed is not None:
                seeds.append(seed)
                related_lists.append(related)
                edge_lists.append(edges)

        if not seeds:
            # No provider succeeded — nothing to persist.
            logger.warning(
                "citation_graph_build_no_data",
                seed_paper_id=paper_id,
                errors=errors,
            )
            return GraphBuildResult(
                seed_paper_id=paper_id,
                nodes_added=0,
                edges_added=0,
                provider_used=ProviderTag.NONE,
                errors=errors,
            )

        nodes_added, edges_added, persist_errors = self._persist(
            seeds, related_lists, edge_lists
        )
        errors.extend(persist_errors)

        logger.info(
            "citation_graph_built",
            seed_paper_id=paper_id,
            depth=depth,
            direction=direction.value,
            provider_used=provider_used,
            nodes_added=nodes_added,
            edges_added=edges_added,
            error_count=len(errors),
        )
        return GraphBuildResult(
            seed_paper_id=paper_id,
            nodes_added=nodes_added,
            edges_added=edges_added,
            provider_used=provider_used,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _fetch_with_fallback(
        self,
        paper_id: str,
        direction: CitationDirection,
        max_results: int,
    ) -> tuple[
        Optional[CitationNode],
        list[CitationNode],
        list[CitationEdge],
        ProviderTag,
        list[str],
    ]:
        """Call S2 first, fall back to OpenAlex on empty / error.

        Returns a 5-tuple ``(seed, related, edges, provider, errors)``.
        ``seed`` is ``None`` only when both providers failed. When S2
        returns successfully but with zero related rows we still treat
        that as a success (the seed is real, the paper just has no
        references / citations on file at S2) and do *not* fall back —
        OpenAlex is unlikely to do better and would double the API
        cost.

        Error messages forwarded into ``errors`` are sanitized via
        :func:`_sanitize_error_msg` before being appended (#N4) so
        upstream CRLF cannot inject log lines.
        """
        errors: list[str] = []

        # Pass 1: Semantic Scholar.
        try:
            seed, related, edges = await self._call_provider(
                self.s2_client, paper_id, direction, max_results
            )
        except APIError as exc:
            # APIError covers both 404 and 5xx and RateLimitError. We
            # log + record the error and fall through to OpenAlex.
            sanitized = _sanitize_error_msg(str(exc))
            logger.warning(
                "citation_s2_failed",
                seed_paper_id=paper_id,
                direction=direction.value,
                error=sanitized,
            )
            errors.append(_sanitize_error_msg(f"s2: {exc}"))
            seed = None
            related = []
            edges = []

        if seed is not None:
            return seed, related, edges, ProviderTag.S2, errors

        # Pass 2: OpenAlex fallback.
        try:
            oa_seed, oa_related, oa_edges = await self._call_provider(
                self.openalex_client, paper_id, direction, max_results
            )
            return oa_seed, oa_related, oa_edges, ProviderTag.OPENALEX, errors
        except APIError as exc:
            sanitized = _sanitize_error_msg(str(exc))
            logger.warning(
                "citation_openalex_failed",
                seed_paper_id=paper_id,
                direction=direction.value,
                error=sanitized,
            )
            errors.append(_sanitize_error_msg(f"openalex: {exc}"))
            return None, [], [], ProviderTag.NONE, errors

    @staticmethod
    async def _call_provider(
        client: SemanticScholarCitationClient | OpenAlexCitationClient,
        paper_id: str,
        direction: CitationDirection,
        max_results: int,
    ) -> tuple[CitationNode, list[CitationNode], list[CitationEdge]]:
        """Dispatch to the right method on the chosen client."""
        if direction == CitationDirection.OUT:
            return await client.get_references(paper_id, max_results=max_results)
        # ``CitationDirection.BOTH`` is split apart in ``build_for_paper``
        # before we ever reach here, so the only remaining case is IN.
        return await client.get_citations(paper_id, max_results=max_results)

    @staticmethod
    def _combine_providers(
        out_provider: ProviderTag, in_provider: ProviderTag
    ) -> ProviderTag:
        """Reduce two per-direction provider tags to a single label.

        The exact rules are:
        - both ``NONE`` → ``NONE``
        - one ``NONE``, the other set → use the other one (a single
          direction succeeded)
        - both the same non-``NONE`` value → that value
        - mixed (e.g. ``S2`` + ``OPENALEX``) → ``BOTH``
        """
        providers = {p for p in (out_provider, in_provider) if p != ProviderTag.NONE}
        if not providers:
            return ProviderTag.NONE
        if len(providers) == 1:
            return providers.pop()
        return ProviderTag.BOTH

    def _persist(
        self,
        seeds: list[CitationNode],
        related_lists: list[list[CitationNode]],
        edge_lists: list[list[CitationEdge]],
    ) -> tuple[int, int, list[str]]:
        """Bulk-insert nodes and edges; return (nodes, edges, errors).

        Implementation notes:
        - We deduplicate within the call so a single ``add_nodes_batch``
          never sees the same ``node_id`` twice (that would always
          violate the UNIQUE constraint and roll back the whole batch).
          Cross-call duplicates — e.g. a re-run for the same seed — are
          handled by the recovery path below.
        - On a constraint violation (duplicate node_id / edge_id from a
          previous call), the bulk insert is rolled back and we
          fall back to per-row inserts that swallow duplicates so the
          re-run remains idempotent. This is the price of using
          ``add_*_batch`` for the happy path; the alternative would be
          per-row inserts always, which the spec explicitly disallows.
        - Multiple seeds appear when the BOTH direction had to fall
          back to a different provider for one side; both seed nodes
          are persisted so the IN-side edges aren't orphaned.
        """
        all_nodes: dict[str, GraphNode] = {}
        for seed in seeds:
            if seed.paper_id not in all_nodes:
                all_nodes[seed.paper_id] = seed.to_graph_node()
        for related in related_lists:
            for node in related:
                if node.paper_id not in all_nodes:
                    all_nodes[node.paper_id] = node.to_graph_node()

        all_edges: dict[str, GraphEdge] = {}
        for edges in edge_lists:
            for edge in edges:
                graph_edge = edge.to_graph_edge()
                # Last-writer wins for properties; ids collapse cleanly
                # because the SHA-256 hash is deterministic per pair.
                all_edges[graph_edge.edge_id] = graph_edge

        errors: list[str] = []
        nodes_added = self._bulk_insert_nodes(list(all_nodes.values()), errors)
        edges_added = self._bulk_insert_edges(list(all_edges.values()), errors)
        return nodes_added, edges_added, errors

    def _bulk_insert_nodes(self, nodes: list[GraphNode], errors: list[str]) -> int:
        """Try one ``add_nodes_batch``; recover with per-row inserts.

        The recovery path exists so a re-run for the same seed (where
        the seed node already exists) does not fail the whole call.
        Per-row inserts swallow :class:`GraphStoreDuplicateError` (typed
        UNIQUE-constraint signal — see #S5) and report any other failure
        into ``errors``. We deliberately avoid substring-matching on the
        message text: SQLite's wording is not a stable contract and a
        rephrase upstream would silently break this loop.
        """
        if not nodes:
            return 0
        try:
            self.store.add_nodes_batch(nodes)
            return len(nodes)
        except GraphStoreError as exc:
            logger.info(
                "citation_node_batch_fallback_to_per_row",
                count=len(nodes),
                error=str(exc),
            )
            inserted = 0
            for node in nodes:
                try:
                    self.store.add_node(node.node_id, node.node_type, node.properties)
                    inserted += 1
                except GraphStoreDuplicateError:
                    # Idempotent re-run — typed signal, not an error.
                    continue
                except GraphStoreError as inner_exc:
                    errors.append(
                        _sanitize_error_msg(f"node {node.node_id}: {inner_exc}")
                    )
            return inserted

    def _bulk_insert_edges(self, edges: list[GraphEdge], errors: list[str]) -> int:
        """Same shape as :meth:`_bulk_insert_nodes` for edges."""
        if not edges:
            return 0
        try:
            self.store.add_edges_batch(edges)
            return len(edges)
        except GraphStoreError as exc:
            logger.info(
                "citation_edge_batch_fallback_to_per_row",
                count=len(edges),
                error=str(exc),
            )
            inserted = 0
            for edge in edges:
                try:
                    self.store.add_edge(
                        edge.edge_id,
                        edge.source_id,
                        edge.target_id,
                        edge.edge_type,
                        edge.properties,
                    )
                    inserted += 1
                except GraphStoreDuplicateError:
                    continue
                except GraphStoreError as inner_exc:
                    errors.append(
                        _sanitize_error_msg(f"edge {edge.edge_id}: {inner_exc}")
                    )
            return inserted
