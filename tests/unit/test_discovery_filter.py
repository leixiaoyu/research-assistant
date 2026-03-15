"""Unit tests for DiscoveryFilter service (Phase 7.1)."""

import pytest
from unittest.mock import patch

from src.services.discovery_filter import DiscoveryFilter
from src.services.registry_service import RegistryService
from src.models.paper import PaperMetadata, Author
from src.models.discovery import DiscoveryFilterResult


@pytest.fixture
def temp_registry_path(tmp_path):
    """Temporary registry path for testing."""
    return tmp_path / "test_registry.json"


@pytest.fixture
def registry_service(temp_registry_path):
    """Registry service with temporary storage."""
    return RegistryService(registry_path=temp_registry_path)


@pytest.fixture
def discovery_filter(registry_service):
    """DiscoveryFilter instance for testing."""
    return DiscoveryFilter(registry_service=registry_service)


@pytest.fixture
def sample_paper():
    """Sample paper metadata."""
    return PaperMetadata(
        paper_id="2301.12345",
        title="Sample Research Paper",
        abstract="This is a test abstract",
        url="https://arxiv.org/abs/2301.12345",
        doi="10.1234/test.2023.001",
        arxiv_id="2301.12345",
        authors=[Author(name="John Doe")],
        year=2023,
        citation_count=10,
    )


@pytest.fixture
def sample_paper_no_doi():
    """Sample paper without DOI."""
    return PaperMetadata(
        paper_id="2301.54321",
        title="Another Research Paper",
        abstract="Test abstract without DOI",
        url="https://arxiv.org/abs/2301.54321",
        arxiv_id="2301.54321",
        authors=[Author(name="Jane Smith")],
        year=2023,
        citation_count=5,
    )


class TestDiscoveryFilterInitialization:
    """Test DiscoveryFilter initialization."""

    def test_initialization_default(self, registry_service):
        """Test default initialization."""
        filter_service = DiscoveryFilter(registry_service=registry_service)
        assert filter_service.registry == registry_service
        assert filter_service.skip_filter is False

    def test_initialization_skip_filter(self, registry_service):
        """Test initialization with skip_filter enabled."""
        filter_service = DiscoveryFilter(
            registry_service=registry_service,
            skip_filter=True,
        )
        assert filter_service.skip_filter is True


class TestFilterPapersBasic:
    """Test basic filtering operations."""

    @pytest.mark.asyncio
    async def test_filter_papers_empty_list(self, discovery_filter):
        """Test filtering empty paper list."""
        result = await discovery_filter.filter_papers(
            papers=[],
            topic_slug="test-topic",
            register_new=False,
        )

        assert isinstance(result, DiscoveryFilterResult)
        assert len(result.new_papers) == 0
        assert len(result.filtered_papers) == 0
        assert result.stats.total_discovered == 0
        assert result.stats.new_count == 0
        assert result.stats.filtered_count == 0

    @pytest.mark.asyncio
    async def test_filter_papers_all_new(self, discovery_filter, sample_paper):
        """Test filtering when all papers are new."""
        papers = [sample_paper]

        result = await discovery_filter.filter_papers(
            papers=papers,
            topic_slug="test-topic",
            register_new=False,
        )

        assert len(result.new_papers) == 1
        assert len(result.filtered_papers) == 0
        assert result.stats.total_discovered == 1
        assert result.stats.new_count == 1
        assert result.stats.filtered_count == 0
        assert result.new_papers[0].paper_id == sample_paper.paper_id

    @pytest.mark.asyncio
    async def test_filter_papers_skip_filter_enabled(
        self, registry_service, sample_paper
    ):
        """Test that skip_filter bypasses all filtering."""
        filter_service = DiscoveryFilter(
            registry_service=registry_service,
            skip_filter=True,
        )

        # Pre-register the paper
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Filter with skip_filter enabled
        result = await filter_service.filter_papers(
            papers=[sample_paper],
            topic_slug="test-topic",
            register_new=False,
        )

        # Should return all papers as new even though registered
        assert len(result.new_papers) == 1
        assert len(result.filtered_papers) == 0
        assert result.stats.new_count == 1
        assert result.stats.filtered_count == 0

    @pytest.mark.asyncio
    async def test_filter_papers_skip_filter_with_registration(
        self, registry_service, sample_paper
    ):
        """Test skip_filter with register_new enabled."""
        filter_service = DiscoveryFilter(
            registry_service=registry_service,
            skip_filter=True,
        )

        # Filter with skip_filter enabled and registration
        result = await filter_service.filter_papers(
            papers=[sample_paper],
            topic_slug="test-topic",
            register_new=True,
        )

        # Should return all papers as new
        assert len(result.new_papers) == 1
        assert result.stats.new_count == 1
        assert result.stats.incremental_query is False


