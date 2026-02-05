"""Tests for correlation ID context management."""

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.observability.context import (
    set_correlation_id,
    get_correlation_id,
    clear_correlation_id,
    correlation_id_context,
    get_or_create_correlation_id,
)


class TestSetCorrelationId:
    """Tests for set_correlation_id function."""

    def test_generates_uuid_when_no_id_provided(self):
        """Should generate a valid UUID when no ID is provided."""
        clear_correlation_id()

        result = set_correlation_id()

        # Should be a valid UUID
        parsed = uuid.UUID(result)
        assert str(parsed) == result

    def test_uses_provided_id(self):
        """Should use the provided ID instead of generating."""
        clear_correlation_id()
        custom_id = "my-custom-correlation-id"

        result = set_correlation_id(custom_id)

        assert result == custom_id
        assert get_correlation_id() == custom_id

    def test_overwrites_existing_id(self):
        """Should overwrite existing correlation ID."""
        set_correlation_id("first-id")
        set_correlation_id("second-id")

        assert get_correlation_id() == "second-id"

    def test_returns_the_set_id(self):
        """Should return the ID that was set."""
        clear_correlation_id()

        result = set_correlation_id("test-id")

        assert result == "test-id"


class TestGetCorrelationId:
    """Tests for get_correlation_id function."""

    def test_returns_none_when_not_set(self):
        """Should return None when no correlation ID is set."""
        clear_correlation_id()

        result = get_correlation_id()

        assert result is None

    def test_returns_current_id(self):
        """Should return the current correlation ID."""
        set_correlation_id("current-id")

        result = get_correlation_id()

        assert result == "current-id"


class TestClearCorrelationId:
    """Tests for clear_correlation_id function."""

    def test_clears_existing_id(self):
        """Should clear the existing correlation ID."""
        set_correlation_id("to-clear")

        clear_correlation_id()

        assert get_correlation_id() is None

    def test_safe_to_call_when_not_set(self):
        """Should be safe to call when no ID is set."""
        clear_correlation_id()

        # Should not raise
        clear_correlation_id()

        assert get_correlation_id() is None


class TestCorrelationIdContext:
    """Tests for correlation_id_context context manager."""

    def test_sets_id_in_context(self):
        """Should set correlation ID within context."""
        clear_correlation_id()

        with correlation_id_context("context-id"):
            assert get_correlation_id() == "context-id"

    def test_restores_previous_id_on_exit(self):
        """Should restore previous ID when context exits."""
        set_correlation_id("original-id")

        with correlation_id_context("temporary-id"):
            assert get_correlation_id() == "temporary-id"

        assert get_correlation_id() == "original-id"

    def test_restores_none_when_no_previous(self):
        """Should restore to None when no previous ID."""
        clear_correlation_id()

        with correlation_id_context("temp-id"):
            pass

        assert get_correlation_id() is None

    def test_generates_uuid_when_no_id_provided(self):
        """Should generate UUID when no ID provided to context."""
        clear_correlation_id()

        with correlation_id_context() as ctx_id:
            # Should be a valid UUID
            parsed = uuid.UUID(ctx_id)
            assert str(parsed) == ctx_id
            assert get_correlation_id() == ctx_id

    def test_yields_the_correlation_id(self):
        """Should yield the correlation ID being used."""
        with correlation_id_context("yielded-id") as ctx_id:
            assert ctx_id == "yielded-id"

    def test_handles_nested_contexts(self):
        """Should handle nested contexts correctly."""
        set_correlation_id("outer")

        with correlation_id_context("middle"):
            assert get_correlation_id() == "middle"

            with correlation_id_context("inner"):
                assert get_correlation_id() == "inner"

            assert get_correlation_id() == "middle"

        assert get_correlation_id() == "outer"

    def test_restores_on_exception(self):
        """Should restore previous ID even when exception raised."""
        set_correlation_id("before-exception")

        with pytest.raises(ValueError):
            with correlation_id_context("exception-context"):
                raise ValueError("test error")

        assert get_correlation_id() == "before-exception"


class TestGetOrCreateCorrelationId:
    """Tests for get_or_create_correlation_id function."""

    def test_returns_existing_id(self):
        """Should return existing ID if set."""
        set_correlation_id("existing-id")

        result = get_or_create_correlation_id()

        assert result == "existing-id"

    def test_creates_new_id_when_none(self):
        """Should create new ID when none exists."""
        clear_correlation_id()

        result = get_or_create_correlation_id()

        # Should be a valid UUID
        parsed = uuid.UUID(result)
        assert str(parsed) == result
        # Should persist the ID
        assert get_correlation_id() == result

    def test_subsequent_calls_return_same_id(self):
        """Should return same ID on subsequent calls."""
        clear_correlation_id()

        first = get_or_create_correlation_id()
        second = get_or_create_correlation_id()

        assert first == second


class TestAsyncIsolation:
    """Tests for async context isolation."""

    @pytest.mark.asyncio
    async def test_isolated_in_async_tasks(self):
        """Correlation ID should be isolated between async tasks."""

        async def set_and_get(task_id: str) -> tuple:
            set_correlation_id(f"task-{task_id}")
            await asyncio.sleep(0.01)  # Yield to other tasks
            return task_id, get_correlation_id()

        # Run multiple tasks concurrently
        results = await asyncio.gather(
            set_and_get("1"),
            set_and_get("2"),
            set_and_get("3"),
        )

        # Each task should have its own correlation ID
        for task_id, corr_id in results:
            assert corr_id == f"task-{task_id}"

    @pytest.mark.asyncio
    async def test_context_propagates_to_nested_coroutines(self):
        """Correlation ID should propagate to nested coroutines."""

        async def inner():
            return get_correlation_id()

        async def outer():
            set_correlation_id("outer-coroutine")
            return await inner()

        result = await outer()

        assert result == "outer-coroutine"


class TestThreadIsolation:
    """Tests for thread isolation."""

    def test_isolated_between_threads(self):
        """Correlation ID should be isolated between threads."""

        def set_and_get(thread_id: str) -> tuple:
            set_correlation_id(f"thread-{thread_id}")
            return thread_id, get_correlation_id()

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(set_and_get, str(i)) for i in range(3)]
            results = [f.result() for f in futures]

        # Each thread should have its own correlation ID
        for thread_id, corr_id in results:
            assert corr_id == f"thread-{thread_id}"
