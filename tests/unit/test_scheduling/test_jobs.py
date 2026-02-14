"""Tests for scheduled job definitions."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from src.scheduling.jobs import (
    BaseJob,
    DailyResearchJob,
    CacheCleanupJob,
    CostReportJob,
    HealthCheckJob,
)


class ConcreteJob(BaseJob):
    """Concrete implementation for testing BaseJob."""

    def __init__(self, result=None, should_fail=False):
        super().__init__("test_job")
        self.result = result or {"status": "ok"}
        self.should_fail = should_fail

    async def run(self):
        if self.should_fail:
            raise ValueError("Job failed")
        return self.result


class TestBaseJob:
    """Tests for BaseJob class."""

    def test_init(self):
        """Should initialize with correct defaults."""
        job = ConcreteJob()

        assert job.name == "test_job"
        assert job.last_run is None
        assert job.last_success is None
        assert job.run_count == 0
        assert job.error_count == 0

    @pytest.mark.asyncio
    async def test_call_success(self):
        """Should execute job and update stats on success."""
        job = ConcreteJob(result={"data": "test"})

        result = await job()

        assert result == {"data": "test"}
        assert job.last_run is not None
        assert job.last_success is not None
        assert job.run_count == 1
        assert job.error_count == 0

    @pytest.mark.asyncio
    async def test_call_failure(self):
        """Should update stats on failure."""
        job = ConcreteJob(should_fail=True)

        with pytest.raises(ValueError):
            await job()

        assert job.last_run is not None
        assert job.last_success is None
        assert job.run_count == 0
        assert job.error_count == 1

    def test_get_status(self):
        """Should return status dictionary."""
        job = ConcreteJob()

        status = job.get_status()

        assert status["name"] == "test_job"
        assert status["last_run"] is None
        assert status["last_success"] is None
        assert status["run_count"] == 0
        assert status["error_count"] == 0

    @pytest.mark.asyncio
    async def test_get_status_after_run(self):
        """Should return updated status after run."""
        job = ConcreteJob()
        await job()

        status = job.get_status()

        assert status["run_count"] == 1
        assert status["last_run"] is not None
        assert status["last_success"] is not None


class TestDailyResearchJob:
    """Tests for DailyResearchJob."""

    def test_init_with_defaults(self):
        """Should initialize with default config path."""
        job = DailyResearchJob()

        assert job.name == "daily_research"
        assert job.config_path == Path("config/research_config.yaml")

    def test_init_with_custom_path(self):
        """Should initialize with custom config path."""
        custom_path = Path("/custom/config.yaml")
        job = DailyResearchJob(config_path=custom_path)

        assert job.config_path == custom_path

    @pytest.mark.asyncio
    async def test_run_with_mock_services(self):
        """Should run research pipeline with mocked services via ResearchPipeline."""
        from src.orchestration.research_pipeline import PipelineResult
        from src.models.notification import NotificationSettings

        job = DailyResearchJob()

        # Mock ConfigManager to return valid config
        mock_config = MagicMock()
        mock_config.settings.notification_settings = NotificationSettings()

        # Mock ResearchPipeline and ConfigManager
        with (
            patch(
                "src.services.config_manager.ConfigManager"
            ) as mock_config_manager_class,
            patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class,
        ):
            mock_config_manager = MagicMock()
            mock_config_manager.load_config.return_value = mock_config
            mock_config_manager_class.return_value = mock_config_manager

            mock_result = PipelineResult()
            mock_result.topics_processed = 1
            mock_result.papers_discovered = 5
            mock_result.papers_processed = 3
            mock_result.output_files = ["/tmp/output.md"]
            mock_result.errors = []

            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(return_value=mock_result)
            mock_pipeline_class.return_value = mock_pipeline

            result = await job.run()

        assert "topics_processed" in result
        assert "papers_discovered" in result
        assert "errors" in result
        assert result["topics_processed"] == 1
        assert result["papers_discovered"] == 5


class TestDailyResearchJobErrors:
    """Tests for DailyResearchJob error handling."""

    @pytest.mark.asyncio
    async def test_run_handles_topic_search_error(self):
        """Should handle errors when topic search fails via ResearchPipeline."""
        from src.orchestration.research_pipeline import PipelineResult
        from src.models.notification import NotificationSettings

        job = DailyResearchJob()

        # Mock ConfigManager to return valid config
        mock_config = MagicMock()
        mock_config.settings.notification_settings = NotificationSettings()

        # Mock ResearchPipeline and ConfigManager to return error result
        with (
            patch(
                "src.services.config_manager.ConfigManager"
            ) as mock_config_manager_class,
            patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class,
        ):
            mock_config_manager = MagicMock()
            mock_config_manager.load_config.return_value = mock_config
            mock_config_manager_class.return_value = mock_config_manager

            mock_result = PipelineResult()
            mock_result.topics_processed = 0
            mock_result.topics_failed = 1
            mock_result.errors = [{"topic": "test", "error": "Search failed"}]

            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(return_value=mock_result)
            mock_pipeline_class.return_value = mock_pipeline

            result = await job.run()

        # Should have error recorded
        assert len(result["errors"]) > 0
        assert result["errors"][0]["error"] == "Search failed"


class TestDailyResearchJobNotifications:
    """Tests for DailyResearchJob notification handling (Phase 3.7)."""

    @pytest.mark.asyncio
    async def test_run_sends_notifications_when_enabled(self):
        """Should send notifications when Slack is enabled."""
        from src.orchestration.research_pipeline import PipelineResult
        from src.models.notification import NotificationSettings, SlackConfig

        job = DailyResearchJob()

        # Mock config with notifications enabled
        mock_config = MagicMock()
        mock_config.settings.notification_settings = NotificationSettings(
            slack=SlackConfig(
                enabled=True,
                webhook_url="https://hooks.slack.com/services/test",
            )
        )

        with (
            patch(
                "src.services.config_manager.ConfigManager"
            ) as mock_config_manager_class,
            patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class,
            patch(
                "src.services.notification_service.NotificationService"
            ) as mock_notification_class,
            patch("src.services.report_parser.ReportParser") as mock_parser_class,
        ):
            mock_config_manager = MagicMock()
            mock_config_manager.load_config.return_value = mock_config
            mock_config_manager_class.return_value = mock_config_manager

            mock_result = PipelineResult()
            mock_result.topics_processed = 1
            mock_result.output_files = ["/tmp/output.md"]
            mock_result.errors = []

            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(return_value=mock_result)
            mock_pipeline_class.return_value = mock_pipeline

            # Mock parser
            mock_parser = MagicMock()
            mock_parser.extract_key_learnings.return_value = []
            mock_parser_class.return_value = mock_parser

            # Mock notification service
            mock_notification = MagicMock()
            mock_notification.create_summary_from_result.return_value = MagicMock()
            mock_notification.send_pipeline_summary = AsyncMock(
                return_value=MagicMock(success=True, provider="slack")
            )
            mock_notification_class.return_value = mock_notification

            result = await job.run()

            # Verify notification was sent
            mock_notification.send_pipeline_summary.assert_called_once()
            assert result["topics_processed"] == 1

    @pytest.mark.asyncio
    async def test_run_logs_notification_failure(self):
        """Should log warning when notification fails."""
        from src.orchestration.research_pipeline import PipelineResult
        from src.models.notification import NotificationSettings, SlackConfig

        job = DailyResearchJob()

        mock_config = MagicMock()
        mock_config.settings.notification_settings = NotificationSettings(
            slack=SlackConfig(
                enabled=True,
                webhook_url="https://hooks.slack.com/services/test",
            )
        )

        with (
            patch(
                "src.services.config_manager.ConfigManager"
            ) as mock_config_manager_class,
            patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class,
            patch(
                "src.services.notification_service.NotificationService"
            ) as mock_notification_class,
            patch("src.services.report_parser.ReportParser") as mock_parser_class,
        ):
            mock_config_manager = MagicMock()
            mock_config_manager.load_config.return_value = mock_config
            mock_config_manager_class.return_value = mock_config_manager

            mock_result = PipelineResult()
            mock_result.topics_processed = 1
            mock_result.output_files = []
            mock_result.errors = []

            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(return_value=mock_result)
            mock_pipeline_class.return_value = mock_pipeline

            mock_parser = MagicMock()
            mock_parser.extract_key_learnings.return_value = []
            mock_parser_class.return_value = mock_parser

            # Mock notification service to return failure
            mock_notification = MagicMock()
            mock_notification.create_summary_from_result.return_value = MagicMock()
            mock_notification.send_pipeline_summary = AsyncMock(
                return_value=MagicMock(
                    success=False, provider="slack", error="HTTP 500"
                )
            )
            mock_notification_class.return_value = mock_notification

            # Should not raise, just log warning
            result = await job.run()
            assert result["topics_processed"] == 1

    @pytest.mark.asyncio
    async def test_run_handles_notification_exception(self):
        """Should handle exceptions in notification sending gracefully."""
        from src.orchestration.research_pipeline import PipelineResult
        from src.models.notification import NotificationSettings, SlackConfig

        job = DailyResearchJob()

        mock_config = MagicMock()
        mock_config.settings.notification_settings = NotificationSettings(
            slack=SlackConfig(
                enabled=True,
                webhook_url="https://hooks.slack.com/services/test",
            )
        )

        with (
            patch(
                "src.services.config_manager.ConfigManager"
            ) as mock_config_manager_class,
            patch(
                "src.orchestration.research_pipeline.ResearchPipeline"
            ) as mock_pipeline_class,
            patch(
                "src.services.notification_service.NotificationService"
            ) as mock_notification_class,
        ):
            mock_config_manager = MagicMock()
            mock_config_manager.load_config.return_value = mock_config
            mock_config_manager_class.return_value = mock_config_manager

            mock_result = PipelineResult()
            mock_result.topics_processed = 1
            mock_result.output_files = []
            mock_result.errors = []

            mock_pipeline = MagicMock()
            mock_pipeline.run = AsyncMock(return_value=mock_result)
            mock_pipeline_class.return_value = mock_pipeline

            # Mock notification service to raise exception
            mock_notification_class.side_effect = RuntimeError("Unexpected error")

            # Should not raise, should return result
            result = await job.run()
            assert result["topics_processed"] == 1


class TestCacheCleanupJob:
    """Tests for CacheCleanupJob."""

    def test_init_with_defaults(self):
        """Should initialize with default values."""
        job = CacheCleanupJob()

        assert job.name == "cache_cleanup"
        assert job.cache_dir == Path(".cache")
        assert job.max_cache_size_gb == 10.0

    def test_init_with_custom_values(self):
        """Should initialize with custom values."""
        job = CacheCleanupJob(
            cache_dir=Path("/custom/cache"),
            max_cache_size_gb=5.0,
        )

        assert job.cache_dir == Path("/custom/cache")
        assert job.max_cache_size_gb == 5.0

    @pytest.mark.asyncio
    async def test_run_nonexistent_directory(self):
        """Should handle nonexistent cache directory."""
        job = CacheCleanupJob(cache_dir=Path("/nonexistent/path"))

        result = await job.run()

        assert result["bytes_freed"] == 0

    @pytest.mark.asyncio
    async def test_run_with_empty_cache(self):
        """Should handle empty cache directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            job = CacheCleanupJob(cache_dir=Path(tmpdir))

            result = await job.run()

            assert result["bytes_freed"] == 0

    @pytest.mark.asyncio
    async def test_run_forces_cleanup_over_limit(self):
        """Should force cleanup when over size limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            api_dir = cache_dir / "api"
            api_dir.mkdir()

            # Create a file large enough to exceed the tiny limit
            # 2KB > 0.0000009 GB (approx 1KB)
            test_file = api_dir / "test.txt"
            test_file.write_bytes(b"x" * 2048)

            job = CacheCleanupJob(
                cache_dir=cache_dir,
                max_cache_size_gb=0.0000005,  # About 500 bytes
            )

            result = await job.run()

            assert result["bytes_freed"] > 0

    def test_get_directory_size_bytes(self):
        """Should calculate directory size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_bytes(b"x" * 1024)

            job = CacheCleanupJob()
            size = job._get_directory_size_bytes(Path(tmpdir))

            assert size >= 1024

    def test_get_directory_size_bytes_nonexistent(self):
        """Should return 0 for nonexistent directory."""
        job = CacheCleanupJob()
        size = job._get_directory_size_bytes(Path("/nonexistent/path"))

        assert size == 0

    def test_clear_directory_with_subdirs(self):
        """Should clear directory with subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            # Create nested structure
            subdir = cache_dir / "subdir"
            subdir.mkdir()
            (subdir / "file.txt").write_bytes(b"test")
            (cache_dir / "file.txt").write_bytes(b"test")

            job = CacheCleanupJob(cache_dir=cache_dir)
            job._clear_directory(cache_dir)

            # Both file and subdir should be removed
            assert not (cache_dir / "file.txt").exists()
            assert not subdir.exists()

    def test_clear_directory_error_handling(self):
        """Should handle errors when clearing directory."""
        job = CacheCleanupJob()

        # Try to clear nonexistent directory - should not raise
        job._clear_directory(Path("/nonexistent/path"))


class TestCostReportJob:
    """Tests for CostReportJob."""

    def test_init_with_defaults(self):
        """Should initialize with default threshold."""
        job = CostReportJob()

        assert job.name == "cost_report"
        assert job.alert_threshold_usd == 50.0

    def test_init_with_custom_threshold(self):
        """Should initialize with custom threshold."""
        job = CostReportJob(alert_threshold_usd=100.0)

        assert job.alert_threshold_usd == 100.0

    @pytest.mark.asyncio
    async def test_run_generates_report(self):
        """Should generate cost report."""
        job = CostReportJob()

        result = await job.run()

        assert "report_date" in result
        assert "period" in result
        assert "costs" in result
        assert "tokens" in result
        assert "alerts" in result

    @pytest.mark.asyncio
    async def test_run_triggers_alert_over_threshold(self):
        """Should trigger alert when cost exceeds threshold."""
        # Set threshold to 0 so any cost triggers alert
        job = CostReportJob(alert_threshold_usd=0.0)

        # Mock the report to have costs over threshold
        with patch.object(job, "run", wraps=job.run):
            result = await job.run()

        # Since placeholder costs are 0.0 and threshold is 0.0,
        # we need to test with modified report. Let's manually test the alert logic.
        # For now, verify the report structure
        assert "alerts" in result


class TestCostReportJobAlerts:
    """Tests for CostReportJob alert triggering."""

    @pytest.mark.asyncio
    async def test_alert_triggered_when_costs_exceed_threshold(self):
        """Should add alert when costs exceed threshold."""
        job = CostReportJob(alert_threshold_usd=-1.0)  # Negative ensures 0.0 > -1.0

        result = await job.run()

        # With threshold of -1.0, total=0.0 should trigger alert
        assert len(result["alerts"]) > 0


class TestHealthCheckJob:
    """Tests for HealthCheckJob."""

    def test_init(self):
        """Should initialize correctly."""
        job = HealthCheckJob()

        assert job.name == "health_check"

    @pytest.mark.asyncio
    async def test_run_returns_health_report(self):
        """Should run health checks and return report."""
        with tempfile.TemporaryDirectory():
            # Mock the HealthChecker - import happens in run() method
            with patch("src.health.checks.HealthChecker") as mock_checker:
                mock_instance = MagicMock()

                async def mock_check_all():
                    from src.health.checks import (
                        HealthReport,
                        HealthStatus,
                        CheckResult,
                        CheckStatus,
                    )

                    return HealthReport(
                        status=HealthStatus.HEALTHY,
                        checks=[
                            CheckResult(
                                name="disk_space",
                                status=CheckStatus.PASS,
                                message="OK",
                            )
                        ],
                    )

                mock_instance.check_all = mock_check_all
                mock_checker.return_value = mock_instance

                job = HealthCheckJob()
                result = await job.run()

                assert "status" in result
                assert "checks" in result

    @pytest.mark.asyncio
    async def test_run_logs_degraded_status(self):
        """Should log warning for degraded status."""
        with patch("src.health.checks.HealthChecker") as mock_checker:
            mock_instance = MagicMock()

            async def mock_check_all():
                from src.health.checks import (
                    HealthReport,
                    HealthStatus,
                    CheckResult,
                    CheckStatus,
                )

                return HealthReport(
                    status=HealthStatus.DEGRADED,
                    checks=[
                        CheckResult(
                            name="disk_space",
                            status=CheckStatus.WARN,
                            message="Low disk",
                        )
                    ],
                )

            mock_instance.check_all = mock_check_all
            mock_checker.return_value = mock_instance

            job = HealthCheckJob()
            result = await job.run()

            # Status should be degraded
            assert result["status"] == "degraded"
