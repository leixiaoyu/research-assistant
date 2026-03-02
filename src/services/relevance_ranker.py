"""Relevance Ranker for Phase 6: Enhanced Discovery Pipeline.

LLM-based semantic relevance ranking for academic papers.
Scores papers against the research query and filters by threshold.

Usage:
    from src.services.relevance_ranker import RelevanceRanker
    from src.services.llm import LLMService

    llm_service = LLMService(...)
    ranker = RelevanceRanker(llm_service, min_relevance_score=0.5)
    ranked_papers = await ranker.rank(scored_papers, "Tree of Thoughts")
"""

import asyncio
import json
import re
from collections import OrderedDict
from typing import List, Optional, TYPE_CHECKING

import structlog

from src.models.discovery import ScoredPaper

if TYPE_CHECKING:
    from src.services.llm import LLMService

logger = structlog.get_logger()

# Relevance scoring prompt template
# fmt: off
RELEVANCE_PROMPT = (  # noqa: E501
    "You are an academic research relevance evaluator. Score how relevant "
    "each paper is to the research query on a scale of 0.0 to 1.0.\n\n"
    "Research Query: {query}\n\n"
    "Papers to evaluate:\n{papers_json}\n\n"
    "Scoring criteria:\n"
    "- 0.9-1.0: Directly addresses the exact topic\n"
    "- 0.7-0.8: Highly relevant methodology or application\n"
    "- 0.5-0.6: Related but tangential\n"
    "- 0.3-0.4: Loosely related\n"
    "- 0.0-0.2: Not relevant\n\n"
    "Output ONLY a JSON array of scores in the same order as the papers:\n"
    "[0.85, 0.72, 0.45, ...]"
)
# fmt: on


