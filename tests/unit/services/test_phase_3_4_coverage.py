"""Coverage tests for Phase 3.4 - targeting missed lines.

This test file specifically targets edge cases and error paths
that were identified as coverage gaps in the review:
- QualityScorer YAML error handling (lines 56-61)
- SemanticScholarProvider PDF_REQUIRED strategy (lines 124-126)
- DiscoveryService ArXiv supplement edge cases (lines 256, 306-307)
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.services.quality_scorer import load_venue_scores
from src.services.discovery_service import DiscoveryService
from src.services.providers.semantic_scholar import SemanticScholarProvider
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    PDFStrategy,
    ProviderType,
)
from src.models.paper import PaperMetadata


class TestQualityScorerYAMLErrorHandling:
    """Tests for YAML error handling in load_venue_scores."""

    def test_yaml_parse_error_returns_defaults(self, tmp_path):
        """Test that YAMLError returns default values."""
        # Create a malformed YAML file
        malformed_yaml = tmp_path / "malformed.yaml"
        malformed_yaml.write_text("venues:\n  invalid: [unclosed bracket")

        venues, default = load_venue_scores(malformed_yaml)

        # Should return empty dict and default score 15
        assert venues == {}
        assert default == 15

    def test_value_error_non_integer_score_returns_defaults(self, tmp_path):
        """Test that ValueError from non-integer scores returns defaults."""
        # Create YAML with non-integer venue score
        invalid_yaml = tmp_path / "invalid_scores.yaml"
        invalid_yaml.write_text(
            """
venues:
  NeurIPS: "not_a_number"
default_score: 15
"""
        )

        venues, default = load_venue_scores(invalid_yaml)

        # Should return empty dict and default score 15
        assert venues == {}
        assert default == 15

    def test_value_error_non_integer_default_returns_defaults(self, tmp_path):
        """Test that ValueError from non-integer default_score returns defaults."""
        # Create YAML with non-integer default_score
        invalid_yaml = tmp_path / "invalid_default.yaml"
        invalid_yaml.write_text(
            """
venues:
  NeurIPS: 30
default_score: "fifteen"
"""
        )

        venues, default = load_venue_scores(invalid_yaml)

        # Should return empty dict and default score 15
        assert venues == {}
        assert default == 15

    def test_type_error_list_as_score_returns_defaults(self, tmp_path):
        """Test that TypeError from score value being a list returns defaults."""
        # Create YAML with venue score as a list (not an int)
        # This causes TypeError when int() is called on a list
        invalid_yaml = tmp_path / "list_score.yaml"
        invalid_yaml.write_text(
            """
venues:
  NeurIPS: [30, 25]
