"""Unit tests for SimilaritySearcher."""

from typing import Optional
from unittest.mock import AsyncMock, Mock

import numpy as np
import pytest

from src.models.feedback import FeedbackRating, SimilarPaper
from src.services.embeddings.similarity_searcher import SimilaritySearcher


class MockPaper:
    """Mock paper for testing."""

    def __init__(self, paper_id: str, title: str, abstract: Optional[str] = None):
        self.paper_id = paper_id
        self.title = title
        self.abstract = abstract


@pytest.fixture
def mock_embedding_service():
    """Create mock embedding service."""
    service = Mock()
    service.EMBEDDING_DIM = 768
    service.get_embedding = AsyncMock(
        return_value=np.random.randn(768).astype(np.float32)
    )
    service.search_similar = AsyncMock(
        return_value=[
            ("similar-paper-1", 0.9),
            ("similar-paper-2", 0.8),
            ("similar-paper-3", 0.7),
        ]
    )
    return service


@pytest.fixture
def mock_registry():
    """Create mock registry service."""
    registry = Mock()

    async def mock_resolve(paper_id):
        if paper_id.startswith("similar"):
            entry = Mock()
            entry.title = f"Title for {paper_id}"
            return entry
        return None

    registry.resolve_identity = AsyncMock(side_effect=mock_resolve)
    return registry


@pytest.fixture
def searcher(mock_embedding_service):
    """Create SimilaritySearcher with mock services."""
    return SimilaritySearcher(embedding_service=mock_embedding_service)


@pytest.fixture
def searcher_with_registry(mock_embedding_service, mock_registry):
    """Create SimilaritySearcher with mock services including registry."""
    return SimilaritySearcher(
        embedding_service=mock_embedding_service,
        registry_service=mock_registry,
    )


@pytest.fixture
def sample_paper():
    """Create sample paper."""
    return MockPaper(
        paper_id="query-paper",
        title="Query Paper Title",
        abstract="Query paper abstract.",
    )


class TestSimilaritySearcherInit:
    """Tests for SimilaritySearcher initialization."""

    def test_init_with_embedding_service(self, mock_embedding_service):
        """Test initialization with embedding service only."""
        searcher = SimilaritySearcher(embedding_service=mock_embedding_service)
        assert searcher.embedding_service == mock_embedding_service
        assert searcher.registry_service is None

    def test_init_with_registry(self, mock_embedding_service, mock_registry):
        """Test initialization with registry."""
        searcher = SimilaritySearcher(
            embedding_service=mock_embedding_service,
            registry_service=mock_registry,
        )
        assert searcher.registry_service == mock_registry


