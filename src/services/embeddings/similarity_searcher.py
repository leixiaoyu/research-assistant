"""Similarity search service for Phase 7.3 Human Feedback Loop.

This module provides semantic similarity search for finding papers
similar to a given paper or set of liked papers.
"""

import logging
from typing import List, Optional, Protocol, cast, runtime_checkable

from src.models.feedback import FeedbackRating, SimilarPaper
from src.services.embeddings.embedding_service import EmbeddingService, PaperLike

logger = logging.getLogger(__name__)


@runtime_checkable
class RegistryLike(Protocol):
    """Protocol for registry-like objects."""

    async def get_paper(  # pragma: no cover - protocol method
        self, paper_id: str
    ) -> Optional[object]:
        """Get a paper by ID."""
        ...

    async def resolve_identity(  # pragma: no cover - protocol method
        self, paper_id: str
    ) -> Optional[object]:
        """Resolve paper identity."""
        ...


@runtime_checkable
class FeedbackServiceLike(Protocol):
    """Protocol for feedback service-like objects."""

    async def get_paper_ids_by_rating(  # pragma: no cover - protocol method
        self,
        rating: FeedbackRating,
        topic_slug: Optional[str] = None,
    ) -> List[str]:
        """Get paper IDs with a specific rating."""
        ...


