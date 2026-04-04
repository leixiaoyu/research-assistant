"""Discovery service with multi-provider intelligence (Phase 3.2, 3.4, 6 & 7.2)."""

import asyncio
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING

import structlog

from src.services.providers.base import DiscoveryProvider, APIError
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.services.providers.arxiv import ArxivProvider
from src.services.providers.huggingface import HuggingFaceProvider
from src.services.providers.openalex import OpenAlexProvider
from src.models.config import (
    ResearchTopic,
    ProviderType,
    ProviderSelectionConfig,
    PDFStrategy,
    EnhancedDiscoveryConfig,
    CitationExplorationConfig,
    QueryExpansionConfig,
    AggregationConfig,
    GlobalSettings,
)
from src.models.paper import PaperMetadata
from src.models.provider import ProviderMetrics, ProviderComparison
from src.models.discovery import DiscoveryResult
from src.utils.provider_selector import ProviderSelector
from src.services.quality_scorer import QualityScorer

# Internal modules
from .metrics import MetricsCollector
from .result_merger import ResultMerger

# Phase 6: Enhanced Discovery Pipeline imports
if TYPE_CHECKING:
    from src.services.llm import LLMService
    from src.services.enhanced_discovery_service import EnhancedDiscoveryService

logger = structlog.get_logger()


