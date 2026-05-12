"""Unit tests for ProviderHealthChecker (Phase 9.5 REQ-9.5.1.3).

Verifies the health probe surfaces auth/connectivity failures with a
distinct, actionable structured-log event rather than letting them
silently degrade into per-extraction retry warnings.

SR-9.5.A.1 is also exercised: probe events MUST NOT include raw exception
messages (which can echo headers or request bodies that may carry auth
context). Only the provider name, exception class, and a remediation hint
are logged.
"""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
import structlog

from src.services.llm.exceptions import (
    AuthenticationError,
    ProviderUnavailableError,
)
from src.services.llm.health_check import (
    ProviderHealthChecker,
    ProviderHealthResult,
)


def _provider(name: str, generate_side_effect=None, generate_return=None) -> Mock:
    """Build a mock LLMProvider with controlled generate() behavior."""
    provider = Mock()
    provider.name = name
    if generate_side_effect is not None:
        provider.generate = AsyncMock(side_effect=generate_side_effect)
    else:
        provider.generate = AsyncMock(return_value=generate_return or Mock())
    return provider


@pytest.fixture(autouse=True)
def _isolate_circuit_breaker_registry():
    """Clear the CircuitBreakerRegistry singleton between tests.

    The registry is process-wide, so a force_open from one test would
    leak into the next test's "fresh" LLMService construction (which
    pulls the same breaker by name). Clearing before+after isolates
    the tests in this module that care about breaker state.
    """
    from src.utils.circuit_breaker import CircuitBreakerRegistry

    CircuitBreakerRegistry.clear_instance()
    yield
    CircuitBreakerRegistry.clear_instance()


class TestSingleProviderProbe:
    """Single-provider probe behavior (per-class outcome paths)."""

    @pytest.mark.asyncio
    async def test_passes_on_successful_probe(self):
        provider = _provider("anthropic")

        with structlog.testing.capture_logs() as logs:
            result = await ProviderHealthChecker.check(provider)

        assert result == ProviderHealthResult(provider="anthropic", healthy=True)
        passed = [e for e in logs if e["event"] == "provider_health_check_passed"]
        assert len(passed) == 1
        assert passed[0]["provider"] == "anthropic"
        provider.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fails_on_authentication_error_with_remediation(self):
        provider = _provider(
            "anthropic",
            generate_side_effect=AuthenticationError(
                "invalid x-api-key", provider="anthropic"
            ),
        )

        with structlog.testing.capture_logs() as logs:
            result = await ProviderHealthChecker.check(provider)

        assert result.healthy is False
        assert result.error_class == "AuthenticationError"
        assert "Rotate" in (result.remediation or "")
        failed = [e for e in logs if e["event"] == "provider_health_check_failed"]
        assert len(failed) == 1
        assert failed[0]["error_class"] == "AuthenticationError"

    @pytest.mark.asyncio
    async def test_fails_on_timeout(self, monkeypatch):
        # Force a fast timeout window so the test does not actually sleep
        monkeypatch.setattr("src.services.llm.health_check.PROBE_TIMEOUT_SECONDS", 0.01)

        async def hang(*_args, **_kwargs):
            await asyncio.sleep(10)
            return Mock()

        provider = _provider("google", generate_side_effect=hang)

        result = await ProviderHealthChecker.check(provider)

        assert result.healthy is False
        assert result.error_class == "TimeoutError"
        assert "network" in (result.remediation or "").lower()

    @pytest.mark.asyncio
    async def test_fails_on_other_llm_provider_error(self):
        provider = _provider(
            "anthropic",
            generate_side_effect=ProviderUnavailableError(
                "503 service unavailable", provider="anthropic"
            ),
        )

        result = await ProviderHealthChecker.check(provider)

        assert result.healthy is False
        assert result.error_class == "ProviderUnavailableError"

    @pytest.mark.asyncio
    async def test_fails_on_unexpected_exception(self):
        provider = _provider(
            "google", generate_side_effect=RuntimeError("unexpected bug")
        )

        result = await ProviderHealthChecker.check(provider)

        assert result.healthy is False
        assert result.error_class == "RuntimeError"
        assert "unexpected" in (result.remediation or "").lower()


