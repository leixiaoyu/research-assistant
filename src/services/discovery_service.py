import aiohttp
import asyncio
from typing import List, Optional, Any
from datetime import datetime, date, timedelta
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.models.config import ResearchTopic, TimeframeRecent, TimeframeSinceYear, TimeframeDateRange
from src.models.paper import PaperMetadata, Author
from src.utils.rate_limiter import RateLimiter

logger = structlog.get_logger()

class APIError(Exception):
    """External API error"""
    pass

class RateLimitError(APIError):
    """Rate limit exceeded"""
    pass

class DiscoveryService:
    """Search for papers using Semantic Scholar API"""

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, api_key: str, rate_limiter: Optional[RateLimiter] = None):
        self.api_key = api_key
        self.rate_limiter = rate_limiter or RateLimiter(requests_per_minute=100)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((aiohttp.ClientError, RateLimitError))
    )
    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers matching topic"""
        
        params = self._build_query_params(topic)
        
        await self.rate_limiter.acquire()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.BASE_URL,
                    params=params,
                    headers={"x-api-key": self.api_key},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    
                    if response.status == 429:
                        raise RateLimitError("Semantic Scholar rate limit exceeded")
                    
                    if response.status >= 500:
                         raise aiohttp.ClientError(f"Server error: {response.status}")
                         
                    if response.status != 200:
                        text = await response.text()
                        logger.error("api_error", status=response.status, body=text)
                        raise APIError(f"API request failed: {response.status}")

                    data = await response.json()
                    
        except asyncio.TimeoutError:
            logger.error("api_timeout", topic=topic.query)
            raise APIError("Request timed out")

        papers = self._parse_response(data)
        
        logger.info(
            "papers_discovered",
            query=topic.query,
            count=len(papers)
        )
        
        return papers

    def _build_query_params(self, topic: ResearchTopic) -> dict:
        """Convert topic to API parameters"""
        params = {
            "query": topic.query,
            "limit": topic.max_papers,
            "fields": "paperId,title,abstract,url,authors,year,publicationDate,citationCount,influentialCitationCount,venue,openAccessPdf"
        }

        # Timeframe filter
        tf = topic.timeframe
        if isinstance(tf, TimeframeRecent):
             # Semantic Scholar doesn't support "last 48h" directly in search
             # We must calculate the date.
             # Logic: parse value (e.g., 48h), subtract from now, format as YYYY-MM-DD
             # Note: API supports YYYY-MM-DD: format for range.
             
             delta_hours = 0
             if tf.value.endswith('h'):
                 delta_hours = int(tf.value[:-1])
             elif tf.value.endswith('d'):
                 delta_hours = int(tf.value[:-1]) * 24
                 
             cutoff = datetime.utcnow() - timedelta(hours=delta_hours)
             params["publicationDateOrYear"] = f"{cutoff.strftime('%Y-%m-%d')}:"

        elif isinstance(tf, TimeframeSinceYear):
            params["year"] = f"{tf.value}-"
            
        elif isinstance(tf, TimeframeDateRange):
            start = tf.start_date.isoformat()
            end = tf.end_date.isoformat()
            params["publicationDateOrYear"] = f"{start}:{end}"

        return params

    def _parse_response(self, data: dict) -> List[PaperMetadata]:
        """Parse API response into PaperMetadata models"""
        if "data" not in data or not data["data"]:
            return []

        papers = []
        for item in data["data"]:
            try:
                # Handle authors
                authors = []
                for auth in item.get("authors", []) or []:
                    if auth.get("name"):
                        authors.append(Author(
                            name=auth["name"],
                            author_id=auth.get("authorId")
                        ))

                # Handle open access PDF
                open_access_pdf = None
                oa_data = item.get("openAccessPdf")
                if oa_data and oa_data.get("url"):
                    open_access_pdf = oa_data["url"]

                # Parse dates
                pub_date = None
                if item.get("publicationDate"):
                    try:
                        pub_date = datetime.strptime(item["publicationDate"], "%Y-%m-%d")
                    except ValueError:
                        pass

                paper = PaperMetadata(
                    paper_id=item["paperId"],
                    title=item.get("title") or "Unknown Title",
                    abstract=item.get("abstract"),
                    url=item.get("url") or f"https://semanticscholar.org/paper/{item['paperId']}", # type: ignore
                    year=item.get("year"),
                    publication_date=pub_date,
                    authors=authors,
                    citation_count=item.get("citationCount", 0),
                    influential_citation_count=item.get("influentialCitationCount", 0),
                    venue=item.get("venue"),
                    open_access_pdf=open_access_pdf, # type: ignore
                    relevance_score=0.0
                )
                papers.append(paper)
            except Exception as e:
                logger.warning("paper_parsing_failed", paper_id=item.get("paperId"), error=str(e))
                continue
                
        return papers
