"""Quality Filter Service for Phase 6: Enhanced Discovery Pipeline.

Filters and scores papers based on multiple quality signals:
- Citation count (logarithmic normalization)
- Venue quality (CORE/SJR rankings)
- Recency (5-year half-life decay)
- Engagement (HuggingFace upvotes)
- Metadata completeness
- Author reputation (h-index)

Usage:
    from src.services.quality_filter_service import QualityFilterService

    service = QualityFilterService(min_quality_score=0.3)
    scored_papers = service.filter_and_score(papers)
"""

import math
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict
import json

import structlog

from src.models.discovery import QualityWeights, ScoredPaper
from src.models.paper import PaperMetadata

logger = structlog.get_logger()


class QualityFilterService:
    """Multi-signal quality filtering for academic papers.

    Combines multiple quality signals to compute a composite score
    and filter papers below a minimum threshold.

    Attributes:
        min_citations: Minimum citation count threshold
        min_quality_score: Minimum quality score to include (0.0-1.0)
        weights: Weights for quality signal combination
        venue_scores: Mapping of venue names to quality scores
    """

    # Default venue scores for common venues (can be extended)
    DEFAULT_VENUE_SCORES: Dict[str, float] = {
        # Top-tier conferences (A*)
        "neurips": 1.0,
        "icml": 1.0,
        "iclr": 1.0,
        "acl": 1.0,
        "emnlp": 1.0,
        "cvpr": 1.0,
        "iccv": 1.0,
        "eccv": 0.95,
        "aaai": 0.95,
        "ijcai": 0.95,
        "naacl": 0.9,
        "coling": 0.85,
        # Top-tier journals
        "nature": 1.0,
        "science": 1.0,
        "cell": 1.0,
        "jmlr": 0.95,
        "tacl": 0.9,
        "pnas": 0.9,
        # Preprint servers (lower score but not penalized heavily)
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

        Args:
            min_citations: Minimum citation count to include
            min_quality_score: Minimum quality score (0.0-1.0)
            weights: Custom weights for quality signals
            venue_data_path: Path to venue rankings JSON file
        """
        self.min_citations = min_citations
        self.min_quality_score = min_quality_score
        self.weights = weights or QualityWeights()  # type: ignore[call-arg]
        self.venue_scores = self._load_venue_scores(venue_data_path)

    def _load_venue_scores(self, venue_data_path: Optional[str]) -> Dict[str, float]:
        """Load venue scores from file or use defaults.

        Args:
            venue_data_path: Path to JSON file with venue rankings

        Returns:
            Dictionary mapping normalized venue names to scores
        """
        scores = dict(self.DEFAULT_VENUE_SCORES)

        if venue_data_path:
            path = Path(venue_data_path)
            if path.exists():
                try:
                    with open(path, "r") as f:
                        data = json.load(f)
                        venues = data.get("venues", data)
                        for venue, info in venues.items():
                            if isinstance(info, dict):
                                score = info.get("score", 0.5)
                            else:
                                score = info
                            scores[self._normalize_venue(venue)] = score
                    logger.info(
                        "quality_filter_venue_data_loaded",
                        path=str(path),
                        venues_count=len(scores),
                    )
                except Exception as e:
                    logger.warning(
                        "quality_filter_venue_data_error",
                        path=str(path),
                        error=str(e),
                    )

        return scores

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
            quality_score = self._calculate_quality_score(paper, effective_weights)

            # Check quality threshold
            if quality_score < self.min_quality_score:
                filtered_count += 1
                continue

            # Get engagement score if available
            engagement_score = getattr(paper, "upvotes", 0) or 0

            # Create scored paper
            scored_paper = ScoredPaper.from_paper_metadata(
                paper=paper,
                quality_score=quality_score,
                engagement_score=float(engagement_score),
            )
            scored_papers.append(scored_paper)

        logger.info(
            "quality_filter_completed",
            papers_input=len(papers),
            papers_output=len(scored_papers),
            papers_filtered=filtered_count,
        )

        return scored_papers

    def _calculate_quality_score(
        self,
        paper: PaperMetadata,
        weights: QualityWeights,
    ) -> float:
        """Calculate composite quality score for a paper.

        Args:
            paper: Paper to score
            weights: Weights for each signal

        Returns:
            Quality score between 0.0 and 1.0
        """
        # Calculate individual signal scores
        citation_score = self._calculate_citation_score(paper)
        venue_score = self._calculate_venue_score(paper)
        recency_score = self._calculate_recency_score(paper)
        engagement_score = self._calculate_engagement_score(paper)
        completeness_score = self._calculate_completeness_score(paper)
        author_score = self._calculate_author_score(paper)

        # Compute weighted average
        total_weight = weights.total_weight
        if total_weight == 0:
            return 0.5  # Default if no weights

        score = (
            weights.citation * citation_score
            + weights.venue * venue_score
            + weights.recency * recency_score
            + weights.engagement * engagement_score
            + weights.completeness * completeness_score
            + weights.author * author_score
        ) / total_weight

        return min(1.0, max(0.0, score))

    def _calculate_citation_score(self, paper: PaperMetadata) -> float:
        """Logarithmic citation score (0-1 range).

        Uses log1p normalization with scale factor of 10.
        - 0 citations -> 0.0
        - 10 citations -> ~0.24
        - 100 citations -> ~0.46
        - 1000 citations -> ~0.69
        - 10000 citations -> ~0.92

        Args:
            paper: Paper to score

        Returns:
            Citation score (0.0-1.0)
        """
        citation_count = paper.citation_count or 0
        return min(1.0, math.log1p(citation_count) / 10)

    def _calculate_venue_score(self, paper: PaperMetadata) -> float:
        """Venue quality score based on rankings.

        Args:
            paper: Paper to score

        Returns:
            Venue score (0.0-1.0), default 0.5 for unknown venues
        """
        if not paper.venue:
            return 0.5  # Default for no venue

        venue_key = self._normalize_venue(paper.venue)

        # Check for exact match
        if venue_key in self.venue_scores:
            return self.venue_scores[venue_key]

        # Check for partial match
        for known_venue, score in self.venue_scores.items():
            if known_venue in venue_key or venue_key in known_venue:
                return score

        return 0.5  # Default for unknown venues

    def _calculate_recency_score(self, paper: PaperMetadata) -> float:
        """Recency score with 5-year half-life decay.

        Newer papers get higher scores:
        - This year -> 1.0
        - 1 year old -> ~0.83
        - 2 years old -> ~0.71
        - 5 years old -> ~0.5
        - 10 years old -> ~0.33

        Args:
            paper: Paper to score

        Returns:
            Recency score (0.1-1.0)
        """
        if not paper.publication_date:
            return 0.5  # Default for unknown date

        try:
            # Parse publication date
            if isinstance(paper.publication_date, str):
                # Handle various date formats
                date_str = paper.publication_date
                if len(date_str) == 4:  # Year only
                    pub_year = int(date_str)
                elif len(date_str) >= 7:  # YYYY-MM or YYYY-MM-DD
                    pub_year = int(date_str[:4])
                else:
                    return 0.5
            else:
                pub_year = paper.publication_date.year

            current_year = datetime.now().year
            years_old = max(0, current_year - pub_year)

            # Half-life decay: score = 1 / (1 + 0.2 * years)
            return max(0.1, 1.0 / (1 + 0.2 * years_old))

        except (ValueError, AttributeError):
            return 0.5  # Default for parse errors

    def _calculate_engagement_score(self, paper: PaperMetadata) -> float:
        """Engagement score from community signals (e.g., upvotes).

        Important for HuggingFace Daily Papers which may have
        high engagement but zero citations due to recency.

        Args:
            paper: Paper to score

        Returns:
            Engagement score (0.0-1.0)
        """
        # Get upvotes if available
        upvotes = getattr(paper, "upvotes", 0) or 0

        if upvotes == 0:
            return 0.0

        # Logarithmic scaling: normalize to 0-1 range
        # 10 upvotes -> ~0.35
        # 50 upvotes -> ~0.56
        # 100 upvotes -> ~0.66
        # 500 upvotes -> ~0.86
        return min(1.0, math.log1p(upvotes) / 7)

    def _calculate_completeness_score(self, paper: PaperMetadata) -> float:
        """Metadata completeness score.

        Checks presence of key metadata fields:
        - Abstract
        - Authors
        - Venue
        - PDF URL
        - DOI

        Args:
            paper: Paper to score

        Returns:
            Completeness score (0.0-1.0)
        """
        score = 0.0
        checks = 0.0

        # Required fields (higher weight)
        if paper.abstract and len(paper.abstract) > 50:
            score += 0.3
        checks += 0.3

        if paper.authors and len(paper.authors) > 0:
            score += 0.2
        checks += 0.2

        # Optional but valuable fields
        if paper.venue:
            score += 0.2
        checks += 0.2

        if paper.open_access_pdf or paper.pdf_available:
            score += 0.2
        checks += 0.2

        if paper.doi:
            score += 0.1
        checks += 0.1

        return score / checks if checks > 0 else 0.5

    def _calculate_author_score(self, paper: PaperMetadata) -> float:
        """Author reputation score.

        Currently returns default as author h-index data
        is not typically available from providers.

        Args:
            paper: Paper to score

        Returns:
            Author score (0.0-1.0), default 0.5
        """
        # Author h-index not typically available from APIs
        # Would need additional author lookup service
        # For now, return default
        return 0.5

    def _normalize_venue(self, venue: str) -> str:
        """Normalize venue name for matching.

        Args:
            venue: Raw venue name

        Returns:
            Normalized lowercase name
        """
        if not venue:
            return ""

        # Lowercase and remove common suffixes
        normalized = venue.lower()
        # Remove year suffixes like "2023" or "2024"
        normalized = "".join(c for c in normalized if not c.isdigit())
        # Remove special characters
        normalized = "".join(c for c in normalized if c.isalnum() or c.isspace())
        # Remove common words
        for word in ["proceedings", "conference", "journal", "international"]:
            normalized = normalized.replace(word, "")
        # Collapse whitespace
        normalized = " ".join(normalized.split())
        return normalized.strip()
