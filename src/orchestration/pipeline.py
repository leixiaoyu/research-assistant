"""Refactored research pipeline orchestration.

Phase 5.2: Thin orchestrator using extracted phase modules.

This module provides a single entry point for running the complete research pipeline,
delegating phase-specific logic to focused phase modules.

Usage:
    pipeline = ResearchPipeline(config_path=Path("config/research_config.yaml"))
    results = await pipeline.run()
"""

from pathlib import Path
from typing import Any, Optional

import structlog

from src.models.config import ResearchConfig
from src.orchestration.context import PipelineContext
from src.orchestration.phases import (
    CrossSynthesisPhase,
    DiscoveryPhase,
    ExtractionPhase,
    SynthesisPhase,
)
from src.orchestration.result import PipelineResult
from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.output.markdown_generator import MarkdownGenerator

logger = structlog.get_logger()


class ResearchPipeline:
    """Orchestrates the complete research pipeline.

    Phase 5.2: Refactored to use extracted phase modules for better
    separation of concerns and testability.

    Attributes:
        config_path: Path to research configuration file
        enable_phase2: Whether to enable Phase 2 features (PDF/LLM extraction)
        enable_synthesis: Whether to enable Phase 3.6 synthesis
        enable_cross_synthesis: Whether to enable Phase 3.7 cross-topic synthesis
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        enable_phase2: bool = True,
        enable_synthesis: bool = True,
        enable_cross_synthesis: bool = True,
    ) -> None:
        """Initialize the research pipeline.

        Args:
            config_path: Path to research config (default: config/research_config.yaml)
            enable_phase2: Enable Phase 2 PDF/LLM extraction (default: True)
            enable_synthesis: Enable Phase 3.6 synthesis (default: True)
            enable_cross_synthesis: Enable Phase 3.7 cross-topic synthesis
        """
        self.config_path = config_path or Path("config/research_config.yaml")
        self.enable_phase2 = enable_phase2
        self.enable_synthesis = enable_synthesis
        self.enable_cross_synthesis = enable_cross_synthesis

        # Context (initialized on run)
        self._context: Optional[PipelineContext] = None

    async def run(self) -> PipelineResult:
        """Execute the complete research pipeline.

        Returns:
            PipelineResult with execution statistics and output files
        """
        result = PipelineResult()

        try:
            # Initialize context with all services
            self._context = await self._create_context()

            logger.info(
                "pipeline_starting",
                config_path=str(self.config_path),
                phase2_enabled=self.enable_phase2,
                synthesis_enabled=self.enable_synthesis,
                cross_synthesis_enabled=self.enable_cross_synthesis,
                topics_count=len(self._context.config.research_topics),
            )

            # Phase 1: Discovery
            discovery_phase = DiscoveryPhase(self._context)
            discovery_result = await discovery_phase.run()
            result.topics_processed += discovery_result.topics_processed
            result.topics_failed += discovery_result.topics_failed
            result.papers_discovered = discovery_result.total_papers

            # Phase 2: Extraction
            extraction_phase = ExtractionPhase(self._context)
            extraction_result = await extraction_phase.run()
            result.papers_processed = extraction_result.total_papers_processed
            result.papers_with_extraction = (
                extraction_result.total_papers_with_extraction
            )
            result.total_tokens_used = extraction_result.total_tokens_used
            result.total_cost_usd = extraction_result.total_cost_usd
            result.output_files = extraction_result.output_files

            # Phase 3.6: Synthesis
            synthesis_phase = SynthesisPhase(self._context)
            await synthesis_phase.run()

            # Phase 3.7: Cross-topic synthesis
            cross_synthesis_phase = CrossSynthesisPhase(self._context)
            cross_result = await cross_synthesis_phase.run()
            if cross_result.report:
                result.cross_synthesis_report = cross_result.report

            # Collect errors from context
            result.errors = self._context.errors.copy()

            logger.info(
                "pipeline_completed",
                topics_processed=result.topics_processed,
                papers_discovered=result.papers_discovered,
                papers_processed=result.papers_processed,
                output_files=len(result.output_files),
                errors=len(result.errors),
                cross_synthesis_questions=(
                    result.cross_synthesis_report.questions_answered
                    if result.cross_synthesis_report
                    else 0
                ),
            )

        except Exception as e:
            logger.exception("pipeline_failed", error=str(e))
            result.errors.append({"phase": "pipeline", "error": str(e)})

        return result

    async def _create_context(self) -> PipelineContext:
        """Create and initialize pipeline context with all services.

        Returns:
            Initialized PipelineContext
        """
        from src.services.config_manager import ConfigManager
        from src.services.discovery_service import DiscoveryService
        from src.services.catalog_service import CatalogService
        from src.services.registry_service import RegistryService
        from src.output.synthesis_engine import SynthesisEngine
        from src.output.delta_generator import DeltaGenerator

        # Load configuration
        config_manager = ConfigManager(config_path=str(self.config_path))
        config = config_manager.load_config()

        # Core services
        discovery_service = DiscoveryService(
            api_key=config.settings.semantic_scholar_api_key or ""
        )

        catalog_service = CatalogService(config_manager)
        catalog_service.load()

        registry_service = RegistryService()

        # Create context
        context = PipelineContext(
            config=config,
            config_path=self.config_path,
            config_manager=config_manager,
            discovery_service=discovery_service,
            catalog_service=catalog_service,
            registry_service=registry_service,
            enable_phase2=self.enable_phase2,
            enable_synthesis=self.enable_synthesis,
            enable_cross_synthesis=self.enable_cross_synthesis,
        )

        # Synthesis services
        if self.enable_synthesis:
            output_base = Path(config.settings.output_base_dir)
            context.synthesis_engine = SynthesisEngine(
                registry_service=registry_service,
                output_base_dir=output_base,
            )
            context.delta_generator = DeltaGenerator(output_base_dir=output_base)

        # Cross-synthesis services
        if self.enable_cross_synthesis:
            from src.services.cross_synthesis_service import CrossTopicSynthesisService
            from src.output.cross_synthesis_generator import CrossSynthesisGenerator

            context.cross_synthesis_generator = CrossSynthesisGenerator()
            context.cross_synthesis_service = CrossTopicSynthesisService(
                registry_service=registry_service,
                llm_service=None,  # Set later if Phase 2 enabled
            )

        # Phase 2 services
        if self.enable_phase2:
            await self._initialize_phase2_services(context, config)
        else:
            context.md_generator = MarkdownGenerator()

        return context

    async def _initialize_phase2_services(
        self,
        context: PipelineContext,
        config: ResearchConfig,
    ) -> None:
        """Initialize Phase 2 extraction services.

        Args:
            context: Pipeline context to update
            config: Research configuration
        """
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

        pdf_settings = config.settings.pdf_settings
        llm_settings = config.settings.llm_settings
        cost_limits_config = config.settings.cost_limits

        # Phase 2 requires all settings
        assert pdf_settings is not None
        assert llm_settings is not None
        assert cost_limits_config is not None

        # PDF Service
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

        # Fallback PDF Service
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
        context.extraction_service = ExtractionService(
            pdf_service=pdf_service,
            llm_service=llm_service,
            fallback_service=fallback_service,
            keep_pdfs=pdf_settings.keep_pdfs,
            cache_service=cache_service,
            dedup_service=dedup_service,
            filter_service=filter_service,
            checkpoint_service=checkpoint_service,
            concurrency_config=config.settings.concurrency,
            registry_service=context.registry_service,
        )

        # Enhanced Markdown Generator
        context.md_generator = EnhancedMarkdownGenerator()

        # Update cross-synthesis service with LLM service
        if context.cross_synthesis_service is not None:
            context.cross_synthesis_service.llm_service = llm_service

        logger.info("phase2_services_initialized")

    # Backward compatibility properties
    @property
    def _config(self) -> Optional[ResearchConfig]:
        """Backward compatibility: access config from context."""
        return self._context.config if self._context else None

    @property
    def _extraction_service(self) -> Optional[Any]:
        """Backward compatibility: access extraction service from context."""
        return self._context.extraction_service if self._context else None

    @property
    def _registry_service(self) -> Optional[Any]:
        """Backward compatibility: access registry service from context."""
        return self._context.registry_service if self._context else None

    @property
    def _config_manager(self) -> Optional[Any]:
        """Backward compatibility: access config manager from context."""
        return self._context.config_manager if self._context else None

    @property
    def _catalog_service(self) -> Optional[Any]:
        """Backward compatibility: access catalog service from context."""
        return self._context.catalog_service if self._context else None

    @property
    def _discovery_service(self) -> Optional[Any]:
        """Backward compatibility: access discovery service from context."""
        return self._context.discovery_service if self._context else None

    @property
    def _synthesis_engine(self) -> Optional[Any]:
        """Backward compatibility: access synthesis engine from context."""
        return self._context.synthesis_engine if self._context else None

    @property
    def _delta_generator(self) -> Optional[Any]:
        """Backward compatibility: access delta generator from context."""
        return self._context.delta_generator if self._context else None

    @property
    def _cross_synthesis_service(self) -> Optional[Any]:
        """Backward compatibility: access cross synthesis service from context."""
        return self._context.cross_synthesis_service if self._context else None

    @property
    def _cross_synthesis_generator(self) -> Optional[Any]:
        """Backward compatibility: access cross synthesis generator from context."""
        return self._context.cross_synthesis_generator if self._context else None

    @property
    def _md_generator(self) -> Optional[Any]:
        """Backward compatibility: access markdown generator from context."""
        return self._context.md_generator if self._context else None

    def _get_processing_results(
        self,
        papers: Any,
        topic_slug: str,
        extracted_papers: Optional[Any] = None,
    ) -> Any:
        """Backward compatibility: get processing results for synthesis.

        Args:
            papers: All discovered papers
            topic_slug: Topic slug
            extracted_papers: Extracted papers from Phase 2 (if available)

        Returns:
            List of ProcessingResult for synthesis
        """
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        # Phase 2/3: Get processing results from extraction service
        if self._extraction_service is not None:
            pipeline_results = self._extraction_service.get_processing_results()
            topic_results = [r for r in pipeline_results if r.topic_slug == topic_slug]
            if topic_results:
                return topic_results

        # Fallback: Create basic results with NEW status
        results = []

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
