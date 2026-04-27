from abc import ABC, abstractmethod
from typing import List
from src.models.config import ResearchTopic
from src.models.paper import PaperMetadata


class APIError(Exception):
    """External API error"""

    pass


class RateLimitError(APIError):
    """Rate limit exceeded.

    The optional ``retry_after`` attribute carries the upstream
    server's ``Retry-After`` hint when present (parsed from either the
    numeric-seconds form or the HTTP-date form). Callers implementing
    backoff should prefer this value over their own heuristic when it
    is provided. ``None`` means the server gave no hint.

    Naming note: this attribute is named ``retry_after`` (not
    ``retry_after_seconds``) to match the project-wide convention used
    by ``src.utils.exceptions.RateLimitError``,
    ``src.services.llm.exceptions.RateLimitError``, and the shared
    retry orchestrator at ``src.utils.retry`` which reads
    ``e.retry_after``. A field name drift would silently drop the
    backoff hint when this exception flows through the orchestrator.
    """

    def __init__(
        self,
        message: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class APIParameterError(APIError):
    """API parameter validation error (non-retryable)"""

    pass


class DiscoveryProvider(ABC):
    """Abstract base class for research paper discovery providers

    All providers must implement this interface to ensure consistent behavior
    across different research paper sources (ArXiv, Semantic Scholar, etc.)
    """

    @abstractmethod
    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers matching the given topic

        Args:
            topic: Research topic configuration with query, timeframe, filters

        Returns:
            List of PaperMetadata objects matching the query

        Raises:
            APIError: If search fails
            RateLimitError: If rate limit exceeded
        """
        pass  # pragma: no cover

    @abstractmethod
    def validate_query(self, query: str) -> str:
        """Validate query against provider-specific syntax

        Args:
            query: User-provided search query

        Returns:
            Validated and sanitized query string

        Raises:
            ValueError: If query contains invalid syntax or malicious patterns
        """
        pass  # pragma: no cover

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging and identification"""
        pass  # pragma: no cover

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """Whether this provider requires an API key"""
        pass  # pragma: no cover
