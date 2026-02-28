"""Synthesis phase - per-topic knowledge base synthesis.

Phase 5.2: Extracted from research_pipeline.py.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from src.orchestration.phases.base import PipelinePhase


@dataclass
class TopicSynthesisResult:
    """Result of synthesis for a single topic."""

    topic_slug: str
    delta_path: Optional[Path] = None
    kb_total_papers: int = 0
    kb_average_quality: float = 0.0
    kb_duration_ms: float = 0.0
    success: bool = False
    error: Optional[str] = None


@dataclass
class SynthesisResult:
    """Result of the synthesis phase."""

    topics_processed: int = 0
    topics_failed: int = 0
    topic_results: List[TopicSynthesisResult] = field(default_factory=list)


class SynthesisPhase(PipelinePhase[SynthesisResult]):
    """Synthesis phase - generates Knowledge Base documents.

    Responsibilities:
    - Generate Delta briefs for each topic's run
    - Update Knowledge_Base.md for each topic
    - Update topic registries
    """

    @property
    def name(self) -> str:
        """Phase name."""
        return "synthesis"

    def is_enabled(self) -> bool:
        """Check if synthesis phase should run."""
        return self.context.enable_synthesis

    async def execute(self) -> SynthesisResult:
        """Execute synthesis for all processed topics.

        Returns:
            SynthesisResult with synthesis statistics
        """
        result = SynthesisResult()

        if not self.context.synthesis_engine or not self.context.delta_generator:
            self.logger.warning("synthesis_skipped", reason="services not initialized")
            return result

        self.logger.info(
            "synthesis_starting",
            topics=list(self.context.topic_processing_results.keys()),
        )

        for (
            topic_slug,
            processing_results,
        ) in self.context.topic_processing_results.items():
            topic_result = await self._synthesize_topic(topic_slug, processing_results)
            result.topic_results.append(topic_result)

            if topic_result.success:
                result.topics_processed += 1
            else:
                result.topics_failed += 1
                if topic_result.error:
                    self.context.add_error(
                        self.name, topic_result.error, topic=topic_slug
                    )

        self.logger.info(
            "synthesis_completed",
            topics_processed=result.topics_processed,
            topics_failed=result.topics_failed,
        )

        return result

    async def _synthesize_topic(
        self,
        topic_slug: str,
        processing_results: List[Any],
    ) -> TopicSynthesisResult:
        """Synthesize a single topic.

        Args:
            topic_slug: Topic identifier
            processing_results: Processing results for the topic

        Returns:
            TopicSynthesisResult with synthesis results
        """
        result = TopicSynthesisResult(topic_slug=topic_slug)

        try:
            assert self.context.delta_generator is not None
            assert self.context.synthesis_engine is not None

            # Generate Delta Brief for this run
            delta_path = self.context.delta_generator.generate(
                results=processing_results,
                topic_slug=topic_slug,
            )

            if delta_path:
                result.delta_path = delta_path
                self.logger.info(
                    "delta_generated",
                    topic=topic_slug,
                    path=str(delta_path),
                )

            # Synthesize Knowledge Base
            stats = self.context.synthesis_engine.synthesize(topic_slug)

            result.kb_total_papers = stats.total_papers
            result.kb_average_quality = stats.average_quality
            result.kb_duration_ms = stats.synthesis_duration_ms
            result.success = True

            self.logger.info(
                "knowledge_base_synthesized",
                topic=topic_slug,
                total_papers=stats.total_papers,
                average_quality=stats.average_quality,
                duration_ms=stats.synthesis_duration_ms,
            )

        except Exception as e:
            result.error = str(e)
            self.logger.error(
                "synthesis_failed",
                topic=topic_slug,
                error=str(e),
                exc_info=True,
            )

        return result

    def _get_default_result(self) -> SynthesisResult:
        """Get default result when phase is skipped."""
        return SynthesisResult()
