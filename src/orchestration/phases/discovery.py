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
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
)
from src.models.discovery import (
    DiscoveryStats,
    DiscoveryMode,
    DiscoveryPipelineConfig,
    ScoredPaper,
)
from src.models.paper import PaperMetadata
from src.orchestration.phases.base import PipelinePhase
from src.services.providers.base import APIError
from src.utils.timeframe_resolver import TimeframeResolver

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
    """

    def __init__(
        self,
        context: "PipelineContext",  # type: ignore[name-defined]
        multi_source_enabled: bool = False,
        query_expansion_config: Optional[QueryExpansionConfig] = None,
        citation_config: Optional[CitationExplorationConfig] = None,
        aggregation_config: Optional[AggregationConfig] = None,
    ):
        """Initialize DiscoveryPhase.

        Args:
            context: Pipeline context
            multi_source_enabled: Enable Phase 7.2 multi-source discovery
            query_expansion_config: Query expansion configuration
            citation_config: Citation exploration configuration
            aggregation_config: Result aggregation configuration
        """
        super().__init__(context)
        self.multi_source_enabled = multi_source_enabled
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
            )

            # Phase 8: Use unified discover() API based on configuration
            # Determine discovery mode from config flags
            if self.multi_source_enabled:
                mode = DiscoveryMode.DEEP
            elif getattr(self.context.config.settings, "enhanced_enabled", False):
                mode = DiscoveryMode.STANDARD
            else:
                mode = DiscoveryMode.SURFACE

            # Create pipeline config
            max_papers_value = getattr(topic, "max_papers", None) or getattr(
                self.context.config, "max_papers_per_topic", 50
            )
            # Ensure max_papers is an int
            max_papers_int = (
                int(max_papers_value) if max_papers_value is not None else 50
            )
            pipeline_config = DiscoveryPipelineConfig(
                mode=mode,
                max_papers=max_papers_int,
            )

            # Call unified discover() API
            discovery_result = await self.context.discovery_service.discover(
                topic=topic.query,
                mode=mode,
                config=pipeline_config,
                llm_service=getattr(self.context, "llm_service", None),
            )

            # Convert ScoredPaper to PaperMetadata for backward compatibility
            result.papers = self._convert_scored_to_metadata(discovery_result.papers)

            # Store source breakdown for reporting (preserve Phase 7.2 behavior)
            if self.multi_source_enabled and discovery_result.source_breakdown:
                # Update Phase 7.2 stats with source breakdown
                if result.phase72_stats is None:
                    result.phase72_stats = Phase72Stats()
                result.phase72_stats.source_breakdown = (
                    discovery_result.source_breakdown
                )
                result.phase72_stats.sources_queried = list(
                    discovery_result.source_breakdown.keys()
                )
                result.phase72_stats.papers_after_dedup = len(result.papers)

            # Use DiscoveryResult.metrics directly for stats
            # Note: filtered_count can be negative if citation exploration adds papers
            # after papers_retrieved was captured, so we clamp to 0
            result.discovery_stats = DiscoveryStats(
                total_discovered=discovery_result.metrics.papers_retrieved,
                new_count=len(result.papers),
                filtered_count=max(
                    0, discovery_result.metrics.papers_retrieved - len(result.papers)
                ),
                filter_breakdown={},
                incremental_query=(
                    resolved_timeframe.is_incremental if resolved_timeframe else False
                ),
                query_start_date=(
                    resolved_timeframe.start_date if resolved_timeframe else None
                ),
            )

            self.logger.info(
                "discovery_completed_via_unified_api",
                topic=topic.query,
                mode=mode.value,
                papers_retrieved=discovery_result.metrics.papers_retrieved,
                papers_after_filters=len(result.papers),
                providers_queried=discovery_result.metrics.providers_queried,
                duration_ms=discovery_result.metrics.pipeline_duration_ms,
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

    def _convert_scored_to_metadata(
        self, scored_papers: List[ScoredPaper]
    ) -> List[PaperMetadata]:
        """Convert ScoredPaper objects to PaperMetadata for backward compatibility.

        Args:
            scored_papers: List of ScoredPaper from discover()

        Returns:
            List of PaperMetadata objects
        """
        from src.models.paper import Author
        from pydantic import HttpUrl

        metadata_papers = []
        for sp in scored_papers:
            # Convert authors to Author objects
            author_objects = (
                [Author(name=name) for name in sp.authors] if sp.authors else []
            )

            # Parse publication_date if string
            pub_date = None
            if sp.publication_date:
                if isinstance(sp.publication_date, str):
                    from datetime import datetime

                    try:
                        pub_date = datetime.fromisoformat(
                            sp.publication_date.replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pub_date = None

            # Create PaperMetadata from ScoredPaper fields
            paper = PaperMetadata(
                paper_id=sp.paper_id,
                title=sp.title,
                abstract=sp.abstract,
                doi=sp.doi,
                url=HttpUrl(sp.url) if sp.url else HttpUrl("https://example.com"),
                open_access_pdf=(
                    HttpUrl(sp.open_access_pdf) if sp.open_access_pdf else None
                ),
                authors=author_objects,
                publication_date=pub_date,
                venue=sp.venue,
                citation_count=sp.citation_count,
                discovery_source=sp.source,
            )
            metadata_papers.append(paper)
        return metadata_papers

    def _get_default_result(self) -> DiscoveryResult:
        """Get default result when phase is skipped."""
        return DiscoveryResult()
