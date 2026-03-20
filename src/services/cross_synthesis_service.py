"""Cross-Topic Synthesis Service for Phase 3.7.

BACKWARD COMPATIBILITY WRAPPER

This module has been refactored into the synthesis/ package:
- src/services/synthesis/cross_synthesis.py: Main orchestration
- src/services/synthesis/paper_selector.py: Paper selection
- src/services/synthesis/prompt_builder.py: Prompt building
- src/services/synthesis/answer_synthesizer.py: LLM synthesis
- src/services/synthesis/state_manager.py: Configuration & state

All public APIs are re-exported here for backward compatibility.
New code should import directly from src.services.synthesis.
"""

# Re-export everything from the synthesis package for backward compatibility
from src.services.synthesis import (
    CrossTopicSynthesisService,
    PaperSelector,
    SynthesisPromptBuilder,
    AnswerSynthesizer,
    SynthesisStateManager,
    DIVERSITY_RATIO,
    DEFAULT_CONFIG_PATH,
)

__all__ = [
    "CrossTopicSynthesisService",
    "PaperSelector",
    "SynthesisPromptBuilder",
    "AnswerSynthesizer",
    "SynthesisStateManager",
    "DIVERSITY_RATIO",
    "DEFAULT_CONFIG_PATH",
]
