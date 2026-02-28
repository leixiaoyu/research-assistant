"""Schedule commands for scheduler management.

Provides commands for starting and managing the research scheduler.
"""

import asyncio
from pathlib import Path

import typer

from src.cli.utils import handle_errors, display_warning, display_success, logger


def _validate_hour(value: int) -> int:
    """Validate hour is in range 0-23."""
    if not 0 <= value <= 23:
        raise typer.BadParameter("Hour must be between 0 and 23")
    return value


def _validate_minute(value: int) -> int:
    """Validate minute is in range 0-59."""
    if not 0 <= value <= 59:
        raise typer.BadParameter("Minute must be between 0 and 59")
    return value


# Create schedule sub-app
schedule_app = typer.Typer(help="Manage research scheduler")


@schedule_app.command(name="start")
def schedule_start(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    hour: int = typer.Option(
        6,
        "--hour",
        "-H",
        help="Hour to run daily research (0-23)",
        callback=_validate_hour,
    ),
    minute: int = typer.Option(
        0,
        "--minute",
        "-M",
        help="Minute to run (0-59)",
        callback=_validate_minute,
    ),
    health_port: int = typer.Option(
        8000, "--health-port", "-p", help="Port for health server"
    ),
    enable_cleanup: bool = typer.Option(
        True, "--cleanup/--no-cleanup", help="Enable cache cleanup job"
    ),
    enable_cost_report: bool = typer.Option(
        True, "--cost-report/--no-cost-report", help="Enable daily cost report"
    ),
):
    """Start scheduler daemon with health server.

    Runs the research pipeline on a schedule with monitoring endpoints.
    Press Ctrl+C to stop gracefully.

    Examples:
        # Run with defaults (6:00 AM daily)
        python -m src.cli schedule start

        # Custom schedule (8:30 AM)
        python -m src.cli schedule start --hour 8 --minute 30

        # Custom health port
        python -m src.cli schedule start --health-port 9000
    """
    try:
        asyncio.run(
            _run_scheduler(
                config_path=config_path,
                hour=hour,
                minute=minute,
                health_port=health_port,
                enable_cleanup=enable_cleanup,
                enable_cost_report=enable_cost_report,
            )
        )
    except KeyboardInterrupt:
        display_warning("\nScheduler stopped.")
    except Exception as e:
        logger.exception("scheduler_failed")
        typer.secho(f"Scheduler failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


async def _run_scheduler(
    config_path: Path,
    hour: int,
    minute: int,
    health_port: int,
    enable_cleanup: bool,
    enable_cost_report: bool,
):
    """Run the scheduler daemon with health server.

    Args:
        config_path: Path to research config.
        hour: Hour for daily research run.
        minute: Minute for daily research run.
        health_port: Port for health server.
        enable_cleanup: Whether to enable cache cleanup.
        enable_cost_report: Whether to enable cost reporting.
    """
    from src.scheduling import (
        ResearchScheduler,
        DailyResearchJob,
        CacheCleanupJob,
        CostReportJob,
    )
    from src.health.server import run_health_server_async

    typer.secho(
        "Starting ARISP Scheduler Daemon",
        fg=typer.colors.CYAN,
        bold=True,
    )
    typer.echo(f"  Config: {config_path}")
    typer.echo(f"  Daily run: {hour:02d}:{minute:02d}")
    typer.echo(f"  Health endpoint: http://localhost:{health_port}/health")
    typer.echo(f"  Metrics endpoint: http://localhost:{health_port}/metrics")
    typer.echo("\nPress Ctrl+C to stop.\n")

    # Create scheduler
    scheduler = ResearchScheduler()

    # Add daily research job
    daily_job = DailyResearchJob(config_path=config_path)
    scheduler.add_job(
        daily_job,
        job_id="daily_research",
        trigger="cron",
        hour=hour,
        minute=minute,
    )

    # Add cache cleanup job (every 4 hours)
    if enable_cleanup:
        cleanup_job = CacheCleanupJob()
        scheduler.add_job(
            cleanup_job,
            job_id="cache_cleanup",
            trigger="interval",
            hours=4,
        )

    # Add cost report job (daily at 23:00)
    if enable_cost_report:
        cost_job = CostReportJob()
        scheduler.add_job(
            cost_job,
            job_id="cost_report",
            trigger="cron",
            hour=23,
            minute=0,
        )

    # Log scheduled jobs
    jobs = scheduler.get_jobs()
    display_success(f"\nScheduled {len(jobs)} jobs:")
    for job in jobs:
        next_run = job.get("next_run_time", "N/A")
        typer.echo(f"  - {job['id']}: next run at {next_run}")

    # Start health server and scheduler concurrently
    await asyncio.gather(
        run_health_server_async(host="0.0.0.0", port=health_port, log_level="warning"),
        scheduler.start(),
    )


# Legacy command for backward compatibility
@handle_errors
def schedule_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    hour: int = typer.Option(
        6, "--hour", "-H", help="Hour to run daily research (0-23)"
    ),
    minute: int = typer.Option(0, "--minute", "-M", help="Minute to run (0-59)"),
    health_port: int = typer.Option(
        8000, "--health-port", "-p", help="Port for health server"
    ),
    enable_cleanup: bool = typer.Option(
        True, "--cleanup/--no-cleanup", help="Enable cache cleanup job"
    ),
    enable_cost_report: bool = typer.Option(
        True, "--cost-report/--no-cost-report", help="Enable daily cost report"
    ),
):
    """Start scheduler daemon with health server (legacy interface).

    Use 'schedule start' instead.
    """
    schedule_start(
        config_path=config_path,
        hour=hour,
        minute=minute,
        health_port=health_port,
        enable_cleanup=enable_cleanup,
        enable_cost_report=enable_cost_report,
    )