class TestProbeDoesNotLeakSecrets:
    """SR-9.5.A.1: probes MUST NOT log raw exception messages."""

    @pytest.mark.asyncio
    async def test_failure_log_omits_exception_message(self):
        # Construct an error whose str() contains a secret-like string
        secret_message = "auth failed: x-api-key=sk-ant-FAKE-SECRET-XXX"
        provider = _provider(
            "anthropic",
            generate_side_effect=AuthenticationError(
                secret_message, provider="anthropic"
            ),
        )

        with structlog.testing.capture_logs() as logs:
            await ProviderHealthChecker.check(provider)

        for event in logs:
            for key, value in event.items():
                assert "FAKE-SECRET" not in str(value), (
                    f"Probe log leaked secret-like content via field {key!r}: "
                    f"{value!r}"
                )
                assert "sk-ant" not in str(value), (
                    f"Probe log leaked api-key prefix via field {key!r}: " f"{value!r}"
                )


class TestParallelProbe:
    """check_all parallelism and aggregation behavior."""

    @pytest.mark.asyncio
    async def test_check_all_returns_one_result_per_provider(self):
        provider_a = _provider("anthropic")
        provider_b = _provider("google")

        results = await ProviderHealthChecker.check_all([provider_a, provider_b])

        assert len(results) == 2
        assert {r.provider for r in results} == {"anthropic", "google"}
        assert all(r.healthy for r in results)

    @pytest.mark.asyncio
    async def test_check_all_isolates_one_provider_failure_from_others(self):
        provider_a = _provider(
            "anthropic",
            generate_side_effect=AuthenticationError("bad key", provider="anthropic"),
        )
        provider_b = _provider("google")

        results = await ProviderHealthChecker.check_all([provider_a, provider_b])

        by_name = {r.provider: r for r in results}
        assert by_name["anthropic"].healthy is False
        assert by_name["google"].healthy is True

    @pytest.mark.asyncio
    async def test_check_all_returns_empty_for_no_providers(self):
        assert await ProviderHealthChecker.check_all([]) == []


