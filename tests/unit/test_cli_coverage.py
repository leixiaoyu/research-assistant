"""Tests for CLI coverage."""

import pytest
from typer.testing import CliRunner
from unittest.mock import Mock, patch, AsyncMock

from src.cli import app
from src.services.config_manager import ConfigValidationError
from src.orchestration.research_pipeline import PipelineResult

runner = CliRunner()


class TestCLICoverage:
    def test_run_config_error(self):
        """Test config loading error"""
        with patch("src.cli.utils.ConfigManager") as mock_cm:
            mock_cm.return_value.load_config.side_effect = ConfigValidationError(
                "Invalid config"
            )

            result = runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "Configuration Error" in result.stdout

    def test_run_dry_run_phase2(self):
        """Test dry run with Phase 2 enabled"""
        with patch("src.cli.utils.ConfigManager") as mock_cm:
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
        with patch("src.cli.utils.ConfigManager") as mock_cm:
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
        with patch("src.cli.utils.ConfigManager", side_effect=Exception("Unexpected")):
            result = runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "Error" in result.stdout

    def test_process_topics_no_papers(self):
        """Test processing with no papers found - via ResearchPipeline"""
        with patch("src.cli.utils.ConfigManager") as mock_cm:
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
        with patch("src.cli.utils.ConfigManager") as mock_cm:
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
        """Test catalog history without topic (missing argument)"""
        result = runner.invoke(app, ["catalog", "history"])
        # Now uses positional argument, should show missing argument error
        assert result.exit_code == 2
        assert "Missing argument" in result.output

    def test_catalog_history_topic_not_found(self):
        """Test catalog history with unknown topic"""
        # Patch ConfigManager to return empty catalog
        with patch("src.cli.catalog.ConfigManager") as mock_cm:
            mock_cm.return_value.load_catalog.return_value.topics = {}
            # Use positional argument (new API)
            result = runner.invoke(app, ["catalog", "history", "unknown"])
            assert "Topic 'unknown' not found" in result.stdout


class TestSchedulerExceptionHandling:
    """Tests for scheduler command exception handling."""

    def test_scheduler_keyboard_interrupt(self):
        """Test scheduler graceful shutdown on KeyboardInterrupt."""
        with patch("src.cli.schedule.asyncio.run", side_effect=KeyboardInterrupt()):
            # Use "schedule start" (new sub-app command)
            result = runner.invoke(app, ["schedule", "start"])
            # KeyboardInterrupt causes graceful exit
            assert result.exit_code == 0
            assert "Scheduler stopped" in result.stdout

    def test_scheduler_general_exception(self):
        """Test scheduler error handling on general exception."""
        with patch(
            "src.cli.schedule.asyncio.run",
            side_effect=RuntimeError("Connection failed"),
        ):
            # Use "schedule start" (new sub-app command)
            result = runner.invoke(app, ["schedule", "start"])
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
                # Error now displayed by generic handle_errors decorator
                assert "Error" in result.stdout


class TestDryRunPhase1:
    """Tests for dry-run with Phase 1 (Phase 2 disabled)."""

    def test_dry_run_phase1_only(self):
        """Test dry run with Phase 2 features disabled."""
        with patch("src.cli.utils.ConfigManager") as mock_cm:
            mock_config = Mock()
            # Phase 2 NOT configured - None values
            mock_config.settings.pdf_settings = None
            mock_config.settings.llm_settings = None
            mock_config.settings.cost_limits = None
            mock_config.settings.semantic_scholar_api_key = "key"

            mock_config.research_topics = [
                Mock(query="topic1", timeframe=Mock(type="recent"))
            ]

            mock_cm.return_value.load_config.return_value = mock_config

            result = runner.invoke(app, ["run", "--dry-run"])
            assert result.exit_code == 0
            assert "Phase 2 Features: Disabled" in result.stdout


