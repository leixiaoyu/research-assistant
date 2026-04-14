"""Discovery phase - paper discovery for research topics.

Phase 5.2: Extracted from research_pipeline.py.
Phase 7.1: Added discovery statistics support and integrated filtering.
Phase 7.2: Enhanced with multi-source discovery, query expansion, and citations.
"""

import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from src.models.config import (
    ResearchTopic,
    TimeframeDateRange,
    TimeframeType,
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
)
from src.models.discovery import DiscoveryStats
from src.models.paper import PaperMetadata
from src.orchestration.phases.base import PipelinePhase
from src.services.providers.base import APIError
from src.utils.timeframe_resolver import TimeframeResolver
from src.services.discovery_filter import DiscoveryFilter

if TYPE_CHECKING:
    from src.orchestration.context import PipelineContext


@dataclass
class Phase72Stats:
    """Phase 7.2 multi-source discovery statistics."""

    query_variants_used: int = 0
    sources_queried: List[str] = field(default_factory=list)
    source_breakdown: Dict[str, int] = field(default_factory=dict)
    forward_citations_found: int = 0
    backward_citations_found: int = 0
    papers_before_dedup: int = 0
    papers_after_dedup: int = 0


@dataclass
class TopicDiscoveryResult:
    """Result of processing a single topic in discovery phase.

    Phase 7.1: Added discovery_stats field for observability.
    Phase 7.2: Added phase72_stats for multi-source discovery.
    """

    topic: ResearchTopic
    topic_slug: str
    papers: List[PaperMetadata] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0
    # Phase 7.1: Discovery statistics
    discovery_stats: Optional[DiscoveryStats] = None
    # Phase 7.2: Multi-source statistics
    phase72_stats: Optional[Phase72Stats] = None


@dataclass
class DiscoveryResult:
    """Result of the discovery phase."""

    topics_processed: int = 0
    topics_failed: int = 0
    total_papers: int = 0
    topic_results: List[TopicDiscoveryResult] = field(default_factory=list)
    # Phase 7.2: Enable multi-source discovery
    multi_source_enabled: bool = False


