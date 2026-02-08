"""Unit tests for Phase 3.3 Circuit Breaker Utility"""

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
        cooldown_seconds=0.1,
    )


@pytest.fixture
def circuit_breaker(circuit_config):
    """Create circuit breaker instance."""
    return CircuitBreaker("test-provider", circuit_config)


@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clean up registry singleton before and after each test."""
    CircuitBreakerRegistry.clear_instance()
    yield
    CircuitBreakerRegistry.clear_instance()


class TestCircuitBreakerInit:
    """Tests for CircuitBreaker initialization."""

    def test_initial_state_is_closed(self, circuit_breaker):
        """Test initial state is CLOSED."""
        assert circuit_breaker.state == CircuitState.CLOSED

    def test_initial_counters_are_zero(self, circuit_breaker):
        """Test initial counters are zero."""
        assert circuit_breaker.consecutive_failures == 0
        assert circuit_breaker.consecutive_successes == 0


class TestStateTransitions:
    """Tests for circuit state transitions."""

    def test_closed_to_open_after_threshold(self, circuit_breaker):
        """Test CLOSED -> OPEN after failure threshold."""
        for _ in range(3):
            circuit_breaker.record_failure()
        assert circuit_breaker.state == CircuitState.OPEN

    def test_open_to_half_open_after_cooldown(self, circuit_config):
        """Test OPEN -> HALF_OPEN after cooldown."""
        cb = CircuitBreaker("test", circuit_config)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_after_success(self, circuit_config):
        """Test HALF_OPEN -> CLOSED after successes."""
        cb = CircuitBreaker("test", circuit_config)
        for _ in range(3):
            cb.record_failure()
        time.sleep(0.15)
        # Access state to trigger auto-transition to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestAllowRequest:
    """Tests for allow_request method."""

    def test_allows_when_closed(self, circuit_breaker):
        """Test requests allowed when CLOSED."""
        assert circuit_breaker.allow_request() is True

    def test_blocks_when_open(self, circuit_breaker):
        """Test requests blocked when OPEN."""
        for _ in range(3):
            circuit_breaker.record_failure()
        assert circuit_breaker.allow_request() is False


class TestCheckOrRaise:
    """Tests for check_or_raise method."""

    def test_does_not_raise_when_closed(self, circuit_breaker):
        """Test no exception when CLOSED."""
        circuit_breaker.check_or_raise()

    def test_raises_when_open(self, circuit_breaker):
        """Test raises ProviderUnavailableError when OPEN."""
        for _ in range(3):
            circuit_breaker.record_failure()
        with pytest.raises(ProviderUnavailableError, match="is OPEN"):
            circuit_breaker.check_or_raise()


class TestReset:
    """Tests for reset method."""

    def test_reset_closes_circuit(self, circuit_breaker):
        """Test reset closes the circuit."""
        for _ in range(3):
            circuit_breaker.record_failure()
        circuit_breaker.reset()
        assert circuit_breaker.state == CircuitState.CLOSED


class TestGetStats:
    """Tests for get_stats method."""

    def test_get_stats_initial(self, circuit_breaker):
        """Test stats for fresh circuit breaker."""
        stats = circuit_breaker.get_stats()
        assert stats["name"] == "test-provider"
        assert stats["state"] == "closed"


class TestCircuitBreakerRegistry:
    """Tests for CircuitBreakerRegistry singleton."""

    def test_is_singleton(self):
        """Test registry is singleton."""
        reg1 = CircuitBreakerRegistry()
        reg2 = CircuitBreakerRegistry()
        assert reg1 is reg2

    def test_get_or_create(self, circuit_config):
        """Test get_or_create creates new breaker."""
        registry = CircuitBreakerRegistry()
        cb = registry.get_or_create("provider-a", circuit_config)
        assert cb.name == "provider-a"

    def test_get_non_existing(self):
        """Test get returns None for non-existing."""
        registry = CircuitBreakerRegistry()
        assert registry.get("non-existing") is None

    def test_remove_existing(self, circuit_config):
        """Test remove returns True for existing breaker."""
        registry = CircuitBreakerRegistry()
        registry.get_or_create("provider-a", circuit_config)
        assert registry.remove("provider-a") is True

    def test_reset_all(self, circuit_config):
        """Test reset_all resets all breakers."""
        registry = CircuitBreakerRegistry()
        cb = registry.get_or_create("provider-a", circuit_config)
        for _ in range(3):
            cb.record_failure()
        registry.reset_all()
        assert cb.state == CircuitState.CLOSED
