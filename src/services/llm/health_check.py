"""LLM provider startup health check (Phase 9.5 REQ-9.5.1.3).

Probes each configured provider with a single minimal completion to verify
the provider is reachable, the API key is valid, and the model is
available. The probe runs on first use of :class:`LLMService` per process
(or when explicitly invoked) so authentication failures surface as a
single, distinct ``provider_health_check_failed`` event rather than being
buried in the per-extraction retry warnings that the prior code emitted.

Design notes:

- Probes run with a short per-provider timeout; failures DO NOT prevent
  service startup, but the failed provider is reported as unhealthy so a
  caller can decide whether to abort, fail-over, or proceed.
- Per SR-9.5.A.1 the structured log events SHALL include only the
  provider name and the exception class name. Raw exception messages,
  request bodies, and response bodies are NOT logged because provider
  errors occasionally echo headers or fragments of the request that may
  contain authentication context.
- Probe cost is negligible (~$0.00001 per provider per process; one
  ``max_tokens=1`` completion).
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, Sequence

import structlog

from src.services.llm.exceptions import (
    AuthenticationError,
    LLMProviderError,
)
from src.services.llm.providers.base import LLMProvider

logger = structlog.get_logger()


PROBE_TIMEOUT_SECONDS = 5.0
PROBE_PROMPT = "ping"
PROBE_MAX_TOKENS = 1


@dataclass(frozen=True)
class ProviderHealthResult:
    """Outcome of a single provider health probe.

    Attributes:
        provider: Provider name (e.g. "anthropic", "google").
        healthy: True when the provider responded successfully.
        error_class: Exception class name on failure (None when healthy).
        remediation: Human-readable hint for resolving the failure
            (None when healthy).
    """

    provider: str
    healthy: bool
    error_class: Optional[str] = None
    remediation: Optional[str] = None


class ProviderHealthChecker:
    """Runs startup health probes against LLM providers.

    Stateless utility — instances are not required; static methods are
    provided for ergonomics. Callers typically use :meth:`check_all` from
    :class:`LLMService` or any other component that wants to verify
    provider connectivity before its first real call.
    """

    @staticmethod
    async def check(provider: LLMProvider) -> ProviderHealthResult:
        """Probe a single provider with a minimal completion.

        Returns a :class:`ProviderHealthResult` rather than raising so the
        caller can record the outcome for every provider regardless of
        which ones fail.
        """
        try:
            await asyncio.wait_for(
                provider.generate(
                    prompt=PROBE_PROMPT,
                    max_tokens=PROBE_MAX_TOKENS,
                    temperature=0.0,
                ),
                timeout=PROBE_TIMEOUT_SECONDS,
            )
        except AuthenticationError:
            remediation = f"Rotate the {provider.name} API key in .env and restart"
            logger.error(
                "provider_health_check_failed",
                provider=provider.name,
                error_class="AuthenticationError",
                remediation=remediation,
            )
            return ProviderHealthResult(
                provider=provider.name,
                healthy=False,
                error_class="AuthenticationError",
                remediation=remediation,
            )
        except asyncio.TimeoutError:
            remediation = (
                "Check network connectivity and " f"{provider.name} provider status"
            )
            logger.error(
                "provider_health_check_failed",
                provider=provider.name,
                error_class="TimeoutError",
                remediation=remediation,
            )
            return ProviderHealthResult(
                provider=provider.name,
                healthy=False,
                error_class="TimeoutError",
                remediation=remediation,
            )
        except LLMProviderError as exc:
            error_class = type(exc).__name__
            remediation = (
                f"Check {provider.name} provider status, model name, and "
                "configuration"
            )
            logger.error(
                "provider_health_check_failed",
                provider=provider.name,
                error_class=error_class,
                remediation=remediation,
            )
            return ProviderHealthResult(
                provider=provider.name,
                healthy=False,
                error_class=error_class,
                remediation=remediation,
            )
        except Exception as exc:
            # Unexpected exception type — record it but do not let one
            # provider's failure mode crash the health-check sweep.
            error_class = type(exc).__name__
            remediation = (
                f"Investigate unexpected {provider.name} probe failure "
                f"({error_class})"
            )
            logger.error(
                "provider_health_check_failed",
                provider=provider.name,
                error_class=error_class,
                remediation=remediation,
            )
            return ProviderHealthResult(
                provider=provider.name,
                healthy=False,
                error_class=error_class,
                remediation=remediation,
            )
        else:
            logger.info(
                "provider_health_check_passed",
                provider=provider.name,
            )
            return ProviderHealthResult(
                provider=provider.name,
                healthy=True,
            )

    @staticmethod
    async def check_all(
        providers: Sequence[LLMProvider],
    ) -> list[ProviderHealthResult]:
        """Probe a collection of providers in parallel."""
        if not providers:
            return []
        return list(
            await asyncio.gather(*(ProviderHealthChecker.check(p) for p in providers))
        )
