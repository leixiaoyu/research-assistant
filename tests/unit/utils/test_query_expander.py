"""Tests for QueryExpander utility.

Split from test_phase_7_2_components.py for better organization.
Tests cover LLM-based query expansion with caching and parsing.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.models.config import QueryExpansionConfig
from src.utils.query_expander import QueryExpander


class TestQueryExpander:
    """Tests for QueryExpander."""

    @pytest.fixture
    def mock_llm_service(self):
        """Create mock LLM service."""
        llm = MagicMock()
        llm.complete = AsyncMock()
        return llm

    @pytest.fixture
    def expander(self, mock_llm_service):
        """Create QueryExpander with mock LLM."""
        return QueryExpander(llm_service=mock_llm_service)

    @pytest.mark.asyncio
    async def test_expand_returns_original_when_no_llm(self):
        """Test expansion returns only original query when no LLM configured."""
        expander = QueryExpander(llm_service=None)
        result = await expander.expand("machine learning")
        assert result == ["machine learning"]

    @pytest.mark.asyncio
    async def test_expand_success(self, expander, mock_llm_service):
        """Test successful query expansion."""
        mock_response = MagicMock()
        mock_response.content = '["deep learning", "neural networks", "AI"]'
        mock_llm_service.complete.return_value = mock_response

        result = await expander.expand("machine learning")

        assert "machine learning" in result
        assert len(result) >= 1
        mock_llm_service.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_expand_handles_llm_error(self, expander, mock_llm_service):
        """Test graceful degradation on LLM error."""
        mock_llm_service.complete.side_effect = Exception("LLM error")

        result = await expander.expand("machine learning")

        assert result == ["machine learning"]

    @pytest.mark.asyncio
    async def test_expand_caches_results(self, expander, mock_llm_service):
        """Test query expansion caching."""
        mock_response = MagicMock()
        mock_response.content = '["variant 1", "variant 2"]'
        mock_llm_service.complete.return_value = mock_response

        # First call
        result1 = await expander.expand("test query")
        # Second call - should use cache
        result2 = await expander.expand("test query")

        assert result1 == result2
        # LLM should only be called once due to caching
        assert mock_llm_service.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_expand_respects_max_variants(self, expander, mock_llm_service):
        """Test max_variants limit is respected."""
        mock_response = MagicMock()
        mock_response.content = '["v1", "v2", "v3", "v4", "v5", "v6", "v7"]'
        mock_llm_service.complete.return_value = mock_response

        result = await expander.expand("test", max_variants=3)

        # Should have original + max 3 variants = 4 total
        assert len(result) <= 4

    def test_parse_response_json_array(self, expander):
        """Test parsing plain JSON array."""
        result = expander._parse_response('["query1", "query2"]')
        assert result == ["query1", "query2"]

    def test_parse_response_markdown_code_block(self, expander):
        """Test parsing JSON in markdown code block."""
        response = '```json\n["query1", "query2"]\n```'
        result = expander._parse_response(response)
        assert result == ["query1", "query2"]

    def test_parse_response_embedded_json(self, expander):
        """Test parsing JSON embedded in text."""
        response = 'Here are the queries: ["query1", "query2"] end'
        result = expander._parse_response(response)
        assert result == ["query1", "query2"]

    def test_parse_response_empty(self, expander):
        """Test parsing empty response."""
        assert expander._parse_response("") == []
        assert expander._parse_response("invalid") == []

    def test_cache_key_normalization(self, expander):
        """Test cache key normalization (lowercase and strip).

        Phase 9.5 PR β: `_cache_key` now takes a second
        ``recent_paper_titles`` argument; pass an empty list so the
        normalization assertion still pins the query-side behavior.
        """
        key1 = expander._cache_key("Machine Learning", [])
        key2 = expander._cache_key("machine learning", [])
        key3 = expander._cache_key("  machine learning  ", [])

        # Same content after lowercase and strip should have same key
        assert key1 == key2
        assert key2 == key3


class TestQueryExpanderCaching:
    """Tests for QueryExpander caching."""

    @pytest.mark.asyncio
    async def test_cache_stores_expansion_result(self):
        """Test that expansion results are cached."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value='["query 1", "query 2"]')

        config = QueryExpansionConfig(cache_expansions=True)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        # First call
        result1 = await expander.expand("machine learning")
        assert len(result1) >= 1

        # Second call should use cache
        result2 = await expander.expand("machine learning")
        assert result1 == result2

        # LLM should only be called once
        assert mock_llm.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json(self):
        """Test handling of invalid JSON from LLM."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value="not valid json")

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Should fall back to original query
        assert result == ["test query"]

    @pytest.mark.asyncio
    async def test_llm_returns_non_list(self):
        """Test handling of non-list JSON from LLM."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value='{"query": "test"}')

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Should fall back to original query
        assert result == ["test query"]


