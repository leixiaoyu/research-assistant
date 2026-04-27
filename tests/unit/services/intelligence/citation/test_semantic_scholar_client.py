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
    status, json_body=None, text_body="oops", headers=None, content_length=None
):
    """Build an async-context-manager-compatible mocked response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_body)
    resp.text = AsyncMock(return_value=text_body)
    resp.headers = headers if headers is not None else {}
    # ``content_length`` is ``Optional[int]`` on aiohttp.ClientResponse;
    # default to ``None`` so the size-cap branch is exercised separately.
    resp.content_length = content_length

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


@pytest.mark.asyncio
async def test_paper_id_with_doi_is_quoted_in_url(client):
    """Legitimate DOIs (with `/`) pass validation but are URL-quoted."""
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


# ---------------------------------------------------------------------------
# Security hardening — Fix #9: Retry-After parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_with_numeric_retry_after(client):
    """Numeric Retry-After (delta-seconds) must be parsed and surfaced."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={"Retry-After": "120"})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after_seconds == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_429_with_httpdate_retry_after(client):
    """HTTP-date Retry-After must be parsed to seconds-from-now."""
    # A date well in the future yields a positive delta; we don't pin
    # the exact value (clock-dependent) but assert it's plausible.
    cm = _mock_aiohttp_response(
        429,
        text_body="slow",
        headers={"Retry-After": "Wed, 01 Jan 2200 00:00:00 GMT"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after_seconds is not None
    assert ei.value.retry_after_seconds > 0


@pytest.mark.asyncio
async def test_429_without_retry_after(client):
    """Missing Retry-After header → ``retry_after_seconds`` is ``None``."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after_seconds is None


@pytest.mark.asyncio
async def test_429_with_unparseable_retry_after(client):
    """Garbage Retry-After value safely degrades to ``None``."""
    cm = _mock_aiohttp_response(
        429, text_body="slow", headers={"Retry-After": "not-a-date"}
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after_seconds is None


@pytest.mark.asyncio
async def test_429_with_empty_retry_after(client):
    """Empty Retry-After string degrades to ``None``."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={"Retry-After": "   "})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after_seconds is None


@pytest.mark.asyncio
async def test_429_with_past_httpdate_clamps_to_zero(client):
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
    assert ei.value.retry_after_seconds == 0.0


@pytest.mark.asyncio
async def test_429_with_negative_numeric_clamps_to_zero(client):
    """Negative numeric Retry-After clamps to ``0.0``."""
    cm = _mock_aiohttp_response(429, text_body="slow", headers={"Retry-After": "-30"})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as ei:
            await client._http_get("http://x", {})
    assert ei.value.retry_after_seconds == 0.0


def test_parse_retry_after_returns_none_for_none():
    """Static helper: ``None`` input returns ``None``."""
    assert SemanticScholarCitationClient._parse_retry_after(None) is None


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
    """Missing Content-Length header → defer to aiohttp's stream guard."""
    cm = _mock_aiohttp_response(200, json_body={"ok": True}, content_length=None)
    p, _ = _patch_session(cm)
    with p:
        body = await client._http_get("http://x", {})
    assert body == {"ok": True}


# ---------------------------------------------------------------------------
# Security hardening — Fix #19: cache key API-key context
# ---------------------------------------------------------------------------


def test_cache_key_differs_with_and_without_api_key(fast_limiter):
    """Auth presence must change the cache key — never share slots."""
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
    tmp_path, fast_limiter
):
    """End-to-end: same paper, different auth context → separate slots.

    Both clients must be able to populate their own slot independently;
    a fetch by one must not satisfy the other.
    """
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
    assert err.retry_after_seconds is None


def test_rate_limit_error_accepts_retry_after():
    err = RateLimitError("slow down", retry_after_seconds=42.5)
    assert err.retry_after_seconds == 42.5
