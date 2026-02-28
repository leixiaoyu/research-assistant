"""Tests for PipelineContext."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path
from datetime import datetime

from src.orchestration.context import PipelineContext
from src.models.config import ResearchConfig, GlobalSettings
from src.models.synthesis import ProcessingResult, ProcessingStatus


@pytest.fixture
def mock_config():
    """Create mock research config."""
    config = MagicMock(spec=ResearchConfig)
    config.settings = MagicMock(spec=GlobalSettings)
    config.settings.output_base_dir = "./output"
    config.research_topics = []
    return config


@pytest.fixture
def sample_context(mock_config):
    """Create sample pipeline context."""
    return PipelineContext(
        config=mock_config,
        config_path=Path("config/research_config.yaml"),
    )


@pytest.fixture
def sample_papers():
    """Create sample paper metadata (mocked)."""
    paper1 = MagicMock()
    paper1.paper_id = "paper1"
    paper1.title = "Test Paper 1"
    return [paper1]


class TestPipelineContext:
    """Tests for PipelineContext."""

    def test_init_required_fields(self, mock_config):
        """Test initialization with required fields."""
        context = PipelineContext(
            config=mock_config,
            config_path=Path("config/test.yaml"),
        )
        assert context.config == mock_config
        assert context.config_path == Path("config/test.yaml")

    def test_init_default_values(self, sample_context):
        """Test default values are set."""
        assert sample_context.enable_phase2 is True
        assert sample_context.enable_synthesis is True
        assert sample_context.enable_cross_synthesis is True
        assert sample_context.discovered_papers == {}
        assert sample_context.extraction_results == {}
        assert sample_context.topic_processing_results == {}
        assert sample_context.errors == []

    def test_init_run_id_generated(self, sample_context):
        """Test run_id is auto-generated."""
        assert sample_context.run_id is not None
        assert len(sample_context.run_id) > 0

    def test_init_started_at_set(self, sample_context):
        """Test started_at is set to current time."""
        assert sample_context.started_at is not None
        assert isinstance(sample_context.started_at, datetime)

    def test_init_custom_flags(self, mock_config):
        """Test initialization with custom flags."""
        context = PipelineContext(
            config=mock_config,
            config_path=Path("config/test.yaml"),
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=False,
        )
        assert context.enable_phase2 is False
        assert context.enable_synthesis is False
        assert context.enable_cross_synthesis is False

    def test_add_discovered_papers(self, sample_context, sample_papers):
        """Test add_discovered_papers."""
        sample_context.add_discovered_papers("test-topic", sample_papers)
        assert "test-topic" in sample_context.discovered_papers
        assert sample_context.discovered_papers["test-topic"] == sample_papers

    def test_add_discovered_papers_overwrites(self, sample_context, sample_papers):
        """Test add_discovered_papers overwrites existing."""
        sample_context.add_discovered_papers("test-topic", sample_papers)
        new_papers = [MagicMock()]
        sample_context.add_discovered_papers("test-topic", new_papers)
        assert sample_context.discovered_papers["test-topic"] == new_papers

    def test_add_extraction_results(self, sample_context):
        """Test add_extraction_results."""
        results = [MagicMock()]
        sample_context.add_extraction_results("test-topic", results)
        assert "test-topic" in sample_context.extraction_results
        assert sample_context.extraction_results["test-topic"] == results

    def test_add_processing_results(self, sample_context):
        """Test add_processing_results."""
        results = [
            ProcessingResult(
                paper_id="paper1",
                title="Test",
                status=ProcessingStatus.NEW,
                topic_slug="test-topic",
            )
        ]
        sample_context.add_processing_results("test-topic", results)
        assert "test-topic" in sample_context.topic_processing_results
        assert sample_context.topic_processing_results["test-topic"] == results

    def test_add_error(self, sample_context):
        """Test add_error."""
        sample_context.add_error("discovery", "Test error")
        assert len(sample_context.errors) == 1
        assert sample_context.errors[0]["phase"] == "discovery"
        assert sample_context.errors[0]["error"] == "Test error"

    def test_add_error_with_topic(self, sample_context):
        """Test add_error with topic."""
        sample_context.add_error("extraction", "Test error", topic="test-topic")
        assert len(sample_context.errors) == 1
        assert sample_context.errors[0]["topic"] == "test-topic"

    def test_add_error_multiple(self, sample_context):
        """Test adding multiple errors."""
        sample_context.add_error("discovery", "Error 1")
        sample_context.add_error("extraction", "Error 2")
        assert len(sample_context.errors) == 2

    def test_get_output_path_with_config_manager(self, sample_context):
        """Test get_output_path with config_manager."""
        mock_manager = MagicMock()
        mock_manager.get_output_path.return_value = Path("/output/test-topic")
        sample_context.config_manager = mock_manager

        path = sample_context.get_output_path("test-topic")

        assert path == Path("/output/test-topic")
        mock_manager.get_output_path.assert_called_once_with("test-topic")

    def test_get_output_path_without_config_manager(self, sample_context):
        """Test get_output_path without config_manager."""
        sample_context.config_manager = None
        sample_context.config.settings.output_base_dir = "./output"

        path = sample_context.get_output_path("test-topic")

        assert path == Path("./output/test-topic")

    def test_services_default_none(self, sample_context):
        """Test services default to None."""
        assert sample_context.config_manager is None
        assert sample_context.discovery_service is None
        assert sample_context.catalog_service is None
        assert sample_context.extraction_service is None
        assert sample_context.registry_service is None
        assert sample_context.synthesis_engine is None
        assert sample_context.delta_generator is None
        assert sample_context.cross_synthesis_service is None
        assert sample_context.cross_synthesis_generator is None
        assert sample_context.md_generator is None
