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
    python -m src.cli feedback rate <paper_id> <rating>
    python -m src.cli feedback similar <paper_id>
    python -m src.cli feedback analytics
    python -m src.cli research "What are the key techniques?"
    python -m src.cli research --question-file questions.txt
    python -m src.cli trajectories list
    python -m src.cli trajectories analyze
    python -m src.cli trajectories export -o data.jsonl
"""

import typer

from src.cli.run import run_command
from src.cli.validate import validate_command
from src.cli.catalog import catalog_app, catalog_command
from src.cli.schedule import schedule_app, schedule_command
from src.cli.health import health_command
from src.cli.monitor import monitor_app
from src.cli.citation import citation_app
from src.cli.synthesize import synthesize_command
from src.cli.feedback import app as feedback_app
from src.cli.research import research_app
from src.cli.trajectories import trajectories_app

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
app.add_typer(feedback_app, name="feedback")
app.add_typer(monitor_app, name="monitor")
app.add_typer(citation_app, name="citation")
app.add_typer(research_app, name="research")
app.add_typer(trajectories_app, name="trajectories")

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
    "feedback_app",
    "monitor_app",
    "research_app",
    "trajectories_app",
    "citation_app",
]
