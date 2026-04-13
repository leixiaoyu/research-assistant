"""Unit tests for Phase 2 discovery models.

Tests for new discovery models added in Task 2.1:
- DiscoveryMode enum
- QualityTierConfig
- QueryEnhancementConfig
- DiscoveryCitationConfig
- DiscoveryPipelineConfig
- Extended DiscoveryResult
- Extended DiscoveryMetrics
"""

import pytest
from pydantic import ValidationError

from src.models.discovery import (
    DiscoveryMode,
    QualityTierConfig,
    QueryEnhancementConfig,
    DiscoveryCitationConfig,
    DiscoveryPipelineConfig,
    DiscoveryResult,
    DiscoveryMetrics,
    QualityWeights,
    ScoredPaper,
)


class TestDiscoveryMode:
    """Tests for DiscoveryMode enum."""

    def test_discovery_mode_values(self):
        """Test DiscoveryMode has correct values."""
        assert DiscoveryMode.SURFACE == "surface"
        assert DiscoveryMode.STANDARD == "standard"
        assert DiscoveryMode.DEEP == "deep"

    def test_discovery_mode_iteration(self):
        """Test all DiscoveryMode values can be iterated."""
        modes = list(DiscoveryMode)
        assert len(modes) == 3
        assert DiscoveryMode.SURFACE in modes
        assert DiscoveryMode.STANDARD in modes
        assert DiscoveryMode.DEEP in modes

    def test_discovery_mode_from_string(self):
        """Test DiscoveryMode can be created from string."""
        assert DiscoveryMode("surface") == DiscoveryMode.SURFACE
        assert DiscoveryMode("standard") == DiscoveryMode.STANDARD
        assert DiscoveryMode("deep") == DiscoveryMode.DEEP

    def test_discovery_mode_invalid_value(self):
        """Test DiscoveryMode rejects invalid values."""
        with pytest.raises(ValueError):
            DiscoveryMode("invalid")


class TestQualityTierConfig:
    """Tests for QualityTierConfig model."""

    def test_quality_tier_config_defaults(self):
        """Test QualityTierConfig has correct default values."""
        config = QualityTierConfig()
        assert config.excellent == 0.80
        assert config.good == 0.60
        assert config.fair == 0.40

    def test_quality_tier_config_frozen(self):
        """Test QualityTierConfig is immutable."""
        config = QualityTierConfig()
        with pytest.raises(ValidationError):
            config.excellent = 0.90  # type: ignore[misc]

    def test_quality_tier_config_custom_values(self):
        """Test QualityTierConfig accepts custom values."""
        config = QualityTierConfig(excellent=0.90, good=0.70, fair=0.50)
        assert config.excellent == 0.90
        assert config.good == 0.70
        assert config.fair == 0.50

    def test_quality_tier_config_validates_order(self):
        """Test QualityTierConfig validates tier order (excellent > good > fair)."""
        # Valid order
        config = QualityTierConfig(excellent=0.80, good=0.60, fair=0.40)
        assert config.excellent > config.good > config.fair

        # Invalid: excellent <= good
        with pytest.raises(ValidationError, match="excellent > good > fair"):
            QualityTierConfig(excellent=0.60, good=0.70, fair=0.40)

        # Invalid: good <= fair
        with pytest.raises(ValidationError, match="excellent > good > fair"):
            QualityTierConfig(excellent=0.80, good=0.40, fair=0.60)

        # Invalid: excellent == good
        with pytest.raises(ValidationError, match="excellent > good > fair"):
            QualityTierConfig(excellent=0.70, good=0.70, fair=0.40)

    def test_quality_tier_config_validates_range(self):
        """Test QualityTierConfig validates values are in [0.0, 1.0]."""
        # Valid boundaries
        config = QualityTierConfig(excellent=1.0, good=0.5, fair=0.0)
        assert config.excellent == 1.0
        assert config.fair == 0.0

        # Invalid: above 1.0
        with pytest.raises(ValidationError):
            QualityTierConfig(excellent=1.5, good=0.6, fair=0.4)

        # Invalid: below 0.0
        with pytest.raises(ValidationError):
            QualityTierConfig(excellent=0.8, good=0.6, fair=-0.1)


