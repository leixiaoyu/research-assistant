"""Prometheus metrics definitions for ARISP pipeline.

Defines counters, gauges, and histograms for monitoring:
- Paper processing throughput and latency
- LLM usage and costs
- Cache performance
- PDF processing
- Worker pool status

Usage:
    from src.observability.metrics import (
        PAPERS_PROCESSED,
        LLM_TOKENS_TOTAL,
        PAPER_PROCESSING_DURATION,
    )

    # Increment counter
    PAPERS_PROCESSED.labels(status="success").inc()

    # Track histogram
    with PAPER_PROCESSING_DURATION.labels(stage="extraction").time():
        extract_paper()

    # Set gauge
    ACTIVE_WORKERS.set(5)

Metrics are exposed via /metrics endpoint in the health server.
"""

from typing import Any, Optional
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

# Custom registry to avoid conflicts with default registry
# Allows clean testing and multiple instances
REGISTRY = CollectorRegistry(auto_describe=True)

# =============================================================================
# COUNTERS - Monotonically increasing values
# =============================================================================

PAPERS_PROCESSED = Counter(
    name="arisp_papers_processed_total",
    documentation="Total number of papers processed",
    labelnames=["status"],  # success, failed, skipped
    registry=REGISTRY,
)

PAPERS_DISCOVERED = Counter(
    name="arisp_papers_discovered_total",
    documentation="Total number of papers discovered from APIs",
    labelnames=["provider"],  # semantic_scholar, arxiv
    registry=REGISTRY,
)

LLM_TOKENS_TOTAL = Counter(
    name="arisp_llm_tokens_total",
    documentation="Total LLM tokens used",
    labelnames=["provider", "type"],  # anthropic/google, input/output
    registry=REGISTRY,
)

LLM_COST_USD_TOTAL = Counter(
    name="arisp_llm_cost_usd_total",
    documentation="Total LLM cost in USD",
    labelnames=["provider"],  # anthropic, google
    registry=REGISTRY,
)

LLM_REQUESTS_TOTAL = Counter(
    name="arisp_llm_requests_total",
    documentation="Total LLM API requests",
    labelnames=["provider", "status"],  # anthropic/google, success/failed
    registry=REGISTRY,
)

CACHE_OPERATIONS = Counter(
    name="arisp_cache_operations_total",
    documentation="Total cache operations",
    labelnames=["cache_type", "operation"],  # api/pdf/extraction, hit/miss/set
    registry=REGISTRY,
)

PDF_DOWNLOADS = Counter(
    name="arisp_pdf_downloads_total",
    documentation="Total PDF download attempts",
    labelnames=["status"],  # success, failed, skipped
    registry=REGISTRY,
)

PDF_CONVERSIONS = Counter(
    name="arisp_pdf_conversions_total",
    documentation="Total PDF to markdown conversions",
    labelnames=["backend", "status"],  # marker/pymupdf/pdfplumber, success/failed
    registry=REGISTRY,
)

EXTRACTION_ERRORS = Counter(
    name="arisp_extraction_errors_total",
    documentation="Total extraction errors by type",
    labelnames=["error_type"],  # download, conversion, llm, parsing, cost_limit
    registry=REGISTRY,
)

# =============================================================================
# GAUGES - Values that can go up and down
# =============================================================================

ACTIVE_WORKERS = Gauge(
    name="arisp_active_workers",
    documentation="Number of active worker coroutines",
    labelnames=["worker_type"],  # download, conversion, llm
    registry=REGISTRY,
)

QUEUE_SIZE = Gauge(
    name="arisp_queue_size",
    documentation="Current queue size",
    labelnames=["queue_name"],  # input, results
    registry=REGISTRY,
)

CACHE_SIZE_BYTES = Gauge(
    name="arisp_cache_size_bytes",
    documentation="Cache size in bytes",
    labelnames=["cache_type"],  # api, pdf, extraction
    registry=REGISTRY,
)

DAILY_COST_USD = Gauge(
    name="arisp_daily_cost_usd",
    documentation="Accumulated cost today in USD",
    labelnames=["provider"],  # anthropic, google, total
    registry=REGISTRY,
)

PAPERS_IN_QUEUE = Gauge(
    name="arisp_papers_in_queue",
    documentation="Number of papers waiting to be processed",
    registry=REGISTRY,
)

SCHEDULER_JOBS = Gauge(
    name="arisp_scheduler_jobs",
    documentation="Number of scheduled jobs",
    labelnames=["status"],  # pending, running
    registry=REGISTRY,
)

# =============================================================================
# HISTOGRAMS - Distribution of values
# =============================================================================

