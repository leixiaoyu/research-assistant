"""Citation Explorer for Phase 7.2: Discovery Expansion.

Explores citation networks to discover related papers through
forward citations (papers citing this one) and backward citations
(papers this one cites).
"""

from typing import List, Optional, Set, TYPE_CHECKING

import aiohttp
import structlog
from pydantic import BaseModel, Field

from src.models.config import CitationExplorationConfig
from src.models.paper import PaperMetadata, Author
from src.utils.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from src.services.registry_service import RegistryService

logger = structlog.get_logger()


class CitationStats(BaseModel):
    """Statistics from citation exploration."""

    seed_papers_count: int = 0
    forward_discovered: int = 0
    backward_discovered: int = 0
    filtered_as_duplicate: int = 0
    depth_reached: int = 0


class CitationExplorationResult(BaseModel):
    """Results from citation exploration."""

    forward_papers: List[PaperMetadata] = Field(default_factory=list)
    backward_papers: List[PaperMetadata] = Field(default_factory=list)
    stats: CitationStats = Field(default_factory=CitationStats)


class CitationExplorer:
    """Explores citation networks for discovered papers.

    Uses Semantic Scholar API to fetch forward and backward citations
    for seed papers, enabling discovery of related research.
    """

    CITATIONS_URL = (
        "https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
    )
    REFERENCES_URL = (
        "https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references"
    )
    FIELDS = (
        "paperId,title,abstract,url,authors,year,"
        "publicationDate,citationCount,venue,openAccessPdf"
    )

    def __init__(
        self,
        api_key: str,
        registry_service: Optional["RegistryService"] = None,
        config: Optional[CitationExplorationConfig] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        """Initialize CitationExplorer.

        Args:
            api_key: Semantic Scholar API key
            registry_service: Registry for duplicate detection
            config: Citation exploration configuration
            rate_limiter: Rate limiter for API calls
        """
        self.api_key = api_key
        self.registry = registry_service
        self.config = config or CitationExplorationConfig()
        self.rate_limiter = rate_limiter or RateLimiter(requests_per_minute=100)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def explore(
        self,
        seed_papers: List[PaperMetadata],
        topic_slug: str,
    ) -> CitationExplorationResult:
        """Explore citations for seed papers.

        Args:
            seed_papers: List of papers to explore citations for
            topic_slug: Topic slug for registry lookup

        Returns:
            CitationExplorationResult with discovered papers
        """
        if not self.config.enabled:
            logger.info("citation_exploration_disabled")
            return CitationExplorationResult()

        stats = CitationStats(seed_papers_count=len(seed_papers))
        forward_papers: List[PaperMetadata] = []
        backward_papers: List[PaperMetadata] = []
        seen_ids: Set[str] = set()

        # Track seen papers from seed
        for paper in seed_papers:
            if paper.paper_id:
                seen_ids.add(paper.paper_id)
            if paper.doi:
                seen_ids.add(paper.doi)

        try:
            for paper in seed_papers:
                # Get forward citations (papers citing this one)
                if self.config.forward:
                    new_papers = await self.get_forward_citations(
                        paper,
                        max_results=self.config.max_forward_per_paper,
                    )
                    for p in new_papers:
                        if self._is_new_paper(p, seen_ids, topic_slug):
                            p = p.model_copy(
                                update={"discovery_method": "forward_citation"}
                            )
                            forward_papers.append(p)
                            self._mark_seen(p, seen_ids)
                        else:
                            stats.filtered_as_duplicate += 1

                # Get backward citations (papers this one cites)
                if self.config.backward:
                    new_papers = await self.get_backward_citations(
                        paper,
                        max_results=self.config.max_backward_per_paper,
                    )
                    for p in new_papers:
                        if self._is_new_paper(p, seen_ids, topic_slug):
                            p = p.model_copy(
                                update={"discovery_method": "backward_citation"}
                            )
                            backward_papers.append(p)
                            self._mark_seen(p, seen_ids)
                        else:
                            stats.filtered_as_duplicate += 1

            stats.forward_discovered = len(forward_papers)
            stats.backward_discovered = len(backward_papers)
            stats.depth_reached = 1  # Currently only depth 1 supported

            logger.info(
                "citation_exploration_complete",
                seed_papers=len(seed_papers),
                forward_discovered=stats.forward_discovered,
                backward_discovered=stats.backward_discovered,
                filtered_duplicates=stats.filtered_as_duplicate,
            )

            return CitationExplorationResult(
                forward_papers=forward_papers,
                backward_papers=backward_papers,
                stats=stats,
            )

        except Exception as e:
            logger.exception("citation_exploration_error", error=str(e))
            return CitationExplorationResult(stats=stats)

    async def get_forward_citations(
        self,
        paper: PaperMetadata,
        max_results: int = 10,
    ) -> List[PaperMetadata]:
        """Get papers that cite this paper.

        Args:
            paper: Paper to get citations for
            max_results: Maximum number of citations to fetch

        Returns:
            List of citing papers
        """
        paper_id = paper.paper_id
        if not paper_id:
            return []

        url = self.CITATIONS_URL.format(paper_id=paper_id)
        params: dict[str, str] = {
            "fields": f"citingPaper.{self.FIELDS}",
            "limit": str(min(max_results, 100)),
        }

        try:
            await self.rate_limiter.acquire()
            return await self._fetch_citations(
                url, params, paper_id, "citingPaper", "forward_citation"
            )
        except Exception as e:
            logger.warning("forward_citation_error", paper_id=paper_id, error=str(e))
            return []

    async def get_backward_citations(
        self,
        paper: PaperMetadata,
        max_results: int = 10,
    ) -> List[PaperMetadata]:
        """Get papers cited by this paper (references).

        Args:
            paper: Paper to get references for
            max_results: Maximum number of references to fetch

        Returns:
            List of referenced papers
        """
        paper_id = paper.paper_id
        if not paper_id:
            return []

        url = self.REFERENCES_URL.format(paper_id=paper_id)
        params: dict[str, str] = {
            "fields": f"citedPaper.{self.FIELDS}",
            "limit": str(min(max_results, 100)),
        }

        try:
            await self.rate_limiter.acquire()
            return await self._fetch_citations(
                url, params, paper_id, "citedPaper", "backward_citation"
            )
        except Exception as e:
            logger.warning("backward_citation_error", paper_id=paper_id, error=str(e))
            return []

    async def _fetch_citations(
        self,
        url: str,
        params: dict,
        paper_id: str,
        result_key: str,
        error_prefix: str,
    ) -> List[PaperMetadata]:  # pragma: no cover
        """Fetch citations from Semantic Scholar API.

        This method is excluded from coverage as it requires real network
        calls. The HTTP context manager pattern cannot be easily mocked
        for unit tests. Integration tests should cover this path.

        Args:
            url: API endpoint URL
            params: Query parameters
            paper_id: Paper ID for logging
            result_key: Key to extract from response (citingPaper/citedPaper)
            error_prefix: Prefix for error logging

        Returns:
            List of parsed papers
        """
        session = await self._get_session()

        async with session.get(
            url,
            params=params,
            headers={"x-api-key": self.api_key},
        ) as response:
            if response.status == 429:
                logger.warning(f"{error_prefix}_rate_limit", paper_id=paper_id)
                return []
            if response.status != 200:
                logger.warning(
                    f"{error_prefix}_api_error",
                    paper_id=paper_id,
                    status=response.status,
                )
                return []

            data = await response.json()

        papers = []
        for item in data.get("data", []):
            paper_data = item.get(result_key, {})
            if paper_data:
                parsed = self._parse_paper(paper_data, "semantic_scholar")
                if parsed:
                    papers.append(parsed)

        return papers

    def _parse_paper(
        self,
        data: dict,
        source: str,
    ) -> Optional[PaperMetadata]:
        """Parse Semantic Scholar paper data to PaperMetadata.

        Args:
            data: Raw paper data from API
            source: Discovery source name

        Returns:
            PaperMetadata or None if required fields missing
        """
        paper_id = data.get("paperId")
        title = data.get("title")

        if not paper_id or not title:
            return None

        # Parse authors
        authors = []
        for auth in data.get("authors", []) or []:
            name = auth.get("name")
            if name:
                authors.append(Author(name=name, author_id=auth.get("authorId")))

        # Parse PDF URL
        pdf_url = None
        pdf_available = False
        oa_data = data.get("openAccessPdf")
        if oa_data and oa_data.get("url"):
            pdf_url = oa_data["url"]
            pdf_available = True

        # Build URL
        url = data.get("url") or f"https://semanticscholar.org/paper/{paper_id}"

        return PaperMetadata(
            paper_id=paper_id,
            title=title,
            abstract=data.get("abstract"),
            url=url,  # type: ignore[arg-type]
            authors=authors,
            year=data.get("year"),
            publication_date=data.get("publicationDate"),
            venue=data.get("venue"),
            citation_count=data.get("citationCount", 0),
            influential_citation_count=data.get(
                "influentialCitationCount"
            ),  # SS provides this
            relevance_score=0.0,
            quality_score=0.0,
            open_access_pdf=pdf_url,  # type: ignore[arg-type]
            pdf_available=pdf_available,
            pdf_source="open_access" if pdf_available else None,
            discovery_source=source,
            discovery_method=None,  # Will be set by caller
            source_count=1,
            ranking_score=None,
        )

    def _is_new_paper(
        self,
        paper: PaperMetadata,
        seen_ids: Set[str],
        topic_slug: str,
    ) -> bool:
        """Check if paper is new (not seen and not in registry).

        Args:
            paper: Paper to check
            seen_ids: Set of already seen IDs
            topic_slug: Topic slug for registry lookup

        Returns:
            True if paper is new
        """
        # Check seen IDs
        if paper.paper_id and paper.paper_id in seen_ids:
            return False
        if paper.doi and paper.doi in seen_ids:
            return False

        # Check registry if configured
        if self.config.respect_registry and self.registry:
            match = self.registry.resolve_identity(paper)
            if match.matched:
                return False

        return True

    def _mark_seen(self, paper: PaperMetadata, seen_ids: Set[str]) -> None:
        """Mark paper as seen.

        Args:
            paper: Paper to mark
            seen_ids: Set to add IDs to
        """
        if paper.paper_id:
            seen_ids.add(paper.paper_id)
        if paper.doi:
            seen_ids.add(paper.doi)

    async def __aenter__(self) -> "CitationExplorer":
        """Async context manager entry."""
        return self

    async def __aexit__(self, *args) -> None:
        """Async context manager exit."""
        await self.close()
