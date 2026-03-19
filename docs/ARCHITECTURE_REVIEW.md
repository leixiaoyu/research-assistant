# ARISP Architecture Review
**Principal Engineer Review**
**Date:** 2025-01-23
**Reviewer:** Principal Engineering Team

## Executive Summary

The Automated Research Ingestion & Synthesis Pipeline (ARISP) presents a solid foundation for automated research discovery and synthesis. However, several critical architectural gaps must be addressed before production deployment. This review identifies 16 key areas requiring improvement and proposes a 4-phase delivery approach.

## Architecture Strengths

### 1. Clear Separation of Concerns ✅
- Five distinct modules with well-defined responsibilities
- Config management separated from business logic
- Good modularity for testing and maintenance

### 2. Intelligent Cataloging Design ✅
- Topic normalization prevents folder duplication
- Catalog-based tracking enables historical analysis
- Append-only behavior preserves research history

### 3. Flexible Configuration ✅
- YAML-based user-editable config
- Multiple timeframe strategies (recent, since_year, date_range)
- Topic-level customization

### 4. Appropriate Tech Stack ✅
- Python 3.14 for modern language features
- marker-pdf for code-preserving conversion
- LLM with 1M+ context for comprehensive extraction

## Critical Architectural Gaps

### 1. **Data Models & Type Safety** 🔴 CRITICAL
**Issue:** No structured data models defined. Using raw dicts throughout pipeline.

**Impact:**
- Runtime errors from missing/mistyped fields
- Difficult to maintain and refactor
- No IDE autocomplete support

**Recommendation:**
```python
# Use Pydantic for runtime validation
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List

class PaperMetadata(BaseModel):
    title: str
    abstract: str
    url: str
    doi: Optional[str]
    publication_date: datetime
    open_access_pdf: Optional[str]
    authors: List[str] = Field(default_factory=list)
    citation_count: int = 0

class ResearchTopic(BaseModel):
    query: str
    timeframe_type: Literal["recent", "since_year", "date_range"]
    timeframe_value: str | int
    extraction_targets: List[str] = Field(default_factory=lambda: ["prompts", "code"])
```

### 2. **No Concurrency Model** 🔴 CRITICAL
**Issue:** Sequential processing of papers will be extremely slow.

**Impact:**
- 50 papers × (10s download + 30s PDF conversion + 120s LLM) = ~2 hours per topic
- Poor resource utilization
- User experience degradation

**Recommendation:**
- Use `asyncio` for I/O-bound operations (downloads, API calls)
- Thread pool for CPU-bound operations (PDF conversion)
- Implement backpressure and rate limiting
```python
async def process_papers_concurrently(
    papers: List[PaperMetadata],
    max_concurrent: int = 5
) -> List[ExtractedData]:
    semaphore = asyncio.Semaphore(max_concurrent)
    tasks = [process_single_paper(p, semaphore) for p in papers]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

### 3. **No Resilience Strategy** 🔴 CRITICAL
**Issue:** No retry logic, circuit breakers, or fallback mechanisms.

**Impact:**
- Transient API failures cause complete pipeline failure
- No recovery from partial failures
- Data loss on interruption

**Recommendation:**
- Implement exponential backoff with jitter
- Circuit breaker pattern for external APIs
- Checkpoint/resume capability
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10)
)
async def fetch_with_retry(url: str) -> bytes:
    ...
```

### 4. **Hardcoded Extraction Targets** 🟡 MEDIUM
**Issue:** LLM extraction looks for fixed fields (tot_system_prompt, tot_user_prompt_template, etc.)

**Impact:**
- Not usable for different research domains
- Inflexible to changing requirements
- Wastes LLM tokens on irrelevant extractions

**Recommendation:**
```yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    extraction_targets:
      - name: "system_prompts"
        description: "Extract all LLM system prompts"
      - name: "code_snippets"
        description: "Extract Python code for ToT implementation"
      - name: "evaluation_metrics"
        description: "Extract benchmark results and metrics"
```

### 5. **No Observability** 🟡 MEDIUM
**Issue:** No structured logging, metrics, or monitoring.

**Impact:**
- Difficult to debug production issues
- No visibility into pipeline health
- Cannot optimize performance without metrics

