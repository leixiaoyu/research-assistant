"""
Paper filtering and ranking service.

Filters papers by:
- Citation count (popularity indicator)
- Publication year (recency)
- Text relevance to query (word overlap)

Ranks papers by weighted combination of scores.
"""

import math
from datetime import datetime
from typing import List, Optional
import structlog

from src.models.paper import PaperMetadata
from src.models.filters import FilterConfig, PaperScore, FilterStats

logger = structlog.get_logger()


class FilterService:
    """
    Filter and rank papers by quality and relevance.

    Uses configurable weights for citation, recency, and relevance scores.
    """

    def __init__(self, config: FilterConfig):
        """
        Initialize filter service.

        Args:
            config: Filter configuration
        """
        self.config = config
        self.stats = FilterStats()

        logger.info(
            "filter_service_initialized",
            min_citations=config.min_citation_count,
            min_year=config.min_year,
            citation_weight=config.citation_weight,
            recency_weight=config.recency_weight,
            relevance_weight=config.relevance_weight
        )

    def filter_and_rank(
        self,
        papers: List[PaperMetadata],
        query: str
    ) -> List[PaperMetadata]:
        """
        Filter and rank papers by quality and relevance.

        Args:
            papers: Papers to filter and rank
            query: Search query (for relevance scoring)

        Returns:
            Filtered and ranked papers (highest score first)
        """
        self.stats.total_papers_input = len(papers)

        # Filter by hard criteria
        filtered_papers = self._apply_filters(papers)
        self.stats.papers_filtered_out = len(papers) - len(filtered_papers)

        if not filtered_papers:
            logger.warning("no_papers_after_filtering", original_count=len(papers))
            return []

        # Rank by relevance
        ranked_papers = self._rank_papers(filtered_papers, query)
        self.stats.papers_ranked = len(ranked_papers)

        logger.info(
            "filtering_complete",
            input=len(papers),
            filtered_out=self.stats.papers_filtered_out,
            output=len(ranked_papers)
        )

        return ranked_papers

    def _apply_filters(self, papers: List[PaperMetadata]) -> List[PaperMetadata]:
        """
        Apply hard filters to papers.

        Args:
            papers: Papers to filter

        Returns:
            Papers that pass all filters
        """
        filtered = []

        for paper in papers:
            # Citation count filter
            if paper.citation_count < self.config.min_citation_count:
                continue

            # Year filter
            if paper.year is not None:
                if self.config.min_year and paper.year < self.config.min_year:
                    continue
                if self.config.max_year and paper.year > self.config.max_year:
                    continue

            filtered.append(paper)

        return filtered

    def _rank_papers(
        self,
        papers: List[PaperMetadata],
        query: str
    ) -> List[PaperMetadata]:
        """
        Rank papers by relevance score.

        Args:
            papers: Papers to rank
            query: Search query

        Returns:
            Papers sorted by total score (descending)
        """
        scored_papers = []
        citation_scores = []
        recency_scores = []
        relevance_scores = []

        for paper in papers:
            score = self._calculate_score(paper, query)
            scored_papers.append((paper, score))

            citation_scores.append(score.citation_score)
            recency_scores.append(score.recency_score)
            relevance_scores.append(score.text_similarity_score)

        # Calculate average scores for stats
        if scored_papers:
            self.stats.avg_citation_score = sum(citation_scores) / len(citation_scores)
            self.stats.avg_recency_score = sum(recency_scores) / len(recency_scores)
            self.stats.avg_relevance_score = sum(relevance_scores) / len(relevance_scores)

        # Sort by total score (descending)
        scored_papers.sort(key=lambda x: x[1].total_score, reverse=True)

        return [paper for paper, score in scored_papers]

    def _calculate_score(self, paper: PaperMetadata, query: str) -> PaperScore:
        """
        Calculate relevance score for paper.

        Args:
            paper: Paper to score
            query: Search query

        Returns:
            PaperScore with breakdown
        """
        # Citation score (log scale to handle outliers)
        citation_score = self._citation_score(paper.citation_count)

        # Recency score (10-year decay)
        recency_score = self._recency_score(paper.year)

        # Text similarity score (word overlap)
        text_similarity = self._text_similarity(query, paper)

        # Weighted total
        total_score = (
            self.config.citation_weight * citation_score +
            self.config.recency_weight * recency_score +
            self.config.relevance_weight * text_similarity
        )

        return PaperScore(
            paper_id=paper.paper_id,
            citation_score=citation_score,
            recency_score=recency_score,
            text_similarity_score=text_similarity,
            total_score=total_score
        )

    @staticmethod
    def _citation_score(citation_count: int) -> float:
        """
        Calculate citation score using log scale.

        Args:
            citation_count: Number of citations

        Returns:
            Score 0.0-1.0 (1000+ citations = 1.0)
        """
        if citation_count <= 0:
            return 0.0

        # Log10 scale: 1 = 0.0, 10 = 0.33, 100 = 0.67, 1000+ = 1.0
        score = math.log10(citation_count) / 3.0
        return min(1.0, score)

    @staticmethod
    def _recency_score(year: Optional[int]) -> float:
        """
        Calculate recency score with 10-year linear decay.

        Args:
            year: Publication year

        Returns:
            Score 0.0-1.0 (current year = 1.0, 10+ years ago = 0.0)
        """
        if year is None:
            return 0.5  # Unknown year = neutral score

        current_year = datetime.now().year
        years_old = current_year - year

        if years_old < 0:
            # Future year (data error) = neutral
            return 0.5

        # Linear decay: 0 years = 1.0, 10 years = 0.0
        score = max(0.0, 1.0 - (years_old / 10.0))
        return score

    @staticmethod
    def _text_similarity(query: str, paper: PaperMetadata) -> float:
        """
        Calculate text similarity using word overlap.

        Args:
            query: Search query
            paper: Paper to compare

        Returns:
            Score 0.0-1.0 based on word overlap
        """
        # Combine title and abstract
        paper_text = f"{paper.title} {paper.abstract or ''}"

        # Normalize text
        query_words = set(query.lower().split())
        paper_words = set(paper_text.lower().split())

        if not query_words or not paper_words:
            return 0.0

        # Jaccard similarity: intersection / union
        intersection = len(query_words & paper_words)
        union = len(query_words | paper_words)

        similarity = intersection / union if union > 0 else 0.0

        return similarity

    def get_stats(self) -> FilterStats:
        """
        Get filtering statistics.

        Returns:
            FilterStats with current statistics
        """
        return self.stats