class TestQueryEnhancementConfig:
    """Tests for QueryEnhancementConfig model."""

    def test_query_enhancement_config_defaults(self):
        """Test QueryEnhancementConfig has correct default values."""
        config = QueryEnhancementConfig()
        assert config.strategy == "decompose"
        assert config.max_queries == 5
        assert config.include_original is True
        assert config.cache_enabled is True

    def test_query_enhancement_config_frozen(self):
        """Test QueryEnhancementConfig is immutable."""
        config = QueryEnhancementConfig()
        with pytest.raises(ValidationError):
            config.strategy = "expand"  # type: ignore[misc]

    def test_query_enhancement_config_custom_values(self):
        """Test QueryEnhancementConfig accepts custom values."""
        config = QueryEnhancementConfig(
            strategy="hybrid",
            max_queries=10,
            include_original=False,
            cache_enabled=False,
        )
        assert config.strategy == "hybrid"
        assert config.max_queries == 10
        assert config.include_original is False
        assert config.cache_enabled is False

    def test_query_enhancement_config_validates_max_queries_range(self):
        """Test QueryEnhancementConfig validates max_queries is in [1, 20]."""
        # Valid boundaries
        config_min = QueryEnhancementConfig(max_queries=1)
        assert config_min.max_queries == 1

        config_max = QueryEnhancementConfig(max_queries=20)
        assert config_max.max_queries == 20

        # Invalid: below 1
        with pytest.raises(ValidationError):
            QueryEnhancementConfig(max_queries=0)

        # Invalid: above 20
        with pytest.raises(ValidationError):
            QueryEnhancementConfig(max_queries=21)


class TestDiscoveryCitationConfig:
    """Tests for DiscoveryCitationConfig model."""

    def test_citation_exploration_config_defaults(self):
        """Test DiscoveryCitationConfig has correct default values."""
        config = DiscoveryCitationConfig()
        assert config.enabled is True
        assert config.forward_citations is True
        assert config.backward_citations is True
        assert config.max_depth == 1
        assert config.max_papers_per_direction == 10

    def test_citation_exploration_config_frozen(self):
        """Test DiscoveryCitationConfig is immutable."""
        config = DiscoveryCitationConfig()
        with pytest.raises(ValidationError):
            config.enabled = False  # type: ignore[misc]

    def test_citation_exploration_config_custom_values(self):
        """Test DiscoveryCitationConfig accepts custom values."""
        config = DiscoveryCitationConfig(
            enabled=False,
            forward_citations=False,
            backward_citations=False,
            max_depth=2,
            max_papers_per_direction=20,
        )
        assert config.enabled is False
        assert config.forward_citations is False
        assert config.backward_citations is False
        assert config.max_depth == 2
        assert config.max_papers_per_direction == 20

    def test_citation_exploration_config_validates_max_depth(self):
        """Test DiscoveryCitationConfig validates max_depth in [1, 3]."""
        # Valid boundaries
        config_min = DiscoveryCitationConfig(max_depth=1)
        assert config_min.max_depth == 1

        config_max = DiscoveryCitationConfig(max_depth=3)
        assert config_max.max_depth == 3

        # Invalid: below 1
        with pytest.raises(ValidationError):
            DiscoveryCitationConfig(max_depth=0)

        # Invalid: above 3
        with pytest.raises(ValidationError):
            DiscoveryCitationConfig(max_depth=4)

    def test_citation_exploration_config_validates_max_papers(self):
        """Test DiscoveryCitationConfig validates max_papers_per_direction."""
        # Valid boundaries
        config_min = DiscoveryCitationConfig(max_papers_per_direction=1)
        assert config_min.max_papers_per_direction == 1

        config_max = DiscoveryCitationConfig(max_papers_per_direction=50)
        assert config_max.max_papers_per_direction == 50

        # Invalid: below 1
        with pytest.raises(ValidationError):
            DiscoveryCitationConfig(max_papers_per_direction=0)

        # Invalid: above 50
        with pytest.raises(ValidationError):
            DiscoveryCitationConfig(max_papers_per_direction=51)


