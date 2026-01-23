# Phase 4: Production Hardening
**Version:** 1.0
**Status:** Draft
**Timeline:** 1 week
**Dependencies:** Phase 1, 2, 3 Complete

## Overview

Prepare ARISP for production deployment with comprehensive observability, monitoring, automated testing, scheduling, and operational tooling. This phase transforms the system from a functional prototype to a production-grade service.

## Objectives

### Primary Objectives
1. ✅ Implement structured logging with correlation IDs
2. ✅ Add Prometheus metrics for monitoring
3. ✅ Create comprehensive test suite (>80% coverage)
4. ✅ Implement scheduling system for automated runs
5. ✅ Build operational dashboards and alerts
6. ✅ Add health checks and diagnostics
7. ✅ Create deployment documentation

### Success Criteria
- [ ] All errors traceable via correlation IDs
- [ ] Key metrics exported to Prometheus
- [ ] Test coverage > 80%
- [ ] Automated daily runs working
- [ ] Monitoring dashboards operational
- [ ] Zero-downtime deployment process
- [ ] Comprehensive operational runbook

## Architecture Additions

### Updated Module Structure
```
research-assist/
├── src/
│   ├── observability/           # NEW: Observability
│   │   ├── __init__.py
│   │   ├── logging.py          # Structured logging
│   │   ├── metrics.py          # Prometheus metrics
│   │   └── tracing.py          # Correlation IDs
│   ├── scheduling/              # NEW: Scheduling
│   │   ├── __init__.py
│   │   └── scheduler.py
│   └── health/                  # NEW: Health checks
│       ├── __init__.py
│       └── checks.py
├── monitoring/                   # NEW: Monitoring config
│   ├── prometheus.yml
│   ├── grafana/
│   │   └── dashboards/
│   └── alerts/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/                     # NEW: End-to-end tests
│   └── load/                    # NEW: Load tests
├── deployment/                   # NEW: Deployment
│   ├── docker/
│   ├── systemd/
│   └── kubernetes/
└── docs/
    ├── operations/              # NEW: Operational docs
    │   ├── RUNBOOK.md
    │   ├── TROUBLESHOOTING.md
    │   └── MONITORING.md
    └── deployment/
        └── DEPLOYMENT.md
```

## Technical Specifications

### 1. Structured Logging (`src/observability/logging.py`)

**Design:** Use structlog for JSON-formatted logs with context

**Implementation:**
```python
import structlog
import logging
import sys
from contextvars import ContextVar
from typing import Optional
import uuid

# Context var for correlation ID
correlation_id_var: ContextVar[Optional[str]] = ContextVar(
    'correlation_id',
    default=None
)

def setup_logging(
    level: str = "INFO",
    json_format: bool = True
):
    """Configure structured logging"""

    # Pre-processors
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,
        add_service_context,
    ]

    if json_format:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

def add_correlation_id(logger, method_name, event_dict):
    """Add correlation ID to log context"""
    corr_id = correlation_id_var.get()
    if corr_id:
        event_dict['correlation_id'] = corr_id
    return event_dict

def add_service_context(logger, method_name, event_dict):
    """Add service metadata"""
    event_dict['service'] = 'arisp'
    event_dict['version'] = get_version()
    return event_dict

def set_correlation_id(corr_id: str = None):
    """Set correlation ID for current context"""
    if corr_id is None:
        corr_id = str(uuid.uuid4())
    correlation_id_var.set(corr_id)
    return corr_id

# Usage example
logger = structlog.get_logger()

# In main.py
async def run_pipeline(topic: ResearchTopic):
    # Generate correlation ID for this run
    run_id = set_correlation_id()

    logger.info(
        "pipeline_started",
        topic=topic.query,
        run_id=run_id,
        max_papers=topic.max_papers
    )

    try:
        # ... pipeline logic ...

        logger.info(
            "pipeline_completed",
            run_id=run_id,
            papers_processed=count,
            duration_seconds=elapsed
        )

    except Exception as e:
        logger.error(
            "pipeline_failed",
            run_id=run_id,
            error=str(e),
            exc_info=True
        )
        raise
```

