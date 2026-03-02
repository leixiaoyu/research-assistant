"""Enhanced Discovery Service for Phase 6: 4-Stage Discovery Pipeline.

Orchestrates the enhanced paper discovery pipeline with:
1. Query Decomposition (LLM-based sub-query generation)
2. Multi-Source Retrieval (provider-aware query routing)
3. Quality Filtering (multi-signal scoring)
4. Relevance Ranking (LLM-based semantic ranking)

Usage:
    from src.services.enhanced_discovery_service import EnhancedDiscoveryService

    service = EnhancedDiscoveryService(
        providers=providers,
        query_decomposer=decomposer,
        quality_filter=quality_filter,
        relevance_ranker=ranker,
        config=config,
    )
    result = await service.discover(topic)
"""

import asyncio
import time
from typing import List, Dict, Optional, TYPE_CHECKING

import structlog

from src.models.config import ResearchTopic, ProviderType, EnhancedDiscoveryConfig
from src.models.discovery import (
    DecomposedQuery,
    ProviderCategory,
    ScoredPaper,
    DiscoveryMetrics,
    DiscoveryResult,
)
from src.models.paper import PaperMetadata
from src.services.providers.base import DiscoveryProvider

if TYPE_CHECKING:
    from src.services.query_decomposer import QueryDecomposer
    from src.services.quality_filter_service import QualityFilterService
    from src.services.relevance_ranker import RelevanceRanker

logger = structlog.get_logger()

# Provider category mapping for query routing
PROVIDER_CATEGORIES: Dict[ProviderType, ProviderCategory] = {
    ProviderType.ARXIV: ProviderCategory.COMPREHENSIVE,
    ProviderType.SEMANTIC_SCHOLAR: ProviderCategory.COMPREHENSIVE,
    ProviderType.OPENALEX: ProviderCategory.COMPREHENSIVE,
    ProviderType.HUGGINGFACE: ProviderCategory.TRENDING,
}


