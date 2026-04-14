"""Discovery service with multi-provider intelligence (Phase 3.2, 3.4, 6 & 7.2)."""

import asyncio
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING

import structlog

from src.services.providers.base import DiscoveryProvider
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.services.providers.arxiv import ArxivProvider
from src.services.providers.huggingface import HuggingFaceProvider
from src.services.providers.openalex import OpenAlexProvider
from src.models.config import (
    ResearchTopic,
    ProviderType,
    ProviderSelectionConfig,
    EnhancedDiscoveryConfig,
    CitationExplorationConfig,
    QueryExpansionConfig,
    AggregationConfig,
    GlobalSettings,
)
from src.models.paper import PaperMetadata
from src.models.provider import ProviderMetrics, ProviderComparison
from src.models.discovery import (
    DiscoveryResult,
    DiscoveryMode,
    DiscoveryPipelineConfig,
    ScoredPaper,
)
from src.services.quality_intelligence_service import QualityIntelligenceService
from src.services.query_intelligence_service import QueryIntelligenceService
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

        # Phase 3.4: QualityScorer is deprecated, replaced by QualityIntelligenceService
        # Keep parameter for backward compatibility but warn if used
        if quality_scorer is not None:
            logger.warning(
                "quality_scorer_deprecated",
                message=(
                    "quality_scorer parameter is deprecated. "
                    "Use QualityIntelligenceService instead."
                ),
            )
        # Note: _quality_scorer attribute removed - use QualityIntelligenceService

        # Initialize internal components
        self._metrics_collector = MetricsCollector()
        self._result_merger = ResultMerger()

    async def close(self) -> None:
        """Close all provider HTTP sessions to prevent resource leaks.

        This should be called when the DiscoveryService is no longer needed,
        especially in long-running applications to avoid aiohttp session leaks.
        """
        for provider_type, provider in self.providers.items():
            if hasattr(provider, "close") and callable(provider.close):
                try:
                    await provider.close()
                    logger.debug(
                        "provider_session_closed",
                        provider=provider_type.value,
                    )
                except Exception as e:
                    logger.warning(
                        "provider_close_failed",
                        provider=provider_type.value,
                        error=str(e),
                    )

    # =========================================================================
    # Backward Compatibility: Delegate to internal components
    # =========================================================================

    def _scored_to_metadata(self, scored: "ScoredPaper") -> PaperMetadata:
        """Convert ScoredPaper back to PaperMetadata for legacy callers.

        Args:
            scored: ScoredPaper with quality and relevance scores.

        Returns:
            PaperMetadata with quality_score set.
        """
        from datetime import datetime
        from pydantic import HttpUrl
        from src.models.paper import Author

        # Convert author strings back to Author objects
        authors = [Author(name=name) for name in scored.authors]

        # Convert URL string to HttpUrl (required field, use placeholder if missing)
        url = (
            HttpUrl(scored.url) if scored.url else HttpUrl("https://example.com/paper")
        )

        # Convert publication_date string to datetime if available
        pub_date = None
        if scored.publication_date:
            try:
                pub_date = datetime.fromisoformat(scored.publication_date)
            except (ValueError, AttributeError):
                # If parsing fails, leave as None
                pass

        # Create PaperMetadata
        paper = PaperMetadata(
            paper_id=scored.paper_id,
            title=scored.title,
            abstract=scored.abstract,
            doi=scored.doi,
            url=url,
            authors=authors,
            publication_date=pub_date,
            venue=scored.venue,
            citation_count=scored.citation_count,
        )

        # Set quality_score on the mutable metadata (0-100 scale)
        paper.quality_score = scored.quality_score * 100

        return paper

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

    async def search(
        self,
        topic: ResearchTopic,
        max_papers: int = 50,
        providers: Optional[List[ProviderType]] = None,
    ) -> List[PaperMetadata]:
        """[DEPRECATED] Search for papers using intelligent provider selection.

        This method is deprecated. Use discover(mode=DiscoveryMode.SURFACE) instead
        for fast surface-level discovery.

        Args:
            topic: Research topic with query and settings.
            max_papers: Maximum papers to return (default: 50).
            providers: Optional list of providers to use.

        Returns:
            List of paper metadata.

        Raises:
            APIError: If provider is unavailable or request fails.
            ValueError: If unknown provider type requested.
        """
        logger.warning(
            "search_method_deprecated",
            message=(
                "search() is deprecated, use "
                "discover(mode=DiscoveryMode.SURFACE) instead"
            ),
            migration_guide=(
                "Replace search(topic) with "
                "discover(topic.query, mode=DiscoveryMode.SURFACE)"
            ),
        )

        # Import discovery models
        from src.models.discovery import DiscoveryMode, DiscoveryPipelineConfig

        # Build provider list for config
        provider_names = []
        if providers:
            provider_names = [p.value for p in providers]
        else:
            # Use all available providers
            provider_names = [p.value for p in self.providers.keys()]

        # Route to discover with SURFACE mode
        result = await self.discover(
            topic=topic.query,
            mode=DiscoveryMode.SURFACE,
            config=DiscoveryPipelineConfig(
                mode=DiscoveryMode.SURFACE,
                max_papers=max_papers,
                providers=provider_names,
            ),
        )

        # Convert ScoredPaper back to PaperMetadata for backward compatibility
        return [self._scored_to_metadata(sp) for sp in result.papers]

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
        """[DEPRECATED] Search using the Phase 6 enhanced discovery pipeline.

        This method is deprecated. Use discover(mode=DiscoveryMode.STANDARD) instead
        for balanced discovery with query decomposition.

        Note: If an EnhancedDiscoveryService was injected via constructor or
        enhanced_service property setter, it will be used for backward compatibility.
        Otherwise, this delegates to the unified discover() API.

        Args:
            topic: Research topic with query and settings.
            llm_service: Optional LLM service for query decomposition and
                relevance ranking. Ignored if an EnhancedDiscoveryService is
                injected (uses the injected service's configuration instead).
            config: Optional enhanced discovery configuration.

        Returns:
            DiscoveryResult with scored and ranked papers, metrics, and queries.
        """
        logger.warning(
            "enhanced_search_deprecated",
            message=(
                "enhanced_search() is deprecated, use "
                "discover(mode=DiscoveryMode.STANDARD) instead"
            ),
            migration_guide=(
                "Replace enhanced_search(topic, llm) with "
                "discover(topic.query, mode=DiscoveryMode.STANDARD, "
                "llm_service=llm)"
            ),
        )

        # Backward compatibility: use injected EnhancedDiscoveryService if available
        if self._enhanced_service is not None:
            return await self._enhanced_service.discover(topic)

        # Import discovery models
        from src.models.discovery import DiscoveryMode

        # Route to discover with STANDARD mode
        return await self.discover(
            topic=topic.query,
            mode=DiscoveryMode.STANDARD,
            llm_service=llm_service,
        )

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
        """[DEPRECATED] Search using Phase 7.2 multi-source discovery.

        This method is deprecated. Use discover(mode=DiscoveryMode.DEEP)
        instead for comprehensive discovery with citations.

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
        logger.warning(
            "multi_source_search_deprecated",
            message=(
                "multi_source_search() is deprecated, use "
                "discover(mode=DiscoveryMode.DEEP) instead"
            ),
            migration_guide=(
                "Replace multi_source_search(topic, llm) with "
                "discover(topic.query, mode=DiscoveryMode.DEEP, "
                "llm_service=llm)"
            ),
        )

        # Import discovery models
        from src.models.discovery import DiscoveryMode

        # Route to discover with DEEP mode
        result = await self.discover(
            topic=topic.query,
            mode=DiscoveryMode.DEEP,
            llm_service=llm_service,
        )

        # Convert ScoredPaper back to PaperMetadata for backward compatibility
        return [self._scored_to_metadata(sp) for sp in result.papers]

    # =========================================================================
    # Phase 8: Unified Discovery API with Tiered Complexity
    # =========================================================================

    async def discover(
        self,
        topic: str,
        mode: Optional["DiscoveryMode"] = None,
        config: Optional["DiscoveryPipelineConfig"] = None,
        llm_service: Optional["LLMService"] = None,
    ) -> "DiscoveryResult":
        """Unified discovery API with tiered complexity modes.

        This method consolidates search(), enhanced_search(), and
        multi_source_search() into a single interface with three operational
        modes:

        - SURFACE: Fast (<5s), single provider, no query enhancement
        - STANDARD: Balanced (<30s), query decomposition, all providers
        - DEEP: Comprehensive (<120s), hybrid enhancement, citations

        Args:
            topic: Research topic string (will be converted to ResearchTopic)
            mode: Discovery mode (defaults to STANDARD if not in config)
            config: Optional pipeline configuration
            llm_service: Optional LLM service for query enhancement and
                relevance ranking

        Returns:
            DiscoveryResult with scored papers, metrics, and source breakdown

        Example:
            # Fast surface discovery
            result = await service.discover(
                "GPT-4 applications", mode=DiscoveryMode.SURFACE
            )

            # Standard discovery with query decomposition
            result = await service.discover("transformer optimization")

            # Deep discovery with citations
            result = await service.discover(
                "reinforcement learning robotics",
                mode=DiscoveryMode.DEEP,
                llm_service=llm
            )
        """
        import time
        from src.services.venue_repository import YamlVenueRepository

        start_time = time.time()

        # Use default config if not provided
        if config is None:
            effective_mode = mode or DiscoveryMode.STANDARD
            config = DiscoveryPipelineConfig(mode=effective_mode)
        else:
            effective_mode = config.mode

        # Override mode if explicitly provided
        if mode is not None:
            effective_mode = mode

        # Convert topic string to ResearchTopic with default timeframe
        from src.models.config.core import TimeframeRecent, TimeframeType

        research_topic = ResearchTopic(
            query=topic,
            max_papers=config.max_papers,
            timeframe=TimeframeRecent(type=TimeframeType.RECENT, value="30d"),
        )

        # Initialize services
        venue_repo = YamlVenueRepository()
        quality_service = QualityIntelligenceService(
            venue_repository=venue_repo,
            min_citations=config.min_citations,
        )
        query_service = (
            QueryIntelligenceService(llm_service=llm_service) if llm_service else None
        )

        logger.info(
            "discover_starting",
            query=topic[:50],
            mode=effective_mode.value,
            providers=list(self.providers.keys()),
            llm_enabled=llm_service is not None,
        )

        # Route based on mode
        if effective_mode == DiscoveryMode.SURFACE:
            result = await self._discover_surface(
                research_topic, config, quality_service, start_time
            )
        elif effective_mode == DiscoveryMode.STANDARD:
            result = await self._discover_standard(
                research_topic, config, quality_service, query_service, start_time
            )
        else:  # DEEP
            result = await self._discover_deep(
                research_topic,
                config,
                quality_service,
                query_service,
                llm_service,
                start_time,
            )

        logger.info(
            "discover_completed",
            query=topic[:50],
            mode=effective_mode.value,
            papers_found=result.paper_count,
            duration_ms=result.metrics.pipeline_duration_ms,
        )

        return result

    async def _discover_surface(
        self,
        topic: "ResearchTopic",
        config: "DiscoveryPipelineConfig",
        quality_service: "QualityIntelligenceService",
        start_time: float,
    ) -> "DiscoveryResult":
        """SURFACE mode: Fast discovery with single provider.

        Target: <5s
        - Single best provider (use first available)
        - No query enhancement
        - Basic quality scoring
        - Return quickly with minimal processing
        """
        import time
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
        )

        # Select single provider (first available or ArXiv as fallback)
        selected_provider = None
        if self.providers:
            # Use first provider in available list
            selected_provider = list(self.providers.keys())[0]
        else:
            # No providers available
            logger.error("discover_surface_no_providers")
            return DiscoveryResult(
                papers=[],
                metrics=DiscoveryMetrics(
                    pipeline_duration_ms=int((time.time() - start_time) * 1000),
                    duration_ms=int((time.time() - start_time) * 1000),
                ),
                mode=DiscoveryMode.SURFACE,
            )

        logger.info(
            "discover_surface_provider_selected", provider=selected_provider.value
        )

        # Query single provider
        provider = self.providers[selected_provider]
        papers = await provider.search(topic)

        # Apply basic quality scoring
        scored_papers = [quality_service.score_paper(paper) for paper in papers]

        # Sort by quality score and limit
        scored_papers.sort(key=lambda p: p.quality_score, reverse=True)
        scored_papers = scored_papers[: config.max_papers]

        # Build source breakdown
        source_breakdown = {selected_provider.value: len(scored_papers)}

        # Calculate metrics
        duration_ms = int((time.time() - start_time) * 1000)
        avg_quality = (
            sum(p.quality_score for p in scored_papers) / len(scored_papers)
            if scored_papers
            else 0.0
        )

        metrics = DiscoveryMetrics(
            papers_retrieved=len(papers),
            papers_after_dedup=len(scored_papers),
            papers_after_quality_filter=len(scored_papers),
            providers_queried=[selected_provider.value],
            avg_quality_score=avg_quality,
            pipeline_duration_ms=duration_ms,
            duration_ms=duration_ms,
        )

        return DiscoveryResult(
            papers=scored_papers,
            metrics=metrics,
            source_breakdown=source_breakdown,
            mode=DiscoveryMode.SURFACE,
        )

    async def _discover_standard(
        self,
        topic: "ResearchTopic",
        config: "DiscoveryPipelineConfig",
        quality_service: "QualityIntelligenceService",
        query_service: Optional["QueryIntelligenceService"],
        start_time: float,
    ) -> "DiscoveryResult":
        """STANDARD mode: Balanced discovery with query decomposition.

        Target: <30s
        - Query decomposition (if LLM available)
        - All providers queried concurrently
        - Quality filtering
        - Deduplication
        """
        import time
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            DecomposedQuery,
            QueryFocus,
        )
        from src.models.query import QueryStrategy

        # Step 1: Query enhancement (if available)
        queries_used = []
        if query_service:
            enhanced_queries = await query_service.enhance(
                topic.query,
                strategy=QueryStrategy.DECOMPOSE,
                max_queries=config.query_enhancement.max_queries,
                include_original=config.query_enhancement.include_original,
            )
            # Convert EnhancedQuery to DecomposedQuery for backward compatibility
            for eq in enhanced_queries:
                # Map query.QueryFocus to discovery.QueryFocus by value
                focus_value = eq.focus.value if eq.focus else "methodology"
                discovery_focus = QueryFocus(focus_value)
                queries_used.append(
                    DecomposedQuery(
                        query=eq.query,
                        focus=discovery_focus,
                        weight=eq.weight,
                    )
                )
        else:
            # No LLM - use original query only
            queries_used = [
                DecomposedQuery(
                    query=topic.query,
                    focus=QueryFocus.METHODOLOGY,
                    weight=1.0,
                )
            ]

        logger.info(
            "discover_standard_queries_generated",
            original=topic.query[:50],
            count=len(queries_used),
        )

        # Step 2: Query all providers concurrently for each query
        all_papers = []
        source_breakdown: dict = {}

        for decomposed_query in queries_used:
            search_topic = topic.model_copy(update={"query": decomposed_query.query})

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
                        "discover_standard_provider_error",
                        provider=provider_name,
                        error=str(result),
                    )
                    continue

                # Track source
                source_breakdown[provider_name] = source_breakdown.get(
                    provider_name, 0
                ) + len(result)
                all_papers.extend(result)

        papers_retrieved = len(all_papers)

        # Step 3: Deduplication
        deduplicated_papers: List[PaperMetadata] = []
        seen_ids: set[str] = set()
        for paper in all_papers:
            if not self._result_merger.is_duplicate(
                paper, deduplicated_papers, seen_ids
            ):
                deduplicated_papers.append(paper)
                if paper.doi:
                    seen_ids.add(paper.doi)
                if paper.paper_id:
                    seen_ids.add(paper.paper_id)

        # Step 4: Quality filtering and scoring
        scored_papers = quality_service.filter_by_quality(
            deduplicated_papers,
            min_score=config.min_quality_score,
        )

        # Sort by quality score and limit
        scored_papers.sort(key=lambda p: p.quality_score, reverse=True)
        scored_papers = scored_papers[: config.max_papers]

        # Calculate metrics
        duration_ms = int((time.time() - start_time) * 1000)
        avg_quality = (
            sum(p.quality_score for p in scored_papers) / len(scored_papers)
            if scored_papers
            else 0.0
        )

        metrics = DiscoveryMetrics(
            queries_generated=len(queries_used),
            papers_retrieved=papers_retrieved,
            papers_after_dedup=len(deduplicated_papers),
            papers_after_quality_filter=len(scored_papers),
            providers_queried=list(self.providers.keys()),
            avg_quality_score=avg_quality,
            pipeline_duration_ms=duration_ms,
            duration_ms=duration_ms,
        )

        return DiscoveryResult(
            papers=scored_papers,
            metrics=metrics,
            queries_used=queries_used,
            source_breakdown=source_breakdown,
            mode=DiscoveryMode.STANDARD,
        )

    async def _discover_deep(
        self,
        topic: "ResearchTopic",
        config: "DiscoveryPipelineConfig",
        quality_service: "QualityIntelligenceService",
        query_service: Optional["QueryIntelligenceService"],
        llm_service: Optional["LLMService"],
        start_time: float,
    ) -> "DiscoveryResult":
        """DEEP mode: Comprehensive discovery with citations and relevance ranking.

        Target: <120s
        - Hybrid query enhancement (decompose + expand)
        - All providers queried concurrently
        - Citation exploration (forward + backward)
        - Quality filtering
        - Relevance ranking (LLM-based)
        """
        import time
        from src.models.discovery import (
            DiscoveryResult,
            DiscoveryMetrics,
            DiscoveryMode,
            DecomposedQuery,
            QueryFocus,
        )
        from src.models.query import QueryStrategy

        # Step 1: Hybrid query enhancement (if available)
        queries_used = []
        if query_service:
            enhanced_queries = await query_service.enhance(
                topic.query,
                strategy=QueryStrategy.HYBRID,
                max_queries=config.query_enhancement.max_queries
                * 2,  # More queries for deep mode
                include_original=config.query_enhancement.include_original,
            )
            # Convert EnhancedQuery to DecomposedQuery
            for eq in enhanced_queries:
                # Map query.QueryFocus to discovery.QueryFocus by value
                focus_value = eq.focus.value if eq.focus else "methodology"
                discovery_focus = QueryFocus(focus_value)
                queries_used.append(
                    DecomposedQuery(
                        query=eq.query,
                        focus=discovery_focus,
                        weight=eq.weight,
                    )
                )
        else:
            # No LLM - use original query only
            queries_used = [
                DecomposedQuery(
                    query=topic.query,
                    focus=QueryFocus.METHODOLOGY,
                    weight=1.0,
                )
            ]

        logger.info(
            "discover_deep_queries_generated",
            original=topic.query[:50],
            count=len(queries_used),
        )

        # Step 2: Query all providers concurrently for each query
        all_papers = []
        source_breakdown: dict = {}

        for decomposed_query in queries_used:
            search_topic = topic.model_copy(update={"query": decomposed_query.query})

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
                        "discover_deep_provider_error",
                        provider=provider_name,
                        error=str(result),
                    )
                    continue

                # Track source
                source_breakdown[provider_name] = source_breakdown.get(
                    provider_name, 0
                ) + len(result)
                all_papers.extend(result)

        # Note: papers_retrieved is captured after citation exploration
        # to include all papers in the count

        # Step 3: Citation exploration (if enabled and SS available)
        forward_citations_found = 0
        backward_citations_found = 0

        if config.citation_exploration.enabled and self._api_key and all_papers:
            from src.services.citation_explorer import CitationExplorer
            from src.models.config import CitationExplorationConfig

            explorer = CitationExplorer(
                api_key=self._api_key,
                config=CitationExplorationConfig(
                    enabled=True,
                    forward=config.citation_exploration.forward_citations,
                    backward=config.citation_exploration.backward_citations,
                    max_citation_depth=config.citation_exploration.max_depth,
                    max_forward_per_paper=(
                        config.citation_exploration.max_papers_per_direction
                    ),
                    max_backward_per_paper=(
                        config.citation_exploration.max_papers_per_direction
                    ),
                ),
            )

            # Limit seed papers to avoid excessive API calls
            seed_papers = all_papers[:10]

            citation_result = await explorer.explore(
                seed_papers=seed_papers,
                topic_slug=topic.slug,
            )

            # Add citation papers to results
            if citation_result.forward_papers:
                forward_citations_found = len(citation_result.forward_papers)
                source_breakdown["forward_citations"] = forward_citations_found
                all_papers.extend(citation_result.forward_papers)

            if citation_result.backward_papers:
                backward_citations_found = len(citation_result.backward_papers)
                source_breakdown["backward_citations"] = backward_citations_found
                all_papers.extend(citation_result.backward_papers)

            logger.info(
                "discover_deep_citation_exploration",
                forward=forward_citations_found,
                backward=backward_citations_found,
            )

            # Clean up: close the citation explorer session
            await explorer.close()

        # Capture papers_retrieved after citation exploration to include all papers
        papers_retrieved = len(all_papers)

        # Step 4: Deduplication
        deduplicated_papers: List[PaperMetadata] = []
        seen_ids: set[str] = set()
        for paper in all_papers:
            if not self._result_merger.is_duplicate(
                paper, deduplicated_papers, seen_ids
            ):
                deduplicated_papers.append(paper)
                if paper.doi:
                    seen_ids.add(paper.doi)
                if paper.paper_id:
                    seen_ids.add(paper.paper_id)

        # Step 5: Quality filtering and scoring
        scored_papers = quality_service.filter_by_quality(
            deduplicated_papers,
            min_score=config.min_quality_score,
        )

        papers_after_quality = len(scored_papers)

        # Step 6: Relevance ranking (if enabled and LLM available)
        if config.enable_relevance_ranking and llm_service:
            from src.services.relevance_ranker import RelevanceRanker

            ranker = RelevanceRanker(
                llm_service=llm_service,
                min_relevance_score=config.min_relevance_score,
                batch_size=10,
                enable_cache=True,
            )

            # Rank papers
            ranked_papers = await ranker.rank(
                papers=scored_papers,
                query=topic.query,
            )

            # Filter by relevance threshold
            scored_papers = [
                p
                for p in ranked_papers
                if p.relevance_score is not None
                and p.relevance_score >= config.min_relevance_score
            ]

            logger.info(
                "discover_deep_relevance_ranking",
                before=papers_after_quality,
                after=len(scored_papers),
            )

        # Sort by final score and limit
        scored_papers.sort(key=lambda p: p.final_score, reverse=True)
        scored_papers = scored_papers[: config.max_papers]

        # Calculate metrics
        duration_ms = int((time.time() - start_time) * 1000)
        avg_quality = (
            sum(p.quality_score for p in scored_papers) / len(scored_papers)
            if scored_papers
            else 0.0
        )
        avg_relevance = (
            sum(
                p.relevance_score
                for p in scored_papers
                if p.relevance_score is not None
            )
            / len([p for p in scored_papers if p.relevance_score is not None])
            if any(p.relevance_score is not None for p in scored_papers)
            else 0.0
        )

        metrics = DiscoveryMetrics(
            queries_generated=len(queries_used),
            papers_retrieved=papers_retrieved,
            papers_after_dedup=len(deduplicated_papers),
            papers_after_quality_filter=papers_after_quality,
            papers_after_relevance_filter=len(scored_papers),
            providers_queried=list(self.providers.keys()),
            avg_quality_score=avg_quality,
            avg_relevance_score=avg_relevance,
            pipeline_duration_ms=duration_ms,
            duration_ms=duration_ms,
            forward_citations_found=forward_citations_found,
            backward_citations_found=backward_citations_found,
        )

        return DiscoveryResult(
            papers=scored_papers,
            metrics=metrics,
            queries_used=queries_used,
            source_breakdown=source_breakdown,
            mode=DiscoveryMode.DEEP,
        )