**Log Format:**
```json
{
  "event": "paper_processed",
  "level": "info",
  "timestamp": "2025-01-23T14:30:52.123Z",
  "correlation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "service": "arisp",
  "version": "1.0.0",
  "paper_id": "abc123",
  "processing_time_ms": 45000,
  "pdf_available": true,
  "extraction_success": true
}
```

### 2. Prometheus Metrics (`src/observability/metrics.py`)

**Key Metrics:**
- Counter: Papers processed, API calls, errors
- Gauge: Queue size, cache size, active workers
- Histogram: Processing time, API latency, LLM tokens

**Implementation:**
```python
from prometheus_client import (
    Counter, Gauge, Histogram, Summary,
    start_http_server, REGISTRY
)

# Counters
papers_processed = Counter(
    'arisp_papers_processed_total',
    'Total papers processed',
    ['status']  # success, failed, skipped
)

api_calls = Counter(
    'arisp_api_calls_total',
    'Total API calls',
    ['api', 'status']  # semantic_scholar/llm, success/error
)

llm_tokens = Counter(
    'arisp_llm_tokens_total',
    'Total LLM tokens used',
    ['provider', 'type']  # anthropic/google, input/output
)

llm_cost = Counter(
    'arisp_llm_cost_usd_total',
    'Total LLM cost in USD',
    ['provider']
)

# Gauges
active_workers = Gauge(
    'arisp_active_workers',
    'Number of active worker coroutines',
    ['type']  # download, conversion, llm
)

queue_size = Gauge(
    'arisp_queue_size',
    'Current queue size',
    ['queue']  # papers, results
)

cache_size = Gauge(
    'arisp_cache_size_bytes',
    'Cache size in bytes',
    ['cache_type']  # api, pdf, extraction
)

# Histograms
paper_processing_duration = Histogram(
    'arisp_paper_processing_duration_seconds',
    'Time to process a single paper',
    buckets=[10, 30, 60, 120, 300, 600]
)

pdf_download_duration = Histogram(
    'arisp_pdf_download_duration_seconds',
    'PDF download time',
    buckets=[1, 5, 10, 30, 60, 120]
)

llm_extraction_duration = Histogram(
    'arisp_llm_extraction_duration_seconds',
    'LLM extraction time',
    buckets=[10, 30, 60, 120, 300]
)

# Summary for latency percentiles
api_latency = Summary(
    'arisp_api_latency_seconds',
    'API request latency',
    ['api']
)

class MetricsMiddleware:
    """Decorator for automatic metrics collection"""

    @staticmethod
    def track_processing(func):
        """Track paper processing metrics"""
        async def wrapper(*args, **kwargs):
            with paper_processing_duration.time():
                try:
                    result = await func(*args, **kwargs)
                    papers_processed.labels(status='success').inc()
                    return result
                except Exception as e:
                    papers_processed.labels(status='failed').inc()
                    raise
        return wrapper

    @staticmethod
    def track_api_call(api_name: str):
        """Track API call metrics"""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                with api_latency.labels(api=api_name).time():
                    try:
                        result = await func(*args, **kwargs)
                        api_calls.labels(
                            api=api_name,
                            status='success'
                        ).inc()
                        return result
                    except Exception as e:
                        api_calls.labels(
                            api=api_name,
                            status='error'
                        ).inc()
                        raise
            return wrapper
        return decorator

# Start metrics server
def start_metrics_server(port: int = 9090):
    """Start Prometheus metrics HTTP server"""
    start_http_server(port)
    logger.info("metrics_server_started", port=port)
```

