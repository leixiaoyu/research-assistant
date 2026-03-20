"""Tests for PaperSearchMCPProvider.

Split from test_phase_7_2_components.py for better organization.
Tests cover MCP-based paper search provider with validation and mapping.
"""

import pytest

from src.models.config import ResearchTopic, TimeframeRecent
from src.models.paper import PaperMetadata
from src.services.providers.paper_search_mcp import PaperSearchMCPProvider


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
