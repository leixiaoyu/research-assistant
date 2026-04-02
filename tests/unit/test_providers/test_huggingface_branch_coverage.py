"""Branch coverage tests for HuggingFaceProvider.

These tests target specific uncovered branches to reach 99% coverage:
- Session management edge cases
- TimeframeDateRange handling
- Author parsing edge cases
- Date parsing exceptions
- Exception handler branches
- Search term extraction edge cases
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, date, timedelta, timezone

from src.services.providers.huggingface import HuggingFaceProvider
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
    ProviderType,
)
from src.models.paper import PaperMetadata


@pytest.fixture
def provider():
    """Create a HuggingFaceProvider instance."""
    return HuggingFaceProvider()


class TestSessionManagementBranches:
    """Test session management edge cases for branch coverage."""

    @pytest.mark.asyncio
    async def test_close_when_session_closed(self, provider):
        """Test close() when session is already closed (line 124->exit)."""
        # Create and immediately close a session
        session = await provider._get_session()
        await session.close()

        # Now call close() - should handle gracefully
        await provider.close()
        assert provider._session.closed

    @pytest.mark.asyncio
    async def test_close_when_no_session(self, provider):
        """Test close() when no session exists."""
        # Don't create a session, just close
        await provider.close()
        # Should not raise an error


class TestBuildQueryParamsBranches:
    """Test _build_query_params branch coverage."""

    def test_build_params_with_date_range(self, provider):
        """Test date range branch in _build_query_params (line 220->224)."""
        topic = ResearchTopic(
            query="test query",
            provider=ProviderType.HUGGINGFACE,
            timeframe=TimeframeDateRange(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            ),
            max_papers=10,
        )

        params = provider._build_query_params(topic)

        # Should include date parameter for date range
        assert "date" in params
        assert params["date"] == "2026-01-01"
        assert params["limit"] == 100

    def test_build_params_with_since_year(self, provider):
        """Test since_year timeframe (no date param added)."""
        topic = ResearchTopic(
            query="test query",
            provider=ProviderType.HUGGINGFACE,
            timeframe=TimeframeSinceYear(value=2020),
            max_papers=10,
        )

        params = provider._build_query_params(topic)

        # Should NOT include date parameter for since_year
        assert "date" not in params
        assert params["limit"] == 100


class TestParseResponseBranches:
    """Test _parse_response branch coverage for edge cases."""

    def test_parse_response_author_with_empty_name(self, provider):
        """Test author parsing when name is empty string (line 260->258)."""
        response = [
            {
                "paper": {
                    "id": "12345",
                    "title": "Test Paper",
                    "summary": "Test abstract",
                    "authors": [
                        {"name": ""},  # Empty name - should skip
                        {"name": "Valid Author"},  # Valid name
                    ],
                    "publishedAt": "2026-01-01T00:00:00.000Z",
                }
            }
        ]

        papers = list(provider._parse_response(response))

        assert len(papers) == 1
        # Should only have 1 author (empty name skipped)
        assert len(papers[0].authors) == 1
        assert papers[0].authors[0].name == "Valid Author"

    def test_parse_response_invalid_date_format(self, provider):
        """Test date parsing exception handling (line 283->293)."""
        response = [
            {
                "paper": {
                    "id": "12345",
                    "title": "Test Paper",
                    "summary": "Test abstract",
                    "authors": [{"name": "Author"}],
                    # Invalid date format - will raise TypeError
                    "publishedAt": None,
                }
            }
        ]

        papers = list(provider._parse_response(response))

        assert len(papers) == 1
        # Date parsing failed, so pub_date and year should be None
        assert papers[0].publication_date is None
        assert papers[0].year is None

    def test_parse_response_exception_with_dict_item(self, provider):
        """Test exception handler when item is a dict (line 326->328)."""
        response = [
            {
                "paper": {
                    "id": "valid-id",
                    "title": "Test",
                    "summary": "test",
                    "authors": "not-a-list",  # Will cause exception
                }
            }
        ]

        # Should handle exception gracefully
        papers = list(provider._parse_response(response))
        # Exception was caught, item skipped
        assert len(papers) == 0

    def test_parse_response_exception_with_non_dict_paper(self, provider):
        """Test exception handler when paper is not dict."""
        response = [
            {
                "paper": None,  # Will cause exception when calling .get()
            }
        ]

        # Should handle exception gracefully
        papers = list(provider._parse_response(response))
        assert len(papers) == 0


class TestExtractSearchTermsBranches:
    """Test _extract_search_terms branch coverage."""

    def test_extract_search_terms_short_quoted_phrase(self, provider):
        """Test quoted phrase that's too short (line 388->386)."""
        # Quoted phrase with only 2 chars - should be skipped
        query = '"ab" machine learning'

        terms = provider._extract_search_terms(query)

        # Short quoted phrase should be excluded
        assert "ab" not in terms
        assert "machine" in terms
        assert "learning" in terms

    def test_extract_search_terms_empty_quoted_phrase(self, provider):
        """Test empty quoted phrase."""
        query = '"" machine learning'

        terms = provider._extract_search_terms(query)

        # Empty phrase should be excluded
        assert "" not in terms
        assert "machine" in terms

    def test_extract_search_terms_whitespace_quoted_phrase(self, provider):
        """Test quoted phrase with only whitespace."""
        query = '"   " machine learning'

        terms = provider._extract_search_terms(query)

        # Whitespace-only phrase should be excluded
        assert "machine" in terms
        assert len([t for t in terms if not t.strip()]) == 0


