"""Comprehensive tests for HuggingFaceProvider."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, date, timedelta
import aiohttp

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


@pytest.fixture
def topic_hf():
    """Create a basic research topic for HuggingFace."""
    return ResearchTopic(
        query="large language model",
        provider=ProviderType.HUGGINGFACE,
        timeframe=TimeframeRecent(value="48h"),
        max_papers=10,
    )


@pytest.fixture
def mock_hf_response():
    """Create a mock HuggingFace API response with recent dates."""
    # Use recent timestamps to pass timeframe filtering
    now = datetime.utcnow()
    recent_time_1 = (now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    recent_time_2 = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    return [
        {
            "paper": {
                "id": "2602.12345",
                "title": "Advances in Large Language Models",
                "summary": "This paper explores advances in LLM architectures.",
                "authors": [
                    {"name": "John Doe", "hidden": False},
                    {"name": "Jane Smith", "hidden": False, "user": {"user": "jsmith"}},
                ],
                "publishedAt": recent_time_1,
                "upvotes": 42,
                "discussionId": "abc123",
                "organization": {"name": "OpenAI", "fullname": "OpenAI Research"},
            },
            "publishedAt": recent_time_1,
            "title": "Advances in Large Language Models",
            "summary": "This paper explores advances in LLM architectures.",
            "numComments": 5,
            "isAuthorParticipating": True,
        },
        {
            "paper": {
                "id": "2602.67890",
                "title": "Transformer Optimization Techniques",
                "summary": "Novel optimization methods for transformer models.",
                "authors": [{"name": "Alice Johnson", "hidden": False}],
                "publishedAt": recent_time_2,
                "upvotes": 28,
                "discussionId": "def456",
            },
            "publishedAt": recent_time_2,
            "title": "Transformer Optimization Techniques",
            "summary": "Novel optimization methods for transformer models.",
            "numComments": 3,
            "isAuthorParticipating": False,
        },
    ]


class TestHuggingFaceProviderProperties:
    """Test provider properties."""

    def test_name(self, provider):
        """Test provider name."""
        assert provider.name == "huggingface"

    def test_requires_api_key(self, provider):
        """Test that no API key is required."""
        assert provider.requires_api_key is False

    def test_base_url(self, provider):
        """Test base URL constant."""
        assert provider.BASE_URL == "https://huggingface.co/api/daily_papers"

    def test_arxiv_pdf_base(self, provider):
        """Test ArXiv PDF base URL."""
        assert provider.ARXIV_PDF_BASE == "https://arxiv.org/pdf"


class TestValidateQuery:
    """Test query validation."""

    def test_valid_query(self, provider):
        """Test valid query passes validation."""
        assert provider.validate_query("machine learning") == "machine learning"
        assert provider.validate_query("AI AND NLP") == "AI AND NLP"
        assert provider.validate_query("GPT-4 models") == "GPT-4 models"

    def test_query_with_operators(self, provider):
        """Test query with boolean operators."""
        result = provider.validate_query("transformer OR attention")
        assert result == "transformer OR attention"

    def test_invalid_query_special_chars(self, provider):
        """Test invalid query with special characters (injection attempt)."""
        # Centralized InputValidation detects command injection patterns
        with pytest.raises(ValueError, match="forbidden pattern.*injection"):
            provider.validate_query("test; rm -rf /")

    def test_invalid_query_shell_injection(self, provider):
        """Test query rejects shell injection attempts."""
        # Centralized InputValidation rejects $ as outside allowed charset
        with pytest.raises(ValueError, match="characters outside allowed"):
            provider.validate_query("$HOME")

    def test_invalid_query_too_short(self, provider):
        """Test query too short."""
        with pytest.raises(ValueError, match="too short"):
            provider.validate_query("a")

    def test_invalid_query_too_long(self, provider):
        """Test query too long."""
        with pytest.raises(ValueError, match="too long"):
            provider.validate_query("a" * 501)

    def test_query_whitespace_stripped(self, provider):
        """Test query whitespace is stripped."""
        result = provider.validate_query("  machine learning  ")
        assert result == "machine learning"


class TestBuildQueryParams:
    """Test query parameter building."""

    def test_params_recent_timeframe(self, provider, topic_hf):
        """Test params for recent timeframe."""
        params = provider._build_query_params(topic_hf)
        assert params["limit"] == 100

    def test_params_date_range_timeframe(self, provider):
        """Test params for date range timeframe."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.HUGGINGFACE,
            timeframe=TimeframeDateRange(
                start_date=date(2026, 2, 15),
                end_date=date(2026, 2, 20),
            ),
            max_papers=10,
        )
        params = provider._build_query_params(topic)
        assert params["limit"] == 100
        assert params["date"] == "2026-02-15"

    def test_params_max_limit(self, provider, topic_hf):
        """Test params always use max limit of 100."""
        topic_hf.max_papers = 5  # User wants 5
        params = provider._build_query_params(topic_hf)
        assert params["limit"] == 100  # API fetches 100, filters later