class EnhancedDiscoveryService:
    """Enhanced paper discovery with 4-stage retrieval and ranking pipeline.

    Implements the Phase 6 discovery enhancement:
    1. Query Decomposition: Break broad queries into focused sub-queries
    2. Multi-Source Retrieval: Query multiple providers with smart routing
    3. Quality Filtering: Score papers on multiple quality signals
    4. Relevance Ranking: LLM-based semantic relevance scoring

    Attributes:
        providers: Map of provider type to provider instance
        query_decomposer: LLM-based query decomposition service
        quality_filter: Multi-signal quality filtering service
        relevance_ranker: LLM-based relevance ranking service
        config: Enhanced discovery configuration
    """

    def __init__(
        self,
        providers: Dict[ProviderType, DiscoveryProvider],
        query_decomposer: "QueryDecomposer",
        quality_filter: "QualityFilterService",
        relevance_ranker: "RelevanceRanker",
        config: Optional[EnhancedDiscoveryConfig] = None,
    ) -> None:
        """Initialize EnhancedDiscoveryService.

        Args:
            providers: Map of provider type to provider instance
            query_decomposer: Query decomposition service
            quality_filter: Quality filtering service
            relevance_ranker: Relevance ranking service
            config: Enhanced discovery configuration (uses defaults if None)
        """
        self.providers = providers
        self.query_decomposer = query_decomposer
        self.quality_filter = quality_filter
        self.relevance_ranker = relevance_ranker
        self.config = config or EnhancedDiscoveryConfig()  # type: ignore[call-arg]

    async def discover(self, topic: ResearchTopic) -> DiscoveryResult:
        """Execute 4-stage discovery pipeline.

        Args:
            topic: Research topic with query, timeframe, and filters

        Returns:
            DiscoveryResult with ranked papers and pipeline metrics
        """
        start_time = time.time()

        logger.info(
            "enhanced_discovery_starting",
            query=topic.query[:50],
            max_papers=topic.max_papers,
            providers=list(self.providers.keys()),
        )

        # Stage 1: Query Decomposition
        queries = await self._stage1_decompose_query(topic.query)

        # Stage 2: Multi-Source Retrieval
        raw_papers = await self._stage2_retrieve_papers(queries, topic)

        # Deduplicate papers by paper_id
        deduped_papers = self._deduplicate_papers(raw_papers)

        # Stage 3: Quality Filtering
        quality_papers = self._stage3_filter_quality(deduped_papers)

        # Stage 4: Relevance Ranking (optional)
        if self.config.enable_relevance_ranking:
            ranked_papers = await self._stage4_rank_relevance(
                quality_papers, topic.query, topic.max_papers
            )
        else:
            # Skip relevance ranking, sort by quality score
            ranked_papers = sorted(
                quality_papers,
                key=lambda p: p.quality_score,
                reverse=True,
            )[: topic.max_papers]

        # Build metrics
        duration_ms = int((time.time() - start_time) * 1000)
        metrics = self._build_metrics(
            queries=queries,
            raw_papers=raw_papers,
            deduped_papers=deduped_papers,
            quality_papers=quality_papers,
            ranked_papers=ranked_papers,
            duration_ms=duration_ms,
        )

        logger.info(
            "enhanced_discovery_completed",
            query=topic.query[:50],
            papers_retrieved=len(raw_papers),
            papers_after_dedup=len(deduped_papers),
            papers_after_quality=len(quality_papers),
            papers_final=len(ranked_papers),
            duration_ms=duration_ms,
        )

        return DiscoveryResult(
            papers=ranked_papers,
            metrics=metrics,
            queries_used=queries,
        )

    async def _stage1_decompose_query(self, query: str) -> List[DecomposedQuery]:
        """Stage 1: Decompose query into focused sub-queries.

        Args:
            query: Original research query

        Returns:
            List of decomposed queries (includes original if configured)
        """
        if not self.config.enable_query_decomposition:
            # Return original query only
            from src.models.discovery import QueryFocus

            return [
                DecomposedQuery(
                    query=query,
                    focus=QueryFocus.RELATED,
                    weight=1.0,
                )
            ]

        queries = await self.query_decomposer.decompose(
            query=query,
            max_subqueries=self.config.max_subqueries,
            include_original=True,
        )

        logger.info(
            "stage1_decomposition_completed",
            original_query=query[:50],
            subqueries_count=len(queries),
        )

        return queries

    async def _stage2_retrieve_papers(
        self,
        queries: List[DecomposedQuery],
        topic: ResearchTopic,
    ) -> List[PaperMetadata]:
        """Stage 2: Retrieve papers from multiple sources.

        Routes queries to providers based on their category:
        - COMPREHENSIVE: Send all decomposed sub-queries
        - TRENDING: Send original query only

        Args:
            queries: Decomposed queries
            topic: Research topic configuration

        Returns:
            List of papers from all providers
        """
        all_papers: List[PaperMetadata] = []
        providers_queried: List[str] = []

        # Determine which providers to use
        enabled_providers = [pt for pt in self.config.providers if pt in self.providers]

        if not enabled_providers:
            logger.warning("stage2_no_providers_available")
            return []

        # Create tasks for concurrent provider queries
        tasks = []
        for provider_type in enabled_providers:
            provider = self.providers[provider_type]
            category = PROVIDER_CATEGORIES.get(
                provider_type, ProviderCategory.COMPREHENSIVE
            )

            if category == ProviderCategory.COMPREHENSIVE:
                # Send all decomposed queries
                for dq in queries:
                    # Create topic copy with sub-query
                    sub_topic = self._create_sub_topic(topic, dq.query)
                    tasks.append(self._search_provider(provider, sub_topic))
            else:
                # TRENDING: Send original query only
                tasks.append(self._search_provider(provider, topic))

            providers_queried.append(provider.name)

        # Execute all searches concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "stage2_provider_search_failed",
                    error=str(result),
                )
                continue
            all_papers.extend(result)  # type: ignore[arg-type]

        logger.info(
            "stage2_retrieval_completed",
            providers_queried=providers_queried,
            total_papers=len(all_papers),
        )

        return all_papers

    async def _search_provider(
        self,
        provider: DiscoveryProvider,
        topic: ResearchTopic,
    ) -> List[PaperMetadata]:
        """Search a single provider with error handling.

        Args:
            provider: Provider to search
            topic: Research topic

        Returns:
            List of papers (empty on error)
        """
        try:
            papers = await provider.search(topic)
            logger.debug(
                "provider_search_completed",
                provider=provider.name,
                papers_found=len(papers),
            )
            return papers
        except Exception as e:
            logger.warning(
                "provider_search_failed",
                provider=provider.name,
                error=str(e),
            )
            return []

    def _create_sub_topic(
        self, original: ResearchTopic, sub_query: str
    ) -> ResearchTopic:
        """Create a topic copy with a different query.

        Args:
            original: Original topic configuration
            sub_query: Sub-query to use

        Returns:
            New ResearchTopic with sub-query
        """
        return ResearchTopic(
            query=sub_query,
            provider=original.provider,
            timeframe=original.timeframe,
            max_papers=self.config.papers_per_provider,
            min_citations=original.min_citations,
            pdf_strategy=original.pdf_strategy,
        )

    def _deduplicate_papers(self, papers: List[PaperMetadata]) -> List[PaperMetadata]:
        """Deduplicate papers by paper_id.

        Args:
            papers: Papers to deduplicate

        Returns:
            Unique papers (first occurrence kept)
        """
        seen: set[str] = set()
        unique: List[PaperMetadata] = []

        for paper in papers:
            if paper.paper_id not in seen:
                seen.add(paper.paper_id)
                unique.append(paper)

        if len(papers) != len(unique):
            logger.debug(
                "deduplication_completed",
                before=len(papers),
                after=len(unique),
                duplicates_removed=len(papers) - len(unique),
            )

        return unique

    def _stage3_filter_quality(self, papers: List[PaperMetadata]) -> List[ScoredPaper]:
        """Stage 3: Filter papers by quality signals.

        Args:
            papers: Papers to filter

        Returns:
            Papers with quality scores, filtered by threshold
        """
        scored_papers = self.quality_filter.filter_and_score(papers)

        logger.info(
            "stage3_quality_filtering_completed",
            input_papers=len(papers),
            output_papers=len(scored_papers),
        )

        return scored_papers

    async def _stage4_rank_relevance(
        self,
        papers: List[ScoredPaper],
        query: str,
        top_k: int,
    ) -> List[ScoredPaper]:
        """Stage 4: Rank papers by semantic relevance.

        Args:
            papers: Papers with quality scores
            query: Original research query
            top_k: Maximum papers to return

        Returns:
            Papers ranked by combined quality + relevance
        """
        ranked_papers = await self.relevance_ranker.rank(
            papers=papers,
            query=query,
            top_k=top_k,
        )

        logger.info(
            "stage4_relevance_ranking_completed",
            input_papers=len(papers),
            output_papers=len(ranked_papers),
        )

        return ranked_papers

    def _build_metrics(
        self,
        queries: List[DecomposedQuery],
        raw_papers: List[PaperMetadata],
        deduped_papers: List[PaperMetadata],
        quality_papers: List[ScoredPaper],
        ranked_papers: List[ScoredPaper],
        duration_ms: int,
    ) -> DiscoveryMetrics:
        """Build pipeline execution metrics.

        Args:
            queries: Decomposed queries used
            raw_papers: Papers before deduplication
            deduped_papers: Papers after deduplication
            quality_papers: Papers after quality filtering
            ranked_papers: Final ranked papers
            duration_ms: Total pipeline duration

        Returns:
            DiscoveryMetrics with pipeline statistics
        """
        # Calculate average scores
        avg_quality = 0.0
        avg_relevance = 0.0

        if ranked_papers:
            quality_sum = sum(p.quality_score for p in ranked_papers)
            avg_quality = quality_sum / len(ranked_papers)
            relevance_scores = [
                p.relevance_score
                for p in ranked_papers
                if p.relevance_score is not None
            ]
            if relevance_scores:
                avg_relevance = sum(relevance_scores) / len(relevance_scores)

        return DiscoveryMetrics(
            queries_generated=len(queries),
            papers_retrieved=len(raw_papers),
            papers_after_dedup=len(deduped_papers),
            papers_after_quality_filter=len(quality_papers),
            papers_after_relevance_filter=len(ranked_papers),
            providers_queried=[pt.value for pt in self.providers.keys()],
            avg_quality_score=avg_quality,
            avg_relevance_score=avg_relevance,
            pipeline_duration_ms=duration_ms,
        )

    async def close(self) -> None:
        """Close all provider connections."""
        for provider in self.providers.values():
            if hasattr(provider, "close"):
                await provider.close()

    async def __aenter__(self) -> "EnhancedDiscoveryService":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