class TestNoSynthesisFlag:
    """Tests for --no-synthesis flag."""

    def test_run_with_no_synthesis_flag(self):
        """Test run with --no-synthesis flag shows disabled message."""
        with patch("src.cli.utils.ConfigManager") as mock_cm:
            mock_config = Mock()
            mock_config.settings.pdf_settings = Mock(keep_pdfs=True)
            mock_config.settings.llm_settings = Mock(provider="gemini")
            mock_config.settings.cost_limits = Mock()
            mock_config.settings.semantic_scholar_api_key = "key"

            topic = Mock(query="topic1", extraction_targets=[])
            topic.timeframe.value = "7d"
            mock_config.research_topics = [topic]

            mock_cm.return_value.load_config.return_value = mock_config

            with patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class:
                mock_result = PipelineResult()
                mock_result.topics_processed = 1
                mock_result.papers_discovered = 5
                mock_result.papers_processed = 3
                mock_result.papers_with_extraction = 0
                mock_result.total_tokens_used = 0
                mock_result.total_cost_usd = 0
                mock_result.output_files = []
                mock_result.errors = []

                mock_pipeline = Mock()
                mock_pipeline.run = AsyncMock(return_value=mock_result)
                mock_pipeline_class.return_value = mock_pipeline

                result = runner.invoke(app, ["run", "--no-synthesis"])
                assert result.exit_code == 0
                assert "synthesis disabled" in result.stdout


class TestValidateCommand:
    """Tests for validate command."""

    def test_validate_success(self):
        """Test validate command with valid config."""
        # Patch where ConfigManager is used (validate.py imports directly)
        with patch("src.cli.validate.ConfigManager") as mock_cm:
            mock_cm.return_value.load_config.return_value = Mock()

            result = runner.invoke(app, ["validate", "config/test.yaml"])
            assert result.exit_code == 0
            assert "valid" in result.stdout

    def test_validate_failure(self):
        """Test validate command with invalid config."""
        with patch("src.cli.validate.ConfigManager") as mock_cm:
            mock_cm.return_value.load_config.side_effect = ConfigValidationError(
                "Invalid YAML"
            )

            result = runner.invoke(app, ["validate", "config/bad.yaml"])
            assert result.exit_code == 1
            assert "Validation failed" in result.stdout


class TestCatalogShow:
    """Tests for catalog show action."""

    def test_catalog_show_with_topics(self):
        """Test catalog show displays all topics."""
        # Patch where ConfigManager is used (catalog.py imports directly)
        with patch("src.cli.catalog.ConfigManager") as mock_cm:
            mock_topic = Mock()
            mock_topic.query = "test query"
            mock_topic.runs = [Mock(), Mock()]

            mock_catalog = Mock()
            mock_catalog.topics = {"test-topic": mock_topic}
            mock_cm.return_value.load_catalog.return_value = mock_catalog

            result = runner.invoke(app, ["catalog", "show"])
            assert "1 topics" in result.stdout
            assert "test-topic" in result.stdout
            assert "2 runs" in result.stdout


class TestCatalogHistoryWithTopic:
    """Tests for catalog history with valid topic."""

    def test_catalog_history_valid_topic(self):
        """Test catalog history with existing topic."""
        # Patch where ConfigManager is used (catalog.py imports directly)
        with patch("src.cli.catalog.ConfigManager") as mock_cm:
            mock_run = Mock()
            mock_run.date = "2025-01-01"
            mock_run.papers_found = 10
            mock_run.output_file = "/output/test.md"

            mock_topic = Mock()
            mock_topic.query = "test query"
            mock_topic.runs = [mock_run]

            mock_catalog = Mock()
            mock_catalog.topics = {"test-topic": mock_topic}
            mock_cm.return_value.load_catalog.return_value = mock_catalog

            # Use positional argument (new API)
            result = runner.invoke(app, ["catalog", "history", "test-topic"])
            assert "History for test query" in result.stdout
            assert "Found 10 papers" in result.stdout


class TestSynthesizeQuestionReturnsNone:
    """Tests for synthesize when question lookup returns None after initial check."""

    def test_synthesize_question_returns_none_on_second_lookup(self):
        """Test synthesize handles None from second get_question_by_id call."""
        with patch("src.services.registry_service.RegistryService"):
            with patch(
                "src.services.cross_synthesis_service.CrossTopicSynthesisService"
            ) as mock_service:
                # First call returns question (validation passes)
                # Second call in run_synthesis returns None
                mock_question = Mock(id="test-q", enabled=True)
                mock_service.return_value.get_enabled_questions.return_value = [
                    mock_question
                ]
                mock_service.return_value.get_question_by_id.side_effect = [
                    mock_question,  # First call - validation
                    None,  # Second call - in run_synthesis
                ]

                result = runner.invoke(app, ["synthesize", "--question", "test-q"])

                # Should handle None gracefully
                assert "No synthesis results" in result.stdout


