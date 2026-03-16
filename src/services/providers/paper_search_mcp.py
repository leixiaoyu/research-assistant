"""Paper Search MCP provider for Phase 7.2: Discovery Expansion.

Connects to Paper Search MCP server for unified multi-source queries
across arXiv, PubMed, bioRxiv, medRxiv, Google Scholar, and Semantic Scholar.
"""

import re
from typing import List, Optional, Dict, Any
from datetime import datetime
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.services.providers.base import (
    DiscoveryProvider,
    APIError,
    RateLimitError,
)
from src.models.config import ResearchTopic
from src.models.paper import PaperMetadata, Author
from src.utils.rate_limiter import RateLimiter

logger = structlog.get_logger()


class PaperSearchMCPProvider(DiscoveryProvider):
    """Search for papers using Paper Search MCP server.

    Provides unified access to multiple academic search sources:
    - arXiv: Preprint repository
    - PubMed: Biomedical literature
    - bioRxiv: Biology preprints
    - medRxiv: Medical preprints
    - Google Scholar: Broad academic search
    - Semantic Scholar: AI-powered academic search

    Features:
    - Graceful degradation when MCP unavailable
    - Per-source result tracking
    - Automatic discovery_source tagging
    - Rate limiting for MCP endpoints

    Note:
        This provider is currently a placeholder implementation awaiting
        the MCP client library. When the MCP server is unavailable (default),
        it gracefully degrades by returning empty results. The data mapping
        and validation logic is fully implemented and ready for MCP integration.
    """

    DEFAULT_SOURCES = [
        "arxiv",
        "pubmed",
        "biorxiv",
        "medrxiv",
        "google_scholar",
        "semantic_scholar",
    ]

    def __init__(
        self,
        mcp_endpoint: str = "localhost:50051",
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Initialize MCP provider.

        Args:
            mcp_endpoint: MCP server endpoint (host:port)
            rate_limiter: Optional rate limiter instance
        """
        self.endpoint = mcp_endpoint
        self._available = False
        self._checked_availability = False
        # Conservative rate limiting for MCP aggregation
        self.rate_limiter = rate_limiter or RateLimiter(
            requests_per_minute=30, burst_size=5
        )

    @property
    def name(self) -> str:
        """Provider name for logging and identification."""
        return "paper_search_mcp"

    @property
    def requires_api_key(self) -> bool:
        """MCP handles authentication internally."""
        return False

    def validate_query(self, query: str) -> str:
        """Validate query against MCP-compatible syntax.

        Args:
            query: User-provided search query

        Returns:
            Validated and sanitized query string

        Raises:
            ValueError: If query contains invalid syntax
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")

        if len(query) > 500:
            raise ValueError("Query too long (max 500 characters)")

        # Check for control characters (excluding common whitespace)
        if any(ord(c) < 32 for c in query if c not in "\t\n\r"):
            raise ValueError("Query contains invalid control characters")

        # Allow alphanumeric, spaces, and common search operators
        if not re.match(r'^[a-zA-Z0-9\s\-_+.,"():|&]+$', query):
            raise ValueError("Query contains forbidden characters")

        return query.strip()

    async def health_check(self) -> bool:
        """Check if MCP server is available.

        Returns:
            True if MCP server is reachable, False otherwise
        """
        if self._checked_availability:
            return self._available

        try:
            # TODO: Implement actual MCP health check when MCP client is available
            # For now, assume unavailable (graceful degradation)
            logger.info(
                "mcp_health_check",
                endpoint=self.endpoint,
                status="not_implemented",
            )
            self._available = False
            self._checked_availability = True
            return False
        except Exception as e:  # pragma: no cover - MCP client not yet available
            logger.warning(
                "mcp_health_check_failed", endpoint=self.endpoint, error=str(e)
            )
            self._available = False
            self._checked_availability = True
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APIError, RateLimitError)),
    )
    async def search(
        self, topic: ResearchTopic, sources: Optional[List[str]] = None
    ) -> List[PaperMetadata]:
        """Search for papers via MCP server.

        Args:
            topic: Research topic configuration
            sources: Optional list of sources to query (defaults to all)

        Returns:
            List of PaperMetadata objects with discovery_source set

        Raises:
            APIError: If MCP request fails (after retries)
            RateLimitError: If rate limit exceeded
        """
        # 1. Validate Query
        try:
            safe_query = self.validate_query(topic.query)
        except ValueError as e:  # pragma: no cover - defensive validation
            logger.error("invalid_mcp_query", query=topic.query, error=str(e))
            return []

        # 2. Check MCP Availability (graceful degradation)
        is_available = await self.health_check()
        if not is_available:
            logger.warning(
                "mcp_unavailable",
                endpoint=self.endpoint,
                note="Gracefully degrading - returning empty results",
            )
            return []

        # MCP client integration - Phase 7.3
        # When MCP becomes available, implement actual query here
        return await self._execute_mcp_search(safe_query, topic, sources)

    async def _execute_mcp_search(
        self,
        query: str,
        topic: ResearchTopic,
        sources: Optional[List[str]],
    ) -> List[PaperMetadata]:  # pragma: no cover
        """Execute MCP search (placeholder - requires MCP client library).

        This method is excluded from coverage as it requires the MCP client
        library which is not yet available. When MCP is integrated, remove
        the pragma and add proper tests.

        Args:
            query: Validated search query
            topic: Research topic with timeframe
            sources: List of sources to query

        Returns:
            List of PaperMetadata with discovery_source set
        """
        query_sources = sources or self.DEFAULT_SOURCES
        await self.rate_limiter.acquire(requester_id="paper_search_mcp")

        # Placeholder: MCP client call would go here
        # results = await mcp_client.search(query, sources=query_sources)
        results: List[Dict[str, Any]] = []

        papers = self._map_mcp_results(results)
        self._log_source_breakdown(papers, topic.query)

        logger.info(
            "papers_discovered",
            query=topic.query,
            count=len(papers),
            provider="paper_search_mcp",
            sources=query_sources,
        )
        return papers

    def _map_mcp_results(
        self, results: List[Dict[str, Any]]
    ) -> List[PaperMetadata]:  # pragma: no cover
        """Map MCP results to PaperMetadata objects.

        Args:
            results: Raw MCP search results

        Returns:
            List of PaperMetadata with discovery_source set
        """
        papers = []
        for result in results:
            try:
                paper = self._map_mcp_result_to_paper(
                    result, result.get("source", "unknown")
                )
                papers.append(paper)
            except Exception as e:
                logger.warning(
                    "mcp_result_parse_error",
                    error=str(e),
                    result_id=result.get("id", "unknown"),
                )
        return papers

    def _map_mcp_result_to_paper(
        self, result: Dict[str, Any], source: str
    ) -> PaperMetadata:
        """Map single MCP result to PaperMetadata.

        Args:
            result: Single MCP search result
            source: Source identifier (arxiv, pubmed, etc.)

        Returns:
            PaperMetadata with discovery_source and discovery_method set
        """
        # Extract authors
        authors = []
        for author_data in result.get("authors", []):
            if isinstance(author_data, str):
                authors.append(Author(name=author_data))
            elif isinstance(author_data, dict) and author_data.get("name"):
                authors.append(
                    Author(
                        name=author_data["name"],
                        author_id=author_data.get("id"),
                        affiliation=author_data.get("affiliation"),
                    )
                )

        # Parse publication date
        pub_date = None
        year = None
        if result.get("publication_date"):
            try:
                pub_date = datetime.fromisoformat(result["publication_date"])
                year = pub_date.year
            except (ValueError, TypeError):
                # Try alternative formats
                if result.get("year"):
                    year = int(result["year"])

        # Extract PDF information
        pdf_link = result.get("pdf_url")
        pdf_available = bool(pdf_link)
        pdf_source = source if pdf_available else None

        return PaperMetadata(
            paper_id=result.get("id", f"mcp_{source}_{hash(result.get('title', ''))}"),
            doi=result.get("doi"),
            arxiv_id=result.get("arxiv_id"),
            title=result.get("title", "Unknown Title"),
            abstract=result.get("abstract"),
            url=result.get("url") or f"https://{source}.org/unknown",  # type: ignore
            open_access_pdf=pdf_link,  # type: ignore
            authors=authors,
            year=year,
            publication_date=pub_date,
            venue=result.get("venue") or result.get("journal"),
            citation_count=result.get("citation_count", 0),
            influential_citation_count=result.get("influential_citation_count", 0),
            relevance_score=result.get("relevance_score", 0.0),
            quality_score=result.get("quality_score", 0.0),
            # Phase 3.4: PDF availability tracking
            pdf_available=pdf_available,
            pdf_source=pdf_source,
            # Phase 7.2: Multi-source tracking
            discovery_source=source,
            discovery_method="keyword",  # Default to keyword search
            source_count=1,  # Will be updated by aggregator
        )

    def _log_source_breakdown(self, papers: List[PaperMetadata], query: str) -> None:
        """Log detailed breakdown of papers by source.

        Args:
            papers: List of discovered papers
            query: Original search query
        """
        if not papers:
            logger.info("mcp_source_breakdown", query=query, total=0, sources={})
            return

        # Count papers per source
        source_counts: Dict[str, int] = {}
        for paper in papers:
            source = paper.discovery_source or "unknown"
            source_counts[source] = source_counts.get(source, 0) + 1

        # Calculate percentages
        total = len(papers)
        source_breakdown = {
            source: {
                "count": count,
                "percentage": f"{(count / total * 100):.1f}%",
            }
            for source, count in source_counts.items()
        }

        logger.info(
            "mcp_source_breakdown",
            query=query,
            total=total,
            sources=source_breakdown,
        )
