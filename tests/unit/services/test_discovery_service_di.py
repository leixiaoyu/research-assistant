"""Tests for DiscoveryService dependency injection pattern (Phase P0-A1).

Tests the enhanced_discovery_service injection and the relationship
between DiscoveryService and EnhancedDiscoveryService.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.discovery_service import DiscoveryService
from src.models.config import ResearchTopic, TimeframeRecent
from src.models.discovery import DiscoveryResult, DiscoveryMetrics, ScoredPaper


@pytest.fixture
def mock_enhanced_service():
    """Create a mock EnhancedDiscoveryService."""
    service = AsyncMock()
    service.discover = AsyncMock(
        return_value=DiscoveryResult(
            papers=[
                ScoredPaper(
                    paper_id="test-1",
                    title="Test Paper",
                    url="https://example.com/paper",
                    abstract="Test abstract",
                    quality_score=0.8,
                    relevance_score=0.9,
                )
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=10,
                papers_after_quality_filter=5,
                papers_after_relevance_filter=1,
                avg_quality_score=0.8,
                avg_relevance_score=0.9,
            ),
            queries_used=[],
        )
    )
    return service


@pytest.fixture
def sample_topic():
    """Create a sample research topic."""
    return ResearchTopic(
        query="machine learning",
        timeframe=TimeframeRecent(value="48h"),
    )


class TestDiscoveryServiceDependencyInjection:
    """Tests for DiscoveryService dependency injection."""

    def test_init_without_enhanced_service(self):
        """Test initialization without injected enhanced service."""
        service = DiscoveryService()

        assert service.enhanced_service is None
        assert service._enhanced_service is None

    def test_init_with_enhanced_service(self, mock_enhanced_service):
        """Test initialization with injected enhanced service."""
        service = DiscoveryService(enhanced_discovery_service=mock_enhanced_service)

        assert service.enhanced_service is mock_enhanced_service
        assert service._enhanced_service is mock_enhanced_service

    def test_enhanced_service_property_getter(self, mock_enhanced_service):
        """Test enhanced_service property getter."""
        service = DiscoveryService(enhanced_discovery_service=mock_enhanced_service)

        assert service.enhanced_service is mock_enhanced_service

    def test_enhanced_service_property_setter(self, mock_enhanced_service):
        """Test enhanced_service property setter."""
        service = DiscoveryService()
        assert service.enhanced_service is None

        service.enhanced_service = mock_enhanced_service
        assert service.enhanced_service is mock_enhanced_service

        # Can set to None to revert
        service.enhanced_service = None
        assert service.enhanced_service is None

    @pytest.mark.asyncio
    async def test_enhanced_search_uses_injected_service(
        self, mock_enhanced_service, sample_topic
    ):
        """Test that enhanced_search uses injected service when available."""
        service = DiscoveryService(enhanced_discovery_service=mock_enhanced_service)

        result = await service.enhanced_search(sample_topic)

        # Verify injected service was used
        mock_enhanced_service.discover.assert_called_once_with(sample_topic)
        assert result.paper_count == 1
        assert result.metrics.avg_quality_score == 0.8

    @pytest.mark.asyncio
    async def test_enhanced_search_uses_setter_injected_service(
        self, mock_enhanced_service, sample_topic
    ):
        """Test enhanced_search uses service set via property setter."""
        service = DiscoveryService()  # No injection at init
        assert service.enhanced_service is None

        service.enhanced_service = mock_enhanced_service  # Set via setter

        result = await service.enhanced_search(sample_topic)

        # Verify setter-injected service was used
        mock_enhanced_service.discover.assert_called_once_with(sample_topic)
        assert result.paper_count == 1

    @pytest.mark.asyncio
    async def test_enhanced_search_creates_service_when_not_injected(
        self, sample_topic
    ):
        """Test that enhanced_search creates service internally when not injected."""
        service = DiscoveryService()

        # Mock the internal service creation (local import in enhanced_search)
        with patch(
            "src.services.enhanced_discovery_service.EnhancedDiscoveryService"
        ) as MockEnhanced:
            mock_instance = AsyncMock()
            mock_instance.discover = AsyncMock(
                return_value=DiscoveryResult(
                    papers=[],
                    metrics=DiscoveryMetrics(
                        papers_retrieved=0,
                        papers_after_quality_filter=0,
                        papers_after_relevance_filter=0,
                        avg_quality_score=0.0,
                        avg_relevance_score=0.0,
                    ),
                    queries_used=[],
                )
            )
            MockEnhanced.return_value = mock_instance

            with patch("src.services.query_decomposer.QueryDecomposer"):
                with patch("src.services.quality_filter_service.QualityFilterService"):
                    with patch("src.services.relevance_ranker.RelevanceRanker"):
                        await service.enhanced_search(sample_topic)

            # Verify internal service was created
            MockEnhanced.assert_called_once()

    @pytest.mark.asyncio
    async def test_enhanced_search_ignores_params_when_service_injected(
        self, mock_enhanced_service, sample_topic
    ):
        """Test that llm_service and config params are ignored when injected."""
        service = DiscoveryService(enhanced_discovery_service=mock_enhanced_service)

        mock_llm = MagicMock()
        mock_config = MagicMock()

        # These should be ignored since service is injected
        await service.enhanced_search(
            sample_topic,
            llm_service=mock_llm,
            config=mock_config,
        )

        # Verify injected service was used, params ignored
        mock_enhanced_service.discover.assert_called_once_with(sample_topic)


class TestDiscoveryServiceDocumentation:
    """Tests to verify documentation and docstrings are accurate."""

    def test_class_docstring_mentions_composition(self):
        """Test that class docstring documents the composition pattern."""
        docstring = DiscoveryService.__doc__
        assert "EnhancedDiscoveryService" in docstring
        assert "composition" in docstring.lower() or "inject" in docstring.lower()

    def test_init_docstring_mentions_enhanced_param(self):
        """Test that __init__ docstring documents enhanced_discovery_service param."""
        docstring = DiscoveryService.__init__.__doc__
        assert "enhanced_discovery_service" in docstring
        assert "dependency injection" in docstring.lower()

    def test_enhanced_search_docstring_mentions_injection(self):
        """Test that enhanced_search docstring documents injection behavior."""
        docstring = DiscoveryService.enhanced_search.__doc__
        assert "inject" in docstring.lower() or "constructor" in docstring.lower()
