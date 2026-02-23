"""LLM Service Package

Phase 5.1: Decomposed LLM service with focused modules.

This package provides:
- LLMService: Main orchestrator for LLM extraction
- Provider implementations (Anthropic, Google)
- Cost tracking and budget enforcement
- Prompt building and response parsing

Usage:
    from src.services.llm import LLMService
    # or
    from src.services.llm.service import LLMService

For backward compatibility, LLMService is also available from:
    from src.services.llm_service import LLMService
"""

from src.services.llm.service import LLMService
from src.services.llm.cost_tracker import CostTracker
from src.services.llm.prompt_builder import PromptBuilder
from src.services.llm.response_parser import ResponseParser
from src.services.llm.providers.base import LLMProvider, LLMResponse, ProviderHealth
from src.services.llm.exceptions import (
    LLMProviderError,
    RateLimitError,
    AuthenticationError,
    ContentFilterError,
    ProviderUnavailableError,
    ModelNotFoundError,
    ContextLengthExceededError,
)

__all__ = [
    # Main service
    "LLMService",
    # Components
    "CostTracker",
    "PromptBuilder",
    "ResponseParser",
    # Provider abstractions
    "LLMProvider",
    "LLMResponse",
    "ProviderHealth",
    # Exceptions
    "LLMProviderError",
    "RateLimitError",
    "AuthenticationError",
    "ContentFilterError",
    "ProviderUnavailableError",
    "ModelNotFoundError",
    "ContextLengthExceededError",
]
