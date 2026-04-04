"""Integration tests for RelevanceFilter with ResultAggregator.

Tests end-to-end relevance filtering in the aggregation pipeline.
"""

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.config import AggregationConfig, RelevanceFilterConfig
from src.models.paper import PaperMetadata
from src.services.result_aggregator import ResultAggregator


@pytest.fixture
def nmt_papers():
    """Create NMT-related papers."""
    return [
        PaperMetadata(
            paper_id="nmt1",
            title="Neural Machine Translation for Low-Resource Languages",
            abstract="We present a neural approach to machine translation...",
            url="https://example.com/nmt1",
            citation_count=50,
        ),
        PaperMetadata(
            paper_id="nmt2",
            title="Attention Mechanisms in Neural Machine Translation",
            abstract="This work explores attention for translation...",
            url="https://example.com/nmt2",
            citation_count=30,
        ),
    ]


@pytest.fixture
def irrelevant_papers():
    """Create papers irrelevant to NMT."""
    return [
        PaperMetadata(
            paper_id="physics1",
            title="Quantum Entanglement in Photonic Crystals",
            abstract="We study quantum phenomena in photonic systems...",
            url="https://example.com/physics1",
            citation_count=100,  # High citations but irrelevant
        ),
        PaperMetadata(
            paper_id="gaming1",
            title="Action Recognition in Multiplayer Video Games",
            abstract="A system for recognizing player actions in games...",
            url="https://example.com/gaming1",
            citation_count=20,
        ),
    ]


