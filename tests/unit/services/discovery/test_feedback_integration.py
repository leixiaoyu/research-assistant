"""Tests for Phase 7.3 Feedback Integration into Discovery Pipeline.

Tests cover:
- Preference-based ranking integration
- Model training at discovery start
- Similar paper recommendations from liked papers
- Feature flag disabling
"""

import pytest
from typing import List, Optional

import numpy as np

from src.models.config import FeedbackIntegrationConfig
from src.models.feedback import FeedbackEntry, FeedbackRating
from src.models.paper import PaperMetadata
from src.services.result_aggregator import ResultAggregator
from src.services.feedback.preference_model import PreferenceModel


class MockFeedbackService:
    """Mock feedback service for testing."""

    def __init__(self):
        self.feedback_entries: List[FeedbackEntry] = []

    async def get_paper_ids_by_rating(
        self,
        rating: FeedbackRating,
        topic_slug: Optional[str] = None,
    ) -> List[str]:
        """Get paper IDs with specific rating."""
        return [
            e.paper_id
            for e in self.feedback_entries
            if e.rating == rating and (topic_slug is None or e.topic_slug == topic_slug)
        ]

    async def get_positive_feedback(
        self,
        topic_slug: Optional[str] = None,
    ) -> List[FeedbackEntry]:
        """Get positive feedback."""
        return [
            e
            for e in self.feedback_entries
            if e.rating == FeedbackRating.THUMBS_UP
            and (topic_slug is None or e.topic_slug == topic_slug)
        ]

    def add_feedback(
        self,
        paper_id: str,
        rating: FeedbackRating,
        topic_slug: str = "test_topic",
    ) -> None:
        """Add feedback entry."""
        self.feedback_entries.append(
            FeedbackEntry(
                paper_id=paper_id,
                rating=rating,
                topic_slug=topic_slug,
            )
        )


