"""Tests for CrossSynthesisPhase."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from src.orchestration.phases.cross_synthesis import (
    CrossSynthesisPhase,
    CrossSynthesisResult,
)
from src.orchestration.context import PipelineContext


@pytest.fixture
def mock_context():
    """Create mock pipeline context."""
    context = MagicMock(spec=PipelineContext)
    context.enable_cross_synthesis = True
    context.cross_synthesis_service = AsyncMock()
    context.cross_synthesis_generator = MagicMock()
    context.errors = []
    context.add_error = MagicMock()
    return context


@pytest.fixture
def sample_report():
    """Create sample cross-synthesis report (mock)."""
    report = MagicMock()
    report.questions_answered = 3
    report.total_cost_usd = 0.05
    report.total_tokens_used = 500
    report.results = [MagicMock()]
    return report


class TestCrossSynthesisResult:
    """Tests for CrossSynthesisResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = CrossSynthesisResult()
        assert result.report is None
        assert result.output_path is None
        assert result.questions_answered == 0
        assert result.total_cost_usd == 0.0
        assert result.total_tokens_used == 0
        assert result.success is False
        assert result.error is None


class TestCrossSynthesisPhase:
    """Tests for CrossSynthesisPhase."""

    def test_name_property(self, mock_context):
        """Test name property."""
        phase = CrossSynthesisPhase(mock_context)
        assert phase.name == "cross_synthesis"

    def test_is_enabled_true_when_enabled(self, mock_context):
        """Test is_enabled returns True when cross_synthesis enabled."""
        mock_context.enable_cross_synthesis = True
        phase = CrossSynthesisPhase(mock_context)
        assert phase.is_enabled() is True

    def test_is_enabled_false_when_disabled(self, mock_context):
        """Test is_enabled returns False when cross_synthesis disabled."""
        mock_context.enable_cross_synthesis = False
        phase = CrossSynthesisPhase(mock_context)
        assert phase.is_enabled() is False

    @pytest.mark.asyncio
    async def test_execute_skips_without_services(self, mock_context):
        """Test execute skips when services not initialized."""
        mock_context.cross_synthesis_service = None
        mock_context.cross_synthesis_generator = None
        phase = CrossSynthesisPhase(mock_context)
        result = await phase.execute()
        assert result.success is False
        assert result.report is None

    @pytest.mark.asyncio
    async def test_execute_skips_no_enabled_questions(self, mock_context):
        """Test execute skips when no enabled questions."""
        # get_enabled_questions is sync, not async
        mock_context.cross_synthesis_service = MagicMock()
        mock_context.cross_synthesis_service.get_enabled_questions.return_value = []
        phase = CrossSynthesisPhase(mock_context)
        result = await phase.execute()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_context, sample_report):
        """Test successful cross-synthesis execution."""
        # Mix sync and async mocks appropriately
        mock_context.cross_synthesis_service = MagicMock()
        mock_context.cross_synthesis_service.get_enabled_questions.return_value = [
            MagicMock()
        ]
        mock_context.cross_synthesis_service.synthesize_all = AsyncMock(
            return_value=sample_report
        )
        mock_context.cross_synthesis_generator.write.return_value = Path(
            "/output/synthesis.md"
        )

        phase = CrossSynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.success is True
        assert result.report == sample_report
        assert result.questions_answered == 3
        assert result.output_path == Path("/output/synthesis.md")

    @pytest.mark.asyncio
    async def test_execute_write_failure(self, mock_context, sample_report):
        """Test execute handles write failure."""
        mock_context.cross_synthesis_service = MagicMock()
        mock_context.cross_synthesis_service.get_enabled_questions.return_value = [
            MagicMock()
        ]
        mock_context.cross_synthesis_service.synthesize_all = AsyncMock(
            return_value=sample_report
        )
        mock_context.cross_synthesis_generator.write.return_value = None

        phase = CrossSynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.success is False
        assert result.error == "Failed to write output file"

    @pytest.mark.asyncio
    async def test_execute_no_results(self, mock_context):
        """Test execute when synthesis returns no results."""
        mock_context.cross_synthesis_service = MagicMock()
        mock_context.cross_synthesis_service.get_enabled_questions.return_value = [
            MagicMock()
        ]
        empty_report = MagicMock()
        empty_report.questions_answered = 0
        empty_report.total_cost_usd = 0.0
        empty_report.total_tokens_used = 0
        empty_report.results = []
        mock_context.cross_synthesis_service.synthesize_all = AsyncMock(
            return_value=empty_report
        )

        phase = CrossSynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.success is True
        assert result.questions_answered == 0

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self, mock_context):
        """Test execute handles exceptions."""
        mock_context.cross_synthesis_service = MagicMock()
        mock_context.cross_synthesis_service.get_enabled_questions.return_value = [
            MagicMock()
        ]
        mock_context.cross_synthesis_service.synthesize_all = AsyncMock(
            side_effect=Exception("Synthesis failed")
        )

        phase = CrossSynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.success is False
        assert result.error == "Synthesis failed"

    def test_get_default_result(self, mock_context):
        """Test _get_default_result."""
        phase = CrossSynthesisPhase(mock_context)
        result = phase._get_default_result()
        assert isinstance(result, CrossSynthesisResult)

    @pytest.mark.asyncio
    async def test_run_returns_default_when_disabled(self, mock_context):
        """Test run returns default result when disabled."""
        mock_context.enable_cross_synthesis = False
        phase = CrossSynthesisPhase(mock_context)
        result = await phase.run()
        assert isinstance(result, CrossSynthesisResult)
