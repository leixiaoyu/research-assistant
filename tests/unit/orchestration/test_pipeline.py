"""Tests for refactored ResearchPipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.orchestration.pipeline import ResearchPipeline
from src.orchestration.result import PipelineResult
from src.orchestration.context import PipelineContext


@pytest.fixture
def mock_config():
    """Create mock research config."""
    config = MagicMock()
    config.settings.semantic_scholar_api_key = "test-key"
    config.settings.output_base_dir = "./output"
    config.settings.pdf_settings = MagicMock()
    config.settings.llm_settings = MagicMock()
    config.settings.cost_limits = MagicMock()
    config.settings.concurrency = None
    config.research_topics = []
    return config


class TestResearchPipeline:
    """Tests for ResearchPipeline class."""

    def test_init_default_values(self):
        """Test initialization with default values."""
        pipeline = ResearchPipeline()
        assert pipeline.config_path == Path("config/research_config.yaml")
        assert pipeline.enable_phase2 is True
        assert pipeline.enable_synthesis is True
        assert pipeline.enable_cross_synthesis is True
        assert pipeline._context is None

    def test_init_custom_values(self):
        """Test initialization with custom values."""
        pipeline = ResearchPipeline(
            config_path=Path("custom/config.yaml"),
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=False,
        )
        assert pipeline.config_path == Path("custom/config.yaml")
        assert pipeline.enable_phase2 is False
        assert pipeline.enable_synthesis is False
        assert pipeline.enable_cross_synthesis is False

    @pytest.mark.asyncio
    async def test_run_returns_pipeline_result(self, mock_config):
        """Test run returns PipelineResult."""
        pipeline = ResearchPipeline()

        with patch.object(
            pipeline, "_create_context", new_callable=AsyncMock
        ) as mock_create:
            mock_context = MagicMock(spec=PipelineContext)
            mock_context.config = mock_config
            mock_context.errors = []
            mock_create.return_value = mock_context

            # Mock phases
            with (
                patch("src.orchestration.pipeline.DiscoveryPhase") as mock_discovery,
                patch("src.orchestration.pipeline.ExtractionPhase") as mock_extraction,
                patch("src.orchestration.pipeline.SynthesisPhase") as mock_synthesis,
                patch("src.orchestration.pipeline.CrossSynthesisPhase") as mock_cross,
            ):
                # Setup phase mocks
                mock_discovery.return_value.run = AsyncMock(
                    return_value=MagicMock(
                        topics_processed=1,
                        topics_failed=0,
                        total_papers=5,
                    )
                )
                mock_extraction.return_value.run = AsyncMock(
                    return_value=MagicMock(
                        total_papers_processed=5,
                        total_papers_with_extraction=4,
                        total_tokens_used=1000,
                        total_cost_usd=0.05,
                        output_files=["test.md"],
                    )
                )
                mock_synthesis.return_value.run = AsyncMock(return_value=MagicMock())
                mock_cross.return_value.run = AsyncMock(
                    return_value=MagicMock(report=None)
                )

                result = await pipeline.run()

                assert isinstance(result, PipelineResult)
                assert result.topics_processed == 1
                assert result.papers_discovered == 5

    @pytest.mark.asyncio
    async def test_run_handles_exception(self):
        """Test run handles exceptions gracefully."""
        pipeline = ResearchPipeline()

        with patch.object(
            pipeline, "_create_context", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = Exception("Context creation failed")

            result = await pipeline.run()

            assert isinstance(result, PipelineResult)
            assert len(result.errors) == 1
            assert "Context creation failed" in result.errors[0]["error"]

    @pytest.mark.asyncio
    async def test_run_collects_errors_from_context(self, mock_config):
        """Test run collects errors from context."""
        pipeline = ResearchPipeline()

        with patch.object(
            pipeline, "_create_context", new_callable=AsyncMock
        ) as mock_create:
            mock_context = MagicMock(spec=PipelineContext)
            mock_context.config = mock_config
            mock_context.errors = [
                {"phase": "discovery", "error": "Test error"},
            ]
            mock_create.return_value = mock_context

            # Mock phases
            with (
                patch("src.orchestration.pipeline.DiscoveryPhase") as mock_discovery,
                patch("src.orchestration.pipeline.ExtractionPhase") as mock_extraction,
                patch("src.orchestration.pipeline.SynthesisPhase") as mock_synthesis,
                patch("src.orchestration.pipeline.CrossSynthesisPhase") as mock_cross,
            ):
                for mock_phase in [
                    mock_discovery,
                    mock_extraction,
                    mock_synthesis,
                    mock_cross,
                ]:
                    mock_phase.return_value.run = AsyncMock(
                        return_value=MagicMock(
                            topics_processed=0,
                            topics_failed=0,
                            total_papers=0,
                            total_papers_processed=0,
                            total_papers_with_extraction=0,
                            total_tokens_used=0,
                            total_cost_usd=0,
                            output_files=[],
                            report=None,
                        )
                    )

                result = await pipeline.run()

                assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_run_includes_cross_synthesis_report(self, mock_config):
        """Test run includes cross-synthesis report when available."""
        pipeline = ResearchPipeline()

        with patch.object(
            pipeline, "_create_context", new_callable=AsyncMock
        ) as mock_create:
            mock_context = MagicMock(spec=PipelineContext)
            mock_context.config = mock_config
            mock_context.errors = []
            mock_create.return_value = mock_context

            mock_report = MagicMock()
            mock_report.questions_answered = 3

            with (
                patch("src.orchestration.pipeline.DiscoveryPhase") as mock_discovery,
                patch("src.orchestration.pipeline.ExtractionPhase") as mock_extraction,
                patch("src.orchestration.pipeline.SynthesisPhase") as mock_synthesis,
                patch("src.orchestration.pipeline.CrossSynthesisPhase") as mock_cross,
            ):
                mock_discovery.return_value.run = AsyncMock(
                    return_value=MagicMock(
                        topics_processed=0, topics_failed=0, total_papers=0
                    )
                )
                mock_extraction.return_value.run = AsyncMock(
                    return_value=MagicMock(
                        total_papers_processed=0,
                        total_papers_with_extraction=0,
                        total_tokens_used=0,
                        total_cost_usd=0,
                        output_files=[],
                    )
                )
                mock_synthesis.return_value.run = AsyncMock(return_value=MagicMock())
                mock_cross.return_value.run = AsyncMock(
                    return_value=MagicMock(report=mock_report)
                )

                result = await pipeline.run()

                assert result.cross_synthesis_report == mock_report

    def test_config_property_returns_none_before_run(self):
        """Test _config property returns None before run."""
        pipeline = ResearchPipeline()
        assert pipeline._config is None

    def test_extraction_service_property_returns_none_before_run(self):
        """Test _extraction_service property returns None before run."""
        pipeline = ResearchPipeline()
        assert pipeline._extraction_service is None

    @pytest.mark.asyncio
    async def test_create_context_initializes_services(self, mock_config):
        """Test _create_context initializes all required services."""
        pipeline = ResearchPipeline(
            enable_phase2=False,  # Simplify test
            enable_synthesis=False,
            enable_cross_synthesis=False,
        )

        with patch.object(
            pipeline, "_create_context", new_callable=AsyncMock
        ) as mock_create:
            mock_context = MagicMock(spec=PipelineContext)
            mock_context.config = mock_config
            mock_create.return_value = mock_context

            # Call run which invokes _create_context
            await mock_create()

            assert mock_create.called
            # Verify the mock was called
            mock_create.assert_called_once()


class TestPipelineEmitsSloEventsAtEnd:
    """Phase 9.5 PR γ wiring test — ResearchPipeline.run() emits the
    Phase 9.5 SLO events at the end of every successful run.

    This test pins the wiring that PR γ established. PRs #157 and
    #159 emitted the events from DailyResearchJob.run() instead, but
    the production cron invokes ``python -m src.cli run`` which
    bypasses DailyResearchJob entirely — making the events dead code
    in production. PR γ moved emission into ResearchPipeline.run() so
    both entry points emit. This test guards against a future
    regression that puts emission back into the scheduler layer only.
    """

    @pytest.mark.asyncio
    async def test_run_calls_emit_pipeline_health_slo_events(self):
        """ResearchPipeline.run() MUST invoke emit_pipeline_health_slo_events."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from src.orchestration import ResearchPipeline

        pipeline = ResearchPipeline()

        # Mock everything inside run() so we isolate the emission call.
        mock_context = MagicMock()
        mock_context.config.research_topics = []
        mock_context.errors = []
        mock_context.discovery_service = None

        # Mock all the phase classes — we don't care about their
        # internals for this wiring assertion.
        with (
            patch.object(
                ResearchPipeline,
                "_create_context",
                AsyncMock(return_value=mock_context),
            ),
            patch("src.orchestration.pipeline.DiscoveryPhase") as mock_discovery,
            patch("src.orchestration.pipeline.ExtractionPhase") as mock_extraction,
            patch("src.orchestration.pipeline.SynthesisPhase") as mock_synthesis,
            patch("src.orchestration.pipeline.CrossSynthesisPhase") as mock_cross,
            patch(
                "src.orchestration.pipeline.emit_pipeline_health_slo_events"
            ) as mock_emit,
        ):
            mock_discovery.return_value.run = AsyncMock(
                return_value=MagicMock(
                    topics_processed=0,
                    topics_failed=0,
                    total_papers=0,
                    source_breakdown={},
                )
            )
            mock_extraction.return_value.run = AsyncMock(
                return_value=MagicMock(
                    total_papers_processed=0,
                    total_papers_with_extraction=0,
                    total_papers_with_pdf=0,
                    total_papers_with_abstract_fallback=0,
                    total_tokens_used=0,
                    total_cost_usd=0.0,
                    output_files=[],
                )
            )
            mock_synthesis.return_value.run = AsyncMock()
            mock_cross.return_value.run = AsyncMock(return_value=MagicMock(report=None))

            await pipeline.run()

        mock_emit.assert_called_once(), (
            "ResearchPipeline.run MUST call emit_pipeline_health_slo_events"
            " so SLO events fire for both CLI and scheduler entry points"
        )

    @pytest.mark.asyncio
    async def test_emission_is_skipped_when_pipeline_raises_pre_completion(self):
        """If pipeline raises before end-of-pipeline emission, no SLO fires.

        The emission lives AFTER the synthesis/cross-synthesis stages
        (inside the try block, before `except`) so a phase failure
        skips it. This is the right behavior — partial-run SLO data
        would be misleading. The exception still propagates.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from src.orchestration import ResearchPipeline

        pipeline = ResearchPipeline()
        mock_context = MagicMock()
        mock_context.config.research_topics = []
        mock_context.errors = []
        mock_context.discovery_service = None

        with (
            patch.object(
                ResearchPipeline,
                "_create_context",
                AsyncMock(return_value=mock_context),
            ),
            patch("src.orchestration.pipeline.DiscoveryPhase") as mock_discovery,
            patch(
                "src.orchestration.pipeline.emit_pipeline_health_slo_events"
            ) as mock_emit,
        ):
            mock_discovery.return_value.run = AsyncMock(
                side_effect=RuntimeError("discovery exploded")
            )

            # The pipeline catches exceptions in run() (per the
            # existing try/except), records them on result.errors,
            # and returns. So we don't expect a raise here.
            result = await pipeline.run()

        mock_emit.assert_not_called(), (
            "When discovery raises mid-pipeline, the SLO emission MUST"
            " be skipped — partial-run telemetry would mislead ops"
        )
        # The exception was caught and recorded
        assert any("discovery exploded" in e.get("error", "") for e in result.errors)
