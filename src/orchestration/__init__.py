"""Orchestration module for research pipeline coordination.

Phase 5.2: Refactored with extracted phase modules.

Import from this package for all orchestration needs:
    from src.orchestration import ResearchPipeline, PipelineResult
"""

from src.orchestration.concurrent_pipeline import ConcurrentPipeline

# Phase 5.2: New modular components (primary exports)
from src.orchestration.pipeline import ResearchPipeline
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

__all__ = [
    # Core pipeline
    "ResearchPipeline",
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
