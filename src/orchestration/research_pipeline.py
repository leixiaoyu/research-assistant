"""Reusable research pipeline orchestration.

Provides a single entry point for running the complete research pipeline,
ensuring feature parity between CLI and scheduled job execution.

Usage:
    pipeline = ResearchPipeline(config_path=Path("config/research_config.yaml"))
    results = await pipeline.run()
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import structlog

from src.models.catalog import CatalogRun
from src.models.config import ResearchConfig, ResearchTopic
from src.models.paper import PaperMetadata
from src.models.synthesis import ProcessingResult
from src.services.providers.base import APIError
from src.output.markdown_generator import MarkdownGenerator
from src.output.enhanced_generator import EnhancedMarkdownGenerator

# Conditional type imports for type hints
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.config_manager import ConfigManager
    from src.services.discovery_service import DiscoveryService
    from src.services.catalog_service import CatalogService
    from src.services.extraction_service import ExtractionService
    from src.services.registry_service import RegistryService
    from src.output.synthesis_engine import SynthesisEngine
    from src.output.delta_generator import DeltaGenerator
    from src.models.catalog import TopicCatalogEntry

logger = structlog.get_logger()


class PipelineResult:
    """Result of a pipeline run."""

    def __init__(self) -> None:
        self.topics_processed: int = 0
        self.topics_failed: int = 0
        self.papers_discovered: int = 0
        self.papers_processed: int = 0
        self.papers_with_extraction: int = 0
        self.total_tokens_used: int = 0
        self.total_cost_usd: float = 0.0
        self.output_files: List[str] = []
        self.errors: List[Dict[str, str]] = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "topics_processed": self.topics_processed,
            "topics_failed": self.topics_failed,
            "papers_discovered": self.papers_discovered,
            "papers_processed": self.papers_processed,
            "papers_with_extraction": self.papers_with_extraction,
            "total_tokens_used": self.total_tokens_used,
            "total_cost_usd": self.total_cost_usd,
            "output_files": self.output_files,
            "errors": self.errors,
        }


class ResearchPipeline:
    """Orchestrates the complete research pipeline.

    This class provides a single, reusable entry point for running the
    research pipeline with all phases (Discovery, Extraction, Report Generation).

    Used by both the CLI `run` command and the scheduled `DailyResearchJob`
    to ensure feature parity.

    Attributes:
        config_path: Path to research configuration file
        enable_phase2: Whether to enable Phase 2 features (PDF/LLM extraction)
        enable_synthesis: Whether to enable Phase 3.6 synthesis
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        enable_phase2: bool = True,
        enable_synthesis: bool = True,
    ) -> None:
        """Initialize the research pipeline.

        Args:
            config_path: Path to research config (default: config/research_config.yaml)
            enable_phase2: Enable Phase 2 PDF/LLM extraction (default: True)
            enable_synthesis: Enable Phase 3.6 synthesis (default: True)
        """
        self.config_path = config_path or Path("config/research_config.yaml")
        self.enable_phase2 = enable_phase2
        self.enable_synthesis = enable_synthesis

        # Services (initialized on run)
        self._config: Optional[ResearchConfig] = None
        self._config_manager: Optional["ConfigManager"] = None
        self._discovery_service: Optional["DiscoveryService"] = None
        self._catalog_service: Optional["CatalogService"] = None
        self._extraction_service: Optional["ExtractionService"] = None
        self._registry_service: Optional["RegistryService"] = None
        self._synthesis_engine: Optional["SynthesisEngine"] = None
        self._delta_generator: Optional["DeltaGenerator"] = None
        self._md_generator: Optional[
            Union[MarkdownGenerator, EnhancedMarkdownGenerator]
        ] = None

        # Processing results for synthesis (Phase 3.6)
        self._topic_processing_results: Dict[str, List[ProcessingResult]] = {}

    async def run(self) -> PipelineResult:
        """Execute the complete research pipeline.

        Returns:
            PipelineResult with execution statistics and output files
        """
        result = PipelineResult()

        try:
            # Initialize all services
            await self._initialize_services()

            # Type assertions after initialization
            assert self._config is not None
            assert self._config_manager is not None
            assert self._discovery_service is not None
            assert self._catalog_service is not None
            assert self._md_generator is not None

            logger.info(
                "pipeline_starting",
                config_path=str(self.config_path),
                phase2_enabled=self.enable_phase2,
                synthesis_enabled=self.enable_synthesis,
                topics_count=len(self._config.research_topics),
            )

            # Process each topic
            for topic in self._config.research_topics:
                topic_result = await self._process_topic(topic)
                self._merge_topic_result(result, topic_result)

            # Phase 3.6: Run synthesis for all processed topics
            if self.enable_synthesis:
                await self._run_synthesis()

            logger.info(
                "pipeline_completed",
                topics_processed=result.topics_processed,
                papers_discovered=result.papers_discovered,
                papers_processed=result.papers_processed,
                output_files=len(result.output_files),
                errors=len(result.errors),
            )

        except Exception as e:
            logger.exception("pipeline_failed", error=str(e))
            result.errors.append({"topic": "pipeline", "error": str(e)})

        return result

    async def _initialize_services(self) -> None:
        """Initialize all required services."""
        from src.services.config_manager import ConfigManager
        from src.services.discovery_service import DiscoveryService
        from src.services.catalog_service import CatalogService
        from src.services.registry_service import RegistryService
        from src.output.synthesis_engine import SynthesisEngine
        from src.output.delta_generator import DeltaGenerator

        # Core services
        self._config_manager = ConfigManager(config_path=str(self.config_path))
        self._config = self._config_manager.load_config()

        self._discovery_service = DiscoveryService(
            api_key=self._config.settings.semantic_scholar_api_key or ""
        )

        self._catalog_service = CatalogService(self._config_manager)
        self._catalog_service.load()

        # Phase 3.5: Registry service (global identity)
        self._registry_service = RegistryService()

        # Phase 3.6: Synthesis services
        if self.enable_synthesis:
            output_base = Path(self._config.settings.output_base_dir)
            self._synthesis_engine = SynthesisEngine(
                registry_service=self._registry_service,
                output_base_dir=output_base,
            )
            self._delta_generator = DeltaGenerator(output_base_dir=output_base)

        # Phase 2 services (if enabled)
        if self.enable_phase2:  # pragma: no cover (Phase 2 tested via integration)
            await self._initialize_phase2_services()
        else:
            self._md_generator = MarkdownGenerator()

    async def _initialize_phase2_services(  # pragma: no cover (Phase 2 integration)
        self,
    ) -> None:
        """Initialize Phase 2 extraction services."""
        from src.services.pdf_service import PDFService
        from src.services.llm_service import LLMService
        from src.services.extraction_service import ExtractionService
        from src.services.cache_service import CacheService
        from src.services.dedup_service import DeduplicationService
        from src.services.filter_service import FilterService
        from src.services.checkpoint_service import CheckpointService
        from src.services.pdf_extractors.fallback_service import FallbackPDFService
        from src.models.cache import CacheConfig
        from src.models.dedup import DedupConfig
        from src.models.filters import FilterConfig
        from src.models.checkpoint import CheckpointConfig
        from src.models.llm import LLMConfig, CostLimits

        # Type assertion - _config must be initialized
        assert self._config is not None
        pdf_settings = self._config.settings.pdf_settings
        llm_settings = self._config.settings.llm_settings
        cost_limits_config = self._config.settings.cost_limits

        # Phase 2 requires all settings
        assert pdf_settings is not None
        assert llm_settings is not None
        assert cost_limits_config is not None

        # PDF Service (uses individual parameters)
        pdf_service = PDFService(
            temp_dir=Path(pdf_settings.temp_dir),
            max_size_mb=pdf_settings.max_file_size_mb,
            timeout_seconds=pdf_settings.timeout_seconds,
        )

        # LLM Service
        llm_config = LLMConfig(
            provider=llm_settings.provider,
            model=llm_settings.model,
            api_key=llm_settings.api_key or "",
            temperature=llm_settings.temperature,
            max_tokens=llm_settings.max_tokens,
        )

        cost_limits = CostLimits(
            max_tokens_per_paper=cost_limits_config.max_tokens_per_paper,
            max_daily_spend_usd=cost_limits_config.max_daily_spend_usd,
            max_total_spend_usd=cost_limits_config.max_total_spend_usd,
        )

        llm_service = LLMService(config=llm_config, cost_limits=cost_limits)

        # Fallback PDF Service (uses config object)
        fallback_service = FallbackPDFService(config=pdf_settings)

        # Phase 3 Services
        cache_service = CacheService(config=CacheConfig())  # type: ignore[call-arg]
        dedup_service = DeduplicationService(
            config=DedupConfig()  # type: ignore[call-arg]
        )
        filter_service = FilterService(config=FilterConfig())  # type: ignore[call-arg]
        checkpoint_service = CheckpointService(
            config=CheckpointConfig()  # type: ignore[call-arg]
        )

        # Extraction Service
        self._extraction_service = ExtractionService(
            pdf_service=pdf_service,
            llm_service=llm_service,
            fallback_service=fallback_service,
            keep_pdfs=pdf_settings.keep_pdfs,
            cache_service=cache_service,
            dedup_service=dedup_service,
            filter_service=filter_service,
            checkpoint_service=checkpoint_service,
            concurrency_config=self._config.settings.concurrency,
            registry_service=self._registry_service,  # Phase 3.8
        )

        # Enhanced Markdown Generator
        self._md_generator = EnhancedMarkdownGenerator()

        logger.info("phase2_services_initialized")

    async def _process_topic(self, topic: ResearchTopic) -> Dict[str, Any]:
        """Process a single research topic.

        Args:
            topic: ResearchTopic to process

        Returns:
            Dictionary with topic processing results
        """
        start_time = time.time()
        topic_result: Dict[str, Any] = {
            "success": False,
            "papers_discovered": 0,
            "papers_processed": 0,
            "papers_with_extraction": 0,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "output_file": None,
            "error": None,
        }

        run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

        # Type assertions
        assert self._catalog_service is not None
        assert self._discovery_service is not None
        assert self._config_manager is not None
        assert self._md_generator is not None

        try:
            logger.info(
                "processing_topic",
                topic=topic.query,
                run_id=run_id,
                phase2=self.enable_phase2,
            )

            # A. Get/Create Topic in Catalog
            catalog_topic = self._catalog_service.get_or_create_topic(topic.query)

            # B. Discovery
            papers = await self._discovery_service.search(topic)
            topic_result["papers_discovered"] = len(papers)

            if not papers:
                logger.warning("no_papers_found", topic=topic.query)
                topic_result["success"] = True
                return topic_result

            # C. Phase 2: PDF Processing & LLM Extraction
            extracted_papers = None
            summary_stats: Optional[Dict[str, Any]] = None

            if (  # pragma: no cover (Phase 2 tested via integration)
                self.enable_phase2
                and self._extraction_service
                and topic.extraction_targets
            ):
                extracted_papers, summary_stats = await self._run_extraction(
                    papers, topic, run_id, catalog_topic.topic_slug  # Phase 3.8
                )
                if summary_stats:
                    topic_result["papers_with_extraction"] = summary_stats[
                        "papers_with_extraction"
                    ]
                    topic_result["tokens_used"] = summary_stats["total_tokens_used"]
                    topic_result["cost_usd"] = summary_stats["total_cost_usd"]

            # D. Generate Output
            output_file = await self._generate_output(
                papers=papers,
                extracted_papers=extracted_papers,
                topic=topic,
                run_id=run_id,
                summary_stats=summary_stats,
                catalog_topic=catalog_topic,
            )
            topic_result["output_file"] = str(output_file)
            topic_result["papers_processed"] = (
                summary_stats["papers_with_extraction"]
                if summary_stats
                else len(papers)
            )

            # Phase 3.6: Store processing results for synthesis
            if self.enable_synthesis and self._extraction_service:
                # Get processing results from extraction service if available
                processing_results = self._get_processing_results(
                    papers=papers,
                    topic_slug=catalog_topic.topic_slug,
                    extracted_papers=extracted_papers,
                )
                self._topic_processing_results[catalog_topic.topic_slug] = (
                    processing_results
                )

            # E. Update Catalog
            duration = time.time() - start_time
            self._update_catalog(
                catalog_topic=catalog_topic,
                run_id=run_id,
                papers=papers,
                topic=topic,
                output_file=output_file,
                summary_stats=summary_stats,
                duration_seconds=duration,
            )

            topic_result["success"] = True
            logger.info(
                "topic_completed",
                topic=topic.query,
                papers_discovered=topic_result["papers_discovered"],
                papers_processed=topic_result["papers_processed"],
                output_file=str(output_file),
            )

        except APIError as e:
            topic_result["error"] = str(e)
            logger.error("topic_failed", topic=topic.query, error=str(e))
        except Exception as e:
            topic_result["error"] = str(e)
            logger.exception("topic_unexpected_error", topic=topic.query)

        return topic_result

    async def _run_extraction(  # pragma: no cover (Phase 2 tested via integration)
        self,
        papers: List[PaperMetadata],
        topic: ResearchTopic,
        run_id: str,
        topic_slug: str,  # Phase 3.8: For registry integration
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        """Run Phase 2 extraction pipeline.

        Args:
            papers: Papers to process
            topic: Research topic
            run_id: Run identifier
            topic_slug: Topic slug for registry affiliation (Phase 3.5/3.8)

        Returns:
            Tuple of (extracted_papers, summary_stats)
        """
        # Type assertions
        assert self._extraction_service is not None
        assert topic.extraction_targets is not None

        logger.info(
            "starting_extraction",
            topic=topic.query,
            papers_count=len(papers),
            targets_count=len(topic.extraction_targets),
        )

        extracted_papers = await self._extraction_service.process_papers(
            papers=papers,
            targets=topic.extraction_targets,
            run_id=run_id,
            query=topic.query,
            topic_slug=topic_slug,  # Phase 3.8
        )

        summary_stats = self._extraction_service.get_extraction_summary(
            extracted_papers
        )

        logger.info(
            "extraction_completed",
            topic=topic.query,
            papers_with_pdf=summary_stats["papers_with_pdf"],
            papers_with_extraction=summary_stats["papers_with_extraction"],
            total_tokens=summary_stats["total_tokens_used"],
            total_cost_usd=summary_stats["total_cost_usd"],
        )

        return extracted_papers, summary_stats

    async def _generate_output(
        self,
        papers: List[PaperMetadata],
        extracted_papers: Any,
        topic: ResearchTopic,
        run_id: str,
        summary_stats: Optional[Dict[str, Any]],
        catalog_topic: "TopicCatalogEntry",
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
        # Type assertion
        assert self._config_manager is not None
        assert self._md_generator is not None

        output_dir = self._config_manager.get_output_path(catalog_topic.topic_slug)
        filename = f"{datetime.utcnow().strftime('%Y-%m-%d')}_Research.md"
        output_file = output_dir / filename

        # Generate markdown
        if (  # pragma: no cover (Phase 2 tested via integration)
            self.enable_phase2 and extracted_papers is not None
        ):
            assert isinstance(self._md_generator, EnhancedMarkdownGenerator)
            content = self._md_generator.generate_enhanced(
                extracted_papers=extracted_papers,
                topic=topic,
                run_id=run_id,
                summary_stats=summary_stats,
            )
        else:
            content = self._md_generator.generate(papers, topic, run_id)

        with open(output_file, "w") as f:
            f.write(content)

        logger.info(
            "report_generated",
            path=str(output_file),
            phase2=self.enable_phase2,
        )

        return output_file

    def _update_catalog(
        self,
        catalog_topic: "TopicCatalogEntry",
        run_id: str,
        papers: List[PaperMetadata],
        topic: ResearchTopic,
        output_file: Path,
        summary_stats: Optional[Dict[str, Any]],
        duration_seconds: float = 0.0,
    ) -> None:
        """Update catalog with run information.

        Args:
            catalog_topic: Catalog topic entry
            run_id: Run identifier
            papers: Discovered papers
            topic: Research topic
            output_file: Path to output file
            summary_stats: Extraction summary stats
            duration_seconds: Total run duration in seconds
        """
        # Type assertion
        assert self._catalog_service is not None

        papers_processed = len(papers)
        papers_failed = 0
        papers_skipped = 0
        total_cost_usd = 0.0

        if summary_stats:  # pragma: no cover (Phase 2 tested via integration)
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
        self._catalog_service.add_run(catalog_topic.topic_slug, run)

    async def _run_synthesis(self) -> None:
        """Run Phase 3.6 synthesis for all processed topics.

        Generates:
        - Delta briefs (YYYY-MM-DD_Delta.md) for each topic's run
        - Updated Knowledge_Base.md for each topic
        """
        if not self._synthesis_engine or not self._delta_generator:
            logger.warning("synthesis_skipped", reason="services not initialized")
            return

        logger.info(
            "synthesis_starting",
            topics=list(self._topic_processing_results.keys()),
        )

        for topic_slug, results in self._topic_processing_results.items():
            try:
                # Generate Delta Brief for this run
                delta_path = self._delta_generator.generate(
                    results=results,
                    topic_slug=topic_slug,
                )

                if delta_path:
                    logger.info(
                        "delta_generated",
                        topic=topic_slug,
                        path=str(delta_path),
                    )

                # Synthesize Knowledge Base
                stats = self._synthesis_engine.synthesize(topic_slug)

                logger.info(
                    "knowledge_base_synthesized",
                    topic=topic_slug,
                    total_papers=stats.total_papers,
                    average_quality=stats.average_quality,
                    duration_ms=stats.synthesis_duration_ms,
                )

            except Exception as e:
                logger.error(
                    "synthesis_failed",
                    topic=topic_slug,
                    error=str(e),
                    exc_info=True,
                )

        logger.info("synthesis_completed")

    def _get_processing_results(
        self,
        papers: List[PaperMetadata],
        topic_slug: str,
        extracted_papers: Optional[Any] = None,
    ) -> List[ProcessingResult]:
        """Get processing results for synthesis from the extraction service.

        Retrieves ProcessingResult objects with proper statuses (NEW, BACKFILLED,
        SKIPPED, MAPPED) as determined by the RegistryService during concurrent
        processing. Falls back to basic results only for Phase 1 mode.

        Args:
            papers: All discovered papers.
            topic_slug: Topic slug.
            extracted_papers: Extracted papers from Phase 2 (if available).

        Returns:
            List of ProcessingResult for synthesis.
        """
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        # Phase 2/3: Get processing results from extraction service
        # These have proper statuses from RegistryService (NEW, BACKFILLED, etc.)
        if self._extraction_service is not None:
            pipeline_results = self._extraction_service.get_processing_results()
            # Filter to results for this topic
            topic_results = [r for r in pipeline_results if r.topic_slug == topic_slug]
            if topic_results:
                return topic_results

        # Fallback: Phase 1 mode or extraction service not available
        # Create basic results with NEW status
        results: List[ProcessingResult] = []

        if extracted_papers:
            # Phase 2 without concurrent pipeline - use extracted papers
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
            # Phase 1 mode - just mark papers as new
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

    def _merge_topic_result(
        self, result: PipelineResult, topic_result: Dict[str, Any]
    ) -> None:
        """Merge topic result into pipeline result.

        Args:
            result: Pipeline result to update
            topic_result: Topic processing result
        """
        if topic_result["success"]:
            result.topics_processed += 1
        else:
            result.topics_failed += 1
            error_msg = topic_result.get("error", "Unknown error")
            if error_msg:
                result.errors.append({"topic": "unknown", "error": error_msg})

        result.papers_discovered += topic_result["papers_discovered"]
        result.papers_processed += topic_result["papers_processed"]
        result.papers_with_extraction += topic_result["papers_with_extraction"]
        result.total_tokens_used += topic_result["tokens_used"]
        result.total_cost_usd += topic_result["cost_usd"]

        if topic_result["output_file"]:
            result.output_files.append(topic_result["output_file"])
