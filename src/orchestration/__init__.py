"""Orchestration module for research pipeline coordination.

Phase 5.2: Refactored with extracted phase modules.
"""

from src.orchestration.concurrent_pipeline import ConcurrentPipeline

# Phase 5.2: New modular components
from src.orchestration.context import PipelineContext
from src.orchestration.result import PipelineResult
from src.orchestration.phases import (
    PipelinePhase,
    DiscoveryPhase,
    DiscoveryResult,
    ExtractionPhase,
    ExtractionResult,
    SynthesisPhase,
    SynthesisResult,
    CrossSynthesisPhase,
    CrossSynthesisResult,
)

# Backward compatibility: Import from both old and new locations
# The new pipeline.py is the refactored version
from src.orchestration.pipeline import ResearchPipeline

# Re-export legacy location for backward compatibility
from src.orchestration.research_pipeline import (
    ResearchPipeline as LegacyResearchPipeline,
)

__all__ = [
    # Core pipeline
    "ResearchPipeline",
    "LegacyResearchPipeline",  # For explicit legacy access
    "ConcurrentPipeline",
    # Phase 5.2: New modular components
    "PipelineContext",
    "PipelineResult",
    "PipelinePhase",
    "DiscoveryPhase",
    "DiscoveryResult",
    "ExtractionPhase",
    "ExtractionResult",
    "SynthesisPhase",
    "SynthesisResult",
    "CrossSynthesisPhase",
    "CrossSynthesisResult",
]
