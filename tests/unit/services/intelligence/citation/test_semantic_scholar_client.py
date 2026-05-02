"""Tests for SemanticScholarCitationClient (Milestone 9.2 — Week 1).

All HTTP is mocked. No live API calls.
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.intelligence.citation.models import (
    CitationEdge,
    CitationNode,
    make_paper_node_id,
)
from src.services.intelligence.citation.semantic_scholar_client import (
    SemanticScholarCitationClient,
)
from src.services.providers.base import APIError, RateLimitError
from src.utils.rate_limiter import RateLimiter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SEED_PAYLOAD = {
    "paperId": "seed1",
    "externalIds": {"DOI": "10.1/seed", "ArXiv": None},
    "title": "Seed Paper",
    "year": 2020,
    "citationCount": 42,
    "referenceCount": 7,
}


def _ref_entry(paper_id: str = "ref1", **overrides):
    """Build a single S2 /references row."""
    body = {
        "citedPaper": {
            "paperId": paper_id,
            "externalIds": {"DOI": "10.1/" + paper_id},
            "title": f"Ref {paper_id}",
            "year": 2019,
            "citationCount": 10,
            "referenceCount": 3,
        },
        "contexts": ["Context one", "Context two"],
        "intents": ["methodology"],
        "isInfluential": True,
    }
    body.update(overrides)
    return body


def _cite_entry(paper_id: str = "cite1", **overrides):
    """Build a single S2 /citations row."""
    body = {
        "citingPaper": {
            "paperId": paper_id,
            "externalIds": {"DOI": "10.1/" + paper_id},
            "title": f"Cite {paper_id}",
            "year": 2021,
            "citationCount": 5,
            "referenceCount": 12,
        },
        "contexts": ["Cite context"],
        "intents": [],
        "isInfluential": False,
    }
    body.update(overrides)
    return body


@pytest.fixture
def fast_limiter():
    """A nearly no-op rate limiter so tests don't sleep."""
    return RateLimiter(requests_per_minute=600000, burst_size=1000)


@pytest.fixture
def client(fast_limiter):
    """Default test client: no cache, no env-derived API key."""
    # Ensure env var doesn't leak into the test
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SEMANTIC_SCHOLAR_API_KEY", None)
        os.environ.pop("ARISP_CITATION_CACHE_DIR", None)
        c = SemanticScholarCitationClient(
            api_key=None,
            rate_limiter=fast_limiter,
            cache_dir=None,
        )
        yield c


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_init_uses_env_var_when_api_key_omitted(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "from-env")
    monkeypatch.delenv("ARISP_CITATION_CACHE_DIR", raising=False)
    c = SemanticScholarCitationClient()
    assert c.api_key == "from-env"


def test_init_explicit_api_key_overrides_env(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "from-env")
    c = SemanticScholarCitationClient(api_key="explicit")
    assert c.api_key == "explicit"


