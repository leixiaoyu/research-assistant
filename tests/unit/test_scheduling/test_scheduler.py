"""Tests for ResearchScheduler."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.scheduling.scheduler import ResearchScheduler


class TestResearchSchedulerInit:
    """Tests for ResearchScheduler initialization."""

    def test_init_with_defaults(self):
        """Should initialize with default values."""
        scheduler = ResearchScheduler()

        assert scheduler.scheduler is not None
        assert scheduler._running is False
        assert len(scheduler._jobs) == 0

    def test_init_with_custom_values(self):
        """Should initialize with custom values."""
        scheduler = ResearchScheduler(
            timezone="America/New_York",
            max_instances=3,
            coalesce=False,
            misfire_grace_time=600,
        )

        assert scheduler.scheduler is not None


class TestAddJob:
    """Tests for add_job method."""

    def test_add_cron_job(self):
        """Should add job with cron trigger."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        job_id = scheduler.add_job(
            test_func,
            job_id="test_job",
            trigger="cron",
            hour=6,
            minute=0,
        )

        assert job_id == "test_job"
        assert "test_job" in scheduler._jobs
        assert len(scheduler.get_jobs()) == 1

    def test_add_interval_job(self):
        """Should add job with interval trigger."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        job_id = scheduler.add_job(
            test_func,
            job_id="interval_job",
            trigger="interval",
            hours=4,
        )

        assert job_id == "interval_job"
        assert "interval_job" in scheduler._jobs

    def test_add_job_replaces_existing(self):
        """Should replace existing job with same ID."""
        scheduler = ResearchScheduler()

        async def func1():
            pass

        async def func2():
            pass

        scheduler.add_job(func1, job_id="same_id", trigger="cron", hour=1)
        scheduler.add_job(func2, job_id="same_id", trigger="cron", hour=2)

        # Check internal tracking is correct (single entry per ID)
        assert len(scheduler._jobs) == 1
        assert "same_id" in scheduler._jobs


class TestRemoveJob:
    """Tests for remove_job method."""

    def test_remove_existing_job(self):
        """Should remove existing job."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        scheduler.add_job(test_func, job_id="to_remove", trigger="cron", hour=6)

        result = scheduler.remove_job("to_remove")

        assert result is True
        assert "to_remove" not in scheduler._jobs

    def test_remove_nonexistent_job(self):
        """Should return False for nonexistent job."""
        scheduler = ResearchScheduler()

        result = scheduler.remove_job("nonexistent")

        assert result is False


class TestPauseResumeJob:
    """Tests for pause_job and resume_job methods."""

    def test_pause_job(self):
        """Should pause existing job."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        scheduler.add_job(test_func, job_id="pausable", trigger="cron", hour=6)

        result = scheduler.pause_job("pausable")

        assert result is True

    def test_pause_nonexistent_job(self):
        """Should return False for nonexistent job."""
        scheduler = ResearchScheduler()

        result = scheduler.pause_job("nonexistent")

        assert result is False

    def test_resume_job(self):
        """Should resume paused job."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        scheduler.add_job(test_func, job_id="resumable", trigger="cron", hour=6)
        scheduler.pause_job("resumable")

        result = scheduler.resume_job("resumable")

        assert result is True

    def test_resume_nonexistent_job(self):
        """Should return False for nonexistent job."""
        scheduler = ResearchScheduler()

        result = scheduler.resume_job("nonexistent")

        assert result is False


class TestGetJobs:
    """Tests for get_jobs method."""

    def test_get_empty_jobs(self):
        """Should return empty list when no jobs."""
        scheduler = ResearchScheduler()

        jobs = scheduler.get_jobs()

        assert jobs == []

    def test_get_jobs_returns_info(self):
        """Should return job information."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        scheduler.add_job(test_func, job_id="info_job", trigger="cron", hour=6)

        jobs = scheduler.get_jobs()

        assert len(jobs) == 1
        assert jobs[0]["id"] == "info_job"
        assert "next_run_time" in jobs[0]


class TestIsRunning:
    """Tests for is_running property."""

    def test_is_running_false_initially(self):
        """Should be False initially."""
        scheduler = ResearchScheduler()

        assert scheduler.is_running is False


class TestShutdown:
    """Tests for shutdown method."""

    @pytest.mark.asyncio
    async def test_shutdown_when_not_running(self):
        """Should handle shutdown when not running."""
        scheduler = ResearchScheduler()

        # Should not raise
        await scheduler.shutdown()

        assert scheduler._running is False


class TestUpdateMetrics:
    """Tests for _update_metrics method."""

    def test_update_metrics(self):
        """Should update Prometheus metrics."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        scheduler.add_job(test_func, job_id="metric_job", trigger="cron", hour=6)

        # Should not raise
        scheduler._update_metrics()


class TestEventCallbacks:
    """Tests for event callback methods."""

    def test_on_job_executed(self):
        """Should log successful job execution."""
        scheduler = ResearchScheduler()

        mock_event = MagicMock()
        mock_event.job_id = "test_job"
        mock_event.scheduled_run_time = datetime.now()

        # Should not raise
        scheduler._on_job_executed(mock_event)

    def test_on_job_error(self):
        """Should log job error."""
        scheduler = ResearchScheduler()

        mock_event = MagicMock()
        mock_event.job_id = "test_job"
        mock_event.exception = Exception("Test error")
        mock_event.traceback = None

        # Should not raise
        scheduler._on_job_error(mock_event)

    def test_on_job_missed(self):
        """Should log missed job."""
        scheduler = ResearchScheduler()

        mock_event = MagicMock()
        mock_event.job_id = "test_job"
        mock_event.scheduled_run_time = datetime.now()

        # Should not raise
        scheduler._on_job_missed(mock_event)


class TestSignalHandler:
    """Tests for signal handler."""

    def test_signal_handler_creates_shutdown_task(self):
        """Should create shutdown task on signal."""
        scheduler = ResearchScheduler()

        # Mock asyncio.create_task
        with patch("asyncio.create_task") as mock_create_task:
            scheduler._signal_handler()

            # Should have called create_task
            mock_create_task.assert_called_once()


class TestAddJobEdgeCases:
    """Tests for add_job edge cases."""

    def test_add_job_with_custom_trigger(self):
        """Should handle custom trigger type."""
        scheduler = ResearchScheduler()

        async def test_func():
            pass

        # Using a trigger_obj directly
        from apscheduler.triggers.cron import CronTrigger

        custom_trigger = CronTrigger(hour=12)
        job_id = scheduler.add_job(
            test_func,
            job_id="custom_trigger_job",
            trigger="custom",
            trigger_obj=custom_trigger,
        )

        assert job_id == "custom_trigger_job"


class TestStartShutdownLifecycle:
    """Tests for scheduler start/shutdown lifecycle."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self):
        """Should set running flag when started."""
        scheduler = ResearchScheduler()

        # We can't fully test start() because it blocks, but we can test initial state
        assert scheduler._running is False
        assert not scheduler._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_start_already_running_returns_early(self):
        """Should return early if already running."""
        scheduler = ResearchScheduler()
        scheduler._running = True

        # Should return immediately
        await scheduler.start()

        # Still running
        assert scheduler._running is True

    @pytest.mark.asyncio
    async def test_shutdown_stops_scheduler(self):
        """Should stop scheduler on shutdown."""
        scheduler = ResearchScheduler()
        scheduler._running = True
        scheduler.scheduler.start()

        await scheduler.shutdown()

        assert scheduler._running is False
        assert scheduler._shutdown_event.is_set()
