import feedparser
import asyncio
import re
from typing import List, Optional
from datetime import datetime, timedelta
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.services.providers.base import DiscoveryProvider, APIError, RateLimitError
from src.models.config import ResearchTopic, TimeframeRecent, TimeframeSinceYear, TimeframeDateRange
from src.models.paper import PaperMetadata, Author
from src.utils.rate_limiter import RateLimiter
from src.utils.security import SecurityError

logger = structlog.get_logger()

class ArxivProvider(DiscoveryProvider):
    """Search for papers using ArXiv API"""

    BASE_URL = "https://export.arxiv.org/api/query"

    def __init__(self, rate_limiter: Optional[RateLimiter] = None):
        # ArXiv requires 3 seconds between requests
        self.rate_limiter = rate_limiter or RateLimiter(
            requests_per_minute=20, # 60/3 = 20
            burst_size=1
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
        # Allow alphanumeric, spaces, and basic boolean operators/syntax chars
        # Explicitly disallow shell special chars that shouldn't be in a query
        if not re.match(r'^[a-zA-Z0-9\s\-_+.,"():|]+$', query):
             # Check for "AND", "OR", "NOT" explicitly? 
             # The regex above allows them as letters.
             # It blocks things like `$` (shell var), `;` (command chain), etc.
             raise ValueError("Invalid ArXiv query syntax: contains forbidden characters")
        return query

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=3, max=10),
        retry=retry_if_exception_type((APIError, RateLimitError))
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
            feed = await loop.run_in_executor(None, lambda: feedparser.parse(self.BASE_URL + "?" + params))
        except Exception as e:
            logger.error("arxiv_network_error", error=str(e))
            raise APIError(f"ArXiv request failed: {e}")

        # 5. Check Status
        if hasattr(feed, 'status') and feed.status != 200:
             if feed.status == 403: # Forbidden (often rate limit)
                 raise RateLimitError("ArXiv rate limit exceeded (403)")
             raise APIError(f"ArXiv API returned status {feed.status}")

        if hasattr(feed, 'bozo') and feed.bozo:
             logger.warning("arxiv_feed_parse_warning", error=str(feed.bozo_exception))
             # We continue, as bozo often triggers on minor XML issues but data is usable

        # 6. Parse
        papers = self._parse_feed(feed)
        
        logger.info(
            "papers_discovered",
            query=topic.query,
            count=len(papers),
            provider="arxiv"
        )
        
        return papers

    def _build_query_params(self, topic: ResearchTopic, query: str) -> str:
        """Build ArXiv query string"""
        # Base query
        q_part = f"all:{query}"
        
        # Timeframe
        tf = topic.timeframe
        date_query = ""
        
        if isinstance(tf, TimeframeRecent):
             # last N hours/days
             delta_hours = 0
             if tf.value.endswith('h'):
                 delta_hours = int(tf.value[:-1])
             elif tf.value.endswith('d'):
                 delta_hours = int(tf.value[:-1]) * 24
             
             start_dt = datetime.utcnow() - timedelta(hours=delta_hours)
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

        import urllib.parse
        encoded_q = urllib.parse.quote(q_part)
        
        return f"search_query={encoded_q}&start=0&max_results={topic.max_papers}&sortBy=submittedDate&sortOrder=descending"

    def _parse_feed(self, feed) -> List[PaperMetadata]:
        papers = []
        for entry in feed.entries:
            try:
                # ID: http://arxiv.org/abs/2301.12345v1 -> 2301.12345v1
                paper_id = entry.id.split('/abs/')[-1]
                
                # Title
                title = entry.title.replace('\n', ' ')
                
                # Abstract
                summary = entry.summary.replace('\n', ' ')
                
                # Authors
                authors = [Author(name=a.name) for a in entry.authors]
                
                # Date
                pub_date = None
                year = None
                if hasattr(entry, 'published_parsed'):
                    pub_date = datetime(*entry.published_parsed[:6])
                    year = pub_date.year
                
                # PDF Link
                pdf_link = None
                for link in entry.links:
                    if link.type == 'application/pdf':
                        raw_link = link.href
                        # Validate PDF URL for security
                        pdf_link = self._validate_pdf_url(raw_link)
                        break
                
                paper = PaperMetadata(
                    paper_id=paper_id,
                    title=title,
                    abstract=summary,
                    url=entry.link,
                    year=year,
                    publication_date=pub_date,
                    authors=authors,
                    citation_count=0, # ArXiv doesn't provide this
                    venue="ArXiv",
                    open_access_pdf=pdf_link, # type: ignore
                    relevance_score=0.0 # Default
                )
                papers.append(paper)
                
            except Exception as e:
                logger.warning("arxiv_entry_parse_error", error=str(e), entry_id=getattr(entry, 'id', 'unknown'))
                continue
                
        return papers

    def _validate_pdf_url(self, url: str) -> str:
        """Security check for PDF URLs"""
        # ArXiv PDF pattern: https://arxiv.org/pdf/2301.12345.pdf or ...v1.pdf
        # Also allow http for now? No, strict HTTPS preferred, but feed might return http.
        # Let's enforce HTTPS if possible, or upgrade it.
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)
            
        pattern = r'^https://arxiv\.org/pdf/[\w\-\.]+(\.pdf)?$' # Escaped the dot in .org and .pdf
        if not re.match(pattern, url):
             # It might be valid but unusual. Log warning? 
             # Spec said "Validate ArXiv PDF URLs match expected pattern".
             # Strict mode: raise error.
             raise SecurityError(f"Invalid ArXiv PDF URL: {url}")
        
        return url