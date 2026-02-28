"""ARISP CLI Package.

Provides command-line interface for the Automated Research Ingestion
& Synthesis Pipeline.

Usage:
    python -m src.cli run --config config/research_config.yaml
    python -m src.cli catalog show
    python -m src.cli schedule start
    python -m src.cli health
    python -m src.cli synthesize
    python -m src.cli validate config/research_config.yaml
"""

import typer

from src.cli.run import run_command
from src.cli.validate import validate_command
from src.cli.catalog import catalog_app, catalog_command
from src.cli.schedule import schedule_app, schedule_command
from src.cli.health import health_command
from src.cli.synthesize import synthesize_command

# Create main app
app = typer.Typer(help="ARISP: Automated Research Ingestion & Synthesis Pipeline")

# Register individual commands
app.command(name="run")(run_command)
app.command(name="validate")(validate_command)
app.command(name="health")(health_command)
app.command(name="synthesize")(synthesize_command)

# Register sub-applications
app.add_typer(catalog_app, name="catalog")
app.add_typer(schedule_app, name="schedule")

# Legacy command registrations for backward compatibility
# These allow the old invocation style: python -m src.cli catalog show
# as well as: python -m src.cli catalog <action>
app.command(name="catalog-legacy", hidden=True)(catalog_command)
app.command(name="schedule-legacy", hidden=True)(schedule_command)

# Re-export for backward compatibility
__all__ = [
    "app",
    "run_command",
    "validate_command",
    "catalog_app",
    "catalog_command",
    "schedule_app",
    "schedule_command",
    "health_command",
    "synthesize_command",
]
