"""Synthesize command for cross-topic synthesis.

Provides commands for running cross-topic knowledge synthesis.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog
import typer

from src.cli.utils import (
    handle_errors,
    display_info,
    display_warning,
    display_error,
)

logger = structlog.get_logger()


@handle_errors
def synthesize_command(
    config_path: Path = typer.Option(
        "config/synthesis_config.yaml",
        "--config",
        "-c",
        help="Path to synthesis config YAML",
    ),
    question: Optional[str] = typer.Option(
        None,
        "--question",
        "-q",
        help="Run only specific question by ID",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force full synthesis (ignore incremental mode)",
    ),
):
    """Run cross-topic knowledge synthesis.

    Synthesizes insights across multiple research topics using LLM.
    Generates Global_Synthesis.md with answers to configured questions.

    Examples:
        # Run all enabled synthesis questions
        python -m src.cli synthesize

        # Run with custom config
        python -m src.cli synthesize --config my_synthesis.yaml

        # Run specific question only
        python -m src.cli synthesize --question mt-quality-improvement

        # Force full synthesis (ignore incremental mode)
        python -m src.cli synthesize --force
    """
    from src.services.registry_service import RegistryService
    from src.services.cross_synthesis_service import CrossTopicSynthesisService
    from src.output.cross_synthesis_generator import CrossSynthesisGenerator

    display_info("Starting cross-topic synthesis...")

    # Initialize services
    registry_service = RegistryService()
    synthesis_service = CrossTopicSynthesisService(
        registry_service=registry_service,
        config_path=config_path,
    )
    generator = CrossSynthesisGenerator()

    # Check for enabled questions
    enabled_questions = synthesis_service.get_enabled_questions()
    if not enabled_questions:
        display_warning("No enabled synthesis questions found.")
        return

    # If specific question requested, validate it exists
    if question:
        target_question = synthesis_service.get_question_by_id(question)
        if not target_question:
            display_error(f"Question '{question}' not found in config.")
            raise typer.Exit(code=1)
        if not target_question.enabled:
            display_warning(f"Question '{question}' is disabled in config.")
            return

    typer.echo(f"Config: {config_path}")
    typer.echo(f"Enabled questions: {len(enabled_questions)}")
    if force:
        display_warning("Force mode: ignoring incremental checks")

    # Run synthesis
    async def run_synthesis():
        if question:
            target_q = synthesis_service.get_question_by_id(question)
            if target_q:
                budget = synthesis_service.config.budget_per_synthesis_usd
                result = await synthesis_service.synthesize_question(
                    question=target_q,
                    budget_remaining=budget,
                )
                # Create report with single result
                from src.models.cross_synthesis import CrossTopicSynthesisReport

                report = CrossTopicSynthesisReport(
                    report_id=f"syn-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
                    total_papers_in_registry=len(synthesis_service.get_all_entries()),
                    results=[result],
                    total_tokens_used=result.tokens_used,
                    total_cost_usd=result.cost_usd,
                    incremental=False,
                )
                return report
            return None
        else:
            return await synthesis_service.synthesize_all(force=force)

    report = asyncio.run(run_synthesis())

    if not report or not report.results:
        display_warning(
            "No synthesis results generated "
            "(may be skipped due to incremental mode)."
        )
        return

    # Write output
    output_path = generator.write(report=report, incremental=not force)

    # Display results
    _display_synthesis_results(report, output_path)


def _display_synthesis_results(report, output_path) -> None:
    """Display synthesis execution results.

    Args:
        report: CrossTopicSynthesisReport from synthesis.
        output_path: Path to output file.
    """
    typer.echo("")
    typer.secho("Synthesis completed!", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  Questions answered: {report.questions_answered}")
    typer.echo(f"  Total tokens used: {report.total_tokens_used:,}")
    typer.echo(f"  Total cost: ${report.total_cost_usd:.4f}")
    if output_path:
        typer.echo(f"  Output: {output_path}")

    if report.results:
        typer.echo("\nSynthesis results:")
        for result in report.results:
            status = "✓" if result.tokens_used > 0 else "○"
            typer.echo(
                f"  {status} {result.question_name}: "
                f"{len(result.papers_used)} papers, ${result.cost_usd:.4f}"
            )
