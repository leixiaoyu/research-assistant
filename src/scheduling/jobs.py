"""Scheduled job definitions for ARISP pipeline.

Provides pre-configured jobs:
- DailyResearchJob: Run research pipeline daily
- CacheCleanupJob: Clean up expired cache entries
- CostReportJob: Generate and log cost reports

Usage:
    from src.scheduling.jobs import DailyResearchJob

    job = DailyResearchJob(config_path=Path("config.yaml"))
    await job.run()
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import structlog

from src.observability.context import set_correlation_id, clear_correlation_id
from src.models.notification import KeyLearning

logger = structlog.get_logger()


class BaseJob(ABC):
    """Base class for scheduled jobs.

    Provides common functionality:
    - Correlation ID management
    - Error handling and logging
    - Execution timing
    """

    def __init__(self, name: str):
        """Initialize job.

        Args:
            name: Job name for logging
        """
        self.name = name
        self.last_run: Optional[datetime] = None
        self.last_success: Optional[datetime] = None
        self.run_count: int = 0
        self.error_count: int = 0

    async def __call__(self) -> Any:
        """Execute the job with correlation ID and error handling."""
        import time

        start = time.time()
        corr_id = set_correlation_id(
            f"{self.name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        )

        logger.info(
            "job_starting",
            job_name=self.name,
            correlation_id=corr_id,
        )

        try:
            result = await self.run()

            self.last_run = datetime.now(timezone.utc)
            self.last_success = datetime.now(timezone.utc)
            self.run_count += 1

            duration = time.time() - start

            logger.info(
                "job_completed",
                job_name=self.name,
                duration_seconds=round(duration, 2),
                correlation_id=corr_id,
            )

            return result

        except Exception as e:
            self.last_run = datetime.now(timezone.utc)
            self.error_count += 1

            logger.error(
                "job_failed",
                job_name=self.name,
                error=str(e),
                correlation_id=corr_id,
                exc_info=True,
            )
            raise

        finally:
            clear_correlation_id()

    @abstractmethod
    async def run(self) -> Any:
        """Execute the job logic.

        Subclasses must implement this method.

        Returns:
            Job result (implementation-specific)
        """
        pass  # pragma: no cover (abstract method)

    def get_status(self) -> Dict[str, Any]:
        """Get job status information.

        Returns:
            Dictionary with job status
        """
        return {
            "name": self.name,
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_success": (
                self.last_success.isoformat() if self.last_success else None
            ),
            "run_count": self.run_count,
            "error_count": self.error_count,
        }


class DailyResearchJob(BaseJob):
    """Daily research pipeline job.

    Runs the complete research pipeline with configured topics,
    including PDF download, LLM extraction, and report generation.

    Uses the shared ResearchPipeline to ensure feature parity with CLI.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        enable_phase2: bool = True,
        enable_dra_refresh: bool = True,
    ):
        """Initialize daily research job.

        Args:
            config_path: Path to research config (default: config/research_config.yaml)
            enable_phase2: Enable Phase 2 PDF/LLM extraction (default: True)
            enable_dra_refresh: Enable DRA corpus refresh after pipeline (Phase 8.5)
        """
        super().__init__("daily_research")
        self.config_path = config_path or Path("config/research_config.yaml")
        self.enable_phase2 = enable_phase2
        self.enable_dra_refresh = enable_dra_refresh

    async def run(self) -> Dict[str, Any]:
        """Run the complete research pipeline.

        Executes the full pipeline:
        1. Discovery - Find papers via Semantic Scholar/ArXiv
        2. Extraction - Download PDFs and extract content via LLM
        3. Report Generation - Generate Obsidian-ready markdown
        4. Catalog Update - Track run history
        5. Notifications - Send Slack notification (Phase 3.7)

        Returns:
            Dictionary with run results including output files
        """
        from src.orchestration import ResearchPipeline
        from src.services.config_manager import ConfigManager

        logger.info(
            "daily_research_starting",
            config_path=str(self.config_path),
            phase2_enabled=self.enable_phase2,
        )

        # Load config for notification settings
        config_manager = ConfigManager(config_path=str(self.config_path))
        config = config_manager.load_config()

        # Use shared ResearchPipeline for full feature parity with CLI
        pipeline = ResearchPipeline(
            config_path=self.config_path,
            enable_phase2=self.enable_phase2,
        )

        # Execute the complete pipeline
        result = await pipeline.run()

        logger.info(
            "daily_research_completed",
            topics_processed=result.topics_processed,
            topics_failed=result.topics_failed,
            papers_discovered=result.papers_discovered,
            papers_processed=result.papers_processed,
            output_files=len(result.output_files),
            total_cost_usd=result.total_cost_usd,
            errors=len(result.errors),
        )

        # Phase 3.7 + 3.8: Send notifications with deduplication (fail-safe)
        await self._send_notifications(result, config, pipeline)

        # Phase 8.5: DRA corpus refresh (fail-safe)
        dra_result = await self._refresh_dra_corpus(config)

        # Include DRA result in response
        result_dict = result.to_dict()
        result_dict["dra_corpus_refresh"] = dra_result
        return result_dict

    async def _send_notifications(
        self,
        result: Any,
        config: Any,
        pipeline: Any = None,
    ) -> None:
        """Send pipeline notifications (Phase 3.7 + 3.8 deduplication).

        Notifications are fail-safe - errors are logged but never raised.

        Args:
            result: PipelineResult from pipeline execution.
            config: ResearchConfig with notification settings.
            pipeline: ResearchPipeline instance for accessing context (Phase 3.8).
        """
        try:
            from src.services.notification_service import NotificationService
            from src.services.notification import NotificationDeduplicator
            from src.services.report_parser import ReportParser
            from src.models.notification import DeduplicationResult

            notification_settings = config.settings.notification_settings

            # Skip if notifications disabled
            if not notification_settings.slack.enabled:
                logger.debug("notifications_disabled")
                return

            # Extract key learnings from output files
            learnings: List[KeyLearning] = []
            if notification_settings.slack.include_key_learnings:
                parser = ReportParser()
                learnings = parser.extract_key_learnings(
                    output_files=result.output_files,
                    max_per_topic=notification_settings.slack.max_learnings_per_topic,
                )

            # Phase 3.8: Deduplication-aware notifications
            dedup_result: Optional[DeduplicationResult] = None
            if pipeline is not None:
                context = pipeline.context
                if context is not None:
                    # Get all discovered papers from context
                    all_papers = []
                    for papers in context.discovered_papers.values():
                        all_papers.extend(papers)

                    # Create deduplicator with registry service
                    registry_service = getattr(context, "registry_service", None)
                    deduplicator = NotificationDeduplicator(registry_service)

                    # Categorize papers
                    if all_papers:
                        dedup_result = deduplicator.categorize_papers(all_papers)
                        logger.info(
                            "notification_dedup_completed",
                            new=dedup_result.new_count,
                            duplicate=dedup_result.duplicate_count,
                            total=dedup_result.total_checked,
                        )

            # Create notification service and send
            service = NotificationService(notification_settings)
            summary = service.create_summary_from_result(
                result=result.to_dict(),
                key_learnings=learnings,
                dedup_result=dedup_result,
            )

            notification_result = await service.send_pipeline_summary(summary)

            if notification_result.success:
                logger.info(
                    "notification_sent",
                    provider=notification_result.provider,
                )
            else:
                logger.warning(
                    "notification_failed",
                    provider=notification_result.provider,
                    error=notification_result.error,
                )

        except Exception as e:
            # Notifications should never break the pipeline
            logger.error(
                "notification_error",
                error=str(e),
                exc_info=True,
            )

    async def _refresh_dra_corpus(self, config: Any) -> Dict[str, Any]:
        """Refresh DRA corpus after pipeline completion (Phase 8.5).

        DRA corpus refresh is fail-safe - errors are logged but never raised.

        Args:
            config: ResearchConfig with DRA settings.

        Returns:
            Dictionary with refresh results or skip reason.
        """
        result: Dict[str, Any] = {
            "status": "skipped",
            "papers_ingested": 0,
            "error": None,
        }

        # Check if DRA refresh is enabled
        if not self.enable_dra_refresh:
            result["error"] = "DRA refresh disabled via constructor"
            logger.debug("dra_corpus_refresh_disabled", reason="constructor_flag")
            return result

        # Check config-level DRA settings
        dra_settings = getattr(config.settings, "dra_daily", None)
        if dra_settings is None:
            result["error"] = "No dra_daily settings in config"
            logger.debug("dra_corpus_refresh_skipped", reason="no_config")
            return result

        if not dra_settings.enable_corpus_refresh:
            result["error"] = "Corpus refresh disabled in config"
            logger.debug("dra_corpus_refresh_disabled", reason="config_flag")
            return result

        try:
            from src.models.dra import CorpusConfig
            from src.services.dra.corpus_manager import CorpusManager

            corpus_data_dir = Path(dra_settings.corpus_data_dir)
            registry_path = Path(dra_settings.registry_path)

            # Check if registry exists
            if not registry_path.exists():
                result["error"] = f"Registry not found: {registry_path}"
                logger.warning(
                    "dra_corpus_refresh_skipped",
                    reason="registry_not_found",
                    path=str(registry_path),
                )
                return result

            logger.info(
                "dra_corpus_refresh_starting",
                corpus_dir=str(corpus_data_dir),
                registry_path=str(registry_path),
                force_reindex=dra_settings.force_reindex,
            )

            # Initialize corpus manager and ingest
            corpus_config = CorpusConfig(corpus_dir=str(corpus_data_dir))
            corpus_manager = CorpusManager(config=corpus_config)
            papers_ingested = corpus_manager.ingest_from_registry(
                registry_path=registry_path,
                force=dra_settings.force_reindex,
            )

            result["status"] = "success"
            result["papers_ingested"] = papers_ingested
            result["corpus_size"] = corpus_manager.stats.total_chunks

            logger.info(
                "dra_corpus_refresh_completed",
                papers_ingested=papers_ingested,
                corpus_size=result.get("corpus_size", 0),
            )

        except Exception as e:
            # DRA refresh should never break the pipeline
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(
                "dra_corpus_refresh_failed",
                error=str(e),
                exc_info=True,
            )

        return result


