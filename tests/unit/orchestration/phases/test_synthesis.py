"""Tests for SynthesisPhase."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path

from src.orchestration.phases.synthesis import (
    SynthesisPhase,
    SynthesisResult,
    TopicSynthesisResult,
)
from src.orchestration.context import PipelineContext
from src.models.synthesis import ProcessingResult, ProcessingStatus


@pytest.fixture
def mock_context():
    """Create mock pipeline context."""
    context = MagicMock(spec=PipelineContext)
    context.enable_synthesis = True
    context.synthesis_engine = MagicMock()
    context.delta_generator = MagicMock()
    context.topic_processing_results = {}
    context.errors = []
    context.add_error = MagicMock()
    return context


@pytest.fixture
def sample_processing_results():
    """Create sample processing results."""
    return [
        ProcessingResult(
            paper_id="paper1",
            title="Test Paper 1",
            status=ProcessingStatus.NEW,
            quality_score=0.8,
            topic_slug="test-topic",
        ),
    ]


class TestSynthesisResult:
    """Tests for SynthesisResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = SynthesisResult()
        assert result.topics_processed == 0
        assert result.topics_failed == 0
        assert result.topic_results == []


class TestTopicSynthesisResult:
    """Tests for TopicSynthesisResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = TopicSynthesisResult(topic_slug="test-topic")
        assert result.delta_path is None
        assert result.kb_total_papers == 0
        assert result.success is False


class TestSynthesisPhase:
    """Tests for SynthesisPhase."""

    def test_name_property(self, mock_context):
        """Test name property."""
        phase = SynthesisPhase(mock_context)
        assert phase.name == "synthesis"

    def test_is_enabled_true_when_synthesis_enabled(self, mock_context):
        """Test is_enabled returns True when synthesis enabled."""
        mock_context.enable_synthesis = True
        phase = SynthesisPhase(mock_context)
        assert phase.is_enabled() is True

    def test_is_enabled_false_when_synthesis_disabled(self, mock_context):
        """Test is_enabled returns False when synthesis disabled."""
        mock_context.enable_synthesis = False
        phase = SynthesisPhase(mock_context)
        assert phase.is_enabled() is False

    @pytest.mark.asyncio
    async def test_execute_skips_without_services(self, mock_context):
        """Test execute skips when services not initialized."""
        mock_context.synthesis_engine = None
        mock_context.delta_generator = None
        phase = SynthesisPhase(mock_context)
        result = await phase.execute()
        assert result.topics_processed == 0

    @pytest.mark.asyncio
    async def test_execute_no_topics(self, mock_context):
        """Test execute with no topics to process."""
        mock_context.topic_processing_results = {}
        phase = SynthesisPhase(mock_context)
        result = await phase.execute()
        assert result.topics_processed == 0

    @pytest.mark.asyncio
    async def test_execute_single_topic_success(
        self, mock_context, sample_processing_results
    ):
        """Test execute with single successful topic."""
        mock_context.topic_processing_results = {
            "test-topic": sample_processing_results
        }
        mock_context.delta_generator.generate.return_value = Path("/output/delta.md")
        mock_context.synthesis_engine.synthesize.return_value = MagicMock(
            total_papers=1,
            average_quality=0.8,
            synthesis_duration_ms=100.0,
        )

        phase = SynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.topics_failed == 0
        assert len(result.topic_results) == 1
        assert result.topic_results[0].success is True

    @pytest.mark.asyncio
    async def test_execute_handles_synthesis_error(
        self, mock_context, sample_processing_results
    ):
        """Test execute handles synthesis errors."""
        mock_context.topic_processing_results = {
            "test-topic": sample_processing_results
        }
        mock_context.delta_generator.generate.side_effect = Exception("Delta failed")

        phase = SynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        mock_context.add_error.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_multiple_topics(
        self, mock_context, sample_processing_results
    ):
        """Test execute with multiple topics."""
        mock_context.topic_processing_results = {
            "topic1": sample_processing_results,
            "topic2": sample_processing_results,
        }
        mock_context.delta_generator.generate.return_value = Path("/output/delta.md")
        mock_context.synthesis_engine.synthesize.return_value = MagicMock(
            total_papers=1,
            average_quality=0.8,
            synthesis_duration_ms=100.0,
        )

        phase = SynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 2
        assert len(result.topic_results) == 2

    def test_get_default_result(self, mock_context):
        """Test _get_default_result."""
        phase = SynthesisPhase(mock_context)
        result = phase._get_default_result()
        assert isinstance(result, SynthesisResult)

    @pytest.mark.asyncio
    async def test_run_returns_default_when_disabled(self, mock_context):
        """Test run returns default result when disabled."""
        mock_context.enable_synthesis = False
        phase = SynthesisPhase(mock_context)
        result = await phase.run()
        assert isinstance(result, SynthesisResult)

    @pytest.mark.asyncio
    async def test_delta_path_none_still_succeeds(
        self, mock_context, sample_processing_results
    ):
        """Test synthesis succeeds even if delta_path is None."""
        mock_context.topic_processing_results = {
            "test-topic": sample_processing_results
        }
        mock_context.delta_generator.generate.return_value = None
        mock_context.synthesis_engine.synthesize.return_value = MagicMock(
            total_papers=1,
            average_quality=0.8,
            synthesis_duration_ms=100.0,
        )

        phase = SynthesisPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.topic_results[0].delta_path is None
        assert result.topic_results[0].success is True