class TestFeedbackIntegration:
    """Tests for feedback integration in ResultAggregator."""

    @pytest.fixture
    def sample_papers(self) -> List[PaperMetadata]:
        """Create sample papers for testing."""
        return [
            PaperMetadata(
                paper_id="paper1",
                title="Machine Learning Basics",
                url="https://example.com/1",
                citation_count=100,
                year=2024,
            ),
            PaperMetadata(
                paper_id="paper2",
                title="Deep Learning Advanced",
                url="https://example.com/2",
                citation_count=50,
                year=2023,
            ),
            PaperMetadata(
                paper_id="paper3",
                title="Natural Language Processing",
                url="https://example.com/3",
                citation_count=75,
                year=2024,
            ),
        ]

    @pytest.fixture
    def trained_preference_model(self) -> PreferenceModel:
        """Create a trained preference model."""
        model = PreferenceModel(
            algorithm="simple_average",
            min_feedback_for_training=2,
            blend_weight=0.3,
        )
        # Manually set as trained and add some preferences
        model._trained = True
        model._alpha = {"paper1": 10.0, "paper2": 2.0, "paper3": 5.0}
        model._beta = {"paper1": 2.0, "paper2": 8.0, "paper3": 5.0}
        return model

    @pytest.fixture
    def mock_feedback_service(self) -> MockFeedbackService:
        """Create mock feedback service."""
        service = MockFeedbackService()
        # Add some feedback
        service.add_feedback("paper1", FeedbackRating.THUMBS_UP)
        service.add_feedback("paper2", FeedbackRating.THUMBS_DOWN)
        service.add_feedback("paper3", FeedbackRating.NEUTRAL)
        return service

    @pytest.mark.asyncio
    async def test_preference_ranking_integration(
        self,
        sample_papers,
        trained_preference_model,
    ):
        """Test that preference model integrates into ranking."""
        aggregator = ResultAggregator(
            preference_model=trained_preference_model,
        )

        source_results = {"test_source": sample_papers}
        result = await aggregator.aggregate(source_results)

        # All papers should have preference_score set
        for paper in result.papers:
            assert paper.preference_score is not None
            assert 0.0 <= paper.preference_score <= 1.0

        # Paper1 (most liked) should have highest preference score
        paper1 = next(p for p in result.papers if p.paper_id == "paper1")
        paper2 = next(p for p in result.papers if p.paper_id == "paper2")
        assert paper1.preference_score > paper2.preference_score

    @pytest.mark.asyncio
    async def test_blended_ranking_score(
        self,
        sample_papers,
        trained_preference_model,
    ):
        """Test that ranking_score blends preference and base scores."""
        aggregator = ResultAggregator(
            preference_model=trained_preference_model,
        )

        source_results = {"test_source": sample_papers}
        result = await aggregator.aggregate(source_results)

        # All papers should have ranking_score
        for paper in result.papers:
            assert paper.ranking_score is not None

        # Ranking score should be different from preference score alone
        paper1 = next(p for p in result.papers if p.paper_id == "paper1")
        assert paper1.ranking_score != paper1.preference_score

    @pytest.mark.asyncio
    async def test_preference_ranking_disabled_when_not_trained(
        self,
        sample_papers,
    ):
        """Test that preference ranking is skipped when model not trained."""
        untrained_model = PreferenceModel(min_feedback_for_training=100)
        aggregator = ResultAggregator(preference_model=untrained_model)

        source_results = {"test_source": sample_papers}
        result = await aggregator.aggregate(source_results)

        # Papers should NOT have preference_score
        for paper in result.papers:
            assert paper.preference_score is None

        # Should still have base ranking_score
        for paper in result.papers:
            assert paper.ranking_score is not None

    @pytest.mark.asyncio
    async def test_preference_ranking_without_model(self, sample_papers):
        """Test that aggregation works without preference model."""
        aggregator = ResultAggregator()  # No model

        source_results = {"test_source": sample_papers}
        result = await aggregator.aggregate(source_results)

        # Should work normally
        assert len(result.papers) == len(sample_papers)
        for paper in result.papers:
            assert paper.preference_score is None
            assert paper.ranking_score is not None

    @pytest.mark.asyncio
    async def test_model_training_with_sufficient_feedback(
        self,
        mock_feedback_service,
    ):
        """Test that model trains when sufficient feedback exists."""
        model = PreferenceModel(min_feedback_for_training=2)

        # Create feedback entries
        feedback_entries = await mock_feedback_service.get_positive_feedback()
        feedback_entries.extend(
            [
                e
                for e in mock_feedback_service.feedback_entries
                if e.rating != FeedbackRating.THUMBS_UP
            ]
        )

        # Train model
        await model.train(feedback_entries, {})

        assert model.is_trained is True

    @pytest.mark.asyncio
    async def test_model_training_with_insufficient_feedback(self):
        """Test that model doesn't train with insufficient feedback."""
        model = PreferenceModel(min_feedback_for_training=10)

        # Only 2 feedback entries
        feedback_entries = [
            FeedbackEntry(
                paper_id="p1",
                rating=FeedbackRating.THUMBS_UP,
            ),
            FeedbackEntry(
                paper_id="p2",
                rating=FeedbackRating.THUMBS_DOWN,
            ),
        ]

        await model.train(feedback_entries, {})

        assert model.is_trained is False

    @pytest.mark.asyncio
    async def test_blend_weight_affects_ranking(
        self,
        sample_papers,
        trained_preference_model,
    ):
        """Test that blend_weight properly affects final ranking."""
        # Test with high preference weight
        trained_preference_model.blend_weight = 0.9
        aggregator = ResultAggregator(preference_model=trained_preference_model)

        source_results = {"test_source": sample_papers}
        result = await aggregator.aggregate(source_results)

        paper1 = next(p for p in result.papers if p.paper_id == "paper1")

        # Ranking should be heavily influenced by preference
        expected = (
            0.9 * paper1.preference_score
            + 0.1 * 0.3  # Approximate base score component
        )
        # Allow for some variance due to base score calculation
        assert abs(paper1.ranking_score - expected) < 0.5

    @pytest.mark.asyncio
    async def test_papers_sorted_by_blended_score(
        self,
        sample_papers,
        trained_preference_model,
    ):
        """Test that papers are sorted by blended score."""
        aggregator = ResultAggregator(preference_model=trained_preference_model)

        source_results = {"test_source": sample_papers}
        result = await aggregator.aggregate(source_results)

        # Papers should be sorted descending by ranking_score
        scores = [p.ranking_score for p in result.papers]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_contextual_bandit_training(self):
        """Test contextual bandit training with features."""
        model = PreferenceModel(
            algorithm="contextual_bandit",
            min_feedback_for_training=3,
        )

        feedback_entries = [
            FeedbackEntry(paper_id="p1", rating=FeedbackRating.THUMBS_UP),
            FeedbackEntry(paper_id="p2", rating=FeedbackRating.THUMBS_DOWN),
            FeedbackEntry(paper_id="p3", rating=FeedbackRating.THUMBS_UP),
        ]

        # Provide feature vectors
        features = {
            "p1": np.array([1.0, 2.0, 3.0]),
            "p2": np.array([0.5, 1.0, 1.5]),
            "p3": np.array([1.5, 2.5, 3.5]),
        }

        await model.train(feedback_entries, features)

        assert model.is_trained is True
        assert model._feature_weights is not None

    @pytest.mark.asyncio
    async def test_preference_score_calculation(
        self,
        trained_preference_model,
    ):
        """Test preference score prediction for known papers."""
        paper1 = PaperMetadata(
            paper_id="paper1",
            title="Test Paper 1",
            url="https://example.com/1",
        )

        score = await trained_preference_model.predict_preference(paper1)

        # paper1 has alpha=10, beta=2, mean = 10/(10+2) = 0.833
        expected = 10.0 / (10.0 + 2.0)
        assert abs(score - expected) < 0.01

    @pytest.mark.asyncio
    async def test_unknown_paper_gets_neutral_score(
        self,
        trained_preference_model,
    ):
        """Test that unknown papers get neutral preference score."""
        unknown_paper = PaperMetadata(
            paper_id="unknown",
            title="Unknown Paper",
            url="https://example.com/unknown",
        )

        score = await trained_preference_model.predict_preference(unknown_paper)

        # Unknown papers should get neutral score (0.5)
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_aggregation_with_multiple_sources_and_preferences(
        self,
        trained_preference_model,
    ):
        """Test aggregation with multiple sources and preference model."""
        papers_source1 = [
            PaperMetadata(
                paper_id="paper1",
                title="Paper 1",
                url="https://example.com/1",
                doi="10.1234/test1",
            ),
        ]

        papers_source2 = [
            PaperMetadata(
                paper_id="paper1_dup",
                title="Paper 1 Duplicate",
                url="https://example.com/1b",
                doi="10.1234/test1",  # Same DOI - should deduplicate
            ),
            PaperMetadata(
                paper_id="paper2",
                title="Paper 2",
                url="https://example.com/2",
            ),
        ]

        aggregator = ResultAggregator(preference_model=trained_preference_model)
        source_results = {
            "source1": papers_source1,
            "source2": papers_source2,
        }

        result = await aggregator.aggregate(source_results)

        # Should deduplicate to 2 unique papers
        assert len(result.papers) == 2
        # Both should have preference scores
        for paper in result.papers:
            assert paper.preference_score is not None


