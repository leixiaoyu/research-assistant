"""Query Intelligence Service - Unified Query Processing (Phase 6, 7.2 & PR #86).

Merges QueryDecomposer (Phase 6) and QueryExpander (Phase 7.2) into a single
service that handles both "Perspective Decomposition" and "Academic Expansion".

This resolves the collision where the two services used different prompts
and data models for generating search variants.

Usage:
    from src.services.query_intelligence_service import QueryIntelligenceService

    service = QueryIntelligenceService(llm_service)
    decomposed = await service.decompose("transformer attention")
    expanded = await service.expand("transformer attention")
    variants = await service.generate_variants("transformer attention")
"""

import hashlib
import json
import re
from collections import OrderedDict
from typing import List, Optional, Dict, TYPE_CHECKING

import structlog

from src.models.config import QueryExpansionConfig
from src.models.discovery import DecomposedQuery, QueryFocus

if TYPE_CHECKING:
    from src.services.llm import LLMService

logger = structlog.get_logger()

# ============================================================================
# Prompt Templates
# ============================================================================

# Perspective Decomposition prompt (from QueryDecomposer)
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

# Academic Expansion prompt (from QueryExpander)
EXPANSION_PROMPT = """You are an academic research assistant. \
Given a research query, generate {max_variants} alternative search queries \
that would find related academic papers.

Original query: {query}

Requirements:
- Each alternative should use different terminology or phrasing
- Focus on academic/scientific language
- Include synonyms, related concepts, and alternative formulations
- Keep queries concise and searchable

Return ONLY a JSON array of strings, no other text:
["query 1", "query 2", ...]"""


# ============================================================================
# Query Intelligence Service
# ============================================================================


