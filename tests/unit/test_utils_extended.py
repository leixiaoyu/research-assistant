import pytest
import asyncio
from unittest.mock import patch, MagicMock
from pathlib import Path
from datetime import datetime
from src.utils.rate_limiter import RateLimiter
from src.utils.security import PathSanitizer, SecurityError
from src.utils.logging import configure_logging

@pytest.mark.asyncio
async def test_rate_limiter_abuse_detection():
    limiter = RateLimiter()
    
    # We patch datetime in the module where RateLimiter is defined
    with patch("src.utils.rate_limiter.datetime") as mock_dt:
        mock_dt.utcnow.return_value = datetime(2023, 1, 1, 12, 0, 0)
        
        # Add 501 timestamps
        for _ in range(501):
            limiter.request_times.append(datetime(2023, 1, 1, 12, 0, 0))
            
        with patch("src.utils.rate_limiter.logger") as mock_logger:
            await limiter.acquire()
            mock_logger.warning.assert_called_with(
                "rate_limit_abuse_detected", 
                requester_id="system", 
                requests_per_minute=502
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
    
    # We expect "Path traversal attempt detected" because resolve() + relative_to() triggers it first
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