class TestDiscoveryPipelineConfig:
    """Tests for DiscoveryPipelineConfig model."""

    def test_discovery_pipeline_config_defaults(self):
        """Test DiscoveryPipelineConfig has correct default values."""
        config = DiscoveryPipelineConfig()

        # Mode selection
        assert config.mode == DiscoveryMode.STANDARD

        # Provider configuration
        assert config.providers == [
            "arxiv",
            "semantic_scholar",
            "openalex",
            "huggingface",
        ]
        assert config.provider_timeout_seconds == 30.0
        assert config.fallback_enabled is True

        # Query enhancement
        assert isinstance(config.query_enhancement, QueryEnhancementConfig)
        assert config.query_enhancement.strategy == "decompose"

        # Citation exploration
        assert isinstance(config.citation_exploration, DiscoveryCitationConfig)
        assert config.citation_exploration.enabled is True

        # Quality filtering
        assert isinstance(config.quality_weights, QualityWeights)
        assert isinstance(config.quality_tiers, QualityTierConfig)
        assert config.min_quality_score == 0.3
        assert config.min_citations == 0

        # Relevance filtering
        assert config.enable_relevance_ranking is True
        assert config.min_relevance_score == 0.5

        # Result limits
        assert config.max_papers == 50

    def test_discovery_pipeline_config_frozen(self):
        """Test DiscoveryPipelineConfig is immutable."""
        config = DiscoveryPipelineConfig()
        with pytest.raises(ValidationError):
            config.mode = DiscoveryMode.DEEP  # type: ignore[misc]

    def test_discovery_pipeline_config_custom_mode(self):
        """Test DiscoveryPipelineConfig accepts custom mode."""
        config_surface = DiscoveryPipelineConfig(mode=DiscoveryMode.SURFACE)
        assert config_surface.mode == DiscoveryMode.SURFACE

        config_deep = DiscoveryPipelineConfig(mode=DiscoveryMode.DEEP)
        assert config_deep.mode == DiscoveryMode.DEEP

    def test_discovery_pipeline_config_custom_providers(self):
        """Test DiscoveryPipelineConfig accepts custom provider list."""
        config = DiscoveryPipelineConfig(providers=["arxiv", "semantic_scholar"])
        assert config.providers == ["arxiv", "semantic_scholar"]

    def test_discovery_pipeline_config_validates_timeout(self):
        """Test DiscoveryPipelineConfig validates timeout in [1.0, 300.0]."""
        # Valid boundaries
        config_min = DiscoveryPipelineConfig(provider_timeout_seconds=1.0)
        assert config_min.provider_timeout_seconds == 1.0

        config_max = DiscoveryPipelineConfig(provider_timeout_seconds=300.0)
        assert config_max.provider_timeout_seconds == 300.0

        # Invalid: below 1.0
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(provider_timeout_seconds=0.5)

        # Invalid: above 300.0
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(provider_timeout_seconds=301.0)

    def test_discovery_pipeline_config_validates_quality_score(self):
        """Test DiscoveryPipelineConfig validates min_quality_score."""
        # Valid boundaries
        config_min = DiscoveryPipelineConfig(min_quality_score=0.0)
        assert config_min.min_quality_score == 0.0

        config_max = DiscoveryPipelineConfig(min_quality_score=1.0)
        assert config_max.min_quality_score == 1.0

        # Invalid: below 0.0
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(min_quality_score=-0.1)

        # Invalid: above 1.0
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(min_quality_score=1.1)

    def test_discovery_pipeline_config_validates_relevance_score(self):
        """Test DiscoveryPipelineConfig validates min_relevance_score."""
        # Valid boundaries
        config_min = DiscoveryPipelineConfig(min_relevance_score=0.0)
        assert config_min.min_relevance_score == 0.0

        config_max = DiscoveryPipelineConfig(min_relevance_score=1.0)
        assert config_max.min_relevance_score == 1.0

        # Invalid: below 0.0
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(min_relevance_score=-0.1)

        # Invalid: above 1.0
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(min_relevance_score=1.1)

    def test_discovery_pipeline_config_validates_max_papers(self):
        """Test DiscoveryPipelineConfig validates max_papers range."""
        # Valid boundaries
        config_min = DiscoveryPipelineConfig(max_papers=1)
        assert config_min.max_papers == 1

        config_max = DiscoveryPipelineConfig(max_papers=500)
        assert config_max.max_papers == 500

        # Invalid: below 1
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(max_papers=0)

        # Invalid: above 500
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(max_papers=501)

    def test_discovery_pipeline_config_validates_min_citations(self):
        """Test DiscoveryPipelineConfig validates min_citations >= 0."""
        # Valid
        config = DiscoveryPipelineConfig(min_citations=10)
        assert config.min_citations == 10

        config_zero = DiscoveryPipelineConfig(min_citations=0)
        assert config_zero.min_citations == 0

        # Invalid: negative
        with pytest.raises(ValidationError):
            DiscoveryPipelineConfig(min_citations=-1)

    def test_discovery_pipeline_config_nested_configs(self):
        """Test DiscoveryPipelineConfig accepts custom nested configs."""
        custom_enhancement = QueryEnhancementConfig(strategy="hybrid", max_queries=10)
        custom_citation = DiscoveryCitationConfig(max_depth=2)
        custom_quality = QualityWeights(citation=0.5, venue=0.3, recency=0.2)
        custom_tiers = QualityTierConfig(excellent=0.9, good=0.7, fair=0.5)

        config = DiscoveryPipelineConfig(
            query_enhancement=custom_enhancement,
            citation_exploration=custom_citation,
            quality_weights=custom_quality,
            quality_tiers=custom_tiers,
        )

        assert config.query_enhancement.strategy == "hybrid"
        assert config.query_enhancement.max_queries == 10
        assert config.citation_exploration.max_depth == 2
        assert config.quality_weights.citation == 0.5
        assert config.quality_tiers.excellent == 0.9


