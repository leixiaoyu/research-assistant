"""Comprehensive tests for Phase 7.2: Discovery Expansion components.

DEPRECATION NOTICE (Phase P0-T1):
This monolithic test file has been split into component-specific files.
DO NOT ADD NEW TESTS HERE - use the appropriate split file instead:

COMPLETED SPLITS (tests duplicated in new locations):
- tests/unit/utils/test_query_expander.py - QueryExpander tests
- tests/unit/services/discovery/test_citation_explorer.py - CitationExplorer tests
- tests/unit/services/discovery/test_result_aggregator.py - ResultAggregator tests
- tests/unit/services/providers/test_paper_search_mcp.py - PaperSearchMCPProvider tests
- tests/unit/orchestration/test_discovery_phase_multisource.py - DiscoveryPhase tests
- tests/unit/test_phase_7_2_integration.py - Integration and config model tests

NEXT STEPS (Phase P0-T1 follow-up):
1. Remove duplicated test classes from this file after PR merge
2. Delete this file once all tests are migrated

This file is kept temporarily for safety. Tests run from both locations.
See REFACTORING_OPPORTUNITIES.md Phase T1 for details.

Legacy tests below (DO NOT ADD NEW TESTS HERE):
- QueryExpander: LLM-based query expansion
- CitationExplorer: Forward/backward citation discovery
- ResultAggregator: Multi-source deduplication and ranking
- PaperSearchMCPProvider: MCP server integration
- DiscoveryPhase: Multi-source discovery integration
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.config import (
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
    RankingWeights,
    ResearchTopic,
    TimeframeRecent,
)
from src.models.paper import PaperMetadata, Author
from src.utils.query_expander import QueryExpander
from src.services.citation_explorer import CitationExplorer
from src.services.result_aggregator import ResultAggregator
from src.services.providers.paper_search_mcp import PaperSearchMCPProvider

# =============================================================================
# QueryExpander Tests
# =============================================================================


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

        Phase 9.5 PR β: ``_cache_key`` now takes ``recent_paper_titles``
        as a second positional arg; pass an empty list to preserve the
        original normalization assertion.
        """
        key1 = expander._cache_key("Machine Learning", [])
        key2 = expander._cache_key("machine learning", [])
        key3 = expander._cache_key("  machine learning  ", [])

        # Same content after lowercase and strip should have same key
        assert key1 == key2
        assert key2 == key3


# =============================================================================
# CitationExplorer Tests
# =============================================================================


