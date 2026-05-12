"""Pytest configuration for ARISP test suite.

This file provides shared fixtures and path configuration for all tests.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.services.llm.health_check import ProviderHealthResult

# Add scripts directory to path for validate_phase_specs imports
# This is done here rather than in individual test files per pytest best practices
scripts_path = Path(__file__).parent.parent / "scripts"
if str(scripts_path) not in sys.path:
    sys.path.insert(0, str(scripts_path))


@pytest.fixture(autouse=True)
def _disable_llm_provider_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the Phase 9.5 provider health probe in unit tests.

    REQ-9.5.1.3 introduced an automatic startup probe that calls
    ``provider.generate(prompt="ping", max_tokens=1)`` on first
    ``LLMService.extract()`` / ``complete()`` invocation. That probe is
    correct for production but adds an unwanted call to provider mocks
    in many existing unit tests (e.g. those that assert
    ``provider.generate.assert_called_once()``).

    This autouse fixture short-circuits the probe to a no-op for the
    entire suite. Tests that specifically exercise the probe (see
    :mod:`tests.unit.test_services.test_llm_health_check`) call the
    underlying :class:`ProviderHealthChecker` directly and are unaffected.
    The wiring between ``LLMService`` and the probe is verified by the
    opt-in :func:`enable_llm_provider_health_check` fixture.
    """
    from src.services.llm.service import LLMService

    async def _noop(self: LLMService) -> "list[ProviderHealthResult]":
        self._health_checked = True
        return []

    monkeypatch.setattr(LLMService, "ensure_health_checked", _noop)


@pytest.fixture
def enable_llm_provider_health_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-enable the real provider health probe for opt-in wiring tests.

    Pair with the autouse :func:`_disable_llm_provider_health_check` to
    restore the real :meth:`LLMService.ensure_health_checked` for one
    specific test that wants to verify the probe runs at first use.
    """
    from src.services.llm.service import LLMService
    from src.services.llm.health_check import ProviderHealthChecker

    async def _real(self: LLMService) -> "list[ProviderHealthResult]":
        if self._health_checked:
            return self._health_results
        self._health_results = await ProviderHealthChecker.check_all(
            list(self._providers.values())
        )
        self._health_checked = True
        return self._health_results

    monkeypatch.setattr(LLMService, "ensure_health_checked", _real)
