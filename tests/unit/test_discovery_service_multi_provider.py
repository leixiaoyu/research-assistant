"""Comprehensive tests for DiscoveryService multi-provider intelligence."""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from src.services.discovery_service import DiscoveryService
from src.services.providers.base import APIError
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    ProviderType,
    ProviderSelectionConfig,
)
from src.models.paper import PaperMetadata, Author
from src.models.provider import ProviderMetrics, ProviderComparison


@pytest.fixture
def mock_paper():
    """Create a mock paper for testing."""
    return PaperMetadata(
        paper_id="test123",
        title="Test Paper",
        abstract="Test abstract",
        authors=[Author(name="Author One")],
        url="https://example.com/paper",
        doi="10.1234/test",
    )


@pytest.fixture
def topic_basic():
    """Basic topic for testing."""
    return ResearchTopic(
        query="machine learning",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeRecent(value="48h"),
    )


class TestDiscoveryServiceInitialization:
    """Test DiscoveryService initialization."""

    def test_init_with_no_api_key(self):
        """Test initialization without API key."""
        ds = DiscoveryService()
        assert ProviderType.ARXIV in ds.available_providers
        assert ProviderType.SEMANTIC_SCHOLAR not in ds.available_providers

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        ds = DiscoveryService(api_key="test_key_1234567890")
        assert ProviderType.ARXIV in ds.available_providers
        assert ProviderType.SEMANTIC_SCHOLAR in ds.available_providers

    def test_init_with_custom_config(self):
        """Test initialization with custom config."""
        config = ProviderSelectionConfig(
            auto_select=False,
            fallback_enabled=False,
        )
        ds = DiscoveryService(config=config)
        assert ds.config.auto_select is False
        assert ds.config.fallback_enabled is False

    def test_available_providers_property(self):
        """Test available_providers property."""
        ds = DiscoveryService(api_key="test_key_1234567890")
        providers = ds.available_providers
        assert isinstance(providers, list)
        assert len(providers) == 2


