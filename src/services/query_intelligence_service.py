"""Query Intelligence Service for unified query enhancement.

This service consolidates query decomposition and expansion into a single
interface with multiple strategies. Replaces QueryDecomposer and QueryExpander.

Usage:
    from src.services.query_intelligence_service import QueryIntelligenceService
    from src.models.query import QueryStrategy

    service = QueryIntelligenceService(llm_service)
    queries = await service.enhance(
        "Tree of Thoughts for machine translation",
        strategy=QueryStrategy.DECOMPOSE
    )
"""

import hashlib
import json
import re
from collections import OrderedDict
from typing import List, Optional, TYPE_CHECKING

import structlog

from src.models.query import QueryStrategy, QueryFocus, EnhancedQuery

if TYPE_CHECKING:
    from src.services.llm import LLMService

logger = structlog.get_logger()

# Decomposition prompt template (from QueryDecomposer)
DECOMPOSITION_PROMPT = (
    "You are an academic research expert. Decompose the following research "
    "query into {max_subqueries} focused sub-queries that would help find "
    "relevant academic papers.\n\n"
    "Original Query: {query}\n\n"
    "For each sub-query:\n"
    "1. Focus on a specific aspect (methodology, application, comparison, "
    "related concepts, or cross-disciplinary intersection)\n"
    "2. Use academic terminology appropriate for paper search\n"
    "3. Include relevant synonyms and related concepts\n"
    "4. Keep queries concise but specific (3-10 words ideal)\n\n"
    'Output ONLY a valid JSON array with objects containing "query" and '
    '"focus" fields.\n'
    'Valid focus values: "methodology", "application", "comparison", '
    '"related", "intersection"\n\n'
    "Example output format:\n"
    "[\n"
    '  {{"query": "Tree of Thoughts prompting technique", '
    '"focus": "methodology"}},\n'
    '  {{"query": "reasoning-based neural machine translation", '
    '"focus": "application"}}\n'
    "]\n\n"
    "Now generate {max_subqueries} sub-queries for the given query. "
    "Output ONLY the JSON array, no other text:"
)

# Expansion prompt template (from QueryExpander)
EXPANSION_PROMPT = (
    "You are an academic research assistant. "
    "Given a research query, generate {max_variants} alternative search queries "
    "that would find related academic papers.\n\n"
    "Original query: {query}\n\n"
    "Requirements:\n"
    "- Each alternative should use different terminology or phrasing\n"
    "- Focus on academic/scientific language\n"
    "- Include synonyms, related concepts, and alternative formulations\n"
    "- Keep queries concise and searchable\n\n"
    "Return ONLY a JSON array of strings, no other text:\n"
    '["query 1", "query 2", ...]'
)


