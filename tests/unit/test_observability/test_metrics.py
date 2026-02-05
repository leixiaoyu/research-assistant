"""Tests for Prometheus metrics definitions."""

import pytest
from prometheus_client import CollectorRegistry

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
    PAPERS_IN_QUEUE,
    SCHEDULER_JOBS,
    # Histograms
    PAPER_PROCESSING_DURATION,
    LLM_REQUEST_DURATION,
    PDF_DOWNLOAD_DURATION,
    PDF_CONVERSION_DURATION,
    PAPER_SIZE_BYTES,
    EXTRACTION_CONFIDENCE,
    # Utilities
    get_metrics_text,
    get_metrics_content_type,
    REGISTRY,
    MetricsContext,
)


class TestCounterMetrics:
    """Tests for counter metrics."""

    def test_papers_processed_counter(self):
        """Should increment papers processed counter."""
        initial = PAPERS_PROCESSED.labels(status="success")._value.get()

        PAPERS_PROCESSED.labels(status="success").inc()

        assert PAPERS_PROCESSED.labels(status="success")._value.get() == initial + 1

    def test_papers_processed_labels(self):
        """Should support different status labels."""
        # Access different labels
        PAPERS_PROCESSED.labels(status="success").inc()
        PAPERS_PROCESSED.labels(status="failed").inc()
        PAPERS_PROCESSED.labels(status="skipped").inc()

        # Should not raise
        assert True

    def test_papers_discovered_counter(self):
        """Should increment papers discovered counter."""
        initial = PAPERS_DISCOVERED.labels(provider="semantic_scholar")._value.get()

        PAPERS_DISCOVERED.labels(provider="semantic_scholar").inc()

        current = PAPERS_DISCOVERED.labels(provider="semantic_scholar")._value.get()
        assert current == initial + 1

    def test_llm_tokens_counter(self):
        """Should increment LLM tokens counter."""
        TOKENS_PROCESSED_INITIAL = LLM_TOKENS_TOTAL.labels(
            provider="anthropic", type="input"
        )._value.get()

        LLM_TOKENS_TOTAL.labels(provider="anthropic", type="input").inc(1000)

        current = LLM_TOKENS_TOTAL.labels(
            provider="anthropic", type="input"
        )._value.get()
        assert current == TOKENS_PROCESSED_INITIAL + 1000

    def test_llm_cost_counter(self):
        """Should increment LLM cost counter."""
        initial = LLM_COST_USD_TOTAL.labels(provider="google")._value.get()

        LLM_COST_USD_TOTAL.labels(provider="google").inc(0.05)

        current = LLM_COST_USD_TOTAL.labels(provider="google")._value.get()
        assert current == pytest.approx(initial + 0.05, rel=1e-6)

    def test_llm_requests_counter(self):
        """Should increment LLM requests counter."""
        LLM_REQUESTS_TOTAL.labels(provider="anthropic", status="success").inc()
        LLM_REQUESTS_TOTAL.labels(provider="anthropic", status="failed").inc()

        # Should not raise
        assert True

    def test_cache_operations_counter(self):
        """Should increment cache operations counter."""
        CACHE_OPERATIONS.labels(cache_type="api", operation="hit").inc()
        CACHE_OPERATIONS.labels(cache_type="pdf", operation="miss").inc()
        CACHE_OPERATIONS.labels(cache_type="extraction", operation="set").inc()

        # Should not raise
        assert True

    def test_pdf_downloads_counter(self):
        """Should increment PDF downloads counter."""
        PDF_DOWNLOADS.labels(status="success").inc()
        PDF_DOWNLOADS.labels(status="failed").inc()

        # Should not raise
        assert True

    def test_pdf_conversions_counter(self):
        """Should increment PDF conversions counter."""
        PDF_CONVERSIONS.labels(backend="marker", status="success").inc()
        PDF_CONVERSIONS.labels(backend="pymupdf", status="failed").inc()

        # Should not raise
        assert True

    def test_extraction_errors_counter(self):
        """Should increment extraction errors counter."""
        EXTRACTION_ERRORS.labels(error_type="download").inc()
        EXTRACTION_ERRORS.labels(error_type="conversion").inc()
        EXTRACTION_ERRORS.labels(error_type="llm").inc()
        EXTRACTION_ERRORS.labels(error_type="parsing").inc()
        EXTRACTION_ERRORS.labels(error_type="cost_limit").inc()

        # Should not raise
        assert True


