"""Tests for PipelinePhase base class."""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from src.orchestration.phases.base import PipelinePhase
from src.orchestration.context import PipelineContext


@dataclass
class MockResult:
    """Mock result for testing."""

    success: bool = False
    value: int = 0


class ConcretePipelinePhase(PipelinePhase[MockResult]):
    """Concrete implementation for testing."""

    @property
    def name(self) -> str:
        return "test_phase"

    async def execute(self) -> MockResult:
        return MockResult(success=True, value=42)

    def _get_default_result(self) -> MockResult:
        return MockResult()


class DisabledPipelinePhase(PipelinePhase[MockResult]):
    """Disabled phase for testing."""

    @property
    def name(self) -> str:
        return "disabled_phase"

    def is_enabled(self) -> bool:
        return False

    async def execute(self) -> MockResult:
        return MockResult(success=True, value=100)

    def _get_default_result(self) -> MockResult:
        return MockResult(success=False, value=-1)


@pytest.fixture
def mock_context():
    """Create mock pipeline context."""
    context = MagicMock(spec=PipelineContext)
    context.config = MagicMock()
    context.config.research_topics = []
    return context


class TestPipelinePhase:
    """Tests for PipelinePhase base class."""

    def test_init_sets_context(self, mock_context):
        """Test that init sets context."""
        phase = ConcretePipelinePhase(mock_context)
        assert phase.context is mock_context

    def test_name_property(self, mock_context):
        """Test name property returns correct value."""
        phase = ConcretePipelinePhase(mock_context)
        assert phase.name == "test_phase"

    def test_is_enabled_default_true(self, mock_context):
        """Test is_enabled defaults to True."""
        phase = ConcretePipelinePhase(mock_context)
        assert phase.is_enabled() is True

    def test_is_enabled_can_be_overridden(self, mock_context):
        """Test is_enabled can be overridden."""
        phase = DisabledPipelinePhase(mock_context)
        assert phase.is_enabled() is False

    @pytest.mark.asyncio
    async def test_run_executes_when_enabled(self, mock_context):
        """Test run executes phase when enabled."""
        phase = ConcretePipelinePhase(mock_context)
        result = await phase.run()
        assert result.success is True
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_run_returns_default_when_disabled(self, mock_context):
        """Test run returns default result when disabled."""
        phase = DisabledPipelinePhase(mock_context)
        result = await phase.run()
        assert result.success is False
        assert result.value == -1

    def test_logger_property(self, mock_context):
        """Test logger property returns structlog logger."""
        phase = ConcretePipelinePhase(mock_context)
        assert phase.logger is not None

    @pytest.mark.asyncio
    async def test_run_logs_phase_start(self, mock_context):
        """Test run logs phase start."""
        phase = ConcretePipelinePhase(mock_context)
        with patch.object(phase, "logger") as mock_logger:
            await phase.run()
            mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_run_logs_skip_when_disabled(self, mock_context):
        """Test run logs skip when disabled."""
        phase = DisabledPipelinePhase(mock_context)
        with patch.object(phase, "logger") as mock_logger:
            await phase.run()
            # Should log that phase was skipped
            assert mock_logger.info.called

    @pytest.mark.asyncio
    async def test_run_handles_exception(self, mock_context):
        """Test run handles exceptions and adds error to context."""
        mock_context.add_error = MagicMock()

        class FailingPhase(PipelinePhase[MockResult]):
            @property
            def name(self) -> str:
                return "failing_phase"

            async def execute(self) -> MockResult:
                raise ValueError("Test error")

        phase = FailingPhase(mock_context)

        with pytest.raises(ValueError, match="Test error"):
            await phase.run()

        # Verify error was added to context
        mock_context.add_error.assert_called_once_with("failing_phase", "Test error")

    @pytest.mark.asyncio
    async def test_run_logs_exception(self, mock_context):
        """Test run logs exception when execute fails."""
        mock_context.add_error = MagicMock()

        class FailingPhase(PipelinePhase[MockResult]):
            @property
            def name(self) -> str:
                return "failing_phase"

            async def execute(self) -> MockResult:
                raise RuntimeError("Execution failed")

        phase = FailingPhase(mock_context)

        with patch.object(phase, "logger") as mock_logger:
            with pytest.raises(RuntimeError):
                await phase.run()
            # Should log the exception
            mock_logger.exception.assert_called_once()

    def test_get_default_result_base_returns_none(self, mock_context):
        """Test base _get_default_result returns None."""

        # Create a phase that doesn't override _get_default_result
        class MinimalPhase(PipelinePhase[MockResult]):
            @property
            def name(self) -> str:
                return "minimal_phase"

            async def execute(self) -> MockResult:
                return MockResult()

        phase = MinimalPhase(mock_context)
        result = phase._get_default_result()
        assert result is None
