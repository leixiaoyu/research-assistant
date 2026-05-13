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


# Capture the real LLMService.ensure_health_checked at import time, BEFORE
# the autouse fixture replaces it. The opt-in fixture restores this exact
# reference so tests that verify the wiring exercise production code
# (and contribute coverage to src/services/llm/service.py).
def _capture_real_ensure_health_checked():
    from src.services.llm.service import LLMService

    return LLMService.ensure_health_checked


_REAL_ENSURE_HEALTH_CHECKED = _capture_real_ensure_health_checked()


@pytest.fixture(autouse=True)
def _disable_llm_provider_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the Phase 9.5 provider startup health probe in unit tests.

    REQ-9.5.1.3 introduced an automatic startup probe that calls
    ``provider.generate(prompt="ping", max_tokens=1)`` on first
    ``LLMService.extract()`` / ``complete()`` invocation, AND force-opens
    the circuit breaker for any probe-failed provider so subsequent
    calls fail-fast (per spec Section 3, Workstream A).

    That behavior is correct for production but interacts with most
    existing unit tests in three ways that need neutralization:

    1. Tests that mock ``provider.generate`` with an exception side_effect
       (to exercise extract()'s retry/fallback branches) would have the
       probe trip first, force-open the circuit, and prevent extract()
       from even reaching the branch under test.
    2. Tests that assert exact ``provider.generate.assert_called_once()``
       see two calls (1 probe + 1 real) instead of one.
    3. Tests that don't care about the probe still pay its (small) cost
       of an extra await in setup, masking warning-on-noise discipline.

    This fixture short-circuits the probe to a no-op for the entire
    suite. The opt-in :func:`enable_llm_provider_health_check` fixture
    re-enables the real implementation for tests that specifically
    verify the probe wiring (see
    :mod:`tests.unit.test_services.test_llm_health_check`).

    The ``ProviderHealthChecker`` class itself is exercised directly
    (without going through ``LLMService``) by the unit tests in
    ``test_llm_health_check.py``, so probe behavior is not vacuous —
    only the wiring path is short-circuited.
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
    """Re-enable the real provider startup health probe.

    Pair with the autouse :func:`_disable_llm_provider_health_check`.
    Tests that exercise the wiring between :class:`LLMService` and the
    probe (e.g. asserting first ``extract()`` triggers ``check_all`` and
    a probe-failed provider has its circuit breaker force-opened) MUST
    request this fixture so the real implementation runs.

    Restores the exact production method (captured at import time before
    the autouse replaced it) — not a copy — so coverage of
    ``src/services/llm/service.py`` reflects real execution.
    """
    from src.services.llm.service import LLMService

    monkeypatch.setattr(
        LLMService, "ensure_health_checked", _REAL_ENSURE_HEALTH_CHECKED
    )
