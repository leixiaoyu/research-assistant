"""APScheduler wrapper for research job scheduling.

Provides:
- Async-compatible scheduler
- Job management (add, remove, pause, resume)
- Graceful shutdown handling
- Integration with Prometheus metrics

Usage:
    scheduler = ResearchScheduler()

    # Add job with cron trigger
    scheduler.add_daily_research_job(config_path, hour=6)

    # Start scheduler
    await scheduler.start()

    # Stop gracefully
    await scheduler.shutdown()
"""

import asyncio
import signal
from typing import Any, Callable, Dict, List  # noqa: F401
import structlog

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import (
    EVENT_JOB_EXECUTED,
    EVENT_JOB_ERROR,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
)

from src.observability.metrics import SCHEDULER_JOBS

logger = structlog.get_logger()


class ResearchScheduler:
    """Async scheduler for ARISP research jobs.

    Wraps APScheduler's AsyncIOScheduler with:
    - Job lifecycle management
    - Error handling and logging
    - Prometheus metrics integration
    - Graceful shutdown
    """

    def __init__(
        self,
        timezone: str = "UTC",
        max_instances: int = 1,
        coalesce: bool = True,
        misfire_grace_time: int = 300,
    ):
        """Initialize research scheduler.

        Args:
            timezone: Timezone for job scheduling
            max_instances: Max concurrent instances per job
            coalesce: Coalesce missed executions
            misfire_grace_time: Grace time for missed jobs (seconds)
        """
        self.scheduler = AsyncIOScheduler(
            timezone=timezone,
            job_defaults={
                "max_instances": max_instances,
                "coalesce": coalesce,
                "misfire_grace_time": misfire_grace_time,
            },
        )

        self._running = False
        self._shutdown_event = asyncio.Event()
        self._jobs: Dict[str, Any] = {}

        # Add event listeners
        self.scheduler.add_listener(self._on_job_executed, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._on_job_error, EVENT_JOB_ERROR)
        self.scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)

        logger.info("scheduler_initialized", timezone=timezone)

    def add_job(
        self,
        func: Callable,
        job_id: str,
        trigger: str = "cron",
        **trigger_args: Any,
    ) -> str:
        """Add a job to the scheduler.

        Args:
            func: Async function to execute
            job_id: Unique job identifier
            trigger: Trigger type ('cron', 'interval', 'date')
            **trigger_args: Trigger-specific arguments

        Returns:
            Job ID

        Example:
            # Daily at 6:00 AM
            scheduler.add_job(
                daily_research,
                job_id="daily_research",
                trigger="cron",
                hour=6,
                minute=0,
            )

            # Every 4 hours
            scheduler.add_job(
                cache_cleanup,
                job_id="cache_cleanup",
                trigger="interval",
                hours=4,
            )
        """
        if trigger == "cron":
            trigger_obj = CronTrigger(**trigger_args)
        elif trigger == "interval":
            trigger_obj = IntervalTrigger(**trigger_args)
        else:
            trigger_obj = trigger_args.get("trigger_obj", trigger)

        job = self.scheduler.add_job(
            func,
            trigger=trigger_obj,
            id=job_id,
            name=job_id,
            replace_existing=True,
        )

        self._jobs[job_id] = job

        next_run = getattr(job, "next_run_time", None)
        logger.info(
            "job_added",
            job_id=job_id,
            trigger=trigger,
            next_run=str(next_run) if next_run else "not scheduled",
        )

        self._update_metrics()
        return job_id

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler.

        Args:
            job_id: Job ID to remove

        Returns:
            True if job was removed, False if not found
        """
        try:
            self.scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            logger.info("job_removed", job_id=job_id)
            self._update_metrics()
            return True
        except Exception as e:
            logger.warning("job_remove_failed", job_id=job_id, error=str(e))
            return False

    def pause_job(self, job_id: str) -> bool:
        """Pause a job.

        Args:
            job_id: Job ID to pause

        Returns:
            True if paused, False if not found
        """
        try:
            self.scheduler.pause_job(job_id)
            logger.info("job_paused", job_id=job_id)
            return True
        except Exception as e:
            logger.warning("job_pause_failed", job_id=job_id, error=str(e))
            return False

    def resume_job(self, job_id: str) -> bool:
        """Resume a paused job.

        Args:
            job_id: Job ID to resume

        Returns:
            True if resumed, False if not found
        """
        try:
            self.scheduler.resume_job(job_id)
            logger.info("job_resumed", job_id=job_id)
            return True
        except Exception as e:
            logger.warning("job_resume_failed", job_id=job_id, error=str(e))
            return False

    def get_jobs(self) -> List[Dict[str, Any]]:
        """Get list of all scheduled jobs.

        Returns:
            List of job information dictionaries
        """
        jobs = []
        for job in self.scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            pending = getattr(job, "pending", False)
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": str(next_run) if next_run else None,
                    "pending": pending,
                }
            )
        return jobs

    async def start(self) -> None:
        """Start the scheduler.

        Begins executing scheduled jobs and blocks until shutdown.
        """
        if self._running:  # pragma: no cover
            logger.warning("scheduler_already_running")
            return

        self._running = True  # pragma: no cover (blocking scheduler runtime)
        self._shutdown_event.clear()  # pragma: no cover

        # Register signal handlers
        loop = asyncio.get_event_loop()  # pragma: no cover
        for sig in (signal.SIGTERM, signal.SIGINT):  # pragma: no cover
            loop.add_signal_handler(sig, self._signal_handler)  # pragma: no cover

        self.scheduler.start()  # pragma: no cover
        logger.info("scheduler_started", jobs=len(self._jobs))  # pragma: no cover

        self._update_metrics()  # pragma: no cover

        # Wait for shutdown signal
        await self._shutdown_event.wait()  # pragma: no cover

    async def shutdown(self, wait: bool = True) -> None:
        """Shutdown the scheduler gracefully.

        Args:
            wait: Wait for running jobs to complete
        """
        if not self._running:
            return

        logger.info("scheduler_shutting_down")

        self.scheduler.shutdown(wait=wait)
        self._running = False
        self._shutdown_event.set()

        logger.info("scheduler_stopped")

    def _signal_handler(self) -> None:
        """Handle termination signals."""
        logger.info("shutdown_signal_received")
        asyncio.create_task(self.shutdown())

    def _on_job_executed(self, event: JobExecutionEvent) -> None:
        """Handle successful job execution."""
        logger.info(
            "job_executed",
            job_id=event.job_id,
            scheduled_run_time=str(event.scheduled_run_time),
        )
        self._update_metrics()

    def _on_job_error(self, event: JobExecutionEvent) -> None:
        """Handle job execution error."""
        logger.error(
            "job_failed",
            job_id=event.job_id,
            exception=str(event.exception),
            traceback=event.traceback,
        )
        self._update_metrics()

    def _on_job_missed(self, event: JobExecutionEvent) -> None:
        """Handle missed job execution."""
        logger.warning(
            "job_missed",
            job_id=event.job_id,
            scheduled_run_time=str(event.scheduled_run_time),
        )
        self._update_metrics()

    def _update_metrics(self) -> None:
        """Update Prometheus metrics."""
        pending = sum(1 for j in self.scheduler.get_jobs() if j.pending)
        running = len(self._jobs) - pending

        SCHEDULER_JOBS.labels(status="pending").set(pending)
        SCHEDULER_JOBS.labels(status="running").set(running)

    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