class SimilaritySearcher:
    """Service for finding similar papers using embeddings.

    Provides methods for semantic similarity search based on
    paper embeddings.

    Attributes:
        embedding_service: Service for computing embeddings.
        registry_service: Optional registry for paper lookup.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        registry_service: Optional[RegistryLike] = None,
    ) -> None:
        """Initialize similarity searcher.

        Args:
            embedding_service: Service for computing embeddings.
            registry_service: Optional registry for paper lookup.
        """
        self.embedding_service = embedding_service
        self.registry_service = registry_service

    async def find_similar(
        self,
        paper: PaperLike,
        top_k: int = 20,
        include_reasons: Optional[str] = None,
        exclude_self: bool = True,
    ) -> List[SimilarPaper]:
        """Find papers similar to the given paper.

        Args:
            paper: Paper object with paper_id, title, abstract.
            top_k: Number of similar papers to return.
            include_reasons: Optional user reasons for weighting.
            exclude_self: Whether to exclude the query paper.

        Returns:
            List of similar papers with scores.
        """
        # Get paper_id for exclusion
        paper_id = getattr(paper, "paper_id", None)
        exclude_ids = [paper_id] if exclude_self and paper_id else []

        # Compute embedding for query paper
        embedding = await self.embedding_service.get_embedding(paper)

        # Search FAISS index
        results = await self.embedding_service.search_similar(
            embedding, top_k=top_k, exclude_ids=exclude_ids
        )

        similar_papers: List[SimilarPaper] = []

        for result_paper_id, similarity_score in results:
            # Try to get paper details from registry
            title = result_paper_id  # Default to ID
            previously_discovered = False

            if self.registry_service is not None:
                try:
                    entry = await self.registry_service.resolve_identity(
                        result_paper_id
                    )
                    if entry is not None:
                        title = getattr(entry, "title", result_paper_id)
                        previously_discovered = True
                except Exception as e:
                    logger.debug(f"Registry lookup failed: {e}")

            # Determine matching aspects based on similarity score
            matching_aspects = self._determine_matching_aspects(
                similarity_score, include_reasons
            )

            similar_papers.append(
                SimilarPaper(
                    paper_id=result_paper_id,
                    title=title,
                    similarity_score=similarity_score,
                    matching_aspects=matching_aspects,
                    previously_discovered=previously_discovered,
                )
            )

        return similar_papers

    def _determine_matching_aspects(
        self,
        similarity_score: float,
        user_reasons: Optional[str] = None,
    ) -> List[str]:
        """Determine matching aspects based on similarity.

        Args:
            similarity_score: The similarity score (0-1).
            user_reasons: Optional user-provided reasons.

        Returns:
            List of matching aspect labels.
        """
        aspects = []

        # Score-based aspects
        if similarity_score >= 0.9:
            aspects.append("highly_related")
        elif similarity_score >= 0.7:
            aspects.append("related")
        elif similarity_score >= 0.5:
            aspects.append("somewhat_related")

        # Add semantic aspects based on score ranges
        if similarity_score >= 0.8:
            aspects.append("similar_methodology")
        if similarity_score >= 0.75:
            aspects.append("similar_topic")
        if similarity_score >= 0.6:
            aspects.append("related_field")

        # Parse user reasons and add as aspects
        if user_reasons:
            reason_keywords = {
                "methodology": "similar_methodology",
                "method": "similar_methodology",
                "approach": "similar_approach",
                "findings": "similar_findings",
                "results": "similar_results",
                "application": "similar_applications",
                "domain": "same_domain",
                "topic": "similar_topic",
            }
            reasons_lower = user_reasons.lower()
            for keyword, aspect in reason_keywords.items():
                if keyword in reasons_lower and aspect not in aspects:
                    aspects.append(aspect)

        return aspects

    async def find_similar_to_liked(
        self,
        topic_slug: str,
        feedback_service: FeedbackServiceLike,
        top_k: int = 20,
    ) -> List[SimilarPaper]:
        """Find papers similar to all liked papers in a topic.

        Aggregates similarity scores across all positively-rated papers
        to find papers that match the user's preferences.

        Args:
            topic_slug: The topic identifier.
            feedback_service: Service to get feedback data.
            top_k: Number of similar papers to return.

        Returns:
            List of similar papers ranked by aggregate similarity.
        """
        # Get liked paper IDs
        liked_ids = await feedback_service.get_paper_ids_by_rating(
            FeedbackRating.THUMBS_UP, topic_slug
        )

        if not liked_ids:
            logger.info(f"No liked papers found for topic {topic_slug}")
            return []

        # Aggregate similarity scores across all liked papers
        aggregate_scores: dict[str, float] = {}
        seen_counts: dict[str, int] = {}

        for liked_id in liked_ids:
            # Get paper from registry if available
            paper_obj: Optional[PaperLike] = None
            if self.registry_service is not None:
                try:
                    resolved = await self.registry_service.resolve_identity(liked_id)
                    if resolved is not None:
                        paper_obj = cast(PaperLike, resolved)
                except Exception as e:
                    logger.debug(f"Registry lookup failed for {liked_id}: {e}")

            if paper_obj is None:
                # Create minimal paper object
                paper_obj = _MinimalPaper(
                    paper_id=liked_id, title=liked_id, abstract=None
                )

            # Find similar to this liked paper
            similar = await self.find_similar(
                paper_obj,
                top_k=top_k * 2,  # Get more for aggregation
                exclude_self=True,
            )

            for sp in similar:
                # Skip papers the user has already liked
                if sp.paper_id in liked_ids:
                    continue

                if sp.paper_id not in aggregate_scores:
                    aggregate_scores[sp.paper_id] = 0.0
                    seen_counts[sp.paper_id] = 0

                aggregate_scores[sp.paper_id] += sp.similarity_score
                seen_counts[sp.paper_id] += 1

        if not aggregate_scores:
            return []

        # Normalize scores by number of liked papers that matched
        normalized_scores = {
            pid: score / seen_counts[pid] for pid, score in aggregate_scores.items()
        }

        # Sort by normalized score
        sorted_ids = sorted(
            normalized_scores.keys(),
            key=lambda x: normalized_scores[x],
            reverse=True,
        )[:top_k]

        # Build result list
        results: List[SimilarPaper] = []
        for pid in sorted_ids:
            title = pid
            previously_discovered = False

            if self.registry_service is not None:
                try:
                    entry = await self.registry_service.resolve_identity(pid)
                    if entry is not None:
                        title = getattr(entry, "title", pid)
                        previously_discovered = True
                except Exception:
                    pass

            results.append(
                SimilarPaper(
                    paper_id=pid,
                    title=title,
                    similarity_score=normalized_scores[pid],
                    matching_aspects=self._determine_matching_aspects(
                        normalized_scores[pid]
                    ),
                    previously_discovered=previously_discovered,
                )
            )

        return results

    async def compute_paper_similarity(
        self,
        paper1: PaperLike,
        paper2: PaperLike,
    ) -> float:
        """Compute similarity between two papers.

        Args:
            paper1: First paper object.
            paper2: Second paper object.

        Returns:
            Similarity score between 0 and 1.
        """
        import numpy as np

        emb1 = await self.embedding_service.get_embedding(paper1)
        emb2 = await self.embedding_service.get_embedding(paper2)

        # Cosine similarity
        norm1 = np.linalg.norm(emb1)
        norm2 = np.linalg.norm(emb2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        similarity = float(np.dot(emb1, emb2) / (norm1 * norm2))
        # Normalize to 0-1 range
        return max(0.0, min(1.0, (similarity + 1) / 2))


class _MinimalPaper:
    """Minimal paper object for similarity search."""

    def __init__(
        self,
        paper_id: str,
        title: str,
        abstract: Optional[str] = None,
    ) -> None:
        self.paper_id = paper_id
        self.title = title
        self.abstract = abstract
