"""Query models for unified query intelligence.

This module defines data structures for query enhancement strategies
and enhanced queries used by QueryIntelligenceService.

Usage:
    from src.models.query import (
        QueryStrategy,
        QueryFocus,
        EnhancedQuery,
    )
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class QueryStrategy(str, Enum):
    """Query enhancement strategies.

    Determines how queries are enhanced for improved discovery:
    - DECOMPOSE: Break into focused sub-queries with specific focus areas
    - EXPAND: Generate semantic variants and related terminology
    - HYBRID: Decompose first, then expand each sub-query
    """

    DECOMPOSE = "decompose"
    EXPAND = "expand"
    HYBRID = "hybrid"


class QueryFocus(str, Enum):
    """Focus area for decomposed queries.

    Categorizes sub-queries by their research perspective:
    - METHODOLOGY: Focus on techniques, algorithms, approaches
    - APPLICATION: Focus on use cases, domains, implementations
    - COMPARISON: Focus on comparisons, benchmarks, evaluations
    - RELATED: Focus on related concepts, synonyms, variations
    - INTERSECTION: Focus on cross-disciplinary aspects
    """

    METHODOLOGY = "methodology"
    APPLICATION = "application"
    COMPARISON = "comparison"
    RELATED = "related"
    INTERSECTION = "intersection"


class EnhancedQuery(BaseModel):
    """Unified query representation for all enhancement strategies.

    Replaces DecomposedQuery with a more flexible structure that supports
    both decomposition and expansion strategies.

    Attributes:
        query: Query text for API search
        focus: Optional focus area (for decomposed queries)
        weight: Weight for result merging (1.0 = normal weight)
        is_original: True if this is the original unmodified query
        parent_query: Parent query if expanded from decomposition
        strategy_used: Strategy that generated this query
    """

    model_config = ConfigDict(frozen=True)

    query: str = Field(..., min_length=1, max_length=500, description="Query text")
    focus: Optional[QueryFocus] = Field(None, description="Focus area if decomposed")
    weight: float = Field(1.0, ge=0.0, le=2.0, description="Weight for result merging")
    is_original: bool = Field(False, description="True for the original query")
    parent_query: Optional[str] = Field(
        None, description="Parent if expanded from decomposition"
    )
    strategy_used: QueryStrategy = Field(
        ..., description="Strategy that generated this query"
    )
