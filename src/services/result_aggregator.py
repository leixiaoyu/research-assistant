"""Result Aggregator for Phase 7.2: Discovery Expansion.

Merges and ranks papers from multiple discovery sources with
intelligent deduplication and quality-based ranking.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

import structlog
from pydantic import BaseModel, Field

from src.models.config import AggregationConfig, RankingWeights
from src.models.paper import PaperMetadata

if TYPE_CHECKING:
    from src.services.registry_service import RegistryService

logger = structlog.get_logger()


class AggregationResult(BaseModel):
    """Results from aggregation."""

    papers: List[PaperMetadata] = Field(default_factory=list)
    source_breakdown: Dict[str, int] = Field(default_factory=dict)
    total_raw: int = 0
    total_after_dedup: int = 0
    ranking_applied: bool = False


class ResultAggregator:
    """Aggregates results from multiple discovery sources.

    Handles deduplication across sources, metadata merging,
    and quality-based ranking.
    """

    # Title similarity threshold for fuzzy matching
    TITLE_SIMILARITY_THRESHOLD = 0.9

    def __init__(
        self,
        registry_service: Optional["RegistryService"] = None,
        config: Optional[AggregationConfig] = None,
    ):
        """Initialize ResultAggregator.

        Args:
            registry_service: Registry for duplicate detection
            config: Aggregation configuration
        """
        self.registry = registry_service
        self.config = config or AggregationConfig()

    async def aggregate(
        self,
        source_results: Dict[str, List[PaperMetadata]],
    ) -> AggregationResult:
        """Aggregate results from multiple sources.

        Args:
            source_results: Dict mapping source name to list of papers

        Returns:
            AggregationResult with deduplicated, ranked papers
        """
        # 1. Count total raw papers
        total_raw = sum(len(papers) for papers in source_results.values())

        # 2. Build source breakdown
        source_breakdown = {
            source: len(papers) for source, papers in source_results.items()
        }

        # 3. Flatten and set discovery_source
        all_papers: List[PaperMetadata] = []
        for source, papers in source_results.items():
            for paper in papers:
                # Set discovery_source if not already set
                if not paper.discovery_source:
                    paper = paper.model_copy(update={"discovery_source": source})
                all_papers.append(paper)

        # 4. Deduplicate
        deduplicated = self._deduplicate(all_papers)

        # 5. Rank papers
        ranked = self._rank(deduplicated)

        # 6. Apply limit if configured
        if self.config.max_papers_per_topic > 0:
            ranked = ranked[: self.config.max_papers_per_topic]

        logger.info(
            "aggregation_complete",
            total_raw=total_raw,
            after_dedup=len(deduplicated),
            after_ranking=len(ranked),
            source_breakdown=source_breakdown,
        )

        return AggregationResult(
            papers=ranked,
            source_breakdown=source_breakdown,
            total_raw=total_raw,
            total_after_dedup=len(deduplicated),
            ranking_applied=True,
        )

    def _deduplicate(self, papers: List[PaperMetadata]) -> List[PaperMetadata]:
        """Remove duplicates across sources using Union-Find algorithm.

        Uses a Connected Components approach where papers sharing ANY identifier
        (DOI, ArXiv ID, paper_id, or normalized title) are grouped together.
        This prevents losing unique papers when identifiers partially overlap.

        Args:
            papers: List of papers to deduplicate

        Returns:
            Deduplicated list with merged metadata
        """
        if not papers:
            return []

        n = len(papers)

        # Union-Find data structure
        parent = list(range(n))
        rank = [0] * n

        def find(x: int) -> int:
            """Find with path compression."""
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x: int, y: int) -> None:
            """Union by rank."""
            px, py = find(x), find(y)
            if px == py:
                return
            if rank[px] < rank[py]:
                px, py = py, px
            parent[py] = px
            if rank[px] == rank[py]:
                rank[px] += 1

        # Build identifier -> paper indices mapping
        doi_map: Dict[str, List[int]] = {}
        arxiv_map: Dict[str, List[int]] = {}
        paper_id_map: Dict[str, List[int]] = {}
        title_map: Dict[str, List[int]] = {}

        for i, paper in enumerate(papers):
            # Track DOI
            if paper.doi:
                key = f"doi:{paper.doi.lower().strip()}"
                if key not in doi_map:
                    doi_map[key] = []
                doi_map[key].append(i)

            # Track ArXiv ID
            if paper.arxiv_id:
                key = f"arxiv:{paper.arxiv_id.lower().strip()}"
                if key not in arxiv_map:
                    arxiv_map[key] = []
                arxiv_map[key].append(i)

            # Track paper_id
            if paper.paper_id:
                key = f"pid:{paper.paper_id}"
                if key not in paper_id_map:
                    paper_id_map[key] = []
                paper_id_map[key].append(i)

            # Track normalized title
            norm_title = self._normalize_title(paper.title)
            if norm_title:
                key = f"title:{norm_title}"
                if key not in title_map:
                    title_map[key] = []
                title_map[key].append(i)

        # Union papers sharing any identifier
        for indices in doi_map.values():
            for j in range(1, len(indices)):
                union(indices[0], indices[j])

        for indices in arxiv_map.values():
            for j in range(1, len(indices)):
                union(indices[0], indices[j])

        for indices in paper_id_map.values():
            for j in range(1, len(indices)):
                union(indices[0], indices[j])

        for indices in title_map.values():
            for j in range(1, len(indices)):
                union(indices[0], indices[j])

        # Group papers by their root component
        components: Dict[int, List[PaperMetadata]] = {}
        for i, paper in enumerate(papers):
            root = find(i)
            if root not in components:
                components[root] = []
            components[root].append(paper)

        # Merge each component and collect results
        result: List[PaperMetadata] = []
        for group in components.values():
            merged = self._merge_group(group)
            result.append(merged)

        return result

    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison.

        Args:
            title: Paper title

        Returns:
            Normalized title string
        """
        # Lowercase, strip, remove extra spaces
        normalized = " ".join(title.lower().split())
        # Remove common punctuation
        for char in ".,;:!?()-\"'":
            normalized = normalized.replace(char, "")
        return normalized

    def _merge_group(self, papers: List[PaperMetadata]) -> PaperMetadata:
        """Merge metadata from multiple papers representing the same work.

        Strategy: prefer non-None values, higher citation counts,
        and combine source information.

        Args:
            papers: List of duplicate papers to merge

        Returns:
            Single merged PaperMetadata
        """
        if len(papers) == 1:
            return papers[0].model_copy(update={"source_count": 1})

        # Start with the paper that has the most complete metadata
        base = max(papers, key=lambda p: self._metadata_completeness(p))

        # Collect sources
        sources: Set[str] = set()
        for p in papers:
            if p.discovery_source:
                sources.add(p.discovery_source)

        # Merge fields from all papers
        merged_data: Dict[str, Any] = {
            "source_count": len(papers),
        }

        # Take best values
        best_citation_count = max(p.citation_count or 0 for p in papers)
        if best_citation_count > (base.citation_count or 0):
            merged_data["citation_count"] = best_citation_count

        # Take first non-None values for optional fields
        for field in ["doi", "arxiv_id", "abstract", "venue", "open_access_pdf"]:
            base_value = getattr(base, field)
            if base_value is None:
                for p in papers:
                    value = getattr(p, field)
                    if value is not None:  # pragma: no cover - defensive fill
                        merged_data[field] = value
                        break

        # Set PDF availability
        if any(p.pdf_available for p in papers):
            merged_data["pdf_available"] = True
            # Get PDF source from first paper with PDF
            for p in papers:
                if p.pdf_available and p.pdf_source:
                    merged_data["pdf_source"] = p.pdf_source
                    break

        return base.model_copy(update=merged_data)

    def _metadata_completeness(self, paper: PaperMetadata) -> int:
        """Score metadata completeness.

        Args:
            paper: Paper to score

        Returns:
            Completeness score (higher = more complete)
        """
        score = 0
        if paper.doi:
            score += 3
        if paper.abstract:
            score += 2
        if paper.authors:
            score += 1
        if paper.venue:
            score += 1
        if paper.pdf_available:
            score += 2
        if paper.citation_count and paper.citation_count > 0:
            score += 1
        return score

    def _rank(self, papers: List[PaperMetadata]) -> List[PaperMetadata]:
        """Rank papers by composite score.

        Score components (configurable weights):
        - citation_count: normalized by log scale
        - recency: based on publication date
        - source_count: papers found by multiple sources
        - pdf_availability: binary score

        Args:
            papers: Papers to rank

        Returns:
            Sorted list of papers with ranking_score set
        """
        weights = self.config.ranking_weights

        ranked_papers = []
        for paper in papers:
            score = self._calculate_score(paper, weights)
            updated = paper.model_copy(update={"ranking_score": score})
            ranked_papers.append(updated)

        return sorted(ranked_papers, key=lambda p: p.ranking_score or 0, reverse=True)

    def _calculate_score(
        self,
        paper: PaperMetadata,
        weights: RankingWeights,
    ) -> float:
        """Calculate composite ranking score.

        Args:
            paper: Paper to score
            weights: Ranking weights

        Returns:
            Score between 0 and 1
        """
        import math

        # Normalize citation count (log scale, cap effective at ~1000)
        citation_count = paper.citation_count or 0
        if citation_count > 0:
            # log10(1001) ≈ 3, so divide by 3 to normalize to ~1
            citation_score = min(1.0, math.log10(citation_count + 1) / 3)
        else:
            citation_score = 0.0

        # Calculate recency score
        recency_score = self._calculate_recency_score(paper)

        # Source count score (multi-source papers more valuable)
        # 3+ sources = max score
        source_score = min(1.0, (paper.source_count or 1) / 3)

        # PDF availability is binary
        pdf_score = 1.0 if paper.pdf_available else 0.0

        return (
            weights.citation_count * citation_score
            + weights.recency * recency_score
            + weights.source_count * source_score
            + weights.pdf_availability * pdf_score
        )

    def _calculate_recency_score(self, paper: PaperMetadata) -> float:
        """Calculate recency score (0-1, higher = more recent).

        Args:
            paper: Paper to score

        Returns:
            Recency score
        """
        if not paper.publication_date and not paper.year:
            return 0.5  # Unknown date gets neutral score

        # Use publication_date if available, else estimate from year
        if paper.publication_date:
            if isinstance(
                paper.publication_date, str
            ):  # pragma: no cover - Pydantic validates
                try:
                    pub_date = datetime.fromisoformat(paper.publication_date)
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                except ValueError:
                    pub_date = datetime(paper.year or 2020, 6, 15, tzinfo=timezone.utc)
            else:
                pub_date = paper.publication_date
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
        else:
            pub_date = datetime(paper.year or 2020, 6, 15, tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        days_old = (now - pub_date).days

        # Papers less than 1 year old get 1.0, decay linearly over 5 years
        if days_old <= 365:
            return 1.0
        elif days_old >= 365 * 5:
            return 0.0
        else:
            return 1.0 - (days_old - 365) / (365 * 4)
