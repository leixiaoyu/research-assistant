"""Tests for test factories.

Verifies that all factory methods create valid model instances.
"""

from tests.factories import (
    PaperFactory,
    AuthorFactory,
    ScoredPaperFactory,
    TopicFactory,
    TimeframeFactory,
    ExtractionTargetFactory,
    ExtractionResultFactory,
    FilterConfigFactory,
    DedupConfigFactory,
)


class TestAuthorFactory:
    """Tests for AuthorFactory."""

    def test_create_default(self):
        """Test creating author with defaults."""
        author = AuthorFactory.create()
        assert author.name.startswith("Author ")
        assert author.author_id is None

    def test_create_with_name(self):
        """Test creating author with custom name."""
        author = AuthorFactory.create(name="John Doe")
        assert author.name == "John Doe"

    def test_create_with_affiliation(self):
        """Test creating author with affiliation."""
        author = AuthorFactory.with_affiliation("Stanford")
        assert author.affiliation == "Stanford"

    def test_create_batch(self):
        """Test creating multiple authors."""
        authors = AuthorFactory.create_batch(3)
        assert len(authors) == 3
        assert all(a.name.startswith("Author ") for a in authors)


class TestPaperFactory:
    """Tests for PaperFactory."""

    def test_create_default(self):
        """Test creating paper with defaults."""
        paper = PaperFactory.create()
        assert paper.paper_id.startswith("paper-")
        assert paper.title.startswith("Test Paper ")
        assert "example.com" in str(paper.url)
        assert paper.year == 2024
        assert paper.authors == []

    def test_create_with_custom_fields(self):
        """Test creating paper with custom fields."""
        paper = PaperFactory.create(
            title="Custom Title",
            year=2023,
            citation_count=50,
        )
        assert paper.title == "Custom Title"
        assert paper.year == 2023
        assert paper.citation_count == 50

    def test_create_batch(self):
        """Test creating multiple papers."""
        papers = PaperFactory.create_batch(5)
        assert len(papers) == 5
        # Each should have unique ID
        ids = [p.paper_id for p in papers]
        assert len(set(ids)) == 5

    def test_minimal(self):
        """Test creating minimal paper."""
        paper = PaperFactory.minimal()
        assert paper.paper_id.startswith("minimal-")
        assert paper.title.startswith("Minimal Paper ")

    def test_with_doi(self):
        """Test creating paper with DOI."""
        paper = PaperFactory.with_doi()
        assert paper.doi is not None
        assert paper.doi.startswith("10.1234/")

    def test_with_doi_custom(self):
        """Test creating paper with custom DOI."""
        paper = PaperFactory.with_doi(doi="10.5678/custom")
        assert paper.doi == "10.5678/custom"

    def test_with_arxiv(self):
        """Test creating paper with ArXiv ID."""
        paper = PaperFactory.with_arxiv()
        assert paper.arxiv_id is not None
        assert paper.discovery_source == "arxiv"

    def test_with_citations(self):
        """Test creating paper with citations."""
        paper = PaperFactory.with_citations(count=500)
        assert paper.citation_count == 500

    def test_with_pdf(self):
        """Test creating paper with PDF."""
        paper = PaperFactory.with_pdf()
        assert paper.pdf_available is True
        assert paper.open_access_pdf is not None

    def test_highly_cited(self):
        """Test creating highly-cited paper."""
        paper = PaperFactory.highly_cited()
        assert paper.citation_count >= 1000

    def test_from_source(self):
        """Test creating paper from specific source."""
        paper = PaperFactory.from_source("semantic_scholar", "citation")
        assert paper.discovery_source == "semantic_scholar"
        assert paper.discovery_method == "citation"


class TestScoredPaperFactory:
    """Tests for ScoredPaperFactory."""

    def test_create_default(self):
        """Test creating scored paper with defaults."""
        paper = ScoredPaperFactory.create()
        assert paper.paper_id.startswith("scored-")
        assert paper.quality_score == 0.8
        assert paper.relevance_score == 0.7

    def test_high_quality(self):
        """Test creating high-quality paper."""
        paper = ScoredPaperFactory.high_quality()
        assert paper.quality_score > 0.9

    def test_low_quality(self):
        """Test creating low-quality paper."""
        paper = ScoredPaperFactory.low_quality()
        assert paper.quality_score < 0.3


