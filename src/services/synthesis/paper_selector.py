"""Paper selection for cross-topic synthesis.

Handles quality-weighted sampling with diversity for selecting papers
that best answer synthesis questions.
"""

from typing import List, Tuple
import structlog

from src.models.cross_synthesis import (
    SynthesisQuestion,
    PaperSummary,
)
from src.models.registry import RegistryEntry
from src.services.registry_service import RegistryService
from src.utils.author_utils import normalize_authors

logger = structlog.get_logger()

# Diversity sampling ratio (20% of budget for diversity)
DIVERSITY_RATIO = 0.20


class PaperSelector:
    """Selects papers for synthesis using quality-weighted sampling.

    Provides methods for:
    - Converting registry entries to paper summaries
    - Filtering papers by topic and quality
    - Diversity-aware sampling
    """

    def __init__(self, registry_service: RegistryService):
        """Initialize paper selector.

        Args:
            registry_service: Registry service for paper access.
        """
        self.registry = registry_service

    def get_all_entries(self) -> List[RegistryEntry]:
        """Get all entries from the registry.

        Returns:
            List of all registry entries.
        """
        state = self.registry.load()
        return list(state.entries.values())

    def entry_to_summary(self, entry: RegistryEntry) -> PaperSummary:
        """Convert a registry entry to a paper summary.

        Args:
            entry: Registry entry to convert.

        Returns:
            PaperSummary for prompt building.
        """
        metadata = entry.metadata_snapshot or {}

        # Extract authors (handles List[dict], List[str], str, None)
        authors = normalize_authors(metadata.get("authors"))

        # Extract quality score
        quality_score = metadata.get("quality_score", 0.0)
        if not isinstance(quality_score, (int, float)):
            quality_score = 0.0

        # Extract extraction results for summary
        extraction_summary = None
        if "extraction_results" in metadata:
            extraction_summary = metadata["extraction_results"]

        return PaperSummary(
            paper_id=entry.paper_id,
            title=metadata.get("title", entry.title_normalized),
            authors=authors,
            abstract=metadata.get("abstract"),
            publication_date=metadata.get("publication_date"),
            quality_score=float(quality_score),
            topics=entry.topic_affiliations,
            extraction_summary=extraction_summary,
        )

    def _filter_entries(
        self,
        entries: List[RegistryEntry],
        question: SynthesisQuestion,
    ) -> List[Tuple[RegistryEntry, float]]:
        """Filter entries by topic and quality criteria.

        Args:
            entries: All registry entries.
            question: Question with filtering criteria.

        Returns:
            List of (entry, quality_score) tuples passing filters.
        """
        filtered = []
        for entry in entries:
            # Check topic inclusion
            if question.topic_filters:
                if not any(
                    t in entry.topic_affiliations for t in question.topic_filters
                ):
                    continue

            # Check topic exclusion
            if any(t in entry.topic_affiliations for t in question.topic_exclude):
                continue

            # Get quality score from metadata
            metadata = entry.metadata_snapshot or {}
            quality_score = metadata.get("quality_score", 0.0)
            if not isinstance(quality_score, (int, float)):
                quality_score = 0.0

            # Check quality threshold
            if quality_score < question.min_quality_score:
                continue

            filtered.append((entry, float(quality_score)))

        return filtered

    def _apply_diversity_sampling(
        self,
        filtered: List[Tuple[RegistryEntry, float]],
        max_papers: int,
    ) -> List[RegistryEntry]:
        """Apply diversity-aware sampling to filtered entries.

        Algorithm:
        - 80% budget: top quality papers
        - 20% budget: ensure topic diversity

        Args:
            filtered: Sorted list of (entry, quality_score) tuples.
            max_papers: Maximum papers to select.

        Returns:
            List of selected entries.
        """
        quality_budget = int(max_papers * (1 - DIVERSITY_RATIO))  # 80% for quality

        # Take top quality papers
        selected_entries = [e for e, _ in filtered[:quality_budget]]
        remaining = filtered[quality_budget:]

        # Ensure topic diversity in remaining budget
        topics_covered = set()
        for entry in selected_entries:
            topics_covered.update(entry.topic_affiliations)

        for entry, _ in remaining:
            if len(selected_entries) >= max_papers:
                break
            # Prefer papers from underrepresented topics
            new_topics = set(entry.topic_affiliations) - topics_covered
            if new_topics:
                selected_entries.append(entry)
                topics_covered.update(entry.topic_affiliations)

        # Fill remaining slots if diversity didn't use all budget
        for entry, _ in remaining:
            if len(selected_entries) >= max_papers:
                break
            if entry not in selected_entries:
                selected_entries.append(entry)

        return selected_entries

    def select_papers(
        self,
        question: SynthesisQuestion,
    ) -> List[PaperSummary]:
        """Select papers for synthesis using quality-weighted sampling.

        Algorithm:
        1. Get all registry entries
        2. Filter by topic_filters and topic_exclude
        3. Filter by min_quality_score
        4. Sort by quality_score (descending)
        5. Diversity sampling:
           - 80% budget: top quality papers
           - 20% budget: ensure topic diversity
        6. Limit to max_papers

        Args:
            question: Synthesis question with filtering criteria.

        Returns:
            List of PaperSummary objects for synthesis.
        """
        # 1. Get all entries from registry
        all_entries = self.get_all_entries()

        if not all_entries:
            logger.info("select_papers_no_entries")
            return []

        # 2. Apply topic and quality filters
        filtered = self._filter_entries(all_entries, question)

        if not filtered:
            logger.info(
                "select_papers_none_after_filter",
                topic_filters=question.topic_filters,
                topic_exclude=question.topic_exclude,
                min_quality=question.min_quality_score,
            )
            return []

        # 3. Sort by quality (descending)
        filtered.sort(key=lambda x: x[1], reverse=True)

        # 4. Diversity sampling
        selected_entries = self._apply_diversity_sampling(filtered, question.max_papers)

        # Collect topics covered for logging
        topics_covered = set()
        for entry in selected_entries:
            topics_covered.update(entry.topic_affiliations)

        # Convert to summaries
        summaries = [self.entry_to_summary(e) for e in selected_entries]

        logger.info(
            "papers_selected",
            question_id=question.id,
            total_entries=len(all_entries),
            after_filter=len(filtered),
            selected=len(summaries),
            topics_covered=len(topics_covered),
        )

        return summaries
