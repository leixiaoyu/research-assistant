"""Trajectory management CLI commands for DRA.

Provides commands for listing, analyzing, and exporting trajectories.

Usage:
    python -m src.cli trajectories list
    python -m src.cli trajectories analyze
    python -m src.cli trajectories export --format jsonl
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import structlog
import typer

from src.cli.utils import (
    display_error,
    display_info,
    display_success,
    display_warning,
    handle_errors,
    load_config,
)
from src.services.dra.trajectory import TrajectoryCollector

logger = structlog.get_logger()

# Create trajectories sub-application
trajectories_app = typer.Typer(help="Trajectory management commands")


def _get_storage_dir(config_path: Path) -> Path:
    """Get trajectory storage directory from config.

    Args:
        config_path: Path to research config

    Returns:
        Path to trajectory storage directory
    """
    config = load_config(config_path)

    # Get storage directory from config or use default
    storage_dir = Path(
        getattr(
            getattr(config.settings, "dra_settings", None),
            "trajectory_dir",
            "./data/dra/trajectories",
        )
        or "./data/dra/trajectories"
    )

    return storage_dir


@trajectories_app.command("list")
@handle_errors
def list_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    limit: int = typer.Option(
        20,
        "--limit",
        "-n",
        help="Maximum number of trajectories to display",
    ),
    min_quality: float = typer.Option(
        0.0,
        "--min-quality",
        "-q",
        help="Minimum quality score filter (0.0-1.0)",
    ),
    show_details: bool = typer.Option(
        False,
        "--details",
        "-d",
        help="Show detailed information for each trajectory",
    ),
) -> None:
    """List all recorded trajectories.

    Displays trajectory metadata including quality scores, turn counts,
    and papers consulted. Use filters to narrow down results.

    Examples:
        arisp trajectories list
        arisp trajectories list --limit 10 --min-quality 0.7
        arisp trajectories list --details
    """
    storage_dir = _get_storage_dir(config_path)

    if not storage_dir.exists():
        display_warning(f"Trajectory storage not found: {storage_dir}")
        display_info("Run some research sessions first to generate trajectories")
        return

    try:
        collector = TrajectoryCollector(storage_dir=storage_dir)
        trajectories = collector.filter_quality(
            min_turns=0,
            require_answer=False,
            min_quality_score=min_quality,
        )

        if not trajectories:
            display_info("No trajectories found matching criteria")
            return

        # Sort by created_at (newest first)
        trajectories.sort(key=lambda t: t.created_at, reverse=True)

        # Apply limit
        trajectories = trajectories[:limit]

        display_info(f"Found {len(trajectories)} trajectories")
        display_info("=" * 60)

        for traj in trajectories:
            # Format created_at
            created_str = traj.created_at.strftime("%Y-%m-%d %H:%M")

            # Truncate question for display
            question_display = (
                traj.question[:60] + "..." if len(traj.question) > 60 else traj.question
            )

            # Display trajectory summary
            status = "✓" if traj.answer else "✗"
            quality_bar = "█" * int(traj.quality_score * 10) + "░" * (
                10 - int(traj.quality_score * 10)
            )

            typer.echo(f"\n{status} {traj.trajectory_id}")
            typer.echo(f"  Question: {question_display}")
            typer.echo(
                f"  Quality: [{quality_bar}] {traj.quality_score:.2f} | "
                f"Turns: {len(traj.turns)} | Papers: {traj.papers_opened}"
            )
            typer.echo(f"  Created: {created_str}")

            if show_details:
                typer.echo(f"  Unique searches: {traj.unique_searches}")
                typer.echo(f"  Find operations: {traj.find_operations}")
                typer.echo(f"  Context tokens: {traj.context_length_tokens:,}")
                if traj.answer:
                    answer_preview = (
                        traj.answer[:100] + "..."
                        if len(traj.answer) > 100
                        else traj.answer
                    )
                    typer.echo(f"  Answer: {answer_preview}")

        display_info("=" * 60)
        display_success(f"Listed {len(trajectories)} trajectories")

    except Exception as e:
        logger.exception("list_trajectories_failed")
        display_error(f"Failed to list trajectories: {e}")
        raise typer.Exit(code=1)


@trajectories_app.command("analyze")
@handle_errors
def analyze_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    min_quality: float = typer.Option(
        0.5,
        "--min-quality",
        "-q",
        help="Minimum quality score for analysis (0.0-1.0)",
    ),
    generate_tips: bool = typer.Option(
        True,
        "--tips/--no-tips",
        help="Generate contextual learning tips",
    ),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for analysis results (JSON)",
    ),
) -> None:
    """Analyze trajectory patterns and generate insights.

    Examines recorded trajectories to extract:
    - Effective query patterns
    - Successful action sequences
    - Average turns to success
    - Paper consultation patterns

    Optionally generates contextual learning tips for future sessions.

    Examples:
        arisp trajectories analyze
        arisp trajectories analyze --min-quality 0.7 --output analysis.json
        arisp trajectories analyze --no-tips
    """
    storage_dir = _get_storage_dir(config_path)

    if not storage_dir.exists():
        display_warning(f"Trajectory storage not found: {storage_dir}")
        display_info("Run some research sessions first to generate trajectories")
        return

    try:
        collector = TrajectoryCollector(storage_dir=storage_dir)

        # Filter quality trajectories
        trajectories = collector.filter_quality(
            min_turns=3,
            require_answer=True,
            min_quality_score=min_quality,
        )

        if not trajectories:
            display_warning("No quality trajectories found for analysis")
            display_info(f"Try lowering --min-quality below {min_quality}")
            return

        display_info(f"Analyzing {len(trajectories)} quality trajectories...")

        # Analyze patterns
        insights = collector.analyze_patterns(trajectories)

        # Display insights
        display_info("\n📊 Trajectory Analysis Results")
        display_info("=" * 50)

        # Query patterns
        if insights.effective_query_patterns:
            display_info("\n🔍 Effective Query Patterns:")
            for i, pattern in enumerate(insights.effective_query_patterns[:10], 1):
                typer.echo(f"  {i}. {pattern}")

        # Successful sequences
        if insights.successful_sequences:
            display_info("\n🔗 Successful Action Sequences:")
            for i, seq in enumerate(insights.successful_sequences[:5], 1):
                typer.echo(f"  {i}. {seq}")

        # Statistics
        display_info("\n📈 Statistics:")
        typer.echo(
            f"  Average turns to success: {insights.average_turns_to_success:.1f}"
        )

        # Paper consultation patterns
        if insights.paper_consultation_patterns:
            display_info("\n📚 Paper Consultation Patterns:")
            sorted_patterns = sorted(
                insights.paper_consultation_patterns.items(),
                key=lambda x: x[1],
                reverse=True,
            )
            for section, count in sorted_patterns[:5]:
                typer.echo(f"  {section}: {count} times")

        # Generate tips if requested
        tips = []
        if generate_tips:
            tips = collector.generate_contextual_tips(insights, min_confidence=0.7)

            if tips:
                display_info("\n💡 Learning Tips Generated:")
                for i, tip in enumerate(tips, 1):
                    typer.echo(f"\n  Tip {i} (confidence: {tip.confidence:.0%}):")
                    typer.echo(f"    Context: {tip.context}")
                    typer.echo(f"    Strategy: {tip.strategy}")

        display_info("\n" + "=" * 50)
        display_success("Analysis complete")

        # Save to file if requested
        if output_file:
            import json

            output_data = {
                "analyzed_at": datetime.now(UTC).isoformat(),
                "trajectory_count": len(trajectories),
                "min_quality_filter": min_quality,
                "insights": {
                    "effective_query_patterns": insights.effective_query_patterns,
                    "successful_sequences": insights.successful_sequences,
                    "average_turns_to_success": insights.average_turns_to_success,
                    "paper_consultation_patterns": insights.paper_consultation_patterns,
                    "failure_modes": insights.failure_modes,
                },
                "tips": [
                    {
                        "context": tip.context,
                        "strategy": tip.strategy,
                        "confidence": tip.confidence,
                        "examples": tip.examples,
                    }
                    for tip in tips
                ],
            }

            output_file.write_text(json.dumps(output_data, indent=2))
            display_success(f"Analysis saved to {output_file}")

    except Exception as e:
        logger.exception("analyze_trajectories_failed")
        display_error(f"Failed to analyze trajectories: {e}")
        raise typer.Exit(code=1)


@trajectories_app.command("export")
@handle_errors
def export_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    output_file: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output file path",
    ),
    format: str = typer.Option(
        "jsonl",
        "--format",
        "-f",
        help="Export format: jsonl (ShareGPT), json, or csv",
    ),
    min_quality: float = typer.Option(
        0.6,
        "--min-quality",
        "-q",
        help="Minimum quality score for export (0.0-1.0)",
    ),
    include_failed: bool = typer.Option(
        False,
        "--include-failed",
        help="Include trajectories without answers",
    ),
) -> None:
    """Export trajectories for external use or fine-tuning.

    Supports multiple export formats:
    - jsonl: ShareGPT format for SFT/RLHF training
    - json: Full trajectory data as JSON array
    - csv: Summary statistics in CSV format

    Examples:
        arisp trajectories export -o training_data.jsonl
        arisp trajectories export -o data.json --format json --min-quality 0.8
        arisp trajectories export -o stats.csv --format csv --include-failed
    """
    storage_dir = _get_storage_dir(config_path)

    if not storage_dir.exists():
        display_warning(f"Trajectory storage not found: {storage_dir}")
        display_info("Run some research sessions first to generate trajectories")
        return

    # Validate format
    valid_formats = ["jsonl", "json", "csv"]
    if format not in valid_formats:
        display_error(f"Invalid format: {format}. Choose from: {valid_formats}")
        raise typer.Exit(code=1)

    try:
        collector = TrajectoryCollector(storage_dir=storage_dir)

        # Filter trajectories
        trajectories = collector.filter_quality(
            min_turns=3,
            require_answer=not include_failed,
            min_quality_score=min_quality,
        )

        if not trajectories:
            display_warning("No trajectories found matching export criteria")
            return

        display_info(f"Exporting {len(trajectories)} trajectories as {format}...")

        if format == "jsonl":
            _export_jsonl(trajectories, output_file)
        elif format == "json":
            _export_json(trajectories, output_file)
        elif format == "csv":
            _export_csv(trajectories, output_file)

        display_success(f"Exported {len(trajectories)} trajectories to {output_file}")

    except Exception as e:
        logger.exception("export_trajectories_failed")
        display_error(f"Failed to export trajectories: {e}")
        raise typer.Exit(code=1)


def _export_jsonl(trajectories: list, output_file: Path) -> None:
    """Export trajectories in ShareGPT JSONL format.

    Args:
        trajectories: List of TrajectoryRecord objects
        output_file: Output file path
    """
    import json

    lines = []
    for traj in trajectories:
        # Convert to ShareGPT conversation format
        conversations = []

        # System message
        conversations.append(
            {
                "from": "system",
                "value": "You are a research assistant that helps find and "
                "synthesize information from academic papers.",
            }
        )

        # User question
        conversations.append({"from": "human", "value": traj.question})

        # Build assistant response from trajectory
        response_parts = []
        for turn in traj.turns:
            response_parts.append(f"Thought: {turn.reasoning}")
            response_parts.append(
                f"Action: {turn.action.tool.value}({turn.action.arguments})"
            )
            # Skip observation in training data (too verbose)

        if traj.answer:
            response_parts.append(f"\nFinal Answer: {traj.answer}")

        conversations.append({"from": "gpt", "value": "\n".join(response_parts)})

        lines.append(
            json.dumps(
                {
                    "id": traj.trajectory_id,
                    "conversations": conversations,
                    "quality_score": traj.quality_score,
                }
            )
        )

    output_file.write_text("\n".join(lines))


def _export_json(trajectories: list, output_file: Path) -> None:
    """Export trajectories as JSON array.

    Args:
        trajectories: List of TrajectoryRecord objects
        output_file: Output file path
    """
    import json

    data = []
    for traj in trajectories:
        data.append(
            {
                "trajectory_id": traj.trajectory_id,
                "question": traj.question,
                "answer": traj.answer,
                "turns": [
                    {
                        "turn_number": t.turn_number,
                        "reasoning": t.reasoning,
                        "action": {
                            "tool": t.action.tool.value,
                            "arguments": t.action.arguments,
                            "timestamp": t.action.timestamp.isoformat(),
                        },
                        "observation": t.observation,
                        "observation_tokens": t.observation_tokens,
                    }
                    for t in traj.turns
                ],
                "quality_score": traj.quality_score,
                "papers_opened": traj.papers_opened,
                "unique_searches": traj.unique_searches,
                "find_operations": traj.find_operations,
                "context_length_tokens": traj.context_length_tokens,
                "created_at": traj.created_at.isoformat(),
            }
        )

    output_file.write_text(json.dumps(data, indent=2))


def _export_csv(trajectories: list, output_file: Path) -> None:
    """Export trajectory statistics as CSV.

    Args:
        trajectories: List of TrajectoryRecord objects
        output_file: Output file path
    """
    import csv

    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        writer.writerow(
            [
                "trajectory_id",
                "question",
                "has_answer",
                "quality_score",
                "turn_count",
                "papers_opened",
                "unique_searches",
                "find_operations",
                "context_tokens",
                "created_at",
            ]
        )

        # Data rows
        for traj in trajectories:
            writer.writerow(
                [
                    traj.trajectory_id,
                    traj.question[:100],  # Truncate for CSV
                    "yes" if traj.answer else "no",
                    f"{traj.quality_score:.3f}",
                    len(traj.turns),
                    traj.papers_opened,
                    traj.unique_searches,
                    traj.find_operations,
                    traj.context_length_tokens,
                    traj.created_at.isoformat(),
                ]
            )


@trajectories_app.command("stats")
@handle_errors
def stats_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
) -> None:
    """Show trajectory storage statistics.

    Displays summary statistics including total trajectories,
    quality distribution, and storage size.

    Examples:
        arisp trajectories stats
    """
    storage_dir = _get_storage_dir(config_path)

    if not storage_dir.exists():
        display_warning(f"Trajectory storage not found: {storage_dir}")
        display_info("No trajectories have been recorded yet")
        return

    try:
        collector = TrajectoryCollector(storage_dir=storage_dir)

        # Load all trajectories (no filter)
        all_trajectories = collector.filter_quality(
            min_turns=0,
            require_answer=False,
            min_quality_score=0.0,
        )

        if not all_trajectories:
            display_info("No trajectories found")
            return

        # Compute statistics
        total = len(all_trajectories)
        with_answer = sum(1 for t in all_trajectories if t.answer)
        avg_quality = sum(t.quality_score for t in all_trajectories) / total
        avg_turns = sum(len(t.turns) for t in all_trajectories) / total
        total_tokens = sum(t.context_length_tokens for t in all_trajectories)

        # Quality distribution
        high_quality = sum(1 for t in all_trajectories if t.quality_score >= 0.7)
        medium_quality = sum(
            1 for t in all_trajectories if 0.4 <= t.quality_score < 0.7
        )
        low_quality = sum(1 for t in all_trajectories if t.quality_score < 0.4)

        # Storage size
        storage_size = sum(f.stat().st_size for f in storage_dir.glob("*.json"))
        storage_size_mb = storage_size / (1024 * 1024)

        # Display statistics
        display_info("\n📊 Trajectory Storage Statistics")
        display_info("=" * 50)

        typer.echo(f"\n  Total trajectories: {total}")
        typer.echo(f"  With answers: {with_answer} ({with_answer/total:.0%})")
        typer.echo(f"  Without answers: {total - with_answer}")

        typer.echo(f"\n  Average quality score: {avg_quality:.2f}")
        typer.echo(f"  Average turns: {avg_turns:.1f}")
        typer.echo(f"  Total tokens processed: {total_tokens:,}")

        typer.echo("\n  Quality distribution:")
        typer.echo(f"    High (≥0.7): {high_quality} ({high_quality/total:.0%})")
        typer.echo(
            f"    Medium (0.4-0.7): {medium_quality} ({medium_quality/total:.0%})"
        )
        typer.echo(f"    Low (<0.4): {low_quality} ({low_quality/total:.0%})")

        typer.echo(f"\n  Storage directory: {storage_dir}")
        typer.echo(f"  Storage size: {storage_size_mb:.2f} MB")

        # Oldest and newest
        sorted_by_date = sorted(all_trajectories, key=lambda t: t.created_at)
        oldest = sorted_by_date[0].created_at.strftime("%Y-%m-%d %H:%M")
        newest = sorted_by_date[-1].created_at.strftime("%Y-%m-%d %H:%M")
        typer.echo(f"\n  Oldest: {oldest}")
        typer.echo(f"  Newest: {newest}")

        display_info("\n" + "=" * 50)

    except Exception as e:
        logger.exception("trajectory_stats_failed")
        display_error(f"Failed to get trajectory stats: {e}")
        raise typer.Exit(code=1)


@trajectories_app.command("clear")
@handle_errors
def clear_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
    older_than_days: Optional[int] = typer.Option(
        None,
        "--older-than",
        help="Only clear trajectories older than N days",
    ),
) -> None:
    """Clear recorded trajectories.

    Removes trajectory files from storage. Use with caution.

    Examples:
        arisp trajectories clear --force
        arisp trajectories clear --older-than 30
    """
    storage_dir = _get_storage_dir(config_path)

    if not storage_dir.exists():
        display_info("No trajectory storage found")
        return

    # Count files
    files = list(storage_dir.glob("*.json"))
    if not files:
        display_info("No trajectory files to clear")
        return

    # Filter by age if specified
    if older_than_days is not None:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        old_files = []
        for f in files:
            # Get file modification time
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
            if mtime < cutoff:
                old_files.append(f)
        files = old_files

        if not files:
            display_info(f"No trajectories older than {older_than_days} days")
            return

    # Confirm
    if not force:
        display_warning(f"This will delete {len(files)} trajectory file(s)")
        confirm = typer.confirm("Are you sure you want to continue?")
        if not confirm:
            display_info("Aborted")
            return

    # Delete files
    deleted = 0
    for f in files:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            display_warning(f"Failed to delete {f.name}: {e}")

    display_success(f"Cleared {deleted} trajectory file(s)")