class TestQueryExpanderParsing:
    """Tests for QueryExpander response parsing edge cases."""

    @pytest.mark.asyncio
    async def test_parse_code_block_with_invalid_json(self):
        """Test parsing code block with invalid JSON inside."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value="```json\n{not valid json\n```")

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Should fall back to original query
        assert result == ["test query"]

    @pytest.mark.asyncio
    async def test_parse_array_in_text_invalid_json(self):
        """Test parsing array pattern with invalid JSON."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value="Here are queries: [invalid json array"
        )

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Should fall back to original query
        assert result == ["test query"]

    @pytest.mark.asyncio
    async def test_parse_code_block_non_list(self):
        """Test parsing code block returning non-list JSON."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value='```json\n{"key": "value"}\n```')

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Should fall back to original query
        assert result == ["test query"]

    @pytest.mark.asyncio
    async def test_parse_array_non_list(self):
        """Test parsing array pattern returning non-list."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value='Result: {"not": "array"}')

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Should fall back to original query
        assert result == ["test query"]


class TestQueryExpanderEdgeCases:
    """Additional edge case tests for QueryExpander."""

    @pytest.mark.asyncio
    async def test_parse_valid_array_in_text(self):
        """Test parsing valid JSON array embedded in text."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value='Here are the queries: ["query one", "query two"]'
        )

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Result includes original query + expanded variants
        assert len(result) == 3
        assert "test query" in result
        assert "query one" in result
        assert "query two" in result

    @pytest.mark.asyncio
    async def test_parse_empty_array(self):
        """Test parsing empty array returns original query."""
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value="[]")

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Empty array should fall back to original
        assert result == ["test query"]

    @pytest.mark.asyncio
    async def test_parse_array_pattern_invalid_json(self):
        """Test parsing with array pattern that has invalid JSON."""
        mock_llm = MagicMock()
        # Has bracket pattern but invalid JSON inside
        mock_llm.complete = AsyncMock(
            return_value="Here is the result: [not valid json]"
        )

        config = QueryExpansionConfig(cache_expansions=False)
        expander = QueryExpander(llm_service=mock_llm, config=config)

        result = await expander.expand("test query")

        # Should fall back to original query after JSONDecodeError
        assert result == ["test query"]


class TestRecentPaperTitlesContext:
    """Phase 9.5 REQ-9.5.2.2 (PR β) — recent_paper_titles biases variants.

    Backward compatibility: calling expand() without the new param
    behaves identically to the pre-9.5 API. New param injects a
    "Recent papers in this topic area include" section into the prompt
    and caps at RECENT_TITLES_PROMPT_CAP titles.
    """

    @pytest.fixture
    def mock_llm_service(self):
        llm = MagicMock()
        llm.complete = AsyncMock()
        return llm

    @pytest.fixture
    def expander(self, mock_llm_service):
        return QueryExpander(llm_service=mock_llm_service)

    @pytest.mark.asyncio
    async def test_backward_compat_no_titles_param(self, expander, mock_llm_service):
        """Calling expand(query) without titles works identically to pre-9.5."""
        response = MagicMock()
        response.content = '["variant 1", "variant 2"]'
        mock_llm_service.complete.return_value = response

        result = await expander.expand("test query")

        assert result == ["test query", "variant 1", "variant 2"]
        # The prompt sent to the LLM must NOT contain the context section
        sent_prompt = mock_llm_service.complete.call_args.args[0]
        assert "Recent papers in this topic area" not in sent_prompt

    @pytest.mark.asyncio
    async def test_titles_inject_into_prompt(self, expander, mock_llm_service):
        """When titles are provided, the prompt includes them as bullets."""
        response = MagicMock()
        response.content = '["v1"]'
        mock_llm_service.complete.return_value = response

        await expander.expand(
            "machine translation",
            recent_paper_titles=["Tree of Thoughts in NMT", "Sparse attention for MT"],
        )

        sent_prompt = mock_llm_service.complete.call_args.args[0]
        assert "Recent papers in this topic area include" in sent_prompt
        assert "Tree of Thoughts in NMT" in sent_prompt
        assert "Sparse attention for MT" in sent_prompt

    @pytest.mark.asyncio
    async def test_titles_capped_at_prompt_cap(self, expander, mock_llm_service):
        """More than 20 titles → only first 20 reach the prompt + log event."""
        import structlog
        from src.utils.query_expander import RECENT_TITLES_PROMPT_CAP

        response = MagicMock()
        response.content = '["v1"]'
        mock_llm_service.complete.return_value = response

        many_titles = [f"Title {i}" for i in range(25)]

        with structlog.testing.capture_logs() as logs:
            await expander.expand("q", recent_paper_titles=many_titles)

        sent_prompt = mock_llm_service.complete.call_args.args[0]
        # Title 0..19 should be in prompt; title 20..24 should not
        assert "Title 19" in sent_prompt
        assert "Title 20" not in sent_prompt
        # And a truncation event MUST fire so audit grep sees it
        trunc = [e for e in logs if e["event"] == "query_expansion_context_truncated"]
        assert len(trunc) == 1
        assert trunc[0]["original_count"] == 25
        assert trunc[0]["used_count"] == RECENT_TITLES_PROMPT_CAP

    @pytest.mark.asyncio
    async def test_cache_key_differs_per_title_set(self, expander, mock_llm_service):
        """Same query, different titles → different cache entries (no collision)."""
        response = MagicMock()
        response.content = '["v1"]'
        mock_llm_service.complete.return_value = response

        await expander.expand("q", recent_paper_titles=["A"])
        await expander.expand("q", recent_paper_titles=["B"])

        # Two distinct calls because the cache key includes the title hash
        assert mock_llm_service.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_cache_key_same_for_same_titles_unordered(
        self, expander, mock_llm_service
    ):
        """Same query + same titles (different order) → cache hit on second call."""
        response = MagicMock()
        response.content = '["v1"]'
        mock_llm_service.complete.return_value = response

        await expander.expand("q", recent_paper_titles=["A", "B"])
        await expander.expand("q", recent_paper_titles=["B", "A"])

        # Order-insensitive cache key → only one LLM call
        assert mock_llm_service.complete.call_count == 1


class TestQueryExpanderCacheTTL:
    """Phase 9.5 REQ-9.5.2.2 (PR β) — 7-day cache TTL.

    Uses time monkeypatching so tests don't actually sleep. Confirms
    the cache returns hits before TTL expiry, returns misses after,
    and respects the configurable ``cache_ttl_days`` setting.
    """

    @pytest.fixture
    def mock_llm_service(self):
        llm = MagicMock()
        llm.complete = AsyncMock()
        return llm

    @pytest.mark.asyncio
    async def test_cache_hit_within_ttl(self, monkeypatch, mock_llm_service):
        """Entry inserted now, looked up 6 days later → hit, no second LLM call."""
        from src.utils import query_expander as qe_module

        response = MagicMock()
        response.content = '["v1"]'
        mock_llm_service.complete.return_value = response

        # Pin clock at t=0 for insert
        fake_now = [1_000_000.0]
        monkeypatch.setattr(qe_module.time, "time", lambda: fake_now[0])

        expander = QueryExpander(llm_service=mock_llm_service)
        await expander.expand("q")

        # Advance 6 days
        fake_now[0] += 6 * 86400
        await expander.expand("q")

        assert mock_llm_service.complete.call_count == 1, "Cache MUST hit within TTL"

    @pytest.mark.asyncio
    async def test_cache_miss_after_ttl_expiry(self, monkeypatch, mock_llm_service):
        """Entry expires after 7 days → second call re-fetches + emits event."""
        import structlog
        from src.utils import query_expander as qe_module

        response = MagicMock()
        response.content = '["v1"]'
        mock_llm_service.complete.return_value = response

        fake_now = [1_000_000.0]
        monkeypatch.setattr(qe_module.time, "time", lambda: fake_now[0])

        expander = QueryExpander(llm_service=mock_llm_service)
        await expander.expand("q")  # insert at t=0

        # Advance 8 days → entry is expired
        fake_now[0] += 8 * 86400

        with structlog.testing.capture_logs() as logs:
            await expander.expand("q")

        assert mock_llm_service.complete.call_count == 2, "Cache MUST miss after TTL"
        expired_events = [
            e for e in logs if e["event"] == "query_expansion_cache_expired"
        ]
        assert len(expired_events) == 1

    @pytest.mark.asyncio
    async def test_configurable_ttl(self, monkeypatch, mock_llm_service):
        """``cache_ttl_days`` override is honored (1-day TTL expires after 25h)."""
        from src.models.config import QueryExpansionConfig
        from src.utils import query_expander as qe_module

        response = MagicMock()
        response.content = '["v1"]'
        mock_llm_service.complete.return_value = response

        fake_now = [1_000_000.0]
        monkeypatch.setattr(qe_module.time, "time", lambda: fake_now[0])

        expander = QueryExpander(
            llm_service=mock_llm_service,
            config=QueryExpansionConfig(cache_ttl_days=1),
        )
        await expander.expand("q")

        # Advance 25 hours (>1 day TTL)
        fake_now[0] += 25 * 3600
        await expander.expand("q")

        assert mock_llm_service.complete.call_count == 2

    def test_default_ttl_is_seven_days(self):
        """Default TTL matches spec (7 days = 604800 seconds)."""
        expander = QueryExpander()
        assert expander._cache_ttl_seconds == 7 * 86400.0