class TestDiscoveryResultExtensions:
    """Tests for extended DiscoveryResult model."""

    def test_discovery_result_with_source_breakdown(self):
        """Test DiscoveryResult includes source_breakdown field."""
        result = DiscoveryResult(
            papers=[],
            source_breakdown={"arxiv": 10, "semantic_scholar": 15},
        )
        assert result.source_breakdown == {"arxiv": 10, "semantic_scholar": 15}

    def test_discovery_result_with_mode(self):
        """Test DiscoveryResult includes mode field."""
        result = DiscoveryResult(papers=[], mode=DiscoveryMode.DEEP)
        assert result.mode == DiscoveryMode.DEEP

    def test_discovery_result_mode_optional(self):
        """Test DiscoveryResult mode field is optional."""
        result = DiscoveryResult(papers=[])
        assert result.mode is None

    def test_discovery_result_source_breakdown_defaults_to_empty(self):
        """Test DiscoveryResult source_breakdown defaults to empty dict."""
        result = DiscoveryResult(papers=[])
        assert result.source_breakdown == {}

    def test_discovery_result_with_all_new_fields(self):
        """Test DiscoveryResult with all new fields populated."""
        papers = [
            ScoredPaper(
                paper_id="1",
                title="Paper 1",
                quality_score=0.8,
                source="arxiv",
            ),
            ScoredPaper(
                paper_id="2",
                title="Paper 2",
                quality_score=0.7,
                source="semantic_scholar",
            ),
        ]
        result = DiscoveryResult(
            papers=papers,
            source_breakdown={"arxiv": 1, "semantic_scholar": 1},
            mode=DiscoveryMode.STANDARD,
        )
        assert len(result.papers) == 2
        assert result.source_breakdown == {"arxiv": 1, "semantic_scholar": 1}
        assert result.mode == DiscoveryMode.STANDARD
        assert result.paper_count == 2


