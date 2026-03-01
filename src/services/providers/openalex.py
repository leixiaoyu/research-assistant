"""OpenAlex provider for Phase 6: Enhanced Discovery Pipeline.

OpenAlex provides access to 260M+ scholarly works with comprehensive
metadata including citations, venues, institutions, and open access status.

API Details:
- Endpoint: https://api.openalex.org/works
- Method: GET
- Rate limit: 100K requests/day (with polite pool)
- No authentication required (email for polite pool recommended)

Usage:
    from src.services.providers.openalex import OpenAlexProvider

    provider = OpenAlexProvider(email="user@example.com")
    papers = await provider.search(topic)
"""

import os
import re
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from urllib.parse import urlencode

import aiohttp
import structlog

from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
)
from src.models.paper import PaperMetadata, Author
from src.services.providers.base import (
    DiscoveryProvider,
    APIError,
    RateLimitError,
)
from src.utils.rate_limiter import RateLimiter

logger = structlog.get_logger()


class OpenAlexProvider(DiscoveryProvider):
    """Search for papers using OpenAlex API.

    OpenAlex is a free, open catalog of the world's scholarly works.
    It provides comprehensive metadata for academic papers.

    Attributes:
        email: Email for polite pool access (higher rate limits)
        rate_limiter: Rate limiter for API calls
    """

    BASE_URL = "https://api.openalex.org/works"
    MAX_PER_PAGE = 200  # OpenAlex maximum
    DEFAULT_PER_PAGE = 50

    def __init__(
        self,
        email: Optional[str] = None,
        requests_per_minute: int = 100,
    ) -> None:
        """Initialize OpenAlex provider.

        Args:
            email: Email for polite pool (recommended for higher rate limits)
            requests_per_minute: Maximum requests per minute
        """
        self.email = email or os.getenv("OPENALEX_EMAIL")
        self.rate_limiter = RateLimiter(
            requests_per_minute=requests_per_minute,
            burst_size=10,
        )
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def name(self) -> str:
        """Provider name for logging."""
        return "openalex"

    @property
    def requires_api_key(self) -> bool:
        """OpenAlex does not require an API key."""
        return False

    def validate_query(self, query: str) -> str:
        """Validate and sanitize query for OpenAlex.

        Args:
            query: User-provided search query

        Returns:
            Validated query string

        Raises:
            ValueError: If query is invalid
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        # Remove potentially dangerous characters
        sanitized = re.sub(r'[<>"\';\\]', "", query.strip())

        # Limit length
        if len(sanitized) > 500:
            sanitized = sanitized[:500]

        if not sanitized:
            raise ValueError("Query contains only invalid characters")

        return sanitized

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search OpenAlex for papers matching the topic.

        Args:
            topic: Research topic with query and filters

        Returns:
            List of PaperMetadata objects

        Raises:
            APIError: If API request fails
            RateLimitError: If rate limit exceeded
        """
        validated_query = self.validate_query(topic.query)
        filter_str = self._build_filter(validated_query, topic)
        params = self._build_params(filter_str, topic.max_papers)

        logger.info(
            "openalex_search_starting",
            query=validated_query,
            max_papers=topic.max_papers,
        )

        try:
            await self.rate_limiter.acquire()
            session = await self._get_session()

            url = f"{self.BASE_URL}?{urlencode(params)}"

            async with session.get(url) as response:
                if response.status == 429:
                    raise RateLimitError("OpenAlex rate limit exceeded")
                if response.status != 200:
                    text = await response.text()
                    raise APIError(f"OpenAlex API error {response.status}: {text}")

                data = await response.json()

            papers = self._parse_response(data)

            logger.info(
                "openalex_search_completed",
                query=validated_query,
                papers_found=len(papers),
            )

            return papers

        except aiohttp.ClientError as e:
            logger.error("openalex_request_failed", error=str(e))
            raise APIError(f"OpenAlex request failed: {e}") from e

    def _build_filter(self, query: str, topic: ResearchTopic) -> str:
        """Build OpenAlex filter string from topic configuration.

        Args:
            query: Validated search query
            topic: Research topic configuration

        Returns:
            Filter string for OpenAlex API
        """
        filters = []

        # Title and abstract search
        # OpenAlex uses title_and_abstract.search for full-text search
        filters.append(f"title_and_abstract.search:{query}")

        # Date range filter
        date_filter = self._build_date_filter(topic.timeframe)
        if date_filter:
            filters.append(date_filter)

        # Citation filter
        if topic.min_citations and topic.min_citations > 0:
            filters.append(f"cited_by_count:>{topic.min_citations}")

        # Quality filters
        filters.append("is_retracted:false")  # Exclude retractions
        filters.append("has_abstract:true")  # Require abstract

        # PDF filter if required
        if topic.pdf_strategy.value == "pdf_required":
            filters.append("is_oa:true")

        return ",".join(filters)

    def _build_date_filter(self, timeframe: Any) -> Optional[str]:
        """Build date filter from timeframe.

        Args:
            timeframe: Timeframe configuration

        Returns:
            Date filter string or None
        """
        if isinstance(timeframe, TimeframeRecent):
            # Parse recent timeframe (e.g., "48h", "7d")
            value = timeframe.value
            unit = value[-1]
            amount = int(value[:-1])

            if unit == "h":
                delta = timedelta(hours=amount)
            else:  # 'd'
                delta = timedelta(days=amount)

            start_date = (datetime.now() - delta).strftime("%Y-%m-%d")
            return f"from_publication_date:{start_date}"

        elif isinstance(timeframe, TimeframeSinceYear):
            return f"publication_year:{timeframe.value}-"

        elif isinstance(timeframe, TimeframeDateRange):
            start = timeframe.start_date.strftime("%Y-%m-%d")
            end = timeframe.end_date.strftime("%Y-%m-%d")
            return f"from_publication_date:{start},to_publication_date:{end}"

        return None

    def _build_params(self, filter_str: str, max_papers: int) -> Dict[str, str]:
        """Build API request parameters.

        Args:
            filter_str: Filter string
            max_papers: Maximum papers to retrieve

        Returns:
            Dictionary of API parameters
        """
        per_page = min(max_papers, self.MAX_PER_PAGE)

        params = {
            "filter": filter_str,
            "per_page": str(per_page),
            "sort": "relevance_score:desc",
            "select": ",".join(
                [
                    "id",
                    "title",
                    "abstract_inverted_index",
                    "doi",
                    "publication_date",
                    "cited_by_count",
                    "authorships",
                    "primary_location",
                    "open_access",
                    "type",
                ]
            ),
        }

        # Add email for polite pool
        if self.email:
            params["mailto"] = self.email

        return params

    def _parse_response(self, data: Dict[str, Any]) -> List[PaperMetadata]:
        """Parse OpenAlex API response into PaperMetadata objects.

        Args:
            data: Raw API response

        Returns:
            List of PaperMetadata objects
        """
        papers = []
        results = data.get("results", [])

        for work in results:
            try:
                paper = self._map_work_to_paper(work)
                if paper:
                    papers.append(paper)
            except Exception as e:
                logger.warning(
                    "openalex_parse_error",
                    work_id=work.get("id"),
                    error=str(e),
                )
                continue

        return papers

    def _map_work_to_paper(self, work: Dict[str, Any]) -> Optional[PaperMetadata]:
        """Map OpenAlex work to PaperMetadata.

        Args:
            work: OpenAlex work object

        Returns:
            PaperMetadata object or None if required fields missing
        """
        # Extract OpenAlex ID
        openalex_id = work.get("id", "")
        if openalex_id:
            # Extract ID from URL format: https://openalex.org/W123456
            openalex_id = openalex_id.split("/")[-1]

        title = work.get("title")
        if not title:
            return None

        # Reconstruct abstract from inverted index
        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index"))

        # Extract authors
        authors = self._extract_authors(work.get("authorships", []))

        # Extract DOI
        doi = work.get("doi")
        if doi:
            # Remove DOI URL prefix if present
            doi = doi.replace("https://doi.org/", "")

        # Extract venue
        venue = None
        primary_location = work.get("primary_location", {})
        if primary_location:
            source = primary_location.get("source", {})
            if source:
                venue = source.get("display_name")

        # Extract PDF URL
        pdf_url = self._extract_pdf_url(work)

        # Extract URL
        url = None
        if primary_location:
            url = primary_location.get("landing_page_url")
        if not url and doi:
            url = f"https://doi.org/{doi}"

        return PaperMetadata(  # type: ignore[call-arg]
            paper_id=openalex_id,
            title=title,
            abstract=abstract,
            authors=authors,
            publication_date=work.get("publication_date"),
            venue=venue,
            doi=doi,
            url=url,  # type: ignore[arg-type]
            open_access_pdf=pdf_url,  # type: ignore[arg-type]
            citation_count=work.get("cited_by_count", 0),
            pdf_available=bool(pdf_url),
            pdf_source="openalex" if pdf_url else None,
        )

    def _reconstruct_abstract(
        self, inverted_index: Optional[Dict[str, List[int]]]
    ) -> Optional[str]:
        """Reconstruct abstract from OpenAlex inverted index format.

        OpenAlex stores abstracts as inverted indices where each word
        maps to its positions in the text.

        Args:
            inverted_index: Dictionary mapping words to position lists

        Returns:
            Reconstructed abstract string or None
        """
        if not inverted_index:
            return None

        try:
            # Find maximum position to size the array
            max_pos = 0
            for positions in inverted_index.values():
                if positions:
                    max_pos = max(max_pos, max(positions))

            # Create array and fill with words at their positions
            words = [""] * (max_pos + 1)
            for word, positions in inverted_index.items():
                for pos in positions:
                    words[pos] = word

            # Join and clean up
            abstract = " ".join(words)
            # Remove multiple spaces
            abstract = re.sub(r"\s+", " ", abstract).strip()

            return abstract if abstract else None

        except Exception as e:
            logger.warning("openalex_abstract_reconstruction_failed", error=str(e))
            return None

    def _extract_authors(self, authorships: List[Dict[str, Any]]) -> List[Author]:
        """Extract author information from authorships.

        Args:
            authorships: List of authorship objects from OpenAlex

        Returns:
            List of Author objects
        """
        authors = []
        for authorship in authorships:
            author_data = authorship.get("author", {})
            if author_data:
                name = author_data.get("display_name")
                if name:
                    authors.append(Author(name=name))
        return authors

    def _extract_pdf_url(self, work: Dict[str, Any]) -> Optional[str]:
        """Extract PDF URL from work.

        Args:
            work: OpenAlex work object

        Returns:
            PDF URL or None
        """
        # Check open access info
        oa_info = work.get("open_access", {})
        if oa_info:
            oa_url: Optional[str] = oa_info.get("oa_url")
            if oa_url and oa_url.endswith(".pdf"):
                return oa_url

        # Check primary location
        primary_location = work.get("primary_location", {})
        if primary_location:
            pdf_url: Optional[str] = primary_location.get("pdf_url")
            if pdf_url:
                return pdf_url

        return None

    async def __aenter__(self) -> "OpenAlexProvider":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