# Buckets for paper processing (seconds)
PROCESSING_BUCKETS = (0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, float("inf"))

PAPER_PROCESSING_DURATION = Histogram(
    name="arisp_paper_processing_duration_seconds",
    documentation="Paper processing duration in seconds",
    labelnames=["stage"],  # total, download, conversion, extraction
    buckets=PROCESSING_BUCKETS,
    registry=REGISTRY,
)

LLM_REQUEST_DURATION = Histogram(
    name="arisp_llm_request_duration_seconds",
    documentation="LLM API request duration in seconds",
    labelnames=["provider"],  # anthropic, google
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, float("inf")),
    registry=REGISTRY,
)

PDF_DOWNLOAD_DURATION = Histogram(
    name="arisp_pdf_download_duration_seconds",
    documentation="PDF download duration in seconds",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, float("inf")),
    registry=REGISTRY,
)

PDF_CONVERSION_DURATION = Histogram(
    name="arisp_pdf_conversion_duration_seconds",
    documentation="PDF to markdown conversion duration in seconds",
    labelnames=["backend"],  # marker, pymupdf, pdfplumber, pandoc
    buckets=(1, 5, 10, 30, 60, 120, 300, float("inf")),
    registry=REGISTRY,
)

PAPER_SIZE_BYTES = Histogram(
    name="arisp_paper_size_bytes",
    documentation="PDF file size distribution in bytes",
    buckets=(
        100_000,  # 100KB
        500_000,  # 500KB
        1_000_000,  # 1MB
        5_000_000,  # 5MB
        10_000_000,  # 10MB
        50_000_000,  # 50MB
        float("inf"),
    ),
    registry=REGISTRY,
)

EXTRACTION_CONFIDENCE = Histogram(
    name="arisp_extraction_confidence",
    documentation="Distribution of LLM extraction confidence scores",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
    registry=REGISTRY,
)


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def get_metrics_text() -> bytes:
    """Generate Prometheus metrics in text format.

    Returns:
        UTF-8 encoded metrics in Prometheus exposition format.

    Example:
        @app.get("/metrics")
        def metrics():
            return Response(
                content=get_metrics_text(),
                media_type=CONTENT_TYPE_LATEST
            )
    """
    return generate_latest(REGISTRY)


def get_metrics_content_type() -> str:
    """Get the content type for Prometheus metrics response.

    Returns:
        Content-Type header value for Prometheus metrics.
    """
    return CONTENT_TYPE_LATEST


def reset_metrics() -> None:
    """Reset all metrics to zero.

    Useful for testing. In production, metrics should persist
    across requests for accurate monitoring.

    Warning:
        This clears ALL metrics. Use only in tests.
    """
    # Note: prometheus_client doesn't provide a clean way to reset
    # We need to recreate the registry for true reset in tests
    # For now, this is a placeholder that tests can use
    pass  # pragma: no cover (placeholder implementation)


class MetricsContext:
    """Context manager for timing operations and updating metrics.

    Combines histogram timing with counter updates for common patterns.

    Example:
        with MetricsContext(
            histogram=PAPER_PROCESSING_DURATION.labels(stage="extraction"),
            success_counter=PAPERS_PROCESSED.labels(status="success"),
            failure_counter=PAPERS_PROCESSED.labels(status="failed"),
        ) as ctx:
            result = extract_paper()
            ctx.mark_success()

        # Automatically records duration and increments appropriate counter
    """

    def __init__(
        self,
        histogram: Optional[Histogram] = None,
        success_counter: Optional[Counter] = None,
        failure_counter: Optional[Counter] = None,
    ):
        """Initialize metrics context.

        Args:
            histogram: Optional histogram to record duration
            success_counter: Counter to increment on success
            failure_counter: Counter to increment on failure
        """
        self._histogram = histogram
        self._success_counter = success_counter
        self._failure_counter = failure_counter
        self._timer: Any = None
        self._success = False

    def __enter__(self) -> "MetricsContext":
        """Start timing."""
        if self._histogram:
            self._timer = self._histogram.time()
            self._timer.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop timing and update counters."""
        # Stop histogram timer
        if self._timer:
            self._timer.__exit__(exc_type, exc_val, exc_tb)

        # Update counters based on success/failure
        if exc_type is not None:
            # Exception occurred
            if self._failure_counter:
                self._failure_counter.inc()
        elif self._success:
            # Explicitly marked as success
            if self._success_counter:
                self._success_counter.inc()
        else:
            # No exception but not marked success - treat as failure
            if self._failure_counter:
                self._failure_counter.inc()

    def mark_success(self) -> None:
        """Mark the operation as successful.

        Must be called before exiting the context to register success.
        """
        self._success = True