class TestSimilaritySearcherFindSimilar:
    """Tests for find_similar method."""

    @pytest.mark.asyncio
    async def test_find_similar_basic(self, searcher, sample_paper):
        """Test basic similarity search."""
        results = await searcher.find_similar(sample_paper)

        assert len(results) == 3
        assert all(isinstance(r, SimilarPaper) for r in results)

    @pytest.mark.asyncio
    async def test_find_similar_scores_ordered(self, searcher, sample_paper):
        """Test that results are ordered by score."""
        results = await searcher.find_similar(sample_paper)

        scores = [r.similarity_score for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_find_similar_respects_top_k(
        self, searcher, sample_paper, mock_embedding_service
    ):
        """Test that top_k is respected."""
        await searcher.find_similar(sample_paper, top_k=5)

        mock_embedding_service.search_similar.assert_called_once()
        call_args = mock_embedding_service.search_similar.call_args
        assert call_args[1]["top_k"] == 5

    @pytest.mark.asyncio
    async def test_find_similar_excludes_self(
        self, searcher, sample_paper, mock_embedding_service
    ):
        """Test that query paper is excluded."""
        await searcher.find_similar(sample_paper, exclude_self=True)

        call_args = mock_embedding_service.search_similar.call_args
        assert sample_paper.paper_id in call_args[1]["exclude_ids"]

    @pytest.mark.asyncio
    async def test_find_similar_with_registry(
        self, searcher_with_registry, sample_paper
    ):
        """Test similarity search with registry lookup."""
        results = await searcher_with_registry.find_similar(sample_paper)

        # Should have titles from registry
        assert results[0].title == "Title for similar-paper-1"
        assert results[0].previously_discovered is True

    @pytest.mark.asyncio
    async def test_find_similar_with_reasons(self, searcher, sample_paper):
        """Test similarity search with user reasons."""
        results = await searcher.find_similar(
            sample_paper,
            include_reasons="I like the methodology and findings",
        )

        # Should have matching aspects from reasons
        # (similar_methodology, similar_findings)
        all_aspects = [aspect for r in results for aspect in r.matching_aspects]
        assert any("methodology" in aspect for aspect in all_aspects)


class TestSimilaritySearcherMatchingAspects:
    """Tests for _determine_matching_aspects method."""

    def test_matching_aspects_high_score(self, searcher):
        """Test aspects for high similarity score."""
        aspects = searcher._determine_matching_aspects(0.95)
        assert "highly_related" in aspects
        assert "similar_methodology" in aspects

    def test_matching_aspects_medium_score(self, searcher):
        """Test aspects for medium similarity score."""
        aspects = searcher._determine_matching_aspects(0.75)
        assert "related" in aspects
        assert "similar_topic" in aspects

    def test_matching_aspects_low_score(self, searcher):
        """Test aspects for low similarity score."""
        aspects = searcher._determine_matching_aspects(0.55)
        assert "somewhat_related" in aspects

    def test_matching_aspects_with_reasons(self, searcher):
        """Test aspects include parsed reasons."""
        aspects = searcher._determine_matching_aspects(
            0.8, "Great methodology and applications"
        )
        assert "similar_methodology" in aspects
        assert "similar_applications" in aspects


class TestSimilaritySearcherFindSimilarToLiked:
    """Tests for find_similar_to_liked method."""

    @pytest.fixture
    def mock_feedback_service(self):
        """Create mock feedback service."""
        service = Mock()
        service.get_paper_ids_by_rating = AsyncMock(return_value=["liked-1", "liked-2"])
        return service

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_no_liked(
        self, searcher, mock_feedback_service
    ):
        """Test when no liked papers exist."""
        mock_feedback_service.get_paper_ids_by_rating = AsyncMock(return_value=[])

        results = await searcher.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_basic(
        self, searcher_with_registry, mock_feedback_service
    ):
        """Test finding papers similar to liked papers."""
        results = await searcher_with_registry.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
            top_k=5,
        )

        # Should aggregate across liked papers
        assert isinstance(results, list)
        mock_feedback_service.get_paper_ids_by_rating.assert_called_once_with(
            FeedbackRating.THUMBS_UP, "test-topic"
        )

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_excludes_liked(
        self, searcher, mock_feedback_service, mock_embedding_service
    ):
        """Test that liked papers are excluded from results."""
        # Return one of the liked papers in search results
        mock_embedding_service.search_similar = AsyncMock(
            return_value=[
                ("liked-1", 0.95),  # This should be excluded
                ("new-paper-1", 0.9),
                ("new-paper-2", 0.8),
            ]
        )

        results = await searcher.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
        )

        # Should not include liked papers
        result_ids = [r.paper_id for r in results]
        assert "liked-1" not in result_ids


class TestSimilaritySearcherComputeSimilarity:
    """Tests for compute_paper_similarity method."""

    @pytest.mark.asyncio
    async def test_compute_similarity(self, searcher):
        """Test computing similarity between two papers."""
        paper1 = MockPaper("paper-1", "Title 1")
        paper2 = MockPaper("paper-2", "Title 2")

        similarity = await searcher.compute_paper_similarity(paper1, paper2)

        assert isinstance(similarity, float)
        assert 0.0 <= similarity <= 1.0

    @pytest.mark.asyncio
    async def test_compute_similarity_identical(self, searcher, mock_embedding_service):
        """Test similarity for identical embeddings."""
        # Return identical embeddings
        embedding = np.ones(768).astype(np.float32)
        mock_embedding_service.get_embedding = AsyncMock(return_value=embedding)

        paper1 = MockPaper("paper-1", "Title")
        paper2 = MockPaper("paper-2", "Title")

        similarity = await searcher.compute_paper_similarity(paper1, paper2)

        # Should be 1.0 for identical embeddings
        assert similarity == 1.0

    @pytest.mark.asyncio
    async def test_compute_similarity_zero_vector(
        self, searcher, mock_embedding_service
    ):
        """Test similarity with zero vector."""
        mock_embedding_service.get_embedding = AsyncMock(
            return_value=np.zeros(768).astype(np.float32)
        )

        paper1 = MockPaper("paper-1", "Title 1")
        paper2 = MockPaper("paper-2", "Title 2")

        similarity = await searcher.compute_paper_similarity(paper1, paper2)

        # Should handle zero vectors gracefully
        assert similarity == 0.0


