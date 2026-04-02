"""Data models for Phase 7.3 Human Feedback Loop.

This module defines Pydantic models for feedback collection, storage,
analytics, and similarity search results.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class FeedbackRating(str, Enum):
    """Rating options for paper feedback."""

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    NEUTRAL = "neutral"


class FeedbackReason(str, Enum):
    """Structured reasons for paper feedback."""

    METHODOLOGY = "methodology"
    FINDINGS = "findings"
    APPLICATIONS = "applications"
    WRITING_QUALITY = "writing_quality"
    RELEVANCE = "relevance"
    NOVELTY = "novelty"


class FeedbackEntry(BaseModel):
    """A single feedback entry for a paper.

    Attributes:
        id: Unique identifier for this feedback entry.
        paper_id: The paper's registry ID being rated.
        topic_slug: Optional topic context for the feedback.
        rating: The rating given (thumbs_up, thumbs_down, neutral).
        reasons: Optional list of structured reasons for the rating.
        free_text: Optional free-form explanation.
        timestamp: When the feedback was submitted.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    paper_id: str = Field(..., min_length=1, description="Paper ID from registry")
    topic_slug: Optional[str] = Field(
        default=None, description="Topic context for the feedback"
    )
    rating: FeedbackRating = Field(..., description="Rating value")
    reasons: List[FeedbackReason] = Field(
        default_factory=list, description="Structured reasons for rating"
    )
    free_text: Optional[str] = Field(
        default=None, max_length=2000, description="Free-form explanation"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When feedback was submitted",
    )

    model_config = ConfigDict(
        use_enum_values=True,
        str_strip_whitespace=True,
        validate_default=True,
    )


class FeedbackFilters(BaseModel):
    """Filters for querying feedback entries.

    Attributes:
        topic_slug: Filter by topic.
        rating: Filter by rating value.
        reasons: Filter by having any of these reasons.
        start_date: Filter by timestamp >= start_date.
        end_date: Filter by timestamp <= end_date.
        paper_ids: Filter by specific paper IDs.
    """

    topic_slug: Optional[str] = None
    rating: Optional[FeedbackRating] = None
    reasons: Optional[List[FeedbackReason]] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    paper_ids: Optional[List[str]] = None

    model_config = ConfigDict(use_enum_values=True)


class TopicAnalytics(BaseModel):
    """Analytics for a specific topic.

    Attributes:
        topic_slug: The topic identifier.
        total: Total feedback count for this topic.
        thumbs_up: Count of thumbs_up ratings.
        thumbs_down: Count of thumbs_down ratings.
        neutral: Count of neutral ratings.
        common_reasons: Most common reasons selected.
    """

    topic_slug: str
    total: int = 0
    thumbs_up: int = 0
    thumbs_down: int = 0
    neutral: int = 0
    common_reasons: List[str] = Field(default_factory=list)

    @property
    def positive_ratio(self) -> float:
        """Calculate ratio of positive feedback."""
        if self.total == 0:
            return 0.0
        return self.thumbs_up / self.total


class FeedbackAnalytics(BaseModel):
    """Comprehensive feedback analytics report.

    Attributes:
        total_ratings: Total feedback entries across all topics.
        rating_distribution: Count by rating type.
        top_reasons: Most common reasons with counts.
        topic_breakdown: Analytics per topic.
        trending_themes: Emerging themes from recent feedback.
        recommendation_accuracy: Model prediction accuracy if available.
        generated_at: When this report was generated.
    """

    total_ratings: int = 0
    rating_distribution: Dict[str, int] = Field(
        default_factory=lambda: {"thumbs_up": 0, "thumbs_down": 0, "neutral": 0}
    )
    top_reasons: List[tuple] = Field(
        default_factory=list, description="List of (reason, count) tuples"
    )
    topic_breakdown: Dict[str, TopicAnalytics] = Field(default_factory=dict)
    trending_themes: List[str] = Field(default_factory=list)
    recommendation_accuracy: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Model prediction accuracy"
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SimilarPaper(BaseModel):
    """A paper found through similarity search.

    Attributes:
        paper_id: The paper's registry ID.
        title: Paper title.
        similarity_score: Cosine similarity score (0-1).
        matching_aspects: Aspects that contributed to similarity.
        previously_discovered: Whether paper was already in registry.
    """

    paper_id: str
    title: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)
    matching_aspects: List[str] = Field(default_factory=list)
    previously_discovered: bool = False

    model_config = ConfigDict(str_strip_whitespace=True)