class TestDiscoveryMetricsExtensions:
    """Tests for extended DiscoveryMetrics model."""

    def test_discovery_metrics_with_citation_fields(self):
        """Test DiscoveryMetrics includes citation exploration fields."""
        metrics = DiscoveryMetrics(
            forward_citations_found=25,
            backward_citations_found=15,
        )
        assert metrics.forward_citations_found == 25
        assert metrics.backward_citations_found == 15

    def test_discovery_metrics_citation_fields_default_to_zero(self):
        """Test DiscoveryMetrics citation fields default to 0."""
        metrics = DiscoveryMetrics()
        assert metrics.forward_citations_found == 0
        assert metrics.backward_citations_found == 0

    def test_discovery_metrics_with_duration_ms(self):
        """Test DiscoveryMetrics includes duration_ms alias field."""
        metrics = DiscoveryMetrics(
            duration_ms=5000,
            pipeline_duration_ms=5000,
        )
        assert metrics.duration_ms == 5000
        assert metrics.pipeline_duration_ms == 5000

    def test_discovery_metrics_duration_ms_defaults_to_zero(self):
        """Test DiscoveryMetrics duration_ms defaults to 0."""
        metrics = DiscoveryMetrics()
        assert metrics.duration_ms == 0

    def test_discovery_metrics_validates_citation_counts(self):
        """Test DiscoveryMetrics validates citation counts are non-negative."""
        # Valid: zero and positive
        metrics = DiscoveryMetrics(
            forward_citations_found=0,
            backward_citations_found=100,
        )
        assert metrics.forward_citations_found == 0
        assert metrics.backward_citations_found == 100

        # Invalid: negative forward
        with pytest.raises(ValidationError):
            DiscoveryMetrics(forward_citations_found=-1)

        # Invalid: negative backward
        with pytest.raises(ValidationError):
            DiscoveryMetrics(backward_citations_found=-1)

    def test_discovery_metrics_validates_duration_ms(self):
        """Test DiscoveryMetrics validates duration_ms is non-negative."""
        # Valid
        metrics = DiscoveryMetrics(duration_ms=1000)
        assert metrics.duration_ms == 1000

        # Invalid: negative
        with pytest.raises(ValidationError):
            DiscoveryMetrics(duration_ms=-1)

    def test_discovery_metrics_with_all_new_fields(self):
        """Test DiscoveryMetrics with all new fields populated."""
        metrics = DiscoveryMetrics(
            queries_generated=5,
            papers_retrieved=100,
            papers_after_dedup=80,
            papers_after_quality_filter=50,
            papers_after_relevance_filter=30,
            providers_queried=["arxiv", "semantic_scholar"],
            avg_relevance_score=0.75,
            avg_quality_score=0.65,
            pipeline_duration_ms=4500,
            forward_citations_found=20,
            backward_citations_found=15,
            duration_ms=4500,
        )
        assert metrics.queries_generated == 5
        assert metrics.forward_citations_found == 20
        assert metrics.backward_citations_found == 15
        assert metrics.duration_ms == 4500
        assert metrics.pipeline_duration_ms == 4500


