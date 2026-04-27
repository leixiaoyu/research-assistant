"""Regression tests for ``src.services.providers.base`` exceptions.

These tests pin down the constructor surface of ``RateLimitError`` so a
future rename / signature change can't silently break the four sibling
provider call sites (``providers/openalex.py``, ``providers/huggingface.py``,
``providers/arxiv.py``, ``providers/semantic_scholar.py``) — they all
construct ``RateLimitError`` with a single positional message and rely on
``retry_after`` defaulting to ``None``.

Per round-2 review #S8: the previous regression tests in
``tests/unit/test_branch_coverage.py`` and ``tests/unit/test_utils/
test_retry_phase33.py`` pinned ``src.utils.exceptions.RateLimitError``,
not this providers' base class. This file closes that gap.
"""

from __future__ import annotations

import pytest

from src.services.providers.base import APIError, RateLimitError


def test_rate_limit_error_positional_message_only():
    """``RateLimitError("rate limited")`` — must work with one positional arg.

    This is the construction pattern used by every sibling provider
    (e.g. ``raise RateLimitError("OpenAlex rate limit exceeded")``).
    A signature change that requires ``retry_after`` would silently
    break those call sites.
    """
    err = RateLimitError("rate limited")
    assert str(err) == "rate limited"
    assert err.retry_after is None


def test_rate_limit_error_keyword_retry_after():
    """``RateLimitError("rate limited", retry_after=30.0)`` — keyword form.

    This is the construction pattern used by
    ``semantic_scholar_client.py`` after parsing the ``Retry-After``
    response header.
    """
    err = RateLimitError("rate limited", retry_after=30.0)
    assert str(err) == "rate limited"
    assert err.retry_after == 30.0


def test_rate_limit_error_subclasses_apierror():
    """``RateLimitError`` must remain an ``APIError`` subclass.

    ``providers/semantic_scholar.py:62`` retries on
    ``(aiohttp.ClientError, RateLimitError)``; downstream callers
    catch ``APIError`` to handle "any provider failure". A change that
    breaks this hierarchy would route rate-limit errors past those
    handlers.
    """
    assert issubclass(RateLimitError, APIError)
    assert isinstance(RateLimitError("x"), APIError)


def test_rate_limit_error_default_construction_no_args():
    """``RateLimitError()`` — bare construction must not raise.

    The default-empty message is a documented part of the constructor;
    asserting it here keeps ``message: str = ""`` from being tightened
    to a required positional in a future refactor.
    """
    err = RateLimitError()
    assert err.retry_after is None


def test_rate_limit_error_field_type_is_optional_float():
    """Type-shape regression: ``retry_after`` must accept ``float``/``None``.

    Pinning both branches catches a future change that narrows the type
    annotation away from ``float | None``.
    """
    assert RateLimitError("x", retry_after=None).retry_after is None
    assert RateLimitError("x", retry_after=0.0).retry_after == 0.0
    assert RateLimitError("x", retry_after=42.5).retry_after == 42.5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"retry_after": None},
        {"retry_after": 0.0},
        {"retry_after": 1.5},
        {"retry_after": 1000.0},
    ],
)
def test_rate_limit_error_keyword_only_retry_after_values(kwargs):
    """Range sanity: a sampling of legal ``retry_after`` values.

    Hardens against accidental clamping or coercion in the constructor
    (the parsing/clamping happens in ``_parse_retry_after``, not here).
    """
    err = RateLimitError("msg", **kwargs)
    assert err.retry_after == kwargs["retry_after"]