class RelevanceRanker:
    """LLM-based semantic relevance ranking for academic papers.

    Scores papers using an LLM to evaluate semantic relevance to the
    research query, then filters and ranks by combined scores.

    Attributes:
        llm_service: LLM service for relevance scoring
        min_relevance_score: Minimum relevance to include (0.0-1.0)
        batch_size: Papers per LLM request (default: 10)
    """

    # Default maximum cache entries to prevent unbounded memory growth
    DEFAULT_MAX_CACHE_SIZE: int = 5000
    # Default maximum concurrent LLM batches to prevent rate limiting
    DEFAULT_MAX_CONCURRENT_BATCHES: int = 3

    def __init__(
        self,
        llm_service: Optional["LLMService"] = None,
        min_relevance_score: float = 0.5,
        batch_size: int = 10,
        enable_cache: bool = True,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE,
    ) -> None:
        """Initialize RelevanceRanker.

        Args:
            llm_service: LLM service for scoring. If None, ranking is
                disabled and papers are returned with quality score only.
            min_relevance_score: Minimum relevance score (0.0-1.0)
            batch_size: Number of papers per LLM batch
            enable_cache: Enable caching of relevance scores
            max_cache_size: Maximum cache entries (LRU eviction when exceeded)
        """
        self._llm_service = llm_service
        self.min_relevance_score = min_relevance_score
        self.batch_size = batch_size
        self._cache: OrderedDict[str, float] = OrderedDict()
        self._cache_enabled = enable_cache
        self._max_cache_size = max_cache_size

    @property
    def llm_service(self) -> Optional["LLMService"]:
        """Get the LLM service."""
        return self._llm_service

    async def rank(
        self,
        papers: List[ScoredPaper],
        query: str,
        top_k: Optional[int] = None,
    ) -> List[ScoredPaper]:
        """Rank papers by relevance to query.

        Args:
            papers: Papers to rank (with quality scores)
            query: Original research query
            top_k: Return only top k papers (default: all above threshold)

        Returns:
            Papers ranked by final_score, filtered by min_relevance_score

        Note:
            If LLM service is not available, returns papers sorted by
            quality_score alone without relevance filtering.
        """
        if not papers:
            return []

        if not query or not query.strip():
            logger.warning("relevance_ranker_empty_query")
            return papers

        query = query.strip()

        logger.info(
            "relevance_ranker_starting",
            papers_count=len(papers),
            query=query[:50],
            batch_size=self.batch_size,
        )

        # If no LLM service, return papers sorted by quality score
        if self._llm_service is None:
            logger.info(
                "relevance_ranker_no_llm",
                action="returning_by_quality_score",
            )
            sorted_papers = sorted(papers, key=lambda p: p.quality_score, reverse=True)
            if top_k:
                sorted_papers = sorted_papers[:top_k]
            return sorted_papers

        try:
            # Score papers in batches
            scored_papers = await self._score_all_papers(papers, query)

            # Filter by relevance threshold
            filtered_papers = [
                p
                for p in scored_papers
                if p.relevance_score is not None
                and p.relevance_score >= self.min_relevance_score
            ]

            # Sort by final score (combined quality + relevance)
            sorted_papers = sorted(
                filtered_papers,
                key=lambda p: p.final_score,
                reverse=True,
            )

            # Apply top_k limit
            if top_k:
                sorted_papers = sorted_papers[:top_k]

            logger.info(
                "relevance_ranker_completed",
                papers_input=len(papers),
                papers_scored=len(scored_papers),
                papers_filtered=len(filtered_papers),
                papers_output=len(sorted_papers),
            )

            return sorted_papers

        except Exception as e:
            logger.error(
                "relevance_ranker_failed",
                error=str(e),
                query=query[:50],
            )
            # Fallback to quality score ranking
            sorted_papers = sorted(papers, key=lambda p: p.quality_score, reverse=True)
            if top_k:
                sorted_papers = sorted_papers[:top_k]
            return sorted_papers

    async def _score_all_papers(
        self,
        papers: List[ScoredPaper],
        query: str,
    ) -> List[ScoredPaper]:
        """Score all papers using batched LLM calls.

        Args:
            papers: Papers to score
            query: Research query

        Returns:
            Papers with relevance_score populated
        """
        # Split papers into batches
        batches = [
            papers[i : i + self.batch_size]
            for i in range(0, len(papers), self.batch_size)
        ]

        logger.debug(
            "relevance_ranker_batching",
            total_papers=len(papers),
            batch_count=len(batches),
        )

        # Process batches concurrently with semaphore
        semaphore = asyncio.Semaphore(self.DEFAULT_MAX_CONCURRENT_BATCHES)
        scored_papers: List[ScoredPaper] = []

        async def process_batch(batch: List[ScoredPaper]) -> List[ScoredPaper]:
            async with semaphore:
                return await self._score_paper_batch(batch, query)

        tasks = [process_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "relevance_ranker_batch_failed",
                    error=str(result),
                )
                continue
            scored_papers.extend(result)  # type: ignore[arg-type]

        return scored_papers

    async def _score_paper_batch(
        self,
        papers: List[ScoredPaper],
        query: str,
    ) -> List[ScoredPaper]:
        """Score a batch of papers for relevance (0.0-1.0).

        Args:
            papers: Batch of papers to score
            query: Research query

        Returns:
            Papers with relevance_score set
        """
        # Check cache for all papers
        uncached_papers = []
        cached_scores: dict[str, float] = {}

        for paper in papers:
            cache_key = self._get_cache_key(paper.paper_id, query)
            if self._cache_enabled and cache_key in self._cache:
                # Move to end for LRU ordering
                self._cache.move_to_end(cache_key)
                cached_scores[paper.paper_id] = self._cache[cache_key]
            else:
                uncached_papers.append(paper)

        # If all cached, return immediately
        if not uncached_papers:
            logger.debug("relevance_ranker_all_cached", count=len(papers))
            return self._apply_scores(papers, cached_scores)

        # Build papers JSON for prompt
        papers_data = []
        for i, paper in enumerate(uncached_papers):
            papers_data.append(
                {
                    "index": i,
                    "title": paper.title,
                    "abstract": (paper.abstract or "")[:500],  # Limit abstract length
                }
            )

        papers_json = json.dumps(papers_data, indent=2)

        # Build prompt
        prompt = RELEVANCE_PROMPT.format(
            query=query,
            papers_json=papers_json,
        )

        # Call LLM
        # NOTE: complete() method to be added to LLMService during integration phase
        assert self._llm_service is not None
        response = await self._llm_service.complete(  # type: ignore[attr-defined]
            prompt=prompt,
            system_prompt="You are a helpful assistant that outputs only valid JSON.",
            temperature=0.1,  # Low temperature for consistency
            max_tokens=500,
        )

        # Parse scores
        scores = self._parse_scores(response.content, len(uncached_papers))

        # Update cache and build result
        result_scores = dict(cached_scores)
        for paper, score in zip(uncached_papers, scores):
            result_scores[paper.paper_id] = score
            cache_key = self._get_cache_key(paper.paper_id, query)
            self._cache_put(cache_key, score)

        return self._apply_scores(papers, result_scores)

    def _apply_scores(
        self,
        papers: List[ScoredPaper],
        scores: dict[str, float],
    ) -> List[ScoredPaper]:
        """Apply relevance scores to papers.

        Args:
            papers: Original papers
            scores: Map of paper_id to relevance score

        Returns:
            New papers with relevance_score set
        """
        scored = []
        for paper in papers:
            score = scores.get(paper.paper_id)
            if score is not None:
                # Create new paper with relevance score
                scored.append(
                    ScoredPaper(
                        paper_id=paper.paper_id,
                        title=paper.title,
                        abstract=paper.abstract,
                        doi=paper.doi,
                        url=paper.url,
                        open_access_pdf=paper.open_access_pdf,
                        authors=paper.authors,
                        publication_date=paper.publication_date,
                        venue=paper.venue,
                        citation_count=paper.citation_count,
                        source=paper.source,
                        quality_score=paper.quality_score,
                        relevance_score=score,
                        engagement_score=paper.engagement_score,
                    )
                )
            else:
                scored.append(paper)
        return scored

    def _parse_scores(self, response: str, expected_count: int) -> List[float]:
        """Parse relevance scores from LLM response.

        Args:
            response: Raw LLM response
            expected_count: Expected number of scores

        Returns:
            List of scores (0.0-1.0), with 0.0 for parse failures
        """
        # Try to extract JSON array
        json_str = self._extract_json_array(response)

        if not json_str:
            logger.warning(
                "relevance_ranker_no_json_found",
                response_preview=response[:200],
            )
            return [0.0] * expected_count

        try:
            scores = json.loads(json_str)

            if not isinstance(scores, list):
                logger.warning("relevance_ranker_invalid_format")
                return [0.0] * expected_count

            # Validate and clamp scores
            result = []
            for i, score in enumerate(scores):
                if isinstance(score, (int, float)):
                    result.append(min(1.0, max(0.0, float(score))))
                else:
                    result.append(0.0)

            # Pad or truncate to expected count
            if len(result) < expected_count:
                result.extend([0.0] * (expected_count - len(result)))
            elif len(result) > expected_count:
                result = result[:expected_count]

            return result

        except json.JSONDecodeError as e:
            logger.warning(
                "relevance_ranker_json_parse_error",
                error=str(e),
                response_preview=response[:200],
            )
            return [0.0] * expected_count

    def _extract_json_array(self, text: str) -> Optional[str]:
        """Extract JSON array from text.

        Args:
            text: Raw text that may contain JSON

        Returns:
            Extracted JSON string or None
        """
        # Look for pattern starting with [ and ending with ]
        match = re.search(r"\[[\s\S]*?\]", text)
        if match:
            return match.group(0)
        return None

    def _get_cache_key(self, paper_id: str, query: str) -> str:
        """Generate cache key for paper-query pair.

        Args:
            paper_id: Paper identifier
            query: Research query

        Returns:
            Cache key string
        """
        # Normalize query for caching
        normalized_query = query.lower().strip()[:100]
        return f"{paper_id}:{normalized_query}"

    def _cache_put(self, key: str, value: float) -> None:
        """Add item to cache with LRU eviction.

        Args:
            key: Cache key
            value: Relevance score to cache
        """
        if not self._cache_enabled:
            return

        # If key exists, update and move to end
        if key in self._cache:
            self._cache[key] = value
            self._cache.move_to_end(key)
            return

        # Evict oldest entries if at capacity
        while len(self._cache) >= self._max_cache_size:
            evicted_key = next(iter(self._cache))
            del self._cache[evicted_key]
            logger.debug("relevance_ranker_cache_evicted", key=evicted_key[:30])

        # Add new entry
        self._cache[key] = value

    def clear_cache(self) -> None:
        """Clear the relevance score cache."""
        self._cache.clear()
        logger.debug("relevance_ranker_cache_cleared")
