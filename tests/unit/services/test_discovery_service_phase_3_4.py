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

    def test_quality_scorer_default_init(self):
        """Test that quality scorer is initialized by default."""
        with patch("src.services.discovery_service.ArxivProvider"):
            service = DiscoveryService()
            assert service._quality_scorer is not None
            assert isinstance(service._quality_scorer, QualityScorer)

    def test_quality_scorer_custom_init(self):
        """Test that custom quality scorer can be provided."""
        custom_scorer = QualityScorer(
            citation_weight=0.5,
            venue_weight=0.2,
            recency_weight=0.2,
            completeness_weight=0.1,
        )
        with patch("src.services.discovery_service.ArxivProvider"):
            service = DiscoveryService(quality_scorer=custom_scorer)
            assert service._quality_scorer is custom_scorer


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
        """Test that min_quality_score filters out low quality papers."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="48h"),
            pdf_strategy=PDFStrategy.QUALITY_FIRST,
            quality_ranking=True,
            min_quality_score=50.0,  # Filter out low quality
        )

        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(return_value=sample_papers.copy())
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService()
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance

            result = await service.search(topic)

            # Should filter out papers below threshold
            assert len(result) < len(sample_papers)
            for paper in result:
                assert paper.quality_score >= 50.0


class TestDiscoveryServiceArxivSupplement:
    """Tests for ArXiv supplement feature."""

    @pytest.mark.asyncio
    async def test_arxiv_supplement_triggered(self, topic_arxiv_supplement):
        """Test ArXiv supplement when PDF rate below threshold."""
        # Papers with 0% PDF availability
        primary_papers = [
            PaperMetadata(
                paper_id="ss_paper",
                title="SS Paper",
                url="https://example.com/ss",
                pdf_available=False,
            ),
        ]

        arxiv_papers = [
            PaperMetadata(
                paper_id="arxiv_paper",
                title="ArXiv Paper",
                url="https://arxiv.org/paper",
                pdf_available=True,
                pdf_source="arxiv",
            ),
        ]

        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_ss = AsyncMock()
            mock_ss.search = AsyncMock(return_value=primary_papers)

            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(return_value=arxiv_papers)
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService(api_key="test_key")
            service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_ss
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance
            service.config = ProviderSelectionConfig(auto_select=False)

            # Override topic to use SS as primary
            topic = ResearchTopic(
                query="test query",
                provider=ProviderType.SEMANTIC_SCHOLAR,
                timeframe=TimeframeRecent(value="48h"),
                pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
                arxiv_supplement_threshold=0.5,
                quality_ranking=False,  # Disable for simpler test
                auto_select_provider=False,
            )

            result = await service.search(topic)

            # Should include both primary and ArXiv papers
            assert len(result) == 2
            paper_ids = [p.paper_id for p in result]
            assert "ss_paper" in paper_ids
            assert "arxiv_paper" in paper_ids

    @pytest.mark.asyncio
    async def test_arxiv_supplement_not_triggered(self, topic_arxiv_supplement):
        """Test ArXiv supplement NOT triggered when PDF rate above threshold."""
        # Papers with 100% PDF availability
        primary_papers = [
            PaperMetadata(
                paper_id="paper1",
                title="Paper 1",
                url="https://example.com/1",
                pdf_available=True,
            ),
            PaperMetadata(
                paper_id="paper2",
                title="Paper 2",
                url="https://example.com/2",
                pdf_available=True,
            ),
        ]

        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_ss = AsyncMock()
            mock_ss.search = AsyncMock(return_value=primary_papers)

            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock()  # Should NOT be called
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
                arxiv_supplement_threshold=0.5,
                quality_ranking=False,
                auto_select_provider=False,
            )

            result = await service.search(topic)

            # Should only include primary papers
            assert len(result) == 2
            # ArXiv search should NOT have been called
            mock_arxiv_instance.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_arxiv_supplement_deduplication(self, topic_arxiv_supplement):
        """Test that duplicate papers are removed during ArXiv supplement."""
        # Same paper appears in both sources
        primary_papers = [
            PaperMetadata(
                paper_id="shared_paper",
                doi="10.1234/shared",
                title="Shared Paper",
                url="https://example.com/shared",
                pdf_available=False,
            ),
        ]

        arxiv_papers = [
            PaperMetadata(
                paper_id="shared_paper_arxiv",
                doi="10.1234/shared",  # Same DOI
                title="Shared Paper",
                url="https://arxiv.org/shared",
                pdf_available=True,
            ),
            PaperMetadata(
                paper_id="unique_arxiv",
                title="Unique ArXiv Paper",
                url="https://arxiv.org/unique",
                pdf_available=True,
            ),
        ]

        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_ss = AsyncMock()
            mock_ss.search = AsyncMock(return_value=primary_papers)

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
                arxiv_supplement_threshold=0.5,
                quality_ranking=False,
                auto_select_provider=False,
            )

            result = await service.search(topic)

            # Should deduplicate by DOI
            assert len(result) == 2  # shared + unique
            paper_ids = [p.paper_id for p in result]
            # Primary paper preferred
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
        """Test ArXiv supplement handles ArXiv search failure."""
        primary_papers = [
            PaperMetadata(
                paper_id="paper1",
                title="Paper 1",
                url="https://example.com/1",
                pdf_available=False,
            ),
        ]

        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_ss = AsyncMock()
            mock_ss.search = AsyncMock(return_value=primary_papers)

            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(side_effect=Exception("ArXiv error"))
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

            # Should return primary papers despite ArXiv failure
            assert len(result) == 1


class TestDiscoveryServiceQualityStats:
    """Tests for quality statistics logging."""

    @pytest.mark.asyncio
    async def test_log_quality_stats(self, sample_papers, topic_quality_first):
        """Test that quality statistics are logged."""
        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(return_value=sample_papers.copy())
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService()
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance

            with patch("src.services.discovery_service.logger") as mock_logger:
                await service.search(topic_quality_first)

                # Check that quality stats were logged
                log_calls = mock_logger.info.call_args_list
                quality_stat_call = None
                for call in log_calls:
                    if len(call[0]) > 0 and call[0][0] == "quality_ranking_stats":
                        quality_stat_call = call
                        break

                assert quality_stat_call is not None

    @pytest.mark.asyncio
    async def test_log_quality_stats_empty_papers(self, topic_quality_first):
        """Test that quality stats are NOT logged for empty results."""
        with patch("src.services.discovery_service.ArxivProvider") as mock_arxiv:
            mock_arxiv_instance = AsyncMock()
            mock_arxiv_instance.search = AsyncMock(return_value=[])
            mock_arxiv.return_value = mock_arxiv_instance

            service = DiscoveryService()
            service.providers[ProviderType.ARXIV] = mock_arxiv_instance

            with patch("src.services.discovery_service.logger") as mock_logger:
                await service.search(topic_quality_first)

                # Should not log quality stats for empty results
                for call in mock_logger.info.call_args_list:
                    if len(call[0]) > 0:
                        assert call[0][0] != "quality_ranking_stats"
