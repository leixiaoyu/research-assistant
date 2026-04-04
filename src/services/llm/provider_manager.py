"""LLM Provider Management.

This module handles provider initialization, health tracking,
and circuit breaker management for LLM providers.
"""

import os
from typing import Dict, Optional
import structlog

from src.models.llm import LLMConfig
from src.services.llm.providers.base import LLMProvider, ProviderHealth
from src.services.llm.providers.anthropic import AnthropicProvider
from src.services.llm.providers.google import GoogleProvider
from src.services.llm.exceptions import LLMProviderError
from src.utils.exceptions import ExtractionError
from src.utils.circuit_breaker import CircuitBreakerRegistry

logger = structlog.get_logger()


class ProviderManager:
    """Manages LLM provider lifecycle and health.

    Handles:
    - Provider initialization (primary and fallback)
    - Health tracking per provider
    - Circuit breaker attachment
    """

    def __init__(
        self,
        config: LLMConfig,
        circuit_registry: Optional[CircuitBreakerRegistry] = None,
    ):
        """Initialize provider manager.

        Args:
            config: LLM configuration
            circuit_registry: Optional circuit breaker registry
        """
        self.config = config
        self.circuit_registry = circuit_registry or CircuitBreakerRegistry()

        self._providers: Dict[str, LLMProvider] = {}
        self._provider_health: Dict[str, ProviderHealth] = {}
        self.fallback_provider: Optional[str] = None

    def initialize(self) -> None:
        """Initialize all configured providers."""
        self._init_primary_provider()

        if self.config.fallback and self.config.fallback.enabled:
            self._init_fallback_provider()

        logger.info(
            "provider_manager_initialized",
            primary=self.config.provider,
            fallback=self.fallback_provider,
            circuit_breaker_enabled=self.config.circuit_breaker.enabled,
        )

        # Log provider health at startup
        health_status = self.health_check()
        logger.info("startup_health_check", health=health_status)

    def _init_primary_provider(self) -> None:
        """Initialize the primary provider."""
        provider = self._create_provider(
            self.config.provider,
            self.config.api_key,
            self.config.model,
        )
        self._providers[self.config.provider] = provider
        self._init_provider_health(self.config.provider, provider)

    def _init_fallback_provider(self) -> None:
        """Initialize fallback provider if configured."""
        fallback_config = self.config.fallback
        if not fallback_config:
            return

        # Get API key from config or environment
        api_key = fallback_config.api_key
        if not api_key:
            if fallback_config.provider == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY")
            else:
                api_key = os.environ.get("GOOGLE_API_KEY")

        if not api_key:
            logger.warning(
                "fallback_api_key_not_found",
                provider=fallback_config.provider,
            )
            return

        try:
            provider = self._create_provider(
                fallback_config.provider,
                api_key,
                fallback_config.model,
            )
            self._providers[fallback_config.provider] = provider
            self._init_provider_health(fallback_config.provider, provider)
            self.fallback_provider = fallback_config.provider

            logger.info(
                "fallback_provider_initialized",
                provider=fallback_config.provider,
                model=fallback_config.model,
            )
        except Exception as e:
            logger.warning(
                "fallback_provider_init_failed",
                provider=fallback_config.provider,
                error=str(e),
            )

    def _create_provider(
        self,
        provider_name: str,
        api_key: str,
        model: str,
    ) -> LLMProvider:
        """Create a provider instance.

        Args:
            provider_name: Provider name (anthropic, google)
            api_key: API key
            model: Model identifier

        Returns:
            LLMProvider instance

        Raises:
            ExtractionError: If provider is unknown or cannot be initialized
        """
        try:
            if provider_name == "anthropic":
                return AnthropicProvider(api_key=api_key, model=model)
            elif provider_name == "google":
                return GoogleProvider(api_key=api_key, model=model)
            else:
                raise ExtractionError(f"Unknown provider: {provider_name}")
        except LLMProviderError as e:
            # Re-raise as ExtractionError for backward compatibility
            raise ExtractionError(str(e))

    def _init_provider_health(self, name: str, provider: LLMProvider) -> None:
        """Initialize health tracking for a provider."""
        health = provider.get_health()

        # Attach circuit breaker if enabled
        if self.config.circuit_breaker.enabled:
            circuit_breaker = self.circuit_registry.get_or_create(
                name, self.config.circuit_breaker
            )
            # Store circuit breaker reference for later use
            health.circuit_breaker = circuit_breaker  # type: ignore

        self._provider_health[name] = health

    def get_provider(self, name: str) -> Optional[LLMProvider]:
        """Get a provider by name.

        Args:
            name: Provider name

        Returns:
            LLMProvider instance or None
        """
        return self._providers.get(name)

    def get_health(self, name: str) -> Optional[ProviderHealth]:
        """Get health status for a provider.

        Args:
            name: Provider name

        Returns:
            ProviderHealth or None
        """
        return self._provider_health.get(name)

    def get_all_providers(self) -> Dict[str, LLMProvider]:
        """Get all initialized providers."""
        return self._providers

    def get_all_health(self) -> Dict[str, ProviderHealth]:
        """Get health status for all providers."""
        return self._provider_health

    def get_health_stats(self) -> Dict[str, dict]:
        """Get health statistics for all providers."""
        return {
            name: health.get_stats() for name, health in self._provider_health.items()
        }

    def reset_circuit_breakers(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        self.circuit_registry.reset_all()
        for health in self._provider_health.values():
            health.status = "healthy"
            health.consecutive_failures = 0
        logger.info("circuit_breakers_reset", providers=list(self._providers.keys()))

    def has_fallback(self) -> bool:
        """Check if fallback provider is available."""
        return (
            self.fallback_provider is not None
            and self.fallback_provider in self._providers
        )

    def health_check(self) -> Dict[str, dict]:
        """Test health of all providers and return status report.

        Returns:
            Dictionary mapping provider names to health check results:
            {
                "provider_name": {
                    "available": bool,
                    "circuit_state": str,
                    "status": str,
                    "error": str (if unavailable)
                }
            }
        """
        results = {}
        for name, provider in self._providers.items():
            health = self._provider_health.get(name)

            # Get circuit breaker from registry if enabled
            circuit_breaker = None
            if self.config.circuit_breaker.enabled:
                circuit_breaker = self.circuit_registry.get(name)

            # Check circuit breaker state
            if circuit_breaker:
                circuit_state = circuit_breaker.state.value
                is_available = circuit_breaker.allow_request()
            else:
                circuit_state = "disabled"
                is_available = True

            results[name] = {
                "available": is_available,
                "circuit_state": circuit_state,
                "status": health.status if health else "unknown",
            }

            if not is_available:
                results[name]["error"] = f"Circuit breaker is {circuit_state}"

        logger.info("health_check_completed", results=results)
        return results


# Module-level convenience function
def create_provider_manager(
    config: LLMConfig,
    circuit_registry: Optional[CircuitBreakerRegistry] = None,
) -> ProviderManager:
    """Create and initialize a provider manager.

    Args:
        config: LLM configuration
        circuit_registry: Optional circuit breaker registry

    Returns:
        Initialized ProviderManager
    """
    manager = ProviderManager(config, circuit_registry)
    manager.initialize()
    return manager
