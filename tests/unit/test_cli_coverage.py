"""Tests for CLI coverage."""

from typer.testing import CliRunner
from unittest.mock import Mock, patch, AsyncMock

from src.cli import app
from src.services.config_manager import ConfigValidationError
from src.orchestration.research_pipeline import PipelineResult

runner = CliRunner()


class TestCLICoverage:
    def test_run_config_error(self):
        """Test config loading error"""
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_cm.return_value.load_config.side_effect = ConfigValidationError(
                "Invalid config"
            )

            result = runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "Configuration Error" in result.stdout

    def test_run_dry_run_phase2(self):
        """Test dry run with Phase 2 enabled"""
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_config = Mock()
            # Phase 2 settings present
            mock_config.settings.pdf_settings.keep_pdfs = True
            mock_config.settings.pdf_settings.temp_dir = "/tmp"
            mock_config.settings.pdf_settings.max_file_size_mb = 10
            mock_config.settings.pdf_settings.timeout_seconds = 60

            mock_config.settings.llm_settings.provider = "anthropic"
            mock_config.settings.llm_settings.model = "claude-3-5-sonnet"
            mock_config.settings.llm_settings.api_key = "key"
            mock_config.settings.llm_settings.max_tokens = 1000
            mock_config.settings.llm_settings.temperature = 0.7
            mock_config.settings.llm_settings.timeout = 60

            mock_config.settings.cost_limits.max_daily_spend_usd = 10.0
            mock_config.settings.cost_limits.max_total_spend_usd = 100.0
            mock_config.settings.cost_limits.max_tokens_per_paper = 10000

            mock_config.settings.semantic_scholar_api_key = "key"

            mock_config.research_topics = [
                Mock(query="topic1", timeframe=Mock(type="recent"))
            ]

            mock_cm.return_value.load_config.return_value = mock_config

            result = runner.invoke(app, ["run", "--dry-run"])
            assert result.exit_code == 0
            assert "Phase 2 Features Enabled" in result.stdout

    def test_run_full_phase2(self):
        """Test full Phase 2 run with mocks via ResearchPipeline"""
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_config = Mock()
            # Phase 2 settings present
            mock_config.settings.pdf_settings.keep_pdfs = True
            mock_config.settings.pdf_settings.temp_dir = "/tmp"
            mock_config.settings.pdf_settings.max_file_size_mb = 10
            mock_config.settings.pdf_settings.timeout_seconds = 60

            mock_config.settings.llm_settings.provider = "anthropic"
            mock_config.settings.llm_settings.model = "claude-3-5-sonnet"
            mock_config.settings.llm_settings.api_key = "key"
            mock_config.settings.llm_settings.max_tokens = 1000
            mock_config.settings.llm_settings.temperature = 0.7
            mock_config.settings.llm_settings.timeout = 60

            mock_config.settings.cost_limits.max_daily_spend_usd = 10.0
            mock_config.settings.cost_limits.max_total_spend_usd = 100.0
            mock_config.settings.cost_limits.max_tokens_per_paper = 10000

            mock_config.settings.semantic_scholar_api_key = "key"

            topic = Mock(query="topic1", extraction_targets=[Mock()])
            topic.timeframe.value = "7d"
            mock_config.research_topics = [topic]

            mock_cm.return_value.load_config.return_value = mock_config

            # Mock ResearchPipeline
            with patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class:
                mock_result = PipelineResult()
                mock_result.topics_processed = 1
                mock_result.papers_discovered = 5
                mock_result.papers_processed = 3
                mock_result.papers_with_extraction = 2
                mock_result.total_tokens_used = 1000
                mock_result.total_cost_usd = 0.5
                mock_result.output_files = ["/tmp/output.md"]
                mock_result.errors = []

                mock_pipeline = Mock()
                mock_pipeline.run = AsyncMock(return_value=mock_result)
                mock_pipeline_class.return_value = mock_pipeline

                result = runner.invoke(app, ["run"])
                assert result.exit_code == 0
                assert "Pipeline completed" in result.stdout

    def test_run_exception(self):
        """Test general exception in run"""
        with patch("src.cli.ConfigManager", side_effect=Exception("Unexpected")):
            result = runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "Pipeline failed" in result.stdout

    def test_process_topics_no_papers(self):
        """Test processing with no papers found - via ResearchPipeline"""
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_config = Mock()
            mock_config.settings.pdf_settings = None
            mock_config.settings.llm_settings = None
            mock_config.settings.cost_limits = None
            mock_config.settings.semantic_scholar_api_key = None
            mock_config.research_topics = [Mock(query="topic1")]

            mock_cm.return_value.load_config.return_value = mock_config

            with patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class:
                mock_result = PipelineResult()
                mock_result.topics_processed = 1
                mock_result.papers_discovered = 0
                mock_result.papers_processed = 0
                mock_result.output_files = []
                mock_result.errors = []

                mock_pipeline = Mock()
                mock_pipeline.run = AsyncMock(return_value=mock_result)
                mock_pipeline_class.return_value = mock_pipeline

                result = runner.invoke(app, ["run"])
                assert result.exit_code == 0

    def test_run_with_errors(self):
        """Test run that has errors reported"""
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_config = Mock()
            mock_config.settings.pdf_settings = None
            mock_config.settings.llm_settings = None
            mock_config.settings.cost_limits = None
            mock_config.settings.semantic_scholar_api_key = None
            mock_config.research_topics = [Mock(query="topic1")]

            mock_cm.return_value.load_config.return_value = mock_config

            with patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class:
                mock_result = PipelineResult()
                mock_result.topics_processed = 0
                mock_result.topics_failed = 1
                mock_result.papers_discovered = 0
                mock_result.papers_processed = 0
                mock_result.output_files = []
                mock_result.errors = [{"topic": "test", "error": "Search failed"}]

                mock_pipeline = Mock()
                mock_pipeline.run = AsyncMock(return_value=mock_result)
                mock_pipeline_class.return_value = mock_pipeline

                result = runner.invoke(app, ["run"])
                assert result.exit_code == 0
                assert "Errors" in result.stdout

    def test_catalog_history_no_topic(self):
        """Test catalog history without topic"""
        # Patch ConfigManager to avoid validation error
        with patch("src.cli.ConfigManager"):
            result = runner.invoke(app, ["catalog", "history"])
            assert "Please provide --topic" in result.stdout

    def test_catalog_history_topic_not_found(self):
        """Test catalog history with unknown topic"""
        # Patch ConfigManager to return empty catalog
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_cm.return_value.load_catalog.return_value.topics = {}
            result = runner.invoke(app, ["catalog", "history", "--topic", "unknown"])
            assert "Topic 'unknown' not found" in result.stdout
