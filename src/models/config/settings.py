"""Global settings and root configuration models.

This module contains the top-level configuration:
- GlobalSettings: Pipeline-wide settings
- ResearchConfig: Root configuration model
"""

from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

from src.models.config.core import ProviderType, ResearchTopic
from src.models.config.extraction import PDFSettings, LLMSettings, CostLimitSettings
from src.models.config.discovery import (
    ProviderSelectionConfig,
    DiscoveryFilterSettings,
    IncrementalDiscoverySettings,
    EnhancedDiscoveryConfig,
)
from src.models.config.phase7 import (
    QueryExpansionConfig,
    CitationExplorationConfig,
    AggregationConfig,
)
from src.models.concurrency import ConcurrencyConfig
from src.models.notification import NotificationSettings


class GlobalSettings(BaseModel):
    """Global pipeline settings"""

    output_base_dir: str = Field("./output", description="Base output directory")
    enable_duplicate_detection: bool = Field(
        True, description="Enable topic deduplication"
    )
    # Discovery sources configuration
    sources: List[ProviderType] = Field(
        default_factory=lambda: [ProviderType.ARXIV],
        description="List of paper sources (arxiv, semantic_scholar, huggingface)",
    )
    semantic_scholar_api_key: Optional[str] = Field(
        None, min_length=10, description="Semantic Scholar API key (optional)"
    )
    huggingface_api_key: Optional[str] = Field(
        None,
        description="HuggingFace API key (optional, not required for Daily Papers)",
    )
    # Phase 2: PDF and LLM settings (optional for backward compatibility)
    pdf_settings: Optional[PDFSettings] = Field(
        default=None, description="PDF processing settings (Phase 2)"
    )
    llm_settings: Optional[LLMSettings] = Field(
        default=None, description="LLM configuration (Phase 2)"
    )
    cost_limits: Optional[CostLimitSettings] = Field(
        default=None, description="Cost control settings (Phase 2)"
    )
    # Phase 3.1: Concurrency configuration
    concurrency: ConcurrencyConfig = Field(
        default_factory=lambda: ConcurrencyConfig(),
        description="Concurrent processing settings (Phase 3.1)",
    )
    # Phase 3.2: Provider selection configuration
    provider_selection: ProviderSelectionConfig = Field(
        default_factory=lambda: ProviderSelectionConfig(),
        description="Provider selection settings (Phase 3.2)",
    )
    # Phase 3.7: Notification settings
    notification_settings: NotificationSettings = Field(
        default_factory=lambda: NotificationSettings(),
        description="Notification settings (Phase 3.7)",
    )
    # Phase 6: Enhanced discovery settings
    enhanced_discovery: Optional[EnhancedDiscoveryConfig] = Field(
        default=None,
        description="Enhanced discovery pipeline settings (Phase 6)",
    )
    # Phase 7.1: Discovery optimization settings
    discovery_filter_settings: DiscoveryFilterSettings = Field(
        default_factory=DiscoveryFilterSettings,  # type: ignore[arg-type]
        description="Discovery-time filtering settings (Phase 7.1)",
    )
    incremental_discovery_settings: IncrementalDiscoverySettings = Field(
        default_factory=IncrementalDiscoverySettings,  # type: ignore[arg-type]
        description="Incremental discovery settings (Phase 7.1)",
    )
    # Phase 7.2: Multi-source discovery settings
    query_expansion: Optional[QueryExpansionConfig] = Field(
        default=None,
        description="Query expansion settings (Phase 7.2)",
    )
    citation_exploration: Optional[CitationExplorationConfig] = Field(
        default=None,
        description="Citation exploration settings (Phase 7.2)",
    )
    aggregation: Optional[AggregationConfig] = Field(
        default=None,
        description="Result aggregation settings (Phase 7.2)",
    )


class ResearchConfig(BaseModel):
    """Root configuration model"""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    research_topics: List[ResearchTopic] = Field(..., min_length=1, max_length=100)
    settings: GlobalSettings