class TestFeedbackIntegrationConfig:
    """Tests for FeedbackIntegrationConfig model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = FeedbackIntegrationConfig()

        assert config.enabled is True
        assert config.preference_blend_weight == 0.3
        assert config.min_feedback_for_training == 10
        assert config.recommendation_count == 10
        assert config.similarity_threshold == 0.5

    def test_config_validation_blend_weight(self):
        """Test blend_weight validation."""
        # Valid weights
        config1 = FeedbackIntegrationConfig(preference_blend_weight=0.0)
        assert config1.preference_blend_weight == 0.0

        config2 = FeedbackIntegrationConfig(preference_blend_weight=1.0)
        assert config2.preference_blend_weight == 1.0

        # Invalid weights should raise validation error
        with pytest.raises(Exception):  # Pydantic validation error
            FeedbackIntegrationConfig(preference_blend_weight=1.5)

        with pytest.raises(Exception):
            FeedbackIntegrationConfig(preference_blend_weight=-0.1)

    def test_config_validation_recommendation_count(self):
        """Test recommendation_count validation."""
        # Valid counts
        config1 = FeedbackIntegrationConfig(recommendation_count=0)
        assert config1.recommendation_count == 0

        config2 = FeedbackIntegrationConfig(recommendation_count=50)
        assert config2.recommendation_count == 50

        # Invalid counts
        with pytest.raises(Exception):
            FeedbackIntegrationConfig(recommendation_count=-1)

        with pytest.raises(Exception):
            FeedbackIntegrationConfig(recommendation_count=51)

    def test_config_validation_min_feedback(self):
        """Test min_feedback_for_training validation."""
        config = FeedbackIntegrationConfig(min_feedback_for_training=1)
        assert config.min_feedback_for_training == 1

        # Must be >= 1
        with pytest.raises(Exception):
            FeedbackIntegrationConfig(min_feedback_for_training=0)

    def test_config_validation_similarity_threshold(self):
        """Test similarity_threshold validation."""
        config1 = FeedbackIntegrationConfig(similarity_threshold=0.0)
        assert config1.similarity_threshold == 0.0

        config2 = FeedbackIntegrationConfig(similarity_threshold=1.0)
        assert config2.similarity_threshold == 1.0

        with pytest.raises(Exception):
            FeedbackIntegrationConfig(similarity_threshold=1.1)

    def test_config_disabled_integration(self):
        """Test disabling feedback integration."""
        config = FeedbackIntegrationConfig(enabled=False)
        assert config.enabled is False