**Usage:**
```python
# In services
@MetricsMiddleware.track_processing
async def process_paper(paper: PaperMetadata) -> ExtractedPaper:
    ...

@MetricsMiddleware.track_api_call('semantic_scholar')
async def search_papers(query: str) -> List[PaperMetadata]:
    ...

# Manual tracking
llm_tokens.labels(
    provider='anthropic',
    type='input'
).inc(response.usage.input_tokens)

llm_cost.labels(provider='anthropic').inc(calculated_cost)
```

### 3. Scheduling System (`src/scheduling/scheduler.py`)

**Options:**
- **APScheduler** (in-process)
- **Cron/systemd timers** (system-level)
- **Cloud schedulers** (AWS EventBridge, Cloud Scheduler)

**Implementation (APScheduler):**
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import List

class ResearchScheduler:
    """Schedule automated research runs"""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.scheduler = AsyncIOScheduler()

    def start(self):
        """Start the scheduler"""

        # Daily at 2 AM
        self.scheduler.add_job(
            self.run_daily_research,
            CronTrigger(hour=2, minute=0),
            id='daily_research',
            name='Daily Research Pipeline'
        )

        # Cache cleanup weekly
        self.scheduler.add_job(
            self.cleanup_cache,
            CronTrigger(day_of_week='sun', hour=3, minute=0),
            id='cache_cleanup',
            name='Weekly Cache Cleanup'
        )

        # Cost report daily
        self.scheduler.add_job(
            self.generate_cost_report,
            CronTrigger(hour=23, minute=55),
            id='cost_report',
            name='Daily Cost Report'
        )

        self.scheduler.start()
        logger.info("scheduler_started")

    async def run_daily_research(self):
        """Run research pipeline for all configured topics"""
        run_id = set_correlation_id()

        logger.info("scheduled_run_started", run_id=run_id)

        try:
            config = ConfigManager(self.config_path).load_config()

            for topic in config.research_topics:
                await run_pipeline_for_topic(topic)

            logger.info("scheduled_run_completed", run_id=run_id)

        except Exception as e:
            logger.error(
                "scheduled_run_failed",
                run_id=run_id,
                error=str(e),
                exc_info=True
            )
            # Send alert
            await send_alert(f"Scheduled run failed: {e}")

    async def cleanup_cache(self):
        """Cleanup old cache entries"""
        logger.info("cache_cleanup_started")
        # Implement cache cleanup logic
        logger.info("cache_cleanup_completed")

    async def generate_cost_report(self):
        """Generate daily cost report"""
        # Query metrics, generate report
        logger.info("cost_report_generated")
```

### 4. Health Checks (`src/health/checks.py`)

**Health Check Endpoint:** For monitoring and orchestration

**Implementation:**
```python
from fastapi import FastAPI, Response
from pydantic import BaseModel
from typing import Dict, Literal
import aiohttp

app = FastAPI()

