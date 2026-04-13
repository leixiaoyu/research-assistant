"""Tests for legacy discovery method routing to unified discover() API.

This test suite verifies that the deprecated methods (search, enhanced_search,
multi_source_search) correctly route to the new discover() method with appropriate
modes and emit deprecation warnings.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from src.services.discovery.service import DiscoveryService
from src.models.config import ResearchTopic, ProviderType, TimeframeRecent
from src.models.discovery import (
    DiscoveryResult,
    DiscoveryMetrics,
    ScoredPaper,
    DiscoveryMode,
)
from src.models.paper import PaperMetadata


@pytest.fixture
def mock_providers():
    """Mock provider dictionary."""
    return {
        ProviderType.ARXIV: AsyncMock(),
        ProviderType.SEMANTIC_SCHOLAR: AsyncMock(),
    }


@pytest.fixture
def discovery_service(mock_providers):
    """Create DiscoveryService with mocked providers."""
    service = DiscoveryService(api_key="test_key")
    service.providers = mock_providers
    return service


@pytest.fixture
def sample_topic():
    """Sample research topic."""
    return ResearchTopic(
        query="machine learning optimization",
        timeframe=TimeframeRecent(value="7d"),
    )


@pytest.fixture
def sample_scored_paper():
    """Sample ScoredPaper for testing conversion."""
    return ScoredPaper(
        paper_id="test123",
        title="Test Paper",
        abstract="Test abstract",
        doi="10.1234/test",
        url="https://example.com/paper",
        authors=["John Doe", "Jane Smith"],
        publication_date="2025-01-15T00:00:00",
        venue="Test Conference",
        citation_count=42,
        quality_score=0.85,
        relevance_score=0.90,
    )


@pytest.fixture
def sample_discovery_result(sample_scored_paper):
    """Sample DiscoveryResult for testing."""
    return DiscoveryResult(
        papers=[sample_scored_paper],
        metrics=DiscoveryMetrics(
            papers_retrieved=1,
            papers_after_dedup=1,
            papers_after_quality_filter=1,
            avg_quality_score=0.85,
            pipeline_duration_ms=1000,
            duration_ms=1000,
        ),
        mode=DiscoveryMode.SURFACE,
    )


class TestScoredToMetadataConversion:
    """Test conversion from ScoredPaper to PaperMetadata."""

    def test_scored_to_metadata_full_data(self, discovery_service, sample_scored_paper):
        """Test conversion with complete data."""
        result = discovery_service._scored_to_metadata(sample_scored_paper)

        assert isinstance(result, PaperMetadata)
        assert result.paper_id == "test123"
        assert result.title == "Test Paper"
        assert result.abstract == "Test abstract"
        assert result.doi == "10.1234/test"
        assert "example.com/paper" in str(result.url)
        assert len(result.authors) == 2
        assert result.authors[0].name == "John Doe"
        assert result.authors[1].name == "Jane Smith"
        assert result.venue == "Test Conference"
        assert result.citation_count == 42
        # Quality score converted from 0-1 to 0-100 scale
        assert result.quality_score == 85.0

    def test_scored_to_metadata_publication_date_conversion(
        self, discovery_service, sample_scored_paper
    ):
        """Test publication date string to datetime conversion."""
        result = discovery_service._scored_to_metadata(sample_scored_paper)

        assert result.publication_date is not None
        assert isinstance(result.publication_date, datetime)
        assert result.publication_date.year == 2025
        assert result.publication_date.month == 1
        assert result.publication_date.day == 15

    def test_scored_to_metadata_missing_url(self, discovery_service):
        """Test conversion with missing URL (uses placeholder)."""
        scored = ScoredPaper(
            paper_id="test456",
            title="Test Paper",
            url=None,  # Missing URL
            quality_score=0.75,
        )

        result = discovery_service._scored_to_metadata(scored)

        assert isinstance(result, PaperMetadata)
        assert str(result.url) == "https://example.com/paper"

    def test_scored_to_metadata_invalid_date(self, discovery_service):
        """Test conversion with invalid publication date."""
        scored = ScoredPaper(
            paper_id="test789",
            title="Test Paper",
            url="https://example.com/paper",
            publication_date="invalid-date",
            quality_score=0.80,
        )

        result = discovery_service._scored_to_metadata(scored)

        assert isinstance(result, PaperMetadata)
        assert result.publication_date is None  # Failed to parse

    def test_scored_to_metadata_empty_authors(self, discovery_service):
        """Test conversion with empty authors list."""
        scored = ScoredPaper(
            paper_id="test999",
            title="Test Paper",
            url="https://example.com/paper",
            authors=[],
            quality_score=0.70,
        )

        result = discovery_service._scored_to_metadata(scored)

        assert isinstance(result, PaperMetadata)
        assert len(result.authors) == 0


class TestSearchMethodDeprecation:
    """Test search() method routes to discover(SURFACE)."""

    @pytest.mark.asyncio
    async def test_search_routes_to_discover_surface(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify search() calls discover(SURFACE) mode."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            result = await discovery_service.search(sample_topic)

            # Verify discover was called with SURFACE mode
            mock_discover.assert_called_once()
            call_args = mock_discover.call_args
            assert call_args[1]["mode"] == DiscoveryMode.SURFACE
            assert call_args[1]["topic"] == sample_topic.query

            # Verify result is converted to PaperMetadata list
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], PaperMetadata)

    @pytest.mark.asyncio
    async def test_search_emits_deprecation_warning(
        self, discovery_service, sample_topic, sample_discovery_result, capsys
    ):
        """Verify search() emits deprecation warning."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.search(sample_topic)

            # Verify deprecation warning was logged (structlog outputs to stdout)
            captured = capsys.readouterr()
            assert "search_method_deprecated" in captured.out

    @pytest.mark.asyncio
    async def test_search_returns_paper_metadata_list(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify search() returns List[PaperMetadata]."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            result = await discovery_service.search(sample_topic)

            assert isinstance(result, list)
            for paper in result:
                assert isinstance(paper, PaperMetadata)

    @pytest.mark.asyncio
    async def test_search_with_max_papers(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify search() passes max_papers to config."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.search(sample_topic, max_papers=100)

            call_args = mock_discover.call_args
            assert call_args[1]["config"].max_papers == 100

    @pytest.mark.asyncio
    async def test_search_with_providers(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify search() passes provider list to config."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.search(
                sample_topic, providers=[ProviderType.ARXIV, ProviderType.OPENALEX]
            )

            call_args = mock_discover.call_args
            assert "arxiv" in call_args[1]["config"].providers
            assert "openalex" in call_args[1]["config"].providers


class TestEnhancedSearchDeprecation:
    """Test enhanced_search() method routes to discover(STANDARD)."""

    @pytest.mark.asyncio
    async def test_enhanced_search_routes_to_discover_standard(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify enhanced_search() calls discover(STANDARD) mode."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.enhanced_search(sample_topic)

            # Verify discover was called with STANDARD mode
            mock_discover.assert_called_once()
            call_args = mock_discover.call_args
            assert call_args[1]["mode"] == DiscoveryMode.STANDARD
            assert call_args[1]["topic"] == sample_topic.query

    @pytest.mark.asyncio
    async def test_enhanced_search_emits_deprecation_warning(
        self, discovery_service, sample_topic, sample_discovery_result, capsys
    ):
        """Verify enhanced_search() emits deprecation warning."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.enhanced_search(sample_topic)

            # Verify deprecation warning was logged (structlog outputs to stdout)
            captured = capsys.readouterr()
            assert "enhanced_search_deprecated" in captured.out

    @pytest.mark.asyncio
    async def test_enhanced_search_returns_discovery_result(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify enhanced_search() returns DiscoveryResult."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            result = await discovery_service.enhanced_search(sample_topic)

            assert isinstance(result, DiscoveryResult)

    @pytest.mark.asyncio
    async def test_enhanced_search_with_llm_service(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify enhanced_search() passes llm_service to discover."""
        mock_llm = MagicMock()
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.enhanced_search(sample_topic, llm_service=mock_llm)

            call_args = mock_discover.call_args
            assert call_args[1]["llm_service"] == mock_llm


class TestMultiSourceSearchDeprecation:
    """Test multi_source_search() method routes to discover(DEEP)."""

    @pytest.mark.asyncio
    async def test_multi_source_search_routes_to_discover_deep(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify multi_source_search() calls discover(DEEP) mode."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.multi_source_search(sample_topic)

            # Verify discover was called with DEEP mode
            mock_discover.assert_called_once()
            call_args = mock_discover.call_args
            assert call_args[1]["mode"] == DiscoveryMode.DEEP
            assert call_args[1]["topic"] == sample_topic.query

    @pytest.mark.asyncio
    async def test_multi_source_search_emits_deprecation_warning(
        self, discovery_service, sample_topic, sample_discovery_result, capsys
    ):
        """Verify multi_source_search() emits deprecation warning."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.multi_source_search(sample_topic)

            # Verify deprecation warning was logged (structlog outputs to stdout)
            captured = capsys.readouterr()
            assert "multi_source_search_deprecated" in captured.out

    @pytest.mark.asyncio
    async def test_multi_source_search_returns_paper_metadata_list(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify multi_source_search() returns List[PaperMetadata]."""
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            result = await discovery_service.multi_source_search(sample_topic)

            assert isinstance(result, list)
            for paper in result:
                assert isinstance(paper, PaperMetadata)

    @pytest.mark.asyncio
    async def test_multi_source_search_with_llm_service(
        self, discovery_service, sample_topic, sample_discovery_result
    ):
        """Verify multi_source_search() passes llm_service to discover."""
        mock_llm = MagicMock()
        with patch.object(
            discovery_service, "discover", new_callable=AsyncMock
        ) as mock_discover:
            mock_discover.return_value = sample_discovery_result

            await discovery_service.multi_source_search(
                sample_topic, llm_service=mock_llm
            )

            call_args = mock_discover.call_args
            assert call_args[1]["llm_service"] == mock_llm
