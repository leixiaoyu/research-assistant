"""Additional coverage tests for refactored ResearchPipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.orchestration.pipeline import ResearchPipeline
from src.orchestration.context import PipelineContext


@pytest.fixture
def mock_config():
    """Create mock research config."""
    config = MagicMock()
    config.settings.semantic_scholar_api_key = "test-key"
    config.settings.output_base_dir = "./output"
    config.settings.pdf_settings = MagicMock()
    config.settings.pdf_settings.temp_dir = "/tmp"
    config.settings.pdf_settings.max_file_size_mb = 50
    config.settings.pdf_settings.timeout_seconds = 30
    config.settings.pdf_settings.keep_pdfs = False
    config.settings.llm_settings = MagicMock()
    config.settings.llm_settings.provider = "gemini"
    config.settings.llm_settings.model = "gemini-1.5-pro"
    config.settings.llm_settings.api_key = "test-key"
    config.settings.llm_settings.temperature = 0.1
    config.settings.llm_settings.max_tokens = 4096
    config.settings.cost_limits = MagicMock()
    config.settings.cost_limits.max_tokens_per_paper = 10000
    config.settings.cost_limits.max_daily_spend_usd = 10.0
    config.settings.cost_limits.max_total_spend_usd = 100.0
    config.settings.concurrency = None
    config.research_topics = []
    return config


def create_core_service_patches():
    """Create patches for core services."""
    return {
        "config_manager": patch("src.services.config_manager.ConfigManager"),
        "discovery_service": patch("src.services.discovery_service.DiscoveryService"),
        "catalog_service": patch("src.services.catalog_service.CatalogService"),
        "registry_service": patch("src.services.registry_service.RegistryService"),
    }


def create_phase2_service_patches():
    """Create patches for Phase 2 services."""
    return {
        "pdf_service": patch("src.services.pdf_service.PDFService"),
        "llm_service": patch("src.services.llm_service.LLMService"),
        "extraction_service": patch(
            "src.services.extraction_service.ExtractionService"
        ),
        "cache_service": patch("src.services.cache_service.CacheService"),
        "dedup_service": patch("src.services.dedup_service.DeduplicationService"),
        "filter_service": patch("src.services.filter_service.FilterService"),
        "checkpoint_service": patch(
            "src.services.checkpoint_service.CheckpointService"
        ),
        "fallback_service": patch(
            "src.services.pdf_extractors.fallback_service.FallbackPDFService"
        ),
    }


def create_model_patches():
    """Create patches for model classes."""
    return {
        "llm_config": patch("src.models.llm.LLMConfig"),
        "cost_limits": patch("src.models.llm.CostLimits"),
        "cache_config": patch("src.models.cache.CacheConfig"),
        "dedup_config": patch("src.models.dedup.DedupConfig"),
        "filter_config": patch("src.models.filters.FilterConfig"),
        "checkpoint_config": patch("src.models.checkpoint.CheckpointConfig"),
    }


def create_generator_patches():
    """Create patches for generators.

    Note: Some imports happen at module level in pipeline.py, so we patch
    them where they're used (src.orchestration.pipeline.*) not where defined.
    """
    return {
        # Module-level imports in pipeline.py - patch where used
        "markdown_generator": patch("src.orchestration.pipeline.MarkdownGenerator"),
        "enhanced_generator": patch(
            "src.orchestration.pipeline.EnhancedMarkdownGenerator"
        ),
        # These are imported inside _create_context, so patch at source
        "synthesis_engine": patch("src.output.synthesis_engine.SynthesisEngine"),
        "delta_generator": patch("src.output.delta_generator.DeltaGenerator"),
        "cross_synthesis_generator": patch(
            "src.output.cross_synthesis_generator.CrossSynthesisGenerator"
        ),
    }


def create_cross_synthesis_patches():
    """Create patches for cross synthesis services."""
    return {
        "cross_synthesis_service": patch(
            "src.services.cross_synthesis_service.CrossTopicSynthesisService"
        ),
    }


class TestResearchPipelineContextCreation:
    """Tests for context creation in ResearchPipeline."""

    @pytest.mark.asyncio
    async def test_create_context_without_phase2(self, mock_config):
        """Test _create_context without Phase 2 services."""
        pipeline = ResearchPipeline(
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=False,
        )

        patches = {
            **create_core_service_patches(),
            **create_generator_patches(),
        }

        started_patches = {k: p.start() for k, p in patches.items()}
        try:
            started_patches["config_manager"].return_value.load_config.return_value = (
                mock_config
            )
            started_patches["catalog_service"].return_value.load.return_value = None

            context = await pipeline._create_context()

            assert isinstance(context, PipelineContext)
            assert context.enable_phase2 is False
            started_patches["markdown_generator"].assert_called_once()
        finally:
            for p in patches.values():
                p.stop()

    @pytest.mark.asyncio
    async def test_create_context_with_synthesis(self, mock_config):
        """Test _create_context with synthesis enabled."""
        pipeline = ResearchPipeline(
            enable_phase2=False,
            enable_synthesis=True,
            enable_cross_synthesis=False,
        )

        patches = {
            **create_core_service_patches(),
            **create_generator_patches(),
        }

        started_patches = {k: p.start() for k, p in patches.items()}
        try:
            started_patches["config_manager"].return_value.load_config.return_value = (
                mock_config
            )
            started_patches["catalog_service"].return_value.load.return_value = None

            context = await pipeline._create_context()

            assert context.enable_synthesis is True
            started_patches["synthesis_engine"].assert_called_once()
            started_patches["delta_generator"].assert_called_once()
        finally:
            for p in patches.values():
                p.stop()

    @pytest.mark.asyncio
    async def test_create_context_with_cross_synthesis(self, mock_config):
        """Test _create_context with cross synthesis enabled."""
        pipeline = ResearchPipeline(
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=True,
        )

        patches = {
            **create_core_service_patches(),
            **create_generator_patches(),
            **create_cross_synthesis_patches(),
        }

        started_patches = {k: p.start() for k, p in patches.items()}
        try:
            started_patches["config_manager"].return_value.load_config.return_value = (
                mock_config
            )
            started_patches["catalog_service"].return_value.load.return_value = None

            context = await pipeline._create_context()

            assert context.enable_cross_synthesis is True
            started_patches["cross_synthesis_service"].assert_called_once()
            started_patches["cross_synthesis_generator"].assert_called_once()
        finally:
            for p in patches.values():
                p.stop()


class TestResearchPipelinePhase2Init:
    """Tests for Phase 2 service initialization."""

    @pytest.mark.asyncio
    async def test_create_context_with_phase2(self, mock_config):
        """Test _create_context with Phase 2 enabled."""
        pipeline = ResearchPipeline(
            enable_phase2=True,
            enable_synthesis=False,
            enable_cross_synthesis=False,
        )

        patches = {
            **create_core_service_patches(),
            **create_phase2_service_patches(),
            **create_model_patches(),
            **create_generator_patches(),
        }

        started_patches = {k: p.start() for k, p in patches.items()}
        try:
            started_patches["config_manager"].return_value.load_config.return_value = (
                mock_config
            )
            started_patches["catalog_service"].return_value.load.return_value = None

            context = await pipeline._create_context()

            assert context.enable_phase2 is True
            started_patches["pdf_service"].assert_called_once()
            started_patches["llm_service"].assert_called_once()
            started_patches["extraction_service"].assert_called_once()
            started_patches["enhanced_generator"].assert_called_once()
        finally:
            for p in patches.values():
                p.stop()


class TestResearchPipelineBackwardCompatibility:
    """Tests for backward compatibility properties."""

    def test_config_property_with_context(self):
        """Test _config property returns config from context."""
        pipeline = ResearchPipeline()
        mock_context = MagicMock(spec=PipelineContext)
        mock_context.config = MagicMock()
        pipeline._context = mock_context

        assert pipeline._config == mock_context.config

    def test_extraction_service_property_with_context(self):
        """Test _extraction_service property returns service from context."""
        pipeline = ResearchPipeline()
        mock_context = MagicMock(spec=PipelineContext)
        mock_context.extraction_service = MagicMock()
        pipeline._context = mock_context

        assert pipeline._extraction_service == mock_context.extraction_service


class TestResearchPipelinePhaseExecution:
    """Tests for phase execution flow."""

    @pytest.mark.asyncio
    async def test_run_aggregates_phase_results(self, mock_config):
        """Test run properly aggregates results from all phases."""
        pipeline = ResearchPipeline()

        mock_context = MagicMock(spec=PipelineContext)
        mock_context.config = mock_config
        mock_context.errors = []

        with patch.object(
            pipeline, "_create_context", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_context

            phase_patches = {
                "discovery": patch("src.orchestration.pipeline.DiscoveryPhase"),
                "extraction": patch("src.orchestration.pipeline.ExtractionPhase"),
                "synthesis": patch("src.orchestration.pipeline.SynthesisPhase"),
                "cross": patch("src.orchestration.pipeline.CrossSynthesisPhase"),
            }

            started = {k: p.start() for k, p in phase_patches.items()}
            try:
                # Discovery results
                started["discovery"].return_value.run = AsyncMock(
                    return_value=MagicMock(
                        topics_processed=2,
                        topics_failed=1,
                        total_papers=15,
                    )
                )

                # Extraction results
                started["extraction"].return_value.run = AsyncMock(
                    return_value=MagicMock(
                        total_papers_processed=12,
                        total_papers_with_extraction=10,
                        total_tokens_used=5000,
                        total_cost_usd=0.25,
                        output_files=["file1.md", "file2.md"],
                    )
                )

                # Synthesis results
                started["synthesis"].return_value.run = AsyncMock(
                    return_value=MagicMock()
                )

                # Cross-synthesis results with report
                mock_report = MagicMock()
                mock_report.questions_answered = 5
                started["cross"].return_value.run = AsyncMock(
                    return_value=MagicMock(report=mock_report)
                )

                result = await pipeline.run()

                # Verify aggregation
                assert result.topics_processed == 2
                assert result.topics_failed == 1
                assert result.papers_discovered == 15
                assert result.papers_processed == 12
                assert result.papers_with_extraction == 10
                assert result.total_tokens_used == 5000
                assert result.total_cost_usd == 0.25
                assert len(result.output_files) == 2
                assert result.cross_synthesis_report == mock_report
            finally:
                for p in phase_patches.values():
                    p.stop()

    @pytest.mark.asyncio
    async def test_run_without_cross_synthesis_report(self, mock_config):
        """Test run when cross synthesis returns no report."""
        pipeline = ResearchPipeline()

        mock_context = MagicMock(spec=PipelineContext)
        mock_context.config = mock_config
        mock_context.errors = []

        with patch.object(
            pipeline, "_create_context", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_context

            phase_patches = {
                "discovery": patch("src.orchestration.pipeline.DiscoveryPhase"),
                "extraction": patch("src.orchestration.pipeline.ExtractionPhase"),
                "synthesis": patch("src.orchestration.pipeline.SynthesisPhase"),
                "cross": patch("src.orchestration.pipeline.CrossSynthesisPhase"),
            }

            started = {k: p.start() for k, p in phase_patches.items()}
            try:
                for key in ["discovery", "extraction", "synthesis"]:
                    started[key].return_value.run = AsyncMock(
                        return_value=MagicMock(
                            topics_processed=0,
                            topics_failed=0,
                            total_papers=0,
                            total_papers_processed=0,
                            total_papers_with_extraction=0,
                            total_tokens_used=0,
                            total_cost_usd=0,
                            output_files=[],
                        )
                    )

                # Cross synthesis returns no report
                started["cross"].return_value.run = AsyncMock(
                    return_value=MagicMock(report=None)
                )

                result = await pipeline.run()

                assert result.cross_synthesis_report is None
            finally:
                for p in phase_patches.values():
                    p.stop()


class TestResearchPipelinePhase2WithCrossSynthesis:
    """Tests for Phase 2 + cross synthesis interaction."""

    @pytest.mark.asyncio
    async def test_phase2_updates_cross_synthesis_llm_service(self, mock_config):
        """Test that Phase 2 init updates cross-synthesis LLM service."""
        pipeline = ResearchPipeline(
            enable_phase2=True,
            enable_synthesis=False,
            enable_cross_synthesis=True,
        )

        mock_cross_synthesis_service = MagicMock()
        mock_cross_synthesis_service.llm_service = None

        patches = {
            **create_core_service_patches(),
            **create_phase2_service_patches(),
            **create_model_patches(),
            **create_generator_patches(),
            **create_cross_synthesis_patches(),
        }

        started_patches = {k: p.start() for k, p in patches.items()}
        try:
            started_patches["config_manager"].return_value.load_config.return_value = (
                mock_config
            )
            started_patches["catalog_service"].return_value.load.return_value = None
            started_patches["cross_synthesis_service"].return_value = (
                mock_cross_synthesis_service
            )
            mock_llm_instance = MagicMock()
            started_patches["llm_service"].return_value = mock_llm_instance

            await pipeline._create_context()

            # Verify cross-synthesis service got LLM service
            assert mock_cross_synthesis_service.llm_service == mock_llm_instance
        finally:
            for p in patches.values():
                p.stop()
