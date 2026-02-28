"""Research Pipeline - Backward Compatibility Stub

DEPRECATED: This module is deprecated and will be removed in Phase 6.
Please import from src.orchestration instead:

    # New import style (recommended)
    from src.orchestration import ResearchPipeline, PipelineResult

    # Or continue using old import (deprecated)
    from src.orchestration.research_pipeline import ResearchPipeline

This stub exists to maintain backward compatibility during the
Phase 5.2 transition period.
"""

import warnings

# Issue deprecation warning on import
warnings.warn(
    "Importing from src.orchestration.research_pipeline is deprecated. "
    "Use 'from src.orchestration import ResearchPipeline' instead. "
    "This module will be removed in Phase 6.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all public symbols from the new package
from src.orchestration.pipeline import ResearchPipeline  # noqa: E402
from src.orchestration.result import PipelineResult  # noqa: E402
from src.orchestration.context import PipelineContext  # noqa: E402

__all__ = [
    "ResearchPipeline",
    "PipelineResult",
    "PipelineContext",
]
