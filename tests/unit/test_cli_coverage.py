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


class TestSchedulerExceptionHandling:
    """Tests for scheduler command exception handling."""

    def test_scheduler_keyboard_interrupt(self):
        """Test scheduler graceful shutdown on KeyboardInterrupt."""
        with patch("src.cli.asyncio.run", side_effect=KeyboardInterrupt()):
            result = runner.invoke(app, ["schedule"])
            # KeyboardInterrupt causes graceful exit
            assert result.exit_code == 0
            assert "Scheduler stopped" in result.stdout

    def test_scheduler_general_exception(self):
        """Test scheduler error handling on general exception."""
        with patch(
            "src.cli.asyncio.run", side_effect=RuntimeError("Connection failed")
        ):
            result = runner.invoke(app, ["schedule"])
            assert result.exit_code == 1


class TestSynthesizeCommand:
    """Tests for synthesize CLI command."""

    def test_synthesize_no_enabled_questions(self):
        """Test synthesize when no questions are enabled."""
        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                mock_service.return_value.get_enabled_questions.return_value = []

                result = runner.invoke(app, ["synthesize"])

                assert "No enabled synthesis questions found" in result.stdout

    def test_synthesize_question_not_found(self):
        """Test synthesize with non-existent question."""
        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                mock_service.return_value.get_enabled_questions.return_value = [
                    Mock(id="q1")
                ]
                mock_service.return_value.get_question_by_id.return_value = None

                result = runner.invoke(app, ["synthesize", "--question", "unknown"])

                assert result.exit_code == 1
                assert "not found" in result.stdout

    def test_synthesize_question_disabled(self):
        """Test synthesize with disabled question."""
        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                mock_service.return_value.get_enabled_questions.return_value = [
                    Mock(id="q1")
                ]
                mock_service.return_value.get_question_by_id.return_value = Mock(
                    enabled=False
                )

                result = runner.invoke(app, ["synthesize", "--question", "q1"])

                assert "disabled" in result.stdout

    def test_synthesize_success(self):
        """Test successful synthesis."""
        from src.models.cross_synthesis import (
            CrossTopicSynthesisReport,
            SynthesisResult,
        )
        from pathlib import Path

        mock_result = SynthesisResult(
            question_id="q1",
            question_name="Test Question",
            synthesis_text="Synthesis output",
            papers_used=["p1", "p2"],
            topics_covered=["topic-a"],
            tokens_used=1000,
            cost_usd=0.05,
            model_used="test-model",
            confidence=0.8,
        )

        mock_report = CrossTopicSynthesisReport(
            report_id="test-report",
            total_papers_in_registry=10,
            results=[mock_result],
            total_tokens_used=1000,
            total_cost_usd=0.05,
        )

        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                with patch(
                    "src.output.cross_synthesis_generator.CrossSynthesisGenerator"
                ) as mock_generator:
                    mock_service.return_value.get_enabled_questions.return_value = [
                        Mock(id="q1")
                    ]
                    mock_service.return_value.synthesize_all = AsyncMock(
                        return_value=mock_report
                    )
                    mock_generator.return_value.write.return_value = Path(
                        "/output/test.md"
                    )

                    result = runner.invoke(app, ["synthesize"])

                    assert result.exit_code == 0
                    assert "Synthesis completed" in result.stdout
                    assert "Questions answered: 1" in result.stdout

    def test_synthesize_no_results(self):
        """Test synthesize with no results (incremental skip)."""
        from src.models.cross_synthesis import CrossTopicSynthesisReport

        mock_report = CrossTopicSynthesisReport(
            report_id="test-report",
            total_papers_in_registry=10,
            results=[],
            total_tokens_used=0,
            total_cost_usd=0.0,
        )

        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                with patch(
                    "src.output.cross_synthesis_generator.CrossSynthesisGenerator"
                ):
                    mock_service.return_value.get_enabled_questions.return_value = [
                        Mock(id="q1")
                    ]
                    mock_service.return_value.synthesize_all = AsyncMock(
                        return_value=mock_report
                    )

                    result = runner.invoke(app, ["synthesize"])

                    assert "No synthesis results generated" in result.stdout

    def test_synthesize_single_question(self):
        """Test synthesize with specific question."""
        from src.models.cross_synthesis import SynthesisResult, SynthesisQuestion
        from pathlib import Path

        mock_question = SynthesisQuestion(
            id="test-q",
            name="Test Question",
            prompt="Test prompt {paper_summaries}",
            enabled=True,
        )

        mock_result = SynthesisResult(
            question_id="test-q",
            question_name="Test Question",
            synthesis_text="Result",
            papers_used=["p1"],
            topics_covered=["t1"],
            tokens_used=500,
            cost_usd=0.02,
            model_used="model",
            confidence=0.7,
        )

        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                with patch(
                    "src.output.cross_synthesis_generator.CrossSynthesisGenerator"
                ) as mock_generator:
                    mock_service.return_value.get_enabled_questions.return_value = [
                        mock_question
                    ]
                    mock_service.return_value.get_question_by_id.return_value = (
                        mock_question
                    )
                    mock_service.return_value.get_all_entries.return_value = []
                    mock_service.return_value.config.budget_per_synthesis_usd = 10.0
                    mock_service.return_value.synthesize_question = AsyncMock(
                        return_value=mock_result
                    )
                    mock_generator.return_value.write.return_value = Path("/test.md")

                    result = runner.invoke(app, ["synthesize", "--question", "test-q"])

                    assert result.exit_code == 0
                    assert "Synthesis completed" in result.stdout

    def test_synthesize_force_mode(self):
        """Test synthesize with force flag."""
        from src.models.cross_synthesis import (
            CrossTopicSynthesisReport,
            SynthesisResult,
        )
        from pathlib import Path

        mock_result = SynthesisResult(
            question_id="q1",
            question_name="Question",
            synthesis_text="Output",
            papers_used=["p1"],
            topics_covered=["t1"],
            tokens_used=100,
            cost_usd=0.01,
            model_used="model",
            confidence=0.5,
        )

        mock_report = CrossTopicSynthesisReport(
            report_id="test",
            total_papers_in_registry=5,
            results=[mock_result],
            total_tokens_used=100,
            total_cost_usd=0.01,
        )

        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                with patch(
                    "src.output.cross_synthesis_generator.CrossSynthesisGenerator"
                ) as mock_generator:
                    mock_service.return_value.get_enabled_questions.return_value = [
                        Mock(id="q1")
                    ]
                    mock_service.return_value.synthesize_all = AsyncMock(
                        return_value=mock_report
                    )
                    mock_generator.return_value.write.return_value = Path("/test.md")

                    result = runner.invoke(app, ["synthesize", "--force"])

                    assert result.exit_code == 0
                    assert "Force mode" in result.stdout

    def test_synthesize_exception(self):
        """Test synthesize error handling."""
        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                mock_service.return_value.get_enabled_questions.side_effect = (
                    RuntimeError("Service error")
                )

                result = runner.invoke(app, ["synthesize"])

                assert result.exit_code == 1
                assert "Synthesis failed" in result.stdout