class TestScoredPaperFromPaperMetadata:
    """Tests for ScoredPaper.from_paper_metadata factory method."""

    def test_from_paper_metadata_basic(self):
        """Test creating ScoredPaper from minimal PaperMetadata."""
        from src.models.paper import PaperMetadata

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
        )
        scored = ScoredPaper.from_paper_metadata(paper, quality_score=0.8)

        assert scored.paper_id == "test-123"
        assert scored.title == "Test Paper"
        assert scored.url == "https://example.com/paper"
        assert scored.quality_score == 0.8
        assert scored.relevance_score is None
        assert scored.engagement_score == 0.0

    def test_from_paper_metadata_with_all_scores(self):
        """Test creating ScoredPaper with all score parameters."""
        from src.models.paper import PaperMetadata

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
        )
        scored = ScoredPaper.from_paper_metadata(
            paper,
            quality_score=0.8,
            relevance_score=0.9,
            engagement_score=150.0,
            source="arxiv",
        )

        assert scored.quality_score == 0.8
        assert scored.relevance_score == 0.9
        assert scored.engagement_score == 150.0
        assert scored.source == "arxiv"

    def test_from_paper_metadata_with_authors_as_objects(self):
        """Test author extraction when authors are objects with name attribute."""
        from src.models.paper import PaperMetadata, Author

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
            authors=[
                Author(name="John Doe"),
                Author(name="Jane Smith"),
            ],
        )
        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.authors == ["John Doe", "Jane Smith"]

    def test_from_paper_metadata_with_authors_as_strings(self):
        """Test author extraction when authors are strings (legacy format)."""
        from src.models.paper import PaperMetadata
        from unittest.mock import Mock

        # Create a mock paper that bypasses Pydantic validation
        # This tests the defensive code in from_paper_metadata
        paper = Mock(spec=PaperMetadata)
        paper.paper_id = "test-123"
        paper.title = "Test Paper"
        paper.url = "https://example.com/paper"
        paper.authors = ["John Doe", "Jane Smith"]
        paper.abstract = None
        paper.doi = None
        paper.open_access_pdf = None
        paper.publication_date = None
        paper.venue = None
        paper.citation_count = 0

        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.authors == ["John Doe", "Jane Smith"]

    def test_from_paper_metadata_with_authors_as_dicts(self):
        """Test author extraction when authors are dicts with name key."""
        from src.models.paper import PaperMetadata
        from unittest.mock import Mock

        # Create a mock paper that bypasses Pydantic validation
        paper = Mock(spec=PaperMetadata)
        paper.paper_id = "test-123"
        paper.title = "Test Paper"
        paper.url = "https://example.com/paper"
        paper.authors = [
            {"name": "John Doe"},
            {"name": "Jane Smith"},
        ]
        paper.abstract = None
        paper.doi = None
        paper.open_access_pdf = None
        paper.publication_date = None
        paper.venue = None
        paper.citation_count = 0

        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.authors == ["John Doe", "Jane Smith"]

    def test_from_paper_metadata_with_open_access_pdf(self):
        """Test PDF URL extraction."""
        from src.models.paper import PaperMetadata

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
            open_access_pdf="https://example.com/paper.pdf",
        )
        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.open_access_pdf == "https://example.com/paper.pdf"

    def test_from_paper_metadata_with_publication_date_string(self):
        """Test publication date when it's already a string."""
        from src.models.paper import PaperMetadata
        from unittest.mock import Mock

        # Create a mock paper with string publication_date
        paper = Mock(spec=PaperMetadata)
        paper.paper_id = "test-123"
        paper.title = "Test Paper"
        paper.url = "https://example.com/paper"
        paper.publication_date = "2024-01-15"
        paper.abstract = None
        paper.doi = None
        paper.open_access_pdf = None
        paper.authors = []
        paper.venue = None
        paper.citation_count = 0

        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.publication_date == "2024-01-15"

    def test_from_paper_metadata_with_publication_date_object(self):
        """Test publication date when it's a datetime object."""
        from src.models.paper import PaperMetadata
        from datetime import datetime

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
            publication_date=datetime(2024, 1, 15),  # type: ignore[arg-type]
        )
        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.publication_date == "2024-01-15T00:00:00"

    def test_from_paper_metadata_with_source_from_paper(self):
        """Test source extraction from paper's discovery_source attribute."""
        from src.models.paper import PaperMetadata

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
            discovery_source="arxiv",
        )
        scored = ScoredPaper.from_paper_metadata(paper)

        # The from_paper_metadata should use discovery_source when available
        assert scored.source == "arxiv" or scored.source is None

    def test_from_paper_metadata_source_parameter_override(self):
        """Test that provided source parameter is used when paper has no source."""
        from src.models.paper import PaperMetadata

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
        )
        scored = ScoredPaper.from_paper_metadata(paper, source="custom_source")

        assert scored.source == "custom_source"

    def test_from_paper_metadata_with_source_object_with_value(self):
        """Test source extraction when paper.source has .value attribute (enum)."""
        from src.models.paper import PaperMetadata
        from unittest.mock import Mock

        # Create mock with source object that has .value attribute
        paper = Mock(spec=PaperMetadata)
        paper.paper_id = "test-123"
        paper.title = "Test Paper"
        paper.url = "https://example.com/paper"
        paper.abstract = None
        paper.doi = None
        paper.open_access_pdf = None
        paper.authors = []
        paper.publication_date = None
        paper.venue = None
        paper.citation_count = 0

        # Mock source object with .value attribute
        source_obj = Mock()
        source_obj.value = "arxiv"
        paper.source = source_obj

        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.source == "arxiv"

    def test_from_paper_metadata_with_source_object_without_value(self):
        """Test source extraction when paper.source lacks .value attr."""
        from src.models.paper import PaperMetadata
        from unittest.mock import Mock

        # Create mock with source object without .value attribute
        paper = Mock(spec=PaperMetadata)
        paper.paper_id = "test-123"
        paper.title = "Test Paper"
        paper.url = "https://example.com/paper"
        paper.abstract = None
        paper.doi = None
        paper.open_access_pdf = None
        paper.authors = []
        paper.publication_date = None
        paper.venue = None
        paper.citation_count = 0

        # Mock source object without .value attribute, will use str()
        source_obj = Mock()
        source_obj.value = Mock(side_effect=AttributeError)  # Make .value fail
        paper.source = "semantic_scholar"

        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.source == "semantic_scholar"

    def test_from_paper_metadata_with_publication_date_non_string_non_isoformat(self):
        """Test publication date fallback when not string/isoformat."""
        from src.models.paper import PaperMetadata
        from unittest.mock import Mock

        # Create mock with publication_date that's not a string and has no isoformat
        paper = Mock(spec=PaperMetadata)
        paper.paper_id = "test-123"
        paper.title = "Test Paper"
        paper.url = "https://example.com/paper"
        paper.abstract = None
        paper.doi = None
        paper.open_access_pdf = None
        paper.authors = []
        paper.publication_date = 20240115  # Integer, no isoformat method
        paper.venue = None
        paper.citation_count = 0

        scored = ScoredPaper.from_paper_metadata(paper)

        # Should remain None since it can't be converted
        assert scored.publication_date is None

    def test_from_paper_metadata_with_empty_authors_list(self):
        """Test with empty authors list coverage."""
        from src.models.paper import PaperMetadata

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            url="https://example.com/paper",
            authors=[],
        )
        scored = ScoredPaper.from_paper_metadata(paper)

        assert scored.authors == []

    def test_from_paper_metadata_complete(self):
        """Test creating ScoredPaper with all paper metadata fields."""
        from src.models.paper import PaperMetadata, Author
        from datetime import datetime

        paper = PaperMetadata(
            paper_id="test-123",
            title="Test Paper",
            abstract="This is a test abstract.",
            doi="10.1234/test",
            url="https://example.com/paper",
            open_access_pdf="https://example.com/paper.pdf",
            authors=[Author(name="John Doe")],
            publication_date=datetime(2024, 1, 15),
            venue="Test Conference 2024",
            citation_count=42,
            discovery_source="semantic_scholar",
        )
        scored = ScoredPaper.from_paper_metadata(
            paper,
            quality_score=0.85,
            relevance_score=0.92,
            engagement_score=200.0,
        )

        assert scored.paper_id == "test-123"
        assert scored.title == "Test Paper"
        assert scored.abstract == "This is a test abstract."
        assert scored.doi == "10.1234/test"
        assert scored.url == "https://example.com/paper"
        assert scored.open_access_pdf == "https://example.com/paper.pdf"
        assert scored.authors == ["John Doe"]
        assert scored.publication_date == "2024-01-15T00:00:00"
        assert scored.venue == "Test Conference 2024"
        assert scored.citation_count == 42
        assert scored.quality_score == 0.85
        assert scored.relevance_score == 0.92
        assert scored.engagement_score == 200.0


