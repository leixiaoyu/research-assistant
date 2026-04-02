"""CLI commands for Phase 7.3 Human Feedback Loop.

This module provides CLI commands for collecting, viewing,
and managing paper feedback.
"""

import asyncio
from pathlib import Path
from typing import List, Optional

import typer

from src.models.feedback import FeedbackRating, FeedbackReason

app = typer.Typer(
    name="feedback",
    help="Manage paper feedback for personalized recommendations.",
)


def _get_feedback_service():
    """Get or create feedback service instance."""
    from src.services.feedback.feedback_service import FeedbackService
    from src.services.feedback.storage import FeedbackStorage

    storage = FeedbackStorage()
    return FeedbackService(storage)


def _get_embedding_service():
    """Get or create embedding service instance."""
    from src.services.embeddings.embedding_service import EmbeddingService

    return EmbeddingService()


def _get_similarity_searcher():
    """Get or create similarity searcher instance."""
    from src.services.embeddings.similarity_searcher import SimilaritySearcher

    embedding_service = _get_embedding_service()
    return SimilaritySearcher(embedding_service)


@app.command()
def rate(
    paper_id: str = typer.Argument(..., help="Paper ID to rate"),
    rating: str = typer.Argument(
        ...,
        help="Rating: 'up', 'down', or 'neutral'",
    ),
    reasons: Optional[List[str]] = typer.Option(
        None,
        "--reason",
        "-r",
        help="Reasons for rating (methodology, findings, applications, etc.)",
    ),
    comment: Optional[str] = typer.Option(
        None,
        "--comment",
        "-c",
        help="Free-text comment",
    ),
    topic: Optional[str] = typer.Option(
        None,
        "--topic",
        "-t",
        help="Topic context for the feedback",
    ),
) -> None:
    """Rate a paper with thumbs up, down, or neutral."""
    # Map string to enum
    rating_map = {
        "up": FeedbackRating.THUMBS_UP,
        "down": FeedbackRating.THUMBS_DOWN,
        "neutral": FeedbackRating.NEUTRAL,
        "thumbs_up": FeedbackRating.THUMBS_UP,
        "thumbs_down": FeedbackRating.THUMBS_DOWN,
    }

    if rating.lower() not in rating_map:
        typer.echo(f"Invalid rating: {rating}. Use 'up', 'down', or 'neutral'.")
        raise typer.Exit(1)

    feedback_rating = rating_map[rating.lower()]

    # Parse reasons
    feedback_reasons: List[FeedbackReason] = []
    if reasons:
        reason_map = {
            "methodology": FeedbackReason.METHODOLOGY,
            "findings": FeedbackReason.FINDINGS,
            "applications": FeedbackReason.APPLICATIONS,
            "writing_quality": FeedbackReason.WRITING_QUALITY,
            "relevance": FeedbackReason.RELEVANCE,
            "novelty": FeedbackReason.NOVELTY,
        }
        for r in reasons:
            if r.lower() in reason_map:
                feedback_reasons.append(reason_map[r.lower()])
            else:
                typer.echo(f"Warning: Unknown reason '{r}', ignoring.")

    service = _get_feedback_service()

    async def submit():
        return await service.submit_feedback(
            paper_id=paper_id,
            rating=feedback_rating,
            reasons=feedback_reasons,
            free_text=comment,
            topic_slug=topic,
        )

    try:
        entry = asyncio.run(submit())
        rating_emoji = {"thumbs_up": "👍", "thumbs_down": "👎", "neutral": "😐"}
        emoji = rating_emoji.get(entry.rating, "")
        typer.echo(f"{emoji} Feedback recorded for paper {paper_id}")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def interactive(
    topic: Optional[str] = typer.Option(
        None,
        "--topic",
        "-t",
        help="Topic to filter papers for rating",
    ),
    limit: int = typer.Option(
        10,
        "--limit",
        "-n",
        help="Maximum papers to rate in session",
    ),
) -> None:
    """Start interactive feedback session."""
    typer.echo("🔬 Interactive Feedback Session")
    typer.echo("=" * 40)
    typer.echo("Commands: [u]p, [d]own, [n]eutral, [s]kip, [q]uit")
    typer.echo("")

    # For now, show a placeholder message
    # Full implementation would integrate with registry to get papers
    typer.echo(
        "Note: Full interactive mode requires papers in registry.\n"
        "Use 'arisp feedback rate <paper_id> <rating>' to rate individual papers."
    )

    stats = {"up": 0, "down": 0, "neutral": 0, "skipped": 0}

    typer.echo(f"\nSession complete: {sum(stats.values())} papers processed")
    typer.echo(f"  👍 Thumbs up: {stats['up']}")
    typer.echo(f"  👎 Thumbs down: {stats['down']}")
    typer.echo(f"  😐 Neutral: {stats['neutral']}")
    typer.echo(f"  ⏭️  Skipped: {stats['skipped']}")


