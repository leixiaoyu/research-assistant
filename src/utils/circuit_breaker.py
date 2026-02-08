"""Phase 3.3: Circuit Breaker Utility

Implements the circuit breaker pattern to prevent cascading failures.

States:
- CLOSED: Normal operation, requests allowed
- OPEN: After failure threshold, requests blocked
- HALF_OPEN: After cooldown, testing with limited requests

State Transitions:
- CLOSED → OPEN: After failure_threshold consecutive failures
- OPEN → HALF_OPEN: After cooldown_seconds
- HALF_OPEN → CLOSED: After success_threshold consecutive successes
- HALF_OPEN → OPEN: On any failure
"""

import threading
import time
from enum import Enum
from typing import Optional, Dict

from src.models.llm import CircuitBreakerConfig
from src.utils.exceptions import ProviderUnavailableError


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker implementation.

    Tracks failures and successes to determine when to open/close the circuit.
    Automatically transitions from OPEN to HALF_OPEN after cooldown period.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig) -> None:
        """Initialize circuit breaker.

        Args:
            name: Identifier for this circuit breaker (e.g., provider name)
            config: Circuit breaker configuration
        """
        self.name = name
        self.config = config

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._total_successes = 0
        self._total_failures = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        """Get current state, auto-transitioning OPEN to HALF_OPEN after cooldown."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                # Check if cooldown has elapsed
                if self._should_transition_to_half_open():
                    self._state = CircuitState.HALF_OPEN
                    self._consecutive_successes = 0
            return self._state

    @property
    def consecutive_failures(self) -> int:
        """Get consecutive failure count."""
        with self._lock:
            return self._consecutive_failures

    @property
    def consecutive_successes(self) -> int:
        """Get consecutive success count."""
        with self._lock:
            return self._consecutive_successes

    def _should_transition_to_half_open(self) -> bool:
        """Check if cooldown has elapsed for OPEN → HALF_OPEN transition."""
        if self._last_failure_time is None:
            return True
        elapsed = time.time() - self._last_failure_time
        return elapsed >= self.config.cooldown_seconds

    def record_success(self) -> None:
        """Record a successful request."""
        with self._lock:
            self._total_successes += 1
            self._consecutive_successes += 1
            self._consecutive_failures = 0

            # Check for HALF_OPEN → CLOSED transition
            if self._state == CircuitState.HALF_OPEN:
                if self._consecutive_successes >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed request."""
        with self._lock:
            self._total_failures += 1
            self._consecutive_failures += 1
            self._consecutive_successes = 0
            self._last_failure_time = time.time()

            # Check for state transitions
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN reopens the circuit
                self._state = CircuitState.OPEN
            elif self._state == CircuitState.CLOSED:
                # Check for CLOSED → OPEN transition
                if self._consecutive_failures >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN

    def allow_request(self) -> bool:
        """Check if a request should be allowed.

        Returns:
            True if request should proceed, False if blocked
        """
        current_state = self.state  # This triggers auto-transition check
        return current_state != CircuitState.OPEN

    def check_or_raise(self) -> None:
        """Check if request is allowed, raising if circuit is OPEN.

        Raises:
            ProviderUnavailableError: If circuit is OPEN
        """
        if not self.allow_request():
            raise ProviderUnavailableError(
                f"Circuit breaker '{self.name}' is OPEN - provider unavailable"
            )

    def reset(self) -> None:
        """Manually reset circuit breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._last_failure_time = None

    def get_stats(self) -> Dict:
        """Get circuit breaker statistics.

        Returns:
            Dictionary with state and counter information
        """
        with self._lock:
            cooldown_remaining = 0.0
            if self._state == CircuitState.OPEN and self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                cooldown_remaining = max(0.0, self.config.cooldown_seconds - elapsed)

            return {
                "name": self.name,
                "state": self.state.value,
                "consecutive_failures": self._consecutive_failures,
                "consecutive_successes": self._consecutive_successes,
                "total_successes": self._total_successes,
                "total_failures": self._total_failures,
                "cooldown_remaining": cooldown_remaining,
            }


class CircuitBreakerRegistry:
    """Thread-safe singleton registry for circuit breakers.

    Provides centralized management of circuit breakers across providers.
    """

    _instance: Optional["CircuitBreakerRegistry"] = None
    _lock = threading.Lock()

    # Instance attributes declared for type checking
    _breakers: Dict[str, CircuitBreaker]
    _registry_lock: threading.RLock

    def __new__(cls) -> "CircuitBreakerRegistry":
        """Ensure singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._breakers = {}
                cls._instance._registry_lock = threading.RLock()
            return cls._instance

    @classmethod
    def clear_instance(cls) -> None:
        """Clear singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def get_or_create(self, name: str, config: CircuitBreakerConfig) -> CircuitBreaker:
        """Get or create a circuit breaker by name.

        Args:
            name: Unique identifier for the circuit breaker
            config: Configuration for new circuit breakers

        Returns:
            Circuit breaker instance
        """
        with self._registry_lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, config)
            return self._breakers[name]

    def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get an existing circuit breaker by name.

        Args:
            name: Circuit breaker identifier

        Returns:
            Circuit breaker instance or None if not found
        """
        with self._registry_lock:
            return self._breakers.get(name)

    def remove(self, name: str) -> bool:
        """Remove a circuit breaker.

        Args:
            name: Circuit breaker identifier

        Returns:
            True if removed, False if not found
        """
        with self._registry_lock:
            if name in self._breakers:
                del self._breakers[name]
                return True
            return False

    def get_all_stats(self) -> Dict[str, Dict]:
        """Get statistics for all circuit breakers.

        Returns:
            Dictionary mapping names to stats
        """
        with self._registry_lock:
            return {name: cb.get_stats() for name, cb in self._breakers.items()}

    def reset_all(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        with self._registry_lock:
            for cb in self._breakers.values():
                cb.reset()
