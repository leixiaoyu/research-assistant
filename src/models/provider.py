"""Provider models for Phase 3.2 multi-provider intelligence."""

from typing import Optional, List
from pydantic import BaseModel, Field

from src.models.config import ProviderType


class ProviderMetrics(BaseModel):
    """Metrics collected from a provider search."""

    provider: ProviderType
    query_time_ms: int = Field(..., ge=0, description="Query execution time in ms")
    result_count: int = Field(..., ge=0, description="Number of results returned")
    success: bool = Field(True, description="Whether the search succeeded")
    error: Optional[str] = Field(None, description="Error message if failed")


class ProviderComparison(BaseModel):
    """Comparison results from benchmark mode."""

    providers_queried: List[ProviderType]
    metrics: List[ProviderMetrics]
    total_unique_papers: int = Field(..., ge=0)
    overlap_count: int = Field(default=0, ge=0)
    fastest_provider: Optional[ProviderType] = None
    most_results_provider: Optional[ProviderType] = None