class TestLLMServiceWiring:
    """REQ-9.5.1.3 wiring: extract()/complete() trigger health check first.

    The suite-wide autouse in :mod:`tests.conftest` no-ops the probe for
    most tests; this class opts back in to the real implementation via
    the :func:`enable_llm_provider_health_check` fixture so the wiring
    is exercised end-to-end. A future regression in
    :meth:`LLMService.ensure_health_checked` surfaces here.
    """

    @pytest.fixture(autouse=True)
    def _enable_real_probe(self, enable_llm_provider_health_check):
        return enable_llm_provider_health_check

    @pytest.mark.asyncio
    async def test_complete_triggers_health_check_on_first_call(self, monkeypatch):
        from src.models.llm import CostLimits, LLMConfig
        from src.services.llm.providers.base import LLMResponse
        from src.services.llm.service import LLMService

        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet",
            max_tokens=4096,
            temperature=0.0,
        )
        cost_limits = CostLimits(
            max_tokens_per_paper=10_000,
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

        with monkeypatch.context() as mp:
            mp.setattr("anthropic.AsyncAnthropic", Mock())
            service = LLMService(config=config, cost_limits=cost_limits)

            mock_response = LLMResponse(
                content="hello",
                input_tokens=1,
                output_tokens=1,
                model="claude-3-5-sonnet",
                provider="anthropic",
                latency_ms=1.0,
            )
            provider = service._providers["anthropic"]
            provider.generate = AsyncMock(return_value=mock_response)

            assert service._health_checked is False
            await service.complete(prompt="hi")
            # Health check ran (sets the flag) plus the actual call.
            assert service._health_checked is True
            # Two awaits: the ping probe + the real complete call.
            assert provider.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_health_check_runs_only_once_per_process(self, monkeypatch):
        from src.models.llm import CostLimits, LLMConfig
        from src.services.llm.providers.base import LLMResponse
        from src.services.llm.service import LLMService

        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet",
            max_tokens=4096,
            temperature=0.0,
        )
        cost_limits = CostLimits(
            max_tokens_per_paper=10_000,
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

        with monkeypatch.context() as mp:
            mp.setattr("anthropic.AsyncAnthropic", Mock())
            service = LLMService(config=config, cost_limits=cost_limits)
            mock_response = LLMResponse(
                content="x",
                input_tokens=1,
                output_tokens=1,
                model="claude-3-5-sonnet",
                provider="anthropic",
                latency_ms=1.0,
            )
            provider = service._providers["anthropic"]
            provider.generate = AsyncMock(return_value=mock_response)

            await service.complete(prompt="first")
            await service.complete(prompt="second")
            await service.complete(prompt="third")

            # First call = 1 probe + 1 complete; subsequent calls each
            # add 1 complete only. Expect 1 + 3 = 4 awaits.
            assert provider.generate.await_count == 4

    @pytest.mark.asyncio
    async def test_concurrent_first_callers_do_not_double_probe(self, monkeypatch):
        """Phase 9.5 review fix #7: ensure_health_checked has a Lock.

        If two coroutines both pass the ``_health_checked`` check before
        either sets the flag, they MUST NOT both run the probe. The
        double-checked locking inside ``ensure_health_checked`` ensures
        the probe runs exactly once even under concurrent first-callers.
        """
        import asyncio as _asyncio

        from src.models.llm import CostLimits, LLMConfig
        from src.services.llm.providers.base import LLMResponse
        from src.services.llm.service import LLMService

        config = LLMConfig(
            provider="anthropic",
            api_key="test-key",
            model="claude-3-5-sonnet",
            max_tokens=4096,
            temperature=0.0,
        )
        cost_limits = CostLimits(
            max_tokens_per_paper=10_000,
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

        with monkeypatch.context() as mp:
            mp.setattr("anthropic.AsyncAnthropic", Mock())
            service = LLMService(config=config, cost_limits=cost_limits)
            mock_response = LLMResponse(
                content="x",
                input_tokens=1,
                output_tokens=1,
                model="claude-3-5-sonnet",
                provider="anthropic",
                latency_ms=1.0,
            )
            provider = service._providers["anthropic"]
            provider.generate = AsyncMock(return_value=mock_response)

            # Fire many concurrent first-callers; the lock must serialize
            # the probe so generate sees exactly N + 1 calls (N completes
            # + 1 probe), not N + N.
            n = 5
            await _asyncio.gather(*(service.complete(prompt=f"q{i}") for i in range(n)))
            assert provider.generate.await_count == n + 1


class TestProbeOpensCircuitBreaker:
    """Phase 9.5 review fix #2: REQ-9.5.1.3 fail-fast wiring.

    When a probe fails for a provider whose circuit breaker is enabled,
    ``ensure_health_checked`` must force the breaker OPEN so subsequent
    runtime ``extract()`` / ``complete()`` calls fail fast against that
    provider rather than re-discovering the same failure under retry.

    The module-level ``_isolate_circuit_breaker_registry`` fixture
    clears the registry before and after each test so a force-opened
    breaker from one test does not bleed into the next.
    """

    @pytest.fixture(autouse=True)
    def _enable_real_probe(self, enable_llm_provider_health_check):
        """Opt back in to the real probe for these wiring tests."""
        return enable_llm_provider_health_check

    @pytest.mark.asyncio
    async def test_failed_probe_forces_circuit_breaker_open(self, monkeypatch):
        from src.models.llm import (
            CircuitBreakerConfig,
            CostLimits,
            FallbackProviderConfig,
            LLMConfig,
        )
        from src.services.llm.exceptions import AuthenticationError
        from src.services.llm.service import LLMService

        # Configure both providers with circuit breakers enabled so the
        # probe-driven force_open is observable on the primary while the
        # secondary stays CLOSED.
        config = LLMConfig(
            provider="anthropic",
            api_key="bad-key",
            model="claude-3-5-sonnet",
            max_tokens=4096,
            temperature=0.0,
            circuit_breaker=CircuitBreakerConfig(enabled=True),
            fallback=FallbackProviderConfig(
                enabled=True,
                provider="google",
                model="gemini-1.5-pro",
                api_key="ok-key",
            ),
        )
        cost_limits = CostLimits(
            max_tokens_per_paper=10_000,
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

        with monkeypatch.context() as mp:
            mp.setattr("anthropic.AsyncAnthropic", Mock())
            mp.setattr("google.genai.Client", Mock())
            service = LLMService(config=config, cost_limits=cost_limits)

            # Primary fails the probe with AuthenticationError; secondary
            # passes the probe normally.
            primary = service._providers["anthropic"]
            primary.generate = AsyncMock(
                side_effect=AuthenticationError(
                    "invalid x-api-key", provider="anthropic"
                )
            )
            secondary = service._providers["google"]
            secondary.generate = AsyncMock(
                side_effect=AuthenticationError(  # tearing down quickly
                    "ignored", provider="google"
                )
            )
            # Override secondary to succeed AFTER the probe so we can
            # reach the assertion path.
            secondary.generate = AsyncMock()

            primary_health = service._provider_health["anthropic"]
            assert primary_health.circuit_breaker is not None
            # Pre-condition: circuit is CLOSED before any probe runs.
            assert primary_health.circuit_breaker.allow_request() is True

            await service.ensure_health_checked()

            # Post-condition: probe failure forced the circuit OPEN, so
            # subsequent runtime calls fail-fast without hitting the
            # provider.
            assert primary_health.circuit_breaker.allow_request() is False

    @pytest.mark.asyncio
    async def test_failed_probe_with_no_circuit_breaker_skips_force_open(
        self, monkeypatch
    ):
        """Defensive branch: probe-failed provider with CB disabled.

        When ``circuit_breaker.enabled=False``, the provider has no
        breaker to force-open. ``ensure_health_checked`` MUST log the
        failure (per REQ-9.5.1.3) but skip the force_open step rather
        than crashing.
        """
        from src.models.llm import CircuitBreakerConfig, CostLimits, LLMConfig
        from src.services.llm.exceptions import AuthenticationError
        from src.services.llm.service import LLMService

        config = LLMConfig(
            provider="anthropic",
            api_key="bad-key",
            model="claude-3-5-sonnet",
            max_tokens=4096,
            temperature=0.0,
            circuit_breaker=CircuitBreakerConfig(enabled=False),
        )
        cost_limits = CostLimits(
            max_tokens_per_paper=10_000,
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

        with monkeypatch.context() as mp:
            mp.setattr("anthropic.AsyncAnthropic", Mock())
            service = LLMService(config=config, cost_limits=cost_limits)
            primary = service._providers["anthropic"]
            primary.generate = AsyncMock(
                side_effect=AuthenticationError("bad", provider="anthropic")
            )

            # Should not raise even though CB is disabled (line 174 branch)
            results = await service.ensure_health_checked()

            assert len(results) == 1
            assert results[0].healthy is False
            # No CB exists to be opened, but health-check still completed.
            primary_health = service._provider_health["anthropic"]
            assert getattr(primary_health, "circuit_breaker", None) is None

    @pytest.mark.asyncio
    async def test_failed_probe_for_unregistered_provider_skips_safely(
        self, monkeypatch
    ):
        """Defensive branch: result for a name not in _provider_health.

        Should never happen in practice (probe iterates _providers, which
        is populated alongside _provider_health by ProviderManager), but
        a defensive ``continue`` guards against future drift between the
        two collections.
        """
        from src.models.llm import CostLimits, LLMConfig
        from src.services.llm.health_check import ProviderHealthResult
        from src.services.llm.service import LLMService

        config = LLMConfig(
            provider="anthropic",
            api_key="ok-key",
            model="claude-3-5-sonnet",
            max_tokens=4096,
            temperature=0.0,
        )
        cost_limits = CostLimits(
            max_tokens_per_paper=10_000,
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

        with monkeypatch.context() as mp:
            mp.setattr("anthropic.AsyncAnthropic", Mock())
            service = LLMService(config=config, cost_limits=cost_limits)

            # Inject a synthetic probe result for a provider that has no
            # entry in _provider_health (drift simulation).
            ghost_result = ProviderHealthResult(
                provider="ghost-provider",
                healthy=False,
                error_class="LLMProviderError",
            )

            async def _fake_check_all(_providers):
                return [ghost_result]

            mp.setattr(
                "src.services.llm.service.ProviderHealthChecker.check_all",
                staticmethod(_fake_check_all),
            )

            # Should complete without raising (line 171 branch)
            results = await service.ensure_health_checked()
            assert results == [ghost_result]

    @pytest.mark.asyncio
    async def test_passed_probe_leaves_circuit_breaker_closed(self, monkeypatch):
        from src.models.llm import CircuitBreakerConfig, CostLimits, LLMConfig
        from src.services.llm.providers.base import LLMResponse
        from src.services.llm.service import LLMService

        config = LLMConfig(
            provider="anthropic",
            api_key="good-key",
            model="claude-3-5-sonnet",
            max_tokens=4096,
            temperature=0.0,
            circuit_breaker=CircuitBreakerConfig(enabled=True),
        )
        cost_limits = CostLimits(
            max_tokens_per_paper=10_000,
            max_daily_spend_usd=10.0,
            max_total_spend_usd=100.0,
        )

        with monkeypatch.context() as mp:
            mp.setattr("anthropic.AsyncAnthropic", Mock())
            service = LLMService(config=config, cost_limits=cost_limits)
            primary = service._providers["anthropic"]
            primary.generate = AsyncMock(
                return_value=LLMResponse(
                    content="ok",
                    input_tokens=1,
                    output_tokens=1,
                    model="claude-3-5-sonnet",
                    provider="anthropic",
                    latency_ms=1.0,
                )
            )

            await service.ensure_health_checked()

            primary_health = service._provider_health["anthropic"]
            assert primary_health.circuit_breaker is not None
            # Probe passed → circuit stays CLOSED.
            assert primary_health.circuit_breaker.allow_request() is True
