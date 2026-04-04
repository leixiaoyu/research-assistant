"""Unit tests for RelevanceFilter (Phase 7 Issue 2).

Tests relevance filtering using embedding-based similarity.
"""

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock

from src.models.paper import PaperMetadata
from src.services.discovery.relevance_filter import RelevanceFilter, QueryPaper
from src.services.embeddings.embedding_service import EmbeddingService


@pytest.fixture
def mock_embedding_service():
    """Create mock embedding service."""
    service = MagicMock(spec=EmbeddingService)
    service.get_embedding = AsyncMock()
    return service


@pytest.fixture
def relevance_filter(mock_embedding_service):
    """Create RelevanceFilter with mock embedding service."""
    return RelevanceFilter(
        embedding_service=mock_embedding_service,
        threshold=0.3,
        blend_weight=0.4,
    )


@pytest.fixture
def sample_papers():
    """Create sample papers for testing."""
    return [
        PaperMetadata(
            paper_id="nmt1",
            title="Neural Machine Translation for Low-Resource Languages",
            abstract="This paper presents a neural machine translation approach...",
            url="https://example.com/1",
        ),
        PaperMetadata(
            paper_id="physics1",
            title="Quantum Entanglement in Photonic Systems",
            abstract="We study quantum entanglement in photonic crystals...",
            url="https://example.com/2",
        ),
        PaperMetadata(
            paper_id="gaming1",
            title="Action Recognition in Video Games",
            abstract="This work presents an action recognition system for games...",
            url="https://example.com/3",
        ),
    ]


class TestQueryPaper:
    """Tests for QueryPaper wrapper."""

    def test_query_paper_initialization(self):
        """Test QueryPaper wrapper creation."""
        query = "neural machine translation"
        qp = QueryPaper(query)

        assert qp.title == query
        assert qp.abstract == query
        assert qp.paper_id.startswith("query:")

    def test_query_paper_same_hash_for_same_query(self):
        """Test that same query produces same paper_id."""
        query = "neural machine translation"
        qp1 = QueryPaper(query)
        qp2 = QueryPaper(query)

        assert qp1.paper_id == qp2.paper_id