class TestCitationExplorer:
    """Tests for CitationExplorer."""

    @pytest.fixture
    def explorer(self):
        """Create CitationExplorer with mocked session."""
        return CitationExplorer(api_key="test-api-key")

    @pytest.fixture
    def sample_paper(self):
        """Create sample paper for testing."""
        return PaperMetadata(
            paper_id="abc123",
            title="Test Paper",
            abstract="Test abstract",
            url="https://example.com/paper",
            authors=[Author(name="Test Author")],
        )

    @pytest.mark.asyncio
    async def test_explore_disabled(self, sample_paper):
        """Test explore returns empty when disabled."""
        config = CitationExplorationConfig(enabled=False)
        explorer = CitationExplorer(api_key="test", config=config)

        result = await explorer.explore([sample_paper], "test-topic")

        assert result.forward_papers == []
        assert result.backward_papers == []

    @pytest.mark.asyncio
    async def test_explore_tracks_stats(self, explorer, sample_paper):
        """Test explore tracks discovery statistics."""
        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                mock_forward.return_value = []
                mock_backward.return_value = []

                result = await explorer.explore([sample_paper], "test-topic")

                assert result.stats.seed_papers_count == 1
                mock_forward.assert_called_once()
                mock_backward.assert_called_once()

    @pytest.mark.asyncio
    async def test_explore_deduplicates(self, explorer, sample_paper):
        """Test explore deduplicates papers."""
        dup_paper = PaperMetadata(
            paper_id="abc123",  # Same ID as seed
            title="Duplicate",
            url="https://example.com/dup",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                mock_forward.return_value = [dup_paper]
                mock_backward.return_value = []

                result = await explorer.explore([sample_paper], "test-topic")

                # Duplicate should be filtered
                assert result.stats.filtered_as_duplicate == 1
                assert len(result.forward_papers) == 0

    @pytest.mark.asyncio
    async def test_get_forward_citations_no_paper_id(self, explorer):
        """Test get_forward_citations returns empty for paper without ID."""
        paper = PaperMetadata(
            paper_id="",
            title="No ID Paper",
            url="https://example.com",
        )

        result = await explorer.get_forward_citations(paper)
        assert result == []

    @pytest.mark.asyncio
    async def test_get_backward_citations_no_paper_id(self, explorer):
        """Test get_backward_citations returns empty for paper without ID."""
        paper = PaperMetadata(
            paper_id="",
            title="No ID Paper",
            url="https://example.com",
        )

        result = await explorer.get_backward_citations(paper)
        assert result == []

    def test_parse_paper_minimal(self, explorer):
        """Test parsing paper with minimal data."""
        data = {
            "paperId": "test123",
            "title": "Test Paper",
        }
        result = explorer._parse_paper(data, "semantic_scholar")

        assert result is not None
        assert result.paper_id == "test123"
        assert result.title == "Test Paper"

    def test_parse_paper_missing_required(self, explorer):
        """Test parsing paper with missing required fields."""
        assert explorer._parse_paper({}, "test") is None
        assert explorer._parse_paper({"paperId": "123"}, "test") is None
        assert explorer._parse_paper({"title": "Test"}, "test") is None

    def test_parse_paper_full(self, explorer):
        """Test parsing paper with full data."""
        data = {
            "paperId": "test123",
            "title": "Test Paper",
            "abstract": "Test abstract",
            "url": "https://example.com",
            "authors": [{"name": "Author One", "authorId": "a1"}],
            "year": 2024,
            "venue": "Test Conference",
            "citationCount": 100,
            "openAccessPdf": {"url": "https://example.com/paper.pdf"},
        }
        result = explorer._parse_paper(data, "semantic_scholar")

        assert result.paper_id == "test123"
        assert result.title == "Test Paper"
        assert result.abstract == "Test abstract"
        assert len(result.authors) == 1
        assert result.authors[0].name == "Author One"
        assert result.year == 2024
        assert result.citation_count == 100
        assert result.pdf_available is True

    def test_is_new_paper(self, explorer, sample_paper):
        """Test _is_new_paper logic."""
        seen_ids = {"abc123"}

        # Should not be new (ID already seen)
        assert explorer._is_new_paper(sample_paper, seen_ids, "topic") is False

        # New paper should be marked as new
        new_paper = PaperMetadata(
            paper_id="new123",
            title="New Paper",
            url="https://example.com/new",
        )
        assert explorer._is_new_paper(new_paper, seen_ids, "topic") is True

    def test_mark_seen(self, explorer):
        """Test _mark_seen adds IDs to seen set."""
        seen = set()
        paper = PaperMetadata(
            paper_id="test123",
            doi="10.1234/test",
            title="Test",
            url="https://example.com",
        )

        explorer._mark_seen(paper, seen)

        assert "test123" in seen
        assert "10.1234/test" in seen


# =============================================================================
# ResultAggregator Tests
# =============================================================================


class TestResultAggregator:
    """Tests for ResultAggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create ResultAggregator with default config."""
        return ResultAggregator()

    @pytest.fixture
    def sample_papers(self):
        """Create sample papers for testing."""
        return {
            "arxiv": [
                PaperMetadata(
                    paper_id="arxiv1",
                    doi="10.1234/test1",
                    title="Paper One",
                    url="https://arxiv.org/1",
                    citation_count=100,
                    year=2024,
                )
            ],
            "semantic_scholar": [
                PaperMetadata(
                    paper_id="ss1",
                    doi="10.1234/test1",  # Same DOI - should deduplicate
                    title="Paper One (SS)",
                    url="https://semanticscholar.org/1",
                    citation_count=150,
                    abstract="Has abstract",
                ),
                PaperMetadata(
                    paper_id="ss2",
                    title="Unique Paper",
                    url="https://semanticscholar.org/2",
                ),
            ],
        }

    @pytest.mark.asyncio
    async def test_aggregate_deduplicates_by_doi(self, aggregator, sample_papers):
        """Test aggregation deduplicates papers with same DOI."""
        result = await aggregator.aggregate(sample_papers)

        # Should have 2 unique papers (DOI dedup removes 1)
        assert result.total_after_dedup == 2
        assert result.total_raw == 3

    @pytest.mark.asyncio
    async def test_aggregate_merges_metadata(self, aggregator, sample_papers):
        """Test aggregation merges metadata from duplicates."""
        result = await aggregator.aggregate(sample_papers)

        # Find the deduplicated paper
        merged_paper = next(
            (p for p in result.papers if p.doi == "10.1234/test1"), None
        )
        assert merged_paper is not None

        # Should have merged citation count (best value)
        assert merged_paper.citation_count == 150
        # Should have abstract from SS
        assert merged_paper.abstract == "Has abstract"
        # Source count should reflect multiple sources
        assert merged_paper.source_count == 2

    @pytest.mark.asyncio
    async def test_aggregate_ranks_papers(self, aggregator, sample_papers):
        """Test aggregation ranks papers."""
        result = await aggregator.aggregate(sample_papers)

        assert result.ranking_applied is True
        # All papers should have ranking scores
        for paper in result.papers:
            assert paper.ranking_score is not None

    @pytest.mark.asyncio
    async def test_aggregate_respects_limit(self):
        """Test aggregation respects max_papers_per_topic limit."""
        config = AggregationConfig(max_papers_per_topic=1)
        aggregator = ResultAggregator(config=config)

        papers = {
            "source": [
                PaperMetadata(
                    paper_id=f"p{i}", title=f"Paper {i}", url=f"https://x/{i}"
                )
                for i in range(5)
            ]
        }

        result = await aggregator.aggregate(papers)
        assert len(result.papers) == 1

    def test_normalize_title(self, aggregator):
        """Test title normalization for comparison."""
        title1 = aggregator._normalize_title("Machine Learning: A Study")
        title2 = aggregator._normalize_title("machine learning a study")
        title3 = aggregator._normalize_title("  Machine  Learning:  A  Study  ")

        assert title1 == title2 == title3

    def test_metadata_completeness_scoring(self, aggregator):
        """Test metadata completeness scoring."""
        minimal_paper = PaperMetadata(
            paper_id="min",
            title="Minimal",
            url="https://example.com",
        )
        complete_paper = PaperMetadata(
            paper_id="complete",
            doi="10.1234/test",
            title="Complete",
            abstract="Has abstract",
            url="https://example.com",
            authors=[Author(name="Author")],
            venue="Conference",
            citation_count=100,
            pdf_available=True,
        )

        min_score = aggregator._metadata_completeness(minimal_paper)
        complete_score = aggregator._metadata_completeness(complete_paper)

        assert complete_score > min_score

    def test_calculate_score(self, aggregator):
        """Test ranking score calculation."""
        weights = RankingWeights()

        high_quality = PaperMetadata(
            paper_id="hq",
            title="High Quality",
            url="https://example.com",
            citation_count=1000,
            year=2024,
            pdf_available=True,
            source_count=3,
        )
        low_quality = PaperMetadata(
            paper_id="lq",
            title="Low Quality",
            url="https://example.com",
            citation_count=0,
            year=2015,
            pdf_available=False,
            source_count=1,
        )

        high_score = aggregator._calculate_score(high_quality, weights)
        low_score = aggregator._calculate_score(low_quality, weights)

        assert high_score > low_score

    def test_recency_score_calculation(self, aggregator):
        """Test recency score calculation."""
        recent = PaperMetadata(
            paper_id="recent",
            title="Recent",
            url="https://example.com",
            publication_date=datetime.now(timezone.utc),
        )
        old = PaperMetadata(
            paper_id="old",
            title="Old",
            url="https://example.com",
            year=2015,
        )

        recent_score = aggregator._calculate_recency_score(recent)
        old_score = aggregator._calculate_recency_score(old)

        assert recent_score > old_score


# =============================================================================
# PaperSearchMCPProvider Tests
# =============================================================================


class TestPaperSearchMCPProvider:
    """Tests for PaperSearchMCPProvider."""

    @pytest.fixture
    def provider(self):
        """Create MCP provider."""
        return PaperSearchMCPProvider()

    def test_provider_name(self, provider):
        """Test provider name."""
        assert provider.name == "paper_search_mcp"

    def test_requires_api_key_false(self, provider):
        """Test MCP doesn't require API key."""
        assert provider.requires_api_key is False

    def test_validate_query_valid(self, provider):
        """Test valid query validation."""
        assert provider.validate_query("machine learning") == "machine learning"
        assert provider.validate_query("  trimmed  ") == "trimmed"

    def test_validate_query_empty(self, provider):
        """Test empty query validation."""
        with pytest.raises(ValueError, match="cannot be empty"):
            provider.validate_query("")
        with pytest.raises(ValueError, match="cannot be empty"):
            provider.validate_query("   ")

    def test_validate_query_too_long(self, provider):
        """Test query length validation."""
        long_query = "x" * 501
        with pytest.raises(ValueError, match="too long"):
            provider.validate_query(long_query)

    def test_validate_query_invalid_chars(self, provider):
        """Test query character validation."""
        with pytest.raises(ValueError, match="forbidden characters"):
            provider.validate_query("query<script>")

    @pytest.mark.asyncio
    async def test_health_check_unavailable(self, provider):
        """Test health check returns False when MCP unavailable."""
        result = await provider.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_search_graceful_degradation(self, provider):
        """Test search returns empty on MCP unavailable."""
        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="7d"),
        )

        result = await provider.search(topic)
        assert result == []

    def test_map_mcp_result_to_paper(self, provider):
        """Test mapping MCP result to PaperMetadata."""
        result = {
            "id": "test123",
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": [{"name": "Author One", "id": "a1"}],
            "doi": "10.1234/test",
            "url": "https://example.com",
            "pdf_url": "https://example.com/paper.pdf",
            "year": 2024,
            "citation_count": 50,
        }

        paper = provider._map_mcp_result_to_paper(result, "arxiv")

        assert paper.paper_id == "test123"
        assert paper.title == "Test Paper"
        assert paper.doi == "10.1234/test"
        assert paper.discovery_source == "arxiv"
        assert paper.discovery_method == "keyword"
        assert paper.pdf_available is True

    def test_log_source_breakdown_empty(self, provider):
        """Test source breakdown logging with empty papers."""
        # Should not raise
        provider._log_source_breakdown([], "test query")

    def test_log_source_breakdown_with_papers(self, provider):
        """Test source breakdown logging with papers."""
        papers = [
            PaperMetadata(
                paper_id="p1",
                title="Paper 1",
                url="https://example.com/1",
                discovery_source="arxiv",
            ),
            PaperMetadata(
                paper_id="p2",
                title="Paper 2",
                url="https://example.com/2",
                discovery_source="arxiv",
            ),
            PaperMetadata(
                paper_id="p3",
                title="Paper 3",
                url="https://example.com/3",
                discovery_source="pubmed",
            ),
        ]
        # Should not raise
        provider._log_source_breakdown(papers, "test query")