class TestSimilaritySearcherRegistryExceptions:
    """Tests for registry exception handling."""

    @pytest.mark.asyncio
    async def test_find_similar_registry_exception(self, mock_embedding_service):
        """Test find_similar handles registry exceptions."""
        mock_registry = Mock()
        mock_registry.resolve_identity = AsyncMock(
            side_effect=Exception("Registry error")
        )

        searcher = SimilaritySearcher(
            embedding_service=mock_embedding_service,
            registry_service=mock_registry,
        )

        paper = MockPaper("query-paper", "Query Title")
        results = await searcher.find_similar(paper)

        # Should still return results despite registry error
        assert len(results) == 3
        # Title should fallback to paper_id
        assert results[0].title == "similar-paper-1"

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_registry_exception(
        self, mock_embedding_service
    ):
        """Test find_similar_to_liked handles registry exceptions."""
        mock_registry = Mock()
        mock_registry.resolve_identity = AsyncMock(
            side_effect=Exception("Registry error")
        )

        mock_feedback_service = Mock()
        mock_feedback_service.get_paper_ids_by_rating = AsyncMock(
            return_value=["liked-1"]
        )

        searcher = SimilaritySearcher(
            embedding_service=mock_embedding_service,
            registry_service=mock_registry,
        )

        results = await searcher.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
        )

        # Should still work with minimal paper objects
        assert isinstance(results, list)


class TestSimilaritySearcherFindSimilarToLikedEdgeCases:
    """Tests for find_similar_to_liked edge cases."""

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_aggregates_scores(
        self, mock_embedding_service
    ):
        """Test that scores are aggregated across liked papers."""
        # Return different results for different queries
        call_count = [0]

        async def mock_search(embedding, top_k=20, exclude_ids=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return [
                    ("common-paper", 0.9),
                    ("unique-1", 0.8),
                ]
            else:
                return [
                    ("common-paper", 0.85),
                    ("unique-2", 0.7),
                ]

        mock_embedding_service.search_similar = AsyncMock(side_effect=mock_search)

        mock_feedback_service = Mock()
        mock_feedback_service.get_paper_ids_by_rating = AsyncMock(
            return_value=["liked-1", "liked-2"]
        )

        searcher = SimilaritySearcher(embedding_service=mock_embedding_service)

        results = await searcher.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
            top_k=10,
        )

        # common-paper should have aggregated score
        result_dict = {r.paper_id: r.similarity_score for r in results}
        assert "common-paper" in result_dict

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_with_registry_success(
        self, mock_embedding_service, mock_registry
    ):
        """Test find_similar_to_liked with successful registry lookups."""
        mock_feedback_service = Mock()
        mock_feedback_service.get_paper_ids_by_rating = AsyncMock(
            return_value=["liked-1"]
        )

        # Return paper with title
        async def mock_resolve(paper_id):
            entry = Mock()
            entry.title = f"Title for {paper_id}"
            return entry

        mock_registry.resolve_identity = AsyncMock(side_effect=mock_resolve)

        searcher = SimilaritySearcher(
            embedding_service=mock_embedding_service,
            registry_service=mock_registry,
        )

        results = await searcher.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
        )

        # Results should have titles from registry
        assert all(r.title.startswith("Title for") for r in results)

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_no_aggregate_results(
        self, mock_embedding_service
    ):
        """Test find_similar_to_liked when no results after filtering."""
        # Return only liked papers in search results
        mock_embedding_service.search_similar = AsyncMock(
            return_value=[
                ("liked-1", 0.95),  # This will be filtered out
            ]
        )

        mock_feedback_service = Mock()
        mock_feedback_service.get_paper_ids_by_rating = AsyncMock(
            return_value=["liked-1"]
        )

        searcher = SimilaritySearcher(embedding_service=mock_embedding_service)

        results = await searcher.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
        )

        # All results are liked papers, so should be empty
        assert results == []


