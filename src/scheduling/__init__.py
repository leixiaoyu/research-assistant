"""Scheduling module for Phase 4: Production Hardening.

Provides:
- APScheduler wrapper for research job scheduling
- Pre-defined jobs (daily research, cache cleanup, cost reports)
- Integration with CLI for daemon mode

Usage:
    from src.scheduling import ResearchScheduler, DailyResearchJob

    # Create scheduler
    scheduler = ResearchScheduler()

    # Add daily research job
    scheduler.add_job(
        DailyResearchJob(),
        trigger="cron",
        hour=6,
        minute=0,
    )

    # Start scheduler
    await scheduler.start()
"""

from src.scheduling.scheduler import ResearchScheduler
from src.scheduling.jobs import (
    DailyResearchJob,
    CacheCleanupJob,
    CostReportJob,
    BaseJob,
)

__all__ = [
    "ResearchScheduler",
    "DailyResearchJob",
    "CacheCleanupJob",
    "CostReportJob",
    "BaseJob",
]