class TestRelevanceFilter:
    """Tests for RelevanceFilter."""

    @pytest.mark.asyncio
    async def test_filter_papers_empty_list(self, relevance_filter):
        """Test filtering empty paper list returns empty list."""
        result = await relevance_filter.filter_papers([], "machine translation")

        assert result == []

    @pytest.mark.asyncio
    async def test_filter_papers_removes_irrelevant(
        self, relevance_filter, mock_embedding_service, sample_papers
    ):
        """Test that irrelevant papers are filtered out."""
        # Mock embeddings: NMT papers similar to query, physics/gaming not
        query_embedding = np.array([1.0, 0.0, 0.0])
        nmt_embedding = np.array([0.9, 0.1, 0.0])  # High similarity
        physics_embedding = np.array([0.0, 0.0, 1.0])  # Low similarity
        gaming_embedding = np.array([0.0, 1.0, 0.0])  # Low similarity

        async def mock_get_embedding(paper, use_cache=True):
            if hasattr(paper, "paper_id"):
                if paper.paper_id.startswith("query:"):
                    return query_embedding
                elif paper.paper_id == "nmt1":
                    return nmt_embedding
                elif paper.paper_id == "physics1":
                    return physics_embedding
                elif paper.paper_id == "gaming1":
                    return gaming_embedding
            return np.zeros(3)

        mock_embedding_service.get_embedding.side_effect = mock_get_embedding

        result = await relevance_filter.filter_papers(
            sample_papers, "machine translation"
        )

        # Only NMT paper should pass (similarity > 0.3)
        assert len(result) == 1
        assert result[0].paper_id == "nmt1"

    @pytest.mark.asyncio
    async def test_filter_papers_attaches_relevance_score(
        self, relevance_filter, mock_embedding_service, sample_papers
    ):
        """Test that relevance scores are attached to filtered papers."""
        query_embedding = np.array([1.0, 0.0, 0.0])
        paper_embedding = np.array([0.8, 0.6, 0.0])  # Similarity = 0.8

        async def mock_get_embedding(paper, use_cache=True):
            if hasattr(paper, "paper_id") and paper.paper_id.startswith("query:"):
                return query_embedding
            return paper_embedding

        mock_embedding_service.get_embedding.side_effect = mock_get_embedding

        result = await relevance_filter.filter_papers(
            [sample_papers[0]], "machine translation"
        )

        assert len(result) == 1
        assert hasattr(result[0], "relevance_score")
        assert result[0].relevance_score > 0.0
        assert result[0].relevance_score <= 1.0

    @pytest.mark.asyncio
    async def test_caches_query_embeddings(
        self, relevance_filter, mock_embedding_service, sample_papers
    ):
        """Test that query embeddings are cached."""
        query_embedding = np.array([1.0, 0.0, 0.0])
        paper_embedding = np.array([0.9, 0.1, 0.0])

        async def mock_get_embedding(paper, use_cache=True):
            if hasattr(paper, "paper_id") and paper.paper_id.startswith("query:"):
                return query_embedding
            return paper_embedding

        mock_embedding_service.get_embedding.side_effect = mock_get_embedding

        query = "machine translation"

        # First call should compute and cache
        await relevance_filter.filter_papers([sample_papers[0]], query)

        # Second call with same query should use cache
        await relevance_filter.filter_papers([sample_papers[1]], query)

        # Check cache
        assert len(relevance_filter._query_embedding_cache) == 1
        assert query in relevance_filter._query_embedding_cache

    @pytest.mark.asyncio
    async def test_threshold_configurable(self, mock_embedding_service, sample_papers):
        """Test that different thresholds filter differently."""
        query_embedding = np.array([1.0, 0.0, 0.0])
        # Paper with moderate similarity (0.5)
        paper_embedding = np.array([0.5, 0.866, 0.0])

        async def mock_get_embedding(paper, use_cache=True):
            if hasattr(paper, "paper_id") and paper.paper_id.startswith("query:"):
                return query_embedding
            return paper_embedding

        mock_embedding_service.get_embedding.side_effect = mock_get_embedding

        # Low threshold - should pass
        low_filter = RelevanceFilter(
            embedding_service=mock_embedding_service, threshold=0.1
        )
        low_result = await low_filter.filter_papers([sample_papers[0]], "query")
        assert len(low_result) == 1

        # High threshold - should fail
        high_filter = RelevanceFilter(
            embedding_service=mock_embedding_service, threshold=0.8
        )
        high_result = await high_filter.filter_papers([sample_papers[0]], "query")
        assert len(high_result) == 0

    @pytest.mark.asyncio
    async def test_cosine_similarity_calculation(self, relevance_filter):
        """Test cosine similarity calculation."""
        # Identical vectors
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        assert relevance_filter._cosine_similarity(a, b) == pytest.approx(1.0)

        # Orthogonal vectors
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert relevance_filter._cosine_similarity(a, b) == pytest.approx(0.0)

        # Opposite vectors
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([-1.0, 0.0, 0.0])
        assert relevance_filter._cosine_similarity(a, b) == pytest.approx(-1.0)

    @pytest.mark.asyncio
    async def test_cosine_similarity_zero_vector(self, relevance_filter):
        """Test cosine similarity with zero vectors."""
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])

        # Should return 0.0 for zero vector
        assert relevance_filter._cosine_similarity(a, b) == 0.0
        assert relevance_filter._cosine_similarity(b, a) == 0.0
        assert relevance_filter._cosine_similarity(b, b) == 0.0

    def test_get_cache_stats(self, relevance_filter):
        """Test cache statistics retrieval."""
        stats = relevance_filter.get_cache_stats()

        assert "query_cache_size" in stats
        assert stats["query_cache_size"] == 0

        # Add to cache
        relevance_filter._query_embedding_cache["query1"] = np.array([1.0, 0.0])
        relevance_filter._query_embedding_cache["query2"] = np.array([0.0, 1.0])

        stats = relevance_filter.get_cache_stats()
        assert stats["query_cache_size"] == 2

    @pytest.mark.asyncio
    async def test_filter_mixed_relevance_papers(
        self, relevance_filter, mock_embedding_service
    ):
        """Test filtering a mix of relevant and irrelevant papers."""
        papers = [
            PaperMetadata(
                paper_id=f"p{i}",
                title=f"Paper {i}",
                url=f"https://example.com/{i}",
            )
            for i in range(5)
        ]

        query_embedding = np.array([1.0, 0.0, 0.0])
        # Papers 0,1,2 relevant (>0.3), 3,4 irrelevant (<0.3)
        paper_embeddings = [
            np.array([0.9, 0.1, 0.0]),  # sim ~0.9
            np.array([0.8, 0.6, 0.0]),  # sim ~0.8
            np.array([0.5, 0.5, 0.0]),  # sim ~0.5
            np.array([0.1, 0.9, 0.0]),  # sim ~0.1
            np.array([0.0, 1.0, 0.0]),  # sim ~0.0
        ]

        async def mock_get_embedding(paper, use_cache=True):
            if hasattr(paper, "paper_id"):
                if paper.paper_id.startswith("query:"):
                    return query_embedding
                idx = int(paper.paper_id[1:])
                return paper_embeddings[idx]
            return np.zeros(3)

        mock_embedding_service.get_embedding.side_effect = mock_get_embedding

        result = await relevance_filter.filter_papers(papers, "query")

        # Should have 3 papers (threshold 0.3)
        assert len(result) == 3
        assert all(p.relevance_score >= 0.3 for p in result)
        assert {p.paper_id for p in result} == {"p0", "p1", "p2"}

    @pytest.mark.asyncio
    async def test_filter_papers_uses_cache_parameter(
        self, relevance_filter, mock_embedding_service, sample_papers
    ):
        """Test that embedding service is called with use_cache=True."""
        query_embedding = np.array([1.0, 0.0, 0.0])
        paper_embedding = np.array([0.9, 0.1, 0.0])

        async def mock_get_embedding(paper, use_cache=True):
            # Verify use_cache is True
            assert use_cache is True
            if hasattr(paper, "paper_id") and paper.paper_id.startswith("query:"):
                return query_embedding
            return paper_embedding

        mock_embedding_service.get_embedding.side_effect = mock_get_embedding

        await relevance_filter.filter_papers([sample_papers[0]], "query")

        # Should have been called at least twice (query + paper)
        assert mock_embedding_service.get_embedding.call_count >= 2
