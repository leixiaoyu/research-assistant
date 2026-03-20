"""Configuration models package.

This package contains domain-organized configuration models split from
the original monolithic config.py (570 lines, 22 classes).

Modules:
    core: Timeframes, topics, and core enums
    extraction: PDF and LLM settings
    discovery: Provider selection and filtering
    phase7: Phase 7.2 discovery expansion
    settings: GlobalSettings and ResearchConfig

All classes are re-exported here for backward compatibility.
Existing imports like `from src.models.config import ResearchConfig` continue to work.
"""

# Core models (timeframes, topics, enums)
from src.models.config.core import (
    TimeframeType,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
    Timeframe,
    ProviderType,
    PDFStrategy,
    NoPDFAction,
    ResearchTopic,
)

# Extraction models (PDF, LLM)
from src.models.config.extraction import (
    PDFBackendConfig,
    PDFSettings,
    LLMSettings,
    CostLimitSettings,
)

# Discovery models (provider selection, filtering)
from src.models.config.discovery import (
    ProviderSelectionConfig,
    DiscoveryFilterSettings,
    IncrementalDiscoverySettings,
    EnhancedDiscoveryConfig,
)

# Phase 7.2 models (discovery expansion)
from src.models.config.phase7 import (
    RankingWeights,
    CitationExplorationConfig,
    QueryExpansionConfig,
    AggregationConfig,
)

# Settings and root config
from src.models.config.settings import (
    GlobalSettings,
    ResearchConfig,
)

__all__ = [
    # Core
    "TimeframeType",
    "TimeframeRecent",
    "TimeframeSinceYear",
    "TimeframeDateRange",
    "Timeframe",
    "ProviderType",
    "PDFStrategy",
    "NoPDFAction",
    "ResearchTopic",
    # Extraction
    "PDFBackendConfig",
    "PDFSettings",
    "LLMSettings",
    "CostLimitSettings",
    # Discovery
    "ProviderSelectionConfig",
    "DiscoveryFilterSettings",
    "IncrementalDiscoverySettings",
    "EnhancedDiscoveryConfig",
    # Phase 7.2
    "RankingWeights",
    "CitationExplorationConfig",
    "QueryExpansionConfig",
    "AggregationConfig",
    # Settings
    "GlobalSettings",
    "ResearchConfig",
]
