"""Tests for ResultAggregator service.

Split from test_phase_7_2_components.py for better organization.
Tests cover multi-source deduplication and ranking.
"""

import pytest
from datetime import datetime, timezone

from src.models.config import AggregationConfig, RankingWeights
from src.models.paper import PaperMetadata, Author
from src.services.result_aggregator import ResultAggregator


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


class TestResultAggregatorTitleSimilarity:
    """Tests for ResultAggregator title similarity handling."""

    @pytest.mark.asyncio
    async def test_similar_titles_exact_match_after_normalization(self):
        """Test that very similar titles are deduplicated after normalization.

        The current implementation uses exact normalized title matching.
        This test verifies that titles differing only in punctuation,
        case, and whitespace are correctly identified as duplicates.
        """
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    title="Machine Learning: A Comprehensive Study!!!",
                    url="https://example.com/1",
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="p2",
                    title="machine   learning  a  comprehensive  study",
                    url="https://example.com/2",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should deduplicate to 1 paper (exact match after normalization)
        assert len(result.papers) == 1
        assert result.papers[0].source_count == 2

    @pytest.mark.asyncio
    async def test_similar_titles_no_fuzzy_matching(self):
        """Test that similar but not identical titles are NOT deduplicated.

        The current implementation does NOT use fuzzy title similarity matching.
        Titles that differ in actual words (e.g., "Study" vs "Survey") are treated
        as unique papers, even if they're very similar.

        Note: Future enhancement could add fuzzy matching with configurable threshold.
        """
        aggregator = ResultAggregator()

        source_results = {
            "source1": [
                PaperMetadata(
                    paper_id="p1",
                    title="Machine Learning: A Comprehensive Study",
                    url="https://example.com/1",
                ),
            ],
            "source2": [
                PaperMetadata(
                    paper_id="p2",
                    title="Machine Learning: A Comprehensive Survey",  # "Survey" vs "Study"
                    url="https://example.com/2",
                ),
            ],
        }

        result = await aggregator.aggregate(source_results)

        # Should NOT deduplicate (different words after normalization)
        assert len(result.papers) == 2
        # Each paper should have source_count=1 (not merged)
        assert all(p.source_count == 1 for p in result.papers)
