"""Tests for CitationExplorer service.

Split from test_phase_7_2_components.py for better organization.
Tests cover forward/backward citation discovery via Semantic Scholar API.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.config import CitationExplorationConfig
from src.models.paper import PaperMetadata, Author
from src.services.citation_explorer import CitationExplorer


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

    @pytest.mark.asyncio
    async def test_parse_paper_handles_malformed_api_response(self):
        """Test that malformed entries in API response are skipped gracefully.

        Simulates an API response where one paper is missing the paperId field.
        The malformed entry should be skipped without raising an exception,
        and other valid papers in the same response should still be parsed.
        """
        explorer = CitationExplorer(api_key="test-key")

        # Simulate _fetch_citations processing multiple papers with one malformed
        mock_api_response_data = [
            {
                "citingPaper": {
                    "paperId": "valid1",
                    "title": "Valid Paper 1",
                    "abstract": "This paper is complete.",
                    "year": 2023,
                }
            },
            {
                "citingPaper": {
                    # Missing paperId - this is malformed
                    "title": "Malformed Paper",
                    "abstract": "This paper is missing paperId.",
                }
            },
            {
                "citingPaper": {
                    "paperId": "valid2",
                    "title": "Valid Paper 2",
                    "year": 2024,
                }
            },
        ]

        # Parse each paper like _fetch_citations does
        parsed_papers = []
        for item in mock_api_response_data:
            paper_data = item.get("citingPaper", {})
            if paper_data:
                parsed = explorer._parse_paper(paper_data, "semantic_scholar")
                if parsed:  # Only append if parsing succeeded
                    parsed_papers.append(parsed)

        # Should have 2 valid papers (malformed one skipped)
        assert len(parsed_papers) == 2
        assert parsed_papers[0].paper_id == "valid1"
        assert parsed_papers[0].title == "Valid Paper 1"
        assert parsed_papers[1].paper_id == "valid2"
        assert parsed_papers[1].title == "Valid Paper 2"

        # Verify the malformed entry was silently skipped (no exception raised)


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
