"""Feedback service for Phase 7.3 Human Feedback Loop.

This module provides the core service for managing user feedback on papers,
including collection, retrieval, and analytics generation.
"""

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional

from src.models.feedback import (
    FeedbackAnalytics,
    FeedbackEntry,
    FeedbackFilters,
    FeedbackRating,
    FeedbackReason,
    TopicAnalytics,
)
from src.services.feedback.storage import FeedbackStorage

logger = logging.getLogger(__name__)


class FeedbackService:
    """Service for managing paper feedback.

    Provides methods for submitting, retrieving, and analyzing
    user feedback on research papers.

    Attributes:
        storage: The feedback storage backend.
        registry_service: Optional registry for paper validation.
    """

    def __init__(
        self,
        storage: FeedbackStorage,
        registry_service: Optional[object] = None,
    ) -> None:
        """Initialize the feedback service.

        Args:
            storage: The feedback storage backend.
            registry_service: Optional RegistryService for paper validation.
        """
        self.storage = storage
        self.registry_service = registry_service

    async def submit_feedback(
        self,
        paper_id: str,
        rating: FeedbackRating,
        reasons: Optional[List[FeedbackReason]] = None,
        free_text: Optional[str] = None,
        topic_slug: Optional[str] = None,
    ) -> FeedbackEntry:
        """Submit feedback for a paper.

        Args:
            paper_id: The paper's registry ID.
            rating: The rating (thumbs_up, thumbs_down, neutral).
            reasons: Optional structured reasons for the rating.
            free_text: Optional free-form explanation.
            topic_slug: Optional topic context.

        Returns:
            The created feedback entry.

        Raises:
            ValueError: If paper_id is empty or invalid.
        """
        if not paper_id or not paper_id.strip():
            raise ValueError("paper_id cannot be empty")

        # Validate paper exists in registry if available
        if self.registry_service is not None:
            try:
                # Try to resolve the paper identity
                if hasattr(self.registry_service, "resolve_identity"):
                    entry = await self.registry_service.resolve_identity(paper_id)
                    if entry is None:
                        logger.warning(
                            f"Paper {paper_id} not found in registry, "
                            "proceeding anyway"
                        )
            except Exception as e:
                logger.warning(f"Registry validation failed: {e}, proceeding anyway")

        # Check for existing feedback
        existing = await self.storage.get_by_paper_id(paper_id)
        if existing:
            # Update existing entry
            entry = FeedbackEntry(
                id=existing.id,
                paper_id=paper_id,
                rating=rating,
                reasons=reasons or [],
                free_text=free_text,
                topic_slug=topic_slug or existing.topic_slug,
                timestamp=datetime.now(timezone.utc),
            )
            logger.info(f"Updating feedback for paper {paper_id}: {rating}")
        else:
            entry = FeedbackEntry(
                paper_id=paper_id,
                rating=rating,
                reasons=reasons or [],
                free_text=free_text,
                topic_slug=topic_slug,
            )
            logger.info(f"New feedback for paper {paper_id}: {rating}")

        await self.storage.save(entry)
        return entry

    async def get_feedback_for_paper(
        self,
        paper_id: str,
    ) -> Optional[FeedbackEntry]:
        """Get existing feedback for a paper.

        Args:
            paper_id: The paper's registry ID.

        Returns:
            The feedback entry if found, None otherwise.
        """
        return await self.storage.get_by_paper_id(paper_id)

    async def get_feedback_for_topic(
        self,
        topic_slug: str,
        rating_filter: Optional[FeedbackRating] = None,
    ) -> List[FeedbackEntry]:
        """Get all feedback for a topic.

        Args:
            topic_slug: The topic identifier.
            rating_filter: Optional filter by rating.

        Returns:
            List of feedback entries for the topic.
        """
        return await self.storage.get_by_topic(topic_slug, rating_filter)

    async def get_positive_feedback(
        self,
        topic_slug: Optional[str] = None,
    ) -> List[FeedbackEntry]:
        """Get all positive (thumbs_up) feedback.

        Args:
            topic_slug: Optional topic filter.

        Returns:
            List of positive feedback entries.
        """
        filters = FeedbackFilters(
            topic_slug=topic_slug,
            rating=FeedbackRating.THUMBS_UP,
        )
        return await self.storage.query(filters)

    async def get_negative_feedback(
        self,
        topic_slug: Optional[str] = None,
    ) -> List[FeedbackEntry]:
        """Get all negative (thumbs_down) feedback.

        Args:
            topic_slug: Optional topic filter.

        Returns:
            List of negative feedback entries.
        """
        filters = FeedbackFilters(
            topic_slug=topic_slug,
            rating=FeedbackRating.THUMBS_DOWN,
        )
        return await self.storage.query(filters)

    async def get_analytics(
        self,
        topic_slug: Optional[str] = None,
    ) -> FeedbackAnalytics:
        """Generate feedback analytics report.

        Args:
            topic_slug: Optional topic filter for scoped analytics.

        Returns:
            Comprehensive analytics report.
        """
        if topic_slug:
            entries = await self.storage.get_by_topic(topic_slug)
        else:
            entries = await self.storage.load_all()

        if not entries:
            return FeedbackAnalytics()

        # Calculate rating distribution
        rating_counts: Counter[str] = Counter(str(e.rating) for e in entries)
        rating_distribution = {
            "thumbs_up": rating_counts.get("thumbs_up", 0),
            "thumbs_down": rating_counts.get("thumbs_down", 0),
            "neutral": rating_counts.get("neutral", 0),
        }

        # Calculate top reasons
        all_reasons: List[str] = []
        for entry in entries:
            all_reasons.extend(entry.reasons)
        reason_counts = Counter(all_reasons)
        top_reasons = reason_counts.most_common(10)

        # Calculate topic breakdown
        topic_breakdown: dict[str, TopicAnalytics] = {}
        entries_by_topic: dict[str, List[FeedbackEntry]] = {}

        for entry in entries:
            slug = entry.topic_slug or "_uncategorized"
            if slug not in entries_by_topic:
                entries_by_topic[slug] = []
            entries_by_topic[slug].append(entry)

        for slug, topic_entries in entries_by_topic.items():
            topic_rating_counts: Counter[str] = Counter(
                str(e.rating) for e in topic_entries
            )
            topic_reasons: List[str] = []
            for e in topic_entries:
                topic_reasons.extend(str(r) for r in e.reasons)
            topic_reason_counts = Counter(topic_reasons)

            topic_breakdown[slug] = TopicAnalytics(
                topic_slug=slug,
                total=len(topic_entries),
                thumbs_up=topic_rating_counts.get("thumbs_up", 0),
                thumbs_down=topic_rating_counts.get("thumbs_down", 0),
                neutral=topic_rating_counts.get("neutral", 0),
                common_reasons=[r for r, _ in topic_reason_counts.most_common(5)],
            )

        # Extract trending themes from recent positive feedback
        recent_positive = [
            e
            for e in sorted(entries, key=lambda x: x.timestamp, reverse=True)[:50]
            if str(e.rating) == "thumbs_up"
        ]
        trending_reasons: Counter[str] = Counter(
            str(reason) for e in recent_positive for reason in e.reasons
        )
        trending_themes: List[str] = [r for r, _ in trending_reasons.most_common(5)]

        return FeedbackAnalytics(
            total_ratings=len(entries),
            rating_distribution=rating_distribution,
            top_reasons=top_reasons,
            topic_breakdown=topic_breakdown,
            trending_themes=trending_themes,
        )

    async def has_sufficient_feedback(
        self,
        topic_slug: str,
        min_feedback: int = 20,
    ) -> bool:
        """Check if topic has enough feedback for preference learning.

        Args:
            topic_slug: The topic identifier.
            min_feedback: Minimum feedback count required.

        Returns:
            True if topic has at least min_feedback entries.
        """
        entries = await self.storage.get_by_topic(topic_slug)
        return len(entries) >= min_feedback

    async def get_paper_ids_by_rating(
        self,
        rating: FeedbackRating,
        topic_slug: Optional[str] = None,
    ) -> List[str]:
        """Get paper IDs with a specific rating.

        Args:
            rating: The rating to filter by.
            topic_slug: Optional topic filter.

        Returns:
            List of paper IDs with the specified rating.
        """
        filters = FeedbackFilters(topic_slug=topic_slug, rating=rating)
        entries = await self.storage.query(filters)
        return [e.paper_id for e in entries]

    async def delete_feedback(self, paper_id: str) -> bool:
        """Delete feedback for a paper.

        Args:
            paper_id: The paper's registry ID.

        Returns:
            True if deleted, False if not found.
        """
        entry = await self.storage.get_by_paper_id(paper_id)
        if entry:
            return await self.storage.delete(entry.id)
        return False

    async def export_feedback(
        self,
        format: str = "json",
        output_path: Optional[str] = None,
    ) -> str:
        """Export feedback data.

        Args:
            format: Export format ("json" or "csv").
            output_path: Optional output file path.

        Returns:
            Exported data as string, or path to file if output_path given.
        """
        from pathlib import Path

        path = Path(output_path) if output_path else None
        return await self.storage.export(format, path)
