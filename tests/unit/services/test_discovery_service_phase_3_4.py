"""Tests for DiscoveryService Phase 3.4 features."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from src.services.discovery_service import DiscoveryService
from src.services.quality_scorer import QualityScorer
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    ProviderType,
    ProviderSelectionConfig,
    PDFStrategy,
)
from src.models.paper import PaperMetadata, Author


@pytest.fixture
def mock_arxiv_provider():
    """Mock ArxivProvider that returns papers."""
    provider = AsyncMock()
    provider.name = "arxiv"
    provider.search = AsyncMock(return_value=[])
    return provider


@pytest.fixture
def mock_semantic_scholar_provider():
    """Mock SemanticScholarProvider that returns papers."""
    provider = AsyncMock()
    provider.name = "semantic_scholar"
    provider.search = AsyncMock(return_value=[])
    return provider


@pytest.fixture
def sample_papers():
    """Create sample papers for testing."""
    return [
        PaperMetadata(
            paper_id="high_quality",
            title="High Quality Paper",
            url="https://example.com/paper1",
            citation_count=500,
            venue="NeurIPS",
            publication_date=datetime.now(timezone.utc),
            abstract="High quality abstract",
            authors=[Author(name="Test Author")],
            pdf_available=True,
            pdf_source="open_access",
        ),
        PaperMetadata(
            paper_id="medium_quality",
            title="Medium Quality Paper",
            url="https://example.com/paper2",
            citation_count=50,
            venue="Workshop",
            abstract="Medium quality abstract",
            pdf_available=False,
        ),
        PaperMetadata(
            paper_id="low_quality",
            title="Low Quality Paper",
            url="https://example.com/paper3",
            citation_count=0,
            venue="Unknown",
            pdf_available=False,
        ),
    ]


@pytest.fixture
def topic_quality_first():
    """Topic with QUALITY_FIRST strategy."""
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        pdf_strategy=PDFStrategy.QUALITY_FIRST,
        quality_ranking=True,
        min_quality_score=0.0,
    )


@pytest.fixture
def topic_arxiv_supplement():
    """Topic with ARXIV_SUPPLEMENT strategy."""
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
        quality_ranking=True,
        arxiv_supplement_threshold=0.5,
    )


@pytest.fixture
def topic_no_ranking():
    """Topic with quality ranking disabled."""
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        quality_ranking=False,
    )


class TestDiscoveryServicePhase34Init:
    """Tests for Phase 3.4 initialization."""

    def test_discovery_service_init_without_quality_scorer(self):
        """Test that DiscoveryService initializes without quality_scorer param.

        Note: QualityScorer is deprecated and replaced by QualityIntelligenceService.
        The service no longer stores _quality_scorer attribute.
        """
        with patch("src.services.discovery_service.ArxivProvider"):
            service = DiscoveryService()
            # Verify service initializes correctly without quality_scorer
            assert service is not None
            assert service.providers is not None

    def test_quality_scorer_deprecated_warning(self, capsys):
        """Test that passing quality_scorer emits deprecation warning.

        Note: quality_scorer parameter is deprecated. Use QualityIntelligenceService.
        """
        custom_scorer = QualityScorer(
            citation_weight=0.5,
            venue_weight=0.2,
            recency_weight=0.2,
            completeness_weight=0.1,
        )
        with patch("src.services.discovery_service.ArxivProvider"):
            service = DiscoveryService(quality_scorer=custom_scorer)
            # Service should still initialize
            assert service is not None
        # Verify deprecation warning was logged to stdout (structlog output)
        captured = capsys.readouterr()
        assert "quality_scorer_deprecated" in captured.out
        assert "deprecated" in captured.out.lower()


class TestDiscoveryServiceQualityRanking:
    """Tests for quality ranking integration."""

    @pytest.mark.asyncio
    async def test_quality_ranking_applied(self, sample_papers, topic_quality_first):
        """Test that papers are ranked by quality when enabled."""
        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(return_value=sample_papers.copy())
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService()
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance

            result = await service.search(topic_quality_first)

            # Should be ranked by quality (high first)
            assert len(result) == 3
            assert result[0].paper_id == "high_quality"
            # All papers should have quality_score populated
            for paper in result:
                assert paper.quality_score > 0 or paper.citation_count == 0

    @pytest.mark.asyncio
    async def test_quality_ranking_disabled(self, sample_papers, topic_no_ranking):
        """Test that papers are NOT ranked when ranking disabled."""
        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_arxiv_instance = AsyncMock()
            # Return papers in specific order
            papers_copy = sample_papers.copy()
            mock_arxiv_instance.search = AsyncMock(return_value=papers_copy)
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService()
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance

            result = await service.search(topic_no_ranking)

            # Should maintain original order
            assert len(result) == 3
            assert result[0].paper_id == "high_quality"  # Original order preserved

    @pytest.mark.asyncio
    async def test_min_quality_score_filter(self, sample_papers, topic_quality_first):
        """Test that search() returns filtered results from discover().

        Note: With the unified discovery API, search() routes through discover().
        Quality filtering is handled within discover() and returned via ScoredPaper.
        """
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            ScoredPaper,
        )

        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
            pdf_strategy=PDFStrategy.QUALITY_FIRST,
            quality_ranking=True,
            min_quality_score=50.0,  # Filter out low quality
        )

        # Mock discover to return only papers above threshold
        mock_result = DiscoveryResult(
            papers=[
                ScoredPaper(
                    paper_id="high_quality",
                    title="High Quality Paper",
                    url="https://example.com/paper1",
                    quality_score=0.85,  # 85% - above threshold
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=3,
                papers_after_quality_filter=1,
                avg_quality_score=0.85,
            ),
            mode=DiscoveryMode.SURFACE,
        )

        service = DiscoveryService()

        with patch.object(service, "discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = mock_result
            result = await service.search(topic)

            # Should return only filtered papers from discover()
            assert len(result) == 1
            # Quality score is converted from 0-1 to 0-100 scale
            assert result[0].quality_score >= 50.0


class TestDiscoveryServiceArxivSupplement:
    """Tests for ArXiv supplement feature."""

    @pytest.mark.asyncio
    async def test_arxiv_supplement_triggered(self, topic_arxiv_supplement):
        """Test that search() returns combined results from discover().

        Note: With the unified discovery API, search() routes through discover().
        ArXiv supplement behavior is handled within discover().
        """
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            ScoredPaper,
        )

        topic = ResearchTopic(
            query="test query",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
            arxiv_supplement_threshold=0.5,
            quality_ranking=False,
            auto_select_provider=False,
        )

        # Mock discover to return both primary and supplemental papers
        mock_result = DiscoveryResult(
            papers=[
                ScoredPaper(
                    paper_id="ss_paper",
                    title="SS Paper",
                    url="https://example.com/ss",
                    quality_score=0.7,
                ),
                ScoredPaper(
                    paper_id="arxiv_paper",
                    title="ArXiv Paper",
                    url="https://arxiv.org/paper",
                    quality_score=0.8,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=2,
                papers_after_quality_filter=2,
                avg_quality_score=0.75,
            ),
            mode=DiscoveryMode.SURFACE,
        )

        service = DiscoveryService(api_key="test_key")

        with patch.object(service, "discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = mock_result
            result = await service.search(topic)

            # Should include both papers from discover()
            assert len(result) == 2
            paper_ids = [p.paper_id for p in result]
            assert "ss_paper" in paper_ids
            assert "arxiv_paper" in paper_ids

    @pytest.mark.asyncio
    async def test_arxiv_supplement_not_triggered(self, topic_arxiv_supplement):
        """Test that search() returns only primary papers from discover().

        Note: With the unified discovery API, search() routes through discover().
        When PDF availability is sufficient, discover() returns only primary results.
        """
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            ScoredPaper,
        )

        topic = ResearchTopic(
            query="test query",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
            arxiv_supplement_threshold=0.5,
            quality_ranking=False,
            auto_select_provider=False,
        )

        # Mock discover to return only primary papers (no supplement needed)
        mock_result = DiscoveryResult(
            papers=[
                ScoredPaper(
                    paper_id="paper1",
                    title="Paper 1",
                    url="https://example.com/1",
                    quality_score=0.8,
                ),
                ScoredPaper(
                    paper_id="paper2",
                    title="Paper 2",
                    url="https://example.com/2",
                    quality_score=0.75,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=2,
                papers_after_quality_filter=2,
                avg_quality_score=0.775,
            ),
            mode=DiscoveryMode.SURFACE,
        )

        service = DiscoveryService(api_key="test_key")

        with patch.object(service, "discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = mock_result
            result = await service.search(topic)

            # Should only include primary papers from discover()
            assert len(result) == 2
            mock_discover.assert_called_once()

    @pytest.mark.asyncio
    async def test_arxiv_supplement_deduplication(self, topic_arxiv_supplement):
        """Test that search() returns deduplicated results from discover().

        Note: With the unified discovery API, search() routes through discover().
        Deduplication is handled within discover().
        """
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            ScoredPaper,
        )

        topic = ResearchTopic(
            query="test query",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
            arxiv_supplement_threshold=0.5,
            quality_ranking=False,
            auto_select_provider=False,
        )

        # Mock discover to return deduplicated results
        mock_result = DiscoveryResult(
            papers=[
                ScoredPaper(
                    paper_id="shared_paper",
                    title="Shared Paper",
                    url="https://example.com/shared",
                    quality_score=0.7,
                ),
                ScoredPaper(
                    paper_id="unique_arxiv",
                    title="Unique ArXiv Paper",
                    url="https://arxiv.org/unique",
                    quality_score=0.8,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=3,
                papers_after_dedup=2,
                papers_after_quality_filter=2,
                avg_quality_score=0.75,
            ),
            mode=DiscoveryMode.SURFACE,
        )

        service = DiscoveryService(api_key="test_key")

        with patch.object(service, "discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = mock_result
            result = await service.search(topic)

            # Should return deduplicated results from discover()
            assert len(result) == 2
            paper_ids = [p.paper_id for p in result]
            assert "shared_paper" in paper_ids
            assert "unique_arxiv" in paper_ids

    @pytest.mark.asyncio
    async def test_arxiv_supplement_empty_primary(self, topic_arxiv_supplement):
        """Test ArXiv supplement when primary returns no papers."""
        arxiv_papers = [
            PaperMetadata(
                paper_id="arxiv_paper",
                title="ArXiv Paper",
                url="https://arxiv.org/paper",
                pdf_available=True,
            ),
        ]

        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_ss = AsyncMock()
            mock_ss.search = AsyncMock(return_value=[])  # No primary results

            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(return_value=arxiv_papers)
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService(api_key="test_key")
            service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_ss
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance
            service.config = ProviderSelectionConfig(auto_select=False)

            topic = ResearchTopic(
                query="test query",
                provider=ProviderType.SEMANTIC_SCHOLAR,
                timeframe=TimeframeRecent(value="48h"),
                pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
                quality_ranking=False,
                auto_select_provider=False,
            )

            result = await service.search(topic)

            # Should fall back to ArXiv
            assert len(result) == 1
            assert result[0].paper_id == "arxiv_paper"

    @pytest.mark.asyncio
    async def test_arxiv_supplement_arxiv_unavailable(self):
        """Test ArXiv supplement gracefully handles missing ArXiv provider."""
        primary_papers = [
            PaperMetadata(
                paper_id="paper1",
                title="Paper 1",
                url="https://example.com/1",
                pdf_available=False,
            ),
        ]

        with patch("src.services.discovery_service.ArxivProvider"):
            mock_ss = AsyncMock()
            mock_ss.search = AsyncMock(return_value=primary_papers)

            service = DiscoveryService(api_key="test_key")
            service.providers = {ProviderType.SEMANTIC_SCHOLAR: mock_ss}
            # No ArXiv provider!
            service.config = ProviderSelectionConfig(auto_select=False)

            topic = ResearchTopic(
                query="test query",
                provider=ProviderType.SEMANTIC_SCHOLAR,
                timeframe=TimeframeRecent(value="48h"),
                pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
                quality_ranking=False,
                auto_select_provider=False,
            )

            result = await service.search(topic)

            # Should return primary papers only
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_arxiv_supplement_arxiv_fails(self):
        """Test that search() returns primary papers when ArXiv fails.

        Note: With the unified discovery API, search() routes through discover().
        Error handling for supplement failures is done within discover().
        """
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            ScoredPaper,
        )

        topic = ResearchTopic(
            query="test query",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
            quality_ranking=False,
            auto_select_provider=False,
        )

        # Mock discover to return primary papers only
        # (ArXiv supplement failed internally)
        mock_result = DiscoveryResult(
            papers=[
                ScoredPaper(
                    paper_id="paper1",
                    title="Paper 1",
                    url="https://example.com/1",
                    quality_score=0.7,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=1,
                papers_after_quality_filter=1,
                avg_quality_score=0.7,
            ),
            mode=DiscoveryMode.SURFACE,
        )

        service = DiscoveryService(api_key="test_key")

        with patch.object(service, "discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = mock_result
            result = await service.search(topic)

            # Should return primary papers from discover()
            assert len(result) == 1


class TestDiscoveryServiceQualityStats:
    """Tests for quality statistics logging."""

    @pytest.mark.asyncio
    async def test_log_quality_stats(self, sample_papers, topic_quality_first):
        """Test that search() returns results with quality metrics from discover().

        Note: With the unified discovery API, search() routes through discover().
        Quality statistics are logged within discover() and returned in metrics.
        """
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            ScoredPaper,
        )

        # Mock discover to return papers with quality metrics
        mock_result = DiscoveryResult(
            papers=[
                ScoredPaper(
                    paper_id="paper1",
                    title="Paper 1",
                    url="https://example.com/1",
                    quality_score=0.85,
                ),
                ScoredPaper(
                    paper_id="paper2",
                    title="Paper 2",
                    url="https://example.com/2",
                    quality_score=0.75,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=3,
                papers_after_quality_filter=2,
                avg_quality_score=0.8,
            ),
            mode=DiscoveryMode.SURFACE,
        )

        service = DiscoveryService()

        with patch.object(service, "discover", new_callable=AsyncMock) as mock_discover:
            mock_discover.return_value = mock_result
            result = await service.search(topic_quality_first)

            # Verify search returned results from discover
            assert len(result) == 2
            mock_discover.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_quality_stats_empty_papers(self, topic_quality_first):
        """Test that quality stats are NOT logged for empty results."""
        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(return_value=[])
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService()
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance

            # Patch logger in the discovery.metrics module
            with patch("src.services.discovery.metrics.logger") as mock_logger:
                await service.search(topic_quality_first)

                # Should not log quality stats for empty results
                for call in mock_logger.info.call_args_list:
                    if len(call[0]) > 0:
                        assert call[0][0] != "quality_ranking_stats"