class QueryIntelligenceService:
    """Unified query enhancement service with multiple strategies.

    Consolidates query decomposition and expansion into a single service
    with support for DECOMPOSE, EXPAND, and HYBRID strategies.

    Attributes:
        llm_service: LLM service for query generation
        cache_enabled: Whether caching is enabled
        max_cache_size: Maximum cache entries (LRU eviction)
        cache: Bounded LRU cache for enhanced queries
    """

    DEFAULT_MAX_CACHE_SIZE: int = 1000

    def __init__(
        self,
        llm_service: Optional["LLMService"] = None,
        cache_enabled: bool = True,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE,
    ) -> None:
        """Initialize QueryIntelligenceService.

        Args:
            llm_service: LLM service for query enhancement. If None, returns
                original query only (graceful degradation).
            cache_enabled: Enable caching of enhanced queries
            max_cache_size: Maximum cache entries (LRU eviction when exceeded)
        """
        self._llm_service = llm_service
        self._cache_enabled = cache_enabled
        self._max_cache_size = max_cache_size
        self._cache: OrderedDict[str, List[EnhancedQuery]] = OrderedDict()

    async def enhance(
        self,
        query: str,
        strategy: QueryStrategy = QueryStrategy.DECOMPOSE,
        max_queries: int = 5,
        include_original: bool = True,
    ) -> List[EnhancedQuery]:
        """Enhance a query using the specified strategy.

        Args:
            query: Original research query
            strategy: Enhancement strategy to use
            max_queries: Maximum queries to generate
            include_original: Include original query in results

        Returns:
            List of EnhancedQuery objects

        Note:
            If LLM service is unavailable, returns only the original query
            with is_original=True (graceful degradation).
        """
        # Validate input
        if not query or not query.strip():
            logger.warning("query_intelligence_empty_query")
            return []

        query = query.strip()

        # Get LLM model identifier for cache key
        llm_model = self._get_llm_model()
        cache_key = self._get_cache_key(query, strategy.value, max_queries, llm_model)

        # Check cache
        if self._cache_enabled and cache_key in self._cache:
            logger.debug("query_intelligence_cache_hit", query=query[:50])
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # If no LLM service, return original only
        if self._llm_service is None:
            logger.info(
                "query_intelligence_no_llm",
                query=query[:50],
                action="returning_original_only",
            )
            result = [
                EnhancedQuery(
                    query=query,
                    focus=None,
                    weight=1.0,
                    is_original=True,
                    parent_query=None,
                    strategy_used=strategy,
                )
            ]
            self._cache_put(cache_key, result)
            return result

        logger.info(
            "query_intelligence_starting",
            query=query[:50],
            strategy=strategy.value,
            max_queries=max_queries,
        )

        try:
            # Execute strategy
            if strategy == QueryStrategy.DECOMPOSE:
                result = await self._execute_decompose(
                    query, max_queries, include_original
                )
            elif strategy == QueryStrategy.EXPAND:
                result = await self._execute_expand(
                    query, max_queries, include_original
                )
            elif strategy == QueryStrategy.HYBRID:
                result = await self._enhance_hybrid(
                    query, max_queries, include_original
                )
            else:  # pragma: no cover
                # Unreachable: QueryStrategy enum covers all cases
                logger.warning(
                    "query_intelligence_unknown_strategy",
                    strategy=strategy.value,
                    fallback="returning_original",
                )
                result = [
                    EnhancedQuery(
                        query=query,
                        focus=None,
                        weight=1.0,
                        is_original=True,
                        parent_query=None,
                        strategy_used=strategy,
                    )
                ]

            # Cache result
            self._cache_put(cache_key, result)

            logger.info(
                "query_intelligence_completed",
                query=query[:50],
                strategy=strategy.value,
                queries_generated=len(result),
            )

            return result

        except Exception as e:
            logger.error(
                "query_intelligence_failed",
                query=query[:50],
                strategy=strategy.value,
                error=str(e),
            )
            # Fallback to original query
            result = [
                EnhancedQuery(
                    query=query,
                    focus=None,
                    weight=1.0,
                    is_original=True,
                    parent_query=None,
                    strategy_used=strategy,
                )
            ]
            self._cache_put(cache_key, result)
            return result

    async def decompose(
        self,
        query: str,
        max_subqueries: int = 5,
        include_original: bool = True,
    ) -> List[EnhancedQuery]:
        """Decompose a query into focused sub-queries.

        Args:
            query: Original research query
            max_subqueries: Maximum sub-queries to generate
            include_original: Include original query in results

        Returns:
            List of EnhancedQuery objects with focus areas
        """
        # Delegate to enhance() to use caching
        return await self.enhance(
            query=query,
            strategy=QueryStrategy.DECOMPOSE,
            max_queries=max_subqueries,
            include_original=include_original,
        )

    async def expand(
        self,
        query: str,
        max_variants: int = 5,
        include_original: bool = True,
    ) -> List[EnhancedQuery]:
        """Expand a query into semantic variants.

        Args:
            query: Original research query
            max_variants: Maximum variants to generate
            include_original: Include original query in results

        Returns:
            List of EnhancedQuery objects with variants
        """
        # Delegate to enhance() to use caching
        return await self.enhance(
            query=query,
            strategy=QueryStrategy.EXPAND,
            max_queries=max_variants,
            include_original=include_original,
        )

    async def _execute_decompose(
        self,
        query: str,
        max_subqueries: int,
        include_original: bool,
    ) -> List[EnhancedQuery]:
        """Execute decomposition strategy.

        Args:
            query: Original research query
            max_subqueries: Maximum sub-queries to generate
            include_original: Include original query in results

        Returns:
            List of EnhancedQuery objects with focus areas

        Raises:
            RuntimeError: If LLM service is not configured.
        """
        if self._llm_service is None:
            raise RuntimeError("LLM service required for decomposition")

        # Generate prompt
        prompt = DECOMPOSITION_PROMPT.format(
            query=query,
            max_subqueries=max_subqueries,
        )

        # Call LLM
        response = await self._llm_service.complete(
            prompt=prompt,
            system_prompt="You are a helpful assistant that outputs only valid JSON.",
            temperature=0.3,
            max_tokens=1000,
        )

        # Parse response
        subqueries = self._parse_decomposition_response(response.content)

        # Build result
        result = []
        if include_original:
            result.append(
                EnhancedQuery(
                    query=query,
                    focus=QueryFocus.RELATED,
                    weight=1.5,  # Higher weight for original
                    is_original=True,
                    parent_query=None,
                    strategy_used=QueryStrategy.DECOMPOSE,
                )
            )

        result.extend(subqueries)
        return result

    async def _execute_expand(
        self,
        query: str,
        max_variants: int,
        include_original: bool,
    ) -> List[EnhancedQuery]:
        """Execute expansion strategy.

        Args:
            query: Original research query
            max_variants: Maximum variants to generate
            include_original: Include original query in results

        Returns:
            List of EnhancedQuery objects with variants

        Raises:
            RuntimeError: If LLM service is not configured.
        """
        if self._llm_service is None:
            raise RuntimeError("LLM service required for expansion")

        # Generate prompt
        prompt = EXPANSION_PROMPT.format(
            query=query,
            max_variants=max_variants,
        )

        # Call LLM
        response = await self._llm_service.complete(
            prompt=prompt,
            system_prompt="You are a helpful assistant that outputs only valid JSON.",
            temperature=0.3,
            max_tokens=1000,
        )

        # Parse response
        variants = self._parse_expansion_response(response.content)

        # Build result
        result = []
        if include_original:
            result.append(
                EnhancedQuery(
                    query=query,
                    focus=None,
                    weight=1.5,  # Higher weight for original
                    is_original=True,
                    parent_query=None,
                    strategy_used=QueryStrategy.EXPAND,
                )
            )

        result.extend(variants)
        return result

    async def _enhance_hybrid(
        self,
        query: str,
        max_queries: int,
        include_original: bool,
    ) -> List[EnhancedQuery]:
        """Hybrid strategy: decompose then expand each sub-query.

        Args:
            query: Original research query
            max_queries: Maximum total queries to generate
            include_original: Include original query in results

        Returns:
            List of EnhancedQuery objects from hybrid enhancement
        """
        # First decompose (without original)
        decomposed = await self._execute_decompose(
            query, max_subqueries=3, include_original=False
        )

        # Then expand each decomposed query (1-2 variants each)
        result = []
        if include_original:
            result.append(
                EnhancedQuery(
                    query=query,
                    focus=QueryFocus.RELATED,
                    weight=1.5,
                    is_original=True,
                    parent_query=None,
                    strategy_used=QueryStrategy.HYBRID,
                )
            )

        # Add decomposed queries
        result.extend(decomposed)

        # Expand first 2 decomposed queries if space allows
        remaining_slots = max_queries - len(result)
        if remaining_slots > 0:
            for decomposed_query in decomposed[:2]:
                if remaining_slots <= 0:
                    break

                # Expand this decomposed query (1-2 variants)
                expanded = await self._execute_expand(
                    decomposed_query.query,
                    max_variants=min(2, remaining_slots),
                    include_original=False,
                )

                # Update expanded queries with parent reference
                for exp_query in expanded:
                    result.append(
                        EnhancedQuery(
                            query=exp_query.query,
                            focus=decomposed_query.focus,
                            weight=1.0,
                            is_original=False,
                            parent_query=decomposed_query.query,
                            strategy_used=QueryStrategy.HYBRID,
                        )
                    )
                    remaining_slots -= 1
                    if remaining_slots <= 0:
                        break

        return result[:max_queries]

    def _parse_decomposition_response(self, response: str) -> List[EnhancedQuery]:
        """Parse LLM response for decomposition.

        Args:
            response: Raw LLM response text

        Returns:
            List of EnhancedQuery objects with focus areas
        """
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning(
                "query_intelligence_decompose_no_json",
                response_preview=response[:200],
            )
            return []

        try:
            data = json.loads(json_str)
            if not isinstance(data, list):
                logger.warning("query_intelligence_decompose_invalid_format")
                return []

            queries = []
            for item in data:
                if not isinstance(item, dict):
                    continue

                query_text = item.get("query", "").strip()
                focus_str = item.get("focus", "related").lower().strip()

                if not query_text:
                    continue

                focus = self._map_focus(focus_str)

                queries.append(
                    EnhancedQuery(
                        query=query_text,
                        focus=focus,
                        weight=1.0,
                        is_original=False,
                        parent_query=None,
                        strategy_used=QueryStrategy.DECOMPOSE,
                    )
                )

            return queries

        except json.JSONDecodeError as e:
            logger.warning(
                "query_intelligence_decompose_json_error",
                error=str(e),
                response_preview=response[:200],
            )
            return []

    def _parse_expansion_response(self, response: str) -> List[EnhancedQuery]:
        """Parse LLM response for expansion.

        Args:
            response: Raw LLM response text

        Returns:
            List of EnhancedQuery objects with variants
        """
        json_str = self._extract_json(response)
        if not json_str:
            logger.warning(
                "query_intelligence_expand_no_json",
                response_preview=response[:200],
            )
            return []

        try:
            data = json.loads(json_str)
            if not isinstance(data, list):
                logger.warning("query_intelligence_expand_invalid_format")
                return []

            queries = []
            for item in data:
                if not item or not isinstance(item, str):
                    continue

                query_text = item.strip()
                if not query_text:
                    continue

                queries.append(
                    EnhancedQuery(
                        query=query_text,
                        focus=None,
                        weight=1.0,
                        is_original=False,
                        parent_query=None,
                        strategy_used=QueryStrategy.EXPAND,
                    )
                )

            return queries

        except json.JSONDecodeError as e:
            logger.warning(
                "query_intelligence_expand_json_error",
                error=str(e),
                response_preview=response[:200],
            )
            return []

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON array from text.

        Args:
            text: Raw text that may contain JSON

        Returns:
            Extracted JSON string or None
        """
        # Try to find JSON array in the text
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            return match.group(0)
        return None

    def _map_focus(self, focus_str: str) -> QueryFocus:
        """Map focus string to QueryFocus enum.

        Args:
            focus_str: Focus string from LLM response

        Returns:
            QueryFocus enum value
        """
        focus_map = {
            "methodology": QueryFocus.METHODOLOGY,
            "application": QueryFocus.APPLICATION,
            "comparison": QueryFocus.COMPARISON,
            "related": QueryFocus.RELATED,
            "intersection": QueryFocus.INTERSECTION,
        }
        return focus_map.get(focus_str, QueryFocus.RELATED)

    def _get_llm_model(self) -> str:
        """Get LLM model identifier for cache key.

        Returns:
            Model identifier string, or "none" if no LLM service
        """
        if self._llm_service is None:
            return "none"

        # Extract model from LLM service config
        if hasattr(self._llm_service, "config") and hasattr(
            self._llm_service.config, "model"
        ):
            return str(self._llm_service.config.model)

        return "unknown"

    def _get_cache_key(
        self, query: str, strategy: str, max_queries: int, llm_model: str
    ) -> str:
        """Generate cache key including LLM model for consistency.

        The cache key MUST include the LLM model identifier to prevent
        stale expansions when the user changes LLM providers.

        Args:
            query: Query text
            strategy: Strategy name
            max_queries: Maximum queries to generate
            llm_model: LLM model identifier

        Returns:
            Cache key string in format: {hash}:{strategy}:{max}:{model}
        """
        normalized = query.lower().strip()
        query_hash = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        return f"{query_hash}:{strategy}:{max_queries}:{llm_model}"

    def _cache_put(self, key: str, value: List[EnhancedQuery]) -> None:
        """Add item to cache with LRU eviction.

        Args:
            key: Cache key
            value: Value to cache
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
            logger.debug("query_intelligence_cache_evicted", key=evicted_key[:30])

        # Add new entry
        self._cache[key] = value

    def _evict_lru(self) -> None:
        """Evict least recently used cache entry.

        This is a public method for explicit cache management.
        """
        if not self._cache:
            return

        evicted_key = next(iter(self._cache))
        del self._cache[evicted_key]
        logger.debug("query_intelligence_lru_evicted", key=evicted_key[:30])

    def clear_cache(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()
        logger.debug("query_intelligence_cache_cleared")

    def get_cache_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with cache size and capacity
        """
        return {
            "size": len(self._cache),
            "capacity": self._max_cache_size,
            "enabled": self._cache_enabled,
        }