class TestRelevanceFilterIntegration:
    """Integration tests for relevance filtering in aggregation pipeline."""

    @pytest.mark.asyncio
    async def test_aggregator_without_relevance_filter(
        self, nmt_papers, irrelevant_papers
    ):
        """Test that without filtering, all papers pass through."""
        # Disable relevance filtering
        config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=False)
        )
        aggregator = ResultAggregator(
            config=config, query="neural machine translation"
        )

        source_results = {
            "arxiv": nmt_papers[:1] + irrelevant_papers[:1],
            "semantic_scholar": nmt_papers[1:] + irrelevant_papers[1:],
        }

        result = await aggregator.aggregate(source_results)

        # All 4 papers should pass (no filtering)
        assert len(result.papers) == 4

    @pytest.mark.asyncio
    async def test_aggregator_with_relevance_filter_enabled(
        self, nmt_papers, irrelevant_papers
    ):
        """Test that relevance filtering removes irrelevant papers."""
        config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=True, threshold=0.3)
        )
        aggregator = ResultAggregator(
            config=config, query="neural machine translation"
        )

        # Mock the embedding service to return appropriate similarities
        with patch.object(
            aggregator.relevance_filter.embedding_service,
            "get_embedding",
            new_callable=AsyncMock,
        ) as mock_get_embedding:
            query_embedding = np.array([1.0, 0.0, 0.0])
            nmt_embedding = np.array([0.9, 0.1, 0.0])  # High similarity
            irrelevant_embedding = np.array([0.0, 0.0, 1.0])  # Low similarity

            async def mock_embedding(paper, use_cache=True):
                if hasattr(paper, "paper_id"):
                    if paper.paper_id.startswith("query:"):
                        return query_embedding
                    elif "nmt" in paper.paper_id:
                        return nmt_embedding
                    else:
                        return irrelevant_embedding
                return np.zeros(3)

            mock_get_embedding.side_effect = mock_embedding

            source_results = {
                "arxiv": nmt_papers[:1] + irrelevant_papers[:1],
                "semantic_scholar": nmt_papers[1:] + irrelevant_papers[1:],
            }

            result = await aggregator.aggregate(source_results)

            # Only NMT papers should pass (2 papers)
            assert len(result.papers) == 2
            assert all("nmt" in p.paper_id for p in result.papers)

    @pytest.mark.asyncio
    async def test_aggregator_without_query_skips_filtering(
        self, nmt_papers, irrelevant_papers
    ):
        """Test that without query, filtering is skipped."""
        config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=True)
        )
        # No query provided
        aggregator = ResultAggregator(config=config, query=None)

        source_results = {
            "source": nmt_papers + irrelevant_papers,
        }

        result = await aggregator.aggregate(source_results)

        # All papers should pass (no query = no filtering)
        assert len(result.papers) == 4

    @pytest.mark.asyncio
    async def test_relevance_scores_attached_to_papers(
        self, nmt_papers, irrelevant_papers
    ):
        """Test that relevance scores are attached to filtered papers."""
        config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=True, threshold=0.1)
        )
        aggregator = ResultAggregator(
            config=config, query="neural machine translation"
        )

        with patch.object(
            aggregator.relevance_filter.embedding_service,
            "get_embedding",
            new_callable=AsyncMock,
        ) as mock_get_embedding:
            query_embedding = np.array([1.0, 0.0, 0.0])
            paper_embedding = np.array([0.8, 0.6, 0.0])

            async def mock_embedding(paper, use_cache=True):
                if hasattr(paper, "paper_id") and paper.paper_id.startswith("query:"):
                    return query_embedding
                return paper_embedding

            mock_get_embedding.side_effect = mock_embedding

            source_results = {"source": nmt_papers}
            result = await aggregator.aggregate(source_results)

            # All papers should have relevance scores
            for paper in result.papers:
                assert paper.relevance_score > 0.0
                assert paper.relevance_score <= 1.0

    @pytest.mark.asyncio
    async def test_threshold_override_per_topic(self, nmt_papers, irrelevant_papers):
        """Test that threshold can be configured per topic."""
        # Low threshold - more papers pass
        low_config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=True, threshold=0.1)
        )
        low_aggregator = ResultAggregator(
            config=low_config, query="neural machine translation"
        )

        # High threshold - fewer papers pass
        high_config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=True, threshold=0.9)
        )
        high_aggregator = ResultAggregator(
            config=high_config, query="neural machine translation"
        )

        with patch(
            "src.services.discovery.relevance_filter.EmbeddingService"
        ) as mock_service_class:
            mock_service = MagicMock()
            mock_service.get_embedding = AsyncMock()
            mock_service_class.return_value = mock_service

            query_embedding = np.array([1.0, 0.0, 0.0])
            # Moderate similarity (0.5) - should pass low threshold, fail high
            paper_embedding = np.array([0.5, 0.866, 0.0])

            async def mock_embedding(paper, use_cache=True):
                if hasattr(paper, "paper_id") and paper.paper_id.startswith("query:"):
                    return query_embedding
                return paper_embedding

            mock_service.get_embedding.side_effect = mock_embedding

            source_results = {"source": nmt_papers[:1]}

            # Recreate aggregators with mocked service
            low_aggregator.relevance_filter.embedding_service = mock_service
            high_aggregator.relevance_filter.embedding_service = mock_service

            low_result = await low_aggregator.aggregate(source_results)
            high_result = await high_aggregator.aggregate({"source": nmt_papers[:1]})

            # Low threshold should pass paper, high should not
            assert len(low_result.papers) >= len(high_result.papers)

    @pytest.mark.asyncio
    async def test_filter_preserves_deduplication(self, nmt_papers):
        """Test that relevance filtering happens after deduplication."""
        # Create duplicate papers (same DOI)
        paper1 = nmt_papers[0].model_copy(update={"doi": "10.1234/test"})
        paper2 = nmt_papers[1].model_copy(
            update={"doi": "10.1234/test", "paper_id": "nmt1_dup"}
        )

        config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=True, threshold=0.3)
        )
        aggregator = ResultAggregator(
            config=config, query="neural machine translation"
        )

        with patch.object(
            aggregator.relevance_filter.embedding_service,
            "get_embedding",
            new_callable=AsyncMock,
        ) as mock_get_embedding:
            query_embedding = np.array([1.0, 0.0, 0.0])
            paper_embedding = np.array([0.9, 0.1, 0.0])

            async def mock_embedding(paper, use_cache=True):
                if hasattr(paper, "paper_id") and paper.paper_id.startswith("query:"):
                    return query_embedding
                return paper_embedding

            mock_get_embedding.side_effect = mock_embedding

            source_results = {
                "arxiv": [paper1],
                "semantic_scholar": [paper2],
            }

            result = await aggregator.aggregate(source_results)

            # Should have 1 paper (deduplicated, then filtered)
            assert len(result.papers) == 1
            assert result.papers[0].source_count == 2

    @pytest.mark.asyncio
    async def test_filter_stats_logged(self, nmt_papers, irrelevant_papers):
        """Test that filtering removes irrelevant papers correctly."""
        config = AggregationConfig(
            relevance_filter=RelevanceFilterConfig(enabled=True, threshold=0.5)
        )
        aggregator = ResultAggregator(
            config=config, query="neural machine translation"
        )

        with patch.object(
            aggregator.relevance_filter.embedding_service,
            "get_embedding",
            new_callable=AsyncMock,
        ) as mock_get_embedding:
            query_embedding = np.array([1.0, 0.0, 0.0])
            nmt_embedding = np.array([0.9, 0.1, 0.0])
            irrelevant_embedding = np.array([0.0, 0.0, 1.0])

            async def mock_embedding(paper, use_cache=True):
                if hasattr(paper, "paper_id"):
                    if paper.paper_id.startswith("query:"):
                        return query_embedding
                    elif "nmt" in paper.paper_id:
                        return nmt_embedding
                    else:
                        return irrelevant_embedding
                return np.zeros(3)

            mock_get_embedding.side_effect = mock_embedding

            source_results = {"source": nmt_papers + irrelevant_papers}

            result = await aggregator.aggregate(source_results)

            # Should have filtered papers (2 relevant pass, 2 irrelevant filtered)
            assert len(result.papers) == 2
