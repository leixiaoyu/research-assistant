"""Tests for ExtractionPhase."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.orchestration.phases.extraction import (
    ExtractionPhase,
    ExtractionResult,
    TopicExtractionResult,
)
from src.orchestration.context import PipelineContext


@pytest.fixture
def mock_context():
    """Create mock pipeline context."""
    context = MagicMock(spec=PipelineContext)
    context.config = MagicMock()
    context.config.research_topics = []
    context.enable_phase2 = True
    context.enable_synthesis = True
    context.extraction_service = AsyncMock()
    context.catalog_service = MagicMock()
    context.config_manager = MagicMock()
    context.md_generator = MagicMock()
    context.discovered_papers = {}
    context.errors = []
    context.add_error = MagicMock()
    context.add_processing_results = MagicMock()
    return context


@pytest.fixture
def sample_topic():
    """Create a sample research topic (mocked)."""
    topic = MagicMock()
    topic.query = "machine learning"
    topic.extraction_targets = [MagicMock(), MagicMock()]
    return topic


@pytest.fixture
def sample_papers():
    """Create sample paper metadata (mocked)."""
    paper1 = MagicMock()
    paper1.paper_id = "paper1"
    paper1.title = "Test Paper 1"
    return [paper1]


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_default_values(self):
        """Test default values."""
        result = ExtractionResult()
        assert result.topics_processed == 0
        assert result.topics_failed == 0
        assert result.total_papers_processed == 0
        assert result.total_papers_with_extraction == 0
        assert result.total_tokens_used == 0
        assert result.total_cost_usd == 0.0
        assert result.output_files == []
        assert result.topic_results == []


class TestTopicExtractionResult:
    """Tests for TopicExtractionResult dataclass."""

    def test_default_values(self, sample_topic):
        """Test default values."""
        result = TopicExtractionResult(
            topic=sample_topic,
            topic_slug="machine-learning",
        )
        assert result.papers_discovered == 0
        assert result.papers_processed == 0
        assert result.success is False


class TestExtractionPhase:
    """Tests for ExtractionPhase."""

    def test_name_property(self, mock_context):
        """Test name property."""
        phase = ExtractionPhase(mock_context)
        assert phase.name == "extraction"

    def test_is_enabled_true_when_phase2(self, mock_context):
        """Test is_enabled returns True when phase2 enabled."""
        mock_context.enable_phase2 = True
        phase = ExtractionPhase(mock_context)
        assert phase.is_enabled() is True

    def test_is_enabled_false_when_no_phase2(self, mock_context):
        """Test is_enabled returns False when phase2 disabled."""
        mock_context.enable_phase2 = False
        phase = ExtractionPhase(mock_context)
        assert phase.is_enabled() is False

    @pytest.mark.asyncio
    async def test_execute_no_topics(self, mock_context):
        """Test execute with no topics."""
        mock_context.config.research_topics = []
        phase = ExtractionPhase(mock_context)
        result = await phase.execute()
        assert result.topics_processed == 0

    @pytest.mark.asyncio
    async def test_execute_skips_topic_without_papers(self, mock_context, sample_topic):
        """Test execute skips topics without discovered papers."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovered_papers = {}
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        phase = ExtractionPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 0
        assert len(result.topic_results) == 0

    @pytest.mark.asyncio
    async def test_execute_processes_discovered_papers(
        self, mock_context, sample_topic, sample_papers, tmp_path
    ):
        """Test execute processes discovered papers."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovered_papers = {"machine-learning": sample_papers}
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )
        # process_papers is async, so use AsyncMock
        mock_context.extraction_service = MagicMock()
        mock_context.extraction_service.process_papers = AsyncMock(return_value=[])
        mock_context.extraction_service.get_extraction_summary.return_value = {
            "papers_with_extraction": 1,
            "total_tokens_used": 100,
            "total_cost_usd": 0.01,
        }

        # Setup output path
        output_dir = tmp_path / "output" / "machine-learning"
        output_dir.mkdir(parents=True)
        mock_context.config_manager.get_output_path.return_value = output_dir
        mock_context.md_generator.generate.return_value = "# Test"
        mock_context.enable_phase2 = False  # Use basic generator

        phase = ExtractionPhase(mock_context)
        result = await phase.execute()

        assert result.topics_processed == 1
        assert len(result.output_files) == 1

    @pytest.mark.asyncio
    async def test_execute_handles_extraction_error(
        self, mock_context, sample_topic, sample_papers
    ):
        """Test execute handles extraction errors."""
        mock_context.config.research_topics = [sample_topic]
        mock_context.discovered_papers = {"machine-learning": sample_papers}
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )
        mock_context.extraction_service.process_papers.side_effect = Exception(
            "Extraction failed"
        )

        phase = ExtractionPhase(mock_context)
        result = await phase.execute()

        assert result.topics_failed == 1
        mock_context.add_error.assert_called_once()

    def test_get_default_result(self, mock_context):
        """Test _get_default_result."""
        phase = ExtractionPhase(mock_context)
        result = phase._get_default_result()
        assert isinstance(result, ExtractionResult)
        assert result.topics_processed == 0

    @pytest.mark.asyncio
    async def test_run_returns_default_when_disabled(self, mock_context):
        """Test run returns default result when disabled."""
        mock_context.enable_phase2 = False
        phase = ExtractionPhase(mock_context)
        result = await phase.run()
        assert isinstance(result, ExtractionResult)

    @pytest.mark.asyncio
    async def test_execute_uses_enhanced_generator_with_phase2(
        self, mock_context, sample_topic, sample_papers, tmp_path
    ):
        """Test execute uses EnhancedMarkdownGenerator when Phase 2 enabled."""
        from src.output.enhanced_generator import EnhancedMarkdownGenerator

        mock_context.config.research_topics = [sample_topic]
        mock_context.discovered_papers = {"machine-learning": sample_papers}
        mock_context.catalog_service.get_or_create_topic.return_value = MagicMock(
            topic_slug="machine-learning"
        )

        # Mock extraction service
        mock_context.extraction_service = MagicMock()
        mock_extracted_paper = MagicMock()
        mock_extracted_paper.metadata = sample_papers[0]
        mock_extracted_paper.extraction = MagicMock()
        mock_context.extraction_service.process_papers = AsyncMock(
            return_value=[mock_extracted_paper]
        )
        mock_context.extraction_service.get_extraction_summary.return_value = {
            "papers_with_extraction": 1,
            "total_tokens_used": 100,
            "total_cost_usd": 0.01,
        }
        mock_context.extraction_service.get_processing_results.return_value = []

        # Setup output path
        output_dir = tmp_path / "output" / "machine-learning"
        output_dir.mkdir(parents=True)
        mock_context.config_manager.get_output_path.return_value = output_dir

        # Mock enhanced generator
        mock_enhanced_gen = MagicMock(spec=EnhancedMarkdownGenerator)
        mock_enhanced_gen.generate_enhanced.return_value = "# Enhanced Test"
        mock_context.md_generator = mock_enhanced_gen
        mock_context.enable_phase2 = True

        phase = ExtractionPhase(mock_context)
        result = await phase.execute()

        # Verify enhanced generator was called
        mock_enhanced_gen.generate_enhanced.assert_called_once()
        assert result.topics_processed == 1

    @pytest.mark.asyncio
    async def test_get_processing_results_from_extraction_service(
        self, mock_context, sample_topic, sample_papers
    ):
        """Test _get_processing_results returns results from extraction service."""
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        mock_context.config.research_topics = [sample_topic]
        mock_context.discovered_papers = {"machine-learning": sample_papers}

        # Create mock processing results
        mock_result = ProcessingResult(
            paper_id="paper1",
            title="Test Paper",
            status=ProcessingStatus.NEW,
            topic_slug="machine-learning",
        )
        mock_context.extraction_service = MagicMock()
        mock_context.extraction_service.get_processing_results.return_value = [
            mock_result
        ]

        phase = ExtractionPhase(mock_context)
        results = phase._get_processing_results(sample_papers, "machine-learning", None)

        assert len(results) == 1
        assert results[0].paper_id == "paper1"

    @pytest.mark.asyncio
    async def test_get_processing_results_fallback_with_extracted_papers(
        self, mock_context, sample_papers
    ):
        """Test _get_processing_results creates results from extracted papers."""
        # No extraction service
        mock_context.extraction_service = None

        # Create mock extracted paper
        mock_extracted = MagicMock()
        mock_extracted.metadata = MagicMock()
        mock_extracted.metadata.paper_id = "paper1"
        mock_extracted.metadata.title = "Test Paper"
        mock_extracted.extraction = MagicMock()
        mock_extracted.extraction.quality_score = 0.85
        mock_extracted.pdf_available = True

        phase = ExtractionPhase(mock_context)
        results = phase._get_processing_results(
            sample_papers, "machine-learning", [mock_extracted]
        )

        assert len(results) == 1
        assert results[0].paper_id == "paper1"
        assert results[0].quality_score == 0.85
        assert results[0].pdf_available is True