class QueryRefinement(BaseModel):
    """A suggested query refinement based on feedback patterns.

    Attributes:
        original_query: The current topic query.
        refined_query: The suggested refined query.
        rationale: Explanation for the refinement.
        confidence: Confidence score for this suggestion.
        themes_addressed: Themes from feedback that informed this.
        status: Current status (pending, accepted, rejected).
        created_at: When this refinement was suggested.
        decided_at: When user accepted/rejected (if applicable).
    """

    original_query: str
    refined_query: str
    rationale: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    themes_addressed: List[str] = Field(default_factory=list)
    status: str = Field(default="pending", pattern="^(pending|accepted|rejected)$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decided_at: Optional[datetime] = None

    model_config = ConfigDict(str_strip_whitespace=True)


class EmbeddingConfig(BaseModel):
    """Configuration for embedding service.

    Attributes:
        enabled: Whether embeddings are enabled.
        model: The embedding model name.
        cache_dir: Directory for embedding cache.
        vector_db: Vector database backend (faiss or chroma).
        fallback: Fallback method when model unavailable.
        batch_size: Batch size for embedding computation.
    """

    enabled: bool = True
    model: str = "allenai/specter2"
    cache_dir: str = ".cache/embeddings"
    vector_db: str = Field(default="faiss", pattern="^(faiss|chroma)$")
    fallback: str = Field(default="tfidf", pattern="^(tfidf|none)$")
    batch_size: int = Field(default=32, ge=1, le=256)


class PreferenceLearningConfig(BaseModel):
    """Configuration for preference learning.

    Attributes:
        enabled: Whether preference learning is enabled.
        algorithm: Learning algorithm to use.
        min_feedback_for_training: Minimum feedback entries before training.
        exploration_rate: Thompson Sampling exploration rate.
        update_frequency: How often to update the model.
        blend_weight: Weight of preference vs base score (0-1).
    """

    enabled: bool = True
    algorithm: str = Field(
        default="contextual_bandit", pattern="^(contextual_bandit|simple_average)$"
    )
    min_feedback_for_training: int = Field(default=20, ge=1, le=1000)
    exploration_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    update_frequency: str = Field(
        default="daily", pattern="^(realtime|hourly|daily|weekly)$"
    )
    blend_weight: float = Field(default=0.3, ge=0.0, le=1.0)


class HumanFeedbackConfig(BaseModel):
    """Configuration for the human feedback system.

    Attributes:
        enabled: Whether human feedback is enabled.
        storage_path: Path for feedback storage file.
        archive_threshold: Number of entries before archiving.
    """

    enabled: bool = True
    storage_path: str = "data/feedback.json"
    archive_threshold: int = Field(default=10000, ge=100)


class FeedbackUIConfig(BaseModel):
    """Configuration for feedback UI options.

    Attributes:
        cli_enabled: Whether CLI feedback commands are enabled.
        gradio_enabled: Whether Gradio web UI is enabled.
        gradio_port: Port for Gradio server.
    """

    cli_enabled: bool = True
    gradio_enabled: bool = False
    gradio_port: int = Field(default=7860, ge=1024, le=65535)


class QueryRefinementConfig(BaseModel):
    """Configuration for query refinement.

    Attributes:
        enabled: Whether query refinement is enabled.
        min_positive_feedback: Minimum positive feedback before suggesting.
        auto_apply: Whether to auto-apply refinements.
        cooldown_days: Days before re-suggesting rejected refinement.
    """

    enabled: bool = True
    min_positive_feedback: int = Field(default=5, ge=1, le=100)
    auto_apply: bool = False
    cooldown_days: int = Field(default=30, ge=1, le=365)