class TestDuplicateDetection:
    """Test duplicate detection logic."""

    @pytest.mark.asyncio
    async def test_filter_duplicate_by_doi(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test filtering duplicate by DOI match."""
        # Register paper first
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Create duplicate with same DOI
        duplicate = PaperMetadata(
            paper_id="different-id",
            title="Different Title",
            abstract="Different abstract",
            url="https://example.com/different",
            doi=sample_paper.doi,  # Same DOI
            authors=[Author(name="Different Author")],
            year=2023,
            citation_count=0,
        )

        result = await discovery_filter.filter_papers(
            papers=[duplicate],
            topic_slug="test-topic",
            register_new=False,
        )

        assert len(result.new_papers) == 0
        assert len(result.filtered_papers) == 1
        assert result.filtered_papers[0].filter_reason == "doi"
        assert result.stats.filter_breakdown["doi"] == 1

    @pytest.mark.asyncio
    async def test_filter_duplicate_by_arxiv(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test filtering duplicate by ArXiv ID match."""
        # Register paper first
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Create duplicate with same ArXiv ID but no DOI
        duplicate = PaperMetadata(
            paper_id=sample_paper.arxiv_id,  # Same ArXiv ID
            title="Different Title",
            abstract="Different abstract",
            url="https://example.com/different",
            arxiv_id=sample_paper.arxiv_id,
            authors=[Author(name="Different Author")],
            year=2023,
            citation_count=0,
        )

        # Clear DOI to test ArXiv matching
        duplicate.doi = None

        result = await discovery_filter.filter_papers(
            papers=[duplicate],
            topic_slug="test-topic",
            register_new=False,
        )

        assert len(result.new_papers) == 0
        assert len(result.filtered_papers) == 1
        assert result.filtered_papers[0].filter_reason == "arxiv"
        assert result.stats.filter_breakdown["arxiv"] == 1

    @pytest.mark.asyncio
    async def test_filter_duplicate_by_title(
        self, discovery_filter, registry_service, sample_paper_no_doi
    ):
        """Test filtering duplicate by title similarity (≥95%)."""
        # Register paper first
        registry_service.register_paper(
            paper=sample_paper_no_doi,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Create duplicate with very similar title, no DOI/ArXiv
        duplicate = PaperMetadata(
            paper_id="different-id-123",
            title=sample_paper_no_doi.title,  # Same title
            abstract="Different abstract",
            url="https://example.com/different",
            authors=[Author(name="Different Author")],
            year=2023,
            citation_count=0,
        )

        result = await discovery_filter.filter_papers(
            papers=[duplicate],
            topic_slug="test-topic",
            register_new=False,
        )

        assert len(result.new_papers) == 0
        assert len(result.filtered_papers) == 1
        assert result.filtered_papers[0].filter_reason == "title"
        assert result.stats.filter_breakdown["title"] == 1


class TestPaperRegistration:
    """Test paper registration at discovery time."""

    @pytest.mark.asyncio
    async def test_register_new_papers_enabled(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test that new papers are registered when register_new=True."""
        result = await discovery_filter.filter_papers(
            papers=[sample_paper],
            topic_slug="test-topic",
            register_new=True,
        )

        # Paper should be new
        assert len(result.new_papers) == 1

        # Check registry contains the paper
        # (use resolve_identity since paper_id is a UUID)
        match = registry_service.resolve_identity(sample_paper)
        assert match.matched is True
        assert match.entry is not None
        assert "test-topic" in match.entry.topic_affiliations

    @pytest.mark.asyncio
    async def test_register_new_papers_disabled(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test that papers are not registered when register_new=False."""
        result = await discovery_filter.filter_papers(
            papers=[sample_paper],
            topic_slug="test-topic",
            register_new=False,
        )

        # Paper should be new
        assert len(result.new_papers) == 1

        # Registry should be empty
        entry = registry_service.get_entry(sample_paper.paper_id)
        assert entry is None

    @pytest.mark.asyncio
    async def test_registration_failure_handling(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test graceful handling of registration failures."""
        # Mock registry.register_paper to raise exception
        with patch.object(
            registry_service,
            "register_paper",
            side_effect=Exception("Registration failed"),
        ):
            # Should not raise, just log warning
            result = await discovery_filter.filter_papers(
                papers=[sample_paper],
                topic_slug="test-topic",
                register_new=True,
            )

            # Paper should still be in new_papers
            assert len(result.new_papers) == 1


class TestMixedPapers:
    """Test filtering mixed sets of papers."""

    @pytest.mark.asyncio
    async def test_filter_mixed_new_and_duplicate(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test filtering mix of new and duplicate papers."""
        # Register one paper
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Create new paper
        new_paper = PaperMetadata(
            paper_id="9999.88888",
            title="Brand New Paper",
            abstract="Completely new content",
            url="https://example.com/new",
            doi="10.9999/new.2023",
            authors=[Author(name="New Author")],
            year=2023,
            citation_count=0,
        )

        result = await discovery_filter.filter_papers(
            papers=[sample_paper, new_paper],
            topic_slug="test-topic",
            register_new=False,
        )

        assert len(result.new_papers) == 1
        assert len(result.filtered_papers) == 1
        assert result.new_papers[0].paper_id == new_paper.paper_id
        assert result.filtered_papers[0].paper.paper_id == sample_paper.paper_id

    @pytest.mark.asyncio
    async def test_filter_multiple_duplicates_different_reasons(
        self, discovery_filter, registry_service
    ):
        """Test filtering with multiple duplicate detection methods."""
        # Paper 1: Has DOI
        paper1 = PaperMetadata(
            paper_id="2301.11111",
            title="Paper One",
            abstract="Abstract one",
            url="https://example.com/1",
            doi="10.1111/one",
            authors=[Author(name="Author One")],
            year=2023,
            citation_count=10,
        )

        # Paper 2: Has ArXiv ID
        paper2 = PaperMetadata(
            paper_id="2301.22222",
            title="Paper Two",
            abstract="Abstract two",
            url="https://example.com/2",
            arxiv_id="2301.22222",
            authors=[Author(name="Author Two")],
            year=2023,
            citation_count=5,
        )

        # Register both
        registry_service.register_paper(
            paper=paper1, topic_slug="topic1", discovery_only=True
        )
        registry_service.register_paper(
            paper=paper2, topic_slug="topic2", discovery_only=True
        )

        # Create duplicates
        dup1 = PaperMetadata(
            paper_id="different-1",
            title="Different Title 1",
            abstract="Different",
            url="https://example.com/dup1",
            doi=paper1.doi,  # Same DOI
            authors=[Author(name="Dup Author")],
            year=2023,
            citation_count=0,
        )

        dup2 = PaperMetadata(
            paper_id=paper2.arxiv_id,  # Same ArXiv
            title="Different Title 2",
            abstract="Different",
            url="https://example.com/dup2",
            arxiv_id=paper2.arxiv_id,
            authors=[Author(name="Dup Author")],
            year=2023,
            citation_count=0,
        )

        result = await discovery_filter.filter_papers(
            papers=[dup1, dup2],
            topic_slug="test-topic",
            register_new=False,
        )

        assert len(result.new_papers) == 0
        assert len(result.filtered_papers) == 2
        assert result.stats.filter_breakdown["doi"] == 1
        assert result.stats.filter_breakdown["arxiv"] == 1


class TestStatistics:
    """Test statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_all_new(self, discovery_filter, sample_paper):
        """Test statistics when all papers are new."""
        result = await discovery_filter.filter_papers(
            papers=[sample_paper],
            topic_slug="test-topic",
            register_new=False,
        )

        assert result.stats.total_discovered == 1
        assert result.stats.new_count == 1
        assert result.stats.filtered_count == 0
        assert sum(result.stats.filter_breakdown.values()) == 0

    @pytest.mark.asyncio
    async def test_stats_all_filtered(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test statistics when all papers are filtered."""
        # Register paper
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        result = await discovery_filter.filter_papers(
            papers=[sample_paper],
            topic_slug="test-topic",
            register_new=False,
        )

        assert result.stats.total_discovered == 1
        assert result.stats.new_count == 0
        assert result.stats.filtered_count == 1
        assert sum(result.stats.filter_breakdown.values()) == 1

    @pytest.mark.asyncio
    async def test_filter_breakdown_accuracy(self, discovery_filter, registry_service):
        """Test that filter breakdown accurately tracks filter reasons."""
        papers = []

        # Create 3 papers with DOI (use valid DOI format)
        for i in range(3):
            paper = PaperMetadata(
                paper_id=f"doi-paper-{i}",
                title=f"DOI Paper {i}",
                abstract=f"Abstract {i}",
                url=f"https://example.com/doi/{i}",
                doi=f"10.1234/test.{i}",  # Valid DOI format
                authors=[Author(name=f"Author {i}")],
                year=2023,
                citation_count=i,
            )
            registry_service.register_paper(
                paper=paper, topic_slug="existing", discovery_only=True
            )
            papers.append(paper)

        # Create 2 papers with ArXiv
        for i in range(2):
            paper = PaperMetadata(
                paper_id=f"2301.{i}0000",
                title=f"ArXiv Paper {i}",
                abstract=f"Abstract {i}",
                url=f"https://arxiv.org/abs/2301.{i}0000",
                arxiv_id=f"2301.{i}0000",
                authors=[Author(name=f"Author {i}")],
                year=2023,
                citation_count=i,
            )
            registry_service.register_paper(
                paper=paper, topic_slug="existing", discovery_only=True
            )
            papers.append(paper)

        result = await discovery_filter.filter_papers(
            papers=papers,
            topic_slug="test-topic",
            register_new=False,
        )

        assert result.stats.filtered_count == 5
        assert result.stats.filter_breakdown["doi"] == 3
        assert result.stats.filter_breakdown["arxiv"] == 2


class TestCheckDuplicate:
    """Test _check_duplicate helper method."""

    def test_check_duplicate_new_paper(self, discovery_filter, sample_paper):
        """Test _check_duplicate returns None for new paper."""
        result = discovery_filter._check_duplicate(sample_paper)
        assert result is None

    def test_check_duplicate_by_doi(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test _check_duplicate detects DOI duplicates."""
        # Register paper
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Check duplicate
        result = discovery_filter._check_duplicate(sample_paper)
        assert result == "doi"

    def test_check_duplicate_by_arxiv(
        self, discovery_filter, registry_service, sample_paper_no_doi
    ):
        """Test _check_duplicate detects ArXiv duplicates."""
        # Register paper
        registry_service.register_paper(
            paper=sample_paper_no_doi,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Check duplicate
        result = discovery_filter._check_duplicate(sample_paper_no_doi)
        assert result == "arxiv"

    def test_check_duplicate_by_title(
        self, discovery_filter, registry_service, sample_paper_no_doi
    ):
        """Test _check_duplicate detects title duplicates."""
        # Register paper
        registry_service.register_paper(
            paper=sample_paper_no_doi,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Create paper with same title, no DOI/ArXiv
        duplicate = PaperMetadata(
            paper_id="different-id",
            title=sample_paper_no_doi.title,
            abstract="Different abstract",
            url="https://example.com/different",
            authors=[Author(name="Different Author")],
            year=2023,
            citation_count=0,
        )

        result = discovery_filter._check_duplicate(duplicate)
        assert result == "title"

    def test_check_duplicate_by_provider_id(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test _check_duplicate detects provider ID duplicates."""
        # Register paper
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Mock resolve_identity to return semantic_scholar match
        from src.models.registry import IdentityMatch

        with patch.object(
            registry_service,
            "resolve_identity",
            return_value=IdentityMatch(
                matched=True,
                entry=registry_service.resolve_identity(sample_paper).entry,
                match_method="semantic_scholar",
            ),
        ):
            result = discovery_filter._check_duplicate(sample_paper)
            assert result == "provider_id"

    def test_check_duplicate_unknown_match_method(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test _check_duplicate handles unknown match methods."""
        # Register paper
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Mock resolve_identity to return unknown match method
        from src.models.registry import IdentityMatch

        with patch.object(
            registry_service,
            "resolve_identity",
            return_value=IdentityMatch(
                matched=True,
                entry=registry_service.resolve_identity(sample_paper).entry,
                match_method="unknown_method",
            ),
        ):
            result = discovery_filter._check_duplicate(sample_paper)
            # Should default to provider_id for unknown methods
            assert result == "provider_id"

    @pytest.mark.asyncio
    async def test_filter_breakdown_with_unexpected_reason(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test filter breakdown handles unexpected filter reasons."""
        # Register paper
        registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        # Mock _check_duplicate to return unexpected reason
        with patch.object(
            discovery_filter,
            "_check_duplicate",
            return_value="unexpected_reason",
        ):
            result = await discovery_filter.filter_papers(
                papers=[sample_paper],
                topic_slug="test-topic",
                register_new=False,
            )

            # Paper should be filtered
            assert len(result.filtered_papers) == 1
            # Unexpected reason should not be in breakdown
            # (since it's not in the initialized keys)
            assert "unexpected_reason" not in result.stats.filter_breakdown


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_filter_papers_with_none_topic_slug(
        self, discovery_filter, sample_paper
    ):
        """Test handling of None topic_slug."""
        # Should work with empty string
        result = await discovery_filter.filter_papers(
            papers=[sample_paper],
            topic_slug="",
            register_new=False,
        )
        assert len(result.new_papers) == 1

    @pytest.mark.asyncio
    async def test_filter_papers_large_batch(self, discovery_filter, registry_service):
        """Test filtering large batch of papers."""
        # Create 100 papers
        papers = []
        for i in range(100):
            paper = PaperMetadata(
                paper_id=f"paper-{i:04d}",
                title=f"Paper {i}",
                abstract=f"Abstract for paper {i}",
                url=f"https://example.com/{i}",
                doi=f"10.1234/paper.{i}",
                authors=[Author(name=f"Author {i}")],
                year=2023,
                citation_count=i,
            )
            papers.append(paper)

        # Register first 50
        for paper in papers[:50]:
            registry_service.register_paper(
                paper=paper,
                topic_slug="existing-topic",
                discovery_only=True,
            )

        result = await discovery_filter.filter_papers(
            papers=papers,
            topic_slug="test-topic",
            register_new=False,
        )

        assert result.stats.total_discovered == 100
        assert result.stats.new_count == 50
        assert result.stats.filtered_count == 50

    @pytest.mark.asyncio
    async def test_filtered_paper_contains_matched_entry_id(
        self, discovery_filter, registry_service, sample_paper
    ):
        """Test that FilteredPaper contains the matched entry ID."""
        # Register paper
        entry = registry_service.register_paper(
            paper=sample_paper,
            topic_slug="existing-topic",
            discovery_only=True,
        )

        result = await discovery_filter.filter_papers(
            papers=[sample_paper],
            topic_slug="test-topic",
            register_new=False,
        )

        assert len(result.filtered_papers) == 1
        filtered = result.filtered_papers[0]
        assert filtered.matched_entry_id == entry.paper_id
        assert filtered.paper.paper_id == sample_paper.paper_id
