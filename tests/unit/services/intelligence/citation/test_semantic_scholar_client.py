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


def _mock_aiohttp_response(status, json_body=None, text_body="oops"):
    """Build an async-context-manager-compatible mocked response."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_body)
    resp.text = AsyncMock(return_value=text_body)

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