class TestFilterByTimeframeBranches:
    """Test _filter_by_timeframe branch coverage."""

    def test_filter_recent_timeframe_hours_format(self, provider):
        """Test recent timeframe with hours format."""
        now = datetime.now(timezone.utc)
        papers = [
            PaperMetadata(
                paper_id="1",
                title="Recent Paper",
                url="https://arxiv.org/abs/1",
                publication_date=now - timedelta(hours=12),
            ),
            PaperMetadata(
                paper_id="2",
                title="Old Paper",
                url="https://arxiv.org/abs/2",
                publication_date=now - timedelta(hours=72),
            ),
        ]

        timeframe = TimeframeRecent(value="24h")
        filtered = list(provider._filter_by_timeframe(iter(papers), timeframe))

        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"

    def test_filter_recent_timeframe_days_format(self, provider):
        """Test recent timeframe with days format."""
        now = datetime.now(timezone.utc)
        papers = [
            PaperMetadata(
                paper_id="1",
                title="Recent Paper",
                url="https://arxiv.org/abs/1",
                publication_date=now - timedelta(days=2),
            ),
        ]

        timeframe = TimeframeRecent(value="3d")
        filtered = list(provider._filter_by_timeframe(iter(papers), timeframe))

        assert len(filtered) == 1

    def test_filter_since_year_with_year_only(self, provider):
        """Test since_year filtering."""
        papers = [
            PaperMetadata(
                paper_id="1",
                title="New Paper",
                url="https://arxiv.org/abs/1",
                year=2025,
            ),
            PaperMetadata(
                paper_id="2",
                title="Old Paper",
                url="https://arxiv.org/abs/2",
                year=2019,
            ),
        ]

        timeframe = TimeframeSinceYear(value=2020)
        filtered = list(provider._filter_by_timeframe(iter(papers), timeframe))

        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"


class TestSearchIntegrationBranches:
    """Test search() method branch coverage."""

    @pytest.mark.asyncio
    async def test_search_with_date_range_timeframe(self, provider):
        """Test search with date range timeframe."""
        topic = ResearchTopic(
            query="machine learning",
            provider=ProviderType.HUGGINGFACE,
            timeframe=TimeframeDateRange(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
            ),
            max_papers=5,
        )

        # Mock API response
        now = datetime.now(timezone.utc)
        mock_response = [
            {
                "paper": {
                    "id": "2601.12345",
                    "title": "Machine Learning Paper",
                    "summary": "About ML techniques",
                    "authors": [{"name": "Author"}],
                    "publishedAt": (now - timedelta(days=1)).strftime(
                        "%Y-%m-%dT%H:%M:%S.000Z"
                    ),
                }
            }
        ]

        mock_resp_obj = AsyncMock()
        mock_resp_obj.status = 200
        mock_resp_obj.json = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_get_session") as mock_session:
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_resp_obj),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            papers = await provider.search(topic)

            # Should return filtered papers
            assert isinstance(papers, list)


class TestAuthorParsingEdgeCases:
    """Test author parsing edge cases."""

    def test_parse_author_without_user_data(self, provider):
        """Test author parsing when user data is None."""
        response = [
            {
                "paper": {
                    "id": "12345",
                    "title": "Test Paper",
                    "summary": "Test",
                    "authors": [
                        {
                            "name": "Author Name",
                            "user": None,  # No user data
                        }
                    ],
                    "publishedAt": "2026-01-01T00:00:00.000Z",
                }
            }
        ]

        papers = list(provider._parse_response(response))

        assert len(papers) == 1
        assert len(papers[0].authors) == 1
        assert papers[0].authors[0].name == "Author Name"
        assert papers[0].authors[0].author_id is None

    def test_parse_author_with_organization_only_name(self, provider):
        """Test organization parsing when fullname is missing."""
        response = [
            {
                "paper": {
                    "id": "12345",
                    "title": "Test Paper",
                    "summary": "Test",
                    "authors": [{"name": "Author"}],
                    "organization": {
                        "name": "OrgName",
                        # No fullname
                    },
                    "publishedAt": "2026-01-01T00:00:00.000Z",
                }
            }
        ]

        papers = list(provider._parse_response(response))

        assert len(papers) == 1
        # Organization name should be used as affiliation
        assert papers[0].authors[0].affiliation == "OrgName"

    def test_parse_author_without_organization(self, provider):
        """Test author parsing when organization is missing."""
        response = [
            {
                "paper": {
                    "id": "12345",
                    "title": "Test Paper",
                    "summary": "Test",
                    "authors": [{"name": "Author"}],
                    # No organization field
                    "publishedAt": "2026-01-01T00:00:00.000Z",
                }
            }
        ]

        papers = list(provider._parse_response(response))

        assert len(papers) == 1
        assert papers[0].authors[0].affiliation is None
