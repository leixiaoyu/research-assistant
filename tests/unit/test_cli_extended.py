"""Extended CLI tests using mocked ResearchPipeline."""

import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock, patch, AsyncMock

from src.cli import app
from src.orchestration.research_pipeline import PipelineResult

runner = CliRunner()


@pytest.fixture
def mock_pipeline_result():
    """Create a mock PipelineResult for testing."""
    result = PipelineResult()
    result.topics_processed = 1
    result.papers_discovered = 3
    result.papers_processed = 3
    result.papers_with_extraction = 0
    result.total_tokens_used = 0
    result.total_cost_usd = 0.0
    result.output_files = ["/tmp/output.md"]
    result.errors = []
    return result


@pytest.fixture
def mock_components(mock_pipeline_result):
    """Mock ConfigManager and ResearchPipeline for CLI tests."""
    with (
        patch("src.cli.ConfigManager") as MockConfig,
        patch("src.orchestration.research_pipeline.ResearchPipeline") as MockPipeline,
    ):
        # Setup Config
        config_instance = MockConfig.return_value
        config = MagicMock()
        topic = MagicMock()
        topic.query = "Test Query"
        topic.timeframe.value = "48h"
        topic.extraction_targets = None  # No Phase 2 extraction
        config.research_topics = [topic]
        config.settings.semantic_scholar_api_key = "key"
        # Disable Phase 2 by setting Phase 2 settings to None
        config.settings.pdf_settings = None
        config.settings.llm_settings = None
        config.settings.cost_limits = None
        config_instance.load_config.return_value = config

        # Setup Pipeline
        pipeline_instance = MockPipeline.return_value
        pipeline_instance.run = AsyncMock(return_value=mock_pipeline_result)

        yield {
            "config": config_instance,
            "pipeline": pipeline_instance,
            "pipeline_class": MockPipeline,
            "result": mock_pipeline_result,
        }


def test_run_full_flow(mock_components):
    """Test successful run flow."""
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0
    assert "Pipeline completed" in result.stdout

    # Check pipeline was called
    mock_components["pipeline"].run.assert_called_once()


def test_run_discovery_no_papers(mock_components):
    """Test run when no papers are found."""
    # Modify the result to show no papers
    mock_components["result"].papers_discovered = 0
    mock_components["result"].papers_processed = 0
    mock_components["result"].output_files = []

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0


def test_run_discovery_error(mock_components):
    """Test run when discovery fails."""
    # Modify result to show failure
    mock_components["result"].topics_processed = 0
    mock_components["result"].topics_failed = 1
    mock_components["result"].papers_discovered = 0
    mock_components["result"].papers_processed = 0
    mock_components["result"].output_files = []
    mock_components["result"].errors = [{"topic": "test", "error": "API Fail"}]

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0  # Should continue gracefully
    assert "Errors" in result.stdout


def test_run_unexpected_error(mock_components):
    """Test run when pipeline raises exception."""
    # Make pipeline raise exception
    mock_components["pipeline"].run.side_effect = Exception("Boom")

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "Pipeline failed" in result.stdout
