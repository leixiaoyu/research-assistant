"""Concurrency configuration models.

Defines worker pool settings, semaphore limits, and queue parameters for
Phase 3.1 concurrent orchestration.
"""

from pydantic import BaseModel, Field


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel processing"""

    # Worker pool settings
    max_concurrent_downloads: int = Field(default=5, ge=1, le=20)
    max_concurrent_conversions: int = Field(default=3, ge=1, le=10)
    max_concurrent_llm: int = Field(default=2, ge=1, le=5)

    # Queue settings
    queue_size: int = Field(default=100, ge=10, le=1000)

    # Checkpoint settings
    checkpoint_interval: int = Field(default=10, ge=1, le=100)

    # Timeout settings
    worker_timeout_seconds: int = Field(default=600, ge=60, le=3600)

    # Backpressure settings
    enable_backpressure: bool = True
    backpressure_threshold: float = Field(default=0.8, ge=0.5, le=1.0)


class WorkerStats(BaseModel):
    """Statistics for a single worker"""

    worker_id: int
    papers_processed: int = 0
    papers_failed: int = 0
    total_duration_seconds: float = 0.0
    is_active: bool = True


class PipelineStats(BaseModel):
    """Statistics for concurrent pipeline"""

    total_papers: int = 0
    papers_completed: int = 0
    papers_failed: int = 0
    papers_cached: int = 0
    papers_deduplicated: int = 0

    active_workers: int = 0
    queue_size: int = 0

    total_duration_seconds: float = 0.0
