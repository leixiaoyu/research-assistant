"""Quality Filter Service for Phase 6: Enhanced Discovery Pipeline.

.. deprecated::
    QualityFilterService is deprecated in favor of QualityIntelligenceService.
    All functionality has been merged into QualityIntelligenceService which
    provides consistent scoring math (log1p), scale (0-1.0), and venue data (JSON).

This module is preserved for backward compatibility. New code should use
QualityIntelligenceService directly.

Usage:
    from src.services.quality_intelligence_service import QualityIntelligenceService

    service = QualityIntelligenceService(min_quality_score=0.3)
    scored_papers = service.filter_and_score(papers)
"""

from pathlib import Path
from typing import List, Optional, Dict

import structlog

from src.models.discovery import QualityWeights, ScoredPaper
from src.models.paper import PaperMetadata
from src.services.quality_intelligence_service import (
    QualityIntelligenceService,
    load_venue_scores_json,
)

logger = structlog.get_logger()


class QualityFilterService:
    """Multi-signal quality filtering for academic papers.

    .. deprecated::
        QualityFilterService is deprecated. Use QualityIntelligenceService.

    This class now delegates to QualityIntelligenceService for all scoring.
    It is preserved for backward compatibility with existing imports.
    """

    # =========================================================================
    # Scoring Constants (deprecated - use QualityIntelligenceService constants)
    # =========================================================================

    CITATION_NORMALIZATION_FACTOR: float = 10.0
    RECENCY_DECAY_RATE: float = 0.2
    RECENCY_MIN_SCORE: float = 0.1
    ENGAGEMENT_NORMALIZATION_FACTOR: float = 7.0
    MIN_ABSTRACT_LENGTH: int = 50
    DEFAULT_SCORE: float = 0.5

    COMPLETENESS_WEIGHT_ABSTRACT: float = 0.3
    COMPLETENESS_WEIGHT_AUTHORS: float = 0.2
    COMPLETENESS_WEIGHT_VENUE: float = 0.2
    COMPLETENESS_WEIGHT_PDF: float = 0.2
    COMPLETENESS_WEIGHT_DOI: float = 0.1

    DEFAULT_VENUE_SCORES: Dict[str, float] = {
        "neurips": 1.0,
        "icml": 1.0,
        "iclr": 0.93,
        "acl": 1.0,
        "emnlp": 1.0,
        "naacl": 0.93,
        "coling": 0.85,
        "nature": 1.0,
        "science": 1.0,
        "cell": 1.0,
        "jmlr": 0.95,
        "tacl": 0.9,
        "pnas": 0.9,
        "arxiv": 0.6,
        "biorxiv": 0.6,
        "medrxiv": 0.6,
    }

    def __init__(
        self,
        min_citations: int = 0,
        min_quality_score: float = 0.3,
        weights: Optional[QualityWeights] = None,
        venue_data_path: Optional[str] = None,
    ) -> None:
        """Initialize QualityFilterService.

        .. deprecated::
            Use QualityIntelligenceService directly.

        Args:
            min_citations: Minimum citation count to include
            min_quality_score: Minimum quality score (0.0-1.0)
            weights: Custom weights for quality signals
            venue_data_path: Path to venue rankings JSON file
        """
        # Start with DEFAULT_VENUE_SCORES as fallback
        default_venues = dict(self.DEFAULT_VENUE_SCORES)

        # Try to load from file
        if venue_data_path:
            path = Path(venue_data_path)
            if path.exists():
                loaded_venues, _ = load_venue_scores_json(path)
                # Merge loaded venues over defaults
                default_venues.update(loaded_venues)

        # Create delegate with merged venue scores
        self._delegate = QualityIntelligenceService(
            venue_scores_path=None,  # Don't let delegate load from default
            weights=weights,
            min_quality_score=min_quality_score,
            min_citations=min_citations,
        )
        # Override delegate's venue_scores with our merged version
        self._delegate.venue_scores = default_venues

        # Preserve backward-compatible attributes
        self.min_citations = min_citations
        self.min_quality_score = min_quality_score
        self.weights = self._delegate.weights
        self.venue_scores = self._delegate.venue_scores

        logger.info(
            "quality_filter_service_initialized",
            min_citations=min_citations,
            min_quality_score=min_quality_score,
            venue_count=len(self.venue_scores),
        )

    def filter_and_score(
        self,
        papers: List[PaperMetadata],
        weights: Optional[QualityWeights] = None,
    ) -> List[ScoredPaper]:
        """Filter papers by quality and compute composite scores.

        Args:
            papers: List of papers to filter
            weights: Optional custom weights (overrides instance weights)

        Returns:
            List of papers with quality scores, filtered by min_quality_score
        """
        return self._delegate.filter_and_score(papers, weights)

    def calculate_quality_score(
        self,
        paper: PaperMetadata,
        weights: Optional[QualityWeights] = None,
    ) -> float:
        """Calculate quality score for a single paper.

        Public method for scoring individual papers without filtering.

        Args:
            paper: Paper to score
            weights: Optional custom weights (overrides instance weights)

        Returns:
            Quality score between 0.0 and 1.0
        """
        return self._delegate.score(paper)

    def _load_venue_scores(self, venue_data_path: Optional[str]) -> Dict[str, float]:
        """Load venue scores from file or use defaults.

        .. deprecated::
            Internal method. Use QualityIntelligenceService directly.

        Args:
            venue_data_path: Path to JSON file with venue rankings

        Returns:
            Dictionary mapping normalized venue names to scores
        """
        return self._delegate.venue_scores

    def _calculate_quality_score(
        self,
        paper: PaperMetadata,
        weights: QualityWeights,
    ) -> float:
        """Calculate composite quality score for a paper.

        .. deprecated::
            Internal method. Use QualityIntelligenceService.score().

        Returns:
            Quality score between 0.0 and 1.0
        """
        return self._delegate._calculate_quality_score_with_weights(paper, weights)

    def _calculate_citation_score(self, paper: PaperMetadata) -> float:
        """Logarithmic citation score (0-1 range)."""
        return self._delegate._calculate_citation_score(paper)

    def _calculate_venue_score(self, paper: PaperMetadata) -> float:
        """Venue quality score based on rankings."""
        return self._delegate._calculate_venue_score(paper)

    def _calculate_recency_score(self, paper: PaperMetadata) -> float:
        """Recency score with 5-year half-life decay."""
        return self._delegate._calculate_recency_score(paper)

    def _calculate_engagement_score(self, paper: PaperMetadata) -> float:
        """Engagement score from community signals."""
        return self._delegate._calculate_engagement_score(paper)

    def _calculate_completeness_score(self, paper: PaperMetadata) -> float:
        """Metadata completeness score."""
        return self._delegate._calculate_completeness_score(paper)

    def _calculate_author_score(self, paper: PaperMetadata) -> float:
        """Author reputation score."""
        return self._delegate._calculate_author_score(paper)

    def _normalize_venue(self, venue: str) -> str:
        """Normalize venue name for matching."""
        if not venue:
            return ""
        normalized = venue.lower()
        normalized = "".join(c for c in normalized if not c.isdigit())
        normalized = "".join(c for c in normalized if c.isalnum() or c.isspace())
        for word in ["proceedings", "conference", "journal", "international"]:
            normalized = normalized.replace(word, "")
        normalized = " ".join(normalized.split())
        return normalized.strip()
