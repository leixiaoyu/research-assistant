"""Discovery phase - paper discovery for research topics.

Phase 5.2: Extracted from research_pipeline.py.
Phase 7.2: Enhanced with multi-source discovery, query expansion, and citations.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from src.models.config import (
    ResearchTopic,
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
)
from src.models.paper import PaperMetadata
from src.orchestration.phases.base import PipelinePhase
from src.services.providers.base import APIError

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
    """Result of processing a single topic in discovery phase."""

    topic: ResearchTopic
    topic_slug: str
    papers: List[PaperMetadata] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0
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

        Args:
            topic: Research topic to process

        Returns:
            TopicDiscoveryResult with discovered papers
        """
        start_time = time.time()

        # Type assertions
        assert self.context.catalog_service is not None
        assert self.context.discovery_service is not None

        # Get/Create topic in catalog
        catalog_topic = self.context.catalog_service.get_or_create_topic(topic.query)
        topic_slug = catalog_topic.topic_slug

        result = TopicDiscoveryResult(
            topic=topic,
            topic_slug=topic_slug,
        )

        try:
            self.logger.info(
                "discovering_topic",
                topic=topic.query,
                topic_slug=topic_slug,
                multi_source=self.multi_source_enabled,
            )

            # Execute discovery (Phase 7.2: multi-source or standard)
            if self.multi_source_enabled:
                papers = await self._multi_source_discover(topic, result)
            else:
                papers = await self.context.discovery_service.search(topic)

            result.papers = papers
            result.success = True

            if not papers:
                self.logger.warning("no_papers_found", topic=topic.query)
            else:
                self.logger.info(
                    "topic_discovered",
                    topic=topic.query,
                    papers_count=len(papers),
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