class TestTimeframeFactory:
    """Tests for TimeframeFactory."""

    def test_recent(self):
        """Test creating recent timeframe."""
        tf = TimeframeFactory.recent("7d")
        assert tf.value == "7d"

    def test_since_year(self):
        """Test creating since-year timeframe."""
        tf = TimeframeFactory.since_year(2022)
        assert tf.value == 2022

    def test_date_range(self):
        """Test creating date range timeframe."""
        from datetime import date

        tf = TimeframeFactory.date_range(
            start=date(2023, 1, 1),
            end=date(2023, 12, 31),
        )
        assert tf.start_date == date(2023, 1, 1)
        assert tf.end_date == date(2023, 12, 31)

    def test_convenience_methods(self):
        """Test convenience timeframe methods."""
        assert TimeframeFactory.last_24h().value == "24h"
        assert TimeframeFactory.last_week().value == "7d"
        assert TimeframeFactory.last_month().value == "30d"


class TestTopicFactory:
    """Tests for TopicFactory."""

    def test_create_default(self):
        """Test creating topic with defaults."""
        topic = TopicFactory.create()
        assert "machine learning" in topic.query
        assert topic.max_papers == 50
        assert topic.timeframe is not None

    def test_create_with_custom_query(self):
        """Test creating topic with custom query."""
        topic = TopicFactory.create(query="deep learning transformers")
        assert topic.query == "deep learning transformers"

    def test_arxiv(self):
        """Test creating ArXiv topic."""
        from src.models.config import ProviderType

        topic = TopicFactory.arxiv()
        assert topic.provider == ProviderType.ARXIV

    def test_semantic_scholar(self):
        """Test creating Semantic Scholar topic."""
        from src.models.config import ProviderType

        topic = TopicFactory.semantic_scholar()
        assert topic.provider == ProviderType.SEMANTIC_SCHOLAR

    def test_recent_papers(self):
        """Test creating recent papers topic."""
        topic = TopicFactory.recent_papers(hours=24)
        assert topic.timeframe.value == "24h"

    def test_since_year(self):
        """Test creating since-year topic."""
        topic = TopicFactory.since_year(year=2021)
        assert topic.timeframe.value == 2021

    def test_large_batch(self):
        """Test creating large batch topic."""
        topic = TopicFactory.large_batch()
        assert topic.max_papers == 100


class TestExtractionFactories:
    """Tests for extraction factories."""

    def test_target_create(self):
        """Test creating extraction target."""
        target = ExtractionTargetFactory.create()
        assert target.name == "system_prompts"
        assert target.required is True

    def test_target_system_prompts(self):
        """Test system prompts target."""
        target = ExtractionTargetFactory.system_prompts()
        assert target.name == "system_prompts"

    def test_target_code_snippets(self):
        """Test code snippets target."""
        target = ExtractionTargetFactory.code_snippets()
        assert target.name == "code_snippets"

    def test_target_optional(self):
        """Test optional target."""
        target = ExtractionTargetFactory.optional()
        assert target.required is False

    def test_result_success(self):
        """Test successful extraction result."""
        result = ExtractionResultFactory.success()
        assert result.success is True
        assert result.confidence > 0.9
        assert result.content is not None

    def test_result_failure(self):
        """Test failed extraction result."""
        result = ExtractionResultFactory.failure(error="Test error")
        assert result.success is False
        assert result.error == "Test error"
        assert result.confidence == 0.0

    def test_result_with_code(self):
        """Test result with code content."""
        result = ExtractionResultFactory.with_code()
        assert result.target_name == "code_snippets"
        assert len(result.content) > 0


class TestConfigFactories:
    """Tests for config factories."""

    def test_filter_config_default(self):
        """Test default filter config."""
        config = FilterConfigFactory.create()
        assert config.min_citation_count == 0
        assert config.min_relevance_score == 0.0

    def test_filter_config_strict(self):
        """Test strict filter config."""
        config = FilterConfigFactory.strict()
        assert config.min_citation_count >= 10
        assert config.min_year == 2020
        assert config.min_relevance_score == 0.5

    def test_filter_config_relaxed(self):
        """Test relaxed filter config."""
        config = FilterConfigFactory.relaxed()
        assert config.min_citation_count == 0
        assert config.min_relevance_score == 0.0

    def test_filter_config_citation_focused(self):
        """Test citation-focused filter config."""
        config = FilterConfigFactory.citation_focused()
        assert config.citation_weight == 0.60

    def test_dedup_config_default(self):
        """Test default dedup config."""
        config = DedupConfigFactory.create()
        assert config.enabled is True
        assert config.use_doi_matching is True

    def test_dedup_config_disabled(self):
        """Test disabled dedup config."""
        config = DedupConfigFactory.disabled()
        assert config.enabled is False

    def test_dedup_config_doi_only(self):
        """Test DOI-only dedup config."""
        config = DedupConfigFactory.doi_only()
        assert config.use_doi_matching is True
        assert config.use_title_matching is False

    def test_dedup_config_strict(self):
        """Test strict dedup config."""
        config = DedupConfigFactory.strict()
        assert config.title_similarity_threshold == 0.95
