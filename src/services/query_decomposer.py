"""Query Decomposer for Phase 6: Enhanced Discovery Pipeline.

Transforms broad research queries into multiple focused sub-queries
using LLM to improve recall across different research perspectives.

Usage:
    from src.services.query_decomposer import QueryDecomposer
    from src.services.llm import LLMService

    llm_service = LLMService(...)
    decomposer = QueryDecomposer(llm_service)
    queries = await decomposer.decompose("Tree of Thoughts for machine translation")
"""

import json
import re
from typing import List, Optional, TYPE_CHECKING

import structlog

from src.models.discovery import DecomposedQuery, QueryFocus

if TYPE_CHECKING:
    from src.services.llm import LLMService

logger = structlog.get_logger()

# Decomposition prompt template
# fmt: off
DECOMPOSITION_PROMPT = (  # noqa: E501
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
    "Output ONLY a valid JSON array with objects containing \"query\" and "
    "\"focus\" fields.\n"
    "Valid focus values: \"methodology\", \"application\", \"comparison\", "
    "\"related\", \"intersection\"\n\n"
    "Example output format:\n"
    "[\n"
    "  {{\"query\": \"Tree of Thoughts prompting technique\", "
    "\"focus\": \"methodology\"}},\n"
    "  {{\"query\": \"reasoning-based neural machine translation\", "
    "\"focus\": \"application\"}}\n"
    "]\n\n"
    "Now generate {max_subqueries} sub-queries for the given query. "
    "Output ONLY the JSON array, no other text:"
)
# fmt: on


class QueryDecomposer:
    """Decomposes research queries into focused sub-queries using LLM.

    Takes a broad research query and generates multiple focused sub-queries
    targeting different aspects (methodology, application, comparison, etc.)
    to improve paper retrieval recall.

    Attributes:
        llm_service: LLM service for query generation
        cache: Simple cache for decomposed queries
    """

    def __init__(
        self,
        llm_service: Optional["LLMService"] = None,
        enable_cache: bool = True,
    ) -> None:
        """Initialize QueryDecomposer.

        Args:
            llm_service: LLM service for decomposition. If None, decomposition
                is disabled and only the original query is returned.
            enable_cache: Enable caching of decomposed queries
        """
        self._llm_service = llm_service
        self._cache: dict[str, List[DecomposedQuery]] = {} if enable_cache else {}
        self._cache_enabled = enable_cache

    @property
    def llm_service(self) -> Optional["LLMService"]:
        """Get the LLM service."""
        return self._llm_service

    async def decompose(
        self,
        query: str,
        max_subqueries: int = 5,
        include_original: bool = True,
    ) -> List[DecomposedQuery]:
        """Decompose a research query into focused sub-queries.

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
        # Validate inputs
        if not query or not query.strip():
            logger.warning("query_decomposer_empty_query")
            return []

        query = query.strip()
        cache_key = f"{query}:{max_subqueries}:{include_original}"

        # Check cache
        if self._cache_enabled and cache_key in self._cache:
            logger.debug("query_decomposer_cache_hit", query=query[:50])
            return self._cache[cache_key]

        # If no LLM service, return original query only
        if self._llm_service is None:
            logger.info(
                "query_decomposer_no_llm",
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
            if self._cache_enabled:
                self._cache[cache_key] = result
            return result

        logger.info(
            "query_decomposer_starting",
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
            if self._cache_enabled:
                self._cache[cache_key] = result

            logger.info(
                "query_decomposer_completed",
                query=query[:50],
                subqueries_generated=len(subqueries),
                total_queries=len(result),
            )

            return result

        except Exception as e:
            logger.error(
                "query_decomposer_failed",
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
            if self._cache_enabled:
                self._cache[cache_key] = result
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

        # Call LLM service
        # NOTE: complete() method to be added to LLMService during integration phase
        assert self._llm_service is not None
        response = await self._llm_service.complete(  # type: ignore[attr-defined]
            prompt=prompt,
            system_prompt="You are a helpful assistant that outputs only valid JSON.",
            temperature=0.3,  # Low temperature for consistency
            max_tokens=1000,
        )

        # Parse response
        return self._parse_llm_response(response.content)

    def _parse_llm_response(self, response: str) -> List[DecomposedQuery]:
        """Parse LLM response into DecomposedQuery objects.

        Args:
            response: Raw LLM response text

        Returns:
            List of DecomposedQuery objects
        """
        # Try to extract JSON from response
        json_str = self._extract_json(response)

        if not json_str:
            logger.warning(
                "query_decomposer_no_json_found",
                response_preview=response[:200],
            )
            return []

        try:
            data = json.loads(json_str)

            if not isinstance(data, list):
                logger.warning("query_decomposer_invalid_json_format")
                return []

            queries = []
            for item in data:
                if not isinstance(item, dict):
                    continue

                query_text = item.get("query", "").strip()
                focus_str = item.get("focus", "related").lower().strip()

                if not query_text:
                    continue

                # Map focus string to enum
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
                "query_decomposer_json_parse_error",
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
        # Look for pattern starting with [ and ending with ]
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

    def clear_cache(self) -> None:
        """Clear the decomposition cache."""
        self._cache.clear()
        logger.debug("query_decomposer_cache_cleared")
