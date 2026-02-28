"""Discovery phase - paper discovery for research topics.

Phase 5.2: Extracted from research_pipeline.py.
"""

import time
from dataclasses import dataclass, field
from typing import List, Optional

from src.models.config import ResearchTopic
from src.models.paper import PaperMetadata
from src.orchestration.phases.base import PipelinePhase
from src.services.providers.base import APIError


@dataclass
class TopicDiscoveryResult:
    """Result of processing a single topic in discovery phase."""

    topic: ResearchTopic
    topic_slug: str
    papers: List[PaperMetadata] = field(default_factory=list)
    success: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class DiscoveryResult:
    """Result of the discovery phase."""

    topics_processed: int = 0
    topics_failed: int = 0
    total_papers: int = 0
    topic_results: List[TopicDiscoveryResult] = field(default_factory=list)


class DiscoveryPhase(PipelinePhase[DiscoveryResult]):
    """Discovery phase - finds papers for research topics.

    Responsibilities:
    - Execute paper discovery for each topic
    - Apply deduplication
    - Apply quality filtering
    - Store discovered papers in context
    """

    @property
    def name(self) -> str:
        """Phase name."""
        return "discovery"

    async def execute(self) -> DiscoveryResult:
        """Execute discovery for all configured topics.

        Returns:
            DiscoveryResult with discovered papers
        """
        result = DiscoveryResult()

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
            )

            # Execute discovery
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
                )

        except APIError as e:
            result.error = str(e)
            self.logger.error("discovery_failed", topic=topic.query, error=str(e))
        except Exception as e:
            result.error = str(e)
            self.logger.exception("discovery_unexpected_error", topic=topic.query)

        result.duration_seconds = time.time() - start_time
        return result

    def _get_default_result(self) -> DiscoveryResult:
        """Get default result when phase is skipped."""
        return DiscoveryResult()
