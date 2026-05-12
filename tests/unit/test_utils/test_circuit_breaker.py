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

    def test_should_transition_with_no_failures(self, circuit_breaker):
        """Test _should_transition_to_half_open when no failures recorded."""
        # When no failures have been recorded, _last_failure_time is None
        # and _should_transition_to_half_open should return True
        assert circuit_breaker._should_transition_to_half_open() is True


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

    def test_get_stats_with_cooldown_remaining(self, circuit_config):
        """Test stats shows cooldown_remaining when OPEN."""
        cb = CircuitBreaker("test", circuit_config)
        for _ in range(3):
            cb.record_failure()
        stats = cb.get_stats()
        assert stats["state"] == "open"
        assert stats["cooldown_remaining"] > 0.0


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

    def test_remove_non_existing(self):
        """Test remove returns False for non-existing breaker."""
        registry = CircuitBreakerRegistry()
        assert registry.remove("non-existing") is False

    def test_get_all_stats(self, circuit_config):
        """Test get_all_stats returns stats for all breakers."""
        registry = CircuitBreakerRegistry()
        cb1 = registry.get_or_create("provider-a", circuit_config)
        cb2 = registry.get_or_create("provider-b", circuit_config)
        cb1.record_success()
        cb2.record_failure()

        stats = registry.get_all_stats()
        assert "provider-a" in stats
        assert "provider-b" in stats
        assert stats["provider-a"]["state"] == "closed"
        assert stats["provider-b"]["consecutive_failures"] == 1


class TestCircuitBreakerThresholds:
    """Tests for updated circuit breaker thresholds."""

    def test_default_failure_threshold_is_10(self):
        """Test default failure threshold is 10 (updated from 5)."""
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 10

    def test_default_cooldown_is_300(self):
        """Test default cooldown is 300 seconds (updated from 60)."""
        config = CircuitBreakerConfig()
        assert config.cooldown_seconds == 300.0

    def test_circuit_opens_after_10_failures(self):
        """Test circuit opens after 10 consecutive failures."""
        config = CircuitBreakerConfig()  # Uses new defaults
        cb = CircuitBreaker("test-provider", config)

        # Record 9 failures - should stay CLOSED
        for _ in range(9):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

        # 10th failure - should open
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_to_closed_after_success_threshold(self):
        """Test HALF_OPEN -> CLOSED requires success_threshold successes."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=3,  # Require 3 successes
            cooldown_seconds=0.1,
        )
        cb = CircuitBreaker("test", config)

        # Open the circuit
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for cooldown
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        # Record 2 successes - should stay HALF_OPEN
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN

        # 3rd success - should close
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_reopens_on_failure(self):
        """Test HALF_OPEN -> OPEN on any failure."""
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            cooldown_seconds=0.1,
        )
        cb = CircuitBreaker("test", config)

        # Open the circuit
        for _ in range(3):
            cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        # Any failure in HALF_OPEN should reopen
        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestForceOpen:
    """Phase 9.5 review fix #2: force_open() bypasses failure-threshold counting.

    Used by ``LLMService.ensure_health_checked`` so a probe-failed
    provider's circuit immediately fails-fast without waiting for N
    consecutive runtime failures to accumulate.
    """

    def test_force_open_transitions_closed_to_open_immediately(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            cooldown_seconds=60,
        )
        cb = CircuitBreaker("test", config)
        assert cb.state == CircuitState.CLOSED

        cb.force_open()

        assert cb.state == CircuitState.OPEN
        # Single force_open must trip even though only 1 failure happened.
        assert cb.allow_request() is False
        with pytest.raises(ProviderUnavailableError):
            cb.check_or_raise()

    def test_force_open_records_failure_in_stats(self):
        config = CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60)
        cb = CircuitBreaker("test", config)
        before = cb.get_stats()["total_failures"]

        cb.force_open()

        after = cb.get_stats()["total_failures"]
        assert after == before + 1, (
            "force_open must increment total_failures so operators do not "
            "see status=OPEN with consecutive_failures=0 in dashboards"
        )

    def test_force_open_respects_cooldown_and_eventually_half_opens(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=2,
            cooldown_seconds=0.1,
        )
        cb = CircuitBreaker("test", config)

        cb.force_open()
        assert cb.state == CircuitState.OPEN

        # The auto HALF_OPEN cooldown still applies — force_open is a
        # one-time push, not a permanent OPEN.
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_force_open_is_idempotent(self):
        config = CircuitBreakerConfig(failure_threshold=3, cooldown_seconds=60)
        cb = CircuitBreaker("test", config)

        cb.force_open()
        cb.force_open()
        cb.force_open()

        assert cb.state == CircuitState.OPEN
        # Counter accumulates but state never leaves OPEN.
        assert cb.get_stats()["total_failures"] == 3
