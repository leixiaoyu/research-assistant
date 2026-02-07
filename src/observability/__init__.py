"""Observability module for Phase 4: Production Hardening.

Provides:
- Correlation ID context management for request tracing
- Enhanced structured logging with context propagation
- Prometheus metrics for monitoring and alerting

Usage:
    from src.observability import (
        set_correlation_id,
        get_correlation_id,
        get_logger,
        PAPERS_PROCESSED,
        LLM_TOKENS_TOTAL,
    )

    # Set correlation ID at request boundary
    corr_id = set_correlation_id()

    # Get logger with automatic correlation ID injection
    logger = get_logger()
    logger.info("processing_started", paper_id="123")

    # Increment metrics
    PAPERS_PROCESSED.labels(status="success").inc()
"""

from src.observability.context import (
    set_correlation_id,
    get_correlation_id,
    clear_correlation_id,
    correlation_id_context,
)
from src.observability.logging import (
    get_logger,
    configure_logging,
    add_correlation_id_processor,
)
from src.observability.metrics import (
    # Counters
    PAPERS_PROCESSED,
    PAPERS_DISCOVERED,
    LLM_TOKENS_TOTAL,
    LLM_COST_USD_TOTAL,
    LLM_REQUESTS_TOTAL,
    CACHE_OPERATIONS,
    PDF_DOWNLOADS,
    PDF_CONVERSIONS,
    EXTRACTION_ERRORS,
    # Gauges
    ACTIVE_WORKERS,
    QUEUE_SIZE,
    CACHE_SIZE_BYTES,
    DAILY_COST_USD,
    # Histograms
    PAPER_PROCESSING_DURATION,
    LLM_REQUEST_DURATION,
    PDF_DOWNLOAD_DURATION,
    PDF_CONVERSION_DURATION,
    # Registry and utilities
    get_metrics_text,
    reset_metrics,
)

__all__ = [
    # Context
    "set_correlation_id",
    "get_correlation_id",
    "clear_correlation_id",
    "correlation_id_context",
    # Logging
    "get_logger",
    "configure_logging",
    "add_correlation_id_processor",
    # Counters
    "PAPERS_PROCESSED",
    "PAPERS_DISCOVERED",
    "LLM_TOKENS_TOTAL",
    "LLM_COST_USD_TOTAL",
    "LLM_REQUESTS_TOTAL",
    "CACHE_OPERATIONS",
    "PDF_DOWNLOADS",
    "PDF_CONVERSIONS",
    "EXTRACTION_ERRORS",
    # Gauges
    "ACTIVE_WORKERS",
    "QUEUE_SIZE",
    "CACHE_SIZE_BYTES",
    "DAILY_COST_USD",
    # Histograms
    "PAPER_PROCESSING_DURATION",
    "LLM_REQUEST_DURATION",
    "PDF_DOWNLOAD_DURATION",
    "PDF_CONVERSION_DURATION",
    # Utilities
    "get_metrics_text",
    "reset_metrics",
]
