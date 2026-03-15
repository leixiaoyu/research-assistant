"""Query Expander for Phase 7.2: Discovery Expansion.

Uses LLM to generate semantically related queries for broader
paper discovery coverage.
"""

import hashlib
import json
import re
from typing import Dict, List, Optional, TYPE_CHECKING

import structlog

from src.models.config import QueryExpansionConfig

if TYPE_CHECKING:
    from src.services.llm import LLMService

logger = structlog.get_logger()


QUERY_EXPANSION_PROMPT = """You are an academic research assistant. \
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


class QueryExpander:
    """Generates semantically related queries using LLM."""

    CACHE_PREFIX = "query_expansion"

    def __init__(
        self,
        llm_service: Optional["LLMService"] = None,
        config: Optional[QueryExpansionConfig] = None,
    ):
        """Initialize QueryExpander.

        Args:
            llm_service: LLM service for generating expansions
            config: Query expansion configuration
        """
        self.llm = llm_service
        self.config = config or QueryExpansionConfig()
        # Simple in-memory cache for query expansions
        self._cache: Dict[str, List[str]] = {}

    async def expand(
        self,
        query: str,
        max_variants: Optional[int] = None,
    ) -> List[str]:
        """Generate expanded query variants.

        Returns list of queries including the original.
        If LLM fails, returns only the original query.

        Args:
            query: Original search query
            max_variants: Maximum number of variants to generate

        Returns:
            List of queries with original first
        """
        max_variants = max_variants or self.config.max_variants

        # Check cache first
        if self.config.cache_expansions:
            cached = self._get_cached_expansion(query)
            if cached is not None:
                logger.info("query_expansion_cache_hit", query=query[:50])
                return cached

        # If no LLM, return original only
        if self.llm is None:
            logger.warning("query_expansion_no_llm", query=query[:50])
            return [query]

        try:
            # Call LLM for expansion
            prompt = QUERY_EXPANSION_PROMPT.format(
                query=query,
                max_variants=max_variants,
            )
            response = await self.llm.complete(prompt)
            # LLMResponse has a .content attribute
            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            variants = self._parse_response(content)

            # Always include original query first
            result = [query] + [v for v in variants if v.lower() != query.lower()]

            # Limit to max_variants + 1 (original + variants)
            result = result[: max_variants + 1]

            # Cache result
            if self.config.cache_expansions:
                self._cache_expansion(query, result)

            logger.info(
                "query_expansion_success",
                original_query=query[:50],
                variants_generated=len(result) - 1,
            )
            return result

        except Exception as e:
            logger.warning("query_expansion_failed", query=query[:50], error=str(e))
            return [query]  # Graceful degradation

    def _get_cached_expansion(self, query: str) -> Optional[List[str]]:
        """Check cache for existing expansion.

        Args:
            query: Original query

        Returns:
            Cached expansion list or None
        """
        cache_key = self._cache_key(query)
        return self._cache.get(cache_key)

    def _cache_expansion(self, query: str, variants: List[str]) -> None:
        """Cache expansion result.

        Args:
            query: Original query
            variants: List of query variants
        """
        cache_key = self._cache_key(query)
        self._cache[cache_key] = variants

    def _cache_key(self, query: str) -> str:
        """Generate cache key for query.

        Args:
            query: Original query

        Returns:
            Cache key string
        """
        normalized = query.lower().strip()
        hash_str = hashlib.sha256(normalized.encode()).hexdigest()[:12]
        return f"{self.CACHE_PREFIX}:{hash_str}"

    def _parse_response(self, response: str) -> List[str]:
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

        logger.warning("query_expansion_parse_failed", response=response[:100])
        return []
