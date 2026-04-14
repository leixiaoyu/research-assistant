"""Quality Intelligence Service - Unified Quality Scoring (Phase 6 & PR #86).

Merges QualityScorer (Phase 3.4) and QualityFilterService (Phase 6) into a single
service using the 0-1.0 scale and 5-year half-life decay from Phase 6.

This resolves the drift where the two services used:
- Different math: log10 (QualityScorer) vs log1p (QualityFilterService)
- Different scales: 0-100 (QualityScorer) vs 0-1.0 (QualityFilterService)
- Different data sources: venue_scores.yaml vs venue_rankings.json

All scoring now uses:
- Scale: 0.0-1.0 (use score_100() for legacy 0-100 compatibility)
- Citation normalization: log1p with factor of 10 (from Phase 6)
- Recency: 5-year half-life decay (from Phase 6)
- Venue scores: unified JSON format

Usage:
    from src.services.quality_intelligence_service import QualityIntelligenceService

    service = QualityIntelligenceService()
    score = service.score(paper)  # 0.0-1.0
    score_100 = service.score_100(paper)  # 0-100 (legacy)
    scored_papers = service.filter_and_score(papers)  # Returns ScoredPaper list
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog

from src.models.discovery import QualityWeights, ScoredPaper
from src.models.paper import PaperMetadata

logger = structlog.get_logger()

# Default path for unified venue scores
DEFAULT_VENUE_SCORES_PATH = Path(__file__).parent.parent / "data" / "venue_scores.json"

# ============================================================================
# Venue Score Loading
# ============================================================================


def load_venue_scores_json(
    path: Optional[Path] = None,
) -> Tuple[Dict[str, float], float]:
    """Load venue scores from unified JSON file.

    Handles two JSON formats:
    1. {"venues": {"venue_name": 0.85}, "default_score": 0.5}
    2. {"venues": {"venue_name": {"score": 0.85}}}

    Args:
        path: Path to venue scores JSON. Uses default if None.

    Returns:
        Tuple of (venue_scores dict, default_score)
    """
    scores_path = path or DEFAULT_VENUE_SCORES_PATH

    if not scores_path.exists():
        logger.warning("venue_scores_json_not_found", path=str(scores_path))
        return {}, 0.5  # Fallback defaults

    try:
        with open(scores_path, encoding="utf-8") as f:
            data = json.load(f)

        if data is None:
            logger.warning("venue_scores_json_empty", path=str(scores_path))
            return {}, 0.5

        # Handle both top-level "venues" key or direct venue dict
        venues_raw = data.get("venues", data)

        # Default score: check for "default_score" in data, otherwise 0.5
        default = float(data.get("default_score", 0.5))

        venues: Dict[str, float] = {}
        for venue, info in venues_raw.items():
            # Handle {"venue": {"score": 0.85}} format
            if isinstance(info, dict):
                score = float(info.get("score", default))
            else:
                # Handle {"venue": 0.85} format
                score = float(info)

            # Normalize venue name: lowercase, remove digits
            normalized = _normalize_venue_name(venue)
            venues[normalized] = score

        logger.info(
            "venue_scores_json_loaded",
            count=len(venues),
            default=default,
            path=str(scores_path),
        )
        return venues, default
    except json.JSONDecodeError as e:
        logger.error(
            "venue_scores_json_parse_error",
            path=str(scores_path),
            error=str(e),
        )
        return {}, 0.5
    except (ValueError, TypeError) as e:
        logger.error(
            "venue_scores_json_value_error",
            path=str(scores_path),
            error=str(e),
        )
        return {}, 0.5


def _normalize_venue_name(venue: str) -> str:
    """Normalize venue name for matching.

    Args:
        venue: Raw venue name

    Returns:
        Normalized lowercase name with digits removed
    """
    if not venue:
        return ""
    # Lowercase and remove year digits
    normalized = venue.lower()
    normalized = "".join(c for c in normalized if not c.isdigit())
    # Remove special characters, keep alphanumerics and spaces
    normalized = "".join(c for c in normalized if c.isalnum() or c.isspace())
    # Remove common words
    for word in ["proceedings", "conference", "journal", "international"]:
        normalized = normalized.replace(word, "")
    # Collapse whitespace
    normalized = " ".join(normalized.split())
    return normalized.strip()


# ============================================================================
# QualityIntelligenceService
# ============================================================================


class QualityIntelligenceService:
    """Unified quality scoring service.

    Combines Phase 3.4 QualityScorer and Phase 6 QualityFilterService into
    a single service with consistent math and scoring.

    Scoring uses:
    - Citation: log1p normalization with factor 10 (0.0-1.0)
    - Venue: 0-1.0 scale from unified JSON
    - Recency: 5-year half-life decay (0.1-1.0)
    - Engagement: log1p normalization (HuggingFace upvotes)
    - Completeness: metadata presence scoring
    - Author: default 0.5 (no h-index data)

    Attributes:
        weights: Quality signal weights for composite scoring
        venue_scores: Mapping of venue names to quality scores
        default_venue_score: Default score for unknown venues
        min_quality_score: Minimum quality score threshold (0.0-1.0)
        min_citations: Minimum citation count threshold
    """

    # Scoring constants (from Phase 6 QualityFilterService)
    CITATION_NORMALIZATION_FACTOR: float = 10.0
    RECENCY_DECAY_RATE: float = 0.2  # 5-year half-life
    RECENCY_MIN_SCORE: float = 0.1
    ENGAGEMENT_NORMALIZATION_FACTOR: float = 7.0
    MIN_ABSTRACT_LENGTH: int = 50
    DEFAULT_SCORE: float = 0.5

    # Completeness weights
    COMPLETENESS_WEIGHT_ABSTRACT: float = 0.3
    COMPLETENESS_WEIGHT_AUTHORS: float = 0.2
    COMPLETENESS_WEIGHT_VENUE: float = 0.2
    COMPLETENESS_WEIGHT_PDF: float = 0.2
    COMPLETENESS_WEIGHT_DOI: float = 0.1

    def __init__(
        self,
        venue_scores_path: Optional[Path] = None,
        weights: Optional[QualityWeights] = None,
        min_quality_score: float = 0.3,
        min_citations: int = 0,
    ) -> None:
        """Initialize QualityIntelligenceService.

        Args:
            venue_scores_path: Path to unified venue scores JSON.
                Uses default path if None.
            weights: Quality signal weights. Uses QualityWeights defaults if None.
            min_quality_score: Minimum quality score for filter_and_score (0.0-1.0).
            min_citations: Minimum citation count threshold.
        """
        self.weights = weights or QualityWeights()  # type: ignore[call-arg]
        self.min_quality_score = min_quality_score
        self.min_citations = min_citations

        # Load venue scores from unified JSON
        self.venue_scores, self.default_venue_score = load_venue_scores_json(
            venue_scores_path
        )

        logger.info(
            "quality_intelligence_initialized",
            venue_count=len(self.venue_scores),
            default_venue_score=self.default_venue_score,
            min_quality_score=self.min_quality_score,
            weights=self.weights.model_dump(),
        )

    def score(self, paper: PaperMetadata) -> float:
        """Calculate composite quality score (0.0-1.0).

        This is the primary scoring method using unified Phase 6 math.

        Args:
            paper: Paper metadata to score.

        Returns:
            Quality score between 0.0 and 1.0.
        """
        citation_s = self._calculate_citation_score(paper)
        venue_s = self._calculate_venue_score(paper)
        recency_s = self._calculate_recency_score(paper)
        engagement_s = self._calculate_engagement_score(paper)
        completeness_s = self._calculate_completeness_score(paper)
        author_s = self._calculate_author_score(paper)

        total_weight = self.weights.total_weight
        if total_weight == 0:
            return self.DEFAULT_SCORE

        score = (
            self.weights.citation * citation_s
            + self.weights.venue * venue_s
            + self.weights.recency * recency_s
            + self.weights.engagement * engagement_s
            + self.weights.completeness * completeness_s
            + self.weights.author * author_s
        ) / total_weight

        result = min(1.0, max(0.0, score))

        logger.debug(
            "quality_score_calculated",
            paper_id=paper.paper_id,
            title=paper.title[:50] if paper.title else "N/A",
            citation=citation_s,
            venue=venue_s,
            recency=recency_s,
            engagement=engagement_s,
            completeness=completeness_s,
            author=author_s,
            final=round(result, 4),
        )

        return result

    def score_100(self, paper: PaperMetadata) -> float:
        """Calculate composite quality score (0-100).

        Legacy compatibility method for code that expects 0-100 scale
        from the original Phase 3.4 QualityScorer.

        Args:
            paper: Paper metadata to score.

        Returns:
            Quality score between 0 and 100.
        """
        return self.score(paper) * 100.0

    def filter_and_score(
        self,
        papers: List[PaperMetadata],
        weights: Optional[QualityWeights] = None,
    ) -> List[ScoredPaper]:
        """Filter papers by quality and compute composite scores.

        Args:
            papers: List of papers to filter.
            weights: Optional custom weights (overrides instance weights).

        Returns:
            List of papers with quality scores, filtered by min_quality_score.
        """
        if not papers:
            return []

        effective_weights = weights or self.weights

        logger.info(
            "quality_filter_starting",
            papers_count=len(papers),
            min_citations=self.min_citations,
            min_quality_score=self.min_quality_score,
        )

        scored_papers = []
        filtered_count = 0

        for paper in papers:
            # Check citation threshold
            citation_count = paper.citation_count or 0
            if citation_count < self.min_citations:
                filtered_count += 1
                continue

            # Calculate quality score
            quality_score = self._calculate_quality_score_with_weights(
                paper, effective_weights
            )

            # Check quality threshold
            if quality_score < self.min_quality_score:
                filtered_count += 1
                continue

            # Get engagement score if available
            engagement_score = float(getattr(paper, "upvotes", 0) or 0)

            # Create scored paper
            scored_paper = ScoredPaper.from_paper_metadata(
                paper=paper,
                quality_score=quality_score,
                engagement_score=engagement_score,
            )
            scored_papers.append(scored_paper)

        logger.info(
            "quality_filter_completed",
            papers_input=len(papers),
            papers_output=len(scored_papers),
            papers_filtered=filtered_count,
        )

        return scored_papers

    def rank_papers(
        self,
        papers: List[PaperMetadata],
        min_score: float = 0.0,
    ) -> List[PaperMetadata]:
        """Score and rank papers by quality (legacy Phase 3.4 interface).

        Args:
            papers: Papers to rank.
            min_score: Minimum quality score threshold (0-100 for legacy compat).

        Returns:
            Papers sorted by quality score (highest first),
            with quality_score field populated.
        """
        if not papers:
            return []

        scored = []
        for paper in papers:
            quality_score = self.score_100(paper)  # Get 0-100 scale
            paper.quality_score = quality_score

            if quality_score >= min_score:
                scored.append(paper)

        # Sort by quality (highest first)
        scored.sort(key=lambda p: p.quality_score, reverse=True)

        logger.info(
            "papers_ranked_by_quality",
            total=len(papers),
            above_threshold=len(scored),
            min_score=min_score,
            top_score=round(scored[0].quality_score, 2) if scored else 0,
            bottom_score=round(scored[-1].quality_score, 2) if scored else 0,
        )

        return scored

    def get_quality_tier(self, score: float) -> str:
        """Get quality tier label for a score (0-100 scale, legacy).

        Args:
            score: Quality score (0-100).

        Returns:
            Tier label string.
        """
        if score >= 80:
            return "excellent"
        elif score >= 60:
            return "good"
        elif score >= 40:
            return "fair"
        else:
            return "low"

    def _calculate_quality_score_with_weights(
        self,
        paper: PaperMetadata,
        weights: QualityWeights,
    ) -> float:
        """Calculate composite quality score with custom weights.

        Args:
            paper: Paper to score.
            weights: Weights for each signal.

        Returns:
            Quality score between 0.0 and 1.0.
        """
        citation_s = self._calculate_citation_score(paper)
        venue_s = self._calculate_venue_score(paper)
        recency_s = self._calculate_recency_score(paper)
        engagement_s = self._calculate_engagement_score(paper)
        completeness_s = self._calculate_completeness_score(paper)
        author_s = self._calculate_author_score(paper)

        total_weight = weights.total_weight
        if total_weight == 0:
            return self.DEFAULT_SCORE

        score = (
            weights.citation * citation_s
            + weights.venue * venue_s
            + weights.recency * recency_s
            + weights.engagement * engagement_s
            + weights.completeness * completeness_s
            + weights.author * author_s
        ) / total_weight

        return min(1.0, max(0.0, score))

    def _calculate_citation_score(self, paper: PaperMetadata) -> float:
        """Logarithmic citation score (0-1 range).

        Uses log1p normalization with scale factor of 10 (Phase 6).
        - 0 citations -> 0.0
        - 10 citations -> ~0.24
        - 100 citations -> ~0.46
        - 1000 citations -> ~0.69
        - 10000 citations -> ~0.92

        Args:
            paper: Paper to score.

        Returns:
            Citation score (0.0-1.0).
        """
        citation_count = paper.citation_count or 0
        score = math.log1p(citation_count) / self.CITATION_NORMALIZATION_FACTOR

        # Influential citation bonus (up to 0.1 extra)
        influential = getattr(paper, "influential_citation_count", 0) or 0
        if influential and int(influential) > 0:
            influential_bonus = min(0.1, int(influential) * 0.01)
            score += influential_bonus

        return min(1.0, score)

    def _calculate_venue_score(self, paper: PaperMetadata) -> float:
        """Venue quality score based on unified venue rankings.

        Uses case-insensitive partial matching against known venues.

        Args:
            paper: Paper to score.

        Returns:
            Venue score (0.0-1.0), default 0.5 for unknown venues.
        """
        venue = (paper.venue or "").lower().strip()

        if not venue:
            return self.default_venue_score

        # Case-insensitive partial matching
        for known_venue, score in self.venue_scores.items():
            if known_venue in venue:
                return float(score)

        # Unknown venue - use default
        return self.default_venue_score

    def _calculate_recency_score(self, paper: PaperMetadata) -> float:
        """Recency score with 5-year half-life decay.

        Uses the formula: score = 1 / (1 + decay_rate * years)
        - This year -> 1.0
        - 1 year old -> ~0.83
        - 2 years old -> ~0.71
        - 5 years old -> ~0.5
        - 10 years old -> ~0.33

        Args:
            paper: Paper to score.

        Returns:
            Recency score (0.1-1.0).
        """
        if not paper.publication_date:
            return self.DEFAULT_SCORE

        try:
            # Parse publication date
            if isinstance(paper.publication_date, str):
                date_str = paper.publication_date
                if len(date_str) == 4:  # Year only
                    pub_year = int(date_str)
                elif len(date_str) >= 7:  # YYYY-MM or YYYY-MM-DD
                    pub_year = int(date_str[:4])
                else:
                    return self.DEFAULT_SCORE
            else:
                pub_year = paper.publication_date.year

            current_year = datetime.now(timezone.utc).year
            years_old = max(0, current_year - pub_year)

            # Half-life decay
            decay_score = 1.0 / (1 + self.RECENCY_DECAY_RATE * years_old)
            return max(self.RECENCY_MIN_SCORE, decay_score)

        except (ValueError, AttributeError):
            return self.DEFAULT_SCORE

    def _calculate_engagement_score(self, paper: PaperMetadata) -> float:
        """Engagement score from community signals (e.g., upvotes).

        Args:
            paper: Paper to score.

        Returns:
            Engagement score (0.0-1.0).
        """
        upvotes = getattr(paper, "upvotes", 0) or 0

        if upvotes == 0:
            return 0.0

        return min(
            1.0,
            math.log1p(upvotes) / self.ENGAGEMENT_NORMALIZATION_FACTOR,
        )

    def _calculate_completeness_score(self, paper: PaperMetadata) -> float:
        """Metadata completeness score.

        Args:
            paper: Paper to score.

        Returns:
            Completeness score (0.0-1.0).
        """
        score = 0.0
        checks = 0.0

        # Required fields (higher weight)
        if paper.abstract and len(paper.abstract) > self.MIN_ABSTRACT_LENGTH:
            score += self.COMPLETENESS_WEIGHT_ABSTRACT
        checks += self.COMPLETENESS_WEIGHT_ABSTRACT

        if paper.authors and len(paper.authors) > 0:
            score += self.COMPLETENESS_WEIGHT_AUTHORS
        checks += self.COMPLETENESS_WEIGHT_AUTHORS

        # Optional but valuable fields
        if paper.venue:
            score += self.COMPLETENESS_WEIGHT_VENUE
        checks += self.COMPLETENESS_WEIGHT_VENUE

        if paper.open_access_pdf or paper.pdf_available:
            score += self.COMPLETENESS_WEIGHT_PDF
        checks += self.COMPLETENESS_WEIGHT_PDF

        if paper.doi:
            score += self.COMPLETENESS_WEIGHT_DOI
        checks += self.COMPLETENESS_WEIGHT_DOI

        return score / checks if checks > 0 else self.DEFAULT_SCORE

    def _calculate_author_score(self, paper: PaperMetadata) -> float:
        """Author reputation score.

        Currently returns default as author h-index data
        is not typically available from providers.

        Args:
            paper: Paper to score.

        Returns:
            Author score (0.0-1.0), default 0.5.
        """
        return self.DEFAULT_SCORE