class QueryIntelligenceService:
    """Unified service for query intelligence: decomposition and expansion.

    Combines the Perspective Decomposition (QueryDecomposer) and
    Academic Expansion (QueryExpander) capabilities into a single service.

    Attributes:
        llm_service: LLM service for query generation
        config: Query expansion configuration
        enable_cache: Whether to enable caching
        max_cache_size: Maximum cache entries
    """

    # Default maximum cache entries
    DEFAULT_MAX_CACHE_SIZE: int = 1000

    def __init__(
        self,
        llm_service: Optional["LLMService"] = None,
        config: Optional[QueryExpansionConfig] = None,
        enable_cache: bool = True,
        max_cache_size: int = DEFAULT_MAX_CACHE_SIZE,
    ) -> None:
        """Initialize QueryIntelligenceService.

        Args:
            llm_service: LLM service for query processing
            config: Query expansion configuration
            enable_cache: Enable caching of processed queries
            max_cache_size: Maximum cache entries (LRU eviction when exceeded)
        """
        self._llm_service = llm_service
        self._config = config or QueryExpansionConfig()
        self._cache: OrderedDict[str, List[DecomposedQuery]] = OrderedDict()
        self._cache_enabled = enable_cache
        self._max_cache_size = max_cache_size
        self._expansion_cache: Dict[str, List[str]] = {}

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def llm_service(self) -> Optional["LLMService"]:
        """Get the LLM service."""
        return self._llm_service

    @property
    def config(self) -> QueryExpansionConfig:
        """Get the query expansion config."""
        return self._config

    # =========================================================================
    # Perspective Decomposition (QueryDecomposer functionality)
    # =========================================================================

    async def decompose(
        self,
        query: str,
        max_subqueries: int = 5,
        include_original: bool = True,
    ) -> List[DecomposedQuery]:
        """Decompose a research query into focused sub-queries.

        This is "Perspective Decomposition" - generating sub-queries that
        explore different aspects (methodology vs. application vs. comparison).

        Args:
            query: Original research query
            max_subqueries: Maximum sub-queries to generate (default: 5)
            include_original: Include original query in results (default: True)

        Returns:
            List of DecomposedQuery objects with query text and focus area

        Note:
            If LLM service is not available, returns only the original query
            wrapped as a DecomposedQuery with RELATED focus.
        """
        if not query or not query.strip():
            logger.warning("query_intelligence_empty_query")
            return []

        query = query.strip()
        cache_key = f"decompose:{query}:{max_subqueries}:{include_original}"

        # Check cache
        if self._cache_enabled and cache_key in self._cache:
            logger.debug("query_intelligence_cache_hit", query=query[:50])
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        # If no LLM service, return original query only
        if self._llm_service is None:
            logger.info(
                "query_intelligence_no_llm",
                query=query[:50],
                action="returning_original_only",
            )
            result = [
                DecomposedQuery(
                    query=query,
                    focus=QueryFocus.RELATED,
                    weight=1.0,
                )
            ]
            self._cache_put(cache_key, result)
            return result

        logger.info(
            "query_intelligence_decompose_starting",
            query=query[:50],
            max_subqueries=max_subqueries,
        )

        try:
            # Generate sub-queries using LLM
            subqueries = await self._generate_subqueries(query, max_subqueries)

            # Optionally include original query
            result = []
            if include_original:
                result.append(
                    DecomposedQuery(
                        query=query,
                        focus=QueryFocus.RELATED,
                        weight=1.5,  # Higher weight for original
                    )
                )

            # Add generated sub-queries
            result.extend(subqueries)

            # Cache result
            self._cache_put(cache_key, result)

            logger.info(
                "query_intelligence_decompose_completed",
                query=query[:50],
                subqueries_generated=len(subqueries),
                total_queries=len(result),
            )

            return result

        except Exception as e:
            logger.error(
                "query_intelligence_decompose_failed",
                query=query[:50],
                error=str(e),
            )
            # Fallback to original query
            result = [
                DecomposedQuery(
                    query=query,
                    focus=QueryFocus.RELATED,
                    weight=1.0,
                )
            ]
            self._cache_put(cache_key, result)
            return result

    async def _generate_subqueries(
        self,
        query: str,
        max_subqueries: int,
    ) -> List[DecomposedQuery]:
        """Generate sub-queries using LLM.

        Args:
            query: Original query
            max_subqueries: Maximum sub-queries to generate

        Returns:
            List of DecomposedQuery objects
        """
        prompt = DECOMPOSITION_PROMPT.format(
            query=query,
            max_subqueries=max_subqueries,
        )

        assert self._llm_service is not None
        response = await self._llm_service.complete(
            prompt=prompt,
            system_prompt="You are a helpful assistant that outputs only valid JSON.",
            temperature=0.3,
            max_tokens=1000,
        )

        content = response.content if hasattr(response, "content") else str(response)
        return self._parse_decomposition_response(content)

    def _parse_decomposition_response(self, response: str) -> List[DecomposedQuery]:
        """Parse LLM response into DecomposedQuery objects.

        Args:
            response: Raw LLM response text

        Returns:
            List of DecomposedQuery objects
        """
        json_str = self._extract_json(response)

        if not json_str:
            logger.warning(
                "query_intelligence_no_json_found",
                response_preview=response[:200],
            )
            return []

        try:
            data = json.loads(json_str)

            if not isinstance(data, list):
                logger.warning("query_intelligence_invalid_json_format")
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
                    DecomposedQuery(
                        query=query_text,
                        focus=focus,
                        weight=1.0,
                    )
                )

            return queries

        except json.JSONDecodeError as e:
            logger.warning(
                "query_intelligence_json_parse_error",
                error=str(e),
                response_preview=response[:200],
            )
            return []

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

    # =========================================================================
    # Academic Expansion (QueryExpander functionality)
    # =========================================================================

    async def expand(
        self,
        query: str,
        max_variants: Optional[int] = None,
    ) -> List[str]:
        """Generate expanded query variants with different terminology.

        This is "Academic Expansion" - generating semantically related queries
        using synonyms and alternative phrasing.

        Returns list of queries including the original.
        If LLM fails, returns only the original query.

        Args:
            query: Original search query
            max_variants: Maximum number of variants to generate

        Returns:
            List of queries with original first
        """
        max_variants = max_variants or self._config.max_variants

        # Check cache first
        if self._config.cache_expansions:
            cached = self._get_cached_expansion(query)
            if cached is not None:
                logger.info("query_intelligence_expansion_cache_hit", query=query[:50])
                return cached

        # If no LLM, return original only
        if self._llm_service is None:
            logger.warning("query_intelligence_expansion_no_llm", query=query[:50])
            return [query]

        try:
            # Call LLM for expansion
            prompt = EXPANSION_PROMPT.format(
                query=query,
                max_variants=max_variants,
            )
            response = await self._llm_service.complete(prompt)
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            variants = self._parse_expansion_response(content)

            # Always include original query first
            result = [query] + [v for v in variants if v.lower() != query.lower()]

            # Limit to max_variants + 1 (original + variants)
            result = result[: max_variants + 1]

            # Cache result
            if self._config.cache_expansions:
                self._cache_expansion(query, result)

            logger.info(
                "query_intelligence_expansion_success",
                original_query=query[:50],
                variants_generated=len(result) - 1,
            )
            return result

        except Exception as e:
            logger.warning(
                "query_intelligence_expansion_failed",
                query=query[:50],
                error=str(e),
            )
            return [query]  # Graceful degradation

    def _get_cached_expansion(self, query: str) -> Optional[List[str]]:
        """Check cache for existing expansion.

        Args:
            query: Original query

        Returns:
            Cached expansion list or None
        """
        cache_key = self._expansion_cache_key(query)
        return self._expansion_cache.get(cache_key)

    def _cache_expansion(self, query: str, variants: List[str]) -> None:
        """Cache expansion result.

        Args:
            query: Original query
            variants: List of query variants
        """
        cache_key = self._expansion_cache_key(query)
        self._expansion_cache[cache_key] = variants

    def _expansion_cache_key(self, query: str) -> str:
        """Generate cache key for query.

        Args:
            query: Original query

        Returns:
            Cache key string
        """
        normalized = query.lower().strip()
        hash_str = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        return f"query_expansion:{hash_str}"

    def _parse_expansion_response(self, response: str) -> List[str]:
        """Parse LLM response to extract query list.

        Handles various response formats:
        - Plain JSON array
        - JSON in markdown code blocks
        - JSON embedded in text

        Args:
            response: Raw LLM response

        Returns:
            List of query strings
        """
        if not response:
            return []

        # Try direct JSON parse
        try:
            result = json.loads(response.strip())
            if isinstance(result, list):
                return [str(q).strip() for q in result if q and str(q).strip()]
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code block
        code_block_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", response, re.DOTALL
        )
        if code_block_match:
            try:
                result = json.loads(code_block_match.group(1).strip())
                if isinstance(result, list):
                    return [str(q).strip() for q in result if q and str(q).strip()]
            except json.JSONDecodeError:
                pass

        # Try to find JSON array in text
        array_match = re.search(r"\[.*?\]", response, re.DOTALL)
        if array_match:
            try:
                result = json.loads(array_match.group(0))
                if isinstance(result, list):
                    return [str(q).strip() for q in result if q and str(q).strip()]
            except json.JSONDecodeError:
                pass

        logger.warning(
            "query_intelligence_expansion_parse_failed",
            response=response[:100],
        )
        return []

    # =========================================================================
    # Combined variants generation
    # =========================================================================

    async def generate_variants(
        self,
        query: str,
        max_decomposed: int = 5,
        max_expanded: int = 5,
    ) -> List[str]:
        """Generate combined query variants from both decomposition and expansion.

        This combines the Perspective Decomposition and Academic Expansion
        into a single list of query variants.

        Args:
            query: Original search query
            max_decomposed: Maximum decomposed sub-queries
            max_expanded: Maximum expanded variants

        Returns:
            Combined list of query strings (deduplicated)
        """
        # Run both operations concurrently
        decompose_task = self.decompose(query, max_decomposed, include_original=False)
        expand_task = self.expand(query, max_expanded)

        decomposed_queries, expanded_queries = await Promise.all(
            [
                decompose_task,
                expand_task,
            ]
        )

        # Combine and deduplicate
        all_queries = set()

        # Add decomposed queries (they have weights, but we just need the text)
        for dq in decomposed_queries:
            all_queries.add(dq.query.lower())

        # Add expanded queries (original is included, we need to exclude it)
        for eq in expanded_queries:
            if eq.lower() != query.lower():
                all_queries.add(eq.lower())

        # Return as list, preserving some notion of order
        return list(all_queries)

    # =========================================================================
    # Utility methods
    # =========================================================================

    def _extract_json(self, text: str) -> Optional[str]:
        """Extract JSON array from text.

        Args:
            text: Raw text that may contain JSON

        Returns:
            Extracted JSON string or None
        """
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            return match.group(0)
        return None

    def _cache_put(self, key: str, value: List[DecomposedQuery]) -> None:
        """Add item to cache with LRU eviction.

        Args:
            key: Cache key
            value: Value to cache
        """
        if not self._cache_enabled:
            return

        if key in self._cache:
            self._cache[key] = value
            self._cache.move_to_end(key)
            return

        # Evict oldest entries if at capacity
        while len(self._cache) >= self._max_cache_size:
            evicted_key = next(iter(self._cache))
            del self._cache[evicted_key]
            logger.debug("query_intelligence_cache_evicted", key=evicted_key[:30])

        self._cache[key] = value

    def clear_cache(self) -> None:
        """Clear all caches."""
        self._cache.clear()
        self._expansion_cache.clear()
        logger.debug("query_intelligence_cache_cleared")


# ============================================================================
# Promise helper for concurrent execution (simple implementation)
# ============================================================================


class Promise:
    """Simple Promise-like helper for awaiting multiple coroutines."""

    @staticmethod
    async def all(coros):
        """Await multiple coroutines concurrently.

        Args:
            coros: List of coroutines to await

        Returns:
            List of results
        """
        results = []

        for coro in coros:
            results.append(await coro)
        return results
