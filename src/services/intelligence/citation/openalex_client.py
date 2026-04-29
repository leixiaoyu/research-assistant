"""OpenAlex citation client (Milestone 9.2 — fallback source).

This is **not** the existing ``OpenAlexProvider`` from
``src.services.providers.openalex``; that one implements the
``DiscoveryProvider`` ABC for keyword paper search and produces
``PaperMetadata``. The citation graph needs different endpoints
(``/works/{id}`` to read ``referenced_works``; ``/works?filter=cites:{id}``
for incoming citations), a different response shape (``CitationNode`` /
``CitationEdge``), and a 7-day disk cache per spec (Section 11.3). We
deliberately built alongside the search provider — see the package
docstring for the full rationale.

Spec mapping:
- REQ-9.2.1 (Citation Graph Construction): ``get_references`` and
  ``get_citations`` produce :class:`CitationNode` / :class:`CitationEdge`
  pairs ready for the graph builder to persist.
- SR-9.1 (API Key Management): no API key is required by OpenAlex, but
  the *polite-pool* email is read from ``OPENALEX_POLITE_EMAIL`` (env
  var). It is never hardcoded; if missing we log a one-shot warning and
  fall back to the slower anonymous pool.
- SR-9.2 (Rate Limiting): OpenAlex's polite pool allows 100k req/day
  (~70/min sustained); we cap at 60 req/min by default to leave
  headroom for retry storms. The anonymous tier is throttled more
  aggressively, so we drop to 20 req/min when no email is configured.
- Cost optimization (Section 11.3): citation lookups are cached on
  disk for 7 days (TTL configurable for tests).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Optional, cast
from urllib.parse import quote

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

# OpenAlex's documented per-page cap. We default to 200 below, matching
# the spec's typical max_results, but smaller pages let us bail early
# once the per-call cap is hit without wasting bandwidth.
_OPENALEX_MAX_PER_PAGE = 200

# Default per-call ceiling. Identical to the S2 client so the graph
# builder can switch providers transparently.
_DEFAULT_MAX_RESULTS = 200

# Maximum number of OpenAlex IDs we pack into a single ``filter=openalex:W1|W2|...``
# request when hydrating reference metadata. OpenAlex does not publish a
# hard cap on filter length, but URLs over ~2000 chars risk truncation
# and CDN rejection — 50 IDs (~1100 chars including ``W`` prefix and
# pipes) leaves ample headroom.
_OPENALEX_ID_BATCH_SIZE = 50

# Fields requested from OpenAlex for both endpoints. Matches the spec's
# ``CitationNode`` schema; we also pull ``referenced_works`` so the
# references path can resolve outgoing edges in a single hop.
_OPENALEX_WORK_SELECT = ",".join(
    [
        "id",
        "doi",
        "title",
        "publication_year",
        "cited_by_count",
        "referenced_works",
        "referenced_works_count",
        "ids",
    ]
)

# Lightweight select for the seed fetch when we already have the work
# id and only need basics. Identical to ``_OPENALEX_WORK_SELECT`` for
# now; kept separate so we can shrink it later without affecting the
# related-paper hydration call.
_OPENALEX_SEED_SELECT = _OPENALEX_WORK_SELECT


# Strict allow-list for OpenAlex work ids. The shape of an OpenAlex
# work id is the literal letter ``W`` followed by a digit run (typically
# 8-10 digits today; 15 leaves headroom for future growth). Anything
# outside this shape is rejected before it ever reaches URL
# construction. ASCII-only by design — Unicode lookalikes could mask an
# injection vector.
_WORK_ID_PATTERN = re.compile(r"^W\d{1,15}$")

# Substrings that the regex above already excludes but which we re-check
# explicitly as a defense-in-depth tripwire. If a future maintainer
# loosens the regex (e.g. to support a new namespace prefix), the
# forbid-list still blocks the worst SSRF / traversal payloads.
# - ``..`` flags relative-path traversal.
# - ``://`` flags inlined URLs (``http://evil``).
# - ``?`` and ``#`` would split the URL into query/fragment segments
#   and could be used to smuggle parameters past our explicit ones.
_WORK_ID_FORBIDDEN_SUBSTRINGS = ("..", "://", "?", "#")

# Hard cap on work-id length — well above ``W`` + 15-digit run, so the
# regex is the binding check, but the length check fails fast on
# multi-megabyte payload-stuffing attempts before regex backtracking
# burns CPU.
_MAX_WORK_ID_LENGTH = 32

# Hard cap on the size of a single OpenAlex response body we will
# parse. Without this, a malicious or misbehaving upstream could stream
# an arbitrarily large payload into ``response.json()`` and exhaust
# memory. 25 MB is intentionally larger than the S2 cap (10 MB) — a
# single OpenAlex page can include 200 full ``Work`` payloads with all
# selected fields, which is heavier than S2's per-row shape.
_MAX_RESPONSE_BYTES = 25 * 1024 * 1024


# Module-level flag so we warn at most once per process when the polite
# email is missing. Tests reset this via ``reset_polite_email_warning``
# (kept private to the module).
_POLITE_EMAIL_WARNED = False


# Mute aiohttp's transport-level DEBUG logger at import time. The
# polite-pool email is appended to every URL as a ``mailto`` query
# param; aiohttp's ``aiohttp.client`` logger emits the full URL at
# DEBUG which would leak the email into application logs whenever a
# downstream consumer raises the global log level. Setting the floor to
# INFO globally is the simplest defensible choice — those DEBUG records
# are rarely useful in production and never emitted by this module's
# own structlog calls. The alternative (a redacting handler) adds code
# without a behavioural difference for any caller we care about.
logging.getLogger("aiohttp.client").setLevel(logging.INFO)


def _reset_polite_email_warning() -> None:
    """Reset the once-per-process polite-email warning latch.

    Test-only helper; not part of the public API. Mutating a module
    global from a function avoids ``global`` declarations in tests.
    """
    global _POLITE_EMAIL_WARNED
    _POLITE_EMAIL_WARNED = False


class OpenAlexCitationClient:
    """Citation-endpoint client for OpenAlex.

    Public methods return ``(seed_node, related_nodes, edges)`` tuples
    where:
    - ``seed_node`` is a :class:`CitationNode` for the paper queried,
    - ``related_nodes`` is the list of cited/citing papers (as
      :class:`CitationNode`),
    - ``edges`` is the list of :class:`CitationEdge` connecting them
      (always pointing from citing to cited).

    The shape is identical to :class:`SemanticScholarCitationClient` so
    the graph builder can swap providers transparently.

    Caching: each ``(endpoint, paper_id, max_results, polite_email_set)``
    tuple is cached for ``cache_ttl_seconds`` (7 days by default). The
    cache is on disk via ``diskcache`` so it survives process restarts.
    The ``polite_email_set`` bit segregates entries because the polite
    pool may return slightly fresher data; mixing them would let an
    anonymous call serve stale polite-pool results. Pass
    ``cache_dir=None`` to disable caching entirely.
    """

    BASE_URL = "https://api.openalex.org"

    def __init__(
        self,
        polite_email: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None,
        cache_dir: Optional[Path | str] = None,
        cache_ttl_seconds: int = _DEFAULT_CITATION_CACHE_TTL_SECONDS,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize the client.

        Args:
            polite_email: Email address used for OpenAlex's polite pool.
                If ``None``, falls back to the ``OPENALEX_POLITE_EMAIL``
                env var. If that is also unset we log a single WARN and
                use the anonymous pool (still works, just slower). The
                value is never emitted by this client; aiohttp's
                transport debug logger is muted to INFO at module
                import time to prevent transport-level URL leakage of
                the ``mailto`` query parameter (#S7).
            rate_limiter: Optional pre-built rate limiter. When ``None``
                the client builds one matching the polite-pool budget
                (60 req/min) or the anonymous budget (20 req/min) when
                no email is available. Both bounds are deliberately
                conservative — OpenAlex's published limits change
                without notice and we want headroom for retries.
            cache_dir: Directory for the disk cache. ``None`` disables
                caching. Defaults to ``$ARISP_CITATION_CACHE_DIR`` or
                ``./cache/citation/openalex`` if the env var is set.
            cache_ttl_seconds: TTL for cached citation lookups. Default
                is 7 days per spec Section 11.3; tests pass smaller
                values to exercise expiration logic.
            request_timeout_seconds: Per-request HTTP timeout.
        """
        self.polite_email = (
            polite_email
            if polite_email is not None
            else os.getenv("OPENALEX_POLITE_EMAIL")
        )

        if not self.polite_email:
            global _POLITE_EMAIL_WARNED
            if not _POLITE_EMAIL_WARNED:
                logger.warning(
                    "openalex_polite_pool_disabled",
                    reason=(
                        "OPENALEX_POLITE_EMAIL not set; falling back to "
                        "anonymous pool (lower rate limits)."
                    ),
                )
                _POLITE_EMAIL_WARNED = True

        if rate_limiter is None:
            requests_per_minute = 60 if self.polite_email else 20
            rate_limiter = RateLimiter(
                requests_per_minute=requests_per_minute,
                burst_size=10,
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
            cache_path = Path(cache_dir) / "openalex"
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
        """Fetch papers the seed work *references* (outgoing edges).

        OpenAlex returns the reference list inline on the seed work as
        ``referenced_works`` — a list of OpenAlex URLs. We hydrate the
        first ``max_results`` of those into full :class:`CitationNode`
        objects via a batched ``filter=openalex:W1|W2|...`` call so we
        only pay one extra round-trip per 50 references.

        Args:
            paper_id: An OpenAlex work id (``W123…``). Bare ids and
                full URLs (``https://openalex.org/W123…``) are both
                accepted.
            max_results: Cap on rows returned. Defaults to 200.

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
        """Fetch papers that *cite* the seed work (incoming edges).

        Uses OpenAlex's ``filter=cites:W123`` query and pages through
        the result set. Returned edges still point from citing → cited,
        so in this case every edge has ``cited_paper_id == seed.paper_id``.
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
            raise ValueError(f"Unsupported endpoint: {endpoint!r}")

        normalized_id = self._normalize_work_id(paper_id)

        cache_key = self._cache_key(endpoint, normalized_id, max_results)
        cached = self._cache_get(cache_key)
        if cached is not None:
            logger.info(
                "openalex_citation_cache_hit",
                endpoint=endpoint,
                paper_id=normalized_id,
            )
            return self._deserialize_payload(cached)

        seed_payload = await self._fetch_work(normalized_id)
        seed_node = self._payload_to_node(seed_payload)

        if endpoint == "references":
            related_payloads = await self._fetch_referenced_works(
                seed_payload, max_results
            )
        else:  # citations
            related_payloads = await self._fetch_citing_works(
                normalized_id, max_results
            )

        related_nodes: list[CitationNode] = []
        edges: list[CitationEdge] = []
        for payload in related_payloads:
            try:
                related_node = self._payload_to_node(payload)
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "openalex_citation_skip_invalid_node",
                    endpoint=endpoint,
                    seed_paper_id=normalized_id,
                    error=str(exc),
                )
                continue

            related_nodes.append(related_node)

            if endpoint == "references":
                citing, cited = seed_node.paper_id, related_node.paper_id
            else:  # citations
                citing, cited = related_node.paper_id, seed_node.paper_id

            edges.append(
                CitationEdge(
                    citing_paper_id=citing,
                    cited_paper_id=cited,
                    # OpenAlex does not provide per-citation context,
                    # section, or an "isInfluential" signal — leave them
                    # unset so the graph layer omits the JSON fields
                    # entirely (see ``CitationEdge.to_graph_edge``).
                    source="openalex",
                )
            )

        result = (seed_node, related_nodes, edges)
        self._cache_set(cache_key, self._serialize_payload(result))
        logger.info(
            "openalex_citation_fetched",
            endpoint=endpoint,
            paper_id=normalized_id,
            related_count=len(related_nodes),
        )
        return result

    async def _fetch_work(self, work_id: str) -> dict[str, Any]:
        """Fetch a single work's metadata from OpenAlex.

        ``work_id`` is presumed to have already been validated by
        ``_normalize_work_id`` (the only caller goes through
        ``_fetch_relationships``). We still ``urllib.parse.quote(...,
        safe="")`` it as defense-in-depth — if a future refactor adds
        a caller that forgets the normalize step, the quoting still
        prevents path traversal at URL construction time.
        """
        url = f"{self.BASE_URL}/works/{quote(work_id, safe='')}"
        params = {"select": _OPENALEX_SEED_SELECT}
        return await self._http_get(url, params=params)

    async def _fetch_referenced_works(
        self,
        seed_payload: dict[str, Any],
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Hydrate ``seed_payload['referenced_works']`` into full payloads.

        OpenAlex returns a list of work URLs (e.g.
        ``https://openalex.org/W12345``). To avoid one round-trip per
        reference we batch them in 50-id chunks via the
        ``filter=openalex:W1|W2|...`` query.
        """
        ref_urls = seed_payload.get("referenced_works") or []
        # ``_normalize_work_id`` now raises on hostile / malformed ids;
        # we silently drop those rather than aborting the whole call —
        # a single bad reference must not poison the rest of the
        # hydration batch.
        ref_ids: list[str] = []
        for url in ref_urls:
            if not url:
                continue
            try:
                ref_ids.append(self._normalize_work_id(url))
            except ValueError:
                logger.warning(
                    "openalex_skip_invalid_referenced_work",
                    referenced_work=url,
                )
        ref_ids = ref_ids[:max_results]
        if not ref_ids:
            return []

        # Batch the ID list to keep the query string within reasonable
        # bounds. ``asyncio.gather`` would cut latency further, but
        # OpenAlex's polite pool is tight enough that serial calls
        # leave more headroom for retries — and the BFS crawler in
        # Week 2 will fan out concurrency at the layer above.
        hydrated: list[dict[str, Any]] = []
        for i in range(0, len(ref_ids), _OPENALEX_ID_BATCH_SIZE):
            chunk = ref_ids[i : i + _OPENALEX_ID_BATCH_SIZE]
            # Each id was validated by ``_normalize_work_id`` so quoting
            # is a no-op for legitimate inputs; we still quote each id
            # individually as defense-in-depth (mirrors #C1 policy in
            # ``_fetch_work`` / ``_fetch_citing_works``).
            quoted_chunk = [quote(cid, safe="") for cid in chunk]
            payload = await self._http_get(
                f"{self.BASE_URL}/works",
                params={
                    "filter": "openalex:" + "|".join(quoted_chunk),
                    "per-page": str(min(len(chunk), _OPENALEX_MAX_PER_PAGE)),
                    "select": _OPENALEX_WORK_SELECT,
                },
            )
            hydrated.extend(payload.get("results") or [])

        # Preserve the original ordering (OpenAlex does not guarantee
        # filter result order matches input). We map by id then walk
        # the original list.
        by_id = {self._extract_id(p): p for p in hydrated if self._extract_id(p)}
        ordered: list[dict[str, Any]] = []
        for ref_id in ref_ids:
            ref_payload = by_id.get(ref_id)
            if ref_payload is not None:
                ordered.append(ref_payload)
        return ordered

    async def _fetch_citing_works(
        self,
        work_id: str,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """Page through ``filter=cites:{work_id}`` until done.

        We use page-based pagination (``page=N``) because our default
        max is 200 (one page). For larger requests OpenAlex's
        documentation recommends switching to cursor pagination, but
        that path is reserved for the BFS crawler in Week 2.
        """
        url = f"{self.BASE_URL}/works"
        page_size = min(_OPENALEX_MAX_PER_PAGE, max_results)
        # ``work_id`` came through ``_normalize_work_id`` already, so
        # the only legal characters are ``W`` + digits. ``quote`` is
        # therefore a no-op in practice — we apply it as
        # defense-in-depth to mirror the URL-construction policy in
        # ``_fetch_work`` (#C1).
        safe_work_id = quote(work_id, safe="")

        collected: list[dict[str, Any]] = []
        page = 1
        while len(collected) < max_results:
            payload = await self._http_get(
                url,
                params={
                    "filter": f"cites:{safe_work_id}",
                    "per-page": str(page_size),
                    "page": str(page),
                    "select": _OPENALEX_WORK_SELECT,
                },
            )
            results = payload.get("results") or []
            if not results:
                break
            collected.extend(results)

            meta = payload.get("meta") or {}
            total = meta.get("count")
            # Stop as soon as we have enough or the API has nothing more.
            if total is not None and len(collected) >= int(total):
                break
            if len(results) < page_size:
                break
            page += 1

        return collected[:max_results]

    async def _http_get(
        self,
        url: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """Issue a single GET to OpenAlex with rate limiting + error handling.

        Distinguishes:
        - 200: returns the parsed JSON body (after a content-length cap
          check; oversized bodies raise ``APIError`` before parsing).
        - 3xx (301/302/303/307/308): raises ``APIError``. We disable
          automatic redirects so a compromised or hostile upstream
          cannot redirect our (potentially polite-pool-bearing)
          request to an attacker-controlled host (#C2).
        - 404: raises ``APIError`` (the work id is unknown — not
          retryable).
        - 429: raises ``RateLimitError`` carrying the parsed
          ``Retry-After`` hint when the server provided one (#C4).
        - 5xx / other: raises ``APIError``.
        """
        await self.rate_limiter.acquire("openalex_citations")

        # Polite pool is signaled via a ``mailto`` query param. We add
        # it server-side rather than relying on the caller because
        # missing it costs the user rate-limit headroom.
        request_params = dict(params)
        if self.polite_email:
            request_params["mailto"] = self.polite_email

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=request_params,
                    timeout=aiohttp.ClientTimeout(total=self.request_timeout_seconds),
                    # Disable automatic redirect-following: an upstream
                    # 3xx pointing at an attacker-controlled host would
                    # otherwise receive our ``mailto`` polite-pool
                    # email plus any future auth header (#C2).
                    allow_redirects=False,
                ) as response:
                    if response.status == 429:
                        retry_after = self._parse_retry_after(
                            response.headers.get("Retry-After")
                        )
                        raise RateLimitError(
                            "OpenAlex rate limit exceeded",
                            retry_after=retry_after,
                        )
                    # Explicit list of redirect statuses we reject:
                    # 301/302/303/307/308 are the genuine redirects
                    # that would otherwise leak our request to whatever
                    # host the ``Location`` header names. 304 is *not*
                    # a redirect (it's "Not Modified") so it must not
                    # be treated as one.
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location", "<none>")
                        # ``repr`` neutralises CRLF (renders ``\r\n``
                        # as the literal escape) and the slice caps
                        # length — a hostile upstream cannot inject
                        # control characters or arbitrarily long
                        # payloads into our exception message.
                        safe_location = repr(location[:200])
                        raise APIError(
                            f"OpenAlex returned an unexpected redirect "
                            f"({response.status} -> {safe_location}); "
                            "redirects are disabled for SSRF protection."
                        )
                    if response.status == 404:
                        text = await response.text()
                        raise APIError(f"Work not found on OpenAlex (404): {text}")
                    if response.status != 200:
                        text = await response.text()
                        raise APIError(f"OpenAlex error {response.status}: {text}")
                    # Bound memory before parsing. First check the
                    # advertised ``content_length`` — cheapest possible
                    # rejection when the server tells us the size up
                    # front (#C3).
                    content_length = response.content_length
                    if (
                        content_length is not None
                        and content_length > _MAX_RESPONSE_BYTES
                    ):
                        raise APIError(
                            f"OpenAlex response too large: "
                            f"{content_length} bytes > {_MAX_RESPONSE_BYTES} cap."
                        )
                    # Even when ``content_length`` is absent (chunked
                    # transfer, gzip, etc.) we must enforce the cap —
                    # ``response.json()`` would otherwise buffer
                    # arbitrarily many bytes. Read at most one byte
                    # over the cap so we can detect (and reject)
                    # overruns without ever holding more than cap+1 in
                    # memory.
                    raw = await response.content.read(_MAX_RESPONSE_BYTES + 1)
                    if len(raw) > _MAX_RESPONSE_BYTES:
                        raise APIError(
                            f"OpenAlex response exceeded "
                            f"{_MAX_RESPONSE_BYTES} bytes (streaming/chunked)."
                        )
                    body: dict[str, Any] = json.loads(raw)
                    return body
        except asyncio.TimeoutError as exc:
            raise APIError(
                f"OpenAlex request timed out after " f"{self.request_timeout_seconds}s"
            ) from exc

    @staticmethod
    def _parse_retry_after(value: Optional[str]) -> Optional[float]:
        """Parse an HTTP ``Retry-After`` header value to seconds.

        RFC 7231 §7.1.3 allows two forms:
        - delta-seconds (a non-negative integer), e.g. ``"120"``.
        - HTTP-date (RFC 7231 §7.1.1.1), e.g.
          ``"Wed, 21 Oct 2015 07:28:00 GMT"``.

        Returns ``None`` when the header is absent or unparsable;
        callers should treat ``None`` as "no hint, use your own
        backoff" and never trust the value blindly (negative or
        far-future dates clamp to ``0.0``). Mirrors the post-#118
        S2 client implementation so the orchestrator sees a
        consistent shape across both providers (#C4).
        """
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        # Numeric (delta-seconds) form first — it's the common case.
        try:
            seconds = float(value)
        except ValueError:
            seconds = None  # type: ignore[assignment]
        if seconds is not None:
            return max(0.0, seconds)
        # HTTP-date form. ``parsedate_to_datetime`` returns a tz-aware
        # datetime when the input includes a zone (RFC HTTP-dates
        # always do); it raises ``ValueError`` (or in pathological
        # cases ``TypeError``) on bad input.
        try:
            target = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        # Defensive: a non-conforming upstream may send an HTTP-date
        # with no timezone token, in which case ``parsedate_to_datetime``
        # returns a *naive* datetime. Subtracting a naive datetime
        # from a tz-aware ``datetime.now`` raises ``TypeError`` and
        # would escape ``_http_get`` unwrapped — a DoS-adjacent
        # failure on the 429 path. Coerce naive → UTC so we still
        # produce a useful backoff hint instead of dropping the value.
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        now = datetime.now(target.tzinfo)
        delta = (target - now).total_seconds()
        return max(0.0, delta)

    # ------------------------------------------------------------------
    # Payload <-> CitationNode glue
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_work_id(value: str) -> str:
        """Strip the ``https://openalex.org/`` prefix and validate.

        OpenAlex's ``referenced_works`` field stores full URLs; the
        REST endpoints want the bare id (``W12345``). Accepts either
        form so callers can pass whichever is convenient.

        The returned id is guaranteed to match ``_WORK_ID_PATTERN`` —
        the strict ``^W\\d{1,15}$`` allow-list — and to be free of any
        URL/traversal metacharacter listed in
        ``_WORK_ID_FORBIDDEN_SUBSTRINGS``. Any failure raises
        ``ValueError`` so the URL builder upstream is never asked to
        interpolate a hostile payload (#C1).

        Raises:
            ValueError: If the input is empty after trimming, exceeds
                ``_MAX_WORK_ID_LENGTH``, contains a forbidden
                substring, or fails the regex match.
        """
        if not value:
            raise ValueError(f"Invalid OpenAlex work_id: {value!r}")
        cleaned = value.strip()
        if "/" in cleaned:
            # Last path segment after any URL prefix. Accepts both bare
            # ids and full ``https://openalex.org/Wxxx`` URLs.
            cleaned = cleaned.rsplit("/", 1)[-1]

        # Length check first — cheapest rejection for payload-stuffing.
        if not cleaned or len(cleaned) > _MAX_WORK_ID_LENGTH:
            raise ValueError(f"Invalid OpenAlex work_id: {value!r}")

        # Forbid-list before regex so the failure mode is explicit on
        # the worst payloads even if someone later loosens the regex.
        if any(substr in cleaned for substr in _WORK_ID_FORBIDDEN_SUBSTRINGS):
            raise ValueError(f"Invalid OpenAlex work_id: {value!r}")

        if not _WORK_ID_PATTERN.match(cleaned):
            raise ValueError(f"Invalid OpenAlex work_id: {value!r}")

        return cleaned

    @classmethod
    def _extract_id(cls, payload: dict[str, Any]) -> Optional[str]:
        """Return the bare OpenAlex id from a work payload, or None.

        Returns ``None`` when ``id`` is absent OR when the value fails
        the strict ``_normalize_work_id`` validator. This shields the
        caller (``_payload_to_node`` / hydration map building) from
        upstream payloads carrying malformed or hostile ids — those
        rows are silently dropped rather than poisoning the URL builder.
        """
        raw = payload.get("id")
        if not raw:
            return None
        try:
            return cls._normalize_work_id(str(raw))
        except ValueError:
            return None

    def _payload_to_node(self, payload: dict[str, Any]) -> CitationNode:
        """Convert an OpenAlex work payload into a :class:`CitationNode`."""
        oa_id = self._extract_id(payload)
        if not oa_id:
            raise KeyError("OpenAlex payload missing id")

        external_ids: dict[str, str] = {"openalex": oa_id}
        # ``ids`` is OpenAlex's catch-all dict of cross-references
        # (doi, mag, pmid, openalex). Some are URLs; we strip them so
        # downstream consumers see bare values.
        ids_dict = payload.get("ids") or {}
        for key, value in ids_dict.items():
            if not value or not isinstance(value, str):
                continue
            if key == "openalex":
                # Already captured under "openalex" above; skip to
                # avoid duplicating into the external_ids map.
                continue
            external_ids[str(key).lower()] = self._strip_id_prefix(str(key), value)

        # Top-level ``doi`` is sometimes a URL; prefer ids.doi when set
        # but fall back to top-level for older payloads.
        if "doi" not in external_ids:
            top_doi = payload.get("doi")
            if isinstance(top_doi, str) and top_doi:
                external_ids["doi"] = self._strip_id_prefix("doi", top_doi)

        title = payload.get("title") or "Unknown Title"

        return CitationNode(
            paper_id=make_paper_node_id("openalex", oa_id),
            external_ids=external_ids,
            title=title,
            year=payload.get("publication_year"),
            citation_count=int(payload.get("cited_by_count") or 0),
            reference_count=int(payload.get("referenced_works_count") or 0),
        )

    @staticmethod
    def _strip_id_prefix(key: str, value: str) -> str:
        """Strip well-known URL prefixes from an OpenAlex ``ids`` value.

        OpenAlex publishes its cross-references as URLs (e.g.
        ``https://doi.org/10.1/abc``). The downstream graph wants bare
        identifiers so it can render them in any convention. We only
        strip prefixes we can verify; unknown shapes pass through.
        """
        prefixes = {
            "doi": "https://doi.org/",
            "openalex": "https://openalex.org/",
            "mag": (
                "https://www.microsoft.com/en-us/research/project/"
                "microsoft-academic-graph/"
            ),
            "pmid": "https://pubmed.ncbi.nlm.nih.gov/",
            "pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/",
        }
        prefix = prefixes.get(key.lower())
        if prefix and value.startswith(prefix):
            return value[len(prefix) :]
        return value

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, endpoint: str, paper_id: str, max_results: int) -> str:
        """Derive a stable cache key.

        The cache key includes ``polite_email_set`` so anonymous-pool
        and polite-pool fetches do not share entries (see class
        docstring for the rationale).
        """
        polite_bit = "1" if self.polite_email else "0"
        raw = f"{endpoint}|{paper_id}|{max_results}|polite={polite_bit}"
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