default_score: 15
"""
        )

        # int([30, 25]) raises TypeError
        venues, default = load_venue_scores(invalid_yaml)

        # The code handles this with the TypeError catch
        assert venues == {}
        assert default == 15

    def test_yaml_scanner_error_returns_defaults(self, tmp_path):
        """Test that YAML scanner error returns defaults."""
        # Create YAML with tabs (YAML scanner error)
        invalid_yaml = tmp_path / "scanner_error.yaml"
        invalid_yaml.write_text("venues:\n\t- invalid tabs")

        venues, default = load_venue_scores(invalid_yaml)

        assert venues == {}
        assert default == 15


class TestSemanticScholarPDFRequiredStrategy:
    """Tests for PDF_REQUIRED strategy in SemanticScholarProvider."""

    @pytest.fixture
    def provider(self):
        """Create provider with mock API key."""
        return SemanticScholarProvider(api_key="test-key")

    @pytest.fixture
    def topic_pdf_required(self):
        """Create topic with PDF_REQUIRED strategy."""
        return ResearchTopic(
            query="machine learning",
            timeframe=TimeframeRecent(value="7d"),
            pdf_strategy=PDFStrategy.PDF_REQUIRED,
        )

    @pytest.fixture
    def mock_mixed_papers_response(self):
        """Mock API response with mixed PDF availability."""
        return {
            "data": [
                {
                    "paperId": "paper1",
                    "title": "Paper With PDF",
                    "abstract": "Has open access PDF",
                    "url": "https://example.com/1",
                    "openAccessPdf": {"url": "https://example.com/1.pdf"},
                    "citationCount": 100,
                    "venue": "NeurIPS",
                },
                {
                    "paperId": "paper2",
                    "title": "Paper Without PDF",
                    "abstract": "No open access PDF",
                    "url": "https://example.com/2",
                    "openAccessPdf": None,
                    "citationCount": 50,
                    "venue": "ICML",
                },
                {
                    "paperId": "paper3",
                    "title": "Another Paper With PDF",
                    "abstract": "Has PDF",
                    "url": "https://example.com/3",
                    "openAccessPdf": {"url": "https://example.com/3.pdf"},
                    "citationCount": 75,
                    "venue": "ACL",
                },
                {
                    "paperId": "paper4",
                    "title": "No PDF Paper 2",
                    "abstract": "Also no PDF",
                    "url": "https://example.com/4",
                    "openAccessPdf": None,
                    "citationCount": 25,
                    "venue": "Workshop",
                },
                {
                    "paperId": "paper5",
                    "title": "Third Paper With PDF",
                    "abstract": "Has PDF too",
                    "url": "https://example.com/5",
                    "openAccessPdf": {"url": "https://example.com/5.pdf"},
                    "citationCount": 200,
                    "venue": "Nature",
                },
            ]
        }

    @pytest.mark.asyncio
    async def test_pdf_required_filters_papers_without_pdf(
        self, provider, topic_pdf_required, mock_mixed_papers_response
    ):
        """Test that PDF_REQUIRED strategy filters out papers without PDFs."""
        with patch("aiohttp.ClientSession.get") as mock_get:
            # Create mock response
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_mixed_papers_response)

            # Set up context manager
            mock_get.return_value.__aenter__.return_value = mock_response

            papers = await provider.search(topic_pdf_required)

            # Should only return papers with PDFs (3 out of 5)
            assert len(papers) == 3
            assert all(p.pdf_available for p in papers)
            assert all(p.open_access_pdf is not None for p in papers)

            # Verify the correct papers were kept
            titles = [p.title for p in papers]
            assert "Paper With PDF" in titles
            assert "Another Paper With PDF" in titles
            assert "Third Paper With PDF" in titles
            assert "Paper Without PDF" not in titles
            assert "No PDF Paper 2" not in titles


class TestDiscoveryServiceArxivSupplementEdgeCases:
    """Tests for ArXiv supplement edge cases in DiscoveryService."""

    @pytest.fixture
    def service_without_arxiv(self):
        """Create service without ArXiv provider."""
        service = DiscoveryService(api_key="test-key")
        # Remove ArXiv provider to test edge case
        del service.providers[ProviderType.ARXIV]
        return service

    @pytest.fixture
    def service_arxiv_only(self):
        """Create service with only ArXiv provider."""
        return DiscoveryService(api_key="")

    @pytest.fixture
    def topic_arxiv_supplement(self):
        """Create topic with ARXIV_SUPPLEMENT strategy."""
        return ResearchTopic(
            query="deep learning",
            timeframe=TimeframeRecent(value="7d"),
            pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
            arxiv_supplement_threshold=0.5,
        )

    @pytest.mark.asyncio
    async def test_arxiv_supplement_no_primary_results_no_arxiv_provider(
        self, service_without_arxiv, topic_arxiv_supplement
    ):
        """Test ArXiv supplement returns empty list when no ArXiv provider."""
        # Mock Semantic Scholar to return empty
        service_without_arxiv.providers[ProviderType.SEMANTIC_SCHOLAR].search = (
            AsyncMock(return_value=[])
        )

        result = await service_without_arxiv._apply_arxiv_supplement(
            topic_arxiv_supplement, []
        )

        # Should return empty list since no ArXiv provider
        assert result == []

    @pytest.mark.asyncio
    async def test_arxiv_supplement_no_primary_results_with_arxiv(
        self, service_arxiv_only, topic_arxiv_supplement
    ):
        """Test ArXiv supplement queries ArXiv when no primary results."""
        arxiv_papers = [
            PaperMetadata(
                paper_id="arxiv1",
                title="ArXiv Paper 1",
                url="https://arxiv.org/abs/1",
                pdf_available=True,
            ),
        ]

        service_arxiv_only.providers[ProviderType.ARXIV].search = AsyncMock(
            return_value=arxiv_papers
        )

        result = await service_arxiv_only._apply_arxiv_supplement(
            topic_arxiv_supplement, []
        )

        # Should return ArXiv papers
        assert len(result) == 1
        assert result[0].title == "ArXiv Paper 1"

    @pytest.mark.asyncio
    async def test_arxiv_supplement_dedup_by_title_when_no_unique_id(self):
        """Test title-based deduplication when papers lack unique IDs."""
        service = DiscoveryService(api_key="")

        topic = ResearchTopic(
            query="test",
            timeframe=TimeframeRecent(value="7d"),
            pdf_strategy=PDFStrategy.ARXIV_SUPPLEMENT,
            arxiv_supplement_threshold=0.8,  # High threshold to trigger supplement
        )

        # Primary papers without DOI
        primary_papers = [
            PaperMetadata(
                paper_id="",  # No paper_id
                title="Duplicate Title Paper",
                url="https://example.com/1",
                pdf_available=False,  # Low PDF rate to trigger supplement
            ),
        ]

        # ArXiv papers with same title but no unique ID
        arxiv_papers = [
            PaperMetadata(
                paper_id="",  # No paper_id
                title="Duplicate Title Paper",  # Same title - should be skipped
                url="https://arxiv.org/abs/1",
                pdf_available=True,
            ),
            PaperMetadata(
                paper_id="",  # No paper_id
                title="Unique ArXiv Paper",  # Different title - should be added
                url="https://arxiv.org/abs/2",
                pdf_available=True,
            ),
        ]

        service.providers[ProviderType.ARXIV].search = AsyncMock(
            return_value=arxiv_papers
        )

        result = await service._apply_arxiv_supplement(topic, primary_papers)

        # Should have original + only the unique ArXiv paper
        assert len(result) == 2
        titles = [p.title for p in result]
        assert "Duplicate Title Paper" in titles
        assert "Unique ArXiv Paper" in titles


class TestDiscoveryServiceUnifiedDeduplication:
    """Tests for the unified _is_duplicate helper method."""

    @pytest.fixture
    def service(self):
        """Create service instance."""
        return DiscoveryService(api_key="")

    def test_is_duplicate_by_doi(self, service):
        """Test deduplication by DOI."""
        existing = [
            PaperMetadata(
                paper_id="p1",
                title="Paper 1",
                url="https://example.com/1",
                doi="10.1234/test",
            )
        ]
        seen_ids = {"10.1234/test"}

        paper = PaperMetadata(
            paper_id="p2",
            title="Different Title",
            url="https://example.com/2",
            doi="10.1234/test",  # Same DOI
        )

        assert service._is_duplicate(paper, existing, seen_ids) is True

    def test_is_duplicate_by_paper_id(self, service):
        """Test deduplication by paper_id when no DOI."""
        existing = [
            PaperMetadata(
                paper_id="unique_id_123",
                title="Paper 1",
                url="https://example.com/1",
            )
        ]
        seen_ids = {"unique_id_123"}

        paper = PaperMetadata(
            paper_id="unique_id_123",  # Same paper_id
            title="Different Title",
            url="https://example.com/2",
        )

        assert service._is_duplicate(paper, existing, seen_ids) is True

    def test_is_duplicate_by_title_when_no_ids(self, service):
        """Test deduplication by title when no unique IDs."""
        existing = [
            PaperMetadata(
                paper_id="",
                title="Machine Learning Survey",
                url="https://example.com/1",
            )
        ]
        seen_ids: set = set()

        paper = PaperMetadata(
            paper_id="",
            title="machine learning survey",  # Same title (case-insensitive)
            url="https://example.com/2",
        )

        assert service._is_duplicate(paper, existing, seen_ids) is True

    def test_is_not_duplicate_different_everything(self, service):
        """Test non-duplicate paper with different IDs and title."""
        existing = [
            PaperMetadata(
                paper_id="p1",
                title="Paper 1",
                url="https://example.com/1",
                doi="10.1234/original",
            )
        ]
        seen_ids = {"10.1234/original", "p1"}

        paper = PaperMetadata(
            paper_id="p2",
            title="Completely Different Paper",
            url="https://example.com/2",
            doi="10.5678/different",
        )

        assert service._is_duplicate(paper, existing, seen_ids) is False

    def test_is_duplicate_title_with_whitespace(self, service):
        """Test title matching ignores leading/trailing whitespace."""
        existing = [
            PaperMetadata(
                paper_id="",
                title="  Paper Title  ",
                url="https://example.com/1",
            )
        ]
        seen_ids: set = set()

        paper = PaperMetadata(
            paper_id="",
            title="Paper Title",  # Same without whitespace
            url="https://example.com/2",
        )

        assert service._is_duplicate(paper, existing, seen_ids) is True


class TestDiscoveryServiceBenchmarkDeduplication:
    """Tests for benchmark search deduplication using unified logic."""

    @pytest.mark.asyncio
    async def test_benchmark_deduplicates_by_title(self):
        """Test benchmark search deduplicates papers without unique IDs by title."""
        service = DiscoveryService(api_key="test-key")

        # Mock both providers to return papers with same title but no unique IDs
        semantic_papers = [
            PaperMetadata(
                paper_id="",
                title="Shared Paper Title",
                url="https://semanticscholar.org/1",
            )
        ]
        arxiv_papers = [
            PaperMetadata(
                paper_id="",
                title="Shared Paper Title",  # Same title - should be deduplicated
                url="https://arxiv.org/abs/1",
            ),
            PaperMetadata(
                paper_id="",
                title="Unique ArXiv Paper",
                url="https://arxiv.org/abs/2",
            ),
        ]

        service.providers[ProviderType.SEMANTIC_SCHOLAR].search = AsyncMock(
            return_value=semantic_papers
        )
        service.providers[ProviderType.ARXIV].search = AsyncMock(
            return_value=arxiv_papers
        )

        topic = ResearchTopic(
            query="test",
            timeframe=TimeframeRecent(value="7d"),
            benchmark=True,
        )

        result = await service._benchmark_search(topic)

        # Should have 2 papers (deduplicated by title)
        assert len(result) == 2
        titles = [p.title for p in result]
        assert "Shared Paper Title" in titles
        assert "Unique ArXiv Paper" in titles


class TestDiscoveryServiceLogQualityStatsEdgeCase:
    """Tests for _log_quality_stats edge cases."""

    def test_log_quality_stats_empty_papers(self):
        """Test _log_quality_stats handles empty papers list."""
        service = DiscoveryService(api_key="")

        # Should not raise any errors
        service._log_quality_stats([])
