"""Unified Quality Intelligence Service for Paper Scoring.

This service consolidates quality scoring from Phase 3.4 (QualityScorer) and
Phase 6 (QualityFilterService) into a single, authoritative scoring system.

Provides 6-signal quality scoring on a normalized 0.0-1.0 scale:
- Citation impact (logarithmic with influential bonus)
- Venue reputation (from YAML via VenueRepository)
- Publication recency (half-life decay)
- Community engagement (upvotes)
- Metadata completeness (5 fields)
- Author reputation (placeholder for future implementation)

Usage:
    from src.services.quality_intelligence_service import QualityIntelligenceService
    from src.services.venue_repository import YamlVenueRepository

    # Initialize with defaults
    service = QualityIntelligenceService()

    # Score a single paper
    scored = service.score_paper(paper)

    # Score and filter multiple papers
    scored_papers = service.filter_by_quality(papers, min_score=0.5)

    # Get quality tier
    tier = service.get_tier(scored.quality_score)  # "excellent", "good", etc.
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

import structlog

from src.models.discovery import QualityWeights, ScoredPaper
from src.models.paper import PaperMetadata
from src.services.venue_repository import VenueRepository, YamlVenueRepository

logger = structlog.get_logger()


class QualityIntelligenceService:
    """Unified quality scoring service with 6 configurable signals.

    Combines citation impact, venue reputation, recency, engagement,
    completeness, and author reputation into a normalized 0-1 score.

    Attributes:
        weights: Signal weights (must sum to 1.0 ± 0.01)
        venue_repository: Venue score provider (injected)
        min_citations: Pre-filter threshold (default: 0)
    """

    # Scoring normalization factors
    CITATION_NORMALIZATION_FACTOR: float = 10.0
    INFLUENTIAL_BONUS_FACTOR: float = 0.01
    MAX_INFLUENTIAL_BONUS: float = 0.1
    # Neutral factor when influential_citation_count is unavailable (None)
    # Value 0.05 is midpoint between 0.0 (known zero) and 0.1 (max bonus)
    # This prevents provider bias between SS and non-SS sources
    INFLUENTIAL_UNKNOWN_NEUTRAL: float = 0.05

    RECENCY_DECAY_RATE: float = 0.2
    RECENCY_MIN_SCORE: float = 0.1

    ENGAGEMENT_NORMALIZATION_FACTOR: float = 7.0

    MIN_ABSTRACT_LENGTH: int = 50
    DEFAULT_SCORE: float = 0.5

    # Completeness field weights
    COMPLETENESS_WEIGHT_ABSTRACT: float = 0.3
    COMPLETENESS_WEIGHT_AUTHORS: float = 0.2
    COMPLETENESS_WEIGHT_VENUE: float = 0.2
    COMPLETENESS_WEIGHT_PDF: float = 0.2
    COMPLETENESS_WEIGHT_DOI: float = 0.1

    # Deprecation tracking (class-level flags)
    _warned_score_legacy: bool = False
    _warned_rank_papers_legacy: bool = False
    _warned_filter_and_score: bool = False

    def __init__(
        self,
        weights: Optional[QualityWeights] = None,
        venue_repository: Optional[VenueRepository] = None,
        min_citations: int = 0,
    ) -> None:
        """Initialize quality intelligence service.

        Args:
            weights: Custom signal weights (defaults to balanced 6-signal weights)
            venue_repository: Venue score provider (defaults to YamlVenueRepository)
            min_citations: Minimum citation count for pre-filtering (default: 0)

        Raises:
            ValueError: If weights do not sum to 1.0 (±0.01)
        """
        # Use default weights if not provided
        self.weights = weights or QualityWeights()

        # Validate weights sum to 1.0
        total = self.weights.total_weight
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Weights must sum to 1.0 (±0.01), got {total:.4f}")

        # Inject venue repository (default to YAML-based)
        self.venue_repository = venue_repository or YamlVenueRepository()

        # Pre-filter threshold
        self.min_citations = min_citations

        logger.info(
            "quality_intelligence_service_initialized",
            weights=self.weights.model_dump(),
            min_citations=min_citations,
        )

    def score_paper(self, paper: PaperMetadata) -> ScoredPaper:
        """Calculate quality score for a single paper.

        Args:
            paper: Paper metadata to score

        Returns:
            ScoredPaper with computed quality score (0.0-1.0)
        """
        # Calculate individual signal scores
        citation_score = self._calculate_citation_score(paper)
        venue_score = self._calculate_venue_score(paper)
        recency_score = self._calculate_recency_score(paper)
        engagement_score = self._calculate_engagement_score(paper)
        completeness_score = self._calculate_completeness_score(paper)
        author_score = self._calculate_author_score(paper)

        # Compute weighted composite score
        quality_score = (
            self.weights.citation * citation_score
            + self.weights.venue * venue_score
            + self.weights.recency * recency_score
            + self.weights.engagement * engagement_score
            + self.weights.completeness * completeness_score
            + self.weights.author * author_score
        )

        # Ensure score is in [0.0, 1.0]
        quality_score = max(0.0, min(1.0, quality_score))

        # Get engagement score for ScoredPaper
        engagement_value = getattr(paper, "upvotes", 0) or 0

        # Create ScoredPaper with quality score
        scored_paper = ScoredPaper.from_paper_metadata(
            paper=paper,
            quality_score=quality_score,
            engagement_score=float(engagement_value),
        )

        logger.debug(
            "paper_scored",
            paper_id=paper.paper_id,
            title=paper.title[:50] if paper.title else "N/A",
            quality_score=round(quality_score, 3),
            citation=round(citation_score, 3),
            venue=round(venue_score, 3),
            recency=round(recency_score, 3),
            engagement=round(engagement_score, 3),
            completeness=round(completeness_score, 3),
            author=round(author_score, 3),
        )

        return scored_paper

    def score_papers(self, papers: List[PaperMetadata]) -> List[ScoredPaper]:
        """Score multiple papers.

        Args:
            papers: List of papers to score

        Returns:
            List of ScoredPaper objects with quality scores
        """
        if not papers:
            return []

        scored_papers = [self.score_paper(paper) for paper in papers]

        logger.info(
            "papers_scored",
            count=len(scored_papers),
            avg_score=(
                round(
                    sum(p.quality_score for p in scored_papers) / len(scored_papers), 3
                )
                if scored_papers
                else 0.0
            ),
        )

        return scored_papers

    def filter_by_quality(
        self, papers: List[PaperMetadata], min_score: float = 0.3
    ) -> List[ScoredPaper]:
        """Score papers and filter by quality threshold.

        Applies min_citations pre-filter before scoring, then filters by
        quality score.

        Args:
            papers: Papers to score and filter
            min_score: Minimum quality score threshold (0.0-1.0)

        Returns:
            List of ScoredPaper objects passing both filters
        """
        if not papers:
            return []

        logger.info(
            "quality_filtering_started",
            total_papers=len(papers),
            min_citations=self.min_citations,
            min_score=min_score,
        )

        # Pre-filter by citation count
        citation_filtered = []
        for paper in papers:
            citation_count = paper.citation_count or 0
            if citation_count >= self.min_citations:
                citation_filtered.append(paper)

        logger.info(
            "papers_pre_filtered",
            original=len(papers),
            after_filter=len(citation_filtered),
            min_citations=self.min_citations,
        )

        # Score remaining papers
        scored_papers = self.score_papers(citation_filtered)

        # Filter by quality score
        quality_filtered = [
            paper for paper in scored_papers if paper.quality_score >= min_score
        ]

        logger.info(
            "quality_filtering_completed",
            papers_input=len(papers),
            papers_output=len(quality_filtered),
            papers_filtered=len(papers) - len(quality_filtered),
        )

        return quality_filtered

    def get_tier(self, score: float) -> str:
        """Get quality tier label for a score.

        Args:
            score: Quality score (0.0-1.0)

        Returns:
            Tier label: "excellent", "good", "fair", or "low"
        """
        if score >= 0.80:
            return "excellent"
        elif score >= 0.60:
            return "good"
        elif score >= 0.40:
            return "fair"
        else:
            return "low"

    # =========================================================================
    # Private Scoring Methods
    # =========================================================================

    def _calculate_citation_score(self, paper: PaperMetadata) -> float:
        """Calculate citation impact score with influential bonus.

        Uses log1p normalization:
        - 10 citations -> ~0.24
        - 100 citations -> ~0.46
        - 1000 citations -> ~0.69

        Plus influential citation bonus:
        - Up to +0.1 for highly influential citations (Semantic Scholar)
        - Neutral factor (0.05) when influential_citation_count is unavailable
          (prevents provider bias between SS and non-SS sources)

        Args:
            paper: Paper to score

        Returns:
            Citation score (0.0-1.0)
        """
        citation_count = paper.citation_count or 0
        if citation_count <= 0:
            return 0.0

        # Base score: log1p normalization
        base_score = math.log1p(citation_count) / self.CITATION_NORMALIZATION_FACTOR

        # Influential citation bonus
        # Distinguish between: None (unavailable) vs 0 (known, no influential citations)
        influential_count = paper.influential_citation_count

        if influential_count is None:
            # Data unavailable (non-SS source) - use neutral factor to prevent bias
            influential_bonus = self.INFLUENTIAL_UNKNOWN_NEUTRAL
        elif influential_count > 0:
            # Known influential citations - calculate bonus
            influential_bonus = min(
                self.MAX_INFLUENTIAL_BONUS,
                influential_count * self.INFLUENTIAL_BONUS_FACTOR,
            )
        else:
            # Known to be zero influential citations
            influential_bonus = 0.0

        return min(1.0, base_score + influential_bonus)

    def _calculate_venue_score(self, paper: PaperMetadata) -> float:
        """Calculate venue quality score.

        Delegates to injected VenueRepository for score lookup.

        Args:
            paper: Paper to score

        Returns:
            Venue score (0.0-1.0)
        """
        if not paper.venue:
            return self.venue_repository.get_default_score()

        return self.venue_repository.get_score(paper.venue)

    def _calculate_recency_score(self, paper: PaperMetadata) -> float:
        """Calculate publication recency score with half-life decay.

        Half-life model:
        - This year -> 1.0
        - 1 year old -> ~0.83
        - 5 years old -> ~0.5
        - 10 years old -> ~0.33
        - Floor: 0.1

        Args:
            paper: Paper to score

        Returns:
            Recency score (0.1-1.0)
        """
        if not paper.publication_date:
            return self.DEFAULT_SCORE

        try:
            # Parse publication year
            if isinstance(paper.publication_date, str):
                date_str = paper.publication_date
                if len(date_str) == 4:  # Year only
                    pub_year = int(date_str)
                elif len(date_str) >= 7:  # YYYY-MM or YYYY-MM-DD
                    pub_year = int(date_str[:4])
                else:
                    return self.DEFAULT_SCORE
            else:
                # Handle datetime object
                pub_year = paper.publication_date.year

            current_year = datetime.now(timezone.utc).year
            years_old = max(0, current_year - pub_year)

            # Half-life decay formula
            decay_score = 1.0 / (1 + self.RECENCY_DECAY_RATE * years_old)
            return max(self.RECENCY_MIN_SCORE, decay_score)

        except (ValueError, AttributeError) as e:
            logger.debug(
                "recency_score_parse_error",
                paper_id=paper.paper_id,
                publication_date=str(paper.publication_date),
                error=str(e),
            )
            return self.DEFAULT_SCORE

    def _calculate_engagement_score(self, paper: PaperMetadata) -> float:
        """Calculate community engagement score from upvotes.

        Uses log normalization:
        - 10 upvotes -> ~0.35
        - 100 upvotes -> ~0.66
        - 500 upvotes -> ~0.86

        Returns neutral 0.5 for missing engagement data to avoid
        penalizing non-HuggingFace papers.

        Args:
            paper: Paper to score

        Returns:
            Engagement score (0.0-1.0)
        """
        upvotes = getattr(paper, "upvotes", 0) or 0

        if upvotes <= 0:
            # Neutral score for missing data (not 0.0)
            return self.DEFAULT_SCORE

        # Logarithmic scaling
        return min(1.0, math.log1p(upvotes) / self.ENGAGEMENT_NORMALIZATION_FACTOR)

    def _calculate_completeness_score(self, paper: PaperMetadata) -> float:
        """Calculate metadata completeness score.

        Evaluates 5 fields:
        - Abstract (min 50 chars): 0.30 weight
        - Authors (at least 1): 0.20 weight
        - Venue: 0.20 weight
        - PDF URL: 0.20 weight
        - DOI: 0.10 weight

        Args:
            paper: Paper to score

        Returns:
            Completeness score (0.0-1.0)
        """
        score = 0.0
        total_weight = 0.0

        # Abstract (minimum 50 chars)
        if paper.abstract and len(paper.abstract.strip()) >= self.MIN_ABSTRACT_LENGTH:
            score += self.COMPLETENESS_WEIGHT_ABSTRACT
        total_weight += self.COMPLETENESS_WEIGHT_ABSTRACT

        # Authors
        if paper.authors and len(paper.authors) > 0:
            score += self.COMPLETENESS_WEIGHT_AUTHORS
        total_weight += self.COMPLETENESS_WEIGHT_AUTHORS

        # Venue
        if paper.venue:
            score += self.COMPLETENESS_WEIGHT_VENUE
        total_weight += self.COMPLETENESS_WEIGHT_VENUE

        # PDF URL
        if paper.open_access_pdf or getattr(paper, "pdf_available", False):
            score += self.COMPLETENESS_WEIGHT_PDF
        total_weight += self.COMPLETENESS_WEIGHT_PDF

        # DOI
        if paper.doi:
            score += self.COMPLETENESS_WEIGHT_DOI
        total_weight += self.COMPLETENESS_WEIGHT_DOI

        return score / total_weight if total_weight > 0 else self.DEFAULT_SCORE

    def _calculate_author_score(self, paper: PaperMetadata) -> float:
        """Calculate author reputation score.

        Placeholder implementation returning neutral 0.5 until
        author h-index service is implemented.

        Args:
            paper: Paper to score

        Returns:
            Author score (0.0-1.0), currently always 0.5
        """
        # Future: Integrate with author h-index lookup service
        # For now: neutral score to avoid biasing papers
        return self.DEFAULT_SCORE

    # =========================================================================
    # Legacy Compatibility Methods (Deprecated)
    # =========================================================================

    def score_legacy(self, paper: PaperMetadata) -> float:
        """Score a single paper using legacy 0-100 scale.

        DEPRECATED: This method is deprecated in favor of score_papers().
        Use score_papers() for new code, which returns ScoredPaper objects
        with normalized 0.0-1.0 scores.

        Args:
            paper: Paper to score

        Returns:
            Quality score on 0-100 scale (legacy format)
        """
        # Emit deprecation warning once
        if not QualityIntelligenceService._warned_score_legacy:
            logger.warning(
                "deprecation_warning",
                method="score_legacy",
                message="score_legacy is deprecated, use score_papers() instead",
                migration_guide="Replace service.score_legacy(paper) with "
                "service.score_paper(paper).quality_score * 100",
            )
            QualityIntelligenceService._warned_score_legacy = True

        # Score using new system and convert to 0-100 scale
        scored_paper = self.score_paper(paper)
        return scored_paper.quality_score * 100.0

    def rank_papers_legacy(
        self, papers: List[PaperMetadata], min_score: float = 0.0
    ) -> List[PaperMetadata]:
        """Score, filter, and rank papers using legacy format.

        DEPRECATED: This method is deprecated in favor of score_papers().
        Use score_papers() for new code, which returns ScoredPaper objects.

        This method mutates each paper's quality_score attribute and returns
        papers sorted by quality_score descending.

        Args:
            papers: Papers to score and rank
            min_score: Minimum quality score threshold (0-100 scale)

        Returns:
            List of PaperMetadata sorted by quality_score (descending),
            filtered by min_score. Each paper's quality_score attribute
            is set to its score on 0-100 scale.
        """
        # Emit deprecation warning once
        if not QualityIntelligenceService._warned_rank_papers_legacy:
            logger.warning(
                "deprecation_warning",
                method="rank_papers_legacy",
                message=(
                    "rank_papers_legacy is deprecated, use score_papers() instead"
                ),
                migration_guide=(
                    "Replace service.rank_papers_legacy(papers, min_score) with "
                    "service.score_papers(papers), then filter and sort "
                    "ScoredPaper objects"
                ),
            )
            QualityIntelligenceService._warned_rank_papers_legacy = True

        if not papers:
            return []

        # Score all papers
        scored_papers = self.score_papers(papers)

        # Mutate original papers and filter
        filtered_papers = []
        for scored, original in zip(scored_papers, papers):
            # Convert to 0-100 scale
            score_100 = scored.quality_score * 100.0

            # Mutate original paper
            original.quality_score = score_100

            # Filter by min_score
            if score_100 >= min_score:
                filtered_papers.append(original)

        # Sort by quality_score descending
        filtered_papers.sort(key=lambda p: p.quality_score or 0.0, reverse=True)

        logger.info(
            "papers_ranked_legacy",
            input_count=len(papers),
            output_count=len(filtered_papers),
            filtered_count=len(papers) - len(filtered_papers),
            min_score=min_score,
        )

        return filtered_papers

    def filter_and_score(
        self, papers: List[PaperMetadata], weights: Optional[Dict[str, float]] = None
    ) -> List[ScoredPaper]:
        """Score papers with optional custom weights (QualityFilterService migration).

        DEPRECATED: This method is deprecated in favor of score_papers().
        Use score_papers() for new code.

        This method helps QualityFilterService callers migrate to the new
        QualityIntelligenceService API.

        Args:
            papers: Papers to score
            weights: Optional custom weights dict (keys: citation, venue, recency,
                     engagement, completeness, author). If provided, must sum to 1.0.

        Returns:
            List of ScoredPaper objects with quality scores (0.0-1.0 scale)

        Raises:
            ValueError: If custom weights don't sum to 1.0
        """
        # Emit deprecation warning once
        if not QualityIntelligenceService._warned_filter_and_score:
            logger.warning(
                "deprecation_warning",
                method="filter_and_score",
                message=("filter_and_score is deprecated, use score_papers() instead"),
                migration_guide=(
                    "Replace service.filter_and_score(papers, weights) with "
                    "QualityIntelligenceService(weights=QualityWeights(**weights))"
                    ".score_papers(papers)"
                ),
            )
            QualityIntelligenceService._warned_filter_and_score = True

        # If custom weights provided, create temporary service
        if weights:
            custom_weights = QualityWeights(**weights)
            temp_service = QualityIntelligenceService(
                weights=custom_weights,
                venue_repository=self.venue_repository,
                min_citations=self.min_citations,
            )
            return temp_service.score_papers(papers)

        # Use current service weights
        return self.score_papers(papers)
