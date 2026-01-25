"""
Extended test coverage for SemanticScholarProvider to meet ≥95% requirement.

This file adds comprehensive tests for all uncovered code paths identified
in the coverage analysis.
"""

import pytest
from unittest.mock import AsyncMock, patch
import asyncio
from datetime import date
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
)


@pytest.fixture
def provider():
    return SemanticScholarProvider(api_key="test_key_12345")


@pytest.fixture
def topic():
    return ResearchTopic(
        query="test query", timeframe=TimeframeRecent(value="48h"), max_papers=10
    )


# ============================================================================
# Property Tests (Coverage: name, requires_api_key)
# ============================================================================


def test_provider_name(provider):
    """Test name property returns 'semantic_scholar'"""
    assert provider.name == "semantic_scholar"


def test_requires_api_key(provider):
    """Test requires_api_key property returns True"""
    assert provider.requires_api_key is True


# ============================================================================
# validate_query() Tests (Coverage: Lines 48-59)
# ============================================================================


def test_validate_query_success(provider):
    """Test validate_query accepts valid queries"""
    assert provider.validate_query("machine learning") == "machine learning"
    assert provider.validate_query("  spaced query  ") == "spaced query"
    assert provider.validate_query("AI AND robotics") == "AI AND robotics"


def test_validate_query_empty_string(provider):
    """Test validate_query rejects empty strings"""
    with pytest.raises(ValueError, match="cannot be empty"):
        provider.validate_query("")


def test_validate_query_whitespace_only(provider):
    """Test validate_query rejects whitespace-only strings"""
    with pytest.raises(ValueError, match="cannot be empty"):
        provider.validate_query("   ")


def test_validate_query_too_long(provider):
    """Test validate_query rejects queries over 500 characters"""
    long_query = "a" * 501
    with pytest.raises(ValueError, match="too long"):
        provider.validate_query(long_query)


def test_validate_query_max_length(provider):
    """Test validate_query accepts exactly 500 characters"""
    query_500 = "a" * 500
    assert provider.validate_query(query_500) == query_500


def test_validate_query_control_characters(provider):
    """Test validate_query rejects control characters"""
    with pytest.raises(ValueError, match="invalid control characters"):
        provider.validate_query("test\x00query")

    with pytest.raises(ValueError, match="invalid control characters"):
        provider.validate_query("test\x1bquery")


def test_validate_query_allows_tabs_newlines(provider):
    """Test validate_query allows tabs and newlines"""
    # Tabs and newlines should be allowed
    assert provider.validate_query("test\tquery") == "test\tquery"
    assert provider.validate_query("test\nquery") == "test\nquery"
    assert provider.validate_query("test\rquery") == "test\rquery"


# ============================================================================
# search() Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_search_invalid_query_returns_empty(provider, topic):
    """Test search returns empty list for invalid queries"""
    topic.query = ""
    papers = await provider.search(topic)
    assert papers == []


@pytest.mark.asyncio
async def test_search_server_error_500(provider, topic):
    """Test search handles 500 server errors"""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_get.return_value.__aenter__.return_value = mock_resp

        # Should raise after retries
        with pytest.raises(Exception):
            await provider.search(topic)


@pytest.mark.asyncio
async def test_search_server_error_503(provider, topic):
    """Test search handles 503 service unavailable"""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 503
        mock_get.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(Exception):
            await provider.search(topic)


@pytest.mark.asyncio
async def test_search_non_200_status(provider, topic):
    """Test search handles non-200 status codes (4xx)"""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="Bad Request")
        mock_get.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(Exception):  # RetryError wraps APIError
            await provider.search(topic)


@pytest.mark.asyncio
async def test_search_timeout_error(provider, topic):
    """Test search handles timeout errors"""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.return_value.__aenter__.side_effect = asyncio.TimeoutError()

        with pytest.raises(Exception):  # RetryError wraps APIError
            await provider.search(topic)


# ============================================================================
# _build_query_params() Timeframe Tests
# ============================================================================


def test_build_query_params_since_year(provider, topic):
    """Test _build_query_params with TimeframeSinceYear"""
    topic.timeframe = TimeframeSinceYear(value=2020)

    params = provider._build_query_params(topic, "test query")

    assert params["query"] == "test query"
    assert params["year"] == "2020-"
    assert "publicationDateOrYear" not in params


def test_build_query_params_date_range(provider, topic):
    """Test _build_query_params with TimeframeDateRange"""
    topic.timeframe = TimeframeDateRange(
        start_date=date(2023, 1, 1), end_date=date(2023, 12, 31)
    )

    params = provider._build_query_params(topic, "test query")

    assert params["query"] == "test query"
    assert params["publicationDateOrYear"] == "2023-01-01:2023-12-31"
    assert "year" not in params


def test_build_query_params_recent_hours(provider, topic):
    """Test _build_query_params with TimeframeRecent (hours)"""
    topic.timeframe = TimeframeRecent(value="48h")

    params = provider._build_query_params(topic, "test")

    assert "publicationDateOrYear" in params
    assert ":" in params["publicationDateOrYear"]


def test_build_query_params_recent_days(provider, topic):
    """Test _build_query_params with TimeframeRecent (days)"""
    topic.timeframe = TimeframeRecent(value="7d")

    params = provider._build_query_params(topic, "test")

    assert "publicationDateOrYear" in params
    assert ":" in params["publicationDateOrYear"]


# ============================================================================
# _parse_response() Tests - Edge Cases
# ============================================================================


def test_parse_response_empty_data(provider):
    """Test _parse_response handles empty data array"""
    response = {"data": []}
    papers = provider._parse_response(response)
    assert papers == []