class TestSendNotifications:
    """Tests for _send_notifications function in CLI."""

    import pytest

    @pytest.mark.asyncio
    async def test_notification_settings_not_configured(self):
        """Test notification skipped when settings attribute missing."""
        from src.cli.run import _send_notifications

        # Mock result
        mock_result = Mock()
        mock_result.output_files = []
        mock_result.to_dict.return_value = {}

        # Mock config without notification_settings attribute
        mock_config = Mock(spec=["settings"])
        mock_config.settings = Mock(spec=[])  # No notification_settings attr

        # Should return without error
        await _send_notifications(mock_result, mock_config, True)

    @pytest.mark.asyncio
    async def test_notification_settings_none(self):
        """Test notification skipped when settings is None."""
        from src.cli.run import _send_notifications

        mock_result = Mock()
        mock_result.output_files = []
        mock_result.to_dict.return_value = {}

        mock_config = Mock()
        mock_config.settings.notification_settings = None

        await _send_notifications(mock_result, mock_config, True)

    @pytest.mark.asyncio
    async def test_slack_notifications_disabled(self):
        """Test notification skipped when Slack is disabled."""
        from src.cli.run import _send_notifications

        mock_result = Mock()
        mock_result.output_files = []
        mock_result.to_dict.return_value = {}

        mock_config = Mock()
        mock_config.settings.notification_settings.slack.enabled = False

        await _send_notifications(mock_result, mock_config, True)

    @pytest.mark.asyncio
    async def test_notification_success(self):
        """Test successful notification sends and logs success."""
        from src.cli.run import _send_notifications
        from src.models.notification import NotificationResult

        mock_result = Mock()
        mock_result.output_files = ["output/test.md"]
        mock_result.to_dict.return_value = {
            "topics_processed": 5,
            "papers_discovered": 100,
        }

        mock_config = Mock()
        mock_config.settings.notification_settings.slack.enabled = True
        mock_config.settings.notification_settings.slack.include_key_learnings = False

        with patch("src.services.notification_service.NotificationService") as mock_svc:
            with patch("src.services.report_parser.ReportParser"):
                mock_svc.return_value.create_summary_from_result.return_value = Mock()
                mock_svc.return_value.send_pipeline_summary = AsyncMock(
                    return_value=NotificationResult(
                        success=True, provider="slack", response_status=200
                    )
                )

                await _send_notifications(mock_result, mock_config, True)

                mock_svc.return_value.send_pipeline_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_notification_failure(self):
        """Test failed notification logs warning."""
        from src.cli.run import _send_notifications
        from src.models.notification import NotificationResult

        mock_result = Mock()
        mock_result.output_files = []
        mock_result.to_dict.return_value = {}

        mock_config = Mock()
        mock_config.settings.notification_settings.slack.enabled = True
        mock_config.settings.notification_settings.slack.include_key_learnings = False

        with patch("src.services.notification_service.NotificationService") as mock_svc:
            with patch("src.services.report_parser.ReportParser"):
                mock_svc.return_value.create_summary_from_result.return_value = Mock()
                mock_svc.return_value.send_pipeline_summary = AsyncMock(
                    return_value=NotificationResult(
                        success=False, provider="slack", error="Webhook error"
                    )
                )

                await _send_notifications(mock_result, mock_config, True)

    @pytest.mark.asyncio
    async def test_notification_exception(self):
        """Test exception during notification is caught and logged."""
        from src.cli.run import _send_notifications

        mock_result = Mock()
        mock_result.output_files = []
        mock_result.to_dict.return_value = {}

        mock_config = Mock()
        mock_config.settings.notification_settings.slack.enabled = True
        mock_config.settings.notification_settings.slack.include_key_learnings = False

        with patch("src.services.notification_service.NotificationService") as mock_svc:
            with patch("src.services.report_parser.ReportParser"):
                mock_svc.return_value.create_summary_from_result.side_effect = (
                    RuntimeError("Unexpected error")
                )

                # Should not raise - notifications are fail-safe
                await _send_notifications(mock_result, mock_config, True)

    @pytest.mark.asyncio
    async def test_notification_with_key_learnings(self):
        """Test notification extracts key learnings when enabled."""
        from src.cli.run import _send_notifications
        from src.models.notification import NotificationResult

        mock_result = Mock()
        mock_result.output_files = ["output/topic1/Knowledge_Base.md"]
        mock_result.to_dict.return_value = {}

        mock_config = Mock()
        mock_config.settings.notification_settings.slack.enabled = True
        mock_config.settings.notification_settings.slack.include_key_learnings = True
        mock_config.settings.notification_settings.slack.max_learnings_per_topic = 2

        with patch("src.services.notification_service.NotificationService") as mock_svc:
            with patch("src.services.report_parser.ReportParser") as mock_parser:
                mock_parser.return_value.extract_key_learnings.return_value = []
                mock_svc.return_value.create_summary_from_result.return_value = Mock()
                mock_svc.return_value.send_pipeline_summary = AsyncMock(
                    return_value=NotificationResult(success=True, provider="slack")
                )

                await _send_notifications(mock_result, mock_config, True)

                mock_parser.return_value.extract_key_learnings.assert_called_once()


