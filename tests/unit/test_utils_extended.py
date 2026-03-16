import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from src.utils.rate_limiter import RateLimiter
from src.utils.security import PathSanitizer, SecurityError
from src.utils.logging import configure_logging


@pytest.mark.asyncio
async def test_rate_limiter_abuse_detection():
    limiter = RateLimiter()

    # Mock datetime.now to return a fixed time
    fixed_now = datetime(2023, 1, 1, 12, 0, 30, tzinfo=timezone.utc)

    # Add 501 timestamps within the last minute (so they won't be filtered out)
    for i in range(501):
        # Timestamps from 0-50 seconds ago (all within 1 minute)
        ts = datetime(2023, 1, 1, 12, 0, i % 30, tzinfo=timezone.utc)
        limiter.request_times.append(ts)

    with patch("src.utils.rate_limiter.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        with patch("src.utils.rate_limiter.logger") as mock_logger:
            await limiter.acquire()
            mock_logger.warning.assert_called_with(
                "rate_limit_abuse_detected",
                requester_id="system",
                requests_per_minute=502,
            )


@pytest.mark.asyncio
async def test_rate_limiter_wait():
    limiter = RateLimiter(requests_per_minute=60, burst_size=1)

    await limiter.acquire()
    assert limiter.tokens < 1

    with patch("asyncio.sleep") as mock_sleep:
        await limiter.acquire()
        mock_sleep.assert_called()


def test_security_symlink(tmp_path):
    sanitizer = PathSanitizer([tmp_path])

    outside = tmp_path.parent / "outside.txt"
    outside.touch()

    symlink = tmp_path / "link.txt"
    symlink.symlink_to(outside)

    # expect traversal blocked error
    with pytest.raises(SecurityError, match="Path traversal attempt detected"):
        sanitizer.safe_path(tmp_path, "link.txt")


def test_security_must_exist(tmp_path):
    sanitizer = PathSanitizer([tmp_path])

    with pytest.raises(FileNotFoundError):
        sanitizer.safe_path(tmp_path, "missing.txt", must_exist=True)


def test_logging_configure():
    configure_logging()
    import structlog

    logger = structlog.get_logger()
    logger.info("test")


@pytest.mark.asyncio
async def test_rate_limiter_precise_wait():
    """Cover line 39 in rate_limiter.py precisely"""
    limiter = RateLimiter(requests_per_minute=60, burst_size=1)
    limiter.tokens = 0
    # ensure tokens stay below 1
    import time

    limiter.last_update = time.time()

    with patch("asyncio.sleep", return_value=None) as mock_sleep:
        await limiter.acquire()
        mock_sleep.assert_called()
