"""Relevance filtering service for Phase 7 Issue 2.

Filters papers by semantic similarity to research query using embeddings.
Prevents irrelevant papers (physics, gaming, etc.) from polluting results.
"""

from typing import Dict, List, Optional

import numpy as np
import structlog

from src.models.paper import PaperMetadata
from src.services.embeddings.embedding_service import EmbeddingService

logger = structlog.get_logger()


class QueryPaper:
    """Wrapper to make query text compatible with PaperLike protocol."""

    def __init__(self, query: str):
        """Initialize with query text.

        Args:
            query: Research query text
        """
        self.paper_id = f"query:{hash(query)}"
        self.title = query
        self.abstract: Optional[str] = query


class RelevanceFilter:
    """Filters papers by semantic relevance to query.

    Uses embedding-based similarity to remove irrelevant papers that
    slip through provider-level filtering.

    Attributes:
        embedding_service: Service for computing paper embeddings
        threshold: Minimum similarity score (0-1) to keep paper
        blend_weight: Weight of relevance in composite ranking
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        threshold: float = 0.25,
        blend_weight: float = 0.4,
    ):
        """Initialize relevance filter.

        Args:
            embedding_service: Service for computing embeddings
            threshold: Minimum relevance score (0-1) to keep paper
            blend_weight: Weight of relevance in final ranking score
        """
        self.embedding_service = embedding_service
        self.threshold = threshold
        self.blend_weight = blend_weight
        self._query_embedding_cache: Dict[str, np.ndarray] = {}

    async def filter_papers(
        self,
        papers: List[PaperMetadata],
        query: str,
    ) -> List[PaperMetadata]:
        """Filter papers by relevance to query.

        Args:
            papers: Papers to filter
            query: Research query text

        Returns:
            Filtered papers with relevance_score attached
        """
        if not papers:
            return []

        # Get query embedding (cached)
        query_embedding = await self._get_query_embedding(query)

        filtered = []
        for paper in papers:
            # Compute paper embedding
            paper_embedding = await self._get_paper_embedding(paper)

            # Compute cosine similarity
            similarity = self._cosine_similarity(query_embedding, paper_embedding)

            if similarity >= self.threshold:
                # Attach relevance score and keep paper
                updated = paper.model_copy(update={"relevance_score": similarity})
                filtered.append(updated)
            else:
                logger.debug(
                    "paper_filtered_low_relevance",
                    paper_id=paper.paper_id,
                    title=paper.title[:50],
                    relevance=round(similarity, 3),
                    threshold=self.threshold,
                )

        filtered_count = len(papers) - len(filtered)
        logger.info(
            "relevance_filter_complete",
            input_count=len(papers),
            output_count=len(filtered),
            filtered_count=filtered_count,
            filter_rate=round(filtered_count / len(papers), 2) if papers else 0,
        )

        return filtered

    async def _get_query_embedding(self, query: str) -> np.ndarray:
        """Get embedding for query (cached).

        Args:
            query: Query text

        Returns:
            Query embedding vector
        """
        if query not in self._query_embedding_cache:
            # Wrap query as PaperLike object
            query_paper = QueryPaper(query)
            embedding = await self.embedding_service.get_embedding(
                query_paper, use_cache=True
            )
            self._query_embedding_cache[query] = embedding
            logger.debug("query_embedding_computed", query=query[:50])
        else:
            logger.debug("query_embedding_cache_hit", query=query[:50])

        return self._query_embedding_cache[query]

    async def _get_paper_embedding(self, paper: PaperMetadata) -> np.ndarray:
        """Get embedding for paper.

        Args:
            paper: Paper to embed

        Returns:
            Paper embedding vector
        """
        return await self.embedding_service.get_embedding(paper, use_cache=True)

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            a: First vector
            b: Second vector

        Returns:
            Cosine similarity in range [0, 1]
        """
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        return {
            "query_cache_size": len(self._query_embedding_cache),
        }
