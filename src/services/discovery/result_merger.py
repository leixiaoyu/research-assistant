"""Result merging and deduplication utilities (Phase 3.4)."""

import asyncio
from typing import List, Dict

import structlog

from src.models.config import ResearchTopic, ProviderType
from src.models.paper import PaperMetadata
from src.services.providers.base import DiscoveryProvider

logger = structlog.get_logger()


class ResultMerger:
    """Handles merging and deduplication of search results."""

    def __init__(self):
        """Initialize result merger."""
        pass

    def is_duplicate(
        self,
        paper: PaperMetadata,
        existing_papers: List[PaperMetadata],
        seen_ids: set,
    ) -> bool:
        """Check if a paper is a duplicate of existing papers.

        Uses two-stage deduplication:
        1. Check DOI or paper_id against seen_ids set
        2. Fall back to case-insensitive title matching

        Args:
            paper: Paper to check.
            existing_papers: List of already-collected papers.
            seen_ids: Set of unique identifiers already seen.

        Returns:
            True if paper is a duplicate, False otherwise.
        """
        unique_id = paper.doi or paper.paper_id

        # Stage 1: Check by unique identifier
        if unique_id and unique_id in seen_ids:
            return True

        # Stage 2: Check by normalized title (for papers without unique ID)
        normalized_title = paper.title.lower().strip()
        for existing in existing_papers:
            if existing.title.lower().strip() == normalized_title:
                return True

        return False

    async def apply_arxiv_supplement(
        self,
        topic: ResearchTopic,
        papers: List[PaperMetadata],
        providers: Dict[ProviderType, DiscoveryProvider],
    ) -> List[PaperMetadata]:
        """Supplement with ArXiv papers if PDF availability is below threshold.

        Phase 3.4: When pdf_strategy is ARXIV_SUPPLEMENT, if the PDF rate
        from the primary provider is below the threshold, query ArXiv
        for additional papers with guaranteed PDF availability.

        Args:
            topic: Research topic with supplement threshold.
            papers: Papers from primary provider.
            providers: Dictionary of available providers.

        Returns:
            Merged and deduplicated list of papers.
        """
        if not papers:
            # No papers from primary - try ArXiv directly
            if ProviderType.ARXIV in providers:
                logger.info("arxiv_supplement_no_primary_results")
                return await providers[ProviderType.ARXIV].search(topic)
            return []

        # Calculate PDF availability rate
        pdf_count = sum(1 for p in papers if p.pdf_available)
        pdf_rate = pdf_count / len(papers)

        logger.info(
            "arxiv_supplement_check",
            pdf_rate=f"{pdf_rate:.2f}",
            threshold=topic.arxiv_supplement_threshold,
            trigger=pdf_rate < topic.arxiv_supplement_threshold,
        )

        # Check if we need to supplement
        if pdf_rate >= topic.arxiv_supplement_threshold:
            return papers

        # ArXiv provider not available
        if ProviderType.ARXIV not in providers:
            logger.warning("arxiv_supplement_unavailable")
            return papers

        # Query ArXiv for supplementary papers
        logger.info("arxiv_supplement_triggered", pdf_rate=f"{pdf_rate:.2f}")
        try:
            arxiv_papers = await providers[ProviderType.ARXIV].search(topic)
        except Exception as e:
            logger.warning("arxiv_supplement_failed", error=str(e))
            return papers

        # Merge and deduplicate (prefer primary provider metadata)
        seen_ids: set = set()
        merged: List[PaperMetadata] = []

        # Add primary papers first
        for paper in papers:
            unique_id = paper.doi or paper.paper_id
            if unique_id:
                seen_ids.add(unique_id)
            merged.append(paper)

        # Add ArXiv papers that are not duplicates (using unified dedup logic)
        for paper in arxiv_papers:
            if not self.is_duplicate(paper, merged, seen_ids):
                unique_id = paper.doi or paper.paper_id
                if unique_id:
                    seen_ids.add(unique_id)
                merged.append(paper)

        logger.info(
            "arxiv_supplement_complete",
            original_count=len(papers),
            arxiv_added=len(merged) - len(papers),
            total_count=len(merged),
        )

        return merged

    async def benchmark_search(
        self,
        topic: ResearchTopic,
        providers: Dict[ProviderType, DiscoveryProvider],
    ) -> List[PaperMetadata]:
        """Search all providers and return deduplicated results.

        Args:
            topic: Research topic.
            providers: Dictionary of available providers.

        Returns:
            Deduplicated list of papers from all providers.
        """
        all_papers: List[PaperMetadata] = []
        seen_ids: set = set()

        # Query all providers concurrently
        tasks = []
        provider_types = []
        for provider_type, provider in providers.items():
            tasks.append(provider.search(topic))
            provider_types.append(provider_type)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for provider_type, result in zip(provider_types, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "benchmark_provider_error",
                    provider=provider_type,
                    error=str(result),
                )
                continue

            # Type is now List[PaperMetadata] after BaseException check
            papers_result: List[PaperMetadata] = result
            for paper in papers_result:
                # Use unified deduplication logic (DOI/paper_id + title matching)
                if not self.is_duplicate(paper, all_papers, seen_ids):
                    unique_id = paper.doi or paper.paper_id
                    if unique_id:
                        seen_ids.add(unique_id)
                    all_papers.append(paper)

        logger.info(
            "benchmark_complete",
            total_papers=len(all_papers),
            providers_queried=len(providers),
        )

        return all_papers