**Recommendation:**
- Structured logging with correlation IDs
- Prometheus metrics for monitoring
- OpenTelemetry for distributed tracing
```python
import structlog

logger = structlog.get_logger()
logger.info(
    "paper_processed",
    paper_id=paper.doi,
    processing_time_ms=elapsed,
    status="success"
)
```

### 6. **Missing Storage Strategy** 🟡 MEDIUM
**Issue:** No disk space management, cleanup policy, or compression.

**Impact:**
- Unbounded disk usage
- Expensive storage costs
- Difficult to manage long-term

**Recommendation:**
- Configurable retention policy
- Compress old PDFs
- Optional cloud storage backend (S3, GCS)
- Storage quota alerts

### 7. **No Cost Controls** 🟡 MEDIUM
**Issue:** No rate limiting or budget controls for LLM API calls.

**Impact:**
- Potential runaway costs
- API quota exhaustion
- No forecasting capability

**Recommendation:**
```yaml
llm_config:
  max_tokens_per_paper: 100000
  max_daily_spend_usd: 50.00
  provider: "anthropic"  # or "google"
  model: "claude-3-5-sonnet-20250122"
```

### 8. **Insufficient Error Handling** 🟡 MEDIUM
**Issue:** Generic try/except mentioned but no error taxonomy.

**Impact:**
- Cannot distinguish transient vs permanent failures
- Poor error messages
- Difficult debugging

**Recommendation:**
```python
class PipelineError(Exception):
    """Base exception for all pipeline errors"""

class TransientError(PipelineError):
    """Retryable errors (network, rate limits)"""

class PermanentError(PipelineError):
    """Non-retryable errors (invalid config, missing API keys)"""

class PartialFailureError(PipelineError):
    """Some papers succeeded, some failed"""
    def __init__(self, successes: int, failures: List[Exception]):
        self.successes = successes
        self.failures = failures
```

### 9. **No Incremental Processing** 🔵 LOW
**Issue:** Pipeline starts from scratch on each run.

**Impact:**
- Wastes time re-processing known papers
- No "continue where left off" capability

**Recommendation:**
- Track processed paper DOIs in catalog
- Skip already-processed papers
- Implement checkpoint/resume

### 10. **Missing Paper Quality Filters** 🔵 LOW
**Issue:** No filtering by citation count, venue, or relevance score.

**Impact:**
- May process low-quality papers
- Wasted LLM tokens
- Noisy research briefs

**Recommendation:**
```yaml
research_topics:
  - query: "..."
    filters:
      min_citation_count: 10
      venues: ["NeurIPS", "ICML", "ACL", "EMNLP"]
      min_year: 2020
```

### 11. **No Scheduling System** 🔵 LOW
**Issue:** "Runs daily" mentioned but no scheduler specified.

**Impact:**
- Manual execution required
- No automated workflows

**Recommendation:**
- Use APScheduler for in-process scheduling
- Or systemd timers / cron for system-level
- Or cloud-native (AWS EventBridge, Cloud Scheduler)

### 12. **Missing CLI Framework** 🔵 LOW
**Issue:** argparse vs typer vs click not specified.

**Recommendation:**
- Use `typer` for modern, type-safe CLI
- Supports autocomplete and validation
```python
import typer
app = typer.Typer()

@app.command()
def run(
    config: Path = typer.Option("research_config.yaml"),
    dry_run: bool = typer.Option(False, "--dry-run")
):
    """Run the research pipeline"""
```

### 13. **No Testing Strategy** 🔵 LOW
**Issue:** Tests mentioned but no framework or strategy defined.

**Recommendation:**
- pytest for unit/integration tests
- pytest-asyncio for async tests
- pytest-mock for API mocking
- Test coverage target: 80%+

### 14. **Security Considerations** 🔵 LOW
**Issue:** API keys in .env but no additional security measures.

**Recommendation:**
- Use keyring for credential storage
- Validate YAML to prevent injection
- Sanitize file paths to prevent traversal
- Rate limit to prevent abuse

### 15. **No Semantic Search** 🔵 LOW
**Issue:** Relies solely on keyword search from Semantic Scholar.

**Future Enhancement:**
- Implement vector similarity search
- Use paper embeddings for better relevance
- Cross-reference with multiple sources

### 16. **Missing Metadata Enrichment** 🔵 LOW
**Issue:** Limited metadata captured (no author info, venues, citations).

