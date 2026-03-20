"""Cross-topic synthesis service package.

Phase R4 decomposition of cross_synthesis_service.py (731 lines) into:
- cross_synthesis.py: Main orchestration (~300 lines)
- paper_selector.py: Paper selection with quality-weighted sampling (~220 lines)
- prompt_builder.py: Template-based prompt building (~100 lines)
- answer_synthesizer.py: LLM interaction for synthesis (~200 lines)
- state_manager.py: Configuration and state management (~160 lines)

Backward Compatibility:
All public APIs are re-exported from this module to maintain
existing import patterns.
"""

# Main service (backward compatible import)
from src.services.synthesis.cross_synthesis import CrossTopicSynthesisService

# Component services (for direct access)
from src.services.synthesis.paper_selector import PaperSelector
from src.services.synthesis.prompt_builder import SynthesisPromptBuilder
from src.services.synthesis.answer_synthesizer import AnswerSynthesizer
from src.services.synthesis.state_manager import SynthesisStateManager

# Re-export constants for backward compatibility
from src.services.synthesis.paper_selector import DIVERSITY_RATIO
from src.services.synthesis.state_manager import DEFAULT_CONFIG_PATH

__all__ = [
    # Main service
    "CrossTopicSynthesisService",
    # Component services
    "PaperSelector",
    "SynthesisPromptBuilder",
    "AnswerSynthesizer",
    "SynthesisStateManager",
    # Constants
    "DIVERSITY_RATIO",
    "DEFAULT_CONFIG_PATH",
]
