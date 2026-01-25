import asyncio
import time
from datetime import datetime, timedelta
from typing import List
import structlog

logger = structlog.get_logger()


class RateLimiter:
    """Token bucket rate limiter for API governance"""

    def __init__(self, requests_per_minute: int = 60, burst_size: int = 10):
        self.rate = requests_per_minute / 60.0
        self.burst_size = burst_size
        self.tokens = float(burst_size)
        self.last_update = time.time()
        self.request_times: List[datetime] = []

    async def acquire(self, requester_id: str = "system") -> None:
        """Acquire a token, waiting if necessary"""
        # 1. Update tokens
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.burst_size, self.tokens + elapsed * self.rate)
        self.last_update = now

        # 2. Check tokens
        if self.tokens < 1:
            wait_time = (1 - self.tokens) / self.rate
            await asyncio.sleep(wait_time)
            self.tokens = 0
        else:
            self.tokens -= 1

        # 3. Abuse detection (track last minute)
        now_dt = datetime.utcnow()
        self.request_times.append(now_dt)
        minute_ago = now_dt - timedelta(minutes=1)
        self.request_times = [t for t in self.request_times if t > minute_ago]

        if (
            len(self.request_times) > 500
        ):  # Threshold for obvious abuse # pragma: no cover
            logger.warning(
                "rate_limit_abuse_detected",
                requester_id=requester_id,
                requests_per_minute=len(self.request_times),
            )
