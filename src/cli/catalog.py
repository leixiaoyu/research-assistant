"""Catalog commands for research catalog management.

Provides commands to view and manage the research catalog.
"""

from typing import Optional

import typer

from src.services.config_manager import ConfigManager
from src.cli.utils import handle_errors, display_warning, display_error

# Create catalog sub-app
catalog_app = typer.Typer(help="Manage research catalog")


@catalog_app.command(name="show")
@handle_errors
def catalog_show():
    """Display catalog contents."""
    manager = ConfigManager()
    cat = manager.load_catalog()

    typer.echo(f"Catalog contains {len(cat.topics)} topics:")
    for slug, t in cat.topics.items():
        typer.echo(f" - {slug}: {t.query} ({len(t.runs)} runs)")


@catalog_app.command(name="history")
@handle_errors
def catalog_history(
    topic: str = typer.Argument(..., help="Topic slug to show history for"),
):
    """Display run history for a topic."""
    manager = ConfigManager()
    cat = manager.load_catalog()

    if topic not in cat.topics:
        display_error(f"Topic '{topic}' not found")
        raise typer.Exit(code=1)

    t = cat.topics[topic]
    typer.echo(f"History for {t.query}:")
    for run in t.runs:
        typer.echo(
            f"  {run.date}: Found {run.papers_found} papers -> {run.output_file}"
        )


# Legacy command for backward compatibility
@handle_errors
def catalog_command(
    action: str = typer.Argument(..., help="Action: show, history"),
    topic: Optional[str] = typer.Option(None, help="Filter by topic slug"),
):
    """Manage research catalog (legacy interface).

    Use 'catalog show' or 'catalog history <topic>' instead.
    """
    manager = ConfigManager()
    cat = manager.load_catalog()

    if action == "show":
        typer.echo(f"Catalog contains {len(cat.topics)} topics:")
        for slug, t in cat.topics.items():
            typer.echo(f" - {slug}: {t.query} ({len(t.runs)} runs)")

    elif action == "history":
        if not topic:
            display_warning("Please provide --topic for history")
            return

        if topic not in cat.topics:
            display_error(f"Topic '{topic}' not found")
            return

        t = cat.topics[topic]
        typer.echo(f"History for {t.query}:")
        for run in t.runs:
            typer.echo(
                f"  {run.date}: Found {run.papers_found} papers -> {run.output_file}"
            )
