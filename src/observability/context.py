"""Correlation ID context management for request tracing.

Provides ContextVar-based storage for correlation IDs that propagate
automatically across async boundaries and thread-local storage.

Usage:
    from src.observability.context import (
        set_correlation_id,
        get_correlation_id,
        correlation_id_context,
    )

    # At request boundary (CLI command, scheduled job, etc.)
    corr_id = set_correlation_id()  # Generates UUID if not provided

    # Or with explicit ID
    set_correlation_id("my-request-123")

    # Retrieve anywhere in the call stack
    current_id = get_correlation_id()

    # Use context manager for scoped correlation IDs
    with correlation_id_context("run-456"):
        # All code here will use "run-456" as correlation ID
        process_papers()
    # Previous correlation ID is restored after context exits
"""

import uuid
from contextvars import ContextVar, Token
from contextlib import contextmanager
from typing import Optional, Generator

# ContextVar provides async-safe, thread-local-like storage
# Default value is None (no correlation ID set)
_correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(corr_id: Optional[str] = None) -> str:
    """Set the correlation ID for the current context.

    If no ID is provided, generates a new UUID v4.

    Args:
        corr_id: Optional correlation ID. If None, generates UUID.

    Returns:
        The correlation ID that was set (generated or provided).

    Example:
        # Generate new ID
        new_id = set_correlation_id()

        # Use explicit ID
        set_correlation_id("run-20250203-001")
    """
    if corr_id is None:
        corr_id = str(uuid.uuid4())

    _correlation_id_var.set(corr_id)
    return corr_id


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID.

    Returns:
        Current correlation ID or None if not set.

    Example:
        corr_id = get_correlation_id()
        if corr_id:
            logger.info("request_started", correlation_id=corr_id)
    """
    return _correlation_id_var.get()


def clear_correlation_id() -> None:
    """Clear the current correlation ID.

    Resets to default (None). Use at request boundaries to prevent
    correlation ID leakage between unrelated requests.

    Example:
        try:
            set_correlation_id()
            process_request()
        finally:
            clear_correlation_id()
    """
    _correlation_id_var.set(None)


@contextmanager
def correlation_id_context(
    corr_id: Optional[str] = None,
) -> Generator[str, None, None]:
    """Context manager for scoped correlation IDs.

    Sets correlation ID on entry and restores previous value on exit.
    Useful for nested operations that need their own correlation IDs
    while preserving parent context.

    Args:
        corr_id: Optional correlation ID. If None, generates UUID.

    Yields:
        The correlation ID being used in this context.

    Example:
        # Nested contexts
        with correlation_id_context("parent-run"):
            process_batch()

            for item in items:
                with correlation_id_context(f"item-{item.id}"):
                    process_item(item)
                # "parent-run" is restored here

        # Back to no correlation ID
    """
    # Save current token for restoration
    previous_token: Token[Optional[str]] = _correlation_id_var.set(None)

    # Reset to saved value and set new one
    _correlation_id_var.reset(previous_token)

    # Generate or use provided ID
    if corr_id is None:
        corr_id = str(uuid.uuid4())

    token = _correlation_id_var.set(corr_id)

    try:
        yield corr_id
    finally:
        # Restore previous value
        _correlation_id_var.reset(token)


def get_or_create_correlation_id() -> str:
    """Get existing correlation ID or create a new one.

    Convenience function for ensuring a correlation ID exists.
    If one is already set, returns it. Otherwise, generates and sets a new one.

    Returns:
        The current or newly created correlation ID.

    Example:
        # Ensure correlation ID exists
        corr_id = get_or_create_correlation_id()
        # Now safe to use corr_id
    """
    current = get_correlation_id()
    if current is not None:
        return current
    return set_correlation_id()