class CacheCleanupJob(BaseJob):
    """Cache cleanup job.

    Removes expired entries from all cache tiers.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        max_cache_size_gb: float = 10.0,
    ):
        """Initialize cache cleanup job.

        Args:
            cache_dir: Cache directory (default: .cache)
            max_cache_size_gb: Maximum cache size before forced cleanup
        """
        super().__init__("cache_cleanup")
        self.cache_dir = cache_dir or Path(".cache")
        self.max_cache_size_gb = max_cache_size_gb

    async def run(self) -> Dict[str, Any]:
        """Run cache cleanup.

        Returns:
            Dictionary with cleanup results
        """
        results = {
            "api_entries_removed": 0,
            "pdf_entries_removed": 0,
            "extraction_entries_removed": 0,
            "bytes_freed": 0,
        }

        # Check if cache directory exists
        if not self.cache_dir.exists():
            logger.info("cache_cleanup_skipped", reason="directory_not_found")
            return results

        # Get current cache size
        total_size = self._get_directory_size_bytes(self.cache_dir)
        size_gb = total_size / (1024**3)

        logger.info(
            "cache_cleanup_starting",
            cache_size_gb=round(size_gb, 2),
            max_size_gb=self.max_cache_size_gb,
        )

        # If cache is over limit, clear older entries
        if size_gb > self.max_cache_size_gb:
            # Clear API cache (shortest TTL)
            api_cache = self.cache_dir / "api"
            if api_cache.exists():
                api_size = self._get_directory_size_bytes(api_cache)
                self._clear_directory(api_cache)
                results["bytes_freed"] += api_size
                results["api_entries_removed"] = 1  # Placeholder count

            logger.info(
                "cache_cleanup_forced",
                reason="over_size_limit",
                freed_bytes=results["bytes_freed"],
            )

        logger.info(
            "cache_cleanup_completed",
            bytes_freed=results["bytes_freed"],
        )

        return results

    def _get_directory_size_bytes(self, path: Path) -> int:
        """Get directory size in bytes."""
        try:
            return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        except Exception:  # pragma: no cover (defensive code for FS errors)
            return 0

    def _clear_directory(self, path: Path) -> None:
        """Clear directory contents."""
        try:
            for item in path.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    import shutil

                    shutil.rmtree(item)
        except Exception as e:
            logger.error("cache_clear_failed", path=str(path), error=str(e))


class CostReportJob(BaseJob):
    """Cost reporting job.

    Generates and logs LLM usage and cost reports.
    """

    def __init__(
        self,
        alert_threshold_usd: float = 50.0,
    ):
        """Initialize cost report job.

        Args:
            alert_threshold_usd: Cost threshold for alerts
        """
        super().__init__("cost_report")
        self.alert_threshold_usd = alert_threshold_usd

    async def run(self) -> Dict[str, Any]:
        """Generate cost report.

        Returns:
            Dictionary with cost information
        """
        # Note: In production, this would read from a persistent store
        # For now, this is a placeholder that shows the report structure

        report: Dict[str, Any] = {
            "report_date": datetime.now(timezone.utc).isoformat(),
            "period": "daily",
            "costs": {
                "anthropic": 0.0,
                "google": 0.0,
                "total": 0.0,
            },
            "tokens": {
                "input": 0,
                "output": 0,
                "total": 0,
            },
            "papers_processed": 0,
            "alerts": [],
        }

        # In a real implementation, we'd aggregate from metrics or database
        # For now, this is a placeholder that logs the report structure

        logger.info(
            "cost_report_generated",
            total_cost_usd=report["costs"]["total"],
            period=report["period"],
        )

        # Check thresholds
        if report["costs"]["total"] > self.alert_threshold_usd:
            alert_msg = (
                f"Daily cost ${report['costs']['total']:.2f} "
                f"exceeds threshold ${self.alert_threshold_usd:.2f}"
            )
            report["alerts"].append(alert_msg)
            logger.warning("cost_alert", message=alert_msg)

        return report


class HealthCheckJob(BaseJob):
    """Periodic health check job.

    Runs health checks and logs results.
    """

    def __init__(self):
        """Initialize health check job."""
        super().__init__("health_check")

    async def run(self) -> Dict[str, Any]:
        """Run health checks.

        Returns:
            Dictionary with health status
        """
        from src.health.checks import HealthChecker

        checker = HealthChecker()
        report = await checker.check_all()

        result = report.to_dict()

        if report.status.value != "healthy":
            logger.warning(
                "health_check_degraded",
                status=report.status.value,
                checks=[c.to_dict() for c in report.checks if c.status.value != "pass"],
            )
        else:
            logger.info("health_check_passed", status=report.status.value)

        return result


class DRACorpusRefreshJob(BaseJob):
    """DRA corpus refresh job (Phase 8.5).

    Refreshes the Deep Research Agent corpus by ingesting new papers
    from the global registry after daily pipeline runs.
    """

    def __init__(
        self,
        corpus_data_dir: Optional[Path] = None,
        registry_path: Optional[Path] = None,
        force_reindex: bool = False,
    ):
        """Initialize DRA corpus refresh job.

        Args:
            corpus_data_dir: Directory for DRA corpus storage
            registry_path: Path to global paper registry
            force_reindex: Force re-indexing of all papers
        """
        super().__init__("dra_corpus_refresh")
        self.corpus_data_dir = corpus_data_dir or Path("./data/dra")
        self.registry_path = registry_path or Path("./data/registry")
        self.force_reindex = force_reindex

    async def run(self) -> Dict[str, Any]:
        """Refresh DRA corpus from registry.

        Ingests new papers discovered since last refresh into the
        searchable corpus for Deep Research Agent queries.

        Returns:
            Dictionary with refresh results
        """
        from src.models.dra import CorpusConfig
        from src.services.dra.corpus_manager import CorpusManager

        result: Dict[str, Any] = {
            "papers_ingested": 0,
            "corpus_size": 0,
            "status": "success",
            "error": None,
        }

        # Check if registry exists
        if not self.registry_path.exists():
            logger.warning(
                "dra_corpus_refresh_skipped",
                reason="registry_not_found",
                path=str(self.registry_path),
            )
            result["status"] = "skipped"
            result["error"] = "Registry directory not found"
            return result

        try:
            # Initialize corpus manager with config
            config = CorpusConfig(corpus_dir=str(self.corpus_data_dir))
            corpus_manager = CorpusManager(config=config)

            logger.info(
                "dra_corpus_refresh_starting",
                registry_path=str(self.registry_path),
                force_reindex=self.force_reindex,
            )

            # Ingest papers from registry
            papers_ingested = corpus_manager.ingest_from_registry(
                registry_path=self.registry_path,
                force=self.force_reindex,
            )

            result["papers_ingested"] = papers_ingested
            result["corpus_size"] = corpus_manager.stats.total_chunks

            logger.info(
                "dra_corpus_refresh_completed",
                papers_ingested=papers_ingested,
                corpus_size=result["corpus_size"],
            )

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            logger.error(
                "dra_corpus_refresh_failed",
                error=str(e),
                exc_info=True,
            )

        return result