def test_init_no_api_key_when_env_unset(monkeypatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    c = SemanticScholarCitationClient(api_key=None)
    assert c.api_key is None


def test_init_default_rate_limiter_with_api_key(monkeypatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    c = SemanticScholarCitationClient(api_key="x")
    # 20 req/min with API key → rate = 20/60
    assert c.rate_limiter.rate == pytest.approx(20 / 60.0)


def test_init_default_rate_limiter_without_api_key(monkeypatch):
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    c = SemanticScholarCitationClient(api_key=None)
    # 12 req/min without API key → rate = 12/60
    assert c.rate_limiter.rate == pytest.approx(12 / 60.0)


def test_init_uses_provided_rate_limiter(fast_limiter):
    c = SemanticScholarCitationClient(api_key="x", rate_limiter=fast_limiter)
    assert c.rate_limiter is fast_limiter


def test_init_no_cache_when_cache_dir_none_and_no_env(monkeypatch):
    monkeypatch.delenv("ARISP_CITATION_CACHE_DIR", raising=False)
    c = SemanticScholarCitationClient(cache_dir=None)
    assert c._cache is None


def test_init_uses_cache_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ARISP_CITATION_CACHE_DIR", str(tmp_path))
    c = SemanticScholarCitationClient(cache_dir=None)
    assert c._cache is not None
    assert (tmp_path / "s2").exists()
    c.close()


def test_init_cache_dir_explicit_path(tmp_path):
    c = SemanticScholarCitationClient(cache_dir=tmp_path)
    assert c._cache is not None
    assert (tmp_path / "s2").exists()
    c.close()


def test_init_cache_dir_explicit_str(tmp_path):
    c = SemanticScholarCitationClient(cache_dir=str(tmp_path))
    assert c._cache is not None
    c.close()


def test_close_releases_cache_handle(tmp_path):
    c = SemanticScholarCitationClient(cache_dir=tmp_path)
    assert c._cache is not None
    c.close()
    assert c._cache is None


def test_close_is_safe_when_no_cache(client):
    # Should not raise even though _cache is None
    client.close()
    assert client._cache is None


# ---------------------------------------------------------------------------
# Input validation in _fetch_relationships
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_references_rejects_empty_paper_id(client):
    with pytest.raises(ValueError, match="non-empty"):
        await client.get_references("")


@pytest.mark.asyncio
async def test_get_references_rejects_whitespace_paper_id(client):
    with pytest.raises(ValueError, match="non-empty"):
        await client.get_references("   ")


@pytest.mark.asyncio
async def test_get_references_rejects_zero_max_results(client):
    with pytest.raises(ValueError, match="max_results must be"):
        await client.get_references("abc", max_results=0)


@pytest.mark.asyncio
async def test_internal_fetch_rejects_unknown_endpoint(client):
    with pytest.raises(ValueError, match="Unsupported endpoint"):
        await client._fetch_relationships(
            endpoint="bogus", paper_id="abc", max_results=5
        )


# ---------------------------------------------------------------------------
# Happy-path: get_references
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_references_happy_path(client):
    # First call → seed metadata. Second → page 1. Third → page 2 (empty stop).
    calls: list[str] = []

    async def fake_http_get(url, params):
        calls.append(url)
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        if url.endswith("/paper/seed1/references"):
            offset = int(params["offset"])
            if offset == 0:
                return {"data": [_ref_entry("ref1"), _ref_entry("ref2")], "next": 2}
            return {"data": []}
        raise AssertionError(f"unexpected url {url}")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        seed, related, edges = await client.get_references("seed1", max_results=10)

    assert seed.paper_id == make_paper_node_id("s2", "seed1")
    assert seed.title == "Seed Paper"
    assert seed.year == 2020
    assert seed.citation_count == 42
    assert seed.reference_count == 7
    assert seed.external_ids["s2"] == "seed1"
    assert seed.external_ids["doi"] == "10.1/seed"
    # ArXiv was None → skipped
    assert "arxiv" not in seed.external_ids

    assert len(related) == 2
    assert {n.title for n in related} == {"Ref ref1", "Ref ref2"}

    # Edges point seed → ref (citing → cited), source set
    assert len(edges) == 2
    for e in edges:
        assert e.citing_paper_id == seed.paper_id
        assert e.source == "semantic_scholar"
        assert e.is_influential is True
        assert e.context == "Context one"
        assert e.section == "methodology"


# ---------------------------------------------------------------------------
# Happy-path: get_citations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_citations_happy_path(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        if url.endswith("/paper/seed1/citations"):
            return {"data": [_cite_entry("cite1")]}
        raise AssertionError(f"unexpected url {url}")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        seed, related, edges = await client.get_citations("seed1", max_results=10)

    assert len(related) == 1
    edge = edges[0]
    # For citations, related → seed
    assert edge.citing_paper_id == related[0].paper_id
    assert edge.cited_paper_id == seed.paper_id
    assert edge.is_influential is False
    # intents was [] → section None
    assert edge.section is None
    assert edge.context == "Cite context"


# ---------------------------------------------------------------------------
# Pagination edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_stops_at_max_results(client):
    # Page returns 100 entries; max_results=3 → trims to 3
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        return {"data": [_ref_entry(f"ref{i}") for i in range(100)], "next": 100}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_references("seed1", max_results=3)

    assert len(related) == 3
    assert len(edges) == 3


@pytest.mark.asyncio
async def test_pagination_stops_when_data_empty(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        return {"data": [], "next": 50}  # next is ignored when data empty

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("seed1", max_results=10)

    assert related == []


@pytest.mark.asyncio
async def test_pagination_stops_when_next_missing(client):
    page_calls = {"n": 0}

    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        page_calls["n"] += 1
        # Single page, no `next`
        return {"data": [_ref_entry("only")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("seed1", max_results=10)

    assert len(related) == 1
    assert page_calls["n"] == 1


@pytest.mark.asyncio
async def test_pagination_stops_when_next_equals_offset(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        offset = int(params["offset"])
        return {"data": [_ref_entry("only")], "next": offset}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("seed1", max_results=10)

    assert len(related) == 1


@pytest.mark.asyncio
async def test_pagination_advances_through_multiple_pages(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        offset = int(params["offset"])
        if offset == 0:
            return {"data": [_ref_entry(f"r{i}") for i in range(5)], "next": 5}
        if offset == 5:
            return {"data": [_ref_entry(f"r{i}") for i in range(5, 8)]}
        raise AssertionError(f"unexpected offset {offset}")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("seed1", max_results=10)

    assert len(related) == 8


# ---------------------------------------------------------------------------
# Malformed responses
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_entries_with_missing_related_payload(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        return {
            "data": [
                {"contexts": [], "intents": []},  # no citingPaper / citedPaper
                _ref_entry("ref-good"),
            ]
        }

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_references("seed1", max_results=10)

    assert len(related) == 1
    assert related[0].title == "Ref ref-good"
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_skips_entries_with_invalid_payload_node(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        return {
            "data": [
                # Missing paperId → KeyError → skipped
                {"citedPaper": {"title": "no id"}, "contexts": [], "intents": []},
                _ref_entry("ref-good"),
            ]
        }

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_references("seed1", max_results=10)

    assert len(related) == 1
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_seed_payload_missing_paper_id_raises(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return {"title": "no id"}  # missing paperId
        return {"data": []}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        with pytest.raises(KeyError, match="missing paperId"):
            await client.get_references("seed1", max_results=5)


@pytest.mark.asyncio
async def test_payload_with_missing_optional_fields(client):
    """citationCount / referenceCount / title / year all absent."""

    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return {"paperId": "seed1"}  # only required field
        return {"data": []}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        seed, related, edges = await client.get_references("seed1", max_results=5)

    assert seed.title == "Unknown Title"
    assert seed.year is None
    assert seed.citation_count == 0
    assert seed.reference_count == 0
    assert seed.external_ids == {"s2": "seed1"}
    assert related == []
    assert edges == []


@pytest.mark.asyncio
async def test_external_ids_filters_falsy_values(client):
    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return {
                "paperId": "seed1",
                "externalIds": {"DOI": "10.1/x", "ArXiv": "", "PubMed": None},
            }
        return {"data": []}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        seed, _, _ = await client.get_references("seed1", max_results=5)

    assert seed.external_ids == {"s2": "seed1", "doi": "10.1/x"}


# ---------------------------------------------------------------------------
# _first_context helper (covers all branches)
# ---------------------------------------------------------------------------


def test_first_context_returns_none_for_none():
    assert SemanticScholarCitationClient._first_context(None) is None


def test_first_context_returns_none_for_empty_list():
    assert SemanticScholarCitationClient._first_context([]) is None


def test_first_context_returns_first_entry():
    assert SemanticScholarCitationClient._first_context(["a", "b", "c"]) == "a"


def test_first_context_skips_falsy_entries():
    assert (
        SemanticScholarCitationClient._first_context([None, "", "first-real"])
        == "first-real"
    )


def test_first_context_returns_none_when_all_falsy():
    assert SemanticScholarCitationClient._first_context(["", None, ""]) is None


def test_first_context_handles_scalar_input():
    # Non-list scalar — defensive branch
    assert SemanticScholarCitationClient._first_context("scalar") == "scalar"


# ---------------------------------------------------------------------------
# Caching behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_deserialized_payload(tmp_path, fast_limiter):
    c = SemanticScholarCitationClient(
        api_key="x", rate_limiter=fast_limiter, cache_dir=tmp_path
    )

    seed = CitationNode(paper_id=make_paper_node_id("s2", "seed1"), title="Cached")
    related = [CitationNode(paper_id=make_paper_node_id("s2", "ref1"), title="R")]
    edges = [
        CitationEdge(
            citing_paper_id=seed.paper_id,
            cited_paper_id=related[0].paper_id,
        )
    ]

    # Pre-populate cache
    key = c._cache_key("references", "seed1", 5)
    c._cache_set(key, c._serialize_payload((seed, related, edges)))

    # _http_get must NOT be called
    with patch.object(c, "_http_get", side_effect=AssertionError("HTTP called!")):
        s, r, e = await c.get_references("seed1", max_results=5)

    assert s.title == "Cached"
    assert r[0].title == "R"
    assert len(e) == 1
    c.close()


@pytest.mark.asyncio
async def test_cache_miss_then_populated_on_success(tmp_path, fast_limiter):
    c = SemanticScholarCitationClient(
        api_key=None, rate_limiter=fast_limiter, cache_dir=tmp_path
    )

    async def fake_http_get(url, params):
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        return {"data": [_ref_entry("ref1")]}

    with patch.object(c, "_http_get", side_effect=fake_http_get):
        await c.get_references("seed1", max_results=5)

    key = c._cache_key("references", "seed1", 5)
    cached_bytes = c._cache_get(key)
    assert cached_bytes is not None
    assert b"Seed Paper" in cached_bytes
    c.close()


def test_cache_get_returns_none_when_no_cache(client):
    assert client._cache_get("any-key") is None


def test_cache_set_no_op_when_no_cache(client):
    # Must not raise when there is no cache backing
    client._cache_set("k", b"v")
    assert client._cache_get("k") is None


def test_cache_key_is_stable_and_deterministic(client):
    k1 = client._cache_key("references", "abc", 10)
    k2 = client._cache_key("references", "abc", 10)
    k3 = client._cache_key("references", "abc", 11)
    assert k1 == k2
    assert k1 != k3
    # SHA-256 hex → 64 chars
    assert len(k1) == 64


def test_serialize_then_deserialize_roundtrip():
    seed = CitationNode(paper_id="paper:s2:abc", title="X")
    related = [CitationNode(paper_id="paper:s2:def", title="Y")]
    edges = [
        CitationEdge(citing_paper_id="paper:s2:abc", cited_paper_id="paper:s2:def")
    ]

    raw = SemanticScholarCitationClient._serialize_payload((seed, related, edges))
    s, r, e = SemanticScholarCitationClient._deserialize_payload(raw)

    assert s.paper_id == seed.paper_id
    assert r[0].paper_id == related[0].paper_id
    assert e[0].cited_paper_id == "paper:s2:def"


# ---------------------------------------------------------------------------
# _http_get — actually exercise the aiohttp path
# ---------------------------------------------------------------------------


def _mock_aiohttp_response(
    status,
    json_body=None,
    text_body="oops",
    headers=None,
    content_length=None,
    raw_body=None,
):
    """Build an async-context-manager-compatible mocked response.

    ``json_body`` is the dict the production code is expected to receive
    after ``json.loads`` of the streamed body. We serialise it to bytes
    and hand them out via the mocked ``response.content.read`` (the
    production code now reads bytes itself rather than calling
    ``.json()`` directly — see #S6).

    ``raw_body`` lets a caller pass exact bytes (e.g. to simulate an
    oversized chunked-transfer payload that exceeds the cap).
    """
    import json as _json

    resp = MagicMock()
    resp.status = status
    # ``.json`` is kept as an AsyncMock so any test that *did* call it
    # before the #S6 change still gets a return value, and the
    # ``assert_not_called`` check in ``test_oversized_response_*``
    # remains a useful regression guard against re-introducing
    # ``await response.json()`` on the hot path.
    resp.json = AsyncMock(return_value=json_body)
    resp.text = AsyncMock(return_value=text_body)
    resp.headers = headers if headers is not None else {}
    # ``content_length`` is ``Optional[int]`` on aiohttp.ClientResponse;
    # default to ``None`` so the size-cap branch is exercised separately.
    resp.content_length = content_length

    if raw_body is None:
        raw_body = b"" if json_body is None else _json.dumps(json_body).encode("utf-8")
    content = MagicMock()
    content.read = AsyncMock(return_value=raw_body)
    resp.content = content

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _patch_session(response_cm):
    session = MagicMock()
    session.get = MagicMock(return_value=response_cm)
    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    return patch("aiohttp.ClientSession", return_value=session_cm), session


@pytest.mark.asyncio
async def test_http_get_returns_json_on_200(client):
    cm = _mock_aiohttp_response(200, json_body={"hello": "world"})
    p, _ = _patch_session(cm)
    with p:
        body = await client._http_get("http://x", {"a": "b"})
    assert body == {"hello": "world"}


@pytest.mark.asyncio
async def test_http_get_includes_api_key_header_when_present(fast_limiter):
    c = SemanticScholarCitationClient(
        api_key="secret", rate_limiter=fast_limiter, cache_dir=None
    )
    cm = _mock_aiohttp_response(200, json_body={})
    p, session = _patch_session(cm)
    with p:
        await c._http_get("http://x", {})
    _, kwargs = session.get.call_args
    assert kwargs["headers"] == {"x-api-key": "secret"}


@pytest.mark.asyncio
async def test_http_get_omits_header_when_no_api_key(client):
    cm = _mock_aiohttp_response(200, json_body={})
    p, session = _patch_session(cm)
    with p:
        await client._http_get("http://x", {})
    _, kwargs = session.get.call_args
    assert kwargs["headers"] == {}


@pytest.mark.asyncio
async def test_http_get_raises_rate_limit_on_429(client):
    cm = _mock_aiohttp_response(429, text_body="slow down")
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError, match="rate limit exceeded"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_raises_api_error_on_404(client):
    cm = _mock_aiohttp_response(404, text_body="not here")
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="not found"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_raises_api_error_on_500(client):
    cm = _mock_aiohttp_response(500, text_body="server explosion")
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="error 500"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_wraps_timeout_as_api_error(client):
    session_cm = MagicMock()
    session = MagicMock()
    session.get = MagicMock(side_effect=asyncio.TimeoutError())
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)
    with patch("aiohttp.ClientSession", return_value=session_cm):
        with pytest.raises(APIError, match="timed out"):
            await client._http_get("http://x", {})


# ---------------------------------------------------------------------------
# Retry-on-transient-failure: caller-side, by re-invoking after a transient
# RateLimitError / APIError. The client itself does not auto-retry; we verify
# both that the error is raised AND that a subsequent retry succeeds with
# fresh mock state. This mirrors how the future graph_builder will behave.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_failure_then_retry_success(client):
    state = {"attempt": 0}

    async def flaky_http_get(url, params):
        if url.endswith("/paper/seed1"):
            state["attempt"] += 1
            if state["attempt"] == 1:
                raise RateLimitError("temporary")
            return SEED_PAYLOAD
        return {"data": []}

    with patch.object(client, "_http_get", side_effect=flaky_http_get):
        # First attempt bubbles RateLimitError up
        with pytest.raises(RateLimitError):
            await client.get_references("seed1", max_results=5)

        # Caller retries → succeeds
        seed, related, _ = await client.get_references("seed1", max_results=5)

    assert seed.title == "Seed Paper"
    assert related == []


# ---------------------------------------------------------------------------
# Class constants
# ---------------------------------------------------------------------------


def test_base_url_is_s2_v1():
    assert (
        SemanticScholarCitationClient.BASE_URL
        == "https://api.semanticscholar.org/graph/v1"
    )


# ---------------------------------------------------------------------------
# Cache integration via end-to-end public API (covers cache hit log path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_call_hits_cache_no_http(tmp_path, fast_limiter):
    c = SemanticScholarCitationClient(
        api_key=None, rate_limiter=fast_limiter, cache_dir=tmp_path
    )

    call_count = {"n": 0}

    async def fake_http_get(url, params):
        call_count["n"] += 1
        if url.endswith("/paper/seed1"):
            return SEED_PAYLOAD
        return {"data": [_ref_entry("ref1")]}

    with patch.object(c, "_http_get", side_effect=fake_http_get):
        await c.get_references("seed1", max_results=5)
        first_call_count = call_count["n"]
        # Second call should be served from cache
        await c.get_references("seed1", max_results=5)

    assert call_count["n"] == first_call_count
    c.close()


# ---------------------------------------------------------------------------
# Security hardening (Phase 9.2) — input validation: SSRF / URL injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_id_rejects_traversal(client):
    """Path traversal attempts must be rejected before URL building."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("../../admin")


@pytest.mark.asyncio
async def test_paper_id_rejects_crlf_injection(client):
    """CRLF injection must be rejected (header-splitting vector)."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("foo HTTP/1.1\r\nHost: evil")


@pytest.mark.asyncio
async def test_paper_id_rejects_full_url(client):
    """Full URLs as paper_id must be rejected (SSRF vector)."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("http://evil")


@pytest.mark.asyncio
async def test_paper_id_rejects_query_string(client):
    """Query strings / fragments must be stripped at the validator."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("foo?evil=1#")


@pytest.mark.asyncio
async def test_get_citations_also_validates_paper_id(client):
    """The same validation gates the /citations endpoint."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_citations("../../etc/passwd")


# ---------------------------------------------------------------------------
# Security hardening (Phase 9.2, round 2) — #S9: SSRF unicode/null/long
# variants. The regex allow-list is ASCII-only; these tests pin that
# choice so a future loosening (e.g. ``re.UNICODE``) wouldn't sneak in.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_id_rejects_null_byte(client):
    """Embedded NUL must be rejected — terminator-injection vector (#S9)."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("\x00abc")


@pytest.mark.asyncio
async def test_paper_id_rejects_unicode_letter(client):
    """Greek letters look like a-z but aren't ASCII — must reject (#S9)."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("αβγ")


@pytest.mark.asyncio
async def test_paper_id_rejects_unicode_digit(client):
    """Arabic-Indic digits are not [0-9] — must reject (#S9)."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("\u0661\u0662\u0663")  # ١٢٣


@pytest.mark.asyncio
async def test_paper_id_rejects_long_string(client):
    """Length above _PAPER_ID_MAX_LENGTH (512) must be rejected (#S9).

    Bounds the URL length and protects against payload-stuffing using
    otherwise-legal characters. 513 = max+1.
    """
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("a" * 513)


@pytest.mark.asyncio
async def test_paper_id_accepts_string_at_max_length(client):
    """Length exactly at the cap is accepted by the validator (#S9, boundary).

    We exercise the validator only (not the model layer): patch
    ``_fetch_paper`` and ``_fetch_relationship_pages`` to short-circuit
    the network path so the test focuses on whether the input passes
    validation at the entry point. A return of an empty result tuple
    proves the validator did not raise.
    """
    boundary_id = "a" * 512  # exactly _PAPER_ID_MAX_LENGTH

    # Short-circuit both internal fetchers so we can isolate the
    # validator (the seed-node CitationNode itself caps at 512 chars
    # *including* the ``paper:s2:`` prefix, which is a separate concern
    # from URL-length validation tested here).
    async def fake_fetch_paper(pid):
        return {"paperId": "short"}  # bypasses model length cap

    async def fake_fetch_pages(endpoint, pid, max_results):
        return []

    with patch.object(client, "_fetch_paper", side_effect=fake_fetch_paper):
        with patch.object(
            client, "_fetch_relationship_pages", side_effect=fake_fetch_pages
        ):
            # Validator must not raise — boundary is inclusive of cap.
            seed, related, edges = await client.get_references(
                boundary_id, max_results=5
            )

    assert related == []
    assert edges == []
    assert seed is not None


@pytest.mark.asyncio
async def test_paper_id_rejects_tab(client):
    """Embedded TAB is whitespace — must reject (#S9)."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("foo\tbar")


@pytest.mark.asyncio
async def test_paper_id_rejects_backtick(client):
    """Backtick is a shell metachar — must reject (#S9)."""
    with pytest.raises(ValueError, match="Invalid paper_id"):
        await client.get_references("foo`bar")


@pytest.mark.asyncio
async def test_paper_id_with_doi_is_quoted_in_url(client):
    """Legitimate DOIs (with `/`) pass validation but are URL-quoted.

    Also asserts that colons (used by S2 namespace prefixes) round-trip
    literally through ``quote(..., safe=':')`` — see #C1.
    """
    captured: list[str] = []

    async def fake_http_get(url, params):
        captured.append(url)
        if "/paper/" in url and not url.endswith("/references"):
            return {**SEED_PAYLOAD, "paperId": "10.1/seed"}
        return {"data": []}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        await client.get_references("10.1/seed", max_results=5)

    # The slash in the DOI must be percent-encoded in the URL path so it
    # cannot escape the /paper/{id}/ segment.
    assert any("10.1%2Fseed" in u for u in captured)
    # And the original raw slash must NOT appear inside the id segment.
    assert not any("/paper/10.1/seed" in u for u in captured)
    # Colons must NOT be percent-encoded — S2 namespaces depend on them.
    assert not any("%3A" in u or "%3a" in u for u in captured)


@pytest.mark.asyncio
async def test_paper_id_with_arxiv_namespace_preserves_colon(client):
    """``arxiv:1706.03762`` — colon must round-trip literally (#C1)."""
    captured: list[str] = []

    async def fake_http_get(url, params):
        captured.append(url)
        if "/paper/" in url and not url.endswith("/references"):
            return {**SEED_PAYLOAD, "paperId": "arxiv:1706.03762"}
        return {"data": []}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        await client.get_references("arxiv:1706.03762", max_results=5)

    # The literal colon-prefixed namespace must reach S2 unencoded.
    assert any("/paper/arxiv:1706.03762" in u for u in captured)
    assert not any("arxiv%3A" in u or "arxiv%3a" in u for u in captured)


@pytest.mark.asyncio
async def test_paper_id_with_corpus_id_preserves_colon(client):
    """``CorpusId:12345`` — colon must round-trip literally (#C1)."""
    captured: list[str] = []

    async def fake_http_get(url, params):
        captured.append(url)
        if "/paper/" in url and not url.endswith("/references"):
            return {**SEED_PAYLOAD, "paperId": "CorpusId:12345"}
        return {"data": []}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        await client.get_references("CorpusId:12345", max_results=5)

    assert any("/paper/CorpusId:12345" in u for u in captured)
    assert not any("CorpusId%3A" in u or "CorpusId%3a" in u for u in captured)


# ---------------------------------------------------------------------------
# Security hardening — Fix #4: redirects disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_get_passes_allow_redirects_false(client):
    """``allow_redirects=False`` must be passed to ``session.get``."""
    cm = _mock_aiohttp_response(200, json_body={})
    p, session = _patch_session(cm)
    with p:
        await client._http_get("http://x", {})
    _, kwargs = session.get.call_args
    assert kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_http_get_raises_api_error_on_302(client):
    """A 3xx response must surface as ``APIError`` (no auto-follow)."""
    cm = _mock_aiohttp_response(
        302,
        text_body="moved",
        headers={"Location": "http://attacker.example/api"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="redirects are disabled"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_raises_api_error_on_301_without_location(client):
    """Redirect with no Location header still raises (defensive branch)."""
    cm = _mock_aiohttp_response(301, text_body="moved", headers={})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="<none>"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_304_not_treated_as_redirect_error(client):
    """304 Not Modified is not a redirect — must not raise (#S4).

    304 means "your cached copy is still good". The previous
    ``300 <= status < 400`` branch swept it up as a redirect and raised
    APIError. We narrow to the explicit redirect set
    ``{301, 302, 303, 307, 308}`` so 304 falls through to the generic
    non-200 branch (which still raises, but with the actual status —
    304 isn't a successful body for our use case).
    """
    cm = _mock_aiohttp_response(304, text_body="not modified", headers={})
    p, _ = _patch_session(cm)
    with p:
        # 304 should NOT match "redirects are disabled" — it's caught by
        # the generic non-200 branch instead.
        with pytest.raises(APIError) as ei:
            await client._http_get("http://x", {})
    assert "redirects are disabled" not in str(ei.value)
    assert "304" in str(ei.value)


@pytest.mark.asyncio
async def test_http_get_rejects_307_temporary_redirect(client):
    """307 (Temporary Redirect) must be rejected (#S7).

    Mirrors the existing 301/302 tests. Aiohttp's default behaviour
    on 307 is to repeat the request method and follow Location, which
    would leak our ``x-api-key``. Even with ``allow_redirects=False``
    we want to fail loud rather than silently return an empty body.
    """
    cm = _mock_aiohttp_response(
        307,
        text_body="moved",
        headers={"Location": "http://attacker.example/api"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="redirects are disabled"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_rejects_308_permanent_redirect(client):
    """308 (Permanent Redirect) must be rejected (#S7).

    308 is the method-preserving cousin of 301. Same SSRF concern as
    307.
    """
    cm = _mock_aiohttp_response(
        308,
        text_body="moved",
        headers={"Location": "http://attacker.example/api"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="redirects are disabled"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_rejects_303_see_other(client):
    """303 (See Other) is in the explicit redirect set; verify (#S7)."""
    cm = _mock_aiohttp_response(
        303,
        text_body="moved",
        headers={"Location": "http://attacker.example/api"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="redirects are disabled"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_redirect_location_with_crlf_is_sanitized(client):
    """A malicious ``Location: foo\\r\\nX-Inject:bar`` must not break the
    error message (#S5).

    The ``repr`` wrapper renders CRLF as the literal escape sequence
    rather than embedding control characters into the exception message
    that would later flow into structured logs.
    """
    cm = _mock_aiohttp_response(
        302,
        text_body="moved",
        headers={"Location": "foo\r\nX-Inject:bar"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError) as ei:
            await client._http_get("http://x", {})
    msg = str(ei.value)
    # Raw control characters must not appear in the message.
    assert "\r\n" not in msg
    # The escape sequence rendered by ``repr`` is what we expect.
    assert "\\r\\n" in msg


# ---------------------------------------------------------------------------
# Security hardening — Fix #9: Retry-After parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_get_429_with_numeric_retry_after(client):
    """Numeric Retry-After (delta-seconds) must be parsed and surfaced."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={"Retry-After": "120"})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_http_get_429_with_httpdate_retry_after(client):
    """HTTP-date Retry-After must be parsed to seconds-from-now (#S10).

    Asserts a tight bound rather than just ``> 0``: the test uses a
    year-2200 date so the expected delta is roughly 150-190 years in
    seconds (~5-6 billion). A buggy implementation returning the raw
    timestamp (~7e9) or ``inf`` would now be caught.
    """
    cm = _mock_aiohttp_response(
        429,
        text_body="slow",
        headers={"Retry-After": "Wed, 01 Jan 2200 00:00:00 GMT"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after is not None
    # 150-190 years in seconds is ~4.7e9 to ~6.0e9. Bracketing this
    # range catches the raw-timestamp bug (~7.3e9 in 2026) and any
    # accidental ``float("inf")`` return without being so tight that
    # clock drift on the test machine produces flakes.
    assert 4_500_000_000 < ei.value.retry_after < 6_000_000_000


@pytest.mark.asyncio
async def test_http_get_429_without_retry_after(client):
    """Missing Retry-After header → ``retry_after`` is ``None``."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after is None


@pytest.mark.asyncio
async def test_http_get_429_with_unparseable_retry_after(client):
    """Garbage Retry-After value safely degrades to ``None``."""
    cm = _mock_aiohttp_response(
        429, text_body="slow", headers={"Retry-After": "not-a-date"}
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after is None


@pytest.mark.asyncio
async def test_http_get_429_with_empty_retry_after(client):
    """Empty Retry-After string degrades to ``None``."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={"Retry-After": "   "})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after is None


@pytest.mark.asyncio
async def test_http_get_429_with_past_httpdate_clamps_to_zero(client):
    """Past HTTP-date clamps to ``0.0`` rather than going negative."""
    cm = _mock_aiohttp_response(
        429,
        text_body="slow",
        headers={"Retry-After": "Wed, 01 Jan 2000 00:00:00 GMT"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after == 0.0


@pytest.mark.asyncio
async def test_http_get_429_with_negative_numeric_clamps_to_zero(client):
    """Negative numeric Retry-After clamps to ``0.0``."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={"Retry-After": "-30"})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after == 0.0


def test_parse_retry_after_returns_none_for_none():
    """Static helper: ``None`` input returns ``None``."""
    assert SemanticScholarCitationClient._parse_retry_after(None) is None


@pytest.mark.asyncio
async def test_http_get_429_with_httpdate_no_timezone_treated_as_utc(client):
    """HTTP-date with no zone token must coerce to UTC, not crash (#S3).

    ``parsedate_to_datetime`` returns a *naive* datetime when the input
    omits the trailing zone (which RFC HTTP-dates always include, but
    non-conforming upstreams sometimes don't). Subtracting that from a
    tz-aware ``datetime.now`` previously raised an unwrapped TypeError
    that escaped ``_http_get`` — DoS-adjacent on the 429 path. We now
    coerce naive → UTC and produce a sane positive backoff hint.
    """
    # A future date with NO timezone token (note: no 'GMT' / '+0000')
    cm = _mock_aiohttp_response(
        429,
        text_body="slow",
        headers={"Retry-After": "Wed, 01 Jan 2200 00:00:00"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    # No exception should escape; we should get a finite, positive hint.
    assert ei.value.retry_after is not None
    assert ei.value.retry_after > 0


# ---------------------------------------------------------------------------
# Security hardening — Fix #10: response size cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_response_raises_before_parse(client):
    """``content_length`` > cap must raise without invoking ``json()``."""
    cm = _mock_aiohttp_response(
        200,
        json_body={"should": "not be parsed"},
        content_length=10 * 1024 * 1024 + 1,  # one byte over the cap
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="response too large"):
            await client._http_get("http://x", {})

    # The body parser must NOT have been called for the oversized path.
    resp = cm.__aenter__.return_value
    resp.json.assert_not_called()


@pytest.mark.asyncio
async def test_response_at_cap_is_accepted(client):
    """A response exactly at the cap is accepted (boundary)."""
    cm = _mock_aiohttp_response(
        200, json_body={"ok": True}, content_length=10 * 1024 * 1024
    )
    p, _ = _patch_session(cm)
    with p:
        body = await client._http_get("http://x", {})
    assert body == {"ok": True}


@pytest.mark.asyncio
async def test_response_with_no_content_length_is_parsed(client):
    """Missing Content-Length header → bounded read still parses small body."""
    cm = _mock_aiohttp_response(200, json_body={"ok": True}, content_length=None)
    p, _ = _patch_session(cm)
    with p:
        body = await client._http_get("http://x", {})
    assert body == {"ok": True}


@pytest.mark.asyncio
async def test_chunked_oversized_response_rejected_after_read(client):
    """Chunked transfer with no Content-Length must still be size-capped (#S6).

    A misbehaving / hostile upstream can omit Content-Length and stream
    arbitrarily many bytes. The bounded read of ``cap + 1`` bytes lets
    us detect (and reject) the overflow without ever buffering more than
    the cap+1 in memory.
    """
    cap = 10 * 1024 * 1024  # _MAX_RESPONSE_BYTES
    oversized = b"x" * (cap + 100)
    cm = _mock_aiohttp_response(
        200,
        json_body=None,
        content_length=None,  # advertised size missing → fall through
        raw_body=oversized,
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="streaming/chunked"):
            await client._http_get("http://x", {})


# ---------------------------------------------------------------------------
# Security hardening — Fix #19: cache key API-key context
# ---------------------------------------------------------------------------


def test_cache_key_differs_with_and_without_api_key(fast_limiter, monkeypatch):
    """Auth presence must change the cache key — never share slots.

    Explicitly clear ``SEMANTIC_SCHOLAR_API_KEY`` so the constructor's
    env-var fallback (``api_key=None`` -> ``os.getenv(...)``) doesn't
    silently authenticate the "anonymous" client when CI / a developer's
    shell has the key set.
    """
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    c_anon = SemanticScholarCitationClient(
        api_key=None, rate_limiter=fast_limiter, cache_dir=None
    )
    c_auth = SemanticScholarCitationClient(
        api_key="secret", rate_limiter=fast_limiter, cache_dir=None
    )
    k_anon = c_anon._cache_key("references", "seed1", 5)
    k_auth = c_auth._cache_key("references", "seed1", 5)
    assert k_anon != k_auth


def test_cache_key_does_not_leak_api_key_value(fast_limiter):
    """Two authenticated clients with *different* keys must collide.

    The fix folds in only ``bool(self.api_key)`` — the secret value
    must NEVER appear in the hashed input. Two clients that both have
    *any* key should produce the same cache key for the same query.
    """
    c1 = SemanticScholarCitationClient(
        api_key="key-one", rate_limiter=fast_limiter, cache_dir=None
    )
    c2 = SemanticScholarCitationClient(
        api_key="key-two", rate_limiter=fast_limiter, cache_dir=None
    )
    assert c1._cache_key("references", "seed1", 5) == c2._cache_key(
        "references", "seed1", 5
    )


@pytest.mark.asyncio
async def test_authenticated_and_anonymous_clients_keep_separate_cache_slots(
    tmp_path, fast_limiter, monkeypatch
):
    """End-to-end: same paper, different auth context → separate slots.

    Both clients must be able to populate their own slot independently;
    a fetch by one must not satisfy the other.

    Explicitly clear ``SEMANTIC_SCHOLAR_API_KEY`` so the constructor's
    env-var fallback doesn't silently authenticate the "anonymous"
    client when the test env has the key set.
    """
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
    anon_seed = {**SEED_PAYLOAD, "title": "Anon-fetched"}
    auth_seed = {**SEED_PAYLOAD, "title": "Auth-fetched"}

    c_anon = SemanticScholarCitationClient(
        api_key=None, rate_limiter=fast_limiter, cache_dir=tmp_path
    )
    c_auth = SemanticScholarCitationClient(
        api_key="secret", rate_limiter=fast_limiter, cache_dir=tmp_path
    )

    async def anon_http(url, params):
        if "/references" in url:
            return {"data": []}
        return anon_seed

    async def auth_http(url, params):
        if "/references" in url:
            return {"data": []}
        return auth_seed

    with patch.object(c_anon, "_http_get", side_effect=anon_http):
        seed_anon, _, _ = await c_anon.get_references("seed1", max_results=5)
    with patch.object(c_auth, "_http_get", side_effect=auth_http):
        seed_auth, _, _ = await c_auth.get_references("seed1", max_results=5)

    assert seed_anon.title == "Anon-fetched"
    assert seed_auth.title == "Auth-fetched"

    # Re-issue both calls — each must hit its own cache slot, not the
    # other client's. We assert this by making the HTTP path raise: a
    # cache hit means no HTTP, so the AssertionError never fires.
    async def boom(url, params):
        raise AssertionError("HTTP must not be called on cache hit")

    with patch.object(c_anon, "_http_get", side_effect=boom):
        seed_anon2, _, _ = await c_anon.get_references("seed1", max_results=5)
    with patch.object(c_auth, "_http_get", side_effect=boom):
        seed_auth2, _, _ = await c_auth.get_references("seed1", max_results=5)

    assert seed_anon2.title == "Anon-fetched"
    assert seed_auth2.title == "Auth-fetched"

    c_anon.close()
    c_auth.close()


# ---------------------------------------------------------------------------
# RateLimitError — backwards-compatible constructor
# ---------------------------------------------------------------------------


def test_rate_limit_error_default_retry_after_is_none():
    """Old call sites that pass only a message must still work."""
    err = RateLimitError("oops")
    assert str(err) == "oops"
    assert err.retry_after is None


def test_rate_limit_error_accepts_retry_after():
    """``retry_after`` keyword arg is preserved on the exception (#SR-9.2).

    This is the construction path used by ``_http_get`` after parsing
    a numeric or HTTP-date Retry-After header. The retry orchestrator
    at ``src.utils.retry:124`` reads ``e.retry_after`` to honour the
    server-supplied backoff hint; if the field name drifts again the
    hint is silently dropped.
    """
    err = RateLimitError("slow down", retry_after=42.5)
    assert err.retry_after == 42.5


# ---------------------------------------------------------------------------
# _payload_to_node: publication_date parsing (C-2) + ICC assertions (H-T5)
# ---------------------------------------------------------------------------


def test_payload_to_node_with_publication_date(client):
    """publicationDate ISO string is parsed to date(2023, 6, 1)."""
    from datetime import date

    payload = {
        "paperId": "s2abc",
        "title": "Dated Paper",
        "year": 2023,
        "citationCount": 10,
        "referenceCount": 2,
        "publicationDate": "2023-06-01",
    }
    node = client._payload_to_node(payload)
    assert node.publication_date == date(2023, 6, 1)


def test_payload_to_node_without_publication_date(client):
    """Absent publicationDate field results in publication_date=None."""
    payload = {
        "paperId": "s2abc",
        "title": "No Date Paper",
        "year": 2022,
        "citationCount": 5,
        "referenceCount": 1,
    }
    node = client._payload_to_node(payload)
    assert node.publication_date is None


def test_payload_to_node_with_malformed_publication_date(client, caplog):
    """Malformed publicationDate string gracefully degrades to None."""
    import structlog.testing

    payload = {
        "paperId": "s2abc",
        "title": "Bad Date Paper",
        "year": 2021,
        "citationCount": 3,
        "referenceCount": 0,
        "publicationDate": "not-a-date",
    }
    with structlog.testing.capture_logs() as logs:
        node = client._payload_to_node(payload)
    assert node.publication_date is None
    warning_events = [e for e in logs if e.get("log_level") == "warning"]
    assert any(
        "malformed_publication_date" in e.get("event", "") for e in warning_events
    )


def test_payload_to_node_with_influential_citation_count(client):
    """influentialCitationCount=42 is forwarded to CitationNode."""
    payload = {
        "paperId": "s2icc",
        "title": "ICC Paper",
        "year": 2020,
        "citationCount": 100,
        "referenceCount": 5,
        "influentialCitationCount": 42,
    }
    node = client._payload_to_node(payload)
    assert node.influential_citation_count == 42


def test_payload_to_node_without_influential_citation_count(client):
    """Absent influentialCitationCount results in None."""
    payload = {
        "paperId": "s2icc",
        "title": "No ICC Paper",
        "year": 2019,
        "citationCount": 50,
        "referenceCount": 3,
    }
    node = client._payload_to_node(payload)
    assert node.influential_citation_count is None
