"""Monitoring models (Milestone 9.1).

Defines:
- ``PaperSource``: enumerates sources eligible for proactive monitoring.
- ``SubscriptionLimitError``: raised when subscription quotas are
  exceeded (SR-9.5).
"""

from enum import Enum


class PaperSource(str, Enum):
    """Sources for paper monitoring (Milestone 9.1).

    MVP Scope: Only ARXIV has RSS/Atom feeds enabling efficient monitoring.
    Other sources require polling with API rate limits.
    """

    ARXIV = "arxiv"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    HUGGINGFACE = "huggingface"
    OPENALEX = "openalex"


class SubscriptionLimitError(ValueError):
    """Raised when subscription limits are exceeded (SR-9.5).

    Limits:
    - Max 50 subscriptions per user
    - Max 100 keywords per subscription
    - Max 1000 papers checked per monitoring cycle
    """

    def __init__(self, limit_type: str, current: int, max_allowed: int):
        message = (
            f"Subscription limit exceeded: {limit_type} "
            f"(current: {current}, max: {max_allowed}). "
            "Remove inactive subscriptions or upgrade plan."
        )
        super().__init__(message)
        self.limit_type = limit_type
        self.current = current
        self.max_allowed = max_allowed