class DiscoveryService:
    """Orchestrates paper discovery across multiple providers.

    This service provides two search modes:

    1. **Basic Search** (search method):
       - Direct provider queries with intelligent fallback
       - Provider selection based on query characteristics
       - Quality scoring and PDF availability tracking

    2. **Enhanced Search** (enhanced_search method):
       - 4-stage pipeline: Query Decomposition → Multi-Source Retrieval
         → Quality Filtering → Relevance Ranking
       - LLM-powered query expansion and relevance scoring
       - Delegated to EnhancedDiscoveryService (composition pattern)

    Architecture:
        DiscoveryService acts as a facade that coordinates:
        - Multiple DiscoveryProvider implementations (ArXiv, SemanticScholar, etc.)
        - Optional EnhancedDiscoveryService for advanced pipeline (Phase 6)

        The EnhancedDiscoveryService can be injected via constructor for:
        - Easier testing with mock dependencies
        - Custom pipeline configurations
        - Decoupled component management

    Phase Features:
        3.2: Intelligent provider selection, fallback, benchmark mode
        3.4: Quality-first ranking, PDF tracking, ArXiv supplement
        6.0: Enhanced 4-stage pipeline with LLM integration
        7.2: Multi-source discovery with citation exploration

    Provider Categories:
        - Comprehensive: ArXiv, SemanticScholar, OpenAlex (query-based)
        - Trending: HuggingFace (curated/trending papers)
    """

    # Sampling providers return trending/curated results only.
    # Empty results from these providers should trigger fallback.
    SAMPLING_PROVIDERS = {ProviderType.HUGGINGFACE}

    def __init__(
        self,
        api_key: str = "",
        config: Optional[ProviderSelectionConfig] = None,
        quality_scorer: Optional[QualityScorer] = None,
        enhanced_discovery_service: Optional["EnhancedDiscoveryService"] = None,
        settings: Optional[GlobalSettings] = None,
    ):
        """Initialize discovery service with providers.

        This service provides multi-provider paper discovery with two modes:
        1. Basic search: Direct provider queries with fallback (search method)
        2. Enhanced search: 4-stage pipeline with LLM (enhanced_search method)

        The enhanced_discovery_service parameter enables dependency injection
        for the Phase 6 enhanced pipeline. If not provided, enhanced_search()
        will create one internally (backward compatible).

        Args:
            api_key: Semantic Scholar API key (optional).
            config: Provider selection configuration.
            quality_scorer: Quality scorer instance (optional, created if None).
            enhanced_discovery_service: Pre-configured enhanced discovery service
                for dependency injection. If provided, enhanced_search() will use
                this instance instead of creating one internally. This enables
                easier testing and customization of the 4-stage pipeline.
            settings: Global settings including ArXiv configuration (Phase 7 Fix I1).
        """
        self.config = config or ProviderSelectionConfig()
        self.providers: Dict[ProviderType, DiscoveryProvider] = {}
        self._api_key = api_key
        self._settings = settings

        # Phase 6: Store injected enhanced service (optional DI)
        self._enhanced_service = enhanced_discovery_service

        # Initialize ArXiv (Always available)
        # Phase 7 Fix I1: Pass GlobalSettings to ArxivProvider for query configuration
        self.providers[ProviderType.ARXIV] = ArxivProvider(settings=settings)

        # Initialize Semantic Scholar (Only if key provided)
        if api_key:
            self.providers[ProviderType.SEMANTIC_SCHOLAR] = SemanticScholarProvider(
                api_key=api_key
            )
        else:
            logger.info("semantic_scholar_disabled", reason="no_api_key")

        # Initialize HuggingFace (Always available - no API key required)
        self.providers[ProviderType.HUGGINGFACE] = HuggingFaceProvider()

        # Phase 7.2: Initialize OpenAlex (Always available - no API key required)
        self.providers[ProviderType.OPENALEX] = OpenAlexProvider()

        # Initialize provider selector
        self._selector = ProviderSelector(
            preference_order=self.config.preference_order,
        )

        # Phase 3.4: Initialize quality scorer
        self._quality_scorer = quality_scorer or QualityScorer()

        # Initialize internal components
        self._metrics_collector = MetricsCollector()
        self._result_merger = ResultMerger()

    # =========================================================================
    # Backward Compatibility: Delegate to internal components
    # =========================================================================

    def _is_duplicate(
        self,
        paper: PaperMetadata,
        existing_papers: List[PaperMetadata],
        seen_ids: set,
    ) -> bool:
        """Check if a paper is a duplicate (backward compatibility).

        Delegates to ResultMerger.is_duplicate().

        Args:
            paper: Paper to check.
            existing_papers: List of already-collected papers.
            seen_ids: Set of unique identifiers already seen.

        Returns:
            True if paper is a duplicate, False otherwise.
        """
        return self._result_merger.is_duplicate(paper, existing_papers, seen_ids)

    def _log_quality_stats(self, papers: List[PaperMetadata]) -> None:
        """Log quality and PDF availability statistics (backward compatibility).

        Delegates to MetricsCollector.log_quality_stats().

        Args:
            papers: Ranked papers with quality scores.
        """
        self._metrics_collector.log_quality_stats(papers)

    async def _apply_arxiv_supplement(
        self,
        topic: ResearchTopic,
        papers: List[PaperMetadata],
    ) -> List[PaperMetadata]:
        """Supplement with ArXiv papers (backward compatibility).

        Delegates to ResultMerger.apply_arxiv_supplement().

        Args:
            topic: Research topic with supplement threshold.
            papers: Papers from primary provider.

        Returns:
            Merged and deduplicated list of papers.
        """
        return await self._result_merger.apply_arxiv_supplement(
            topic, papers, self.providers
        )

    async def _benchmark_search(
        self,
        topic: ResearchTopic,
    ) -> List[PaperMetadata]:
        """Search all providers (backward compatibility).

        Delegates to ResultMerger.benchmark_search().

        Args:
            topic: Research topic.

        Returns:
            Deduplicated list of papers from all providers.
        """
        return await self._result_merger.benchmark_search(topic, self.providers)

    @property
    def available_providers(self) -> List[ProviderType]:
        """Get list of available provider types."""
        return list(self.providers.keys())

    @property
    def enhanced_service(self) -> Optional["EnhancedDiscoveryService"]:
        """Get the injected EnhancedDiscoveryService, if any.

        Returns:
            The EnhancedDiscoveryService instance if one was injected
            via the constructor, None otherwise.

        Note:
            This property is useful for testing and introspection.
            If None, enhanced_search() will create a service internally.
        """
        return self._enhanced_service

    @enhanced_service.setter
    def enhanced_service(self, service: Optional["EnhancedDiscoveryService"]) -> None:
        """Set the EnhancedDiscoveryService for dependency injection.

        Args:
            service: Pre-configured EnhancedDiscoveryService, or None
                to revert to internal creation in enhanced_search().
        """
        self._enhanced_service = service

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers using intelligent provider selection.

        Args:
            topic: Research topic with query and settings.

        Returns:
            List of paper metadata.

        Raises:
            APIError: If provider is unavailable or request fails.
            ValueError: If unknown provider type requested.
        """
        # Check for benchmark mode
        if topic.benchmark or self.config.benchmark_mode:
            return await self._result_merger.benchmark_search(topic, self.providers)

        # Auto-select provider if enabled
        if self.config.auto_select and topic.auto_select_provider:
            selected_provider = self._selector.select_provider(
                topic=topic,
                available_providers=self.available_providers,
                min_citations=topic.min_citations,
            )
        else:
            selected_provider = topic.provider

        # Validate provider availability
        if selected_provider not in self.providers:
            if selected_provider == ProviderType.SEMANTIC_SCHOLAR:
                logger.error(
                    "provider_unavailable",
                    provider=selected_provider,
                    reason="missing_api_key",
                )
                raise APIError(
                    f"Provider {selected_provider} is not available "
                    "(missing API key). Check .env file."
                )
            else:
                raise ValueError(f"Unknown provider type: {selected_provider}")

        provider = self.providers[selected_provider]

        # Execute search with fallback if enabled
        if self.config.fallback_enabled and len(self.providers) > 1:
            papers = await self._search_with_fallback(
                topic, provider, selected_provider
            )
        else:
            papers = await provider.search(topic)

        # Phase 3.4: Handle ArXiv supplement strategy
        if topic.pdf_strategy == PDFStrategy.ARXIV_SUPPLEMENT:
            papers = await self._result_merger.apply_arxiv_supplement(
                topic, papers, self.providers
            )

        # Phase 3.4: Apply quality ranking if enabled
        if topic.quality_ranking and papers:
            papers = self._quality_scorer.rank_papers(
                papers, min_score=topic.min_quality_score
            )
            self._metrics_collector.log_quality_stats(papers)

        return papers

    async def _search_with_fallback(
        self,
        topic: ResearchTopic,
        primary_provider: DiscoveryProvider,
        primary_type: ProviderType,
    ) -> List[PaperMetadata]:
        """Execute search with automatic fallback on failure or empty results.

        For "sampling" providers (like HuggingFace) that only return trending
        papers, empty results trigger fallback since the topic may exist in
        comprehensive providers like ArXiv or Semantic Scholar.

        Args:
            topic: Research topic.
            primary_provider: Primary provider instance.
            primary_type: Primary provider type.

        Returns:
            List of paper metadata.
        """
        try:
            # Try primary provider with timeout
            result = await asyncio.wait_for(
                primary_provider.search(topic),
                timeout=self.config.fallback_timeout_seconds,
            )

            # Result-aware fallback: sampling providers returning empty
            # results should trigger fallback since the topic may exist
            # in comprehensive providers (ArXiv, Semantic Scholar)
            if not result and primary_type in self.SAMPLING_PROVIDERS:
                logger.info(
                    "sampling_provider_empty_results",
                    provider=primary_type,
                    query=topic.query[:50],
                    reason="topic_not_trending",
                )
                return await self._fallback_search(topic, primary_type)

            return result
        except asyncio.TimeoutError:
            logger.warning(
                "provider_timeout",
                provider=primary_type,
                timeout=self.config.fallback_timeout_seconds,
            )
        except Exception as e:
            logger.warning(
                "provider_error",
                provider=primary_type,
                error=str(e),
            )

        # Attempt fallback
        return await self._fallback_search(topic, primary_type)

    async def _fallback_search(
        self,
        topic: ResearchTopic,
        failed_provider: ProviderType,
    ) -> List[PaperMetadata]:
        """Attempt search with fallback providers.

        Args:
            topic: Research topic.
            failed_provider: The provider that failed.

        Returns:
            List of paper metadata from fallback provider.
        """
        for provider_type in self.config.preference_order:
            if provider_type == failed_provider:
                continue
            if (
                provider_type not in self.providers
            ):  # pragma: no cover (config mismatch)
                continue

            logger.info(
                "fallback_attempt",
                from_provider=failed_provider,
                to_provider=provider_type,
            )

            try:
                provider = self.providers[provider_type]
                result = await provider.search(topic)
                logger.info(
                    "fallback_success",
                    provider=provider_type,
                    result_count=len(result),
                )
                return result
            except Exception as e:
                logger.warning(
                    "fallback_failed",
                    provider=provider_type,
                    error=str(e),
                )
                continue

        logger.error("all_providers_failed", topic=topic.query[:50])
        return []

    async def search_with_metrics(
        self,
        topic: ResearchTopic,
    ) -> Tuple[List[PaperMetadata], ProviderMetrics]:
        """Search and return results with performance metrics.

        Args:
            topic: Research topic.

        Returns:
            Tuple of (papers, metrics).
        """
        # Determine which provider will be used
        if self.config.auto_select and topic.auto_select_provider:
            provider_type = self._selector.select_provider(
                topic=topic,
                available_providers=self.available_providers,
            )
        else:
            provider_type = topic.provider

        return await self._metrics_collector.search_with_metrics(
            topic=topic,
            provider_type=provider_type,
            search_func=lambda: self.search(topic),
        )

    async def compare_providers(
        self,
        topic: ResearchTopic,
    ) -> ProviderComparison:
        """Compare all providers for a topic.

        Args:
            topic: Research topic.

        Returns:
            Comparison results with metrics from all providers.
        """
        return await self._metrics_collector.compare_providers(topic, self.providers)

    # =========================================================================
    # Phase 6: Enhanced Discovery Pipeline Integration
    # =========================================================================

    async def enhanced_search(
        self,
        topic: ResearchTopic,
        llm_service: Optional["LLMService"] = None,
        config: Optional[EnhancedDiscoveryConfig] = None,
    ) -> DiscoveryResult:
        """Search using the Phase 6 enhanced discovery pipeline.

        This method implements the 4-stage discovery enhancement:
        1. Query Decomposition: Break broad queries into focused sub-queries
        2. Multi-Source Retrieval: Query multiple providers with smart routing
        3. Quality Filtering: Score papers on multiple quality signals
        4. Relevance Ranking: LLM-based semantic relevance scoring

        The enhanced pipeline can be customized via dependency injection:
        - Pass enhanced_discovery_service to __init__ for full control
        - Or let this method create one internally (backward compatible)

        Args:
            topic: Research topic with query and settings.
            llm_service: Optional LLM service for query decomposition and
                relevance ranking. If not provided, these stages are skipped.
                Note: Ignored if enhanced_discovery_service was injected.
            config: Optional enhanced discovery configuration.
                Note: Ignored if enhanced_discovery_service was injected.

        Returns:
            DiscoveryResult with scored and ranked papers, metrics, and queries.

        Note:
            If llm_service is not provided, the pipeline runs in degraded mode:
            - Query decomposition returns only the original query
            - Relevance ranking uses quality score only
        """
        # Use injected service if available (dependency injection pattern)
        if self._enhanced_service is not None:
            # Warn if caller provided parameters that will be ignored
            if llm_service is not None or config is not None:
                logger.warning(
                    "enhanced_search_params_ignored",
                    reason="using_injected_service",
                    llm_service_provided=llm_service is not None,
                    config_provided=config is not None,
                )
            logger.info(
                "enhanced_search_starting",
                query=topic.query[:50],
                providers=list(self.providers.keys()),
                mode="injected_service",
            )
            result = await self._enhanced_service.discover(topic)
            logger.info(
                "enhanced_search_completed",
                query=topic.query[:50],
                papers_found=result.paper_count,
                avg_quality=result.metrics.avg_quality_score,
                avg_relevance=result.metrics.avg_relevance_score,
            )
            return result

        # Backward compatible: Create service internally if not injected
        # Import here to avoid circular dependencies
        from src.services.enhanced_discovery_service import EnhancedDiscoveryService
        from src.services.query_decomposer import QueryDecomposer
        from src.services.quality_filter_service import QualityFilterService
        from src.services.relevance_ranker import RelevanceRanker

        effective_config = config or EnhancedDiscoveryConfig()  # type: ignore[call-arg]

        # Create Phase 6 components
        query_decomposer = QueryDecomposer(
            llm_service=llm_service,
            enable_cache=True,
        )

        quality_filter = QualityFilterService(
            min_citations=0,
            min_quality_score=effective_config.min_quality_score,
        )

        relevance_ranker = RelevanceRanker(
            llm_service=llm_service,
            min_relevance_score=effective_config.min_relevance_score,
            batch_size=10,
            enable_cache=True,
        )

        # Create enhanced discovery service
        enhanced_service = EnhancedDiscoveryService(
            providers=self.providers,
            query_decomposer=query_decomposer,
            quality_filter=quality_filter,
            relevance_ranker=relevance_ranker,
            config=effective_config,
        )

        logger.info(
            "enhanced_search_starting",
            query=topic.query[:50],
            providers=list(self.providers.keys()),
            llm_enabled=llm_service is not None,
            mode="internal_creation",
        )

        # Run enhanced discovery
        result = await enhanced_service.discover(topic)

        logger.info(
            "enhanced_search_completed",
            query=topic.query[:50],
            papers_found=result.paper_count,
            avg_quality=result.metrics.avg_quality_score,
            avg_relevance=result.metrics.avg_relevance_score,
        )

        return result

    # =========================================================================
    # Phase 7.2: Multi-Source Discovery with Citation Exploration
    # =========================================================================

    async def multi_source_search(
        self,
        topic: ResearchTopic,
        llm_service: Optional["LLMService"] = None,
        registry_service: Optional[object] = None,
        query_expansion_config: Optional[QueryExpansionConfig] = None,
        citation_config: Optional[CitationExplorationConfig] = None,
        aggregation_config: Optional[AggregationConfig] = None,
    ) -> List[PaperMetadata]:
        """Search using Phase 7.2 multi-source discovery with citation exploration.

        This method implements comprehensive discovery:
        1. Query Expansion: LLM-generated query variants
        2. Multi-Source Search: Query all configured providers concurrently
        3. Citation Exploration: Forward/backward citation discovery
        4. Result Aggregation: Deduplication and ranking

        Args:
            topic: Research topic with query and settings.
            llm_service: Optional LLM service for query expansion.
            registry_service: Optional registry for deduplication.
            query_expansion_config: Query expansion configuration.
            citation_config: Citation exploration configuration.
            aggregation_config: Result aggregation configuration.

        Returns:
            List of deduplicated, ranked papers from all sources.
        """
        from src.utils.query_expander import QueryExpander
        from src.services.citation_explorer import CitationExplorer
        from src.services.result_aggregator import ResultAggregator

        # Initialize configurations with defaults
        qe_config = query_expansion_config or QueryExpansionConfig()
        cite_config = citation_config or CitationExplorationConfig()
        agg_config = aggregation_config or AggregationConfig()

        # Step 1: Query Expansion (if enabled and LLM available)
        queries = [topic.query]
        if qe_config.enabled and llm_service is not None:
            expander = QueryExpander(llm_service=llm_service, config=qe_config)
            queries = await expander.expand(topic.query)
            logger.info(
                "phase72_query_expansion",
                original=topic.query[:50],
                expanded_count=len(queries),
            )

        # Step 2: Multi-Source Concurrent Search
        source_results: Dict[str, List[PaperMetadata]] = {}

        for query in queries:
            # Create topic with current query
            search_topic = topic.model_copy(update={"query": query})

            # Query all providers concurrently
            tasks = []
            provider_names = []
            for provider_type, provider in self.providers.items():
                tasks.append(provider.search(search_topic))
                provider_names.append(provider_type.value)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for provider_name, result in zip(provider_names, results):
                if isinstance(result, BaseException):
                    logger.warning(
                        "phase72_provider_error",
                        provider=provider_name,
                        error=str(result),
                    )
                    continue

                # Add discovery_source to papers
                for paper in result:
                    if not paper.discovery_source:
                        paper = paper.model_copy(
                            update={
                                "discovery_source": provider_name,
                                "discovery_method": "keyword",
                            }
                        )

                if provider_name not in source_results:
                    source_results[provider_name] = []
                source_results[provider_name].extend(result)

        logger.info(
            "phase72_multi_source_search",
            providers_queried=len(self.providers),
            total_papers=sum(len(p) for p in source_results.values()),
        )

        # Step 3: Citation Exploration (if enabled and SS available)
        if cite_config.enabled and self._api_key:
            explorer = CitationExplorer(
                api_key=self._api_key,
                registry_service=registry_service,  # type: ignore[arg-type]
                config=cite_config,
            )

            # Get seed papers from initial results
            all_initial = []
            for papers in source_results.values():
                all_initial.extend(papers)

            # Limit seed papers to avoid excessive API calls
            seed_papers = all_initial[:20]

            if seed_papers:
                citation_result = await explorer.explore(
                    seed_papers=seed_papers,
                    topic_slug=topic.slug,
                )

                # Add citation papers to results
                if citation_result.forward_papers:
                    source_results["forward_citations"] = citation_result.forward_papers
                if citation_result.backward_papers:
                    source_results["backward_citations"] = (
                        citation_result.backward_papers
                    )

                logger.info(
                    "phase72_citation_exploration",
                    forward=citation_result.stats.forward_discovered,
                    backward=citation_result.stats.backward_discovered,
                )

        # Step 4: Aggregation (deduplication + ranking)
        aggregator = ResultAggregator(
            registry_service=registry_service,  # type: ignore[arg-type]
            config=agg_config,
        )

        aggregation_result = await aggregator.aggregate(source_results)

        logger.info(
            "phase72_aggregation_complete",
            total_raw=aggregation_result.total_raw,
            after_dedup=aggregation_result.total_after_dedup,
            final_count=len(aggregation_result.papers),
            source_breakdown=aggregation_result.source_breakdown,
        )

        return aggregation_result.papers
