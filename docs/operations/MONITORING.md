# ARISP Monitoring Guide

This guide covers monitoring setup, metrics interpretation, alerting configuration, and best practices for observing the ARISP pipeline in production.

## Table of Contents

1. [Monitoring Architecture](#monitoring-architecture)
2. [Metrics Reference](#metrics-reference)
3. [Grafana Dashboards](#grafana-dashboards)
4. [Alerting](#alerting)
5. [Log Analysis](#log-analysis)
6. [Best Practices](#best-practices)

---

## Monitoring Architecture

### Components

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  ARISP Pipeline │────▶│   Prometheus    │────▶│    Grafana      │
│   :8000/metrics │     │     :9090       │     │     :3000       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
         │                       │
         │                       ▼
         │              ┌─────────────────┐
         │              │  Alertmanager   │
         │              │     :9093       │
         │              └─────────────────┘
         │
         ▼
┌─────────────────┐
│  Structured     │
│  Logs (JSON)    │
└─────────────────┘
```

### Endpoints

| Service | Endpoint | Purpose |
|---------|----------|---------|
| ARISP | `http://localhost:8000/metrics` | Prometheus metrics |
| ARISP | `http://localhost:8000/health` | Health status JSON |
| Prometheus | `http://localhost:9090` | Metrics UI and API |
| Grafana | `http://localhost:3000` | Dashboards |

---

## Metrics Reference

### Counters (Monotonically Increasing)

#### Paper Processing

| Metric | Labels | Description |
|--------|--------|-------------|
| `arisp_papers_processed_total` | `status` | Total papers processed |
| `arisp_papers_discovered_total` | `provider` | Papers found from APIs |

**Status labels:** `success`, `failed`, `skipped`
**Provider labels:** `semantic_scholar`, `arxiv`

**Example queries:**
```promql
# Processing rate (papers/minute)
rate(arisp_papers_processed_total[5m]) * 60

# Error rate
sum(rate(arisp_papers_processed_total{status="failed"}[5m]))
/ sum(rate(arisp_papers_processed_total[5m]))

# Total successful papers today
increase(arisp_papers_processed_total{status="success"}[24h])
```

#### LLM Usage

| Metric | Labels | Description |
|--------|--------|-------------|
| `arisp_llm_tokens_total` | `provider`, `type` | Tokens used |
| `arisp_llm_cost_usd_total` | `provider` | Cumulative cost |
| `arisp_llm_requests_total` | `provider`, `status` | API requests |

**Example queries:**
```promql
# Token rate (tokens/minute)
rate(arisp_llm_tokens_total[5m]) * 60

# Cost per hour
rate(arisp_llm_cost_usd_total[1h]) * 3600

# LLM success rate
sum(rate(arisp_llm_requests_total{status="success"}[5m]))
/ sum(rate(arisp_llm_requests_total[5m]))
```

#### Cache Operations

| Metric | Labels | Description |
|--------|--------|-------------|
| `arisp_cache_operations_total` | `cache_type`, `operation` | Cache operations |

**Cache types:** `api`, `pdf`, `extraction`
**Operations:** `hit`, `miss`, `set`

**Example queries:**
```promql
# Cache hit rate
sum(rate(arisp_cache_operations_total{operation="hit"}[5m]))
/ sum(rate(arisp_cache_operations_total{operation=~"hit|miss"}[5m]))

# Cache efficiency by type
sum by (cache_type) (rate(arisp_cache_operations_total{operation="hit"}[5m]))
/ sum by (cache_type) (rate(arisp_cache_operations_total{operation=~"hit|miss"}[5m]))
```

#### PDF Processing

| Metric | Labels | Description |
|--------|--------|-------------|
| `arisp_pdf_downloads_total` | `status` | Download attempts |
| `arisp_pdf_conversions_total` | `backend`, `status` | Conversions |

**Example queries:**
```promql
# PDF download success rate
arisp_pdf_downloads_total{status="success"}
/ (arisp_pdf_downloads_total{status="success"} + arisp_pdf_downloads_total{status="failed"})

# Conversions by backend
sum by (backend) (rate(arisp_pdf_conversions_total{status="success"}[1h]))
```

#### Errors

| Metric | Labels | Description |
|--------|--------|-------------|
| `arisp_extraction_errors_total` | `error_type` | Extraction errors |

**Error types:** `download`, `conversion`, `llm`, `parsing`, `cost_limit`

### Gauges (Current Values)

| Metric | Labels | Description |
|--------|--------|-------------|
| `arisp_active_workers` | `worker_type` | Active workers |
| `arisp_queue_size` | `queue_name` | Current queue depth |
| `arisp_cache_size_bytes` | `cache_type` | Cache disk usage |
| `arisp_daily_cost_usd` | `provider` | Today's accumulated cost |
| `arisp_papers_in_queue` | - | Papers waiting to process |
| `arisp_scheduler_jobs` | `status` | Scheduled job count |

**Example queries:**
```promql
# Available worker capacity
5 - arisp_active_workers{worker_type="pipeline"}

# Cache size in GB
arisp_cache_size_bytes / 1024 / 1024 / 1024

# Remaining daily budget
50 - arisp_daily_cost_usd{provider="total"}
```

### Histograms (Distributions)

| Metric | Labels | Buckets | Description |
|--------|--------|---------|-------------|
| `arisp_paper_processing_duration_seconds` | `stage` | 0.1-300s | Processing time |
| `arisp_llm_request_duration_seconds` | `provider` | 0.5-120s | LLM latency |
| `arisp_pdf_download_duration_seconds` | - | 0.1-60s | Download time |
| `arisp_pdf_conversion_duration_seconds` | `backend` | 1-300s | Conversion time |
| `arisp_extraction_confidence` | - | 0.1-1.0 | Confidence scores |

**Example queries:**
```promql
# 95th percentile processing time
histogram_quantile(0.95,
  rate(arisp_paper_processing_duration_seconds_bucket{stage="total"}[5m])
)

# Median LLM latency
histogram_quantile(0.50,
  rate(arisp_llm_request_duration_seconds_bucket[5m])
)

# Average confidence score
rate(arisp_extraction_confidence_sum[5m])
/ rate(arisp_extraction_confidence_count[5m])
```

---

## Grafana Dashboards

### Accessing Grafana

1. Navigate to `http://localhost:3000`
2. Default credentials: `admin` / `admin`
3. Find dashboards under **Dashboards** → **Browse**

### ARISP Pipeline Dashboard

The main dashboard includes panels for:

#### Overview Row
- **Papers Processed**: Total successful papers
- **Daily LLM Cost**: Current day's spending
- **Success Rate**: Processing success percentage
- **Active Workers**: Current worker count

#### Processing Metrics Row
- **Paper Processing Rate**: Success/failed/skipped over time
- **Processing Duration**: p50/p90/p99 latencies

#### LLM Usage Row
- **Token Usage Rate**: Input/output tokens by provider
- **LLM Cost**: Cost accumulation over time

#### Cache Performance Row
- **Cache Hit/Miss Rate**: Operations by cache type
- **Cache Size**: Disk usage per cache tier
- **Overall Cache Hit Rate**: Aggregate efficiency

### Creating Custom Dashboards

1. Click **+** → **Dashboard**
2. Add panel with **+ Add visualization**
3. Select **Prometheus** data source
4. Enter PromQL query
5. Configure visualization options
6. Save dashboard

### Useful Panel Examples

**Cost Budget Gauge:**
```promql
Query: arisp_daily_cost_usd{provider="total"}
Thresholds: 40 (yellow), 48 (red)
Max: 50
```

**Processing Throughput:**
```promql
Query: sum(rate(arisp_papers_processed_total{status="success"}[5m])) * 60
Title: Papers/minute
```

---

## Alerting

### Alert Rules

Alert rules are defined in `monitoring/alerts/arisp_alerts.yml`.

### Key Alerts

| Alert | Threshold | Severity | Description |
|-------|-----------|----------|-------------|
| HighPaperProcessingErrorRate | >10% for 5m | Warning | Elevated failures |
| CriticalPaperProcessingErrorRate | >25% for 2m | Critical | Critical failures |
| DailyCostThresholdWarning | >$40 | Warning | Approaching budget |
| DailyCostThresholdCritical | >$48 | Critical | Near budget limit |
| DiskSpaceLow | <10% | Warning | Low disk space |
| NoWorkersActive | 0 for 1h | Warning | No processing |

### Configuring Alertmanager

1. Edit `alertmanager.yml`:
```yaml
route:
  receiver: 'team-email'

receivers:
  - name: 'team-email'
    email_configs:
      - to: 'team@example.com'
        from: 'alerts@example.com'
        smarthost: 'smtp.example.com:587'
```

2. Restart Alertmanager:
```bash
docker-compose restart alertmanager
```

### Silencing Alerts

During maintenance:
1. Go to Alertmanager UI (`http://localhost:9093`)
2. Click **Silences** → **New Silence**
3. Set matcher (e.g., `alertname="HighPaperProcessingErrorRate"`)
4. Set duration and comment
5. Click **Create**

---

## Log Analysis

### Log Format

ARISP uses structured JSON logging:

```json
{
  "event": "paper_processed",
  "timestamp": "2025-01-23T12:00:00.000000Z",
  "level": "info",
  "correlation_id": "abc123",
  "component": "extraction_service",
  "paper_id": "12345",
  "duration_ms": 1234.5
}
```

### Key Log Events

| Event | Level | Description |
|-------|-------|-------------|
| `pipeline_started` | info | Run initiated |
| `paper_processed` | info | Single paper complete |
| `extraction_completed` | info | LLM extraction done |
| `extraction_failed` | error | Extraction error |
| `cost_limit_exceeded` | warning | Budget exhausted |
| `job_executed` | info | Scheduled job ran |
| `job_failed` | error | Scheduled job error |

### Log Queries

**Find errors:**
```bash
docker-compose logs arisp | grep '"level":"error"'
```

**Filter by correlation ID:**
```bash
docker-compose logs arisp | grep '"correlation_id":"abc123"'
```

**Count events by type:**
```bash
docker-compose logs arisp | jq -r '.event' | sort | uniq -c | sort -rn
```

### Log Aggregation

For production, consider:
- **Loki**: Grafana's log aggregation
- **ELK Stack**: Elasticsearch, Logstash, Kibana
- **Datadog**: Managed monitoring

---

## Best Practices

### 1. Set Up Alerts Early

Configure alerts before issues occur:
- Error rate alerts
- Cost threshold alerts
- Disk space alerts
- Service availability alerts

### 2. Monitor Trends

Watch for:
- Increasing error rates
- Decreasing cache hit rates
- Growing processing times
- Cost trajectory

### 3. Review Dashboards Daily

Quick daily checks:
- Papers processed count
- Current daily cost
- Any active alerts
- Queue depth

### 4. Correlate Metrics with Events

When investigating issues:
1. Note the timestamp
2. Check relevant metrics
3. Review logs with correlation ID
4. Check external dependencies

### 5. Capacity Planning

Use metrics for planning:
```promql
# Average daily papers
avg_over_time(increase(arisp_papers_processed_total[24h])[7d:1d])

# Average daily cost
avg_over_time(arisp_daily_cost_usd{provider="total"}[7d:1d])

# Peak processing rate
max_over_time(rate(arisp_papers_processed_total[5m])[7d])
```

### 6. Document Thresholds

Maintain a record of:
- Alert thresholds and rationale
- Normal operating ranges
- Capacity limits
- Budget allocations

### 7. Test Alerting

Periodically verify:
- Alert rules fire correctly
- Notifications reach team
- Runbooks are current
- Escalation paths work

---

## Quick Reference

### Health Check
```bash
curl -s http://localhost:8000/health | jq '.status'
```

### Current Error Rate
```bash
curl -s http://localhost:8000/metrics | grep 'arisp_papers_processed_total'
```

### Daily Cost
```bash
curl -s http://localhost:8000/metrics | grep 'arisp_daily_cost_usd'
```

### Active Workers
```bash
curl -s http://localhost:8000/metrics | grep 'arisp_active_workers'
```

### Cache Hit Rate
```bash
curl -s http://localhost:8000/metrics | grep 'arisp_cache_operations_total'
```
