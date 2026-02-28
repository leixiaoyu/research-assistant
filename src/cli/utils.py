"""Shared CLI utilities.

Provides common functionality for all CLI commands.
"""

import functools
from pathlib import Path
from typing import Callable, TypeVar

import structlog
import typer

from src.services.config_manager import ConfigManager, ConfigValidationError
from src.models.config import ResearchConfig
from src.utils.logging import configure_logging

# Configure structured logging
configure_logging()
logger = structlog.get_logger()

# Type variable for decorator
F = TypeVar("F", bound=Callable)


def load_config(config_path: Path) -> ResearchConfig:
    """Load and validate configuration.

    Args:
        config_path: Path to configuration file.

    Returns:
        Validated ResearchConfig.

    Raises:
        typer.Exit: If configuration is invalid.
    """
    config_manager = ConfigManager(config_path=str(config_path))
    try:
        return config_manager.load_config()
    except (FileNotFoundError, ConfigValidationError) as e:
        typer.secho(f"Configuration Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


def handle_errors(func: F) -> F:
    """Decorator for consistent error handling.

    Catches exceptions and displays user-friendly error messages.

    Args:
        func: Function to wrap.

    Returns:
        Wrapped function with error handling.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except Exception as e:
            logger.exception("command_failed")
            typer.secho(f"Error: {e}", fg=typer.colors.RED)
            raise typer.Exit(code=1)

    return wrapper  # type: ignore[return-value]


def display_success(message: str) -> None:
    """Display a success message.

    Args:
        message: Message to display.
    """
    typer.secho(message, fg=typer.colors.GREEN)


def display_warning(message: str) -> None:
    """Display a warning message.

    Args:
        message: Message to display.
    """
    typer.secho(message, fg=typer.colors.YELLOW)


def display_error(message: str) -> None:
    """Display an error message.

    Args:
        message: Message to display.
    """
    typer.secho(message, fg=typer.colors.RED)


def display_info(message: str) -> None:
    """Display an info message.

    Args:
        message: Message to display.
    """
    typer.secho(message, fg=typer.colors.CYAN)


def is_phase2_enabled(config: ResearchConfig) -> bool:
    """Check if Phase 2 features are enabled based on config.

    Args:
        config: Research configuration.

    Returns:
        True if Phase 2 (PDF/LLM extraction) is enabled.
    """
    return (
        config.settings.pdf_settings is not None
        and config.settings.llm_settings is not None
        and config.settings.cost_limits is not None
    )
