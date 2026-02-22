"""Hugging Face Daily Papers provider for paper discovery.

This provider fetches papers from the Hugging Face Daily Papers API
(https://huggingface.co/api/daily_papers) which aggregates trending
AI/ML research papers submitted by the community.

Key Features:
- No API key required (public API)
- Papers are ArXiv-based with guaranteed PDF availability
- Includes AI-generated summaries and keywords
- Community engagement metrics (upvotes, comments)
"""

import aiohttp
import re
from typing import List, Optional
from datetime import datetime, timedelta, timezone
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    retry_if_not_exception_type,
)

from src.services.providers.base import (
    DiscoveryProvider,
    APIError,
    RateLimitError,
    APIParameterError,
)
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
)
from src.models.paper import PaperMetadata, Author
from src.utils.rate_limiter import RateLimiter

logger = structlog.get_logger()


class HuggingFaceProvider(DiscoveryProvider):
    """Search for papers using Hugging Face Daily Papers API.

    The HF Daily Papers API provides access to community-curated AI/ML papers.
    Papers are sourced from ArXiv and include engagement metrics and AI summaries.

    API Details:
    - Endpoint: https://huggingface.co/api/daily_papers
    - Method: GET
    - Parameters: limit (max 100), date (YYYY-MM-DD)
    - No authentication required
    """

    BASE_URL = "https://huggingface.co/api/daily_papers"
    ARXIV_PDF_BASE = "https://arxiv.org/pdf"
    ARXIV_ABS_BASE = "https://arxiv.org/abs"
    HF_PAPERS_BASE = "https://huggingface.co/papers"

    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        """Initialize HuggingFace provider.

        Args:
            rate_limiter: Optional rate limiter. Default: 30 requests/minute.
        """
        # Conservative rate limiting for public API
        self.rate_limiter = rate_limiter or RateLimiter(
            requests_per_minute=30, burst_size=5
        )
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def name(self) -> str:
        """Provider name."""
        return "huggingface"

    @property
    def requires_api_key(self) -> bool:
        """HuggingFace Daily Papers API does not require an API key."""
        return False

    def validate_query(self, query: str) -> str:
        """Validate search query.

        HuggingFace API doesn't support query-based search directly,
        so we validate the query format for keyword matching.

        Args:
            query: User-provided search query.

        Returns:
            Validated and sanitized query string.

        Raises:
            ValueError: If query contains invalid characters.
        """
        # Basic validation - alphanumeric, spaces, common operators
        if not re.match(r'^[a-zA-Z0-9\s\-_+.,"():|]+$', query):
            raise ValueError("Invalid query syntax: contains forbidden characters")

        # Check for reasonable length
        if len(query) < 2:
            raise ValueError("Query too short (minimum 2 characters)")

        if len(query) > 500:
            raise ValueError("Query too long (maximum 500 characters)")

        return query.strip()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=(
            retry_if_exception_type((APIError, RateLimitError))
            & retry_if_not_exception_type(APIParameterError)
        ),
    )
    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers matching topic.

        Since HuggingFace Daily Papers API doesn't support keyword search,
        we fetch recent papers and filter locally by query keywords.

        Args:
            topic: Research topic with query and timeframe.

        Returns:
            List of matching PaperMetadata objects.
        """
        # 1. Validate Query
        try:
            safe_query = self.validate_query(topic.query)
        except ValueError as e:
            logger.error("invalid_huggingface_query", query=topic.query, error=str(e))
            return []

        # 2. Rate Limit
        await self.rate_limiter.acquire(requester_id="huggingface_provider")

        # 3. Build request parameters
        params = self._build_query_params(topic)

        # 4. Execute request
        session = await self._get_session()
        try:
            async with session.get(self.BASE_URL, params=params) as response:
                if response.status == 429:
                    raise RateLimitError("HuggingFace rate limit exceeded (429)")
                if response.status == 403:
                    raise RateLimitError("HuggingFace access forbidden (403)")
                if response.status != 200:
                    raise APIError(f"HuggingFace API returned status {response.status}")

                data = await response.json()
        except aiohttp.ClientError as e:
            logger.error("huggingface_network_error", error=str(e))
            raise APIError(f"HuggingFace request failed: {e}")

        # 5. Parse response
        papers = self._parse_response(data)

        # 6. Filter by query keywords and timeframe
        filtered_papers = self._filter_by_query(papers, safe_query)
        filtered_papers = self._filter_by_timeframe(filtered_papers, topic.timeframe)

        # 7. Limit results
        filtered_papers = filtered_papers[: topic.max_papers]

        # Log results
        pdf_count = sum(1 for p in filtered_papers if p.pdf_available)
        pdf_rate = (pdf_count / len(filtered_papers) * 100) if filtered_papers else 0.0

        logger.info(
            "papers_discovered",
            query=topic.query,
            count=len(filtered_papers),
            provider="huggingface",
            total_fetched=len(papers),
            pdf_available=pdf_count,
            pdf_rate=f"{pdf_rate:.1f}%",
        )

        return filtered_papers

    def _build_query_params(self, topic: ResearchTopic) -> dict:
        """Build API query parameters.

        Args:
            topic: Research topic configuration.

        Returns:
            Dictionary of query parameters.
        """
        params: dict = {"limit": 100}  # Max allowed by API

        # For date-based queries, add date parameter
        tf = topic.timeframe
        if isinstance(tf, TimeframeRecent):
            # For recent timeframes, fetch multiple days
            # HF API returns papers submitted on a specific date
            # We'll fetch without date param to get latest papers
            pass
        elif isinstance(tf, TimeframeDateRange):
            # Use start date for the query
            params["date"] = tf.start_date.strftime("%Y-%m-%d")

        return params

    def _parse_response(self, data: List[dict]) -> List[PaperMetadata]:
        """Parse HuggingFace API response into PaperMetadata objects.

        Args:
            data: Raw API response (list of paper objects).

        Returns:
            List of PaperMetadata objects.
        """
        papers = []

        for item in data:
            try:
                # Extract nested paper object
                paper_data = item.get("paper", item)

                # Paper ID (ArXiv ID)
                paper_id = paper_data.get("id", "")
                if not paper_id:
                    continue

                # Title
                title = paper_data.get("title", "").strip()
                if not title:
                    continue

                # Abstract/Summary
                abstract = paper_data.get("summary", "")

                # Authors
                authors = []
                for author_data in paper_data.get("authors", []):
                    author_name = author_data.get("name", "")
                    if author_name:
                        # Extract user info if available
                        user_data = author_data.get("user", {})
                        author_id = user_data.get("user") if user_data else None
                        affiliation = None

                        # Get organization if available
                        org = paper_data.get("organization", {})
                        if org:
                            affiliation = org.get("fullname") or org.get("name")

                        authors.append(
                            Author(
                                name=author_name,
                                author_id=author_id,
                                affiliation=affiliation,
                            )
                        )

                # Publication date
                pub_date = None
                year = None
                pub_date_str = paper_data.get("publishedAt")
                if pub_date_str:
                    try:
                        pub_date = datetime.fromisoformat(
                            pub_date_str.replace("Z", "+00:00")
                        )
                        year = pub_date.year
                    except (ValueError, TypeError):
                        pass

                # URLs - use ArXiv URLs since papers are ArXiv-based
                url = f"{self.ARXIV_ABS_BASE}/{paper_id}"
                pdf_url = f"{self.ARXIV_PDF_BASE}/{paper_id}.pdf"

                # Metrics
                upvotes = paper_data.get("upvotes", 0)

                # Create PaperMetadata
                paper = PaperMetadata(
                    paper_id=paper_id,
                    arxiv_id=paper_id,
                    title=title,
                    abstract=abstract,
                    url=url,  # type: ignore
                    open_access_pdf=pdf_url,  # type: ignore
                    authors=authors,
                    year=year,
                    publication_date=pub_date,
                    venue="ArXiv (via HuggingFace)",
                    citation_count=upvotes,  # Use upvotes as engagement proxy
                    influential_citation_count=0,
                    relevance_score=0.0,
                    # Phase 3.4: PDF availability (always available for ArXiv papers)
                    pdf_available=True,
                    pdf_source="arxiv",
                )
                papers.append(paper)

            except Exception as e:
                # Safely extract paper_id for logging (item may be None or malformed)
                paper_id = "unknown"
                if item and isinstance(item, dict):
                    paper_obj = item.get("paper", {})
                    if paper_obj and isinstance(paper_obj, dict):
                        paper_id = paper_obj.get("id", "unknown")
                logger.warning(
                    "huggingface_entry_parse_error",
                    error=str(e),
                    paper_id=paper_id,
                )
                continue

        return papers

    def _filter_by_query(
        self, papers: List[PaperMetadata], query: str
    ) -> List[PaperMetadata]:
        """Filter papers by query keywords.

        Since HuggingFace API doesn't support server-side search,
        we filter locally by checking if query terms appear in
        title or abstract.

        Args:
            papers: List of papers to filter.
            query: Search query with keywords.

        Returns:
            Filtered list of papers matching the query.
        """
        # Extract keywords from query (split by operators and whitespace)
        # Remove common operators: AND, OR, NOT
        query_clean = re.sub(r"\b(AND|OR|NOT)\b", " ", query, flags=re.IGNORECASE)
        keywords = [
            kw.strip().lower()
            for kw in re.split(r"[\s,()]+", query_clean)
            if kw.strip() and len(kw.strip()) > 2
        ]

        if not keywords:
            return papers

        filtered = []
        for paper in papers:
            # Combine title and abstract for matching
            text = f"{paper.title} {paper.abstract or ''}".lower()

            # Check if any keyword matches
            if any(kw in text for kw in keywords):
                filtered.append(paper)

        return filtered

    def _filter_by_timeframe(
        self, papers: List[PaperMetadata], timeframe
    ) -> List[PaperMetadata]:
        """Filter papers by publication timeframe.

        Args:
            papers: List of papers to filter.
            timeframe: Timeframe configuration.

        Returns:
            Filtered list of papers within timeframe.
        """
        if not papers:
            return papers

        # Use timezone-aware datetime for comparison
        now = datetime.now(timezone.utc)

        if isinstance(timeframe, TimeframeRecent):
            # Parse timeframe value (e.g., "48h", "7d")
            value = timeframe.value
            if value.endswith("h"):
                delta = timedelta(hours=int(value[:-1]))
            elif value.endswith("d"):
                delta = timedelta(days=int(value[:-1]))
            else:
                return papers

            cutoff = now - delta
            return [
                p
                for p in papers
                if p.publication_date and self._make_aware(p.publication_date) >= cutoff
            ]

        elif isinstance(timeframe, TimeframeSinceYear):
            return [p for p in papers if p.year and p.year >= timeframe.value]

        elif isinstance(timeframe, TimeframeDateRange):
            start = datetime.combine(
                timeframe.start_date, datetime.min.time(), tzinfo=timezone.utc
            )
            end = datetime.combine(
                timeframe.end_date, datetime.max.time(), tzinfo=timezone.utc
            )
            return [
                p
                for p in papers
                if p.publication_date
                and start <= self._make_aware(p.publication_date) <= end
            ]

        return papers

    def _make_aware(self, dt: datetime) -> datetime:
        """Make a datetime timezone-aware (UTC) if it isn't already."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