def test_parse_response_missing_data_key(provider):
    """Test _parse_response handles missing data key"""
    response = {}
    papers = provider._parse_response(response)
    assert papers == []


def test_parse_response_null_data(provider):
    """Test _parse_response handles null data"""
    response = {"data": None}
    papers = provider._parse_response(response)
    assert papers == []


def test_parse_response_missing_authors(provider):
    """Test _parse_response handles missing authors"""
    response = {"data": [{"paperId": "123", "title": "Test Paper", "authors": None}]}

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].authors == []


def test_parse_response_empty_authors(provider):
    """Test _parse_response handles empty authors array"""
    response = {"data": [{"paperId": "123", "title": "Test Paper", "authors": []}]}

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].authors == []


def test_parse_response_author_without_name(provider):
    """Test _parse_response skips authors without names"""
    response = {
        "data": [
            {
                "paperId": "123",
                "title": "Test Paper",
                "authors": [
                    {"authorId": "1"},  # No name
                    {"name": "Author 2", "authorId": "2"},
                ],
            }
        ]
    }

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert len(papers[0].authors) == 1
    assert papers[0].authors[0].name == "Author 2"


def test_parse_response_missing_open_access_pdf(provider):
    """Test _parse_response handles missing openAccessPdf"""
    response = {"data": [{"paperId": "123", "title": "Test Paper"}]}

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].open_access_pdf is None


def test_parse_response_null_open_access_pdf(provider):
    """Test _parse_response handles null openAccessPdf"""
    response = {
        "data": [{"paperId": "123", "title": "Test Paper", "openAccessPdf": None}]
    }

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].open_access_pdf is None


def test_parse_response_open_access_pdf_without_url(provider):
    """Test _parse_response handles openAccessPdf without url"""
    response = {
        "data": [
            {
                "paperId": "123",
                "title": "Test Paper",
                "openAccessPdf": {"status": "CLOSED"},
            }
        ]
    }

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].open_access_pdf is None


def test_parse_response_open_access_pdf_with_url(provider):
    """Test _parse_response extracts openAccessPdf URL"""
    response = {
        "data": [
            {
                "paperId": "123",
                "title": "Test Paper",
                "openAccessPdf": {"url": "https://example.com/paper.pdf"},
            }
        ]
    }

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert str(papers[0].open_access_pdf) == "https://example.com/paper.pdf"


def test_parse_response_invalid_publication_date(provider):
    """Test _parse_response handles invalid publication date format"""
    response = {
        "data": [
            {"paperId": "123", "title": "Test Paper", "publicationDate": "invalid-date"}
        ]
    }

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].publication_date is None


def test_parse_response_valid_publication_date(provider):
    """Test _parse_response parses valid publication date"""
    response = {
        "data": [
            {"paperId": "123", "title": "Test Paper", "publicationDate": "2023-06-15"}
        ]
    }

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].publication_date is not None
    assert papers[0].publication_date.year == 2023
    assert papers[0].publication_date.month == 6
    assert papers[0].publication_date.day == 15


def test_parse_response_missing_publication_date(provider):
    """Test _parse_response handles missing publicationDate"""
    response = {"data": [{"paperId": "123", "title": "Test Paper"}]}

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].publication_date is None


def test_parse_response_paper_parsing_exception(provider):
    """Test _parse_response skips papers that fail to parse"""
    response = {
        "data": [
            {
                # Missing required 'paperId' field - will cause KeyError
                "title": "Broken Paper"
            },
            {"paperId": "456", "title": "Valid Paper"},
        ]
    }

    with patch("src.services.providers.semantic_scholar.logger") as mock_logger:
        papers = provider._parse_response(response)

        # Should skip first paper and parse second
        assert len(papers) == 1
        assert papers[0].paper_id == "456"

        # Should log warning for failed paper
        mock_logger.warning.assert_called_once()


def test_parse_response_missing_title_uses_default(provider):
    """Test _parse_response uses 'Unknown Title' for missing title"""
    response = {"data": [{"paperId": "123", "title": None}]}

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert papers[0].title == "Unknown Title"


def test_parse_response_missing_url_uses_default(provider):
    """Test _parse_response generates default URL when missing"""
    response = {"data": [{"paperId": "abc123", "title": "Test Paper", "url": None}]}

    papers = provider._parse_response(response)
    assert len(papers) == 1
    assert str(papers[0].url) == "https://semanticscholar.org/paper/abc123"


def test_parse_response_complete_paper(provider):
    """Test _parse_response with all fields present"""
    response = {
        "data": [
            {
                "paperId": "123",
                "title": "Complete Paper",
                "abstract": "This is the abstract",
                "url": "https://example.com/paper",
                "year": 2023,
                "publicationDate": "2023-06-15",
                "authors": [
                    {"name": "Author 1", "authorId": "a1"},
                    {"name": "Author 2", "authorId": "a2"},
                ],
                "citationCount": 42,
                "influentialCitationCount": 5,
                "venue": "ICML 2023",
                "openAccessPdf": {"url": "https://example.com/paper.pdf"},
            }
        ]
    }

    papers = provider._parse_response(response)
    assert len(papers) == 1

    paper = papers[0]
    assert paper.paper_id == "123"
    assert paper.title == "Complete Paper"
    assert paper.abstract == "This is the abstract"
    assert str(paper.url) == "https://example.com/paper"
    assert paper.year == 2023
    assert paper.publication_date.year == 2023
    assert len(paper.authors) == 2
    assert paper.citation_count == 42
    assert paper.influential_citation_count == 5
    assert paper.venue == "ICML 2023"
    assert str(paper.open_access_pdf) == "https://example.com/paper.pdf"