class TestSimilaritySearcherMatchingAspectsEdgeCases:
    """Tests for matching aspects edge cases."""

    def test_matching_aspects_very_high_score(self, searcher):
        """Test aspects for very high similarity score."""
        aspects = searcher._determine_matching_aspects(0.99)
        assert "highly_related" in aspects
        assert "similar_methodology" in aspects
        assert "similar_topic" in aspects
        assert "related_field" in aspects

    def test_matching_aspects_boundary_scores(self, searcher):
        """Test aspects at exact boundary scores."""
        # At exactly 0.9
        aspects_90 = searcher._determine_matching_aspects(0.9)
        assert "highly_related" in aspects_90

        # Just below 0.9
        aspects_89 = searcher._determine_matching_aspects(0.89)
        assert "highly_related" not in aspects_89
        assert "related" in aspects_89

        # At exactly 0.7
        aspects_70 = searcher._determine_matching_aspects(0.7)
        assert "related" in aspects_70

        # Just below 0.5
        aspects_49 = searcher._determine_matching_aspects(0.49)
        assert "somewhat_related" not in aspects_49

    def test_matching_aspects_multiple_keywords(self, searcher):
        """Test aspects with multiple keywords in reasons."""
        aspects = searcher._determine_matching_aspects(
            0.85, "Great methodology and application with similar topic and findings"
        )
        assert "similar_methodology" in aspects
        assert "similar_applications" in aspects
        assert "similar_topic" in aspects
        assert "similar_findings" in aspects

    def test_matching_aspects_domain_keyword(self, searcher):
        """Test domain keyword mapping."""
        aspects = searcher._determine_matching_aspects(
            0.7, "Same domain as my research"
        )
        assert "same_domain" in aspects


class TestSimilaritySearcherRegistryReturnsNone:
    """Tests for registry returning None (paper not found)."""

    @pytest.mark.asyncio
    async def test_find_similar_registry_returns_none(self, mock_embedding_service):
        """Test find_similar when registry returns None for some papers."""
        # Registry returns None for papers not starting with "known"
        mock_registry = Mock()

        async def mock_resolve(paper_id):
            if paper_id.startswith("known"):
                entry = Mock()
                entry.title = f"Title for {paper_id}"
                return entry
            return None  # Return None for unknown papers

        mock_registry.resolve_identity = AsyncMock(side_effect=mock_resolve)

        # Search returns papers that won't be found in registry
        mock_embedding_service.search_similar = AsyncMock(
            return_value=[
                ("unknown-paper-1", 0.9),
                ("unknown-paper-2", 0.8),
            ]
        )

        searcher = SimilaritySearcher(
            embedding_service=mock_embedding_service,
            registry_service=mock_registry,
        )

        paper = MockPaper("query-paper", "Query Title")
        results = await searcher.find_similar(paper)

        # Should use paper_id as fallback title when entry is None
        assert len(results) == 2
        assert results[0].title == "unknown-paper-1"  # Fallback to paper_id
        assert results[0].previously_discovered is False

    @pytest.mark.asyncio
    async def test_find_similar_to_liked_registry_returns_none_for_results(
        self, mock_embedding_service
    ):
        """Test find_similar_to_liked when registry returns None for result papers."""
        mock_registry = Mock()

        async def mock_resolve(paper_id):
            # Return entry for liked papers but None for search results
            if paper_id == "liked-1":
                entry = Mock()
                entry.title = "Liked Paper"
                entry.abstract = "Abstract"
                entry.paper_id = "liked-1"
                return entry
            return None  # Return None for result papers

        mock_registry.resolve_identity = AsyncMock(side_effect=mock_resolve)

        mock_feedback_service = Mock()
        mock_feedback_service.get_paper_ids_by_rating = AsyncMock(
            return_value=["liked-1"]
        )

        # Search returns papers not in registry
        mock_embedding_service.search_similar = AsyncMock(
            return_value=[
                ("unknown-result-1", 0.85),
                ("unknown-result-2", 0.75),
            ]
        )

        searcher = SimilaritySearcher(
            embedding_service=mock_embedding_service,
            registry_service=mock_registry,
        )

        results = await searcher.find_similar_to_liked(
            topic_slug="test-topic",
            feedback_service=mock_feedback_service,
        )

        # Results should use paper_id as fallback title
        assert len(results) == 2
        assert results[0].title == "unknown-result-1"
        assert results[0].previously_discovered is False
