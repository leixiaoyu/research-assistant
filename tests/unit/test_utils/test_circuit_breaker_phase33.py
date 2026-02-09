"""Additional unit tests for Phase 3.3 Circuit Breaker coverage.

Tests for edge cases and additional scenarios.
"""

import pytest
import time

from src.utils.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerRegistry,
)
from src.models.llm import CircuitBreakerConfig
from src.utils.exceptions import ProviderUnavailableError


@pytest.fixture
def circuit_config():
    """Create test circuit breaker configuration."""
    return CircuitBreakerConfig(
        enabled=True,
        failure_threshold=3,
        success_threshold=2,
        cooldown_seconds=0.05,  # Short for tests
    )


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clean up registry singleton before and after each test."""
    CircuitBreakerRegistry.clear_instance()
    yield
    CircuitBreakerRegistry.clear_instance()


class TestCircuitBreakerEdgeCases:
    """Edge case tests for circuit breaker."""

    def test_should_transition_with_no_failure_time(self, circuit_config):
        """Test transition check when last_failure_time is None."""
        cb = CircuitBreaker("test", circuit_config)
        # Force state to OPEN without setting failure time
        cb._state = CircuitState.OPEN
        cb._last_failure_time = None

        # Should transition to HALF_OPEN since no cooldown to wait
        assert cb._should_transition_to_half_open() is True

    def test_half_open_failure_reopens(self, circuit_config):
        """Test that failure in HALF_OPEN state reopens circuit."""
        cb = CircuitBreaker("test", circuit_config)

        # Get to HALF_OPEN state
        for _ in range(3):
            cb.record_failure()
        time.sleep(0.06)  # Wait for cooldown
        _ = cb.state  # Trigger auto-transition

        assert cb.state == CircuitState.HALF_OPEN

        # Single failure should reopen
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_get_stats_with_cooldown_remaining(self, circuit_config):
        """Test stats include cooldown_remaining when OPEN."""
        cb = CircuitBreaker("test", circuit_config)

        for _ in range(3):
            cb.record_failure()

        stats = cb.get_stats()

        assert stats["state"] == "open"
        assert stats["cooldown_remaining"] > 0
        assert stats["cooldown_remaining"] <= circuit_config.cooldown_seconds

    def test_allow_request_triggers_auto_transition(self, circuit_config):
        """Test allow_request triggers OPEN to HALF_OPEN transition."""
        cb = CircuitBreaker("test", circuit_config)

        for _ in range(3):
            cb.record_failure()

        assert cb.allow_request() is False  # Still in cooldown

        time.sleep(0.06)  # Wait for cooldown

        assert cb.allow_request() is True  # Transitioned to HALF_OPEN

    def test_success_resets_failure_counter(self, circuit_config):
        """Test success resets consecutive_failures to 0."""
        cb = CircuitBreaker("test", circuit_config)

        cb.record_failure()
        cb.record_failure()
        assert cb.consecutive_failures == 2

        cb.record_success()
        assert cb.consecutive_failures == 0
        assert cb.consecutive_successes == 1


class TestCircuitBreakerRegistryExtended:
    """Extended tests for CircuitBreakerRegistry."""

    def test_get_existing_breaker(self, circuit_config):
        """Test get returns existing breaker."""
        registry = CircuitBreakerRegistry()
        created = registry.get_or_create("provider-a", circuit_config)
        fetched = registry.get("provider-a")

        assert fetched is created

    def test_remove_non_existing(self):
        """Test remove returns False for non-existing breaker."""
        registry = CircuitBreakerRegistry()
        result = registry.remove("non-existing")

        assert result is False

    def test_get_all_stats(self, circuit_config):
        """Test get_all_stats returns stats for all breakers."""
        registry = CircuitBreakerRegistry()
        registry.get_or_create("provider-a", circuit_config)
        registry.get_or_create("provider-b", circuit_config)

        all_stats = registry.get_all_stats()

        assert "provider-a" in all_stats
        assert "provider-b" in all_stats
        assert all_stats["provider-a"]["name"] == "provider-a"
        assert all_stats["provider-b"]["name"] == "provider-b"

    def test_reset_all_clears_failures(self, circuit_config):
        """Test reset_all clears failures on all breakers."""
        registry = CircuitBreakerRegistry()
        cb_a = registry.get_or_create("provider-a", circuit_config)
        cb_b = registry.get_or_create("provider-b", circuit_config)

        # Add failures to both
        for _ in range(3):
            cb_a.record_failure()
            cb_b.record_failure()

        assert cb_a.state == CircuitState.OPEN
        assert cb_b.state == CircuitState.OPEN

        registry.reset_all()

        assert cb_a.state == CircuitState.CLOSED
        assert cb_b.state == CircuitState.CLOSED
        assert cb_a.consecutive_failures == 0
        assert cb_b.consecutive_failures == 0


class TestProviderUnavailableError:
    """Tests for ProviderUnavailableError integration."""

    def test_check_or_raise_when_open(self, circuit_config):
        """Test check_or_raise raises when circuit is OPEN."""
        cb = CircuitBreaker("test-provider", circuit_config)

        for _ in range(3):
            cb.record_failure()

        with pytest.raises(ProviderUnavailableError, match="test-provider"):
            cb.check_or_raise()

    def test_check_or_raise_when_half_open(self, circuit_config):
        """Test check_or_raise allows when HALF_OPEN."""
        cb = CircuitBreaker("test", circuit_config)

        for _ in range(3):
            cb.record_failure()
        time.sleep(0.06)
        _ = cb.state  # Trigger auto-transition

        # Should not raise in HALF_OPEN
        cb.check_or_raise()  # No exception