class TestParseResponse:
    """Test response parsing."""

    def test_parse_valid_response(self, provider, mock_hf_response):
        """Test parsing valid API response."""
        papers = provider._parse_response(mock_hf_response)
        assert len(papers) == 2

        # First paper
        assert papers[0].paper_id == "2602.12345"
        assert papers[0].arxiv_id == "2602.12345"
        assert papers[0].title == "Advances in Large Language Models"
        assert "advances in LLM architectures" in papers[0].abstract
        assert len(papers[0].authors) == 2
        assert papers[0].authors[0].name == "John Doe"
        assert papers[0].citation_count == 42  # upvotes
        assert papers[0].pdf_available is True
        assert papers[0].pdf_source == "arxiv"
        assert str(papers[0].url) == "https://arxiv.org/abs/2602.12345"
        assert str(papers[0].open_access_pdf) == "https://arxiv.org/pdf/2602.12345.pdf"

    def test_parse_response_with_organization(self, provider, mock_hf_response):
        """Test parsing response with organization info."""
        papers = provider._parse_response(mock_hf_response)
        # First paper has organization
        assert papers[0].authors[0].affiliation == "OpenAI Research"

    def test_parse_response_missing_id(self, provider):
        """Test parsing response with missing paper ID."""
        response = [{"paper": {"title": "No ID Paper"}}]
        papers = provider._parse_response(response)
        assert len(papers) == 0  # Should skip paper without ID

    def test_parse_response_missing_title(self, provider):
        """Test parsing response with missing title."""
        response = [{"paper": {"id": "12345"}}]
        papers = provider._parse_response(response)
        assert len(papers) == 0  # Should skip paper without title

    def test_parse_response_empty_list(self, provider):
        """Test parsing empty response."""
        papers = provider._parse_response([])
        assert len(papers) == 0

    def test_parse_response_malformed_date(self, provider):
        """Test parsing response with malformed date."""
        response = [
            {
                "paper": {
                    "id": "12345",
                    "title": "Test Paper",
                    "publishedAt": "invalid-date",
                }
            }
        ]
        papers = provider._parse_response(response)
        assert len(papers) == 1
        assert papers[0].publication_date is None
        assert papers[0].year is None

    def test_parse_response_exception_handling(self, provider):
        """Test parsing handles exceptions gracefully."""
        # Create malformed response that will cause exception
        response = [
            {
                "paper": {
                    "id": "12345",
                    "title": "Valid Paper",
                    "summary": "Test",
                    "authors": [],
                    "publishedAt": "2026-02-20T10:00:00.000Z",
                }
            },
            None,  # Will cause exception
        ]
        papers = provider._parse_response(response)
        # Should parse the valid paper and skip the invalid one
        assert len(papers) == 1


class TestFilterByQuery:
    """Test keyword filtering."""

    def test_filter_matches_title(self, provider, mock_hf_response):
        """Test filter matches keywords in title."""
        papers = provider._parse_response(mock_hf_response)
        # "language" is only in the first paper
        filtered = provider._filter_by_query(papers, "language")
        assert len(filtered) == 1
        assert "Language Models" in filtered[0].title

    def test_filter_matches_abstract(self, provider, mock_hf_response):
        """Test filter matches keywords in abstract."""
        papers = provider._parse_response(mock_hf_response)
        filtered = provider._filter_by_query(papers, "optimization methods")
        assert len(filtered) == 1
        assert "Optimization" in filtered[0].title

    def test_filter_case_insensitive(self, provider, mock_hf_response):
        """Test filter is case insensitive."""
        papers = provider._parse_response(mock_hf_response)
        filtered = provider._filter_by_query(papers, "TRANSFORMER")
        assert len(filtered) == 1

    def test_filter_removes_operators(self, provider, mock_hf_response):
        """Test filter removes AND/OR/NOT operators."""
        papers = provider._parse_response(mock_hf_response)
        # After removing operators, "language" is the keyword - only in first paper
        filtered = provider._filter_by_query(papers, "language AND advances")
        assert len(filtered) == 1

    def test_filter_no_keywords(self, provider, mock_hf_response):
        """Test filter with no valid keywords returns all."""
        papers = provider._parse_response(mock_hf_response)
        filtered = provider._filter_by_query(papers, "a b")  # Too short keywords
        assert len(filtered) == 2  # Returns all when no keywords

    def test_filter_no_matches(self, provider, mock_hf_response):
        """Test filter with no matches returns empty."""
        papers = provider._parse_response(mock_hf_response)
        filtered = provider._filter_by_query(papers, "quantum computing blockchain")
        assert len(filtered) == 0


