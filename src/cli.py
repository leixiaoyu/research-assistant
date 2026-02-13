import typer
import asyncio
import structlog
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.services.config_manager import ConfigManager, ConfigValidationError
from src.services.discovery_service import APIError  # noqa: F401 (re-exported)
from src.models.catalog import CatalogRun  # noqa: F401 (used in type hints)
from src.utils.logging import configure_logging

# Configure structured logging
configure_logging()
logger = structlog.get_logger()

app = typer.Typer(help="ARISP: Automated Research Ingestion & Synthesis Pipeline")


@app.command()
def run(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate and plan without executing"
    ),
    no_synthesis: bool = typer.Option(
        False,
        "--no-synthesis",
        help="Skip Knowledge Base synthesis (faster runs)",
    ),
):
    """Run the research pipeline based on configuration"""
    try:
        # 1. Load Config
        config_manager = ConfigManager(config_path=str(config_path))
        try:
            config = config_manager.load_config()
        except (FileNotFoundError, ConfigValidationError) as e:
            typer.secho(f"Configuration Error: {e}", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        # Check if Phase 2 is enabled (based on config)
        phase2_enabled = (
            config.settings.pdf_settings is not None
            and config.settings.llm_settings is not None
            and config.settings.cost_limits is not None
        )

        if dry_run:
            typer.secho("Dry run: Configuration valid.", fg=typer.colors.GREEN)
            typer.echo(f"Found {len(config.research_topics)} topics:")
            for t in config.research_topics:  # pragma: no cover
                typer.echo(f" - {t.query} ({t.timeframe.type})")

            if phase2_enabled:
                # Type narrowing for Mypy
                assert config.settings.pdf_settings is not None
                assert config.settings.llm_settings is not None
                assert config.settings.cost_limits is not None

                typer.secho("\nPhase 2 Features Enabled:", fg=typer.colors.CYAN)
                pdf_status = (
                    "Keep PDFs"
                    if config.settings.pdf_settings.keep_pdfs
                    else "Delete after processing"
                )
                typer.echo(f" - PDF Processing: {pdf_status}")
                typer.echo(f" - LLM Provider: {config.settings.llm_settings.provider}")
                typer.echo(f" - LLM Model: {config.settings.llm_settings.model}")
                daily_limit = config.settings.cost_limits.max_daily_spend_usd
                total_limit = config.settings.cost_limits.max_total_spend_usd
                typer.echo(f" - Daily Cost Limit: ${daily_limit:.2f}")
                typer.echo(f" - Total Cost Limit: ${total_limit:.2f}")
            else:
                typer.secho(
                    "\nPhase 2 Features: Disabled (Phase 1 discovery only)",
                    fg=typer.colors.YELLOW,
                )

            return  # pragma: no cover

        # 2. Execute pipeline using shared ResearchPipeline
        # This ensures feature parity with scheduled DailyResearchJob
        from src.orchestration.research_pipeline import ResearchPipeline

        typer.secho("Starting research pipeline...", fg=typer.colors.CYAN)
        if phase2_enabled:
            typer.secho("✓ Phase 2 features enabled", fg=typer.colors.GREEN)
            typer.secho(
                "✓ Phase 3 concurrent processing enabled", fg=typer.colors.GREEN
            )
        else:
            typer.secho(
                "Running in Phase 1 mode (discovery only)", fg=typer.colors.YELLOW
            )

        if no_synthesis:
            typer.secho(
                "✗ Phase 3.6 synthesis disabled (--no-synthesis)",
                fg=typer.colors.YELLOW,
            )
        else:
            typer.secho("✓ Phase 3.6 synthesis enabled", fg=typer.colors.GREEN)

        pipeline = ResearchPipeline(
            config_path=config_path,
            enable_phase2=phase2_enabled,
            enable_synthesis=not no_synthesis,
        )

        result = asyncio.run(pipeline.run())

        # Display results
        typer.echo("")
        typer.secho("Pipeline completed!", fg=typer.colors.GREEN, bold=True)
        typer.echo(f"  Topics processed: {result.topics_processed}")
        typer.echo(f"  Papers discovered: {result.papers_discovered}")
        typer.echo(f"  Papers processed: {result.papers_processed}")
        if phase2_enabled:
            typer.echo(f"  Papers with extraction: {result.papers_with_extraction}")
            typer.echo(f"  Total tokens used: {result.total_tokens_used:,}")
            typer.echo(f"  Total cost: ${result.total_cost_usd:.4f}")
        typer.echo(f"  Output files: {len(result.output_files)}")

        if result.output_files:
            typer.echo("\nGenerated reports:")
            for f in result.output_files:
                typer.echo(f"  - {f}")

        if result.errors:
            typer.secho(f"\nErrors: {len(result.errors)}", fg=typer.colors.YELLOW)
            for err in result.errors:
                typer.echo(f"  - {err}")

    except Exception as e:
        logger.exception("pipeline_failed")
        typer.secho(f"Pipeline failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


# Legacy function kept for backwards compatibility
# New code should use ResearchPipeline directly
async def _process_topics(  # pragma: no cover (legacy, use ResearchPipeline)
    config,
    discovery,
    catalog_svc,
    md_gen,
    config_mgr,
    extraction_svc=None,
    phase2_enabled=False,
):
    """Async processing of topics (LEGACY - use ResearchPipeline instead)

    This function is kept for backwards compatibility.
    New code should use ResearchPipeline directly.

    Args:
        config: Research configuration
        discovery: Discovery service
        catalog_svc: Catalog service
        md_gen: Markdown generator (MarkdownGenerator or EnhancedMarkdownGenerator)
        config_mgr: Configuration manager
        extraction_svc: Extraction service (Phase 2, optional)
        phase2_enabled: Whether Phase 2 features are enabled
    """
    for topic in config.research_topics:
        try:
            run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            logger.info(
                "processing_topic",
                topic=topic.query,
                run_id=run_id,
                phase2=phase2_enabled,
            )

            # A. Get/Create Topic in Catalog
            catalog_topic = catalog_svc.get_or_create_topic(topic.query)

            # B. Discovery
            papers = await discovery.search(topic)

            if not papers:
                logger.warning("no_papers_found", topic=topic.query)
                continue

            # C. Phase 2: PDF Processing & LLM Extraction (if enabled)
            extracted_papers = None
            summary_stats = None

            if phase2_enabled and extraction_svc and topic.extraction_targets:
                logger.info(
                    "starting_phase2_extraction",
                    topic=topic.query,
                    papers_count=len(papers),
                    targets_count=len(topic.extraction_targets),
                )

                # Process papers through extraction pipeline
                # Phase 3.1: process_papers() uses concurrent processing when available
                extracted_papers = await extraction_svc.process_papers(
                    papers=papers,
                    targets=topic.extraction_targets,
                    run_id=run_id,
                    query=topic.query,
                )

                # Get summary statistics
                summary_stats = extraction_svc.get_extraction_summary(extracted_papers)

                logger.info(
                    "phase2_extraction_completed",
                    topic=topic.query,
                    papers_with_pdf=summary_stats["papers_with_pdf"],
                    papers_with_extraction=summary_stats["papers_with_extraction"],
                    total_tokens=summary_stats["total_tokens_used"],
                    total_cost_usd=summary_stats["total_cost_usd"],
                )

            # D. Generate Output
            # Get output path from config manager
            output_dir = config_mgr.get_output_path(catalog_topic.topic_slug)
            filename = f"{datetime.utcnow().strftime('%Y-%m-%d')}_Research.md"
            output_file = output_dir / filename

            # Generate markdown (Phase 1 or Phase 2 format)
            if phase2_enabled and extracted_papers is not None:
                # Phase 2: Enhanced markdown with extraction results
                content = md_gen.generate_enhanced(
                    extracted_papers=extracted_papers,
                    topic=topic,
                    run_id=run_id,
                    summary_stats=summary_stats,
                )
            else:
                # Phase 1: Basic markdown from paper metadata only
                content = md_gen.generate(papers, topic, run_id)

            with open(output_file, "w") as f:
                f.write(content)

            logger.info(
                "report_generated", path=str(output_file), phase2=phase2_enabled
            )

            # E. Update Catalog
            papers_processed = len(papers)
            if (
                phase2_enabled and summary_stats
            ):  # pragma: no cover (phase2 extraction path)
                papers_processed = summary_stats["papers_with_extraction"]

            run = CatalogRun(
                run_id=run_id,
                date=datetime.utcnow(),
                papers_found=len(papers),
                papers_processed=papers_processed,
                timeframe=(
                    str(topic.timeframe.value)
                    if hasattr(topic.timeframe, "value")
                    else "custom"
                ),
                output_file=str(output_file),
            )
            catalog_svc.add_run(catalog_topic.topic_slug, run)

        except APIError as e:
            logger.error("topic_failed", topic=topic.query, error=str(e))
            continue
        except Exception:
            logger.exception("topic_unexpected_error", topic=topic.query)
            continue


@app.command()
def validate(config_path: Path = typer.Argument(..., help="Config file to validate")):
    """Validate configuration file syntax and semantics"""
    try:
        manager = ConfigManager(config_path=str(config_path))
        manager.load_config()
        typer.secho("Configuration is valid! ✅", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Validation failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def catalog(
    action: str = typer.Argument(..., help="Action: show, history"),
    topic: Optional[str] = typer.Option(None, help="Filter by topic slug"),
):
    """Manage research catalog"""
    manager = ConfigManager()
    cat = manager.load_catalog()

    if action == "show":
        typer.echo(f"Catalog contains {len(cat.topics)} topics:")
        for slug, t in cat.topics.items():
            typer.echo(f" - {slug}: {t.query} ({len(t.runs)} runs)")

    elif action == "history":
        if not topic:
            typer.secho("Please provide --topic for history", fg=typer.colors.YELLOW)
            return

        if topic not in cat.topics:
            typer.secho(f"Topic '{topic}' not found", fg=typer.colors.RED)
            return

        t = cat.topics[topic]
        typer.echo(f"History for {t.query}:")
        for run in t.runs:
            typer.echo(
                f"  {run.date}: Found {run.papers_found} papers "
                f"-> {run.output_file}"
            )


@app.command()
def schedule(
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
    """Start scheduler daemon with health server.

    Runs the research pipeline on a schedule with monitoring endpoints.
    Press Ctrl+C to stop gracefully.

    Examples:
        # Run with defaults (6:00 AM daily)
        python -m src.cli schedule

        # Custom schedule (8:30 AM)
        python -m src.cli schedule --hour 8 --minute 30

        # Custom health port
        python -m src.cli schedule --health-port 9000
    """
    try:  # pragma: no cover (CLI blocking entry point)
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
        typer.secho("\nScheduler stopped.", fg=typer.colors.YELLOW)
    except Exception as e:
        logger.exception("scheduler_failed")
        typer.secho(f"Scheduler failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


async def _run_scheduler(  # pragma: no cover (blocking scheduler daemon)
    config_path: Path,
    hour: int,
    minute: int,
    health_port: int,
    enable_cleanup: bool,
    enable_cost_report: bool,
):
    """Run the scheduler daemon with health server.

    Args:
        config_path: Path to research config
        hour: Hour for daily research run
        minute: Minute for daily research run
        health_port: Port for health server
        enable_cleanup: Whether to enable cache cleanup
        enable_cost_report: Whether to enable cost reporting
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
    typer.secho(f"\nScheduled {len(jobs)} jobs:", fg=typer.colors.GREEN)
    for job in jobs:
        next_run = job.get("next_run_time", "N/A")
        typer.echo(f"  - {job['id']}: next run at {next_run}")

    # Start health server and scheduler concurrently
    await asyncio.gather(
        run_health_server_async(host="0.0.0.0", port=health_port, log_level="warning"),
        scheduler.start(),
    )


@app.command()
def health(
    host: str = typer.Option("localhost", "--host", "-h", help="Health server host"),
    port: int = typer.Option(8000, "--port", "-p", help="Health server port"),
):
    """Start standalone health server.

    Starts the health server without the scheduler.
    Useful for testing or when running scheduler separately.
    """
    from src.health.server import (
        run_health_server,
    )  # pragma: no cover (CLI blocking entry point)

    typer.secho(  # pragma: no cover
        f"Starting health server at http://{host}:{port}",
        fg=typer.colors.CYAN,
    )
    run_health_server(host=host, port=port)  # pragma: no cover


if __name__ == "__main__":
    app()  # pragma: no cover
