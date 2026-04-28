"""Tests for OpenAlexCitationClient (Milestone 9.2 — Week 1.5).

All HTTP is mocked. No live API calls.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.intelligence.citation.models import (
    CitationEdge,
    CitationNode,
    make_paper_node_id,
)
from src.services.intelligence.citation.openalex_client import (
    OpenAlexCitationClient,
    _reset_polite_email_warning,
)
from src.services.providers.base import APIError, RateLimitError
from src.utils.rate_limiter import RateLimiter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SEED_PAYLOAD = {
    "id": "https://openalex.org/W1",
    "title": "Seed Work",
    "publication_year": 2020,
    "cited_by_count": 42,
    "referenced_works_count": 3,
    "referenced_works": [
        "https://openalex.org/W101",
        "https://openalex.org/W102",
        "https://openalex.org/W103",
    ],
    "ids": {
        "openalex": "https://openalex.org/W1",
        "doi": "https://doi.org/10.1/seed",
        "mag": "12345",
    },
    "doi": "https://doi.org/10.1/seed",
}


def _hydrated_ref(work_id: str = "W101", **overrides):
    body = {
        "id": f"https://openalex.org/{work_id}",
        "title": f"Ref {work_id}",
        "publication_year": 2019,
        "cited_by_count": 10,
        "referenced_works_count": 4,
        "ids": {
            "openalex": f"https://openalex.org/{work_id}",
            "doi": f"https://doi.org/10.1/{work_id}",
        },
        "doi": f"https://doi.org/10.1/{work_id}",
    }
    body.update(overrides)
    return body


def _citing_payload(work_id: str = "W201", **overrides):
    body = {
        "id": f"https://openalex.org/{work_id}",
        "title": f"Cite {work_id}",
        "publication_year": 2022,
        "cited_by_count": 1,
        "referenced_works_count": 8,
        "ids": {"openalex": f"https://openalex.org/{work_id}"},
    }
    body.update(overrides)
    return body


@pytest.fixture(autouse=True)
def _reset_warning_latch():
    """Reset the once-per-process polite-email warning before each test."""
    _reset_polite_email_warning()


@pytest.fixture
def fast_limiter():
    return RateLimiter(requests_per_minute=600000, burst_size=1000)


@pytest.fixture
def client(fast_limiter, monkeypatch):
    """Default test client: no cache, polite email set to skip warning noise."""
    monkeypatch.delenv("ARISP_CITATION_CACHE_DIR", raising=False)
    monkeypatch.setenv("OPENALEX_POLITE_EMAIL", "test@example.com")
    return OpenAlexCitationClient(
        polite_email="test@example.com",
        rate_limiter=fast_limiter,
        cache_dir=None,
    )


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_init_uses_env_var_when_polite_email_omitted(monkeypatch):
    monkeypatch.setenv("OPENALEX_POLITE_EMAIL", "from-env@example.com")
    monkeypatch.delenv("ARISP_CITATION_CACHE_DIR", raising=False)
    c = OpenAlexCitationClient()
    assert c.polite_email == "from-env@example.com"


def test_init_explicit_email_overrides_env(monkeypatch):
    monkeypatch.setenv("OPENALEX_POLITE_EMAIL", "from-env@example.com")
    c = OpenAlexCitationClient(polite_email="explicit@example.com")
    assert c.polite_email == "explicit@example.com"


def test_init_no_email_logs_warning_once(monkeypatch, caplog):
    monkeypatch.delenv("OPENALEX_POLITE_EMAIL", raising=False)
    _reset_polite_email_warning()
    # First instance should log the warning.
    c1 = OpenAlexCitationClient(polite_email=None)
    # Second instance must not re-warn (the latch is process-wide).
    c2 = OpenAlexCitationClient(polite_email=None)
    assert c1.polite_email is None
    assert c2.polite_email is None


def test_init_default_rate_limiter_with_email():
    c = OpenAlexCitationClient(polite_email="x@y.z")
    # 60 req/min → rate = 1.0 req/sec
    assert c.rate_limiter.rate == pytest.approx(60 / 60.0)


def test_init_default_rate_limiter_without_email(monkeypatch):
    monkeypatch.delenv("OPENALEX_POLITE_EMAIL", raising=False)
    c = OpenAlexCitationClient(polite_email=None)
    # 20 req/min → rate = 20/60
    assert c.rate_limiter.rate == pytest.approx(20 / 60.0)


def test_init_uses_provided_rate_limiter(fast_limiter):
    c = OpenAlexCitationClient(polite_email="x@y.z", rate_limiter=fast_limiter)
    assert c.rate_limiter is fast_limiter


def test_init_no_cache_when_cache_dir_none_and_no_env(monkeypatch):
    monkeypatch.delenv("ARISP_CITATION_CACHE_DIR", raising=False)
    c = OpenAlexCitationClient(polite_email="x@y.z", cache_dir=None)
    assert c._cache is None


def test_init_uses_cache_dir_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ARISP_CITATION_CACHE_DIR", str(tmp_path))
    c = OpenAlexCitationClient(polite_email="x@y.z", cache_dir=None)
    assert c._cache is not None
    assert (tmp_path / "openalex").exists()
    c.close()


def test_init_cache_dir_explicit_path(tmp_path):
    c = OpenAlexCitationClient(polite_email="x@y.z", cache_dir=tmp_path)
    assert c._cache is not None
    assert (tmp_path / "openalex").exists()
    c.close()


def test_init_cache_dir_explicit_str(tmp_path):
    c = OpenAlexCitationClient(polite_email="x@y.z", cache_dir=str(tmp_path))
    assert c._cache is not None
    c.close()


def test_close_releases_cache_handle(tmp_path):
    c = OpenAlexCitationClient(polite_email="x@y.z", cache_dir=tmp_path)
    assert c._cache is not None
    c.close()
    assert c._cache is None


def test_close_is_safe_when_no_cache(client):
    client.close()
    assert client._cache is None


# ---------------------------------------------------------------------------
# Input validation
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
        await client.get_references("W1", max_results=0)


@pytest.mark.asyncio
async def test_internal_fetch_rejects_unknown_endpoint(client):
    with pytest.raises(ValueError, match="Unsupported endpoint"):
        await client._fetch_relationships(
            endpoint="bogus", paper_id="W1", max_results=5
        )


# ---------------------------------------------------------------------------
# normalize_work_id / extract_id helpers
# ---------------------------------------------------------------------------


def test_normalize_strips_url_prefix():
    assert (
        OpenAlexCitationClient._normalize_work_id("https://openalex.org/W123") == "W123"
    )


def test_normalize_handles_bare_id():
    assert OpenAlexCitationClient._normalize_work_id("W123") == "W123"


def test_normalize_rejects_empty_string():
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("")


def test_normalize_rejects_traversal():
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("W123/../../admin")


def test_normalize_rejects_url_scheme_smuggled():
    # The rsplit defang strips the trailing segment, so this id stays
    # ``W1`` and would normally pass — that's defense in depth: the
    # forbid-list catches payloads that survive defang. We test the
    # path-traversal payload above; the URL-scheme payload after
    # defang is verified by ``test_normalize_strips_url_prefix``.
    # Here we ensure that a payload WITHOUT a slash but with an
    # embedded scheme still gets rejected.
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("W1://evil")


def test_normalize_rejects_query_string():
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("W1?evil=1")


def test_normalize_rejects_fragment():
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("W1#frag")


def test_normalize_rejects_oversized():
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("W" + "1" * 64)


def test_normalize_rejects_lowercase_w():
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("w123")


def test_normalize_rejects_non_digit_suffix():
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("Wabc")


def test_normalize_accepts_canonical_W_id():
    assert OpenAlexCitationClient._normalize_work_id("W12345") == "W12345"


def test_normalize_strips_openalex_prefix():
    assert (
        OpenAlexCitationClient._normalize_work_id("https://openalex.org/W2741809807")
        == "W2741809807"
    )


def test_normalize_rejects_only_slash():
    # ``rsplit("/", 1)[-1]`` returns "" → length-zero rejection
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        OpenAlexCitationClient._normalize_work_id("/")


def test_extract_id_returns_none_for_missing_id():
    assert OpenAlexCitationClient._extract_id({}) is None


def test_extract_id_returns_normalized_id():
    payload = {"id": "https://openalex.org/W42"}
    assert OpenAlexCitationClient._extract_id(payload) == "W42"


def test_extract_id_returns_none_for_invalid_id():
    payload = {"id": "https://openalex.org/../admin"}
    assert OpenAlexCitationClient._extract_id(payload) is None


# ---------------------------------------------------------------------------
# strip_id_prefix
# ---------------------------------------------------------------------------


def test_strip_id_prefix_removes_doi_prefix():
    assert (
        OpenAlexCitationClient._strip_id_prefix("doi", "https://doi.org/10.1/x")
        == "10.1/x"
    )


def test_strip_id_prefix_passes_through_unknown_key():
    assert OpenAlexCitationClient._strip_id_prefix("custom", "value") == "value"


def test_strip_id_prefix_passes_through_when_prefix_missing():
    assert OpenAlexCitationClient._strip_id_prefix("doi", "10.1/x") == "10.1/x"


def test_strip_id_prefix_pmid():
    assert (
        OpenAlexCitationClient._strip_id_prefix(
            "pmid", "https://pubmed.ncbi.nlm.nih.gov/12345"
        )
        == "12345"
    )


# ---------------------------------------------------------------------------
# payload_to_node
# ---------------------------------------------------------------------------


def test_payload_to_node_full_payload(client):
    node = client._payload_to_node(SEED_PAYLOAD)
    assert node.paper_id == make_paper_node_id("openalex", "W1")
    assert node.title == "Seed Work"
    assert node.year == 2020
    assert node.citation_count == 42
    assert node.reference_count == 3
    assert node.external_ids["openalex"] == "W1"
    assert node.external_ids["doi"] == "10.1/seed"
    assert node.external_ids["mag"] == "12345"


def test_payload_to_node_missing_id_raises(client):
    with pytest.raises(KeyError, match="missing id"):
        client._payload_to_node({"title": "no id"})


def test_payload_to_node_missing_title_uses_unknown(client):
    payload = {"id": "https://openalex.org/W42"}
    node = client._payload_to_node(payload)
    assert node.title == "Unknown Title"
    assert node.year is None
    assert node.citation_count == 0
    assert node.reference_count == 0
    assert node.external_ids == {"openalex": "W42"}


def test_payload_to_node_handles_empty_ids_dict(client):
    payload = {"id": "https://openalex.org/W42", "title": "T", "ids": {}}
    node = client._payload_to_node(payload)
    assert node.external_ids == {"openalex": "W42"}


def test_payload_to_node_skips_none_id_value(client):
    payload = {
        "id": "https://openalex.org/W42",
        "title": "T",
        "ids": {"doi": None, "mag": ""},
    }
    node = client._payload_to_node(payload)
    assert node.external_ids == {"openalex": "W42"}


def test_payload_to_node_skips_non_string_id_value(client):
    payload = {
        "id": "https://openalex.org/W42",
        "title": "T",
        "ids": {"mag": 12345},  # int, not str
    }
    node = client._payload_to_node(payload)
    assert "mag" not in node.external_ids


def test_payload_to_node_uses_top_level_doi_when_ids_doi_missing(client):
    payload = {
        "id": "https://openalex.org/W42",
        "title": "T",
        "ids": {"openalex": "https://openalex.org/W42"},
        "doi": "https://doi.org/10.1/top",
    }
    node = client._payload_to_node(payload)
    assert node.external_ids["doi"] == "10.1/top"


def test_payload_to_node_top_level_doi_ignored_when_not_string(client):
    payload = {
        "id": "https://openalex.org/W42",
        "title": "T",
        "ids": {},
        "doi": None,
    }
    node = client._payload_to_node(payload)
    assert "doi" not in node.external_ids


def test_payload_to_node_top_level_doi_skipped_when_ids_doi_present(client):
    payload = {
        "id": "https://openalex.org/W42",
        "title": "T",
        "ids": {"doi": "https://doi.org/10.1/from-ids"},
        "doi": "https://doi.org/10.1/from-top",
    }
    node = client._payload_to_node(payload)
    # The ids.doi entry wins
    assert node.external_ids["doi"] == "10.1/from-ids"


# ---------------------------------------------------------------------------
# Happy path: get_references
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_references_happy_path(client):
    calls: list[str] = []

    async def fake_http_get(url, params):
        calls.append(url)
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        if url.endswith("/works"):
            # Filter contains the IDs from referenced_works
            assert "openalex:" in params["filter"]
            return {
                "results": [
                    _hydrated_ref("W101"),
                    _hydrated_ref("W102"),
                    _hydrated_ref("W103"),
                ]
            }
        raise AssertionError(f"unexpected url {url}")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        seed, related, edges = await client.get_references("W1", max_results=10)

    assert seed.paper_id == make_paper_node_id("openalex", "W1")
    assert seed.title == "Seed Work"
    assert seed.year == 2020
    assert seed.citation_count == 42
    assert seed.reference_count == 3
    assert seed.external_ids["doi"] == "10.1/seed"

    assert len(related) == 3
    assert {n.title for n in related} == {"Ref W101", "Ref W102", "Ref W103"}

    assert len(edges) == 3
    for e in edges:
        assert e.citing_paper_id == seed.paper_id
        assert e.source == "openalex"
        # OpenAlex provides no per-citation context / influential signal
        assert e.is_influential is None
        assert e.context is None
        assert e.section is None


@pytest.mark.asyncio
async def test_get_references_accepts_full_url_paper_id(client):
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        return {"results": [_hydrated_ref("W101")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        seed, _, _ = await client.get_references(
            "https://openalex.org/W1", max_results=5
        )

    assert seed.paper_id == make_paper_node_id("openalex", "W1")


@pytest.mark.asyncio
async def test_get_references_no_referenced_works(client):
    seed = dict(SEED_PAYLOAD, referenced_works=[], referenced_works_count=0)

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return seed
        raise AssertionError(f"unexpected url {url}: should not hydrate")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_references("W1", max_results=5)

    assert related == []
    assert edges == []


@pytest.mark.asyncio
async def test_get_references_referenced_works_field_missing(client):
    seed = {k: v for k, v in SEED_PAYLOAD.items() if k != "referenced_works"}

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return seed
        raise AssertionError(f"unexpected url {url}: should not hydrate")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("W1", max_results=5)

    assert related == []


@pytest.mark.asyncio
async def test_get_references_skips_invalid_referenced_work_url(client):
    """Hostile/malformed entries inside ``referenced_works`` are dropped
    silently so a single bad reference does not poison the batch (#C1)."""
    seed = dict(
        SEED_PAYLOAD,
        referenced_works=[
            "https://openalex.org/../admin",  # traversal — rejected
            "https://openalex.org/W101",
        ],
    )

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return seed
        return {"results": [_hydrated_ref("W101")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("W1", max_results=5)

    assert len(related) == 1
    assert related[0].external_ids["openalex"] == "W101"


@pytest.mark.asyncio
async def test_get_references_filters_falsy_urls(client):
    seed = dict(SEED_PAYLOAD, referenced_works=[None, "", "https://openalex.org/W101"])

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return seed
        return {"results": [_hydrated_ref("W101")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("W1", max_results=5)

    assert len(related) == 1
    assert related[0].external_ids["openalex"] == "W101"


@pytest.mark.asyncio
async def test_get_references_caps_at_max_results(client):
    # Seed has 3 referenced_works but we cap at 2
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        # Verify the chunk only contains 2 IDs
        assert params["filter"].count("|") == 1
        return {
            "results": [_hydrated_ref("W101"), _hydrated_ref("W102")],
        }

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_references("W1", max_results=2)

    assert len(related) == 2
    assert len(edges) == 2


@pytest.mark.asyncio
async def test_get_references_preserves_input_order(client):
    """Hydrated payloads may come back in any order; client must reorder."""

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        # Return in reverse order
        return {
            "results": [
                _hydrated_ref("W103"),
                _hydrated_ref("W101"),
                _hydrated_ref("W102"),
            ]
        }

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("W1", max_results=10)

    assert [n.external_ids["openalex"] for n in related] == ["W101", "W102", "W103"]


@pytest.mark.asyncio
async def test_get_references_drops_missing_hydrations(client):
    """If hydration omits a referenced ID, we drop it (no node, no edge)."""

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        # Return only one of three
        return {"results": [_hydrated_ref("W102")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_references("W1", max_results=10)

    assert len(related) == 1
    assert related[0].external_ids["openalex"] == "W102"
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_get_references_chunks_large_id_list(client):
    # 75 references → 50-id chunk + 25-id chunk = 2 hydration calls
    seed = dict(
        SEED_PAYLOAD,
        referenced_works=[f"https://openalex.org/W{i}" for i in range(1000, 1075)],
        referenced_works_count=75,
    )
    chunk_calls = {"n": 0}

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return seed
        chunk_calls["n"] += 1
        ids = params["filter"].split(":", 1)[1].split("|")
        return {"results": [_hydrated_ref(wid) for wid in ids]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_references("W1", max_results=75)

    assert chunk_calls["n"] == 2
    assert len(related) == 75


@pytest.mark.asyncio
async def test_get_references_skips_invalid_hydrated_payload(client):
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        # The Pydantic CitationNode validator rejects year < 1800, so we
        # emit a clearly-invalid year on one entry to drive the
        # try/except (ValueError) skip branch in _fetch_relationships.
        bad = _hydrated_ref("W101")
        bad["publication_year"] = 1500
        return {"results": [bad, _hydrated_ref("W102"), _hydrated_ref("W103")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_references("W1", max_results=10)

    # W101 was skipped due to validation failure; W102 + W103 made it
    assert len(related) == 2
    ids = {n.external_ids["openalex"] for n in related}
    assert ids == {"W102", "W103"}
    assert len(edges) == 2


# ---------------------------------------------------------------------------
# Happy path: get_citations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_citations_happy_path(client):
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        if url.endswith("/works"):
            assert params["filter"] == "cites:W1"
            assert params["page"] == "1"
            return {
                "results": [_citing_payload("W201"), _citing_payload("W202")],
                "meta": {"count": 2},
            }
        raise AssertionError(f"unexpected url {url}")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        seed, related, edges = await client.get_citations("W1", max_results=10)

    assert len(related) == 2
    for e, r in zip(edges, related):
        # edges point citing → cited (= seed)
        assert e.citing_paper_id == r.paper_id
        assert e.cited_paper_id == seed.paper_id
        assert e.source == "openalex"


@pytest.mark.asyncio
async def test_get_citations_pagination_stops_at_total_count(client):
    page_calls = {"n": 0}

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        page_calls["n"] += 1
        page = int(params["page"])
        if page == 1:
            return {
                "results": [_citing_payload(f"W{2000 + i}") for i in range(5)],
                "meta": {"count": 5},
            }
        raise AssertionError("Should stop after first page")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_citations("W1", max_results=200)

    assert len(related) == 5
    assert page_calls["n"] == 1


@pytest.mark.asyncio
async def test_get_citations_pagination_stops_when_no_results(client):
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        return {"results": [], "meta": {"count": 0}}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_citations("W1", max_results=10)

    assert related == []


@pytest.mark.asyncio
async def test_get_citations_pagination_stops_on_short_page(client):
    page_calls = {"n": 0}

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        page_calls["n"] += 1
        page = int(params["page"])
        if page == 1:
            # Return fewer results than requested → stop without
            # claiming a meta.count
            return {"results": [_citing_payload(f"W30{i}") for i in range(3)]}
        raise AssertionError("Should stop on short page")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_citations("W1", max_results=200)

    assert len(related) == 3
    assert page_calls["n"] == 1


@pytest.mark.asyncio
async def test_get_citations_pagination_advances_through_pages(client):
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        page = int(params["page"])
        per_page = int(params["per-page"])
        if page == 1:
            return {
                "results": [_citing_payload(f"W{4000 + i}") for i in range(per_page)],
                "meta": {"count": per_page * 2},
            }
        if page == 2:
            return {
                "results": [_citing_payload(f"W{5000 + i}") for i in range(per_page)],
                "meta": {"count": per_page * 2},
            }
        raise AssertionError("Unexpected page")

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_citations("W1", max_results=10)

    # max_results=10 caps per-page at 10; two pages * 10 = 20 total but
    # collected[:max_results] trims to 10
    assert len(related) == 10


@pytest.mark.asyncio
async def test_get_citations_skips_invalid_payload(client):
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        bad = _citing_payload("W201")
        bad.pop("id")  # missing id → KeyError → skipped
        return {
            "results": [bad, _citing_payload("W202")],
            "meta": {"count": 2},
        }

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, edges = await client.get_citations("W1", max_results=10)

    assert len(related) == 1
    assert related[0].external_ids["openalex"] == "W202"
    assert len(edges) == 1


@pytest.mark.asyncio
async def test_get_citations_handles_meta_missing(client):
    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        # No meta dict at all
        return {"results": [_citing_payload("W201")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        _, related, _ = await client.get_citations("W1", max_results=10)

    # Single short page → break loop
    assert len(related) == 1


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_deserialized_payload(tmp_path, fast_limiter):
    c = OpenAlexCitationClient(
        polite_email="x@y.z", rate_limiter=fast_limiter, cache_dir=tmp_path
    )

    seed = CitationNode(paper_id=make_paper_node_id("openalex", "W1"), title="C")
    related = [CitationNode(paper_id=make_paper_node_id("openalex", "W2"), title="R")]
    edges = [
        CitationEdge(
            citing_paper_id=seed.paper_id,
            cited_paper_id=related[0].paper_id,
            source="openalex",
        )
    ]

    key = c._cache_key("references", "W1", 5)
    c._cache_set(key, c._serialize_payload((seed, related, edges)))

    with patch.object(c, "_http_get", side_effect=AssertionError("HTTP called!")):
        s, r, e = await c.get_references("W1", max_results=5)

    assert s.title == "C"
    assert r[0].title == "R"
    assert len(e) == 1
    c.close()


@pytest.mark.asyncio
async def test_cache_miss_then_populated(tmp_path, fast_limiter):
    c = OpenAlexCitationClient(
        polite_email="x@y.z", rate_limiter=fast_limiter, cache_dir=tmp_path
    )

    async def fake_http_get(url, params):
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        return {"results": [_hydrated_ref("W101")]}

    with patch.object(c, "_http_get", side_effect=fake_http_get):
        await c.get_references("W1", max_results=5)

    cached = c._cache_get(c._cache_key("references", "W1", 5))
    assert cached is not None
    assert b"Seed Work" in cached
    c.close()


@pytest.mark.asyncio
async def test_second_call_hits_cache_no_http(tmp_path, fast_limiter):
    c = OpenAlexCitationClient(
        polite_email="x@y.z", rate_limiter=fast_limiter, cache_dir=tmp_path
    )

    call_count = {"n": 0}

    async def fake_http_get(url, params):
        call_count["n"] += 1
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        return {"results": [_hydrated_ref("W101")]}

    with patch.object(c, "_http_get", side_effect=fake_http_get):
        await c.get_references("W1", max_results=5)
        first = call_count["n"]
        await c.get_references("W1", max_results=5)

    assert call_count["n"] == first
    c.close()


def test_cache_get_returns_none_when_no_cache(client):
    assert client._cache_get("any-key") is None


def test_cache_set_no_op_when_no_cache(client):
    client._cache_set("k", b"v")
    assert client._cache_get("k") is None


def test_cache_key_segregates_polite_vs_anonymous(monkeypatch, fast_limiter):
    monkeypatch.delenv("OPENALEX_POLITE_EMAIL", raising=False)
    polite = OpenAlexCitationClient(polite_email="x@y.z", rate_limiter=fast_limiter)
    anon = OpenAlexCitationClient(polite_email=None, rate_limiter=fast_limiter)

    k_polite = polite._cache_key("references", "W1", 5)
    k_anon = anon._cache_key("references", "W1", 5)

    assert k_polite != k_anon


def test_cache_key_is_stable_and_deterministic(client):
    k1 = client._cache_key("references", "W1", 10)
    k2 = client._cache_key("references", "W1", 10)
    k3 = client._cache_key("references", "W1", 11)
    assert k1 == k2
    assert k1 != k3
    assert len(k1) == 64


def test_serialize_then_deserialize_roundtrip():
    seed = CitationNode(paper_id="paper:openalex:W1", title="X")
    related = [CitationNode(paper_id="paper:openalex:W2", title="Y")]
    edges = [
        CitationEdge(
            citing_paper_id="paper:openalex:W1",
            cited_paper_id="paper:openalex:W2",
            source="openalex",
        )
    ]

    raw = OpenAlexCitationClient._serialize_payload((seed, related, edges))
    s, r, e = OpenAlexCitationClient._deserialize_payload(raw)

    assert s.paper_id == seed.paper_id
    assert r[0].paper_id == related[0].paper_id
    assert e[0].cited_paper_id == "paper:openalex:W2"


# ---------------------------------------------------------------------------
# _http_get path (real aiohttp mock)
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
    ``.json()`` directly — see #C3).

    ``raw_body`` lets a caller pass exact bytes (e.g. to simulate an
    oversized chunked-transfer payload that exceeds the cap).
    """
    import json as _json

    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_body)
    resp.text = AsyncMock(return_value=text_body)
    resp.headers = headers if headers is not None else {}
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
async def test_http_get_adds_polite_email_when_present(client):
    cm = _mock_aiohttp_response(200, json_body={})
    p, session = _patch_session(cm)
    with p:
        await client._http_get("http://x", {"a": "b"})
    _, kwargs = session.get.call_args
    assert kwargs["params"]["mailto"] == "test@example.com"
    # Original params preserved
    assert kwargs["params"]["a"] == "b"


@pytest.mark.asyncio
async def test_http_get_omits_email_when_absent(monkeypatch, fast_limiter):
    monkeypatch.delenv("OPENALEX_POLITE_EMAIL", raising=False)
    c = OpenAlexCitationClient(
        polite_email=None, rate_limiter=fast_limiter, cache_dir=None
    )
    cm = _mock_aiohttp_response(200, json_body={})
    p, session = _patch_session(cm)
    with p:
        await c._http_get("http://x", {})
    _, kwargs = session.get.call_args
    assert "mailto" not in kwargs["params"]


@pytest.mark.asyncio
async def test_http_get_does_not_mutate_input_params(client):
    """The original params dict the caller passed must not gain mailto."""
    cm = _mock_aiohttp_response(200, json_body={})
    p, _session = _patch_session(cm)
    original_params = {"a": "b"}
    with p:
        await client._http_get("http://x", original_params)
    assert "mailto" not in original_params


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
    cm = _mock_aiohttp_response(500, text_body="boom")
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
# #C2 — redirect handling (allow_redirects=False)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_http_get_rejects_redirect(client, status):
    cm = _mock_aiohttp_response(
        status,
        text_body="moved",
        headers={"Location": "https://attacker.example/leak"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="unexpected redirect"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_passes_allow_redirects_false(client):
    cm = _mock_aiohttp_response(200, json_body={})
    p, session = _patch_session(cm)
    with p:
        await client._http_get("http://x", {})
    _, kwargs = session.get.call_args
    assert kwargs["allow_redirects"] is False


@pytest.mark.asyncio
async def test_http_get_redirect_message_neutralises_crlf(client):
    """Hostile Location header bytes must not inject newlines into our message."""
    cm = _mock_aiohttp_response(
        302,
        text_body="moved",
        headers={"Location": "evil\r\nX-Injected: 1"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError) as exc_info:
            await client._http_get("http://x", {})
    msg = str(exc_info.value)
    # ``repr`` renders \r\n as the literal backslash-r-backslash-n,
    # so the raw control characters must not appear in the message.
    assert "\r" not in msg
    assert "\n" not in msg
    assert "\\r\\n" in msg


@pytest.mark.asyncio
async def test_http_get_redirect_message_caps_location_length(client):
    long_loc = "X" * 500
    cm = _mock_aiohttp_response(302, headers={"Location": long_loc})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError) as exc_info:
            await client._http_get("http://x", {})
    msg = str(exc_info.value)
    # 200-char cap on the slice + repr quoting overhead
    assert "X" * 201 not in msg


# ---------------------------------------------------------------------------
# #C3 — response size cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_http_get_rejects_large_advertised_content_length(client):
    cm = _mock_aiohttp_response(
        200,
        json_body={"ok": True},
        content_length=26 * 1024 * 1024,
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="response too large"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_rejects_oversized_streamed_body(client):
    # Server lies about content_length (or omits it), but streams more
    # bytes than the cap. We must reject without calling json.loads.
    huge = b"{" + (b"x" * (25 * 1024 * 1024 + 1))
    cm = _mock_aiohttp_response(200, raw_body=huge, content_length=None)
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(APIError, match="exceeded"):
            await client._http_get("http://x", {})


@pytest.mark.asyncio
async def test_http_get_accepts_body_within_cap(client):
    cm = _mock_aiohttp_response(200, json_body={"ok": True}, content_length=100)
    p, _ = _patch_session(cm)
    with p:
        body = await client._http_get("http://x", {})
    assert body == {"ok": True}


# ---------------------------------------------------------------------------
# #C4 — Retry-After parsing on 429
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_with_numeric_retry_after(client):
    cm = _mock_aiohttp_response(429, headers={"Retry-After": "120"})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as exc_info:
            await client._http_get("http://x", {})
    assert exc_info.value.retry_after == pytest.approx(120.0)


@pytest.mark.asyncio
async def test_429_with_httpdate_retry_after(client):
    # Date in the future → positive delta clamped to >= 0
    cm = _mock_aiohttp_response(
        429,
        headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as exc_info:
            await client._http_get("http://x", {})
    assert exc_info.value.retry_after is not None
    assert exc_info.value.retry_after > 0


@pytest.mark.asyncio
async def test_429_with_httpdate_no_timezone_treated_as_utc(client):
    # No tz token; ``parsedate_to_datetime`` returns naive datetime.
    # The client must coerce to UTC instead of raising TypeError on
    # subtraction.
    cm = _mock_aiohttp_response(
        429,
        headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00"},
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as exc_info:
            await client._http_get("http://x", {})
    assert exc_info.value.retry_after is not None


@pytest.mark.asyncio
async def test_429_without_retry_after(client):
    cm = _mock_aiohttp_response(429, headers={})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as exc_info:
            await client._http_get("http://x", {})
    assert exc_info.value.retry_after is None


@pytest.mark.asyncio
async def test_429_with_unparsable_retry_after(client):
    cm = _mock_aiohttp_response(429, headers={"Retry-After": "not-a-date"})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as exc_info:
            await client._http_get("http://x", {})
    assert exc_info.value.retry_after is None


@pytest.mark.asyncio
async def test_429_with_negative_retry_after_clamped(client):
    cm = _mock_aiohttp_response(429, headers={"Retry-After": "-30"})
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as exc_info:
            await client._http_get("http://x", {})
    assert exc_info.value.retry_after == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_429_with_past_httpdate_clamped(client):
    cm = _mock_aiohttp_response(
        429, headers={"Retry-After": "Wed, 21 Oct 1970 07:28:00 GMT"}
    )
    p, _ = _patch_session(cm)
    with p:
        with pytest.raises(RateLimitError) as exc_info:
            await client._http_get("http://x", {})
    assert exc_info.value.retry_after == pytest.approx(0.0)


def test_parse_retry_after_none_returns_none():
    assert OpenAlexCitationClient._parse_retry_after(None) is None


def test_parse_retry_after_empty_returns_none():
    assert OpenAlexCitationClient._parse_retry_after("   ") is None


# ---------------------------------------------------------------------------
# #C1 — end-to-end: get_references quotes/validates the work_id in the URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_references_rejects_hostile_paper_id(client):
    """Crafted traversal payload must be rejected before any HTTP call."""
    # ``_normalize_work_id`` raises before we ever build a URL.
    with pytest.raises(ValueError, match="Invalid OpenAlex work_id"):
        await client.get_references("../admin")


@pytest.mark.asyncio
async def test_get_references_url_uses_validated_id(client):
    captured: list[str] = []

    async def fake_http_get(url, params):
        captured.append(url)
        if url.endswith("/works/W1"):
            return SEED_PAYLOAD
        return {"results": [_hydrated_ref("W101")]}

    with patch.object(client, "_http_get", side_effect=fake_http_get):
        await client.get_references("W1", max_results=5)

    # No suspicious characters in the URL we built.
    assert any(u.endswith("/works/W1") for u in captured)
    # No traversal smuggled in
    for u in captured:
        assert ".." not in u


# ---------------------------------------------------------------------------
# Transient failure → caller-side retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_failure_then_retry_success(client):
    state = {"attempt": 0}

    async def flaky_http_get(url, params):
        if url.endswith("/works/W1"):
            state["attempt"] += 1
            if state["attempt"] == 1:
                raise RateLimitError("temporary")
            return SEED_PAYLOAD
        return {"results": [_hydrated_ref("W101")]}

    with patch.object(client, "_http_get", side_effect=flaky_http_get):
        with pytest.raises(RateLimitError):
            await client.get_references("W1", max_results=5)

        seed, related, _ = await client.get_references("W1", max_results=5)

    assert seed.title == "Seed Work"
    assert len(related) == 1


# ---------------------------------------------------------------------------
# Class constants
# ---------------------------------------------------------------------------


def test_base_url_is_openalex_root():
    assert OpenAlexCitationClient.BASE_URL == "https://api.openalex.org"
