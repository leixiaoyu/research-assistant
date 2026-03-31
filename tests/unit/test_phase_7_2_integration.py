"""Integration and configuration tests for Phase 7.2 components.

Split from test_phase_7_2_components.py for better organization.
Tests cover component integration and config model validation.
"""

import pytest

from src.models.config import (
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
    RankingWeights,
)
from src.models.paper import PaperMetadata
from src.services.result_aggregator import ResultAggregator
from src.utils.query_expander import QueryExpander


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
