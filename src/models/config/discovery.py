"""Discovery configuration models: provider selection and filtering.

This module contains configuration for paper discovery:
- Provider selection and fallback
- Discovery-time filtering
- Incremental discovery settings
- Enhanced discovery pipeline (Phase 6)
"""

from typing import List
from pydantic import BaseModel, Field

from src.models.config.core import ProviderType


class ProviderSelectionConfig(BaseModel):
    """Configuration for intelligent provider selection (Phase 3.2)"""

    auto_select: bool = Field(
        default=True,
        description="Automatically select optimal provider based on query",
    )
    fallback_enabled: bool = Field(
        default=True,
        description="Enable automatic fallback to alternate providers on failure",
    )
    benchmark_mode: bool = Field(
        default=False,
        description="Query all providers for comparison",
    )
    preference_order: List[ProviderType] = Field(
        default_factory=lambda: [
            ProviderType.ARXIV,
            ProviderType.SEMANTIC_SCHOLAR,
            ProviderType.HUGGINGFACE,
        ],
        description="Provider preference order for auto-selection",
    )
    fallback_timeout_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Timeout before triggering fallback",
    )


class DiscoveryFilterSettings(BaseModel):
    """Discovery-time filtering settings (Phase 7.1)"""

    enabled: bool = Field(
        True,
        description="Enable quality filtering during discovery phase",
    )
    register_at_discovery: bool = Field(
        True,
        description="Register papers when discovered (prevents reprocessing)",
    )
    verbose_logging: bool = Field(
        False,
        description="Log each filtered paper with rejection reason",
    )


class IncrementalDiscoverySettings(BaseModel):
    """Incremental discovery settings (Phase 7.1)"""

    enabled: bool = Field(
        True,
        description="Use last run timestamp for queries (incremental mode)",
    )
    overlap_buffer_hours: int = Field(
        1,
        ge=0,
        le=48,
        description="Safety overlap buffer in hours for edge cases",
    )
    reset_on_query_change: bool = Field(
        True,
        description="Reset timestamp if query text changes",
    )


class EnhancedDiscoveryConfig(BaseModel):
    """Configuration for enhanced discovery pipeline (Phase 6).

    Controls the 4-stage intelligent discovery:
    1. Query decomposition
    2. Multi-source retrieval
    3. Quality filtering
    4. Relevance ranking

    Attributes:
        enable_query_decomposition: Enable LLM-based query decomposition
        max_subqueries: Maximum sub-queries to generate
        providers: List of providers to query
        papers_per_provider: Max papers per provider per query
        min_citations: Minimum citation threshold
        min_quality_score: Minimum quality score (0.0-1.0)
        require_abstract: Require paper abstract
        require_pdf: Require PDF availability
        exclude_preprints: Exclude preprint papers
        enable_relevance_ranking: Enable LLM-based relevance ranking
        min_relevance_score: Minimum relevance score (0.0-1.0)
        relevance_batch_size: Batch size for relevance scoring
    """

    # Query decomposition
    enable_query_decomposition: bool = Field(
        True, description="Enable LLM-based query decomposition"
    )
    max_subqueries: int = Field(
        5, ge=1, le=10, description="Maximum sub-queries to generate"
    )

    # Multi-source retrieval (Comprehensive + Trending)
    providers: List[ProviderType] = Field(
        default_factory=lambda: [
            ProviderType.ARXIV,
            ProviderType.SEMANTIC_SCHOLAR,
            ProviderType.OPENALEX,
            ProviderType.HUGGINGFACE,
        ],
        description="Providers to query (includes HuggingFace as Trending source)",
    )
    papers_per_provider: int = Field(
        100, ge=10, le=500, description="Max papers per provider per query"
    )

    # Quality filtering
    min_citations: int = Field(0, ge=0, description="Minimum citation threshold")
    min_quality_score: float = Field(
        0.3, ge=0.0, le=1.0, description="Minimum quality score"
    )
    require_abstract: bool = Field(True, description="Require paper abstract")
    require_pdf: bool = Field(False, description="Require PDF availability")
    exclude_preprints: bool = Field(False, description="Exclude preprint papers")

    # Relevance ranking
    enable_relevance_ranking: bool = Field(
        True, description="Enable LLM-based relevance ranking"
    )
    min_relevance_score: float = Field(
        0.5, ge=0.0, le=1.0, description="Minimum relevance score"
    )
    relevance_batch_size: int = Field(
        10, ge=1, le=50, description="Batch size for relevance scoring"
    )
