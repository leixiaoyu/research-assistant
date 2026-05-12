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

    The autouse ``_disable_llm_provider_health_check`` conftest fixture
    no-ops the probe for the rest of the suite; this class opts back in
    to the real implementation so the wiring is exercised end-to-end.
    """

    @pytest.fixture(autouse=True)
    def _enable_real_probe(self, enable_llm_provider_health_check):
        """Re-enable the real probe for tests in this class."""
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
