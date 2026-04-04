import feedparser  # type: ignore
import asyncio
import re
import urllib.parse
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
    GlobalSettings,
)
from src.models.paper import PaperMetadata, Author
from src.utils.rate_limiter import RateLimiter
from src.utils.security import SecurityError

logger = structlog.get_logger()


class ArxivProvider(DiscoveryProvider):
    """Search for papers using ArXiv API"""

    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(
        self,
        rate_limiter: Optional[RateLimiter] = None,
        settings: Optional[GlobalSettings] = None,
    ):
        # ArXiv requires 3 seconds between requests
        self.rate_limiter = rate_limiter or RateLimiter(
            requests_per_minute=20, burst_size=1  # 60/3 = 20
        )
        self.settings = settings
        # Feature flag for structured query (Phase 7 Fix I1)
        self.use_structured_query = (
            settings.arxiv_use_structured_query if settings else True
        )
        self.default_categories = (
            settings.arxiv_default_categories
            if settings
            else ["cs.CL", "cs.LG", "cs.AI"]
        )

    @property
    def name(self) -> str:
        """Provider name"""
        return "arxiv"

    @property
    def requires_api_key(self) -> bool:
        """ArXiv does not require an API key"""
        return False

    def validate_query(self, query: str) -> str:
        """Validate ArXiv query syntax"""
        # Allow alphanumeric, spaces, and basic operators
        if not re.match(r'^[a-zA-Z0-9\s\-_+.,"():|]+$', query):
            raise ValueError(
                "Invalid ArXiv query syntax: contains forbidden characters"
            )
        return query

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=3, max=10),
        retry=(
            retry_if_exception_type((APIError, RateLimitError))
            & retry_if_not_exception_type(APIParameterError)
        ),
    )
    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers matching topic"""

        # 1. Validate Query
        try:
            safe_query = self.validate_query(topic.query)
        except ValueError as e:
            logger.error("invalid_arxiv_query", query=topic.query, error=str(e))
            return []

        # 2. Build Params
        params = self._build_query_params(topic, safe_query)

        # 3. Rate Limit
        await self.rate_limiter.acquire(requester_id="arxiv_provider")

        # 4. Execute (using run_in_executor because feedparser is blocking)
        loop = asyncio.get_event_loop()
        try:
            feed = await loop.run_in_executor(
                None, lambda: feedparser.parse(self.BASE_URL + "?" + params)
            )
        except Exception as e:
            logger.error("arxiv_network_error", error=str(e))
            raise APIError(f"ArXiv request failed: {e}")

        # 5. Check Status
        if hasattr(feed, "status") and feed.status != 200:
            if feed.status == 403:  # Forbidden (often rate limit)
                raise RateLimitError("ArXiv rate limit exceeded (403)")
            # ArXiv returns 301 for redirects but may still have valid data
            elif feed.status == 301 and len(feed.entries) > 0:
                first_entry = feed.entries[0]
                entry_id = getattr(first_entry, "id", "")
                if "help/api" in entry_id:
                    error_msg = getattr(
                        first_entry, "summary", "Unknown ArXiv API error"
                    )
                    raise APIParameterError(f"ArXiv API error: {error_msg}")
            elif feed.status == 301:
                raise APIError(f"ArXiv API returned status {feed.status}")
            else:
                raise APIError(f"ArXiv API returned status {feed.status}")

        if hasattr(feed, "bozo") and feed.bozo:
            logger.warning("arxiv_feed_parse_warning", error=str(feed.bozo_exception))

        # 6. Parse
        papers = self._parse_feed(feed)

        # Phase 3.4: Track and log PDF availability
        pdf_count = sum(1 for p in papers if p.pdf_available)
        pdf_rate = (pdf_count / len(papers) * 100) if papers else 0.0

        logger.info(
            "papers_discovered",
            query=topic.query,
            count=len(papers),
            provider="arxiv",
            pdf_available=pdf_count,
            pdf_rate=f"{pdf_rate:.1f}%",
        )

        return papers

    def _build_query_params(self, topic: ResearchTopic, query: str) -> str:
        """Build ArXiv query string"""
        # Base query - use structured fields or legacy all: field
        if self.use_structured_query:
            q_part = self._build_structured_query(query)
        else:
            q_part = f"all:{query}"

        # Timeframe
        tf = topic.timeframe
        date_query = ""

        if isinstance(tf, TimeframeRecent):
            delta_hours = 0
            if tf.value.endswith("h"):
                delta_hours = int(tf.value[:-1])
            elif tf.value.endswith("d"):
                delta_hours = int(tf.value[:-1]) * 24

            start_dt = datetime.now(timezone.utc) - timedelta(hours=delta_hours)
            start_str = start_dt.strftime("%Y%m%d%H%M")
            date_query = f"submittedDate:[{start_str} TO 300001010000]"

        elif isinstance(tf, TimeframeSinceYear):
            start_str = f"{tf.value}01010000"
            date_query = f"submittedDate:[{start_str} TO 300001010000]"

        elif isinstance(tf, TimeframeDateRange):
            start = tf.start_date.strftime("%Y%m%d0000")
            end = tf.end_date.strftime("%Y%m%d2359")
            date_query = f"submittedDate:[{start} TO {end}]"

        if date_query:
            q_part = f"{q_part} AND {date_query}"

        encoded_q = urllib.parse.quote(q_part)

        return (
            f"search_query={encoded_q}&start=0&"
            f"max_results={topic.max_papers}&"
            f"sortBy=submittedDate&sortOrder=descending"
        )

    def _build_structured_query(self, query: str) -> str:
        """Build structured field query for ArXiv (Phase 7 Fix I1).

        Uses ti: (title) and abs: (abstract) fields for targeted search,
        with category filtering for computer science papers.

        Properly handles:
        - Quoted phrases: "machine learning" → (ti:"machine learning" OR abs:"machine learning")  # noqa: E501
        - Boolean operators: AND, OR, NOT
        - Parenthesized groups: (A OR B)
        - Complex combinations: "foo" AND (bar OR baz) NOT "qux"

        Args:
            query: User's search query

        Returns:
            Structured query string with field prefixes
        """
        # Guard against empty queries
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        # Tokenize the query respecting quotes and parentheses
        tokens = self._tokenize_query(query)

        # Process tokens to build structured query
        content_query = self._process_tokens(tokens)

        # Add category filter for computer science papers
        if self.default_categories:
            cat_parts = [f"cat:{cat}" for cat in self.default_categories]
            cat_query = f"({' OR '.join(cat_parts)})"
            return f"({content_query}) AND {cat_query}"

        return content_query

    def _tokenize_query(self, query: str) -> List[str]:
        """Tokenize query into terms, quoted phrases, operators, and parentheses.

        Args:
            query: Raw query string

        Returns:
            List of tokens preserving order and structure
        """
        tokens = []
        i = 0
        while i < len(query):
            char = query[i]

            # Skip whitespace
            if char.isspace():
                i += 1
                continue

            # Handle quoted phrases
            if char == '"':
                # Find closing quote
                j = i + 1
                while j < len(query) and query[j] != '"':
                    j += 1
                if j < len(query):
                    # Extract phrase (including quotes)
                    tokens.append(query[i : j + 1])
                    i = j + 1
                else:
                    # Unclosed quote - treat as regular char
                    i += 1
                continue

            # Handle parentheses
            if char in "()":
                tokens.append(char)
                i += 1
                continue

            # Handle words and operators
            j = i
            while j < len(query) and not query[j].isspace() and query[j] not in '"()':
                j += 1
            token = query[i:j].strip()
            if token:
                tokens.append(token)
            i = j

        return tokens

    def _process_tokens(self, tokens: List[str]) -> str:
        """Process tokens into structured ArXiv query.

        Args:
            tokens: List of tokens from _tokenize_query

        Returns:
            Structured query string
        """
        if not tokens:
            raise ValueError("No tokens to process")

        result_parts = []
        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Quoted phrase - wrap in field search
            if token.startswith('"') and token.endswith('"'):
                phrase = token[1:-1]  # Remove quotes
                result_parts.append(f'(ti:"{phrase}" OR abs:"{phrase}")')
                i += 1

            # Boolean operators - pass through
            elif token in ("AND", "OR", "NOT"):
                result_parts.append(token)
                i += 1

            # Opening parenthesis - recursively process group
            elif token == "(":
                # Find matching closing parenthesis
                depth = 1
                j = i + 1
                while j < len(tokens) and depth > 0:
                    if tokens[j] == "(":
                        depth += 1
                    elif tokens[j] == ")":
                        depth -= 1
                    j += 1

                if depth == 0:
                    # Extract group (excluding outer parentheses)
                    group_tokens = tokens[i + 1 : j - 1]
                    if group_tokens:
                        group_query = self._process_tokens(group_tokens)
                        result_parts.append(f"({group_query})")
                    i = j
                else:
                    # Unmatched parenthesis - treat as regular term
                    result_parts.append(f"(ti:{token} OR abs:{token})")
                    i += 1

            # Closing parenthesis without opening - treat as regular term
            elif token == ")":
                result_parts.append(f"(ti:{token} OR abs:{token})")
                i += 1

            # Regular term - wrap in field search
            else:
                result_parts.append(f"(ti:{token} OR abs:{token})")
                i += 1

        return " ".join(result_parts)

    def _parse_feed(self, feed) -> List[PaperMetadata]:
        papers = []
        for entry in feed.entries:
            try:
                # ID: http://arxiv.org/abs/2301.12345v1 -> 2301.12345v1
                paper_id = entry.id.split("/abs/")[-1]

                # Title
                title = entry.title.replace("\n", " ")

                # Abstract
                summary = entry.summary.replace("\n", " ")

                # Authors
                authors = [Author(name=a.name) for a in entry.authors]

                # Date
                pub_date = None
                year = None
                if hasattr(entry, "published_parsed"):
                    pub_date = datetime(*entry.published_parsed[:6])
                    year = pub_date.year

                # PDF Link (Phase 3.4: track availability)
                pdf_link = None
                pdf_available = False
                pdf_source = None
                for link in entry.links:
                    if link.type == "application/pdf":
                        raw_link = link.href
                        # Validate PDF URL for security
                        pdf_link = self._validate_pdf_url(raw_link)
                        pdf_available = True
                        pdf_source = "arxiv"
                        break

                paper = PaperMetadata(
                    paper_id=paper_id,
                    title=title,
                    abstract=summary,
                    url=entry.link,  # type: ignore
                    year=year,
                    publication_date=pub_date,
                    authors=authors,
                    citation_count=0,
                    influential_citation_count=0,
                    venue="ArXiv",
                    open_access_pdf=pdf_link,  # type: ignore
                    relevance_score=0.0,
                    # Phase 3.4: PDF availability tracking
                    pdf_available=pdf_available,
                    pdf_source=pdf_source,
                )
                papers.append(paper)

            except Exception as e:
                logger.warning(
                    "arxiv_entry_parse_error",
                    error=str(e),
                    entry_id=getattr(entry, "id", "unknown"),
                )
                continue

        return papers

    def _validate_pdf_url(self, url: str) -> str:
        """Security check for PDF URLs"""
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)

        pattern = r"^https://arxiv\.org/pdf/[\w\-\.]+(\.pdf)?$"
        if not re.match(pattern, url):
            raise SecurityError(f"Invalid ArXiv PDF URL: {url}")

        return url