class DiscoveryPhase(PipelinePhase[DiscoveryResult]):
    """Discovery phase - finds papers for research topics.

    Responsibilities:
    - Execute paper discovery for each topic
    - Apply deduplication
    - Apply quality filtering
    - Store discovered papers in context
    - Phase 7.1: Incremental discovery and filtering
    - Phase 7.2: Multi-source discovery with query expansion and citations
    - Phase 6: Enhanced discovery with 4-stage pipeline (LLM-based)
    """

    def __init__(
        self,
        context: "PipelineContext",  # type: ignore[name-defined]
        multi_source_enabled: bool = False,
        enhanced_discovery_enabled: bool = False,
        query_expansion_config: Optional[QueryExpansionConfig] = None,
        citation_config: Optional[CitationExplorationConfig] = None,
        aggregation_config: Optional[AggregationConfig] = None,
    ):
        """Initialize DiscoveryPhase.

        Args:
            context: Pipeline context
            multi_source_enabled: Enable Phase 7.2 multi-source discovery
            enhanced_discovery_enabled: Enable Phase 6 enhanced 4-stage pipeline
            query_expansion_config: Query expansion configuration
            citation_config: Citation exploration configuration
            aggregation_config: Result aggregation configuration
        """
        super().__init__(context)
        self.multi_source_enabled = multi_source_enabled
        self.enhanced_discovery_enabled = enhanced_discovery_enabled
        self.query_expansion_config = query_expansion_config
        self.citation_config = citation_config
        self.aggregation_config = aggregation_config

    @property
    def name(self) -> str:
        """Phase name."""
        return "discovery"

    async def execute(self) -> DiscoveryResult:
        """Execute discovery for all configured topics.

        Returns:
            DiscoveryResult with discovered papers
        """
        result = DiscoveryResult(multi_source_enabled=self.multi_source_enabled)

        # Type assertions
        assert self.context.config is not None
        assert self.context.discovery_service is not None
        assert self.context.catalog_service is not None

        for topic in self.context.config.research_topics:
            topic_result = await self._discover_topic(topic)
            result.topic_results.append(topic_result)

            if topic_result.success:
                result.topics_processed += 1
                result.total_papers += len(topic_result.papers)
                # Store in context for extraction phase
                self.context.add_discovered_papers(
                    topic_result.topic_slug, topic_result.papers
                )
            else:
                result.topics_failed += 1
                if topic_result.error:
                    self.context.add_error(
                        self.name, topic_result.error, topic=topic.query
                    )

        self.logger.info(
            "discovery_completed",
            topics_processed=result.topics_processed,
            topics_failed=result.topics_failed,
            total_papers=result.total_papers,
        )

        return result

    async def _discover_topic(self, topic: ResearchTopic) -> TopicDiscoveryResult:
        """Discover papers for a single topic.

        Phase 7.1: Integrated incremental discovery, filtering, and statistics.
        Phase 7.2: Multi-source discovery with query expansion and citations.

        Args:
            topic: Research topic to process

        Returns:
            TopicDiscoveryResult with discovered papers and stats
        """
        start_time = time.time()

        # Type assertions
        assert self.context.catalog_service is not None
        assert self.context.discovery_service is not None
        assert self.context.config is not None

        # Get/Create topic in catalog
        catalog_topic = self.context.catalog_service.get_or_create_topic(topic.query)
        topic_slug = catalog_topic.topic_slug

        result = TopicDiscoveryResult(
            topic=topic,
            topic_slug=topic_slug,
        )

        try:
            # Phase 7.1: Resolve timeframe (incremental if enabled)
            incremental_enabled = (
                self.context.config.settings.incremental_discovery_settings.enabled
            )
            if incremental_enabled and not topic.force_full_timeframe:
                resolver = TimeframeResolver(self.context.catalog_service)
                resolved_timeframe = resolver.resolve(topic, topic_slug)

                self.logger.info(
                    "using_resolved_timeframe",
                    topic=topic.query,
                    is_incremental=resolved_timeframe.is_incremental,
                    start_date=resolved_timeframe.start_date.isoformat(),
                    end_date=resolved_timeframe.end_date.isoformat(),
                )
            else:
                resolved_timeframe = None
                self.logger.info(
                    "incremental_discovery_disabled",
                    topic=topic.query,
                    reason=(
                        "force_full_timeframe=True"
                        if topic.force_full_timeframe
                        else "incremental_disabled_in_config"
                    ),
                )

            self.logger.info(
                "discovering_topic",
                topic=topic.query,
                topic_slug=topic_slug,
                multi_source=self.multi_source_enabled,
                enhanced_discovery=self.enhanced_discovery_enabled,
            )

            # Phase 7.1: Create modified topic with incremental timeframe
            # This is used by standard, multi-source, and enhanced discovery
            if resolved_timeframe is not None and resolved_timeframe.is_incremental:
                incremental_timeframe = TimeframeDateRange(
                    type=TimeframeType.DATE_RANGE,
                    start_date=resolved_timeframe.start_date.date(),
                    end_date=resolved_timeframe.end_date.date(),
                )
                search_topic = topic.model_copy(
                    update={"timeframe": incremental_timeframe}
                )
                self.logger.info(
                    "using_incremental_search",
                    topic=topic.query,
                    start_date=incremental_timeframe.start_date.isoformat(),
                    end_date=incremental_timeframe.end_date.isoformat(),
                )
            else:
                search_topic = topic

            # Execute discovery
            # Phase 6: Enhanced discovery takes precedence (4-stage LLM pipeline)
            if self.enhanced_discovery_enabled:
                discovery_result = await self.context.discovery_service.enhanced_search(
                    search_topic
                )
                papers = discovery_result.papers
                result.papers = papers
                # Enhanced discovery has its own quality filtering
                self.logger.info(
                    "enhanced_discovery_completed",
                    topic=topic.query,
                    papers_count=len(papers),
                    quality_scores=(
                        [p.quality_score for p in papers[:5]] if papers else []
                    ),
                )
            elif self.multi_source_enabled:
                papers = await self._multi_source_discover(topic, result)
                result.papers = papers
            else:
                papers = await self.context.discovery_service.search(search_topic)

                # Phase 7.1: Apply discovery filtering
                filter_enabled = (
                    self.context.config.settings.discovery_filter_settings.enabled
                )
                filter_settings = self.context.config.settings.discovery_filter_settings
                register_at_discovery = filter_settings.register_at_discovery

                if filter_enabled and self.context.registry_service is not None:
                    # Initialize discovery filter
                    discovery_filter = DiscoveryFilter(
                        registry_service=self.context.registry_service,
                        skip_filter=False,
                    )

                    # Filter papers
                    filter_result = await discovery_filter.filter_papers(
                        papers=papers,
                        topic_slug=topic_slug,
                        register_new=register_at_discovery,
                    )

                    # Update result with filtered papers
                    result.papers = filter_result.new_papers

                    # Update statistics
                    filter_result.stats.incremental_query = (
                        resolved_timeframe.is_incremental
                        if resolved_timeframe
                        else False
                    )
                    if resolved_timeframe and resolved_timeframe.is_incremental:
                        filter_result.stats.query_start_date = (
                            resolved_timeframe.start_date
                        )

                    result.discovery_stats = filter_result.stats

                    self.logger.info(
                        "discovery_filtering_applied",
                        topic=topic.query,
                        total_discovered=filter_result.stats.total_discovered,
                        new_count=filter_result.stats.new_count,
                        filtered_count=filter_result.stats.filtered_count,
                    )
                else:
                    # No filtering - use all papers
                    result.papers = papers

                    # Create basic stats
                    result.discovery_stats = DiscoveryStats(
                        total_discovered=len(papers),
                        new_count=len(papers),
                        filtered_count=0,
                        filter_breakdown={},
                        incremental_query=(
                            resolved_timeframe.is_incremental
                            if resolved_timeframe
                            else False
                        ),
                        query_start_date=(
                            resolved_timeframe.start_date
                            if resolved_timeframe
                            else None
                        ),
                    )

                    self.logger.info(
                        "discovery_filtering_skipped",
                        topic=topic.query,
                        reason="filtering_disabled_or_no_registry",
                    )

            result.success = True

            # Phase 7.1: Update last successful discovery timestamp
            if incremental_enabled and not topic.force_full_timeframe:
                discovery_timestamp = datetime.now(timezone.utc)
                self.context.catalog_service.set_last_discovery_at(
                    topic_slug, discovery_timestamp
                )
                self.logger.info(
                    "updated_last_discovery_timestamp",
                    topic_slug=topic_slug,
                    timestamp=discovery_timestamp.isoformat(),
                )

            if not result.papers:
                self.logger.warning("no_papers_found", topic=topic.query)
            else:
                self.logger.info(
                    "topic_discovered",
                    topic=topic.query,
                    papers_count=len(result.papers),
                    multi_source=self.multi_source_enabled,
                )

        except APIError as e:
            result.error = str(e)
            self.logger.error("discovery_failed", topic=topic.query, error=str(e))
        except Exception as e:
            result.error = str(e)
            self.logger.exception("discovery_unexpected_error", topic=topic.query)

        result.duration_seconds = time.time() - start_time
        return result

    async def _multi_source_discover(
        self,
        topic: ResearchTopic,
        result: TopicDiscoveryResult,
    ) -> List[PaperMetadata]:
        """Execute Phase 7.2 multi-source discovery.

        Uses query expansion, multiple providers, citation exploration,
        and result aggregation for comprehensive paper discovery.

        Args:
            topic: Research topic to process
            result: TopicDiscoveryResult to update with stats

        Returns:
            List of discovered papers
        """
        assert self.context.discovery_service is not None

        # Initialize Phase 7.2 stats
        stats = Phase72Stats()

        # Use multi_source_search from DiscoveryService
        papers = await self.context.discovery_service.multi_source_search(
            topic=topic,
            llm_service=getattr(self.context, "llm_service", None),
            registry_service=getattr(self.context, "registry_service", None),
            query_expansion_config=self.query_expansion_config,
            citation_config=self.citation_config,
            aggregation_config=self.aggregation_config,
        )

        # Track source breakdown from papers
        for paper in papers:
            source = paper.discovery_source or "unknown"
            stats.source_breakdown[source] = stats.source_breakdown.get(source, 0) + 1
            if source not in stats.sources_queried:
                stats.sources_queried.append(source)

            # Track citation discovery
            if paper.discovery_method == "forward_citation":
                stats.forward_citations_found += 1
            elif paper.discovery_method == "backward_citation":
                stats.backward_citations_found += 1

        stats.papers_after_dedup = len(papers)
        result.phase72_stats = stats

        self.logger.info(
            "multi_source_discovery_complete",
            topic=topic.query,
            papers_found=len(papers),
            sources_queried=stats.sources_queried,
            source_breakdown=stats.source_breakdown,
            forward_citations=stats.forward_citations_found,
            backward_citations=stats.backward_citations_found,
        )

        return papers

    def _get_default_result(self) -> DiscoveryResult:
        """Get default result when phase is skipped."""
        return DiscoveryResult()