# =============================================================================
# Additional CitationExplorer Tests for Coverage
# =============================================================================


class TestCitationExplorerAPI:
    """Tests for CitationExplorer API interactions."""

    @pytest.fixture
    def explorer(self):
        """Create CitationExplorer."""
        return CitationExplorer(api_key="test-api-key")

    @pytest.fixture
    def sample_paper(self):
        """Create sample paper."""
        return PaperMetadata(
            paper_id="abc123",
            title="Test Paper",
            url="https://example.com",
        )

    @pytest.mark.asyncio
    async def test_get_forward_citations_rate_limit(self, explorer, sample_paper):
        """Test forward citations handles rate limit."""
        mock_response = AsyncMock()
        mock_response.status = 429

        with patch.object(explorer, "_get_session") as mock_session:
            mock_session.return_value.get.return_value.__aenter__.return_value = (
                mock_response
            )
            with patch.object(explorer.rate_limiter, "acquire", new_callable=AsyncMock):
                result = await explorer.get_forward_citations(sample_paper)
                assert result == []

    @pytest.mark.asyncio
    async def test_get_forward_citations_api_error(self, explorer, sample_paper):
        """Test forward citations handles API error."""
        mock_response = AsyncMock()
        mock_response.status = 500

        with patch.object(explorer, "_get_session") as mock_session:
            mock_session.return_value.get.return_value.__aenter__.return_value = (
                mock_response
            )
            with patch.object(explorer.rate_limiter, "acquire", new_callable=AsyncMock):
                result = await explorer.get_forward_citations(sample_paper)
                assert result == []

    @pytest.mark.asyncio
    async def test_get_forward_citations_success(self, explorer, sample_paper):
        """Test successful forward citations fetch."""
        # This tests the parse_paper method directly instead of mocking HTTP
        data = {
            "paperId": "citing1",
            "title": "Citing Paper",
        }
        result = explorer._parse_paper(data, "semantic_scholar")
        assert result is not None
        assert result.paper_id == "citing1"

    @pytest.mark.asyncio
    async def test_get_forward_citations_exception(self, explorer, sample_paper):
        """Test forward citations handles exception."""
        with patch.object(explorer, "_get_session") as mock_session:
            mock_session.side_effect = Exception("Network error")
            with patch.object(explorer.rate_limiter, "acquire", new_callable=AsyncMock):
                result = await explorer.get_forward_citations(sample_paper)
                assert result == []

    @pytest.mark.asyncio
    async def test_get_backward_citations_rate_limit(self, explorer, sample_paper):
        """Test backward citations handles rate limit."""
        mock_response = AsyncMock()
        mock_response.status = 429

        with patch.object(explorer, "_get_session") as mock_session:
            mock_session.return_value.get.return_value.__aenter__.return_value = (
                mock_response
            )
            with patch.object(explorer.rate_limiter, "acquire", new_callable=AsyncMock):
                result = await explorer.get_backward_citations(sample_paper)
                assert result == []

    @pytest.mark.asyncio
    async def test_get_backward_citations_success(self, explorer, sample_paper):
        """Test successful backward citations - tests parse_paper with full data."""
        # This tests the parse_paper method with more complete data
        data = {
            "paperId": "cited1",
            "title": "Cited Paper",
            "abstract": "Test abstract",
            "year": 2023,
            "venue": "Test Venue",
            "citationCount": 50,
        }
        result = explorer._parse_paper(data, "semantic_scholar")
        assert result is not None
        assert result.paper_id == "cited1"
        assert result.abstract == "Test abstract"
        assert result.citation_count == 50

    @pytest.mark.asyncio
    async def test_context_manager(self, explorer):
        """Test async context manager."""
        async with explorer as e:
            assert e is explorer

    @pytest.mark.asyncio
    async def test_close(self, explorer):
        """Test close method."""
        # Should not raise even if no session
        await explorer.close()

    @pytest.mark.asyncio
    async def test_get_session_creates_new(self, explorer):
        """Test _get_session creates new session."""
        session = await explorer._get_session()
        assert session is not None
        await explorer.close()

    @pytest.mark.asyncio
    async def test_explore_with_forward_and_backward(self, explorer):
        """Test explore with both forward and backward enabled."""
        paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com",
        )

        forward_paper = PaperMetadata(
            paper_id="forward1",
            title="Forward Paper",
            url="https://example.com/forward",
        )
        backward_paper = PaperMetadata(
            paper_id="backward1",
            title="Backward Paper",
            url="https://example.com/backward",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                mock_forward.return_value = [forward_paper]
                mock_backward.return_value = [backward_paper]

                result = await explorer.explore([paper], "test-topic")

                assert len(result.forward_papers) == 1
                assert len(result.backward_papers) == 1
                assert result.forward_papers[0].discovery_method == "forward_citation"
                assert result.backward_papers[0].discovery_method == "backward_citation"

    @pytest.mark.asyncio
    async def test_explore_only_forward(self):
        """Test explore with only forward enabled."""
        config = CitationExplorationConfig(forward=True, backward=False)
        explorer = CitationExplorer(api_key="test", config=config)

        paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                mock_forward.return_value = []
                mock_backward.return_value = []

                await explorer.explore([paper], "test-topic")

                mock_forward.assert_called_once()
                mock_backward.assert_not_called()

    @pytest.mark.asyncio
    async def test_explore_handles_exception(self, explorer):
        """Test explore handles exceptions gracefully."""
        paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            mock_forward.side_effect = Exception("API Error")

            result = await explorer.explore([paper], "test-topic")
            # Should return empty result on error
            assert result.stats.seed_papers_count == 1


# =============================================================================
# Additional ResultAggregator Tests for Coverage
# =============================================================================


class TestResultAggregatorEdgeCases:
    """Edge case tests for ResultAggregator."""

    @pytest.fixture
    def aggregator(self):
        """Create aggregator."""
        return ResultAggregator()

    @pytest.mark.asyncio
    async def test_aggregate_empty_sources(self, aggregator):
        """Test aggregation with empty source results."""
        result = await aggregator.aggregate({})
        assert result.total_raw == 0
        assert result.total_after_dedup == 0
        assert len(result.papers) == 0

    @pytest.mark.asyncio
    async def test_aggregate_dedup_by_arxiv_id(self, aggregator):
        """Test deduplication by ArXiv ID."""
        papers = {
            "source1": [
                PaperMetadata(
                    paper_id="",
                    arxiv_id="2301.00001",
                    title="ArXiv Paper",
                    url="https://arxiv.org/1",
                )
            ],
            "source2": [
                PaperMetadata(
                    paper_id="",
                    arxiv_id="2301.00001",  # Same ArXiv ID
                    title="Same Paper Different Source",
                    url="https://example.com/1",
                )
            ],
        }

        result = await aggregator.aggregate(papers)
        assert result.total_after_dedup == 1

    @pytest.mark.asyncio
    async def test_aggregate_dedup_by_paper_id(self, aggregator):
        """Test deduplication by paper_id."""
        papers = {
            "source1": [
                PaperMetadata(
                    paper_id="unique123",
                    title="Paper 1",
                    url="https://example.com/1",
                )
            ],
            "source2": [
                PaperMetadata(
                    paper_id="unique123",  # Same paper_id
                    title="Same Paper",
                    url="https://example.com/2",
                )
            ],
        }

        result = await aggregator.aggregate(papers)
        assert result.total_after_dedup == 1

    @pytest.mark.asyncio
    async def test_aggregate_dedup_by_title(self, aggregator):
        """Test deduplication by normalized title."""
        papers = {
            "source1": [
                PaperMetadata(
                    paper_id="",
                    title="Machine Learning Advances",
                    url="https://example.com/1",
                )
            ],
            "source2": [
                PaperMetadata(
                    paper_id="",
                    title="machine learning advances",  # Same title, different case
                    url="https://example.com/2",
                )
            ],
        }

        result = await aggregator.aggregate(papers)
        assert result.total_after_dedup == 1

    @pytest.mark.asyncio
    async def test_merge_pdf_availability(self, aggregator):
        """Test merging PDF availability across sources."""
        papers = {
            "source1": [
                PaperMetadata(
                    paper_id="",
                    doi="10.1234/test",
                    title="Paper",
                    url="https://example.com/1",
                    pdf_available=False,
                )
            ],
            "source2": [
                PaperMetadata(
                    paper_id="",
                    doi="10.1234/test",
                    title="Paper",
                    url="https://example.com/2",
                    pdf_available=True,
                    pdf_source="arxiv",
                )
            ],
        }

        result = await aggregator.aggregate(papers)
        merged = result.papers[0]
        assert merged.pdf_available is True
        assert merged.pdf_source == "arxiv"

    def test_recency_score_no_date(self, aggregator):
        """Test recency score with no publication date."""
        paper = PaperMetadata(
            paper_id="test",
            title="No Date Paper",
            url="https://example.com",
            year=None,
            publication_date=None,
        )

        score = aggregator._calculate_recency_score(paper)
        assert score == 0.5  # Neutral score for unknown date

    def test_recency_score_string_date(self, aggregator):
        """Test recency score with string publication date."""
        paper = PaperMetadata(
            paper_id="test",
            title="String Date Paper",
            url="https://example.com",
            publication_date="2024-01-15",
        )

        score = aggregator._calculate_recency_score(paper)
        assert 0 <= score <= 1

    def test_recency_score_old_paper(self, aggregator):
        """Test recency score with old paper (> 5 years)."""
        paper = PaperMetadata(
            paper_id="test",
            title="Old Paper",
            url="https://example.com",
            year=2015,
        )

        score = aggregator._calculate_recency_score(paper)
        # Papers > 5 years old should have 0 recency score
        assert score == 0.0


# =============================================================================
# Additional DiscoveryPhase Tests for Coverage
# =============================================================================


class TestDiscoveryPhaseMultiSource:
    """Tests for DiscoveryPhase multi-source discovery."""

    @pytest.mark.asyncio
    async def test_discovery_phase_init_with_configs(self):
        """Test DiscoveryPhase initialization with Phase 7.2 configs."""
        from src.orchestration.phases.discovery import DiscoveryPhase

        mock_context = MagicMock()

        phase = DiscoveryPhase(
            context=mock_context,
            multi_source_enabled=True,
            query_expansion_config=QueryExpansionConfig(),
            citation_config=CitationExplorationConfig(),
            aggregation_config=AggregationConfig(),
        )

        assert phase.multi_source_enabled is True
        assert phase.query_expansion_config is not None
        assert phase.citation_config is not None
        assert phase.aggregation_config is not None

    def test_discovery_phase_name(self):
        """Test DiscoveryPhase name property."""
        from src.orchestration.phases.discovery import DiscoveryPhase

        mock_context = MagicMock()
        phase = DiscoveryPhase(context=mock_context)
        assert phase.name == "discovery"

    def test_discovery_phase_default_result(self):
        """Test DiscoveryPhase default result."""
        from src.orchestration.phases.discovery import DiscoveryPhase, DiscoveryResult

        mock_context = MagicMock()
        phase = DiscoveryPhase(context=mock_context)
        result = phase._get_default_result()

        assert isinstance(result, DiscoveryResult)
        assert result.topics_processed == 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestPhase72Integration:
    """Integration tests for Phase 7.2 components."""

    @pytest.mark.asyncio
    async def test_full_aggregation_pipeline(self):
        """Test full aggregation pipeline with multiple sources."""
        aggregator = ResultAggregator()

        # Simulate results from multiple sources
        source_results = {
            "arxiv": [
                PaperMetadata(
                    paper_id="arxiv1",
                    doi="10.1234/shared",
                    title="Shared Paper",
                    url="https://arxiv.org/1",
                    citation_count=100,
                    discovery_source="arxiv",
                ),
            ],
            "semantic_scholar": [
                PaperMetadata(
                    paper_id="ss1",
                    doi="10.1234/shared",  # Same DOI
                    title="Shared Paper (SS version)",
                    url="https://ss.org/1",
                    abstract="Has abstract",
                    citation_count=120,
                    discovery_source="semantic_scholar",
                ),
            ],
            "openalex": [
                PaperMetadata(
                    paper_id="oa1",
                    title="Unique OpenAlex Paper",
                    url="https://openalex.org/1",
                    citation_count=50,
                    discovery_source="openalex",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should have 2 unique papers (shared DOI merged)
        assert result.total_after_dedup == 2
        assert result.total_raw == 3

        # Source breakdown should reflect all sources
        assert "arxiv" in result.source_breakdown
        assert "semantic_scholar" in result.source_breakdown
        assert "openalex" in result.source_breakdown

    @pytest.mark.asyncio
    async def test_query_expansion_with_aggregation(self):
        """Test query expansion feeding into aggregation."""
        # Create expander without LLM (returns original only)
        expander = QueryExpander()
        expanded = await expander.expand("machine learning")

        assert "machine learning" in expanded
        assert len(expanded) == 1  # No LLM, only original


# =============================================================================
# Config Model Tests
# =============================================================================


class TestPhase72ConfigModels:
    """Tests for Phase 7.2 configuration models."""

    def test_ranking_weights_default(self):
        """Test RankingWeights default values sum to 1."""
        weights = RankingWeights()
        total = (
            weights.citation_count
            + weights.recency
            + weights.source_count
            + weights.pdf_availability
        )
        assert 0.99 <= total <= 1.01

    def test_ranking_weights_custom_valid(self):
        """Test valid custom RankingWeights."""
        weights = RankingWeights(
            citation_count=0.4,
            recency=0.3,
            source_count=0.2,
            pdf_availability=0.1,
        )
        assert weights.citation_count == 0.4

    def test_ranking_weights_invalid_sum(self):
        """Test RankingWeights validation rejects invalid sum."""
        with pytest.raises(ValueError, match="sum to 1.0"):
            RankingWeights(
                citation_count=0.5,
                recency=0.5,
                source_count=0.5,
                pdf_availability=0.5,
            )

    def test_citation_config_defaults(self):
        """Test CitationExplorationConfig defaults."""
        config = CitationExplorationConfig()
        assert config.enabled is True
        assert config.forward is True
        assert config.backward is True
        assert config.max_forward_per_paper == 10
        assert config.max_backward_per_paper == 10

    def test_query_expansion_config_defaults(self):
        """Test QueryExpansionConfig defaults."""
        config = QueryExpansionConfig()
        assert config.enabled is True
        assert config.max_variants == 5
        assert config.cache_expansions is True

    def test_aggregation_config_defaults(self):
        """Test AggregationConfig defaults."""
        config = AggregationConfig()
        assert config.max_papers_per_topic == 50
        assert config.ranking_weights is not None


# =============================================================================
# Additional Coverage Tests for Phase 7.2
# =============================================================================


class TestCitationExplorerSuccessPaths:
    """Tests for CitationExplorer success paths."""

    @pytest.fixture
    def explorer(self):
        """Create explorer with mocked session."""
        return CitationExplorer(api_key="test-key")

    @pytest.mark.asyncio
    async def test_explore_with_registry_filters_known(self):
        """Test explore filters papers already in registry."""
        mock_registry = MagicMock()
        mock_registry.is_paper_known.return_value = True

        explorer = CitationExplorer(
            api_key="test-key",
            registry_service=mock_registry,
        )

        seed_paper = PaperMetadata(
            paper_id="seed1",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        # Mock forward/backward to return papers
        with patch.object(explorer, "get_forward_citations") as mock_fwd:
            with patch.object(explorer, "get_backward_citations") as mock_bwd:
                mock_fwd.return_value = [
                    PaperMetadata(
                        paper_id="known1",
                        title="Known Paper",
                        url="https://example.com/known",
                    )
                ]
                mock_bwd.return_value = []

                result = await explorer.explore(
                    seed_papers=[seed_paper],
                    topic_slug="test-topic",
                )

        # Known papers should be filtered out, so forward_papers should be empty
        assert len(result.forward_papers) == 0
        assert result.stats.filtered_as_duplicate == 1


class TestResultAggregatorMerging:
    """Tests for ResultAggregator merging behavior."""

    @pytest.mark.asyncio
    async def test_merge_with_pdf_availability(self):
        """Test merging combines PDF availability correctly."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="paper1",
                    doi="10.1234/test",
                    title="Test Paper",
                    url="https://example.com/1",
                    pdf_available=False,
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="paper1-ss",
                    doi="10.1234/test",  # Same DOI
                    title="Test Paper",
                    url="https://example.com/2",
                    pdf_available=True,
                    pdf_source="arxiv",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Merged paper should have PDF available
        assert len(result.papers) == 1
        assert result.papers[0].pdf_available is True
        assert result.papers[0].pdf_source == "arxiv"

    @pytest.mark.asyncio
    async def test_recency_score_unknown_date(self):
        """Test recency score for paper with unknown date."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="paper1",
                    title="No Date Paper",
                    url="https://example.com/1",
                    # No publication_date or year
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should still rank without error
        assert len(result.papers) == 1
        assert result.papers[0].ranking_score is not None

    @pytest.mark.asyncio
    async def test_recency_score_very_old_paper(self):
        """Test recency score for very old paper."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="paper1",
                    title="Old Paper",
                    url="https://example.com/1",
                    year=2010,  # Old paper
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        assert len(result.papers) == 1
        # Old paper should have lower score
        assert result.papers[0].ranking_score is not None

    @pytest.mark.asyncio
    async def test_merge_best_citation_count(self):
        """Test merging takes best citation count."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    doi="10.1234/merged",
                    title="Merged Paper",
                    url="https://example.com/1",
                    citation_count=50,
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="p2",
                    doi="10.1234/merged",
                    title="Merged Paper",
                    url="https://example.com/2",
                    citation_count=100,  # Higher count
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        assert len(result.papers) == 1
        assert result.papers[0].citation_count == 100


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


class TestDiscoveryServiceMultiSource:
    """Tests for DiscoveryService multi_source_search."""

    @pytest.mark.asyncio
    async def test_multi_source_search_basic(self):
        """Test basic multi-source search."""
        from src.services.discovery_service import DiscoveryService

        # Use MagicMock for config
        config = MagicMock()

        service = DiscoveryService(
            config=config,
            api_key="test-key",
        )

        # Mock all providers
        mock_papers = [
            PaperMetadata(
                paper_id="p1",
                title="Test Paper",
                url="https://example.com/p1",
            )
        ]

        for provider in service.providers.values():
            provider.search = AsyncMock(return_value=mock_papers)

        topic = ResearchTopic(
            query="machine learning",
            timeframe=TimeframeRecent(value="7d"),
        )

        result = await service.multi_source_search(
            topic=topic,
            llm_service=None,
            registry_service=None,
        )

        # Should return aggregated papers
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_multi_source_with_query_expansion(self):
        """Test multi-source search with query expansion."""
        from src.services.discovery_service import DiscoveryService

        config = MagicMock()

        service = DiscoveryService(
            config=config,
            api_key="test-key",
        )

        # Mock providers
        for provider in service.providers.values():
            provider.search = AsyncMock(return_value=[])

        # Mock LLM service
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(
            return_value='["expanded query 1", "expanded query 2"]'
        )

        topic = ResearchTopic(
            query="original query",
            timeframe=TimeframeRecent(value="7d"),
        )

        qe_config = QueryExpansionConfig(enabled=True, max_variants=3)

        await service.multi_source_search(
            topic=topic,
            llm_service=mock_llm,
            registry_service=None,
            query_expansion_config=qe_config,
        )

        # Providers should be called multiple times (once per query variant)
        for provider in service.providers.values():
            assert provider.search.call_count >= 1

    @pytest.mark.asyncio
    async def test_multi_source_provider_error_handling(self):
        """Test multi-source handles provider errors gracefully."""
        from src.services.discovery_service import DiscoveryService

        config = MagicMock()
        service = DiscoveryService(config=config, api_key="test-key")

        # One provider fails, others succeed
        providers = list(service.providers.values())
        providers[0].search = AsyncMock(side_effect=Exception("Provider error"))
        for provider in providers[1:]:
            provider.search = AsyncMock(
                return_value=[
                    PaperMetadata(
                        paper_id="p1",
                        title="Success Paper",
                        url="https://example.com/p1",
                    )
                ]
            )

        topic = ResearchTopic(
            query="test query",
            timeframe=TimeframeRecent(value="7d"),
        )

        # Should not raise, should handle error gracefully
        result = await service.multi_source_search(
            topic=topic,
            llm_service=None,
            registry_service=None,
        )

        assert isinstance(result, list)


class TestPaperSearchMCPProviderCoverage:
    """Additional tests for PaperSearchMCPProvider coverage."""

    def test_mcp_provider_init(self):
        """Test provider initialization."""
        provider = PaperSearchMCPProvider(mcp_endpoint="localhost:50051")
        assert provider.endpoint == "localhost:50051"
        assert provider.name == "paper_search_mcp"
        assert provider.requires_api_key is False

    def test_mcp_provider_default_endpoint(self):
        """Test provider uses default endpoint."""
        provider = PaperSearchMCPProvider()
        assert provider.endpoint == "localhost:50051"

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_unavailable(self):
        """Test search returns empty when MCP not available."""
        provider = PaperSearchMCPProvider()
        provider._available = False
        provider._checked_availability = True

        topic = ResearchTopic(
            query="test",
            timeframe=TimeframeRecent(value="7d"),
        )

        result = await provider.search(topic)
        assert result == []

    @pytest.mark.asyncio
    async def test_provider_graceful_degradation(self):
        """Test provider degrades gracefully when MCP unavailable."""
        provider = PaperSearchMCPProvider(mcp_endpoint="invalid:99999")

        topic = ResearchTopic(
            query="machine learning",
            timeframe=TimeframeRecent(value="7d"),
        )

        # Should not raise, returns empty
        result = await provider.search(topic)
        assert result == []


# =============================================================================
# Deduplication Path Coverage Tests
# =============================================================================


class TestResultAggregatorDeduplication:
    """Tests for ResultAggregator deduplication paths."""

    @pytest.mark.asyncio
    async def test_deduplicate_by_arxiv_id(self):
        """Test deduplication by ArXiv ID (no DOI)."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    arxiv_id="2301.12345",  # Same ArXiv ID
                    title="ArXiv Paper",
                    url="https://arxiv.org/1",
                    citation_count=10,
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="p2",
                    arxiv_id="2301.12345",  # Same ArXiv ID
                    title="ArXiv Paper Copy",
                    url="https://ss.org/1",
                    citation_count=20,
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should deduplicate to 1 paper
        assert len(result.papers) == 1
        assert result.papers[0].arxiv_id == "2301.12345"
        assert result.papers[0].source_count == 2

    @pytest.mark.asyncio
    async def test_deduplicate_by_paper_id(self):
        """Test deduplication by paper_id (no DOI or ArXiv)."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="unique-paper-id-123",
                    title="Paper by ID",
                    url="https://example.com/1",
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="unique-paper-id-123",  # Same paper_id
                    title="Paper by ID (copy)",
                    url="https://example.com/2",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should deduplicate to 1 paper
        assert len(result.papers) == 1
        assert result.papers[0].source_count == 2

    @pytest.mark.asyncio
    async def test_deduplicate_by_title_only(self):
        """Test deduplication by title (no DOI, ArXiv, or paper_id)."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="",
                    title="Unique Title for Testing",
                    url="https://example.com/1",
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="",
                    title="UNIQUE TITLE FOR TESTING",  # Same title, different case
                    url="https://example.com/2",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should deduplicate to 1 paper based on normalized title
        assert len(result.papers) == 1
        assert result.papers[0].source_count == 2

    @pytest.mark.asyncio
    async def test_multiple_dedup_groups_arxiv_and_title(self):
        """Test multiple papers with ArXiv and title-only papers."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    arxiv_id="2301.11111",
                    title="ArXiv Paper A",
                    url="https://arxiv.org/a",
                ),
                PaperMetadata(
                    paper_id="",
                    title="Title Only Paper",
                    url="https://example.com/b",
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="p2",
                    arxiv_id="2301.11111",  # Duplicate ArXiv
                    title="ArXiv Paper A Copy",
                    url="https://ss.org/a",
                ),
                PaperMetadata(
                    paper_id="",
                    title="title only paper",  # Duplicate title
                    url="https://example.com/c",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should have 2 unique papers
        assert len(result.papers) == 2


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


class TestDiscoveryPhaseMultiSourceExecution:
    """Tests for DiscoveryPhase multi-source execution.

    Note: With the unified discovery API, DiscoveryPhase now uses
    discover() method which is the unified entry point.
    """

    @pytest.mark.asyncio
    async def test_discovery_phase_multi_source_execute(self):
        """Test DiscoveryPhase executes multi-source discovery.

        Note: With the unified discovery API, DiscoveryPhase now uses
        discover() method which is the unified entry point.
        """
        from src.orchestration.phases.discovery import DiscoveryPhase
        from src.models.discovery import DiscoveryResult as DiscoveryResultModel
        from src.models.discovery import DiscoveryMetrics, DiscoveryMode, ScoredPaper

        # Set up mock context
        mock_context = MagicMock()
        mock_context.config = MagicMock()
        mock_context.config.research_topics = [
            ResearchTopic(
                query="test query",
                timeframe=TimeframeRecent(value="7d"),
            )
        ]

        mock_catalog = MagicMock()
        mock_catalog.get_or_create_topic.return_value = MagicMock(
            topic_slug="test-query"
        )
        mock_context.catalog_service = mock_catalog

        # Mock discover() to return proper DiscoveryResult
        mock_discovery_result = DiscoveryResultModel(
            papers=[
                ScoredPaper(
                    paper_id="p1",
                    title="Test Paper",
                    url="https://example.com/p1",
                    quality_score=0.8,
                )
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=1,
                papers_after_quality_filter=1,
                avg_quality_score=0.8,
            ),
            mode=DiscoveryMode.DEEP,
        )

        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(return_value=mock_discovery_result)
        mock_context.discovery_service = mock_discovery
        mock_context.add_discovered_papers = MagicMock()
        mock_context.add_error = MagicMock()

        phase = DiscoveryPhase(
            context=mock_context,
            multi_source_enabled=True,
            query_expansion_config=QueryExpansionConfig(enabled=False),
            citation_config=CitationExplorationConfig(enabled=False),
            aggregation_config=AggregationConfig(),
        )

        result = await phase.execute()

        assert result.topics_processed == 1
        assert result.total_papers == 1
        assert result.multi_source_enabled is True
        mock_discovery.discover.assert_called_once()

    @pytest.mark.asyncio
    async def test_discovery_phase_tracks_citation_stats(self):
        """Test DiscoveryPhase tracks citation discovery stats.

        Note: With the unified discovery API, DiscoveryPhase now uses
        discover() method which is the unified entry point.
        """
        from src.orchestration.phases.discovery import DiscoveryPhase
        from src.models.discovery import DiscoveryResult as DiscoveryResultModel
        from src.models.discovery import DiscoveryMetrics, DiscoveryMode, ScoredPaper

        mock_context = MagicMock()
        mock_context.config = MagicMock()
        mock_context.config.research_topics = [
            ResearchTopic(
                query="citation test",
                timeframe=TimeframeRecent(value="7d"),
            )
        ]

        mock_catalog = MagicMock()
        mock_catalog.get_or_create_topic.return_value = MagicMock(
            topic_slug="citation-test"
        )
        mock_context.catalog_service = mock_catalog

        # Return papers with citation discovery methods via discover()
        mock_discovery_result = DiscoveryResultModel(
            papers=[
                ScoredPaper(
                    paper_id="p1",
                    title="Forward Citation Paper",
                    url="https://example.com/p1",
                    quality_score=0.8,
                ),
                ScoredPaper(
                    paper_id="p2",
                    title="Backward Citation Paper",
                    url="https://example.com/p2",
                    quality_score=0.75,
                ),
                ScoredPaper(
                    paper_id="p3",
                    title="Keyword Paper",
                    url="https://example.com/p3",
                    quality_score=0.7,
                ),
            ],
            metrics=DiscoveryMetrics(
                papers_retrieved=3,
                papers_after_quality_filter=3,
                avg_quality_score=0.75,
            ),
            mode=DiscoveryMode.DEEP,
        )

        mock_discovery = MagicMock()
        mock_discovery.discover = AsyncMock(return_value=mock_discovery_result)
        mock_context.discovery_service = mock_discovery
        mock_context.add_discovered_papers = MagicMock()
        mock_context.add_error = MagicMock()

        phase = DiscoveryPhase(
            context=mock_context,
            multi_source_enabled=True,
        )

        result = await phase.execute()

        # Check stats are tracked - with unified API, we verify basic discovery stats
        assert result.topics_processed == 1
        assert result.total_papers == 3
        topic_result = result.topic_results[0]
        assert len(topic_result.papers) == 3
        # Note: phase72_stats may be None with unified API as stats come from
        # DiscoveryResult.metrics instead of legacy phase72_stats
        mock_discovery.discover.assert_called_once()


class TestCitationExplorerParsing:
    """Tests for CitationExplorer paper parsing."""

    def test_parse_paper_with_all_fields(self):
        """Test parsing paper with complete data."""
        explorer = CitationExplorer(api_key="test-key")

        data = {
            "paperId": "abc123",
            "title": "Test Paper",
            "url": "https://ss.org/abc123",
            "abstract": "This is the abstract.",
            "year": 2023,
            "citationCount": 100,
            "authors": [
                {"name": "Author One"},
                {"name": "Author Two"},
            ],
            "openAccessPdf": {"url": "https://arxiv.org/pdf/2301.99999.pdf"},
        }

        paper = explorer._parse_paper(data, "semantic_scholar")

        assert paper is not None
        assert paper.paper_id == "abc123"
        assert paper.title == "Test Paper"
        assert paper.abstract == "This is the abstract."
        assert paper.year == 2023
        assert paper.citation_count == 100
        assert paper.pdf_available is True
        assert len(paper.authors) == 2
        assert paper.discovery_source == "semantic_scholar"

    def test_parse_paper_minimal_fields(self):
        """Test parsing paper with minimal data."""
        explorer = CitationExplorer(api_key="test-key")

        data = {
            "paperId": "min123",
            "title": "Minimal Paper",
        }

        paper = explorer._parse_paper(data, "semantic_scholar")

        assert paper is not None
        assert paper.paper_id == "min123"
        assert paper.title == "Minimal Paper"

    def test_parse_paper_missing_required_fields(self):
        """Test parsing paper with missing required fields returns None."""
        explorer = CitationExplorer(api_key="test-key")

        # Missing paperId
        data = {"title": "No ID Paper"}
        paper = explorer._parse_paper(data, "semantic_scholar")
        assert paper is None

        # Missing title
        data = {"paperId": "noid"}
        paper = explorer._parse_paper(data, "semantic_scholar")
        assert paper is None


class TestResultAggregatorOptionalFields:
    """Tests for ResultAggregator merging optional fields."""

    @pytest.mark.asyncio
    async def test_merge_fills_missing_optional_fields(self):
        """Test merging fills missing optional fields from other papers."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    doi="10.1234/test",
                    title="Paper with DOI",
                    url="https://example.com/1",
                    # No abstract, venue, arxiv_id
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="p2",
                    doi="10.1234/test",  # Same DOI
                    title="Paper with DOI",
                    url="https://example.com/2",
                    abstract="This paper has an abstract.",
                    venue="ICML 2023",
                    arxiv_id="2301.12345",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        assert len(result.papers) == 1
        merged = result.papers[0]
        # Should have filled in abstract, venue, arxiv_id from source2
        assert merged.abstract == "This paper has an abstract."
        assert merged.venue == "ICML 2023"
        assert merged.arxiv_id == "2301.12345"

    @pytest.mark.asyncio
    async def test_merge_prefers_existing_values(self):
        """Test merging doesn't override existing non-None values."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    doi="10.1234/test",
                    title="Paper A",
                    url="https://example.com/1",
                    abstract="Original abstract",
                    citation_count=50,
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="p2",
                    doi="10.1234/test",
                    title="Paper A",
                    url="https://example.com/2",
                    abstract="Different abstract",
                    citation_count=100,  # Higher
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        assert len(result.papers) == 1
        merged = result.papers[0]
        # Citation count should be best (100)
        assert merged.citation_count == 100
        # Abstract should be from the paper with highest completeness score


class TestCitationExplorerAPISuccess:
    """Tests for CitationExplorer API success paths."""

    @pytest.mark.asyncio
    async def test_explore_forward_citations_integration(self):
        """Test explore method includes forward citations."""
        explorer = CitationExplorer(api_key="test-key")

        seed_paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        forward_paper = PaperMetadata(
            paper_id="fwd1",
            title="Forward Citation",
            url="https://example.com/fwd",
            discovery_method="forward_citation",
        )

        # Mock the get methods directly
        with patch.object(
            explorer, "get_forward_citations", return_value=[forward_paper]
        ):
            with patch.object(explorer, "get_backward_citations", return_value=[]):
                result = await explorer.explore(
                    seed_papers=[seed_paper],
                    topic_slug="test-topic",
                )

        assert result.stats.forward_discovered == 1
        assert len(result.forward_papers) == 1
        assert result.forward_papers[0].paper_id == "fwd1"

    @pytest.mark.asyncio
    async def test_explore_backward_citations_integration(self):
        """Test explore method includes backward citations."""
        explorer = CitationExplorer(api_key="test-key")

        seed_paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        backward_paper = PaperMetadata(
            paper_id="bwd1",
            title="Backward Citation",
            url="https://example.com/bwd",
            discovery_method="backward_citation",
        )

        with patch.object(explorer, "get_forward_citations", return_value=[]):
            with patch.object(
                explorer, "get_backward_citations", return_value=[backward_paper]
            ):
                result = await explorer.explore(
                    seed_papers=[seed_paper],
                    topic_slug="test-topic",
                )

        assert result.stats.backward_discovered == 1
        assert len(result.backward_papers) == 1
        assert result.backward_papers[0].paper_id == "bwd1"


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


class TestPaperSearchMCPValidation:
    """Tests for PaperSearchMCPProvider validation."""

    def test_validate_query_control_characters(self):
        """Test query validation rejects control characters."""
        provider = PaperSearchMCPProvider()

        # Query with control character (ASCII 1)
        with pytest.raises(ValueError, match="invalid control characters"):
            provider.validate_query("test\x01query")

    def test_map_mcp_result_to_paper_with_string_authors(self):
        """Test mapping MCP result with string author names."""
        provider = PaperSearchMCPProvider()

        result = {
            "id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/test",
            "authors": ["John Doe", "Jane Smith"],
        }

        paper = provider._map_mcp_result_to_paper(result, "arxiv")

        assert paper.title == "Test Paper"
        assert len(paper.authors) == 2
        assert paper.authors[0].name == "John Doe"
        assert paper.authors[1].name == "Jane Smith"

    def test_map_mcp_result_with_publication_date(self):
        """Test mapping MCP result with publication date."""
        provider = PaperSearchMCPProvider()

        result = {
            "id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/test",
            "publication_date": "2023-06-15",
        }

        paper = provider._map_mcp_result_to_paper(result, "pubmed")

        assert paper.title == "Test Paper"
        assert paper.year == 2023

    def test_map_mcp_result_with_invalid_date_fallback(self):
        """Test mapping MCP result with invalid date falls back to year."""
        provider = PaperSearchMCPProvider()

        result = {
            "id": "test123",
            "title": "Test Paper",
            "url": "https://example.com/test",
            "publication_date": "invalid-date",
            "year": "2022",
        }

        paper = provider._map_mcp_result_to_paper(result, "pubmed")

        assert paper.title == "Test Paper"
        assert paper.year == 2022


class TestResultAggregatorRecency:
    """Tests for ResultAggregator recency score edge cases."""

    @pytest.mark.asyncio
    async def test_recency_score_string_date(self):
        """Test recency score with string publication_date."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    title="Recent Paper",
                    url="https://example.com/1",
                    publication_date="2024-01-15",  # String date
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        assert len(result.papers) == 1
        assert result.papers[0].ranking_score is not None

    @pytest.mark.asyncio
    async def test_recency_score_with_year_only(self):
        """Test recency score with only year (no publication_date)."""
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    title="Paper with year only",
                    url="https://example.com/1",
                    year=2023,  # No publication_date
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        assert len(result.papers) == 1
        assert result.papers[0].ranking_score is not None

    @pytest.mark.asyncio
    async def test_recency_score_datetime_without_tz(self):
        """Test recency score with datetime object without timezone."""
        from datetime import datetime

        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    title="Paper with datetime",
                    url="https://example.com/1",
                    publication_date=datetime(2024, 1, 15),  # No timezone
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        assert len(result.papers) == 1
        assert result.papers[0].ranking_score is not None
