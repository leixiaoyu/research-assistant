"""Semantic Scholar citation client (Milestone 9.2 — primary source).

This is **not** the existing ``SemanticScholarProvider`` from
``src.services.providers.semantic_scholar``; that one implements the
``DiscoveryProvider`` ABC for keyword paper search. The citation graph
needs different endpoints (``/paper/{id}/references``,
``/paper/{id}/citations``), pagination semantics (``offset``/``limit``
up to S2's 1000 cap), and a 7-day disk cache per spec (Section 11.3).
We deliberately built alongside rather than retrofitting the search
provider — see the package docstring for the rationale.

Spec mapping:
- REQ-9.2.1 (Citation Graph Construction): ``get_references`` and
  ``get_citations`` produce :class:`CitationNode` / :class:`CitationEdge`
  pairs ready for the graph builder to persist.
- SR-9.1 (API Key Management): the API key is read from the
  ``SEMANTIC_SCHOLAR_API_KEY`` env var by default; never hardcoded.
- SR-9.2 (Rate Limiting): 100 req / 5min with an API key, 1 req/sec
  without; both bounds are enforced via :class:`RateLimiter` and the
  caller can override either value.
- Cost optimization (Section 11.3): citation lookups are cached on
  disk for 7 days (TTL configurable for tests).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional, cast

import aiohttp
import diskcache
import structlog

from src.services.intelligence.citation.models import (
    CitationEdge,
    CitationNode,
    make_paper_node_id,
)
from src.services.providers.base import APIError, RateLimitError
from src.utils.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)


# Spec-mandated cache TTL (Section 11.3): citation lookups are cached
# for 7 days. Tests pass a much shorter TTL via constructor arg.
_DEFAULT_CITATION_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# S2 hard cap on a single page of results.
_S2_MAX_PAGE_LIMIT = 1000

# Default per-call ceiling. Far below the spec's worst-case crawl-level
# budget so a single ``get_references`` cannot pull thousands of pages.
_DEFAULT_MAX_RESULTS = 200

# Fields requested from S2 for both endpoints. Ordered for readability;
# S2 ignores order. We request both ``citationCount`` and
# ``influentialCitationCount`` so the Week-2 ``sort_by_influence``
# helper has the data it needs without a second round-trip.
_S2_PAPER_FIELDS = ",".join(
    [
        "paperId",
        "externalIds",
        "title",
        "year",
        "citationCount",
        "influentialCitationCount",
        "referenceCount",
    ]
)


class SemanticScholarCitationClient:
    """Citation-endpoint client for Semantic Scholar.

    Public methods return ``(seed_node, related_nodes, edges)`` tuples
    where:
    - ``seed_node`` is a :class:`CitationNode` for the paper queried,
    - ``related_nodes`` is the list of cited/citing papers (as
      :class:`CitationNode`),
    - ``edges`` is the list of :class:`CitationEdge` connecting them
      (always pointing from citing to cited).

    Caching: each ``(endpoint, paper_id, max_results)`` triple is cached
    for ``cache_ttl_seconds`` (7 days by default). The cache is on disk
    via ``diskcache`` so it survives process restarts. Pass
    ``cache_dir=None`` to disable caching entirely (used in tests that
    need to assert HTTP behavior on each call).
    """

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None,
        cache_dir: Optional[Path | str] = None,
        cache_ttl_seconds: int = _DEFAULT_CITATION_CACHE_TTL_SECONDS,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize the client.

        Args:
            api_key: Semantic Scholar API key. If ``None``, falls back
                to the ``SEMANTIC_SCHOLAR_API_KEY`` env var. Either path
                is fine — the caller chooses where the secret lives —
                but the resulting key is *never* logged.
            rate_limiter: Optional pre-built rate limiter. When
                ``None``, the client builds one matching S2's published
                limits: 100 req/5min (~20 req/min) with an API key,
                12 req/min (1/5s) without. The lower no-key value is
                deliberately conservative — S2 throttles aggressively
                on unauthenticated calls.
            cache_dir: Directory for the disk cache. ``None`` disables
                caching. Defaults to ``$ARISP_CITATION_CACHE_DIR`` or
                ``./cache/citation/s2``.
            cache_ttl_seconds: TTL for cached citation lookups. Default
                is 7 days per spec Section 11.3; tests pass smaller
                values to exercise expiration logic.
            request_timeout_seconds: Per-request HTTP timeout.
        """
        self.api_key = (
            api_key if api_key is not None else os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        )

        if rate_limiter is None:
            # 100 req / 5min with an API key = 20 req/min effective.
            # Without a key S2 enforces ~1 req/sec; we go a touch under
            # at 12 req/min to leave headroom for retry storms.
            requests_per_minute = 20 if self.api_key else 12
            rate_limiter = RateLimiter(
                requests_per_minute=requests_per_minute,
                burst_size=5,
            )
        self.rate_limiter = rate_limiter

        self.request_timeout_seconds = request_timeout_seconds

        self._cache: Optional[diskcache.Cache]
        if cache_dir is None and "ARISP_CITATION_CACHE_DIR" in os.environ:
            cache_dir = os.environ["ARISP_CITATION_CACHE_DIR"]

        if cache_dir is None:
            self._cache = None
            self._cache_ttl_seconds = cache_ttl_seconds
        else:
            cache_path = Path(cache_dir) / "s2"
            cache_path.mkdir(parents=True, exist_ok=True)
            self._cache = diskcache.Cache(str(cache_path), timeout=cache_ttl_seconds)
            self._cache_ttl_seconds = cache_ttl_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_references(
        self,
        paper_id: str,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> tuple[CitationNode, list[CitationNode], list[CitationEdge]]:
        """Fetch papers the seed paper *references* (outgoing edges).

        Args:
            paper_id: The S2-recognized paper id. Accepts S2 native ids
                (``204e3073...``), DOI form (``10.18653/v1/...``), or
                arxiv form (``arxiv:1706.03762``). S2's API resolves
                all three transparently.
            max_results: Cap on rows returned. We page in 100-row
                chunks until either the cap is hit or S2 reports no
                more results. Defaults to 200; the spec's BFS layer
                caps at 200 too.

        Returns:
            ``(seed_node, ref_nodes, edges)`` — see the class docstring.
        """
        return await self._fetch_relationships(
            endpoint="references",
            paper_id=paper_id,
            max_results=max_results,
        )

    async def get_citations(
        self,
        paper_id: str,
        max_results: int = _DEFAULT_MAX_RESULTS,
    ) -> tuple[CitationNode, list[CitationNode], list[CitationEdge]]:
        """Fetch papers that *cite* the seed paper (incoming edges).

        Mirror of :meth:`get_references` but for the ``/citations``
        endpoint. Returned edges still point from citing → cited, so
        in this case every edge has ``cited_paper_id == seed.paper_id``.
        """
        return await self._fetch_relationships(
            endpoint="citations",
            paper_id=paper_id,
            max_results=max_results,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _fetch_relationships(
        self,
        endpoint: str,
        paper_id: str,
        max_results: int,
    ) -> tuple[CitationNode, list[CitationNode], list[CitationEdge]]:
        """Common path for ``get_references`` / ``get_citations``."""
        if not paper_id or not paper_id.strip():
            raise ValueError("paper_id must be a non-empty string")
        if max_results < 1:
            raise ValueError("max_results must be >= 1")
        if endpoint not in {"references", "citations"}:
            # Internal callers only — guards against typos in future
            # wrapper methods.
            raise ValueError(f"Unsupported endpoint: {endpoint!r}")

        cache_key = self._cache_key(endpoint, paper_id, max_results)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info(
                "s2_citation_cache_hit",
                endpoint=endpoint,
                paper_id=paper_id,
            )
            return self._deserialize_payload(cached)

        # Cache miss — fetch the seed metadata and the related list in
        # parallel. The seed metadata gives us authoritative title /
        # year / citation_count to attach to the seed node, which the
        # spec requires (REQ-9.2.1).
        seed_task = asyncio.create_task(self._fetch_paper(paper_id))
        rels_task = asyncio.create_task(
            self._fetch_relationship_pages(endpoint, paper_id, max_results)
        )
        seed_payload = await seed_task
        rel_payloads = await rels_task

        seed_node = self._payload_to_node(seed_payload)

        related_nodes: list[CitationNode] = []
        edges: list[CitationEdge] = []
        for entry in rel_payloads:
            related_payload = entry.get("citingPaper") or entry.get("citedPaper")
            if not related_payload:
                # S2 occasionally returns rows where the related paper
                # body is missing (deleted record). Skip silently —
                # there's nothing to add to the graph.
                continue

            try:
                related_node = self._payload_to_node(related_payload)
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "s2_citation_skip_invalid_node",
                    endpoint=endpoint,
                    seed_paper_id=paper_id,
                    error=str(exc),
                )
                continue

            related_nodes.append(related_node)

            if endpoint == "references":
                citing, cited = seed_node.paper_id, related_node.paper_id
            else:  # citations: caller is the cited paper
                citing, cited = related_node.paper_id, seed_node.paper_id

            edges.append(
                CitationEdge(
                    citing_paper_id=citing,
                    cited_paper_id=cited,
                    context=self._first_context(entry.get("contexts")),
                    section=self._first_context(entry.get("intents")),
                    is_influential=entry.get("isInfluential"),
                    source="semantic_scholar",
                )
            )

        result = (seed_node, related_nodes, edges)
        self._cache_set(cache_key, self._serialize_payload(result))
        logger.info(
            "s2_citation_fetched",
            endpoint=endpoint,
            paper_id=paper_id,
            related_count=len(related_nodes),
        )
        return result

    async def _fetch_paper(self, paper_id: str) -> dict[str, Any]:
        """Fetch the seed paper's own metadata."""
        url = f"{self.BASE_URL}/paper/{paper_id}"
        params = {"fields": _S2_PAPER_FIELDS}
        return await self._http_get(url, params=params)

    async def _fetch_relationship_pages(
        self,
        endpoint: str,
        paper_id: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Page through ``/references`` or ``/citations`` until done.

        S2 caps a single page at 1000 rows; we chunk in 100-row pages
        because that's where the API documentation says response time
        plateaus, and smaller pages let us bail early once ``max_results``
        is hit without wasting bandwidth.
        """
        url = f"{self.BASE_URL}/paper/{paper_id}/{endpoint}"
        page_size = min(100, max_results, _S2_MAX_PAGE_LIMIT)

        collected: list[dict[str, Any]] = []
        offset = 0
        while len(collected) < max_results:
            params = {
                "fields": _S2_PAPER_FIELDS + ",contexts,intents,isInfluential",
                "limit": str(page_size),
                "offset": str(offset),
            }
            payload = await self._http_get(url, params=params)
            data = payload.get("data") or []
            if not data:
                break
            collected.extend(data)

            # S2 returns ``next`` only when more pages exist. If it is
            # absent or zero we have reached the end of the result set.
            next_offset = payload.get("next")
            if next_offset is None or next_offset == offset:
                break
            offset = int(next_offset)

        return collected[:max_results]

    async def _http_get(
        self,
        url: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """Issue a single GET to S2 with rate limiting + error handling.

        Distinguishes:
        - 200: returns the parsed JSON body.
        - 404: raises ``APIError`` (the seed paper id is unknown — not
          retryable).
        - 429: raises ``RateLimitError`` (caller may retry).
        - 5xx / other: raises ``APIError``.
        """
        await self.rate_limiter.acquire("semantic_scholar_citations")

        headers: dict[str, str] = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout_seconds),
                ) as response:
                    if response.status == 429:
                        raise RateLimitError(
                            "Semantic Scholar citation rate limit exceeded"
                        )
                    if response.status == 404:
                        text = await response.text()
                        raise APIError(
                            f"Paper not found on Semantic Scholar (404): {text}"
                        )
                    if response.status != 200:
                        text = await response.text()
                        raise APIError(
                            f"Semantic Scholar error {response.status}: {text}"
                        )
                    body: dict[str, Any] = await response.json()
                    return body
        except asyncio.TimeoutError as exc:
            raise APIError(
                f"Semantic Scholar request timed out after "
                f"{self.request_timeout_seconds}s"
            ) from exc

    # ------------------------------------------------------------------
    # Payload <-> CitationNode glue
    # ------------------------------------------------------------------

    def _payload_to_node(self, payload: dict[str, Any]) -> CitationNode:
        """Convert an S2 paper payload into a :class:`CitationNode`."""
        s2_id = payload.get("paperId")
        if not s2_id:
            raise KeyError("S2 payload missing paperId")

        external_ids: dict[str, str] = {"s2": str(s2_id)}
        for key, value in (payload.get("externalIds") or {}).items():
            if value:
                external_ids[str(key).lower()] = str(value)

        title = payload.get("title") or "Unknown Title"

        return CitationNode(
            paper_id=make_paper_node_id("s2", str(s2_id)),
            external_ids=external_ids,
            title=title,
            year=payload.get("year"),
            citation_count=int(payload.get("citationCount") or 0),
            reference_count=int(payload.get("referenceCount") or 0),
        )

    @staticmethod
    def _first_context(value: Any) -> Optional[str]:
        """Extract a single string from S2's list-of-strings fields.

        S2 returns ``contexts`` and ``intents`` as JSON arrays. The
        spec's ``CitationEdge`` only allows a single string per field,
        so we keep the first non-empty entry. If the list is empty or
        absent we return ``None`` and the edge property is omitted.
        """
        if not value:
            return None
        if isinstance(value, list):
            for entry in value:
                if entry:
                    return str(entry)
            return None
        # Non-list scalar — should not happen but defends against
        # surprise schema changes upstream.
        return str(value)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, endpoint: str, paper_id: str, max_results: int) -> str:
        """Derive a stable cache key.

        We hash the inputs so the resulting key is filesystem-safe and
        bounded in length — paper ids can include slashes (DOIs) which
        would otherwise break diskcache on some platforms.
        """
        raw = f"{endpoint}|{paper_id}|{max_results}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> Optional[bytes]:
        if self._cache is None:
            return None
        value = self._cache.get(key)
        return cast(Optional[bytes], value)

    def _cache_set(self, key: str, payload: bytes) -> None:
        if self._cache is None:
            return
        self._cache.set(key, payload, expire=self._cache_ttl_seconds)

    @staticmethod
    def _serialize_payload(
        result: tuple[CitationNode, list[CitationNode], list[CitationEdge]],
    ) -> bytes:
        seed, related, edges = result
        return json.dumps(
            {
                "seed": seed.model_dump(mode="json"),
                "related": [n.model_dump(mode="json") for n in related],
                "edges": [e.model_dump(mode="json") for e in edges],
            }
        ).encode("utf-8")

    @staticmethod
    def _deserialize_payload(
        raw: bytes,
    ) -> tuple[CitationNode, list[CitationNode], list[CitationEdge]]:
        data = json.loads(raw.decode("utf-8"))
        seed = CitationNode.model_validate(data["seed"])
        related = [CitationNode.model_validate(n) for n in data["related"]]
        edges = [CitationEdge.model_validate(e) for e in data["edges"]]
        return seed, related, edges

    def close(self) -> None:
        """Release any disk cache handle."""
        if self._cache is not None:
            self._cache.close()
            self._cache = None
