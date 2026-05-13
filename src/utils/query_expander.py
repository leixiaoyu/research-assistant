"""Query Expander for Phase 7.2: Discovery Expansion.

Uses LLM to generate semantically related queries for broader
paper discovery coverage.

Phase 9.5 PR β (REQ-9.5.2.2):
- ``expand()`` now accepts an optional ``recent_paper_titles`` list so
  the LLM prompt can bias variants toward terminology adjacent to
  papers we've recently extracted.
- The in-memory cache now stores ``(insertion_time, value)`` tuples
  and expires entries after ``cache_ttl_days`` (default 7) so stale
  variants don't survive forever in long-running processes.
"""

import hashlib
import json
import re
import time
from typing import Dict, List, Optional, Sequence, Tuple, TYPE_CHECKING

import structlog

from src.models.config import QueryExpansionConfig

if TYPE_CHECKING:
    from src.services.llm import LLMService

logger = structlog.get_logger()


QUERY_EXPANSION_PROMPT = """You are an academic research assistant. \
Given a research query, generate {max_variants} alternative search queries \
that would find related academic papers.

Original query: {query}{context_section}

Requirements:
- Each alternative should use different terminology or phrasing
- Focus on academic/scientific language
- Include synonyms, related concepts, and alternative formulations
- Keep queries concise and searchable

Return ONLY a JSON array of strings, no other text:
["query 1", "query 2", ...]"""


# Phase 9.5 REQ-9.5.2.2 (PR β): bound the prompt-size contribution of
# recent_paper_titles. The spec wants ≤20 titles; we enforce that
# explicitly and log a structured event on truncation so it shows up in
# audit grep instead of silently shrinking the context.
RECENT_TITLES_PROMPT_CAP: int = 20


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
        # Phase 9.5 REQ-9.5.2.2 (PR β): cache stores (insertion_time, value)
        # tuples so a TTL can be enforced lazily on lookup. The previous
        # `Dict[str, List[str]]` shape had no expiry — entries persisted
        # for the entire process lifetime, which was fine for short CLI
        # runs but problematic for long-lived schedulers.
        self._cache: Dict[str, Tuple[float, List[str]]] = {}
        # Cache TTL in seconds. Default 7 days per spec (REQ-9.5.2.2).
        self._cache_ttl_seconds: float = float(self.config.cache_ttl_days) * 86400.0

    async def expand(
        self,
        query: str,
        recent_paper_titles: Optional[Sequence[str]] = None,
        max_variants: Optional[int] = None,
    ) -> List[str]:
        """Generate expanded query variants.

        Returns list of queries including the original.
        If LLM fails, returns only the original query.

        Phase 9.5 REQ-9.5.2.2 (PR β): when ``recent_paper_titles`` is
        provided, the LLM prompt is enriched with up to
        :data:`RECENT_TITLES_PROMPT_CAP` titles so the generated
        variants bias toward terminology adjacent to recently
        extracted papers. The cache key includes a hash of the titles
        so the same query with different recent corpora produces
        distinct cache entries.

        Args:
            query: Original search query
            recent_paper_titles: Optional recent corpus titles (≤20)
                used to inform variant generation
            max_variants: Maximum number of variants to generate

        Returns:
            List of queries with original first
        """
        max_variants = max_variants or self.config.max_variants

        # Truncate titles to the prompt cap and log if we dropped any.
        titles_for_prompt: List[str] = []
        if recent_paper_titles:
            full = list(recent_paper_titles)
            titles_for_prompt = full[:RECENT_TITLES_PROMPT_CAP]
            if len(full) > RECENT_TITLES_PROMPT_CAP:
                logger.info(
                    "query_expansion_context_truncated",
                    original_count=len(full),
                    used_count=len(titles_for_prompt),
                    cap=RECENT_TITLES_PROMPT_CAP,
                )

        # Check cache first
        if self.config.cache_expansions:
            cached = self._get_cached_expansion(query, titles_for_prompt)
            if cached is not None:
                logger.info("query_expansion_cache_hit", query=query[:50])
                return cached

        # If no LLM, return original only
        if self.llm is None:
            logger.warning("query_expansion_no_llm", query=query[:50])
            return [query]

        try:
            # Call LLM for expansion
            context_section = self._build_context_section(titles_for_prompt)
            prompt = QUERY_EXPANSION_PROMPT.format(
                query=query,
                max_variants=max_variants,
                context_section=context_section,
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
                self._cache_expansion(query, titles_for_prompt, result)

            logger.info(
                "query_expansion_success",
                original_query=query[:50],
                variants_generated=len(result) - 1,
            )
            return result

        except Exception as e:
            logger.warning("query_expansion_failed", query=query[:50], error=str(e))
            return [query]  # Graceful degradation

    @staticmethod
    def _build_context_section(titles: List[str]) -> str:
        """Render the recent-paper-titles section of the expansion prompt.

        Returns an empty string when no titles are provided so the
        prompt stays identical to the pre-9.5 wording for callers that
        don't pass a corpus context (backward compatibility).
        """
        if not titles:
            return ""
        bullets = "\n".join(f"- {t}" for t in titles)
        return (
            "\n\nContext: Recent papers in this topic area include:\n"
            f"{bullets}\n\n"
            "Use the terminology and concepts from those titles to inform "
            "your variants — variants that surface adjacent terminology are "
            "preferred."
        )

    def _get_cached_expansion(
        self,
        query: str,
        recent_paper_titles: Sequence[str],
    ) -> Optional[List[str]]:
        """Check cache for existing expansion, honouring TTL.

        Returns ``None`` on cache miss OR on expired entry. Expired
        entries are evicted in-place and a structured
        ``query_expansion_cache_expired`` event is emitted so cache
        churn is visible in audit logs.
        """
        cache_key = self._cache_key(query, recent_paper_titles)
        entry = self._cache.get(cache_key)
        if entry is None:
            return None
        inserted_at, value = entry
        if time.time() - inserted_at > self._cache_ttl_seconds:
            del self._cache[cache_key]
            logger.info(
                "query_expansion_cache_expired",
                query=query[:50],
                age_days=round((time.time() - inserted_at) / 86400.0, 2),
            )
            return None
        return value

    def _cache_expansion(
        self,
        query: str,
        recent_paper_titles: Sequence[str],
        variants: List[str],
    ) -> None:
        """Cache expansion result with an insertion timestamp."""
        cache_key = self._cache_key(query, recent_paper_titles)
        self._cache[cache_key] = (time.time(), variants)

    def _cache_key(self, query: str, recent_paper_titles: Sequence[str]) -> str:
        """Generate cache key for (query, recent_paper_titles) pair.

        Phase 9.5 REQ-9.5.2.2 (PR β): the recent_paper_titles
        contribute to the cache key so variants for the same query but
        a meaningfully different recent corpus don't collide. An empty
        title list produces a deterministic empty-set hash so
        backward-compatible callers (no titles) keep a stable key.
        """
        normalized_query = query.lower().strip()
        query_hash = hashlib.sha256(normalized_query.encode()).hexdigest()[:12]
        # Sort titles to make the key order-insensitive.
        normalized_titles = sorted(t.strip().lower() for t in recent_paper_titles)
        titles_repr = "|".join(normalized_titles)
        titles_hash = hashlib.sha256(titles_repr.encode()).hexdigest()[:8]
        return f"{self.CACHE_PREFIX}:{query_hash}:{titles_hash}"

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
