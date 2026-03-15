"""Discovery Filter Service for Phase 7.1: Discovery Foundation.

Filters discovered papers against the registry to remove duplicates
and optionally registers new papers at discovery time.

This enables:
- Deduplication before quality filtering (save LLM costs)
- Early registration to prevent reprocessing
- Incremental discovery with overlap handling
"""

from typing import List, Optional
import structlog

from src.models.paper import PaperMetadata
from src.models.discovery import (
    DiscoveryFilterResult,
    FilteredPaper,
    DiscoveryStats,
)
from src.services.registry_service import RegistryService

logger = structlog.get_logger()

# Rebuild Pydantic models to resolve forward references
FilteredPaper.model_rebuild()
DiscoveryFilterResult.model_rebuild()


class DiscoveryFilter:
    """Filter discovered papers against the registry for deduplication.

    Uses the RegistryService's multi-stage identity resolution:
    1. DOI exact match (highest priority)
    2. ArXiv ID exact match
    3. Provider ID exact match
    4. Normalized title fuzzy match (≥95% similarity)

    Optionally registers new papers at discovery time with discovery_only=True
    to enable deduplication without requiring full extraction.
    """

    def __init__(
        self,
        registry_service: RegistryService,
        skip_filter: bool = False,
    ):
        """Initialize the discovery filter.

        Args:
            registry_service: Registry service for identity resolution.
            skip_filter: If True, bypass filtering and return all papers as new.
        """
        self.registry = registry_service
        self.skip_filter = skip_filter

        logger.info(
            "discovery_filter_initialized",
            skip_filter=skip_filter,
        )

    async def filter_papers(
        self,
        papers: List[PaperMetadata],
        topic_slug: str,
        register_new: bool = True,
    ) -> DiscoveryFilterResult:
        """Filter papers against registry and optionally register new ones.

        Args:
            papers: List of papers discovered from provider.
            topic_slug: Topic slug for affiliation tracking.
            register_new: Whether to register new papers at discovery time.

        Returns:
            DiscoveryFilterResult with new papers, filtered papers, and stats.
        """
        total_discovered = len(papers)

        # Skip filtering if disabled
        if self.skip_filter:
            logger.info(
                "discovery_filter_skipped",
                total_discovered=total_discovered,
                topic=topic_slug,
            )
            return DiscoveryFilterResult(
                new_papers=papers,
                filtered_papers=[],
                stats=DiscoveryStats(
                    total_discovered=total_discovered,
                    new_count=total_discovered,
                    filtered_count=0,
                    filter_breakdown={},
                    incremental_query=False,
                ),
            )

        # Track filtering results
        new_papers: List[PaperMetadata] = []
        filtered_papers: List[FilteredPaper] = []
        filter_breakdown: dict[str, int] = {
            "doi": 0,
            "arxiv": 0,
            "title": 0,
            "provider_id": 0,
        }

        # Check each paper against registry
        for paper in papers:
            duplicate_reason = self._check_duplicate(paper)

            if duplicate_reason:
                # Paper is duplicate - get the matched entry for tracking
                match = self.registry.resolve_identity(paper)
                matched_entry_id = match.entry.paper_id if match.entry else "unknown"

                filtered_papers.append(
                    FilteredPaper(
                        paper=paper,
                        filter_reason=duplicate_reason,
                        matched_entry_id=matched_entry_id,
                    )
                )

                # Update breakdown stats
                if duplicate_reason in filter_breakdown:
                    filter_breakdown[duplicate_reason] += 1

                logger.debug(
                    "paper_filtered_duplicate",
                    paper_id=paper.paper_id,
                    title=paper.title[:50] if paper.title else "N/A",
                    reason=duplicate_reason,
                    matched_entry=matched_entry_id,
                )
            else:
                # Paper is new
                new_papers.append(paper)

                # Register at discovery time if enabled
                if register_new:
                    try:
                        self.registry.register_paper(
                            paper=paper,
                            topic_slug=topic_slug,
                            extraction_targets=None,
                            discovery_only=True,
                        )
                        logger.debug(
                            "paper_registered_at_discovery",
                            paper_id=paper.paper_id,
                            title=paper.title[:50] if paper.title else "N/A",
                        )
                    except Exception as e:
                        logger.warning(
                            "discovery_registration_failed",
                            paper_id=paper.paper_id,
                            error=str(e),
                        )

        # Build statistics
        stats = DiscoveryStats(
            total_discovered=total_discovered,
            new_count=len(new_papers),
            filtered_count=len(filtered_papers),
            filter_breakdown=filter_breakdown,
            incremental_query=False,  # Caller can update this
        )

        logger.info(
            "discovery_filter_complete",
            topic=topic_slug,
            total_discovered=total_discovered,
            new_count=len(new_papers),
            filtered_count=len(filtered_papers),
            filter_breakdown=filter_breakdown,
        )

        return DiscoveryFilterResult(
            new_papers=new_papers,
            filtered_papers=filtered_papers,
            stats=stats,
        )

    def _check_duplicate(self, paper: PaperMetadata) -> Optional[str]:
        """Check if paper is duplicate using registry identity resolution.

        Args:
            paper: Paper to check against registry.

        Returns:
            Filter reason if duplicate, None if new.
            Reasons: "doi", "arxiv", "provider_id", "title"
        """
        # Use registry's identity resolution
        match = self.registry.resolve_identity(paper)

        if not match.matched:
            return None

        # Map match method to filter reason
        match_method = match.match_method or "unknown"

        # DOI match
        if match_method == "doi":
            return "doi"

        # ArXiv match
        if match_method == "arxiv":
            return "arxiv"

        # Title match
        if match_method == "title":
            return "title"

        # Provider ID match (semantic_scholar, etc.)
        if match_method in ["semantic_scholar", "huggingface", "openalex"]:
            return "provider_id"

        # Fallback for unknown match methods
        logger.warning(
            "unknown_match_method",
            method=match_method,
            paper_id=paper.paper_id,
        )
        return "provider_id"
