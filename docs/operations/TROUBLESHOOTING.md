# ARISP Troubleshooting Guide

This guide helps diagnose and resolve common issues with the ARISP pipeline.

## Table of Contents

1. [Quick Diagnostics](#quick-diagnostics)
2. [Common Issues](#common-issues)
3. [Error Messages](#error-messages)
4. [Performance Issues](#performance-issues)
5. [Integration Issues](#integration-issues)
6. [Debug Mode](#debug-mode)

---

## Quick Diagnostics

### First Steps

When encountering an issue, run these diagnostic commands:

```bash
# 1. Check service health
curl -s http://localhost:8000/health | jq

# 2. Check recent logs
docker-compose logs --tail=50 arisp | grep -E "(error|ERROR|failed|FAILED)"

# 3. Check resource usage
docker stats arisp --no-stream

# 4. Check disk space
df -h

# 5. Check network connectivity
curl -s https://api.semanticscholar.org/ | head -c 100
```

### Health Check Interpretation

| Status | Meaning | Action |
|--------|---------|--------|
| `healthy` | All systems operational | None required |
| `degraded` | Some non-critical issues | Monitor closely |
| `unhealthy` | Critical issues present | Immediate investigation |

---

## Common Issues

### Issue: Pipeline Not Starting

**Symptoms:**
- Service fails to start
- Health endpoint not responding

**Diagnosis:**
```bash
# Check if port is in use
lsof -i :8000

# Check container/process status
docker-compose ps
# or
systemctl status arisp
```

**Solutions:**

1. **Port conflict**: Change health port
   ```bash
   python -m src.cli schedule --health-port 8001
   ```

2. **Missing dependencies**: Reinstall requirements
   ```bash
   pip install -r requirements.txt
   ```

3. **Configuration error**: Validate config
   ```bash
   python -m src.cli validate config/research_config.yaml
   ```

---

### Issue: High Error Rate

**Symptoms:**
- Many papers failing to process
- Error rate above 10%

**Diagnosis:**
```bash
# Check error distribution
curl -s http://localhost:8000/metrics | grep arisp_extraction_errors_total

# Check recent errors in logs
docker-compose logs arisp | grep -E "extraction_failed|llm_api_call_failed"
```

**Solutions:**

1. **LLM API errors**: Check API key and rate limits
   ```bash
   # Verify API key is set
   echo $LLM_API_KEY | head -c 10
   ```

2. **PDF conversion failures**: Check PDF service
   ```bash
   # Test marker-pdf
   marker_single test.pdf --output_dir ./test_output
   ```

3. **Network issues**: Check connectivity
   ```bash
   curl -I https://api.semanticscholar.org/
   curl -I https://generativelanguage.googleapis.com/
   ```

---

### Issue: Cost Limit Exceeded

**Symptoms:**
- `CostLimitExceeded` error in logs
- Papers not being processed

**Diagnosis:**
```bash
# Check current daily cost
curl -s http://localhost:8000/metrics | grep arisp_daily_cost_usd
```

**Solutions:**

1. **Wait for daily reset**: Costs reset at midnight UTC

2. **Increase limits**: Edit configuration
   ```yaml
   settings:
     cost_limits:
       max_daily_spend_usd: 100.0
   ```

3. **Reduce token usage**: Optimize extraction targets

4. **Switch to cheaper model**: Use Gemini instead of Claude

---

### Issue: Disk Space Full

**Symptoms:**
- Disk space check failing
- Write errors in logs

**Diagnosis:**
```bash
# Check disk usage
df -h

# Check cache size
du -sh .cache/*

# Check output size
du -sh output/*
```

**Solutions:**

1. **Clear API cache** (safe):
   ```bash
   rm -rf .cache/api/*
   ```

2. **Clear PDF cache** (may need re-download):
   ```bash
   rm -rf .cache/pdfs/*
   ```

3. **Archive old output**:
   ```bash
   tar -czf old_output.tar.gz output/*/2024-*
   rm -rf output/*/2024-*
   ```

---

### Issue: Slow Processing

**Symptoms:**
- Papers taking too long to process
- Queue building up

**Diagnosis:**
```bash
# Check processing duration
curl -s http://localhost:8000/metrics | grep arisp_paper_processing_duration

# Check queue size
curl -s http://localhost:8000/metrics | grep arisp_papers_in_queue
```

**Solutions:**

1. **Increase concurrency**: Edit configuration
   ```yaml
   settings:
     concurrency:
       max_concurrent_downloads: 5
       max_concurrent_llm: 3
   ```

2. **Check network latency**:
   ```bash
   time curl -s https://api.semanticscholar.org/ > /dev/null
   ```

3. **Reduce paper size limit**:
   ```yaml
   settings:
     pdf_settings:
       max_file_size_mb: 20
   ```

---

### Issue: Cache Not Working

**Symptoms:**
- Low cache hit rate
- Papers being re-processed

**Diagnosis:**
```bash
# Check cache stats
curl -s http://localhost:8000/metrics | grep arisp_cache

# Check cache directory
ls -la .cache/
```

**Solutions:**

1. **Check cache enabled**: Verify configuration
   ```yaml
   settings:
     cache:
       enabled: true
   ```

2. **Check permissions**:
   ```bash
   chmod -R 755 .cache/
   ```

3. **Recreate cache directory**:
   ```bash
   rm -rf .cache
   mkdir -p .cache/{api,pdfs,extractions}
   ```

---

## Error Messages

### `LLMAPIError: Anthropic API error: 429`

**Cause:** Rate limit exceeded on Anthropic API

**Solution:**
- Reduce concurrent LLM requests
- Add delay between requests
- Wait for rate limit window to reset

### `LLMAPIError: Google API error: PERMISSION_DENIED`

**Cause:** Invalid or expired API key

**Solution:**
- Verify `LLM_API_KEY` environment variable
- Check API key permissions in Google Cloud Console
- Generate new API key if needed

### `PDFDownloadError: HTTP 403`

**Cause:** PDF access denied (paywall or restrictions)

**Solution:**
- This is expected for non-open-access papers
- Verify `open_access_pdf` field in paper metadata
- Pipeline will fall back to abstract extraction

### `ConversionError: marker-pdf failed`

**Cause:** PDF conversion tool error

**Solution:**
- Check marker-pdf installation: `marker_single --version`
- Verify PDF is valid: `file document.pdf`
- Check system resources (memory, CPU)

### `JSONParseError: Invalid JSON in LLM response`

**Cause:** LLM returned malformed JSON

**Solution:**
- Usually transient; will retry automatically
- If persistent, check prompt template
- Consider using different LLM model

---

## Performance Issues

### High Memory Usage

```bash
# Check memory usage
docker stats arisp --no-stream

# If using systemd
systemctl status arisp
```

**Solutions:**
- Reduce concurrent workers
- Clear large caches
- Increase memory limit in Docker/systemd

### High CPU Usage

```bash
# Check CPU usage
top -p $(pgrep -f "src.cli schedule")
```

**Solutions:**
- Reduce concurrent PDF conversions
- Check for infinite loops in logs
- Reduce number of extraction targets

### Slow API Responses

```bash
# Test API latency
time curl -s https://api.semanticscholar.org/graph/v1/paper/search?query=test
```

**Solutions:**
- Enable API response caching
- Use API during off-peak hours
- Consider alternative data sources

---

## Integration Issues

### Semantic Scholar API

**Test connectivity:**
```bash
curl -s "https://api.semanticscholar.org/graph/v1/paper/search?query=test&limit=1" | jq
```

**Common issues:**
- Rate limiting (403 responses)
- Invalid query syntax
- API key issues

### ArXiv API

**Test connectivity:**
```bash
curl -s "https://export.arxiv.org/api/query?search_query=test&max_results=1"
```

**Common issues:**
- XML parsing errors
- Query formatting
- Temporary outages

### LLM Providers

**Test Anthropic:**
```bash
curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-3-sonnet-20240229","max_tokens":10,"messages":[{"role":"user","content":"Hi"}]}'
```

**Test Google:**
```python
import google.generativeai as genai
genai.configure(api_key=os.environ['LLM_API_KEY'])
model = genai.GenerativeModel('gemini-1.5-pro')
print(model.generate_content("Hi").text)
```

---

## Debug Mode

### Enable Debug Logging

```bash
# Environment variable
export LOG_LEVEL=DEBUG

# Or in configuration
python -m src.cli schedule --log-level debug
```

### Capture Detailed Traces

```bash
# Run with full traceback
python -c "import traceback; traceback.print_exc()" -m src.cli run 2>&1 | tee debug.log
```

### Profile Performance

```python
import cProfile
import pstats

cProfile.run('asyncio.run(main())', 'profile.stats')
stats = pstats.Stats('profile.stats')
stats.sort_stats('cumulative').print_stats(20)
```

---

## Getting Help

If you cannot resolve an issue:

1. Collect diagnostic information:
   - Health check output
   - Recent log entries
   - Configuration (without secrets)
   - Steps to reproduce

2. Check existing issues in the repository

3. Create a new issue with the collected information

4. For urgent issues, contact the on-call team