class TestAutoSelection:
    """Test auto-selection of providers."""

    @pytest.mark.asyncio
    async def test_auto_select_arxiv_terms(self, topic_basic):
        """Test auto-selection with ArXiv terms."""
        topic = ResearchTopic(
            query="cs.ai paper",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )
        ds = DiscoveryService(api_key="test_key_1234567890")

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = []
            await ds.search(topic)
            mock_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_select_disabled(self, topic_basic):
        """Test explicit provider when auto-select disabled."""
        config = ProviderSelectionConfig(auto_select=False)
        ds = DiscoveryService(config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = []
            await ds.search(topic)
            mock_search.assert_called_once()


class TestFallbackBehavior:
    """Test fallback on provider failure."""

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        """Test fallback triggers when primary fails."""
        config = ProviderSelectionConfig(
            auto_select=False,
            fallback_enabled=True,
            fallback_timeout_seconds=30.0,
        )
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        ss_path = "src.services.providers.semantic_scholar"
        with patch(
            f"{ss_path}.SemanticScholarProvider.search",
            new_callable=AsyncMock,
        ) as mock_ss:
            mock_ss.side_effect = Exception("API Error")

            with patch(
                "src.services.providers.arxiv.ArxivProvider.search",
                new_callable=AsyncMock,
            ) as mock_arxiv:
                mock_arxiv.return_value = []
                result = await ds.search(topic)
                mock_arxiv.assert_called_once()
                assert result == []

    @pytest.mark.asyncio
    async def test_fallback_disabled(self):
        """Test no fallback when disabled."""
        config = ProviderSelectionConfig(
            auto_select=False,
            fallback_enabled=False,
        )
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        ss_path = "src.services.providers.semantic_scholar"
        with patch(
            f"{ss_path}.SemanticScholarProvider.search",
            new_callable=AsyncMock,
        ) as mock_ss:
            mock_ss.return_value = []
            result = await ds.search(topic)
            assert result == []

    @pytest.mark.asyncio
    async def test_fallback_on_timeout(self):
        """Test fallback triggers on timeout."""
        config = ProviderSelectionConfig(
            auto_select=False,
            fallback_enabled=True,
            fallback_timeout_seconds=5.0,
        )
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        async def slow_search(*args):
            await asyncio.sleep(10)
            return []

        ss_path = "src.services.providers.semantic_scholar"
        with patch(
            f"{ss_path}.SemanticScholarProvider.search",
            new_callable=AsyncMock,
        ) as mock_ss:
            mock_ss.side_effect = slow_search

            with patch(
                "src.services.providers.arxiv.ArxivProvider.search",
                new_callable=AsyncMock,
            ) as mock_arxiv:
                mock_arxiv.return_value = []
                await ds.search(topic)
                mock_arxiv.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        """Test when all providers fail."""
        config = ProviderSelectionConfig(
            auto_select=False,
            fallback_enabled=True,
        )
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        ss_path = "src.services.providers.semantic_scholar"
        with patch(
            f"{ss_path}.SemanticScholarProvider.search",
            new_callable=AsyncMock,
        ) as mock_ss:
            mock_ss.side_effect = Exception("SS Error")

            with patch(
                "src.services.providers.arxiv.ArxivProvider.search",
                new_callable=AsyncMock,
            ) as mock_arxiv:
                mock_arxiv.side_effect = Exception("ArXiv Error")
                result = await ds.search(topic)
                assert result == []


class TestBenchmarkMode:
    """Test benchmark mode (query all providers)."""

    @pytest.mark.asyncio
    async def test_benchmark_mode_queries_all(self, mock_paper):
        """Test benchmark mode queries all providers."""
        config = ProviderSelectionConfig(benchmark_mode=True)
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [mock_paper]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                paper2 = PaperMetadata(
                    paper_id="test456",
                    title="Paper 2",
                    abstract="Abstract 2",
                    authors=[Author(name="Author Two")],
                    url="https://example.com/paper2",
                    doi="10.1234/test2",
                )
                mock_ss.return_value = [paper2]

                result = await ds.search(topic)
                assert len(result) == 2
                mock_arxiv.assert_called_once()
                mock_ss.assert_called_once()

    @pytest.mark.asyncio
    async def test_benchmark_mode_deduplicates(self, mock_paper):
        """Test benchmark mode deduplicates by DOI."""
        config = ProviderSelectionConfig(benchmark_mode=True)
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [mock_paper]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                mock_ss.return_value = [mock_paper]

                result = await ds.search(topic)
                assert len(result) == 1

    @pytest.mark.asyncio
    async def test_benchmark_topic_flag(self, mock_paper):
        """Test topic.benchmark flag enables benchmark mode."""
        ds = DiscoveryService(api_key="test_key_1234567890")

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            benchmark=True,
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [mock_paper]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                mock_ss.return_value = []

                await ds.search(topic)
                mock_arxiv.assert_called_once()
                mock_ss.assert_called_once()

    @pytest.mark.asyncio
    async def test_benchmark_handles_provider_error(self, mock_paper):
        """Test benchmark mode handles individual provider errors."""
        config = ProviderSelectionConfig(benchmark_mode=True)
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [mock_paper]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                mock_ss.side_effect = Exception("SS Error")

                result = await ds.search(topic)
                assert len(result) == 1


class TestSearchWithMetrics:
    """Test search_with_metrics method."""

    @pytest.mark.asyncio
    async def test_search_with_metrics_success(self, mock_paper):
        """Test search_with_metrics returns metrics."""
        config = ProviderSelectionConfig(auto_select=False)
        ds = DiscoveryService(config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_search:
            mock_search.return_value = [mock_paper]

            papers, metrics = await ds.search_with_metrics(topic)

            assert len(papers) == 1
            assert isinstance(metrics, ProviderMetrics)
            assert metrics.provider == ProviderType.ARXIV
            assert metrics.success is True
            assert metrics.result_count == 1
            assert metrics.query_time_ms >= 0

    @pytest.mark.asyncio
    async def test_search_with_metrics_failure(self):
        """Test search_with_metrics on failure."""
        config = ProviderSelectionConfig(auto_select=False, fallback_enabled=False)
        ds = DiscoveryService(api_key="", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        papers, metrics = await ds.search_with_metrics(topic)

        assert len(papers) == 0
        assert metrics.success is False
        assert metrics.error is not None


class TestCompareProviders:
    """Test compare_providers method."""

    @pytest.mark.asyncio
    async def test_compare_providers_basic(self, mock_paper):
        """Test compare_providers returns comparison."""
        ds = DiscoveryService(api_key="test_key_1234567890")

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [mock_paper]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                paper2 = PaperMetadata(
                    paper_id="test456",
                    title="Paper 2",
                    abstract="Abstract 2",
                    authors=[Author(name="Author Two")],
                    url="https://example.com/paper2",
                    doi="10.1234/test2",
                )
                mock_ss.return_value = [paper2]

                comparison = await ds.compare_providers(topic)

                assert isinstance(comparison, ProviderComparison)
                assert len(comparison.providers_queried) == 2
                assert len(comparison.metrics) == 2
                assert comparison.total_unique_papers == 2
                assert comparison.fastest_provider is not None
                assert comparison.most_results_provider is not None

    @pytest.mark.asyncio
    async def test_compare_providers_with_overlap(self, mock_paper):
        """Test compare_providers detects overlap."""
        ds = DiscoveryService(api_key="test_key_1234567890")

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [mock_paper]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                mock_ss.return_value = [mock_paper]

                comparison = await ds.compare_providers(topic)

                assert comparison.overlap_count == 1
                assert comparison.total_unique_papers == 1

    @pytest.mark.asyncio
    async def test_compare_providers_with_failure(self, mock_paper):
        """Test compare_providers handles individual failures."""
        ds = DiscoveryService(api_key="test_key_1234567890")

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [mock_paper]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                mock_ss.side_effect = Exception("SS Error")

                comparison = await ds.compare_providers(topic)

                assert len(comparison.metrics) == 2
                ss_metric = next(
                    m
                    for m in comparison.metrics
                    if m.provider == ProviderType.SEMANTIC_SCHOLAR
                )
                assert ss_metric.success is False
                assert ss_metric.error is not None


class TestProviderUnavailable:
    """Test provider unavailable scenarios."""

    @pytest.mark.asyncio
    async def test_semantic_scholar_without_api_key(self):
        """Test error when Semantic Scholar requested without API key."""
        config = ProviderSelectionConfig(auto_select=False)
        ds = DiscoveryService(api_key="", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        with pytest.raises(APIError, match="not available"):
            await ds.search(topic)

    @pytest.mark.asyncio
    async def test_unknown_provider(self):
        """Test error for unknown provider type."""
        config = ProviderSelectionConfig(auto_select=False)
        ds = DiscoveryService(config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )

        del ds.providers[ProviderType.ARXIV]

        with pytest.raises(ValueError, match="Unknown provider type"):
            await ds.search(topic)


class TestAdditionalCoverage:
    """Additional tests to improve coverage."""

    @pytest.mark.asyncio
    async def test_benchmark_paper_without_unique_id(self):
        """Test benchmark handles papers without DOI or paper_id."""
        config = ProviderSelectionConfig(benchmark_mode=True)
        ds = DiscoveryService(api_key="test_key_1234567890", config=config)

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )

        paper_no_id = PaperMetadata(
            paper_id="",
            title="Paper No ID",
            abstract="Abstract",
            authors=[Author(name="Author")],
            url="https://example.com/paper",
            doi=None,
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = [paper_no_id]

            ss_path = "src.services.providers.semantic_scholar"
            with patch(
                f"{ss_path}.SemanticScholarProvider.search",
                new_callable=AsyncMock,
            ) as mock_ss:
                mock_ss.return_value = []

                result = await ds.search(topic)
                assert len(result) == 1

    @pytest.mark.asyncio
    async def test_search_with_metrics_auto_select(self):
        """Test search_with_metrics uses auto-select."""
        ds = DiscoveryService()

        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )

        with patch(
            "src.services.providers.arxiv.ArxivProvider.search",
            new_callable=AsyncMock,
        ) as mock_arxiv:
            mock_arxiv.return_value = []

            papers, metrics = await ds.search_with_metrics(topic)

            assert metrics.provider == ProviderType.ARXIV


class TestModelIntegration:
    """Test integration with new Phase 3.2 models."""

    def test_provider_metrics_model(self):
        """Test ProviderMetrics model."""
        metrics = ProviderMetrics(
            provider=ProviderType.ARXIV,
            query_time_ms=100,
            result_count=10,
            success=True,
        )
        assert metrics.provider == ProviderType.ARXIV
        assert metrics.query_time_ms == 100
        assert metrics.result_count == 10
        assert metrics.success is True
        assert metrics.error is None

    def test_provider_comparison_model(self):
        """Test ProviderComparison model."""
        comparison = ProviderComparison(
            providers_queried=[ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
            metrics=[
                ProviderMetrics(
                    provider=ProviderType.ARXIV,
                    query_time_ms=100,
                    result_count=10,
                ),
                ProviderMetrics(
                    provider=ProviderType.SEMANTIC_SCHOLAR,
                    query_time_ms=200,
                    result_count=20,
                ),
            ],
            total_unique_papers=25,
            overlap_count=5,
            fastest_provider=ProviderType.ARXIV,
            most_results_provider=ProviderType.SEMANTIC_SCHOLAR,
        )
        assert len(comparison.providers_queried) == 2
        assert comparison.total_unique_papers == 25
        assert comparison.overlap_count == 5
