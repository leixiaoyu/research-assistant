"""LLM Service - Backward Compatibility Stub

DEPRECATED: This module is deprecated and will be removed in Phase 6.
Please import from src.services.llm instead:

    # New import style (recommended)
    from src.services.llm import LLMService, ProviderHealth

    # Or continue using old import (deprecated)
    from src.services.llm_service import LLMService

This stub exists to maintain backward compatibility during the
Phase 5.1 transition period.
"""

import warnings
from typing import TYPE_CHECKING

# Issue deprecation warning on import
warnings.warn(
    "Importing from src.services.llm_service is deprecated. "
    "Use 'from src.services.llm import LLMService' instead. "
    "This module will be removed in Phase 6.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all public symbols from the new package
from src.services.llm.service import LLMService  # noqa: E402
from src.services.llm.providers.base import (  # noqa: E402
    ProviderHealth,
    LLMResponse,
    LLMProvider,
)
from src.services.llm.cost_tracker import CostTracker  # noqa: E402
from src.services.llm.prompt_builder import PromptBuilder  # noqa: E402
from src.services.llm.response_parser import ResponseParser  # noqa: E402
from src.services.llm.exceptions import (  # noqa: E402
    LLMProviderError,
    RateLimitError,
    AuthenticationError,
    ContentFilterError,
    ProviderUnavailableError,
    ModelNotFoundError,
    ContextLengthExceededError,
)

# For type checking - ensure all original exports are available
if TYPE_CHECKING:
    from src.models.llm import (  # noqa: F401
        LLMConfig,
        CostLimits,
        EnhancedUsageStats,
        ProviderUsageStats,
    )

__all__ = [
    # Main service
    "LLMService",
    # Provider abstractions
    "ProviderHealth",
    "LLMResponse",
    "LLMProvider",
    # Components
    "CostTracker",
    "PromptBuilder",
    "ResponseParser",
    # Exceptions
    "LLMProviderError",
    "RateLimitError",
    "AuthenticationError",
    "ContentFilterError",
    "ProviderUnavailableError",
    "ModelNotFoundError",
    "ContextLengthExceededError",
]
