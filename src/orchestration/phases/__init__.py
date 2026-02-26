"""Pipeline phase modules.

Phase 5.2: Extracted phase-specific orchestrators.

Each phase is an independent, testable module that handles a specific
part of the research pipeline workflow.
"""

from src.orchestration.phases.base import PipelinePhase
from src.orchestration.phases.discovery import DiscoveryPhase, DiscoveryResult
from src.orchestration.phases.extraction import ExtractionPhase, ExtractionResult
from src.orchestration.phases.synthesis import SynthesisPhase, SynthesisResult
from src.orchestration.phases.cross_synthesis import (
    CrossSynthesisPhase,
    CrossSynthesisResult,
)

__all__ = [
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