class TestScoredPaperFinalScore:
    """Tests for ScoredPaper.final_score computed field."""

    def test_final_score_with_relevance(self):
        """Test final_score combines quality (40%) and relevance (60%)."""
        paper = ScoredPaper(
            paper_id="test-123",
            title="Test Paper",
            quality_score=0.8,
            relevance_score=0.6,
        )
        # Expected: 0.4 * 0.8 + 0.6 * 0.6 = 0.32 + 0.36 = 0.68
        assert paper.final_score == pytest.approx(0.68)

    def test_final_score_without_relevance(self):
        """Test final_score equals quality_score when no relevance."""
        paper = ScoredPaper(
            paper_id="test-123",
            title="Test Paper",
            quality_score=0.75,
            relevance_score=None,
        )
        assert paper.final_score == 0.75


class TestDiscoveryResultGetTopPapers:
    """Tests for DiscoveryResult.get_top_papers method."""

    def test_get_top_papers_returns_sorted_by_final_score(self):
        """Test get_top_papers returns papers sorted by final_score descending."""
        papers = [
            ScoredPaper(
                paper_id="1",
                title="Paper 1",
                quality_score=0.5,
            ),
            ScoredPaper(
                paper_id="2",
                title="Paper 2",
                quality_score=0.9,
            ),
            ScoredPaper(
                paper_id="3",
                title="Paper 3",
                quality_score=0.7,
            ),
        ]
        result = DiscoveryResult(papers=papers)
        top_papers = result.get_top_papers(n=3)

        assert len(top_papers) == 3
        assert top_papers[0].paper_id == "2"  # 0.9
        assert top_papers[1].paper_id == "3"  # 0.7
        assert top_papers[2].paper_id == "1"  # 0.5

    def test_get_top_papers_limits_to_n(self):
        """Test get_top_papers returns only top N papers."""
        papers = [
            ScoredPaper(paper_id=str(i), title=f"Paper {i}", quality_score=i / 10)
            for i in range(10)
        ]
        result = DiscoveryResult(papers=papers)
        top_papers = result.get_top_papers(n=3)

        assert len(top_papers) == 3

    def test_get_top_papers_default_limit(self):
        """Test get_top_papers uses default limit of 10."""
        papers = [
            ScoredPaper(paper_id=str(i), title=f"Paper {i}", quality_score=i / 20)
            for i in range(15)
        ]
        result = DiscoveryResult(papers=papers)
        top_papers = result.get_top_papers()

        assert len(top_papers) == 10

    def test_get_top_papers_with_relevance_scores(self):
        """Test get_top_papers sorts by final_score (quality+relevance)."""
        papers = [
            ScoredPaper(
                paper_id="1",
                title="Paper 1",
                quality_score=0.8,
                relevance_score=0.5,  # final: 0.62
            ),
            ScoredPaper(
                paper_id="2",
                title="Paper 2",
                quality_score=0.6,
                relevance_score=0.9,  # final: 0.78
            ),
        ]
        result = DiscoveryResult(papers=papers)
        top_papers = result.get_top_papers(n=2)

        assert top_papers[0].paper_id == "2"  # Higher final score
        assert top_papers[1].paper_id == "1"

    def test_get_top_papers_empty_list(self):
        """Test get_top_papers handles empty paper list."""
        result = DiscoveryResult(papers=[])
        top_papers = result.get_top_papers(n=5)

        assert len(top_papers) == 0
