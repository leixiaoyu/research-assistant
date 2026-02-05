# ARISP Operations Runbook

This document provides operational procedures for maintaining and operating the ARISP (Automated Research Ingestion & Synthesis Pipeline) in production.

## Table of Contents

1. [Service Overview](#service-overview)
2. [Starting and Stopping](#starting-and-stopping)
3. [Health Checks](#health-checks)
4. [Scheduled Jobs](#scheduled-jobs)
5. [Common Operations](#common-operations)
6. [Monitoring](#monitoring)
7. [Incident Response](#incident-response)
8. [Maintenance Procedures](#maintenance-procedures)

---

## Service Overview

### Components

| Component | Port | Purpose |
|-----------|------|---------|
| ARISP Scheduler | 8000 | Main application with health endpoints |
| Health API | 8000 | `/health`, `/ready`, `/live`, `/metrics` |
| Prometheus | 9090 | Metrics collection |
| Grafana | 3000 | Dashboards and visualization |

### Service Dependencies

- **External APIs**: Semantic Scholar, ArXiv
- **LLM Providers**: Anthropic Claude, Google Gemini
- **Storage**: Local disk for cache and output

---

## Starting and Stopping

### Docker Compose (Recommended)

```bash
# Start all services
cd deployment
docker-compose up -d

# View logs
docker-compose logs -f arisp

# Stop all services
docker-compose down

# Restart ARISP only
docker-compose restart arisp
```

### Systemd (Linux Server)

```bash
# Start service
sudo systemctl start arisp

# Stop service
sudo systemctl stop arisp

# Restart service
sudo systemctl restart arisp

# View status
sudo systemctl status arisp

# View logs
sudo journalctl -u arisp -f
```

### CLI (Development)

```bash
# Start scheduler with default settings
python -m src.cli schedule

# Custom schedule (8:30 AM)
python -m src.cli schedule --hour 8 --minute 30

# Custom health port
python -m src.cli schedule --health-port 9000

# Standalone health server
python -m src.cli health --port 8000
```

---

## Health Checks

### Endpoints

| Endpoint | Purpose | Expected Response |
|----------|---------|-------------------|
| `/health` | Full health check | 200 (healthy/degraded), 503 (unhealthy) |
| `/ready` | Readiness probe | 200 (ready), 503 (not ready) |
| `/live` | Liveness probe | 200 (always) |
| `/metrics` | Prometheus metrics | Prometheus format text |

### Manual Health Check

```bash
# Full health check
curl -s http://localhost:8000/health | jq

# Readiness
curl -s http://localhost:8000/ready | jq

# Liveness
curl -s http://localhost:8000/live | jq

# Prometheus metrics
curl -s http://localhost:8000/metrics
```

### Expected Healthy Response

```json
{
  "status": "healthy",
  "checks": [
    {"name": "disk_space", "status": "pass", "message": "Disk space OK: 50.2GB free"},
    {"name": "cache_directory", "status": "pass", "message": "Cache directory accessible"},
    {"name": "output_directory", "status": "pass", "message": "Output directory accessible"},
    {"name": "semantic_scholar_api", "status": "pass", "message": "API reachable"},
    {"name": "arxiv_api", "status": "pass", "message": "API reachable"}
  ],
  "timestamp": "2025-01-23T12:00:00.000000"
}
```

---

## Scheduled Jobs

### Default Schedule

| Job | Schedule | Purpose |
|-----|----------|---------|
| `daily_research` | 06:00 UTC | Run research pipeline |
| `cache_cleanup` | Every 4 hours | Clean expired cache entries |
| `cost_report` | 23:00 UTC | Generate daily cost report |

### Viewing Scheduled Jobs

```bash
# Check scheduler logs
docker-compose logs arisp | grep "job_"

# Or via systemd
journalctl -u arisp | grep "job_"
```

### Manual Job Execution

To manually trigger a research run:

```bash
# Run pipeline directly
python -m src.cli run --config config/research_config.yaml

# Dry run (validation only)
python -m src.cli run --dry-run
```

---

## Common Operations

### View Configuration

```bash
# Validate configuration
python -m src.cli validate config/research_config.yaml

# View catalog
python -m src.cli catalog show

# View topic history
python -m src.cli catalog history --topic "topic-slug"
```

### Cache Management

```bash
# View cache statistics
curl -s http://localhost:8000/metrics | grep arisp_cache

# Clear cache (requires restart)
rm -rf .cache/*
docker-compose restart arisp
```

### Output Management

```bash
# List output files
ls -la output/*/

# View latest research brief
cat output/*/$(ls -t output/*/ | head -1)
```

---

## Monitoring

### Key Metrics to Watch

| Metric | Alert Threshold | Description |
|--------|-----------------|-------------|
| `arisp_papers_processed_total{status="failed"}` | >10% rate | Paper processing failures |
| `arisp_daily_cost_usd` | >$40 | Daily LLM cost |
| `arisp_cache_size_bytes` | >10GB | Cache size |
| `arisp_active_workers` | 0 for >1h | No active workers |

### Prometheus Queries

```promql
# Error rate over last 5 minutes
sum(rate(arisp_papers_processed_total{status="failed"}[5m]))
/ sum(rate(arisp_papers_processed_total[5m]))

# Daily cost
arisp_daily_cost_usd{provider="total"}

# Cache hit rate
sum(arisp_cache_operations_total{operation="hit"})
/ sum(arisp_cache_operations_total{operation=~"hit|miss"})
```

### Grafana Dashboards

Access Grafana at `http://localhost:3000` (default: admin/admin)

Available dashboards:
- **ARISP Pipeline Dashboard**: Overview of pipeline health and metrics

---

## Incident Response

### High Error Rate

1. Check health endpoint: `curl http://localhost:8000/health`
2. Review recent logs: `docker-compose logs --tail=100 arisp`
3. Check external API status:
   - Semantic Scholar: https://status.semanticscholar.org/
   - ArXiv: https://status.arxiv.org/
4. Verify API keys are valid
5. If issue persists, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

### Cost Limit Exceeded

1. Review daily costs in Grafana or metrics
2. Check for unusual token consumption
3. Pause scheduler if needed: `systemctl stop arisp`
4. Wait for daily reset (midnight UTC) or increase limits
5. Review configuration for optimization opportunities

### Disk Space Issues

1. Check disk space: `df -h`
2. View cache size: `du -sh .cache/*`
3. Clear old cache: `rm -rf .cache/api/*`
4. Archive old output files
5. Consider increasing disk capacity

### Service Unresponsive

1. Check if process is running: `docker-compose ps` or `systemctl status arisp`
2. Check for OOM kills: `dmesg | grep -i kill`
3. Restart service: `docker-compose restart arisp`
4. If persistent, check resource limits

---

## Maintenance Procedures

### Planned Maintenance

1. Notify stakeholders of maintenance window
2. Wait for active jobs to complete
3. Stop scheduler: `docker-compose stop arisp`
4. Perform maintenance tasks
5. Start scheduler: `docker-compose start arisp`
6. Verify health: `curl http://localhost:8000/health`

### Configuration Updates

1. Edit configuration file
2. Validate: `python -m src.cli validate config/research_config.yaml`
3. Restart service: `docker-compose restart arisp`
4. Verify new configuration is loaded (check logs)

### Version Upgrades

1. Review changelog and migration notes
2. Backup configuration and data
3. Pull new version: `git pull`
4. Rebuild container: `docker-compose build`
5. Stop old version: `docker-compose down`
6. Start new version: `docker-compose up -d`
7. Verify health and functionality

### Backup Procedures

```bash
# Backup output files
tar -czf backup/output_$(date +%Y%m%d).tar.gz output/

# Backup configuration
cp config/research_config.yaml backup/

# Backup catalog
cp output/catalog.json backup/
```

---

## Contact Information

- **On-call team**: [Configure as appropriate]
- **Escalation**: [Configure as appropriate]
- **Documentation**: [Link to full documentation]