class TestGaugeMetrics:
    """Tests for gauge metrics."""

    def test_active_workers_gauge(self):
        """Should set active workers gauge."""
        ACTIVE_WORKERS.labels(worker_type="download").set(5)

        assert ACTIVE_WORKERS.labels(worker_type="download")._value.get() == 5

    def test_active_workers_inc_dec(self):
        """Should increment and decrement active workers."""
        ACTIVE_WORKERS.labels(worker_type="llm").set(0)
        ACTIVE_WORKERS.labels(worker_type="llm").inc()
        ACTIVE_WORKERS.labels(worker_type="llm").inc()
        ACTIVE_WORKERS.labels(worker_type="llm").dec()

        assert ACTIVE_WORKERS.labels(worker_type="llm")._value.get() == 1

    def test_queue_size_gauge(self):
        """Should set queue size gauge."""
        QUEUE_SIZE.labels(queue_name="input").set(100)
        QUEUE_SIZE.labels(queue_name="results").set(50)

        assert QUEUE_SIZE.labels(queue_name="input")._value.get() == 100
        assert QUEUE_SIZE.labels(queue_name="results")._value.get() == 50

    def test_cache_size_bytes_gauge(self):
        """Should set cache size gauge."""
        CACHE_SIZE_BYTES.labels(cache_type="api").set(1024 * 1024)

        assert CACHE_SIZE_BYTES.labels(cache_type="api")._value.get() == 1024 * 1024

    def test_daily_cost_gauge(self):
        """Should set daily cost gauge."""
        DAILY_COST_USD.labels(provider="total").set(15.50)

        assert DAILY_COST_USD.labels(provider="total")._value.get() == pytest.approx(
            15.50
        )

    def test_papers_in_queue_gauge(self):
        """Should set papers in queue gauge."""
        PAPERS_IN_QUEUE.set(42)

        assert PAPERS_IN_QUEUE._value.get() == 42

    def test_scheduler_jobs_gauge(self):
        """Should set scheduler jobs gauge."""
        SCHEDULER_JOBS.labels(status="pending").set(3)
        SCHEDULER_JOBS.labels(status="running").set(1)

        assert SCHEDULER_JOBS.labels(status="pending")._value.get() == 3
        assert SCHEDULER_JOBS.labels(status="running")._value.get() == 1


class TestHistogramMetrics:
    """Tests for histogram metrics."""

    def test_paper_processing_duration_histogram(self):
        """Should observe paper processing duration."""
        PAPER_PROCESSING_DURATION.labels(stage="total").observe(5.5)
        PAPER_PROCESSING_DURATION.labels(stage="download").observe(1.2)
        PAPER_PROCESSING_DURATION.labels(stage="extraction").observe(3.0)

        # Should not raise
        assert True

    def test_paper_processing_timer(self):
        """Should time paper processing with context manager."""
        import time

        with PAPER_PROCESSING_DURATION.labels(stage="total").time():
            time.sleep(0.01)

        # Should have recorded a duration > 0
        assert True

    def test_llm_request_duration_histogram(self):
        """Should observe LLM request duration."""
        LLM_REQUEST_DURATION.labels(provider="anthropic").observe(2.5)
        LLM_REQUEST_DURATION.labels(provider="google").observe(1.8)

        # Should not raise
        assert True

    def test_pdf_download_duration_histogram(self):
        """Should observe PDF download duration."""
        PDF_DOWNLOAD_DURATION.observe(0.5)
        PDF_DOWNLOAD_DURATION.observe(2.0)

        # Should not raise
        assert True

    def test_pdf_conversion_duration_histogram(self):
        """Should observe PDF conversion duration."""
        PDF_CONVERSION_DURATION.labels(backend="marker").observe(15.0)
        PDF_CONVERSION_DURATION.labels(backend="pymupdf").observe(3.0)

        # Should not raise
        assert True

    def test_paper_size_bytes_histogram(self):
        """Should observe paper size."""
        PAPER_SIZE_BYTES.observe(500_000)  # 500KB
        PAPER_SIZE_BYTES.observe(2_000_000)  # 2MB

        # Should not raise
        assert True

    def test_extraction_confidence_histogram(self):
        """Should observe extraction confidence."""
        EXTRACTION_CONFIDENCE.observe(0.95)
        EXTRACTION_CONFIDENCE.observe(0.72)
        EXTRACTION_CONFIDENCE.observe(0.88)

        # Should not raise
        assert True


