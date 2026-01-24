import asyncio
import time
from collections import deque
from typing import Optional, Deque
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()

class RateLimiter:
    """Token bucket rate limiter with security logging"""

    def __init__(
        self,
        requests_per_minute: int = 100,
        burst_size: Optional[int] = None
    ):
        self.rate = requests_per_minute / 60.0
        self.burst_size: float = float(burst_size or requests_per_minute)
        self.tokens: float = self.burst_size
        self.last_update = time.time()

        # Track for abuse detection
        self.request_times: Deque[datetime] = deque(maxlen=1000)

    async def acquire(self, requester_id: str = "system"):
        """Acquire token with abuse detection"""
        # Record request
        self.request_times.append(datetime.utcnow())

        # Check for abuse (>500 requests in 1 minute)
        one_min_ago = datetime.utcnow() - timedelta(minutes=1)
        # Filter deque efficiently
        recent = 0
        for t in reversed(self.request_times):
            if t > one_min_ago:
                recent += 1
            else:
                break

        if recent > 500:
            logger.warning(
                "rate_limit_abuse_detected",
                requester_id=requester_id,
                requests_per_minute=recent
            )
            # Consider blocking or alerting

        # Token bucket algorithm
        while True:
            now = time.time()
            elapsed = now - self.last_update

            # Refill bucket
            self.tokens = min(
                self.burst_size,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return

            # Wait for next token
            wait_time = (1 - self.tokens) / self.rate
            if wait_time > 0:
                # logger.debug(
                #     "rate_limit_waiting",
                #     requester_id=requester_id,
                #     wait_seconds=wait_time
                # )
                await asyncio.sleep(wait_time)