class TestFilterByTimeframe:
    """Test timeframe filtering."""

    def test_filter_recent_hours(self, provider):
        """Test filtering by recent hours."""
        now = datetime.utcnow()
        papers = [
            PaperMetadata(
                paper_id="1",
                title="Recent Paper",
                url="https://arxiv.org/abs/1",
                publication_date=now - timedelta(hours=24),
            ),
            PaperMetadata(
                paper_id="2",
                title="Old Paper",
                url="https://arxiv.org/abs/2",
                publication_date=now - timedelta(hours=72),
            ),
        ]
        timeframe = TimeframeRecent(value="48h")
        filtered = provider._filter_by_timeframe(papers, timeframe)
        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"

    def test_filter_recent_days(self, provider):
        """Test filtering by recent days."""
        now = datetime.utcnow()
        papers = [
            PaperMetadata(
                paper_id="1",
                title="Recent Paper",
                url="https://arxiv.org/abs/1",
                publication_date=now - timedelta(days=3),
            ),
            PaperMetadata(
                paper_id="2",
                title="Old Paper",
                url="https://arxiv.org/abs/2",
                publication_date=now - timedelta(days=10),
            ),
        ]
        timeframe = TimeframeRecent(value="7d")
        filtered = provider._filter_by_timeframe(papers, timeframe)
        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"

    def test_filter_since_year(self, provider):
        """Test filtering by since year."""
        papers = [
            PaperMetadata(
                paper_id="1",
                title="New Paper",
                url="https://arxiv.org/abs/1",
                year=2026,
            ),
            PaperMetadata(
                paper_id="2",
                title="Old Paper",
                url="https://arxiv.org/abs/2",
                year=2020,
            ),
        ]
        timeframe = TimeframeSinceYear(value=2025)
        filtered = provider._filter_by_timeframe(papers, timeframe)
        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"

    def test_filter_date_range(self, provider):
        """Test filtering by date range."""
        papers = [
            PaperMetadata(
                paper_id="1",
                title="In Range Paper",
                url="https://arxiv.org/abs/1",
                publication_date=datetime(2026, 2, 15, 12, 0, 0),
            ),
            PaperMetadata(
                paper_id="2",
                title="Out of Range Paper",
                url="https://arxiv.org/abs/2",
                publication_date=datetime(2026, 1, 1, 12, 0, 0),
            ),
        ]
        timeframe = TimeframeDateRange(
            start_date=date(2026, 2, 10),
            end_date=date(2026, 2, 20),
        )
        filtered = provider._filter_by_timeframe(papers, timeframe)
        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"

    def test_filter_empty_list(self, provider):
        """Test filtering empty list."""
        timeframe = TimeframeRecent(value="48h")
        filtered = provider._filter_by_timeframe([], timeframe)
        assert len(filtered) == 0

    def test_filter_no_publication_date(self, provider):
        """Test filtering papers without publication date."""
        papers = [
            PaperMetadata(
                paper_id="1",
                title="No Date Paper",
                url="https://arxiv.org/abs/1",
                publication_date=None,
            ),
        ]
        timeframe = TimeframeRecent(value="48h")
        filtered = provider._filter_by_timeframe(papers, timeframe)
        assert len(filtered) == 0  # Papers without date are excluded


