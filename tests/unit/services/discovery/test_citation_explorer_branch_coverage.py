"""Branch coverage tests for CitationExplorer.

Targets specific uncovered branches:
- Line 122: paper.doi in seen_ids (DOI tracking)
- Line 156: stats.filtered_as_duplicate in backward citations
- Line 380: paper.doi check in _is_new_paper
- Branch 119->121: DOI present in seed papers
- Branch 127->143: config.backward is False (skip backward citations)
- Branch 324->322: Empty authors list handling
- Branch 385->388: Registry match when respect_registry enabled
- Branch 397->399: DOI in _mark_seen
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.models.config import CitationExplorationConfig
from src.models.paper import PaperMetadata
from src.services.citation_explorer import CitationExplorer


class TestCitationExplorerDOITracking:
    """Tests for DOI-based duplicate detection."""

    @pytest.mark.asyncio
    async def test_seed_papers_with_doi_tracked(self):
        """Test that seed papers with DOI are added to seen_ids."""
        explorer = CitationExplorer(api_key="test-key")

        seed_paper = PaperMetadata(
            paper_id="paper123",
            doi="10.1234/test.doi",  # Has DOI
            title="Seed Paper with DOI",
            url="https://example.com/seed",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                # Return a paper with same DOI
                duplicate_by_doi = PaperMetadata(
                    paper_id="different_id",
                    doi="10.1234/test.doi",  # Same DOI
                    title="Duplicate by DOI",
                    url="https://example.com/dup",
                )
                mock_forward.return_value = [duplicate_by_doi]
                mock_backward.return_value = []

                result = await explorer.explore([seed_paper], "test-topic")

                # Should filter duplicate based on DOI (line 122, 380)
                assert result.stats.filtered_as_duplicate == 1
                assert len(result.forward_papers) == 0

    @pytest.mark.asyncio
    async def test_backward_citation_duplicate_by_doi(self):
        """Test backward citations filter duplicates by DOI."""
        explorer = CitationExplorer(api_key="test-key")

        seed_paper = PaperMetadata(
            paper_id="seed123",
            doi="10.5678/seed.doi",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                mock_forward.return_value = []

                # Backward citation with same DOI as seed
                duplicate = PaperMetadata(
                    paper_id="cited999",
                    doi="10.5678/seed.doi",  # Same DOI as seed
                    title="Duplicate Cited Paper",
                    url="https://example.com/cited",
                )
                mock_backward.return_value = [duplicate]

                result = await explorer.explore([seed_paper], "test-topic")

                # Should filter duplicate in backward citations (line 156)
                assert result.stats.filtered_as_duplicate == 1
                assert len(result.backward_papers) == 0


class TestCitationExplorerConfigBranches:
    """Tests for configuration-based branching."""

    @pytest.mark.asyncio
    async def test_backward_disabled_skips_backward_citations(self):
        """Test that backward=False skips backward citation calls."""
        config = CitationExplorationConfig(
            enabled=True,
            forward=True,
            backward=False,  # Disabled
        )
        explorer = CitationExplorer(api_key="test-key", config=config)

        seed_paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                mock_forward.return_value = []
                mock_backward.return_value = []  # Should never be called

                result = await explorer.explore([seed_paper], "test-topic")

                # Forward should be called, backward should not (branch 127->143)
                mock_forward.assert_called_once()
                mock_backward.assert_not_called()
                assert result.stats.backward_discovered == 0

    @pytest.mark.asyncio
    async def test_forward_disabled_skips_forward_citations(self):
        """Test that forward=False skips forward citation calls."""
        config = CitationExplorationConfig(
            enabled=True,
            forward=False,  # Disabled
            backward=True,
        )
        explorer = CitationExplorer(api_key="test-key", config=config)

        seed_paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                mock_forward.return_value = []  # Should never be called
                mock_backward.return_value = []

                result = await explorer.explore([seed_paper], "test-topic")

                # Backward should be called, forward should not
                mock_forward.assert_not_called()
                mock_backward.assert_called_once()
                assert result.stats.forward_discovered == 0


class TestCitationExplorerAuthorParsing:
    """Tests for author parsing edge cases."""

    def test_parse_paper_with_empty_authors_list(self):
        """Test parsing paper with empty authors list."""
        explorer = CitationExplorer(api_key="test-key")

        data = {
            "paperId": "test123",
            "title": "Test Paper",
            "authors": [],  # Empty authors list (branch 324->322)
        }

        paper = explorer._parse_paper(data, "semantic_scholar")

        assert paper is not None
        assert paper.paper_id == "test123"
        assert len(paper.authors) == 0

    def test_parse_paper_with_null_authors(self):
        """Test parsing paper with null authors field."""
        explorer = CitationExplorer(api_key="test-key")

        data = {
            "paperId": "test123",
            "title": "Test Paper",
            "authors": None,  # None authors (branch 324->322)
        }

        paper = explorer._parse_paper(data, "semantic_scholar")

        assert paper is not None
        assert len(paper.authors) == 0

    def test_parse_paper_authors_without_name(self):
        """Test parsing paper with authors missing name field."""
        explorer = CitationExplorer(api_key="test-key")

        data = {
            "paperId": "test123",
            "title": "Test Paper",
            "authors": [
                {"name": "Valid Author"},
                {"authorId": "a2"},  # No name - should skip
                {"name": "Another Valid"},
            ],
        }

        paper = explorer._parse_paper(data, "semantic_scholar")

        assert paper is not None
        assert len(paper.authors) == 2  # Only authors with names
        assert paper.authors[0].name == "Valid Author"
        assert paper.authors[1].name == "Another Valid"


class TestCitationExplorerRegistryIntegration:
    """Tests for registry-based deduplication."""

    @pytest.mark.asyncio
    async def test_registry_filters_known_papers(self):
        """Test that respect_registry=True filters papers in registry."""
        mock_registry = MagicMock()

        # Mock resolve_identity to return matched=True
        match_result = MagicMock()
        match_result.matched = True
        mock_registry.resolve_identity.return_value = match_result

        config = CitationExplorationConfig(
            enabled=True,
            respect_registry=True,
        )
        explorer = CitationExplorer(
            api_key="test-key",
            registry_service=mock_registry,
            config=config,
        )

        seed_paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                # Return papers that registry knows about
                known_paper = PaperMetadata(
                    paper_id="known123",
                    title="Known Paper",
                    url="https://example.com/known",
                )
                mock_forward.return_value = [known_paper]
                mock_backward.return_value = []

                result = await explorer.explore([seed_paper], "test-topic")

                # Should filter based on registry (branch 385->388)
                assert result.stats.filtered_as_duplicate == 1
                assert len(result.forward_papers) == 0

    @pytest.mark.asyncio
    async def test_registry_allows_unknown_papers(self):
        """Test that papers not in registry are added."""
        mock_registry = MagicMock()

        # Mock resolve_identity to return matched=False
        match_result = MagicMock()
        match_result.matched = False
        mock_registry.resolve_identity.return_value = match_result

        config = CitationExplorationConfig(
            enabled=True,
            respect_registry=True,
        )
        explorer = CitationExplorer(
            api_key="test-key",
            registry_service=mock_registry,
            config=config,
        )

        seed_paper = PaperMetadata(
            paper_id="seed123",
            title="Seed Paper",
            url="https://example.com/seed",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                unknown_paper = PaperMetadata(
                    paper_id="unknown123",
                    title="Unknown Paper",
                    url="https://example.com/unknown",
                )
                mock_forward.return_value = [unknown_paper]
                mock_backward.return_value = []

                result = await explorer.explore([seed_paper], "test-topic")

                # Should add unknown paper
                assert len(result.forward_papers) == 1
                assert result.forward_papers[0].paper_id == "unknown123"


class TestCitationExplorerMarkSeen:
    """Tests for _mark_seen DOI handling."""

    def test_mark_seen_adds_doi_to_set(self):
        """Test that _mark_seen adds DOI to seen_ids."""
        explorer = CitationExplorer(api_key="test-key")

        seen_ids = set()
        paper = PaperMetadata(
            paper_id="paper123",
            doi="10.9999/test.doi",  # Has DOI
            title="Test Paper",
            url="https://example.com/test",
        )

        explorer._mark_seen(paper, seen_ids)

        # Should add both paper_id and DOI (line 397->399)
        assert "paper123" in seen_ids
        assert "10.9999/test.doi" in seen_ids
        assert len(seen_ids) == 2

    def test_mark_seen_without_doi(self):
        """Test _mark_seen with paper that has no DOI."""
        explorer = CitationExplorer(api_key="test-key")

        seen_ids = set()
        paper = PaperMetadata(
            paper_id="paper123",
            doi=None,  # No DOI
            title="Test Paper",
            url="https://example.com/test",
        )

        explorer._mark_seen(paper, seen_ids)

        # Should only add paper_id, not DOI
        assert "paper123" in seen_ids
        assert len(seen_ids) == 1

    def test_mark_seen_with_empty_doi(self):
        """Test _mark_seen with paper that has empty DOI string."""
        explorer = CitationExplorer(api_key="test-key")

        seen_ids = set()
        paper = PaperMetadata(
            paper_id="paper123",
            doi="",  # Empty DOI
            title="Test Paper",
            url="https://example.com/test",
        )

        explorer._mark_seen(paper, seen_ids)

        # Should only add paper_id (empty DOI is falsy)
        assert "paper123" in seen_ids
        assert len(seen_ids) == 1


class TestCitationExplorerIsNewPaper:
    """Tests for _is_new_paper DOI checking."""

    def test_is_new_paper_checks_doi_in_seen(self):
        """Test _is_new_paper checks DOI against seen_ids."""
        explorer = CitationExplorer(api_key="test-key")

        seen_ids = {"10.1234/existing.doi"}
        paper = PaperMetadata(
            paper_id="new_paper_id",
            doi="10.1234/existing.doi",  # DOI already seen (line 380)
            title="Test Paper",
            url="https://example.com/test",
        )

        is_new = explorer._is_new_paper(paper, seen_ids, "test-topic")

        # Should return False because DOI is in seen_ids
        assert is_new is False

    def test_is_new_paper_with_no_doi(self):
        """Test _is_new_paper with paper missing DOI."""
        explorer = CitationExplorer(api_key="test-key")

        seen_ids = {"existing_paper_id"}
        paper = PaperMetadata(
            paper_id="new_paper_id",
            doi=None,  # No DOI
            title="Test Paper",
            url="https://example.com/test",
        )

        is_new = explorer._is_new_paper(paper, seen_ids, "test-topic")

        # Should return True (new paper_id, no DOI to check)
        assert is_new is True


class TestCitationExplorerMultipleSeedPapers:
    """Tests for handling multiple seed papers with DOIs."""

    @pytest.mark.asyncio
    async def test_multiple_seed_papers_all_tracked(self):
        """Test that all seed papers (with DOIs) are tracked in seen_ids."""
        explorer = CitationExplorer(api_key="test-key")

        seed1 = PaperMetadata(
            paper_id="seed1",
            doi="10.1111/seed1",
            title="Seed Paper 1",
            url="https://example.com/seed1",
        )
        seed2 = PaperMetadata(
            paper_id="seed2",
            doi="10.2222/seed2",
            title="Seed Paper 2",
            url="https://example.com/seed2",
        )

        with patch.object(
            explorer, "get_forward_citations", new_callable=AsyncMock
        ) as mock_forward:
            with patch.object(
                explorer, "get_backward_citations", new_callable=AsyncMock
            ) as mock_backward:
                # Return paper with DOI matching seed2
                dup_paper = PaperMetadata(
                    paper_id="different_id",
                    doi="10.2222/seed2",  # Matches seed2 DOI
                    title="Duplicate",
                    url="https://example.com/dup",
                )
                mock_forward.return_value = [dup_paper]
                mock_backward.return_value = []

                result = await explorer.explore([seed1, seed2], "test-topic")

                # Both calls should see 1 duplicate filtered
                assert result.stats.filtered_as_duplicate >= 1
                assert result.stats.seed_papers_count == 2
