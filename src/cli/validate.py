"""Validate command for configuration files.

Validates configuration file syntax and semantics.
"""

from pathlib import Path

import typer

from src.services.config_manager import ConfigManager
from src.cli.utils import handle_errors, display_success, display_error


@handle_errors
def validate_command(
    config_path: Path = typer.Argument(..., help="Config file to validate"),
):
    """Validate configuration file syntax and semantics."""
    try:
        manager = ConfigManager(config_path=str(config_path))
        manager.load_config()
        display_success("Configuration is valid! ✅")
    except Exception as e:
        display_error(f"Validation failed: {e}")
        raise typer.Exit(code=1)
