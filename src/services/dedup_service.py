"""
Paper deduplication service.

Multi-stage deduplication:
1. Exact DOI matching (O(1) lookup)
2. Title fuzzy matching using SequenceMatcher (>90% similarity)
"""

from difflib import SequenceMatcher
from typing import Set, List, Tuple
import re
import structlog

from src.models.paper import PaperMetadata
from src.models.dedup import DedupConfig, DedupStats

logger = structlog.get_logger()


class DeduplicationService:
    """
    Detect duplicate papers across runs.

    Maintains indices of previously processed papers for fast lookup.
    """

    def __init__(self, config: DedupConfig):
        """
        Initialize deduplication service.

        Args:
            config: Deduplication configuration
        """
        self.config = config
        self.doi_index: Set[str] = set()
        self.title_index: dict[str, str] = {}  # normalized_title → paper_id
        self.stats = DedupStats()

        if not config.enabled:
            logger.info("dedup_service_disabled")
        else:
            logger.info("dedup_service_initialized")

    def find_duplicates(
        self, papers: List[PaperMetadata]
    ) -> Tuple[List[PaperMetadata], List[PaperMetadata]]:
        """
        Separate new papers from duplicates.

        Args:
            papers: List of papers to check

        Returns:
            Tuple of (new_papers, duplicate_papers)
        """
        if not self.config.enabled:
            return papers, []

        new_papers = []
        duplicates = []

        for paper in papers:
            self.stats.total_papers_checked += 1

            if self._is_duplicate(paper):
                duplicates.append(paper)
                self.stats.duplicates_found += 1
                logger.debug(
                    "duplicate_detected",
                    paper_id=paper.paper_id,
                    title=paper.title[:50],
                )
            else:
                new_papers.append(paper)

        logger.info(
            "deduplication_complete",
            total=len(papers),
            new=len(new_papers),
            duplicates=len(duplicates),
            dedup_rate=f"{self.stats.dedup_rate:.1%}",
        )

        return new_papers, duplicates

    def _is_duplicate(self, paper: PaperMetadata) -> bool:
        """
        Check if paper is duplicate using multi-stage matching.

        Args:
            paper: Paper to check

        Returns:
            True if duplicate, False if new
        """
        # Stage 1: Exact DOI match (fastest)
        if self.config.use_doi_matching and paper.doi and paper.doi in self.doi_index:
            self.stats.duplicates_by_doi += 1
            logger.debug("duplicate_by_doi", doi=paper.doi)
            return True

        # Stage 2: Title similarity (fuzzy matching)
        if self.config.use_title_matching:
            normalized_title = self._normalize_title(paper.title)

            for existing_title in self.title_index.keys():
                similarity = SequenceMatcher(
                    None, normalized_title, existing_title
                ).ratio()

                if similarity >= self.config.title_similarity_threshold:
                    self.stats.duplicates_by_title += 1
                    logger.debug(
                        "duplicate_by_title",
                        new_title=paper.title[:50],
                        similarity=f"{similarity:.2f}",
                    )
                    return True

        # Not a duplicate
        return False

    @staticmethod
    def _normalize_title(title: str) -> str:
        """
        Normalize title for comparison.

        Args:
            title: Original title

        Returns:
            Normalized title (lowercase, no punctuation, trimmed)
        """
        # Lowercase
        title = title.lower()
        # Remove punctuation
        title = re.sub(r"[^\w\s]", "", title)
        # Remove extra whitespace
        title = " ".join(title.split())
        return title

    def update_indices(self, papers: List[PaperMetadata]):
        """
        Update indices with newly processed papers.

        Args:
            papers: Papers that were successfully processed
        """
        if not self.config.enabled:
            return

        for paper in papers:
            if paper.doi and self.config.use_doi_matching:
                self.doi_index.add(paper.doi)
                self.stats.unique_dois_indexed = len(self.doi_index)

            if self.config.use_title_matching:
                normalized_title = self._normalize_title(paper.title)
                self.title_index[normalized_title] = paper.paper_id
                self.stats.unique_titles_indexed = len(self.title_index)

        logger.debug(
            "indices_updated",
            new_dois=len([p for p in papers if p.doi]),
            new_titles=len(papers),
            total_dois=self.stats.unique_dois_indexed,
            total_titles=self.stats.unique_titles_indexed,
        )

    def get_stats(self) -> DedupStats:
        """
        Get deduplication statistics.

        Returns:
            DedupStats with current statistics
        """
        return self.stats

    def clear_indices(self):
        """Clear all deduplication indices"""
        self.doi_index.clear()
        self.title_index.clear()
        self.stats = DedupStats()
        logger.info("dedup_indices_cleared")
