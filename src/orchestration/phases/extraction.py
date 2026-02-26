"""Extraction phase - PDF processing and LLM extraction.

Phase 5.2: Extracted from research_pipeline.py.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.models.config import ResearchTopic
from src.models.paper import PaperMetadata
from src.models.synthesis import ProcessingResult, ProcessingStatus
from src.orchestration.phases.base import PipelinePhase
from src.output.enhanced_generator import EnhancedMarkdownGenerator


@dataclass
class TopicExtractionResult:
    """Result of extraction for a single topic."""

    topic: ResearchTopic
    topic_slug: str
    papers_discovered: int = 0
    papers_processed: int = 0
    papers_with_extraction: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    output_file: Optional[str] = None
    extracted_papers: Optional[Any] = None
    summary_stats: Optional[Dict[str, Any]] = None
    success: bool = False
    error: Optional[str] = None
    duration_seconds: float = 0.0


@dataclass
class ExtractionResult:
    """Result of the extraction phase."""

    topics_processed: int = 0
    topics_failed: int = 0
    total_papers_processed: int = 0
    total_papers_with_extraction: int = 0
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    output_files: List[str] = field(default_factory=list)
    topic_results: List[TopicExtractionResult] = field(default_factory=list)


class ExtractionPhase(PipelinePhase[ExtractionResult]):
    """Extraction phase - PDF processing and LLM extraction.

    Responsibilities:
    - Coordinate PDF download and conversion
    - Execute LLM extraction for each paper
    - Handle extraction failures gracefully
    - Generate markdown output files
    - Store extraction results in context
    """

    @property
    def name(self) -> str:
        """Phase name."""
        return "extraction"

    def is_enabled(self) -> bool:
        """Check if extraction phase should run."""
        return self.context.enable_phase2

    async def execute(self) -> ExtractionResult:
        """Execute extraction for all discovered papers.

        Returns:
            ExtractionResult with extraction statistics
        """
        result = ExtractionResult()

        # Type assertions
        assert self.context.config is not None

        for topic in self.context.config.research_topics:
            # Get catalog topic info
            assert self.context.catalog_service is not None
            catalog_topic = self.context.catalog_service.get_or_create_topic(
                topic.query
            )
            topic_slug = catalog_topic.topic_slug

            # Get discovered papers from context
            papers = self.context.discovered_papers.get(topic_slug, [])

            if not papers:
                self.logger.info(
                    "extraction_skipped",
                    topic=topic.query,
                    reason="no papers discovered",
                )
                continue

            topic_result = await self._extract_topic(
                topic=topic,
                papers=papers,
                topic_slug=topic_slug,
                catalog_topic=catalog_topic,
            )
            result.topic_results.append(topic_result)

            if topic_result.success:
                result.topics_processed += 1
                result.total_papers_processed += topic_result.papers_processed
                result.total_papers_with_extraction += (
                    topic_result.papers_with_extraction
                )
                result.total_tokens_used += topic_result.tokens_used
                result.total_cost_usd += topic_result.cost_usd
                if topic_result.output_file:
                    result.output_files.append(topic_result.output_file)
            else:
                result.topics_failed += 1
                if topic_result.error:
                    self.context.add_error(
                        self.name, topic_result.error, topic=topic.query
                    )

        self.logger.info(
            "extraction_completed",
            topics_processed=result.topics_processed,
            topics_failed=result.topics_failed,
            total_papers_processed=result.total_papers_processed,
            total_tokens_used=result.total_tokens_used,
            total_cost_usd=result.total_cost_usd,
        )

        return result

    async def _extract_topic(
        self,
        topic: ResearchTopic,
        papers: List[PaperMetadata],
        topic_slug: str,
        catalog_topic: Any,
    ) -> TopicExtractionResult:
        """Extract papers for a single topic.

        Args:
            topic: Research topic
            papers: Discovered papers
            topic_slug: Topic identifier
            catalog_topic: Catalog topic entry

        Returns:
            TopicExtractionResult with extraction results
        """
        start_time = time.time()
        run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

        result = TopicExtractionResult(
            topic=topic,
            topic_slug=topic_slug,
            papers_discovered=len(papers),
        )

        try:
            self.logger.info(
                "extracting_topic",
                topic=topic.query,
                papers_count=len(papers),
            )

            extracted_papers = None
            summary_stats: Optional[Dict[str, Any]] = None

            # Run extraction if targets are configured
            if self.context.extraction_service and topic.extraction_targets:
                extracted_papers, summary_stats = await self._run_extraction(
                    papers=papers,
                    topic=topic,
                    run_id=run_id,
                    topic_slug=topic_slug,
                )
                result.extracted_papers = extracted_papers
                result.summary_stats = summary_stats

                if summary_stats:
                    result.papers_with_extraction = summary_stats.get(
                        "papers_with_extraction", 0
                    )
                    result.tokens_used = summary_stats.get("total_tokens_used", 0)
                    result.cost_usd = summary_stats.get("total_cost_usd", 0.0)

            # Generate output file
            output_file = await self._generate_output(
                papers=papers,
                extracted_papers=extracted_papers,
                topic=topic,
                run_id=run_id,
                summary_stats=summary_stats,
                catalog_topic=catalog_topic,
            )
            result.output_file = str(output_file)
            result.papers_processed = (
                summary_stats.get("papers_with_extraction", len(papers))
                if summary_stats
                else len(papers)
            )

            # Store processing results for synthesis
            if self.context.enable_synthesis:
                processing_results = self._get_processing_results(
                    papers=papers,
                    topic_slug=topic_slug,
                    extracted_papers=extracted_papers,
                )
                self.context.add_processing_results(topic_slug, processing_results)

            # Update catalog
            self._update_catalog(
                catalog_topic=catalog_topic,
                run_id=run_id,
                papers=papers,
                topic=topic,
                output_file=output_file,
                summary_stats=summary_stats,
                duration_seconds=time.time() - start_time,
            )

            result.success = True
            self.logger.info(
                "topic_extraction_completed",
                topic=topic.query,
                papers_processed=result.papers_processed,
                output_file=str(output_file),
            )

        except Exception as e:
            result.error = str(e)
            self.logger.exception("extraction_failed", topic=topic.query)

        result.duration_seconds = time.time() - start_time
        return result

    async def _run_extraction(
        self,
        papers: List[PaperMetadata],
        topic: ResearchTopic,
        run_id: str,
        topic_slug: str,
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """Run extraction pipeline for papers.

        Args:
            papers: Papers to process
            topic: Research topic
            run_id: Run identifier
            topic_slug: Topic slug for registry

        Returns:
            Tuple of (extracted_papers, summary_stats)
        """
        assert self.context.extraction_service is not None
        assert topic.extraction_targets is not None

        self.logger.info(
            "starting_llm_extraction",
            topic=topic.query,
            papers_count=len(papers),
            targets_count=len(topic.extraction_targets),
        )

        extracted_papers = await self.context.extraction_service.process_papers(
            papers=papers,
            targets=topic.extraction_targets,
            run_id=run_id,
            query=topic.query,
            topic_slug=topic_slug,
        )

        summary_stats = self.context.extraction_service.get_extraction_summary(
            extracted_papers
        )

        self.logger.info(
            "llm_extraction_completed",
            topic=topic.query,
            papers_with_pdf=summary_stats.get("papers_with_pdf", 0),
            papers_with_extraction=summary_stats.get("papers_with_extraction", 0),
            total_tokens=summary_stats.get("total_tokens_used", 0),
            total_cost_usd=summary_stats.get("total_cost_usd", 0.0),
        )

        return extracted_papers, summary_stats

    async def _generate_output(
        self,
        papers: List[PaperMetadata],
        extracted_papers: Any,
        topic: ResearchTopic,
        run_id: str,
        summary_stats: Optional[Dict[str, Any]],
        catalog_topic: Any,
    ) -> Path:
        """Generate markdown output file.

        Args:
            papers: Discovered papers
            extracted_papers: Extracted papers (Phase 2)
            topic: Research topic
            run_id: Run identifier
            summary_stats: Extraction summary stats
            catalog_topic: Catalog topic entry

        Returns:
            Path to generated output file
        """
        assert self.context.config_manager is not None
        assert self.context.md_generator is not None

        output_dir = self.context.config_manager.get_output_path(
            catalog_topic.topic_slug
        )
        filename = f"{datetime.utcnow().strftime('%Y-%m-%d')}_Research.md"
        output_file = output_dir / filename

        # Generate markdown
        if self.context.enable_phase2 and extracted_papers is not None:
            assert isinstance(self.context.md_generator, EnhancedMarkdownGenerator)
            content = self.context.md_generator.generate_enhanced(
                extracted_papers=extracted_papers,
                topic=topic,
                run_id=run_id,
                summary_stats=summary_stats,
            )
        else:
            content = self.context.md_generator.generate(papers, topic, run_id)

        with open(output_file, "w") as f:
            f.write(content)

        self.logger.info(
            "report_generated",
            path=str(output_file),
            phase2=self.context.enable_phase2,
        )

        return output_file

    def _update_catalog(
        self,
        catalog_topic: Any,
        run_id: str,
        papers: List[PaperMetadata],
        topic: ResearchTopic,
        output_file: Path,
        summary_stats: Optional[Dict[str, Any]],
        duration_seconds: float = 0.0,
    ) -> None:
        """Update catalog with run information."""
        from src.models.catalog import CatalogRun

        assert self.context.catalog_service is not None

        papers_processed = len(papers)
        papers_failed = 0
        papers_skipped = 0
        total_cost_usd = 0.0

        if summary_stats:
            papers_processed = summary_stats.get("papers_with_extraction", len(papers))
            papers_failed = summary_stats.get("papers_failed", 0)
            papers_skipped = summary_stats.get("papers_skipped", 0)
            total_cost_usd = summary_stats.get("total_cost_usd", 0.0)

        run = CatalogRun(
            run_id=run_id,
            date=datetime.utcnow(),
            papers_found=len(papers),
            papers_processed=papers_processed,
            papers_failed=papers_failed,
            papers_skipped=papers_skipped,
            timeframe=(
                str(topic.timeframe.value)
                if hasattr(topic.timeframe, "value")
                else "custom"
            ),
            output_file=str(output_file),
            total_cost_usd=total_cost_usd,
            total_duration_seconds=duration_seconds,
        )
        self.context.catalog_service.add_run(catalog_topic.topic_slug, run)

    def _get_processing_results(
        self,
        papers: List[PaperMetadata],
        topic_slug: str,
        extracted_papers: Optional[Any] = None,
    ) -> List[ProcessingResult]:
        """Get processing results for synthesis.

        Args:
            papers: All discovered papers
            topic_slug: Topic slug
            extracted_papers: Extracted papers from Phase 2 (if available)

        Returns:
            List of ProcessingResult for synthesis
        """
        # Phase 2/3: Get processing results from extraction service
        if self.context.extraction_service is not None:
            pipeline_results = self.context.extraction_service.get_processing_results()
            topic_results = [r for r in pipeline_results if r.topic_slug == topic_slug]
            if topic_results:
                return topic_results

        # Fallback: Create basic results with NEW status
        results: List[ProcessingResult] = []

        if extracted_papers:
            for ep in extracted_papers:
                quality_score = 0.0
                if hasattr(ep, "extraction") and ep.extraction:
                    quality_score = getattr(ep.extraction, "quality_score", 0.0)

                results.append(
                    ProcessingResult(
                        paper_id=ep.metadata.paper_id,
                        title=ep.metadata.title or "Untitled",
                        status=ProcessingStatus.NEW,
                        quality_score=quality_score,
                        pdf_available=getattr(ep, "pdf_available", False),
                        extraction_success=ep.extraction is not None,
                        topic_slug=topic_slug,
                    )
                )
        else:
            for paper in papers:
                results.append(
                    ProcessingResult(
                        paper_id=paper.paper_id,
                        title=paper.title or "Untitled",
                        status=ProcessingStatus.NEW,
                        topic_slug=topic_slug,
                    )
                )

        return results

    def _get_default_result(self) -> ExtractionResult:
        """Get default result when phase is skipped."""
        return ExtractionResult()