class HealthStatus(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    checks: Dict[str, bool]
    message: str = ""

class HealthChecker:
    """Perform system health checks"""

    async def check_all(self) -> HealthStatus:
        """Run all health checks"""

        checks = {
            "api_connectivity": await self.check_api_connectivity(),
            "disk_space": await self.check_disk_space(),
            "cache_accessible": await self.check_cache(),
            "llm_available": await self.check_llm_api(),
        }

        all_healthy = all(checks.values())
        any_unhealthy = not any(checks.values())

        if all_healthy:
            status = "healthy"
        elif any_unhealthy:
            status = "unhealthy"
        else:
            status = "degraded"

        return HealthStatus(
            status=status,
            version=get_version(),
            checks=checks
        )

    async def check_api_connectivity(self) -> bool:
        """Check Semantic Scholar API reachable"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    params={"query": "test"},
                    timeout=5
                ) as resp:
                    return resp.status in (200, 400)  # 400 is ok (bad query)
        except:
            return False

    async def check_disk_space(self) -> bool:
        """Check sufficient disk space"""
        import shutil
        stat = shutil.disk_usage(".")
        free_gb = stat.free / (1024**3)
        return free_gb > 10  # At least 10GB free

    async def check_cache(self) -> bool:
        """Check cache accessible"""
        try:
            cache_service = get_cache_service()
            cache_service.get_stats()
            return True
        except:
            return False

    async def check_llm_api(self) -> bool:
        """Check LLM API available"""
        # Implement LLM API ping
        return True

@app.get("/health")
async def health():
    """Health check endpoint"""
    checker = HealthChecker()
    health_status = await checker.check_all()

    status_code = {
        "healthy": 200,
        "degraded": 200,
        "unhealthy": 503
    }[health_status.status]

    return Response(
        content=health_status.json(),
        status_code=status_code,
        media_type="application/json"
    )

@app.get("/ready")
async def readiness():
    """Kubernetes readiness probe"""
    # Check if system is ready to accept work
    return {"ready": True}

@app.get("/live")
async def liveness():
    """Kubernetes liveness probe"""
    # Check if system is alive (always return 200 unless deadlocked)
    return {"alive": True}
```

### 5. Comprehensive Testing

**Test Structure:**
```
tests/
├── unit/                       # Fast, isolated tests
│   ├── test_models.py
│   ├── test_config.py
│   ├── test_slug_generation.py
│   └── ...
├── integration/                # Component integration
│   ├── test_search_service.py
│   ├── test_pdf_pipeline.py
│   └── ...
├── e2e/                        # End-to-end scenarios
│   ├── test_full_pipeline.py
│   └── test_scheduled_run.py
└── load/                       # Performance tests
    └── test_concurrent_load.py
```

**Coverage Configuration:**
```ini
# pytest.ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

addopts =
    --cov=src
    --cov-report=html
    --cov-report=term
    --cov-fail-under=80
    --asyncio-mode=auto

# .coveragerc
[run]
source = src
omit =
    */tests/*
    */venv/*
    */__pycache__/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
```

**E2E Test Example:**
```python
# tests/e2e/test_full_pipeline.py
import pytest

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_complete_research_pipeline(tmp_path):
    """Test full pipeline from config to output"""

    # Setup
    config_file = tmp_path / "config.yaml"
    config_file.write_text("""
research_topics:
  - query: "test query"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 5
    extraction_targets:
      - name: "summary"
        description: "Extract summary"
        output_format: "text"

settings:
  output_base_dir: "./test_output"
  semantic_scholar_api_key: "${TEST_API_KEY}"
  llm_settings:
    provider: "anthropic"
    api_key: "${TEST_LLM_KEY}"
""")

    # Execute
    result = await run_pipeline(str(config_file))

    # Assert
    assert result.success is True
    assert result.papers_processed > 0
    assert (tmp_path / "test_output").exists()

    # Verify output structure
    output_files = list((tmp_path / "test_output").rglob("*.md"))
    assert len(output_files) > 0

    # Verify catalog
    catalog_file = tmp_path / "test_output" / "catalog.json"
    assert catalog_file.exists()

    # Verify metrics
    assert papers_processed.labels(status='success')._value.get() > 0
```

### 6. Monitoring Dashboards

**Grafana Dashboard (JSON):**
```json
{
  "dashboard": {
    "title": "ARISP Pipeline Monitoring",
    "panels": [
      {
        "title": "Papers Processed",
        "targets": [
          {
            "expr": "rate(arisp_papers_processed_total[5m])"
          }
        ]
      },
      {
        "title": "LLM Cost",
        "targets": [
          {
            "expr": "increase(arisp_llm_cost_usd_total[1d])"
          }
        ]
      },
      {
        "title": "Processing Duration",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, arisp_paper_processing_duration_seconds)"
          }
        ]
      },
      {
        "title": "Cache Hit Rate",
        "targets": [
          {
            "expr": "arisp_cache_hits / (arisp_cache_hits + arisp_cache_misses)"
          }
        ]
      }
    ]
  }
}
```

**Alerts (Prometheus rules):**
```yaml
# monitoring/alerts/arisp_alerts.yml
groups:
  - name: arisp
    interval: 30s
    rules:
      - alert: HighErrorRate
        expr: |
          rate(arisp_papers_processed_total{status="failed"}[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High error rate in paper processing"
          description: "{{ $value }}% of papers failing"

      - alert: DailyCostExceeded
        expr: |
          increase(arisp_llm_cost_usd_total[1d]) > 50
        labels:
          severity: critical
        annotations:
          summary: "Daily LLM cost limit exceeded"
          description: "Cost: ${{ $value }}"

      - alert: DiskSpaceLow
        expr: |
          arisp_cache_size_bytes > 10 * 1024 * 1024 * 1024
        labels:
          severity: warning
        annotations:
          summary: "Cache size exceeds 10GB"
```

## Deployment

### Docker Deployment
```dockerfile
# deployment/docker/Dockerfile
FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    marker-pdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/
COPY config/ ./config/

# Create directories
RUN mkdir -p /app/output /app/cache /app/checkpoints /app/temp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s \
  CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["python", "-m", "src.cli", "schedule"]
```

### Systemd Service
```ini
# deployment/systemd/arisp.service
[Unit]
Description=ARISP Research Pipeline
After=network.target

[Service]
Type=simple
User=arisp
WorkingDirectory=/opt/arisp
Environment="PATH=/opt/arisp/venv/bin"
ExecStart=/opt/arisp/venv/bin/python -m src.cli schedule
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=arisp

[Install]
WantedBy=multi-user.target
```

## Operational Documentation

### Runbook (docs/operations/RUNBOOK.md)
```markdown
# ARISP Operational Runbook

## Starting the Service

```bash
# Start scheduler
python -m src.cli schedule

# Or with systemd
sudo systemctl start arisp
```

## Monitoring

- **Grafana:** http://localhost:3000
- **Prometheus:** http://localhost:9090
- **Health:** http://localhost:8000/health

## Common Operations

### Manual Run
```bash
python -m src.cli run --config research_config.yaml
```

### View Catalog
```bash
python -m src.cli catalog show
```

### Clear Cache
```bash
python -m src.cli cache clear --type all
```

## Troubleshooting

### High Error Rate
1. Check logs: `journalctl -u arisp -f`
2. Check health: `curl localhost:8000/health`
3. Verify API keys in .env
4. Check disk space

### Cost Exceeded
1. Review cost report: `python -m src.cli cost report`
2. Adjust limits in config
3. Review filters to reduce papers
```

## Acceptance Criteria

### Observability
- [ ] Structured JSON logs with correlation IDs
- [ ] All key metrics exported to Prometheus
- [ ] Grafana dashboards configured
- [ ] Alerts configured and tested
- [ ] Health check endpoint working

### Testing
- [ ] Unit test coverage > 80%
- [ ] Integration tests pass
- [ ] E2E test passes
- [ ] Load test validates performance

### Operations
- [ ] Scheduled runs working automatically
- [ ] Deployment scripts tested
- [ ] Runbook complete
- [ ] Troubleshooting guide complete
- [ ] Monitoring dashboards functional

## Deliverables

1. ✅ Structured logging implementation
2. ✅ Prometheus metrics
3. ✅ Comprehensive test suite (>80% coverage)
4. ✅ Scheduling system
5. ✅ Health check endpoints
6. ✅ Grafana dashboards
7. ✅ Alert rules
8. ✅ Deployment configurations
9. ✅ Operational documentation
10. ✅ Troubleshooting guide

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Logging overhead | LOW | Async logging, sampling |
| Metrics memory usage | LOW | Proper label cardinality |
| Alert fatigue | MEDIUM | Tune thresholds carefully |
| Deployment failures | MEDIUM | Canary deployments, rollback |

## Sign-off

- [ ] Product Owner Approval
- [ ] Technical Lead Approval
- [ ] Operations Team Approval
- [ ] Security Review Complete
- [ ] Ready for Production