class TestHealthCommand:
    """Tests for health command coverage."""

    def test_health_command(self):
        """Test health command starts server."""
        # Patch at the source where the import happens
        with patch("src.health.server.run_health_server") as mock_server:
            result = runner.invoke(app, ["health"])
            assert result.exit_code == 0
            mock_server.assert_called_once_with(host="localhost", port=8000)

    def test_health_command_custom_host_port(self):
        """Test health command with custom host and port."""
        with patch("src.health.server.run_health_server") as mock_server:
            result = runner.invoke(
                app, ["health", "--host", "0.0.0.0", "--port", "9000"]
            )
            assert result.exit_code == 0
            mock_server.assert_called_once_with(host="0.0.0.0", port=9000)


class TestCatalogLegacyCommand:
    """Tests for legacy catalog command coverage."""

    def test_catalog_legacy_show(self):
        """Test legacy catalog show action."""
        with patch("src.cli.catalog.ConfigManager") as mock_cm:
            mock_catalog = Mock()
            mock_catalog.topics = {"test-topic": Mock(query="Test", runs=[])}
            mock_cm.return_value.load_catalog.return_value = mock_catalog

            result = runner.invoke(app, ["catalog-legacy", "show"])
            assert result.exit_code == 0
            assert "1 topics" in result.stdout

    def test_catalog_legacy_history_no_topic(self):
        """Test legacy catalog history without topic option."""
        with patch("src.cli.catalog.ConfigManager") as mock_cm:
            mock_cm.return_value.load_catalog.return_value = Mock(topics={})
            result = runner.invoke(app, ["catalog-legacy", "history"])
            assert "Please provide --topic" in result.stdout

    def test_catalog_legacy_history_topic_not_found(self):
        """Test legacy catalog history with unknown topic."""
        with patch("src.cli.catalog.ConfigManager") as mock_cm:
            mock_cm.return_value.load_catalog.return_value = Mock(topics={})
            result = runner.invoke(
                app, ["catalog-legacy", "history", "--topic", "unknown"]
            )
            assert "Topic 'unknown' not found" in result.stdout

    def test_catalog_legacy_history_success(self):
        """Test legacy catalog history with valid topic."""
        with patch("src.cli.catalog.ConfigManager") as mock_cm:
            mock_run = Mock(date="2025-01-01", papers_found=10, output_file="test.md")
            mock_topic = Mock(query="Test Query", runs=[mock_run])
            mock_catalog = Mock(topics={"test-topic": mock_topic})
            mock_cm.return_value.load_catalog.return_value = mock_catalog

            result = runner.invoke(
                app, ["catalog-legacy", "history", "--topic", "test-topic"]
            )
            assert "History for Test Query" in result.stdout
            assert "Found 10 papers" in result.stdout


class TestScheduleLegacyCommand:
    """Tests for legacy schedule command coverage."""

    def test_schedule_legacy_invokes_start(self):
        """Test legacy schedule command invokes schedule_start."""
        with patch("src.cli.schedule.asyncio.run", side_effect=KeyboardInterrupt()):
            result = runner.invoke(app, ["schedule-legacy"])
            # KeyboardInterrupt causes graceful exit
            assert result.exit_code == 0
            assert "Scheduler stopped" in result.stdout