**Future Enhancement:**
- Capture author affiliations
- Track venue/conference rankings
- Build citation graph
- Extract figures and tables

## Recommended Architecture Improvements

### Layered Architecture
```
┌─────────────────────────────────────────────────────┐
│                   CLI Layer (typer)                 │
└─────────────────────────────────────────────────────┘
                         │
┌─────────────────────────────────────────────────────┐
│              Orchestration Layer                    │
│  - Pipeline coordinator                             │
│  - Workflow engine                                  │
│  - Checkpoint/resume                                │
└─────────────────────────────────────────────────────┘
                         │
┌──────────────┬──────────────┬──────────────┬─────────┐
│   Discovery  │  Acquisition │  Extraction  │ Storage │
│   Service    │   Service    │   Service    │ Service │
│              │              │              │         │
│ - Search API │ - Download   │ - PDF→MD     │ - Files │
│ - Filtering  │ - Retry      │ - LLM Call   │ - Catalog│
│ - Ranking    │ - Validate   │ - Parse JSON │ - Index │
└──────────────┴──────────────┴──────────────┴─────────┘
                         │
┌─────────────────────────────────────────────────────┐
│              Infrastructure Layer                   │
│  - Config (Pydantic)                                │
│  - Logging (structlog)                              │
│  - Metrics (prometheus_client)                      │
│  - Caching (diskcache)                              │
└─────────────────────────────────────────────────────┘
```

### Data Flow
```
Config → Discovery → Filter → Download → Convert → Extract → Synthesize → Output
   ↓         ↓         ↓         ↓         ↓         ↓          ↓         ↓
   └─────────┴─────────┴─────────┴─────────┴─────────┴──────────┴─────────┘
                              Catalog & Checkpoints
```

## Proposed Technology Additions

| Category | Tool | Purpose |
|----------|------|---------|
| Data Models | Pydantic | Runtime validation & type safety |
| Async | asyncio + aiohttp | Concurrent I/O operations |
| Retry | tenacity | Exponential backoff |
| Logging | structlog | Structured logging |
| Metrics | prometheus_client | Monitoring |
| CLI | typer | Modern CLI framework |
| Testing | pytest + pytest-asyncio | Test framework |
| Caching | diskcache | Local result caching |
| Scheduling | APScheduler | Task scheduling |

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| API rate limits exceeded | HIGH | Implement rate limiting, backoff |
| LLM costs exceed budget | HIGH | Add cost tracking and limits |
| PDF parsing fails | MEDIUM | Fallback to abstract-only |
| Disk space exhaustion | MEDIUM | Retention policy, compression |
| Data loss on crash | MEDIUM | Checkpointing, atomic writes |
| Invalid config causes crash | LOW | Schema validation |

## Phased Delivery Recommendation

### Phase 1: Foundation & Core Pipeline (MVP) - 2 weeks
**Goal:** End-to-end pipeline working for single topic

**Deliverables:**
- Pydantic data models
- Config manager with validation
- Semantic Scholar integration
- Basic catalog system
- Simple markdown output (no PDF processing)
- CLI with typer

### Phase 2: PDF Processing & LLM Extraction - 2 weeks
**Goal:** Full extraction pipeline with LLM

**Deliverables:**
- PDF download and conversion
- LLM integration (Claude/Gemini)
- Configurable extraction targets
- Enhanced output format
- Error handling and retry logic

### Phase 3: Intelligence & Optimization - 2 weeks
**Goal:** Production-grade performance and reliability

**Deliverables:**
- Concurrent processing (asyncio)
- Duplicate detection and deduplication
- Caching layer
- Incremental processing
- Paper quality filters

### Phase 4: Production Hardening - 1 week
**Goal:** Observable, maintainable, and cost-controlled

**Deliverables:**
- Structured logging and metrics
- Cost tracking and limits
- Scheduling system
- Comprehensive test suite
- Monitoring dashboards

## Conclusion

The current architecture provides a solid conceptual foundation but requires significant hardening before production deployment. The proposed 4-phase approach balances rapid MVP delivery with production-grade quality. Total estimated timeline: 7 weeks.

**Critical Path:** Phase 1 → Phase 2 → Phase 3 (Phase 4 can be parallel)

**Recommendation:** Proceed with Phase 1 immediately while finalizing detailed specs for subsequent phases.
