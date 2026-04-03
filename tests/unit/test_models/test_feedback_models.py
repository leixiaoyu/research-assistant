"""Unit tests for Phase 7.3 feedback data models."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.models.feedback import (
    EmbeddingConfig,
    FeedbackAnalytics,
    FeedbackEntry,
    FeedbackFilters,
    FeedbackRating,
    FeedbackReason,
    FeedbackUIConfig,
    HumanFeedbackConfig,
    PreferenceLearningConfig,
    QueryRefinement,
    QueryRefinementConfig,
    SimilarPaper,
    TopicAnalytics,
)


class TestFeedbackRating:
    """Tests for FeedbackRating enum."""

    def test_thumbs_up_value(self):
        """Test thumbs_up enum value."""
        assert FeedbackRating.THUMBS_UP.value == "thumbs_up"

    def test_thumbs_down_value(self):
        """Test thumbs_down enum value."""
        assert FeedbackRating.THUMBS_DOWN.value == "thumbs_down"

    def test_neutral_value(self):
        """Test neutral enum value."""
        assert FeedbackRating.NEUTRAL.value == "neutral"


class TestFeedbackReason:
    """Tests for FeedbackReason enum."""

    def test_all_reason_values(self):
        """Test all reason enum values."""
        assert FeedbackReason.METHODOLOGY.value == "methodology"
        assert FeedbackReason.FINDINGS.value == "findings"
        assert FeedbackReason.APPLICATIONS.value == "applications"
        assert FeedbackReason.WRITING_QUALITY.value == "writing_quality"
        assert FeedbackReason.RELEVANCE.value == "relevance"
        assert FeedbackReason.NOVELTY.value == "novelty"


class TestFeedbackEntry:
    """Tests for FeedbackEntry model."""

    def test_create_minimal_entry(self):
        """Test creating entry with minimal required fields."""
        entry = FeedbackEntry(
            paper_id="arxiv:2401.12345",
            rating=FeedbackRating.THUMBS_UP,
        )
        assert entry.paper_id == "arxiv:2401.12345"
        assert entry.rating == "thumbs_up"
        assert entry.reasons == []
        assert entry.free_text is None
        assert entry.topic_slug is None
        # ID should be valid UUID
        UUID(entry.id)

    def test_create_full_entry(self):
        """Test creating entry with all fields."""
        entry = FeedbackEntry(
            paper_id="arxiv:2401.12345",
            rating=FeedbackRating.THUMBS_UP,
            reasons=[FeedbackReason.METHODOLOGY, FeedbackReason.NOVELTY],
            free_text="Great paper on attention mechanisms",
            topic_slug="attention-transformers",
        )
        assert entry.paper_id == "arxiv:2401.12345"
        assert entry.rating == "thumbs_up"
        assert entry.reasons == ["methodology", "novelty"]
        assert entry.free_text == "Great paper on attention mechanisms"
        assert entry.topic_slug == "attention-transformers"

    def test_entry_with_string_rating(self):
        """Test entry accepts string rating value."""
        entry = FeedbackEntry(
            paper_id="test-123",
            rating="thumbs_down",
        )
        assert entry.rating == "thumbs_down"

    def test_entry_timestamp_default(self):
        """Test entry has default timestamp."""
        before = datetime.now(timezone.utc)
        entry = FeedbackEntry(
            paper_id="test-123",
            rating=FeedbackRating.NEUTRAL,
        )
        after = datetime.now(timezone.utc)
        assert before <= entry.timestamp <= after

    def test_entry_validates_paper_id(self):
        """Test entry rejects empty paper_id."""
        with pytest.raises(ValidationError):
            FeedbackEntry(
                paper_id="",
                rating=FeedbackRating.THUMBS_UP,
            )

    def test_entry_free_text_max_length(self):
        """Test free_text respects max length."""
        long_text = "x" * 2001
        with pytest.raises(ValidationError):
            FeedbackEntry(
                paper_id="test-123",
                rating=FeedbackRating.THUMBS_UP,
                free_text=long_text,
            )

    def test_entry_strips_whitespace(self):
        """Test entry strips whitespace from strings."""
        entry = FeedbackEntry(
            paper_id="  test-123  ",
            rating=FeedbackRating.THUMBS_UP,
            free_text="  some comment  ",
        )
        assert entry.paper_id == "test-123"
        assert entry.free_text == "some comment"

    def test_entry_serialization(self):
        """Test entry serializes to dict correctly."""
        entry = FeedbackEntry(
            paper_id="test-123",
            rating=FeedbackRating.THUMBS_UP,
            reasons=[FeedbackReason.METHODOLOGY],
        )
        data = entry.model_dump()
        assert data["paper_id"] == "test-123"
        assert data["rating"] == "thumbs_up"
        assert data["reasons"] == ["methodology"]


class TestFeedbackFilters:
    """Tests for FeedbackFilters model."""

    def test_empty_filters(self):
        """Test creating filters with no criteria."""
        filters = FeedbackFilters()
        assert filters.topic_slug is None
        assert filters.rating is None
        assert filters.reasons is None

    def test_filters_with_all_criteria(self):
        """Test creating filters with all criteria."""
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 12, 31, tzinfo=timezone.utc)

        filters = FeedbackFilters(
            topic_slug="test-topic",
            rating=FeedbackRating.THUMBS_UP,
            reasons=[FeedbackReason.METHODOLOGY],
            start_date=start,
            end_date=end,
            paper_ids=["paper-1", "paper-2"],
        )

        assert filters.topic_slug == "test-topic"
        assert filters.rating == "thumbs_up"
        assert filters.start_date == start
        assert filters.end_date == end
        assert filters.paper_ids == ["paper-1", "paper-2"]


class TestTopicAnalytics:
    """Tests for TopicAnalytics model."""

    def test_create_topic_analytics(self):
        """Test creating topic analytics."""
        analytics = TopicAnalytics(
            topic_slug="test-topic",
            total=100,
            thumbs_up=60,
            thumbs_down=30,
            neutral=10,
            common_reasons=["methodology", "findings"],
        )
        assert analytics.topic_slug == "test-topic"
        assert analytics.total == 100
        assert analytics.thumbs_up == 60
        assert analytics.thumbs_down == 30
        assert analytics.neutral == 10

    def test_positive_ratio(self):
        """Test positive_ratio calculation."""
        analytics = TopicAnalytics(
            topic_slug="test",
            total=100,
            thumbs_up=60,
            thumbs_down=30,
            neutral=10,
        )
        assert analytics.positive_ratio == 0.6

    def test_positive_ratio_zero_total(self):
        """Test positive_ratio with zero total."""
        analytics = TopicAnalytics(topic_slug="empty")
        assert analytics.positive_ratio == 0.0


class TestFeedbackAnalytics:
    """Tests for FeedbackAnalytics model."""

    def test_empty_analytics(self):
        """Test creating empty analytics."""
        analytics = FeedbackAnalytics()
        assert analytics.total_ratings == 0
        assert analytics.rating_distribution["thumbs_up"] == 0
        assert analytics.top_reasons == []
        assert analytics.topic_breakdown == {}

    def test_full_analytics(self):
        """Test creating full analytics."""
        analytics = FeedbackAnalytics(
            total_ratings=150,
            rating_distribution={"thumbs_up": 100, "thumbs_down": 30, "neutral": 20},
            top_reasons=[("methodology", 50), ("findings", 30)],
            trending_themes=["attention", "transformers"],
            recommendation_accuracy=0.85,
        )
        assert analytics.total_ratings == 150
        assert analytics.rating_distribution["thumbs_up"] == 100
        assert len(analytics.top_reasons) == 2
        assert analytics.recommendation_accuracy == 0.85


class TestSimilarPaper:
    """Tests for SimilarPaper model."""

    def test_create_similar_paper(self):
        """Test creating similar paper result."""
        similar = SimilarPaper(
            paper_id="arxiv:2401.00001",
            title="Similar Paper Title",
            similarity_score=0.85,
            matching_aspects=["methodology", "topic"],
            previously_discovered=True,
        )
        assert similar.paper_id == "arxiv:2401.00001"
        assert similar.similarity_score == 0.85
        assert similar.previously_discovered is True

    def test_similarity_score_bounds(self):
        """Test similarity_score validation."""
        with pytest.raises(ValidationError):
            SimilarPaper(
                paper_id="test",
                title="Test",
                similarity_score=1.5,  # > 1.0
            )

        with pytest.raises(ValidationError):
            SimilarPaper(
                paper_id="test",
                title="Test",
                similarity_score=-0.1,  # < 0.0
            )


class TestQueryRefinement:
    """Tests for QueryRefinement model."""

    def test_create_query_refinement(self):
        """Test creating query refinement."""
        refinement = QueryRefinement(
            original_query="attention mechanisms",
            refined_query="attention mechanisms transformers NLP",
            rationale="Based on positive feedback, adding transformer context",
            confidence=0.85,
            themes_addressed=["transformers", "NLP"],
        )
        assert refinement.original_query == "attention mechanisms"
        assert refinement.refined_query == "attention mechanisms transformers NLP"
        assert refinement.confidence == 0.85
        assert refinement.status == "pending"

    def test_status_validation(self):
        """Test status field validation."""
        # Valid statuses
        for status in ["pending", "accepted", "rejected"]:
            refinement = QueryRefinement(
                original_query="test",
                refined_query="test refined",
                rationale="test",
                confidence=0.5,
                status=status,
            )
            assert refinement.status == status

        # Invalid status
        with pytest.raises(ValidationError):
            QueryRefinement(
                original_query="test",
                refined_query="test refined",
                rationale="test",
                confidence=0.5,
                status="invalid",
            )


class TestEmbeddingConfig:
    """Tests for EmbeddingConfig model."""

    def test_default_config(self):
        """Test default embedding config."""
        config = EmbeddingConfig()
        assert config.enabled is True
        assert config.model == "allenai/specter2"
        assert config.vector_db == "faiss"
        assert config.fallback == "tfidf"
        assert config.batch_size == 32

    def test_custom_config(self):
        """Test custom embedding config."""
        config = EmbeddingConfig(
            enabled=False,
            model="allenai/specter",
            vector_db="chroma",
            batch_size=64,
        )
        assert config.enabled is False
        assert config.model == "allenai/specter"
        assert config.vector_db == "chroma"
        assert config.batch_size == 64

    def test_invalid_vector_db(self):
        """Test invalid vector_db value."""
        with pytest.raises(ValidationError):
            EmbeddingConfig(vector_db="invalid")


class TestPreferenceLearningConfig:
    """Tests for PreferenceLearningConfig model."""

    def test_default_config(self):
        """Test default preference learning config."""
        config = PreferenceLearningConfig()
        assert config.enabled is True
        assert config.algorithm == "contextual_bandit"
        assert config.min_feedback_for_training == 20
        assert config.exploration_rate == 0.1
        assert config.blend_weight == 0.3

    def test_exploration_rate_bounds(self):
        """Test exploration_rate validation."""
        with pytest.raises(ValidationError):
            PreferenceLearningConfig(exploration_rate=1.5)

        with pytest.raises(ValidationError):
            PreferenceLearningConfig(exploration_rate=-0.1)


class TestHumanFeedbackConfig:
    """Tests for HumanFeedbackConfig model."""

    def test_default_config(self):
        """Test default human feedback config."""
        config = HumanFeedbackConfig()
        assert config.enabled is True
        assert config.storage_path == "data/feedback.json"
        assert config.archive_threshold == 10000


class TestFeedbackUIConfig:
    """Tests for FeedbackUIConfig model."""

    def test_default_config(self):
        """Test default UI config."""
        config = FeedbackUIConfig()
        assert config.cli_enabled is True
        assert config.gradio_enabled is False
        assert config.gradio_port == 7860

    def test_port_validation(self):
        """Test port validation."""
        with pytest.raises(ValidationError):
            FeedbackUIConfig(gradio_port=80)  # < 1024

        with pytest.raises(ValidationError):
            FeedbackUIConfig(gradio_port=70000)  # > 65535


class TestQueryRefinementConfig:
    """Tests for QueryRefinementConfig model."""

    def test_default_config(self):
        """Test default query refinement config."""
        config = QueryRefinementConfig()
        assert config.enabled is True
        assert config.min_positive_feedback == 5
        assert config.auto_apply is False
        assert config.cooldown_days == 30