@app.command()
def similar(
    paper_id: str = typer.Argument(..., help="Paper ID to find similar papers for"),
    top_k: int = typer.Option(
        10,
        "--top",
        "-k",
        help="Number of similar papers to show",
    ),
    reason: Optional[str] = typer.Option(
        None,
        "--reason",
        "-r",
        help="Why you like this paper (for better matching)",
    ),
) -> None:
    """Find papers similar to a given paper."""
    typer.echo(f"🔍 Finding papers similar to {paper_id}...")

    searcher = _get_similarity_searcher()

    # Create minimal paper object
    class MinimalPaper:
        def __init__(self, paper_id: str):
            self.paper_id = paper_id
            self.title = paper_id
            self.abstract = None

    paper = MinimalPaper(paper_id)

    async def search():
        return await searcher.find_similar(
            paper=paper,
            top_k=top_k,
            include_reasons=reason,
        )

    try:
        results = asyncio.run(search())

        if not results:
            typer.echo("No similar papers found. Is the FAISS index built?")
            typer.echo("Hint: Build index with sufficient papers first.")
            return

        typer.echo(f"\n📚 Top {len(results)} Similar Papers:\n")

        for i, result in enumerate(results, 1):
            status = "📌 " if result.previously_discovered else "🆕 "
            score_pct = result.similarity_score * 100
            typer.echo(f"{i}. {status}{result.title}")
            typer.echo(f"   ID: {result.paper_id}")
            typer.echo(f"   Similarity: {score_pct:.1f}%")
            if result.matching_aspects:
                aspects = ", ".join(result.matching_aspects[:3])
                typer.echo(f"   Aspects: {aspects}")
            typer.echo("")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def analytics(
    topic: Optional[str] = typer.Option(
        None,
        "--topic",
        "-t",
        help="Topic to analyze (all topics if not specified)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for report (prints to console if not specified)",
    ),
) -> None:
    """Show feedback analytics and insights."""
    service = _get_feedback_service()

    async def get_analytics():
        return await service.get_analytics(topic)

    try:
        analytics = asyncio.run(get_analytics())

        # Build report
        lines = [
            "📊 Feedback Analytics Report",
            "=" * 40,
            "",
            f"Total Ratings: {analytics.total_ratings}",
            "",
            "Rating Distribution:",
            f"  👍 Thumbs Up: {analytics.rating_distribution.get('thumbs_up', 0)}",
            f"  👎 Thumbs Down: {analytics.rating_distribution.get('thumbs_down', 0)}",
            f"  😐 Neutral: {analytics.rating_distribution.get('neutral', 0)}",
            "",
        ]

        if analytics.top_reasons:
            lines.append("Top Reasons:")
            for reason, count in analytics.top_reasons[:5]:
                lines.append(f"  • {reason}: {count}")
            lines.append("")

        if analytics.trending_themes:
            lines.append("Trending Themes:")
            for theme in analytics.trending_themes[:5]:
                lines.append(f"  🔥 {theme}")
            lines.append("")

        if analytics.topic_breakdown:
            lines.append("By Topic:")
            for slug, topic_stats in analytics.topic_breakdown.items():
                lines.append(f"  {slug}:")
                lines.append(f"    Total: {topic_stats.total}")
                lines.append(
                    f"    👍 {topic_stats.thumbs_up} / "
                    f"👎 {topic_stats.thumbs_down} / "
                    f"😐 {topic_stats.neutral}"
                )
            lines.append("")

        report = "\n".join(lines)

        if output:
            output.write_text(report, encoding="utf-8")
            typer.echo(f"Report saved to {output}")
        else:
            typer.echo(report)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def export(
    format: str = typer.Option(
        "json",
        "--format",
        "-f",
        help="Export format: json or csv",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path",
    ),
) -> None:
    """Export feedback data to JSON or CSV."""
    if format.lower() not in ("json", "csv"):
        typer.echo(f"Invalid format: {format}. Use 'json' or 'csv'.")
        raise typer.Exit(1)

    service = _get_feedback_service()

    async def do_export():
        output_str = str(output) if output else None
        return await service.export_feedback(format.lower(), output_str)

    try:
        result = asyncio.run(do_export())

        if output:
            typer.echo(f"✅ Exported feedback to {output}")
        else:
            typer.echo(result)

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def clear(
    confirm: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompt",
    ),
) -> None:
    """Clear all feedback data."""
    if not confirm:
        confirm = typer.confirm("⚠️  This will delete ALL feedback data. Are you sure?")

    if not confirm:
        typer.echo("Cancelled.")
        return

    service = _get_feedback_service()

    async def do_clear():
        await service.storage.clear()

    asyncio.run(do_clear())
    typer.echo("✅ All feedback data cleared.")


@app.command()
def show(
    paper_id: str = typer.Argument(..., help="Paper ID to show feedback for"),
) -> None:
    """Show feedback for a specific paper."""
    service = _get_feedback_service()

    async def get_feedback():
        return await service.get_feedback_for_paper(paper_id)

    try:
        entry = asyncio.run(get_feedback())

        if entry is None:
            typer.echo(f"No feedback found for paper {paper_id}")
            return

        rating_emoji = {"thumbs_up": "👍", "thumbs_down": "👎", "neutral": "😐"}
        emoji = rating_emoji.get(entry.rating, "")

        typer.echo(f"\n📄 Feedback for {paper_id}")
        typer.echo("=" * 40)
        typer.echo(f"Rating: {emoji} {entry.rating}")
        typer.echo(f"Topic: {entry.topic_slug or 'N/A'}")

        if entry.reasons:
            reasons_str = ", ".join(entry.reasons)
            typer.echo(f"Reasons: {reasons_str}")

        if entry.free_text:
            typer.echo(f"Comment: {entry.free_text}")

        typer.echo(f"Timestamp: {entry.timestamp.isoformat()}")

    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)


# Register with main CLI if imported
def register_commands(main_app: typer.Typer) -> None:
    """Register feedback commands with the main CLI app."""
    main_app.add_typer(app, name="feedback")