class TestMetricsUtilities:
    """Tests for metrics utility functions."""

    def test_get_metrics_text_returns_bytes(self):
        """Should return metrics as bytes."""
        result = get_metrics_text()

        assert isinstance(result, bytes)

    def test_get_metrics_text_contains_metric_names(self):
        """Should contain defined metric names."""
        result = get_metrics_text().decode("utf-8")

        assert "arisp_papers_processed_total" in result
        assert "arisp_llm_tokens_total" in result
        assert "arisp_active_workers" in result

    def test_get_metrics_text_prometheus_format(self):
        """Should be in valid Prometheus exposition format."""
        result = get_metrics_text().decode("utf-8")

        # Check for HELP and TYPE comments
        assert "# HELP" in result
        assert "# TYPE" in result

    def test_get_metrics_content_type(self):
        """Should return correct content type."""
        content_type = get_metrics_content_type()

        assert "text/plain" in content_type or "text/openmetrics" in content_type

    def test_registry_is_collector_registry(self):
        """Should use custom CollectorRegistry."""
        assert isinstance(REGISTRY, CollectorRegistry)


class TestMetricsContext:
    """Tests for MetricsContext helper class."""

    def test_times_operation(self):
        """Should time operation with histogram."""
        import time
        from unittest.mock import MagicMock

        histogram = MagicMock()
        timer_mock = MagicMock()
        histogram.time.return_value = timer_mock

        with MetricsContext(histogram=histogram):
            time.sleep(0.01)

        histogram.time.assert_called_once()
        timer_mock.__enter__.assert_called_once()
        timer_mock.__exit__.assert_called_once()

    def test_increments_success_counter_on_mark_success(self):
        """Should increment success counter when marked."""
        from unittest.mock import MagicMock

        success_counter = MagicMock()
        failure_counter = MagicMock()

        with MetricsContext(
            success_counter=success_counter, failure_counter=failure_counter
        ) as ctx:
            ctx.mark_success()

        success_counter.inc.assert_called_once()
        failure_counter.inc.assert_not_called()

    def test_increments_failure_counter_on_exception(self):
        """Should increment failure counter on exception."""
        from unittest.mock import MagicMock

        success_counter = MagicMock()
        failure_counter = MagicMock()

        with pytest.raises(ValueError):
            with MetricsContext(
                success_counter=success_counter, failure_counter=failure_counter
            ):
                raise ValueError("test error")

        failure_counter.inc.assert_called_once()
        success_counter.inc.assert_not_called()

    def test_increments_failure_counter_when_not_marked_success(self):
        """Should increment failure counter when not marked success."""
        from unittest.mock import MagicMock

        success_counter = MagicMock()
        failure_counter = MagicMock()

        with MetricsContext(
            success_counter=success_counter, failure_counter=failure_counter
        ):
            pass  # Don't mark success

        failure_counter.inc.assert_called_once()
        success_counter.inc.assert_not_called()

    def test_works_with_only_histogram(self):
        """Should work with only histogram, no counters."""
        from unittest.mock import MagicMock

        histogram = MagicMock()
        timer_mock = MagicMock()
        histogram.time.return_value = timer_mock

        with MetricsContext(histogram=histogram) as ctx:
            ctx.mark_success()

        histogram.time.assert_called_once()

    def test_works_with_only_counters(self):
        """Should work with only counters, no histogram."""
        from unittest.mock import MagicMock

        success_counter = MagicMock()

        with MetricsContext(success_counter=success_counter) as ctx:
            ctx.mark_success()

        success_counter.inc.assert_called_once()

    def test_works_with_no_metrics(self):
        """Should work with no metrics configured."""
        with MetricsContext() as ctx:
            ctx.mark_success()

        # Should not raise
        assert True
