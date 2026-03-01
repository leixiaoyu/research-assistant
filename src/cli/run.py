"""Run command for the research pipeline.

Handles pipeline execution and result display.
"""

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

import typer

from src.cli.utils import (
    load_config,
    handle_errors,
    display_success,
    display_warning,
    display_info,
    is_phase2_enabled,
    logger,
)
from src.models.config import ResearchConfig

if TYPE_CHECKING:
    from src.orchestration import PipelineResult, ResearchPipeline


@handle_errors
def run_command(
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
    """Run the research pipeline based on configuration."""
    # 1. Load Config
    config = load_config(config_path)

    # Check if Phase 2 is enabled
    phase2_enabled = is_phase2_enabled(config)

    if dry_run:
        _display_dry_run(config, phase2_enabled)
        return

    # 2. Execute pipeline using shared ResearchPipeline
    from src.orchestration import ResearchPipeline

    display_info("Starting research pipeline...")
    if phase2_enabled:
        display_success("✓ Phase 2 features enabled")
        display_success("✓ Phase 3 concurrent processing enabled")
    else:
        display_warning("Running in Phase 1 mode (discovery only)")

    if no_synthesis:
        display_warning("✗ Phase 3.6 synthesis disabled (--no-synthesis)")
    else:
        display_success("✓ Phase 3.6 synthesis enabled")

    pipeline = ResearchPipeline(
        config_path=config_path,
        enable_phase2=phase2_enabled,
        enable_synthesis=not no_synthesis,
    )

    result = asyncio.run(pipeline.run())

    # Display results
    _display_results(result, phase2_enabled)

    # Send notifications (Phase 3.7 + 3.8 deduplication)
    asyncio.run(_send_notifications(result, config, phase2_enabled, pipeline))


def _display_dry_run(config: ResearchConfig, phase2_enabled: bool) -> None:
    """Display dry run information.

    Args:
        config: Research configuration.
        phase2_enabled: Whether Phase 2 features are enabled.
    """
    display_success("Dry run: Configuration valid.")
    typer.echo(f"Found {len(config.research_topics)} topics:")
    for t in config.research_topics:
        typer.echo(f" - {t.query} ({t.timeframe.type})")

    if phase2_enabled:
        # Type narrowing for Mypy
        assert config.settings.pdf_settings is not None
        assert config.settings.llm_settings is not None
        assert config.settings.cost_limits is not None

        display_info("\nPhase 2 Features Enabled:")
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
        display_warning("\nPhase 2 Features: Disabled (Phase 1 discovery only)")


def _display_results(result: "PipelineResult", phase2_enabled: bool) -> None:
    """Display pipeline execution results.

    Args:
        result: PipelineResult from pipeline execution.
        phase2_enabled: Whether Phase 2 features are enabled.
    """
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
        display_warning(f"\nErrors: {len(result.errors)}")
        for err in result.errors:
            typer.echo(f"  - {err}")


async def _send_notifications(
    result: "PipelineResult",
    config: ResearchConfig,
    phase2_enabled: bool,
    pipeline: Optional["ResearchPipeline"] = None,
) -> None:
    """Send pipeline notifications (Phase 3.7 + 3.8 deduplication).

    Notifications are fail-safe - errors are logged but never raised.

    Args:
        result: PipelineResult from pipeline execution.
        config: ResearchConfig with notification settings.
        phase2_enabled: Whether Phase 2 features are enabled.
        pipeline: ResearchPipeline instance for accessing context (Phase 3.8).
    """
    _ = phase2_enabled  # Reserved for future use
    try:
        # Check if notification settings exist
        if not hasattr(config.settings, "notification_settings"):
            logger.debug("notification_settings_not_configured")
            return

        notification_settings = config.settings.notification_settings
        if notification_settings is None:
            logger.debug("notification_settings_none")
            return

        # Skip if Slack notifications disabled
        if not notification_settings.slack.enabled:
            logger.debug("slack_notifications_disabled")
            return

        from src.services.notification_service import NotificationService
        from src.services.notification import NotificationDeduplicator
        from src.services.report_parser import ReportParser
        from src.models.notification import KeyLearning, DeduplicationResult

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
            display_success("Slack notification sent")
        else:
            logger.warning(
                "notification_failed",
                provider=notification_result.provider,
                error=notification_result.error,
            )
            display_warning(f"⚠ Slack notification failed: {notification_result.error}")

    except Exception as e:
        # Notifications should never break the pipeline
        logger.error(
            "notification_error",
            error=str(e),
        )
        display_warning(f"⚠ Notification error: {e}")
