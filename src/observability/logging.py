"""Enhanced structured logging with correlation ID propagation.

Builds on existing structlog configuration to add:
- Automatic correlation ID injection into all log entries
- Service context (component name) for log filtering
- Configurable log levels per component

Usage:
    from src.observability.logging import get_logger, configure_logging

    # Configure at application startup
    configure_logging(level="INFO")

    # Get logger with component context
    logger = get_logger("llm_service")
    logger.info("extraction_started", paper_id="123")

    # Output includes correlation_id automatically:
    # {"event": "extraction_started", "paper_id": "123",
    #  "correlation_id": "abc-123", "component": "llm_service", ...}
"""

import logging
import sys
from typing import Any, Optional, Callable

import structlog
from structlog.typing import EventDict, WrappedLogger

from src.observability.context import get_correlation_id


def add_correlation_id_processor(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor that adds correlation_id to log entries.

    Retrieves current correlation ID from context and injects it
    into every log entry. If no correlation ID is set, uses "none".

    Args:
        logger: The wrapped logger instance
        method_name: The name of the logging method called
        event_dict: The event dictionary being logged

    Returns:
        Event dictionary with correlation_id added
    """
    corr_id = get_correlation_id()
    event_dict["correlation_id"] = corr_id if corr_id else "none"
    return event_dict


def add_service_context_processor(
    component: str,
) -> Callable[[WrappedLogger, str, EventDict], EventDict]:
    """Create a processor that adds component name to log entries.

    Args:
        component: The component/service name

    Returns:
        A structlog processor function
    """

    def processor(
        logger: WrappedLogger,
        method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        event_dict["component"] = component
        return event_dict

    return processor


def configure_logging(
    level: str = "INFO",
    json_output: bool = True,
    add_timestamp: bool = True,
) -> None:
    """Configure structured logging for the application.

    Sets up structlog with:
    - Correlation ID injection
    - JSON or console output format
    - Timestamp formatting
    - Log level filtering

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, output JSON. If False, use console format.
        add_timestamp: If True, add ISO timestamp to each log entry.

    Example:
        # Production (JSON for log aggregation)
        configure_logging(level="INFO", json_output=True)

        # Development (readable console output)
        configure_logging(level="DEBUG", json_output=False)
    """
    # Convert string level to logging constant
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Build processor chain
    processors: list[Any] = [
        # Add context vars (from structlog.contextvars)
        structlog.contextvars.merge_contextvars,
        # Add correlation ID
        add_correlation_id_processor,
        # Add log level
        structlog.processors.add_log_level,
        # Add caller info for DEBUG level
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ),
        # Add stack info for exceptions
        structlog.processors.StackInfoRenderer(),
        # Format exceptions
        structlog.processors.format_exc_info,
    ]

    # Add timestamp if requested
    if add_timestamp:
        processors.append(structlog.processors.TimeStamper(fmt="iso"))

    # Add final renderer based on output format
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(
    component: Optional[str] = None,
    **initial_context: Any,
) -> Any:
    """Get a structured logger with optional component context.

    Args:
        component: Optional component/service name to include in logs
        **initial_context: Additional context to bind to all log entries

    Returns:
        A bound structlog logger

    Example:
        # Basic usage
        logger = get_logger()
        logger.info("started")

        # With component
        logger = get_logger("pdf_service")
        logger.info("download_started", url="...")

        # With additional context
        logger = get_logger("worker", worker_id=3)
        logger.info("processing")  # Includes worker_id=3
    """
    logger = structlog.get_logger()

    # Bind component if provided
    if component:
        logger = logger.bind(component=component)

    # Bind any additional context
    if initial_context:
        logger = logger.bind(**initial_context)

    return logger


def bind_context(**context: Any) -> None:
    """Bind additional context to all subsequent log entries in current context.

    Uses structlog's contextvars to propagate context across async boundaries.

    Args:
        **context: Key-value pairs to bind

    Example:
        bind_context(run_id="run-123", topic="ml-papers")
        logger.info("processing")  # Includes run_id and topic
    """
    structlog.contextvars.bind_contextvars(**context)


def clear_context() -> None:
    """Clear all bound context from structlog contextvars.

    Call at request boundaries to prevent context leakage.

    Example:
        try:
            bind_context(request_id="req-123")
            handle_request()
        finally:
            clear_context()
    """
    structlog.contextvars.clear_contextvars()


class LoggerAdapter:
    """Adapter for using observability logger with standard logging interface.

    Useful for libraries that expect a standard logger but you want
    structured logging output.

    Example:
        adapter = LoggerAdapter("my_library")
        some_library.set_logger(adapter)
    """

    def __init__(self, component: str):
        """Initialize adapter with component name.

        Args:
            component: Component name for log entries
        """
        self._logger = get_logger(component)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at DEBUG level."""
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at INFO level."""
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at WARNING level."""
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at ERROR level."""
        self._logger.error(msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at CRITICAL level."""
        self._logger.critical(msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log at ERROR level with exception info."""
        self._logger.exception(msg, *args, **kwargs)