class TestSearch:
    """Test search functionality."""

    @pytest.mark.asyncio
    async def test_search_success(self, provider, topic_hf, mock_hf_response):
        """Test successful search."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_hf_response)

        with patch.object(provider, "_get_session") as mock_session:
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_response),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            papers = await provider.search(topic_hf)
            assert len(papers) > 0

    @pytest.mark.asyncio
    async def test_search_rate_limit_error(self, provider, topic_hf):
        """Test search handles 429 rate limit error."""
        mock_response = AsyncMock()
        mock_response.status = 429

        with patch.object(provider, "_get_session") as mock_session:
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_response),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            from tenacity import RetryError

            with pytest.raises(RetryError):
                await provider.search(topic_hf)

    @pytest.mark.asyncio
    async def test_search_forbidden_error(self, provider, topic_hf):
        """Test search handles 403 forbidden error."""
        mock_response = AsyncMock()
        mock_response.status = 403

        with patch.object(provider, "_get_session") as mock_session:
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_response),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            from tenacity import RetryError

            with pytest.raises(RetryError):
                await provider.search(topic_hf)

    @pytest.mark.asyncio
    async def test_search_api_error(self, provider, topic_hf):
        """Test search handles generic API error."""
        mock_response = AsyncMock()
        mock_response.status = 500

        with patch.object(provider, "_get_session") as mock_session:
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_response),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            from tenacity import RetryError

            with pytest.raises(RetryError):
                await provider.search(topic_hf)

    @pytest.mark.asyncio
    async def test_search_network_error(self, provider, topic_hf):
        """Test search handles network error."""
        with patch.object(provider, "_get_session") as mock_session:
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(
                        side_effect=aiohttp.ClientError("Network error")
                    ),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            from tenacity import RetryError

            with pytest.raises(RetryError):
                await provider.search(topic_hf)

    @pytest.mark.asyncio
    async def test_search_invalid_query(self, provider):
        """Test search with invalid query.

        Note: Pydantic validation at ResearchTopic level catches injection
        attempts before reaching the provider. This test verifies that
        invalid queries at the provider level (e.g., query too short)
        are handled gracefully.
        """
        # Create a topic with valid Pydantic query but invalid for provider
        topic = ResearchTopic(
            query="a",  # Too short - will fail provider validation
            provider=ProviderType.HUGGINGFACE,
            timeframe=TimeframeRecent(value="48h"),
            max_papers=10,
        )
        # Should return empty list for invalid query
        papers = await provider.search(topic)
        assert len(papers) == 0

    @pytest.mark.asyncio
    async def test_search_respects_max_papers(self, provider, topic_hf):
        """Test search respects max_papers limit."""
        # Create response with many papers
        mock_response_data = [
            {
                "paper": {
                    "id": f"2602.{i:05d}",
                    "title": f"Test Paper {i} about language models",
                    "summary": f"Abstract for paper {i}",
                    "authors": [{"name": "Author", "hidden": False}],
                    "publishedAt": "2026-02-20T10:00:00.000Z",
                    "upvotes": i,
                }
            }
            for i in range(20)
        ]

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_response_data)

        topic_hf.max_papers = 5

        with patch.object(provider, "_get_session") as mock_session:
            mock_session.return_value.get = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_response),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            papers = await provider.search(topic_hf)
            assert len(papers) <= 5


class TestSessionManagement:
    """Test HTTP session management."""

    @pytest.mark.asyncio
    async def test_get_session_creates_session(self, provider):
        """Test _get_session creates new session."""
        session = await provider._get_session()
        assert session is not None
        assert isinstance(session, aiohttp.ClientSession)
        await provider.close()

    @pytest.mark.asyncio
    async def test_get_session_reuses_session(self, provider):
        """Test _get_session reuses existing session."""
        session1 = await provider._get_session()
        session2 = await provider._get_session()
        assert session1 is session2
        await provider.close()

    @pytest.mark.asyncio
    async def test_close_closes_session(self, provider):
        """Test close() closes the session."""
        await provider._get_session()
        await provider.close()
        assert provider._session is None or provider._session.closed


class TestRateLimiter:
    """Test rate limiting."""

    def test_rate_limiter_default(self, provider):
        """Test default rate limiter configuration."""
        assert provider.rate_limiter is not None
        assert provider.rate_limiter.burst_size == 5

    def test_rate_limiter_custom(self):
        """Test custom rate limiter."""
        from src.utils.rate_limiter import RateLimiter

        custom_limiter = RateLimiter(requests_per_minute=60, burst_size=10)
        provider = HuggingFaceProvider(rate_limiter=custom_limiter)
        assert provider.rate_limiter.burst_size == 10


class TestIntegrationWithDiscoveryService:
    """Test integration with DiscoveryService."""

    def test_provider_type_enum(self):
        """Test HuggingFace is in ProviderType enum."""
        assert hasattr(ProviderType, "HUGGINGFACE")
        assert ProviderType.HUGGINGFACE.value == "huggingface"

    def test_provider_implements_interface(self, provider):
        """Test provider implements DiscoveryProvider interface."""
        from src.services.providers.base import DiscoveryProvider

        assert isinstance(provider, DiscoveryProvider)
        assert hasattr(provider, "search")
        assert hasattr(provider, "validate_query")
        assert hasattr(provider, "name")
        assert hasattr(provider, "requires_api_key")


class TestExtractSearchTerms:
    """Test search term extraction with quoted phrases."""

    def test_extract_simple_keywords(self, provider):
        """Test extraction of simple keywords."""
        terms = provider._extract_search_terms("machine learning")
        assert "machine" in terms
        assert "learning" in terms

    def test_extract_quoted_phrase(self, provider):
        """Test extraction preserves quoted phrases."""
        terms = provider._extract_search_terms('"machine learning" transformer')
        assert "machine learning" in terms
        assert "transformer" in terms

    def test_extract_multiple_quoted_phrases(self, provider):
        """Test extraction of multiple quoted phrases."""
        terms = provider._extract_search_terms('"large language" "neural network"')
        assert "large language" in terms
        assert "neural network" in terms

    def test_extract_removes_operators(self, provider):
        """Test extraction removes AND/OR/NOT operators."""
        terms = provider._extract_search_terms("machine AND learning OR NOT test")
        assert "machine" in terms
        assert "learning" in terms
        assert "test" in terms
        assert "AND" not in terms
        assert "OR" not in terms
        assert "NOT" not in terms

    def test_extract_filters_short_words(self, provider):
        """Test extraction filters words with 2 or fewer chars."""
        terms = provider._extract_search_terms("a to machine learning")
        assert "a" not in terms
        assert "to" not in terms
        assert "machine" in terms
        assert "learning" in terms

    def test_extract_empty_query(self, provider):
        """Test extraction of empty/operator-only query."""
        terms = provider._extract_search_terms("AND OR NOT")
        assert terms == []


class TestFilterByQueryAndSemantics:
    """Test AND semantics in query filtering."""

    def test_filter_requires_all_keywords(self, provider):
        """Test filter requires ALL keywords to match (AND semantics)."""
        papers = [
            PaperMetadata(
                paper_id="1",
                title="Machine Learning Paper",
                abstract="About neural networks",
                url="https://arxiv.org/abs/1",
            ),
            PaperMetadata(
                paper_id="2",
                title="Deep Learning Paper",
                abstract="About transformers",
                url="https://arxiv.org/abs/2",
            ),
        ]
        # Both "machine" AND "neural" must be present
        filtered = provider._filter_by_query(papers, "machine neural")
        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"

    def test_filter_quoted_phrase_matching(self, provider):
        """Test filter matches quoted phrases exactly."""
        papers = [
            PaperMetadata(
                paper_id="1",
                title="Large Language Models",
                abstract="About LLMs",
                url="https://arxiv.org/abs/1",
            ),
            PaperMetadata(
                paper_id="2",
                title="Large Vision Models",
                abstract="About language understanding",
                url="https://arxiv.org/abs/2",
            ),
        ]
        # "large language" as a phrase should only match paper 1
        filtered = provider._filter_by_query(papers, '"large language"')
        assert len(filtered) == 1
        assert filtered[0].paper_id == "1"


class TestValidatePdfUrl:
    """Test PDF URL validation."""

    def test_validate_valid_url(self, provider):
        """Test validation of valid ArXiv PDF URL."""
        url = "https://arxiv.org/pdf/2602.12345.pdf"
        result = provider._validate_pdf_url(url)
        assert result == url

    def test_validate_upgrades_http_to_https(self, provider):
        """Test HTTP is upgraded to HTTPS."""
        url = "http://arxiv.org/pdf/2602.12345.pdf"
        result = provider._validate_pdf_url(url)
        assert result.startswith("https://")

    def test_validate_url_without_pdf_extension(self, provider):
        """Test URL without .pdf extension is valid."""
        url = "https://arxiv.org/pdf/2602.12345"
        result = provider._validate_pdf_url(url)
        assert result == url

    def test_validate_rejects_invalid_domain(self, provider):
        """Test validation rejects non-ArXiv URLs."""
        from src.utils.security import SecurityError

        with pytest.raises(SecurityError, match="Invalid ArXiv PDF URL"):
            provider._validate_pdf_url("https://malicious.com/pdf/2602.12345.pdf")

    def test_validate_rejects_path_traversal(self, provider):
        """Test validation rejects path traversal attempts."""
        from src.utils.security import SecurityError

        with pytest.raises(SecurityError, match="Invalid ArXiv PDF URL"):
            provider._validate_pdf_url("https://arxiv.org/pdf/../../../etc/passwd")
