"""Quality Scorer Service for Paper Ranking (Phase 3.4).

This module maintains backward compatibility with the original Phase 3.4 QualityScorer
interface while internally delegating to QualityIntelligenceService for the composite
score calculation.

Deprecated:
    QualityScorer is deprecated in favor of QualityIntelligenceService.
    The score() method delegates to QualityIntelligenceService internally.
    Internal methods (_citation_score, etc.) preserve original Phase 3.4 math.
"""

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import warnings
import structlog

from src.models.paper import PaperMetadata

logger = structlog.get_logger()

# Default path for venue scores
DEFAULT_VENUE_SCORES_PATH = Path(__file__).parent.parent / "data" / "venue_scores.yaml"


def load_venue_scores(path: Optional[Path] = None) -> Tuple[Dict[str, int], int]:
    """Load venue scores from YAML file.

    Args:
        path: Path to venue scores YAML. Uses default if None.

    Returns:
        Tuple of (venue_scores dict, default_score)
    """
    scores_path = path or DEFAULT_VENUE_SCORES_PATH

    if not scores_path.exists():
        logger.warning("venue_scores_file_not_found", path=str(scores_path))
        return {}, 15  # Fallback defaults

    try:
        import yaml

        with open(scores_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if data is None:
            logger.warning("venue_scores_file_empty", path=str(scores_path))
            return {}, 15

        venues = {str(k).lower(): int(v) for k, v in data.get("venues", {}).items()}
        default = int(data.get("default_score", 15))

        logger.info("venue_scores_loaded", count=len(venues), default=default)
        return venues, default
    except ImportError:
        logger.error("yaml_not_installed", path=str(scores_path))
        return {}, 15
    except yaml.YAMLError as e:
        logger.error("venue_scores_parse_error", path=str(scores_path), error=str(e))
        return {}, 15
    except (ValueError, TypeError) as e:
        logger.error("venue_scores_value_error", path=str(scores_path), error=str(e))
        return {}, 15


class QualityScorer:
    """Calculate quality scores for papers.

    .. deprecated::
        QualityScorer is deprecated in favor of QualityIntelligenceService.
        For new code, use QualityIntelligenceService directly.
        This class is preserved for backward compatibility.

    Uses weighted scoring across multiple dimensions to produce
    a composite quality score (0-100).

    Internal methods (_citation_score, _venue_score, etc.) preserve the
    original Phase 3.4 math for backward compatibility with tests.
    The composite score() method delegates to QualityIntelligenceService.
    """

    # Maximum points for each component (before normalization)
    MAX_CITATION_POINTS = 40.0
    MAX_VENUE_POINTS = 30.0
    MAX_RECENCY_POINTS = 20.0
    MAX_COMPLETENESS_POINTS = 10.0

    def __init__(
        self,
        citation_weight: float = 0.40,
        venue_weight: float = 0.30,
        recency_weight: float = 0.20,
        completeness_weight: float = 0.10,
        venue_scores_path: Optional[Path] = None,
    ):
        """Initialize quality scorer.

        Args:
            citation_weight: Weight for citation score (0-1).
            venue_weight: Weight for venue score (0-1).
            recency_weight: Weight for recency score (0-1).
            completeness_weight: Weight for completeness score (0-1).
            venue_scores_path: Path to venue scores YAML file.
        """
        warnings.warn(
            "QualityScorer is deprecated. Use QualityIntelligenceService instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        # Validate weights sum to 1.0 (with tolerance for floating point)
        total_weight = (
            citation_weight + venue_weight + recency_weight + completeness_weight
        )
        if not (0.99 <= total_weight <= 1.01):
            raise ValueError(f"Weights must sum to 1.0, got {total_weight}")

        self.citation_weight = citation_weight
        self.venue_weight = venue_weight
        self.recency_weight = recency_weight
        self.completeness_weight = completeness_weight

        # Load externalized venue scores from YAML
        self.venue_scores, self.default_venue_score = load_venue_scores(
            venue_scores_path
        )

        logger.info(
            "quality_scorer_initialized",
            citation_weight=citation_weight,
            venue_weight=venue_weight,
            recency_weight=recency_weight,
            completeness_weight=completeness_weight,
            venue_count=len(self.venue_scores),
        )

    def score(self, paper: PaperMetadata) -> float:
        """Calculate composite quality score (0-100).

        This method delegates to QualityIntelligenceService to ensure
        consistent scoring math with the rest of the system.

        Args:
            paper: Paper metadata to score.

        Returns:
            Quality score between 0 and 100.
        """
        # Import here to avoid circular imports
        from src.services.quality_intelligence_service import QualityIntelligenceService

        delegate = QualityIntelligenceService()
        return delegate.score_100(paper)

    def _citation_score(self, paper: PaperMetadata) -> float:
        """Calculate citation impact score (0-1).

        Uses log scale to handle wide range of citation counts:
        - 1 citation = ~0.17
        - 10 citations = ~0.50
        - 100 citations = ~0.83
        - 1000+ citations = 1.0

        Args:
            paper: Paper metadata.

        Returns:
            Score between 0 and 1.
        """
        if paper.citation_count <= 0:
            return 0.0

        # Log10 scale normalized to 0-1 (1000 citations = 1.0)
        base_score = math.log10(paper.citation_count + 1) / 3.0

        # Influential citation bonus (up to 0.1 extra)
        if paper.influential_citation_count > 0:
            influential_bonus = min(0.1, paper.influential_citation_count * 0.01)
            base_score += influential_bonus

        return min(1.0, base_score)

    def _venue_score(self, paper: PaperMetadata) -> float:
        """Calculate venue reputation score (0-1).

        Uses case-insensitive partial matching against known venues.

        Args:
            paper: Paper metadata.

        Returns:
            Score between 0 and 1.
        """
        venue = (paper.venue or "").lower().strip()

        if not venue:
            # No venue information - use default
            return self.default_venue_score / 30.0

        # Case-insensitive partial matching
        for known_venue, points in self.venue_scores.items():
            if known_venue in venue:
                return min(1.0, points / 30.0)

        # Unknown venue - use default
        return self.default_venue_score / 30.0

    def _recency_score(self, paper: PaperMetadata) -> float:
        """Calculate recency score (0-1).

        Tiered scoring based on paper age:
        - < 1 year: 1.0
        - < 2 years: 0.75
        - < 5 years: 0.50
        - >= 5 years: 0.25

        Args:
            paper: Paper metadata.

        Returns:
            Score between 0 and 1.
        """
        if not paper.publication_date:
            # Unknown date - neutral score
            return 0.5

        now = datetime.now(timezone.utc)
        pub_date = paper.publication_date

        # Ensure publication_date is timezone-aware for comparison
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=timezone.utc)

        age_days = (now - pub_date).days

        # Handle future dates (data error)
        if age_days < 0:
            return 0.5

        # Tiered scoring
        if age_days < 365:  # < 1 year
            return 1.0
        elif age_days < 730:  # < 2 years
            return 0.75
        elif age_days < 1825:  # < 5 years
            return 0.50
        else:
            return 0.25

    def _completeness_score(self, paper: PaperMetadata) -> float:
        """Calculate metadata completeness score (0-1).

        Scores based on presence of key metadata:
        - Abstract: 0.5
        - Authors: 0.3
        - DOI: 0.2

        Args:
            paper: Paper metadata.

        Returns:
            Score between 0 and 1.
        """
        score = 0.0

        if paper.abstract and len(paper.abstract.strip()) > 0:
            score += 0.5

        if paper.authors and len(paper.authors) > 0:
            score += 0.3

        if paper.doi and len(paper.doi.strip()) > 0:
            score += 0.2

        return score

    def rank_papers(
        self,
        papers: List[PaperMetadata],
        min_score: float = 0.0,
    ) -> List[PaperMetadata]:
        """Score and rank papers by quality.

        Args:
            papers: Papers to rank.
            min_score: Minimum quality score threshold (0-100).

        Returns:
            Papers sorted by quality score (highest first),
            with quality_score field populated.
        """
        if not papers:
            return []

        scored = []

        for paper in papers:
            quality_score = self.score(paper)
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
        """Get quality tier label for a score.

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