class TestScheduleValidation:
    """Tests for schedule command input validation."""

    def test_invalid_hour_too_high(self):
        """Test that hour > 23 is rejected."""
        result = runner.invoke(app, ["schedule", "start", "--hour", "24"])
        assert result.exit_code == 2
        assert "Hour must be between 0 and 23" in result.output

    def test_invalid_hour_negative(self):
        """Test that negative hour is rejected."""
        result = runner.invoke(app, ["schedule", "start", "--hour", "-1"])
        assert result.exit_code == 2
        assert "Hour must be between 0 and 23" in result.output

    def test_invalid_minute_too_high(self):
        """Test that minute > 59 is rejected."""
        result = runner.invoke(app, ["schedule", "start", "--minute", "60"])
        assert result.exit_code == 2
        assert "Minute must be between 0 and 59" in result.output

    def test_invalid_minute_negative(self):
        """Test that negative minute is rejected."""
        result = runner.invoke(app, ["schedule", "start", "--minute", "-1"])
        assert result.exit_code == 2
        assert "Minute must be between 0 and 59" in result.output


class TestScheduleRunSchedulerCoverage:
    """Tests for _run_scheduler function coverage."""

    @pytest.mark.asyncio
    async def test_run_scheduler_full_flow(self):
        """Test _run_scheduler with all jobs enabled."""
        from src.cli.schedule import _run_scheduler
        from pathlib import Path

        with (
            patch("src.scheduling.ResearchScheduler") as mock_scheduler_cls,
            patch("src.scheduling.DailyResearchJob") as mock_daily_job,
            patch("src.scheduling.CacheCleanupJob") as mock_cleanup_job,
            patch("src.scheduling.CostReportJob") as mock_cost_job,
            patch("src.health.server.run_health_server_async") as mock_health,
        ):
            # Setup mocks
            mock_scheduler = mock_scheduler_cls.return_value
            mock_scheduler.get_jobs.return_value = [
                {"id": "daily_research", "next_run_time": "06:00"},
                {"id": "cache_cleanup", "next_run_time": "10:00"},
                {"id": "cost_report", "next_run_time": "23:00"},
            ]
            mock_scheduler.start = AsyncMock()
            mock_health.return_value = AsyncMock()()

            # Run the scheduler (will complete immediately due to mocking)
            await _run_scheduler(
                config_path=Path("config/research_config.yaml"),
                hour=6,
                minute=0,
                health_port=8000,
                enable_cleanup=True,
                enable_cost_report=True,
            )

            # Verify jobs were created
            mock_daily_job.assert_called_once()
            mock_cleanup_job.assert_called_once()
            mock_cost_job.assert_called_once()
            assert mock_scheduler.add_job.call_count == 3

    @pytest.mark.asyncio
    async def test_run_scheduler_minimal_jobs(self):
        """Test _run_scheduler with cleanup and cost report disabled."""
        from src.cli.schedule import _run_scheduler
        from pathlib import Path

        with (
            patch("src.scheduling.ResearchScheduler") as mock_scheduler_cls,
            patch("src.scheduling.DailyResearchJob") as mock_daily_job,
            patch("src.scheduling.CacheCleanupJob") as mock_cleanup_job,
            patch("src.scheduling.CostReportJob") as mock_cost_job,
            patch("src.health.server.run_health_server_async") as mock_health,
        ):
            # Setup mocks
            mock_scheduler = mock_scheduler_cls.return_value
            mock_scheduler.get_jobs.return_value = [
                {"id": "daily_research", "next_run_time": "08:30"},
            ]
            mock_scheduler.start = AsyncMock()
            mock_health.return_value = AsyncMock()()

            # Run the scheduler with optional jobs disabled
            await _run_scheduler(
                config_path=Path("config/research_config.yaml"),
                hour=8,
                minute=30,
                health_port=9000,
                enable_cleanup=False,
                enable_cost_report=False,
            )

            # Verify only daily job was created
            mock_daily_job.assert_called_once()
            mock_cleanup_job.assert_not_called()
            mock_cost_job.assert_not_called()
            assert mock_scheduler.add_job.call_count == 1
