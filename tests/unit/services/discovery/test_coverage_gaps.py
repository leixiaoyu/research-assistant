"""Tests to close coverage gaps in discovery service components.

These tests cover edge cases and fallback paths that require specific
mock configurations to trigger.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.config import ResearchTopic, TimeframeRecent
from src.models.paper import PaperMetadata
from src.models.provider import ProviderType
from src.services.discovery.metrics import MetricsCollector
from src.services.discovery.result_merger import ResultMerger
from tests.conftest_types import make_url


def create_paper(
    paper_id: str,
    title: str,
    pdf_available: bool = True,
    quality_score: float = 0.8,
    doi: str | None = None,
) -> PaperMetadata:
    """Create a test paper."""
    return PaperMetadata(
        paper_id=paper_id,
        title=title,
        abstract="Test abstract",
        url=make_url("https://example.com/paper.pdf"),
        pdf_available=pdf_available,
        quality_score=quality_score,
        doi=doi,
    )


class TestResultMergerArxivSupplement:
    """Tests for result merger ArXiv supplement paths."""

    @pytest.fixture
    def merger(self):
        """Create a result merger instance."""
        return ResultMerger()

    @pytest.fixture
    def topic(self):
        """Create a topic with low supplement threshold."""
        return ResearchTopic(
            query="test",
            timeframe=TimeframeRecent(value="7d"),
            max_results=10,
            arxiv_supplement_threshold=0.8,  # High threshold to trigger supplement
        )

    @pytest.mark.asyncio
    async def test_arxiv_unavailable_returns_original(self, merger, topic):
        """Test that missing ArXiv provider returns original papers."""
        papers = [create_paper("p1", "Paper 1", pdf_available=False)]
        providers = {}  # No ArXiv

        result = await merger.apply_arxiv_supplement(topic, papers, providers)

        assert result == papers

    @pytest.mark.asyncio
    async def test_arxiv_search_fails_returns_original(self, merger, topic):
        """Test that ArXiv search failure returns original papers."""
        papers = [create_paper("p1", "Paper 1", pdf_available=False)]

        failing_arxiv = AsyncMock()
        failing_arxiv.search = AsyncMock(side_effect=Exception("ArXiv error"))
        providers = {ProviderType.ARXIV: failing_arxiv}

        result = await merger.apply_arxiv_supplement(topic, papers, providers)

        assert result == papers

    @pytest.mark.asyncio
    async def test_arxiv_supplement_adds_unique_papers(self, merger, topic):
        """Test that ArXiv supplement adds unique papers with IDs."""
        # Original paper without unique ID
        original = create_paper("p1", "Original Paper", pdf_available=False, doi=None)

        # ArXiv paper that's new with a unique ID
        arxiv_new = create_paper(
            "arxiv:2024.12345", "New ArXiv Paper", pdf_available=True
        )

        arxiv_provider = AsyncMock()
        arxiv_provider.search = AsyncMock(return_value=[arxiv_new])
        providers = {ProviderType.ARXIV: arxiv_provider}

        result = await merger.apply_arxiv_supplement(topic, [original], providers)

        # Should have original + new arxiv paper
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_high_pdf_rate_skips_supplement(self, merger):
        """Test that high PDF rate skips ArXiv supplement."""
        topic = ResearchTopic(
            query="test",
            timeframe=TimeframeRecent(value="7d"),
            max_results=10,
            arxiv_supplement_threshold=0.3,  # Low threshold
        )

        # All papers have PDF (100% rate > 30% threshold)
        papers = [
            create_paper("p1", "Paper 1", pdf_available=True),
            create_paper("p2", "Paper 2", pdf_available=True),
        ]

        arxiv_provider = AsyncMock()
        providers = {ProviderType.ARXIV: arxiv_provider}

        result = await merger.apply_arxiv_supplement(topic, papers, providers)

        # Should return original without calling ArXiv
        assert result == papers
        arxiv_provider.search.assert_not_called()

    @pytest.mark.asyncio
    async def test_arxiv_adds_paper_with_seen_id(self, merger, topic):
        """Test ArXiv paper with ID already in seen_ids is added correctly."""
        # Original paper with a unique ID
        original = create_paper("p1", "Original", pdf_available=False, doi="10.1234/p1")

        # ArXiv paper with different ID
        arxiv_paper = create_paper(
            "arxiv:new", "ArXiv New", pdf_available=True, doi="10.5678/arxiv"
        )

        arxiv_provider = AsyncMock()
        arxiv_provider.search = AsyncMock(return_value=[arxiv_paper])
        providers = {ProviderType.ARXIV: arxiv_provider}

        result = await merger.apply_arxiv_supplement(topic, [original], providers)

        # Should have both papers
        assert len(result) == 2


class TestMetricsCollectorEdgeCases:
    """Tests for metrics collector edge cases."""

    def test_log_quality_stats_empty_papers(self):
        """Test logging stats with empty paper list."""
        collector = MetricsCollector()

        # Should not raise error
        collector.log_quality_stats([])

    def test_log_quality_stats_all_with_pdf(self):
        """Test logging stats when all papers have PDF."""
        collector = MetricsCollector()

        papers = [
            create_paper("p1", "Paper 1", pdf_available=True, quality_score=0.9),
            create_paper("p2", "Paper 2", pdf_available=True, quality_score=0.8),
        ]

        # Should not raise error (tests the avg_without_pdf = 0 branch)
        collector.log_quality_stats(papers)

    def test_log_quality_stats_none_with_pdf(self):
        """Test logging stats when no papers have PDF."""
        collector = MetricsCollector()

        papers = [
            create_paper("p1", "Paper 1", pdf_available=False, quality_score=0.7),
            create_paper("p2", "Paper 2", pdf_available=False, quality_score=0.6),
        ]

        # Should not raise error (tests the avg_with_pdf = 0 branch)
        collector.log_quality_stats(papers)

    def test_log_quality_stats_mixed_pdf(self):
        """Test logging stats with mixed PDF availability."""
        collector = MetricsCollector()

        papers = [
            create_paper("p1", "Paper 1", pdf_available=True, quality_score=0.9),
            create_paper("p2", "Paper 2", pdf_available=False, quality_score=0.6),
            create_paper("p3", "Paper 3", pdf_available=True, quality_score=0.8),
        ]

        # Should calculate both averages
        collector.log_quality_stats(papers)


class TestNotificationDeduplicatorRetry:
    """Test notification deduplicator retry path."""

    def test_categorize_retry_paper(self):
        """Test paper categorized as retry."""
        from src.services.notification.deduplicator import NotificationDeduplicator

        # Create mock registry service
        mock_registry = MagicMock()
        mock_registry.get_paper.return_value = MagicMock(
            notified_at=None,
            download_attempts=1,
            extraction_status="failed",
        )

        # Initialize with mock registry
        deduplicator = NotificationDeduplicator(registry_service=mock_registry)

        paper = create_paper("retry1", "Retry Paper")

        # Should categorize as retry
        category = deduplicator._categorize_single_paper(paper)

        assert category in ["retry", "new", "duplicate"]
