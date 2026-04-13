# ARISP - Automated Research Ingestion & Synthesis Pipeline

> Automate the discovery, extraction, and synthesis of cutting-edge AI research papers with intelligent LLM-powered analysis.

[![Python 3.14](https://img.shields.io/badge/python-3.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Security: High](https://img.shields.io/badge/security-high-green.svg)](docs/security/)
[![Test Coverage: 99%](https://img.shields.io/badge/coverage-99%25-brightgreen.svg)](tests/)

## 🎯 Overview

ARISP automates the research process by:
- 🔍 **Discovering** papers from multiple sources (ArXiv, Semantic Scholar)
- 📄 **Processing** PDFs with code-preserving markdown conversion
- 🤖 **Extracting** prompts, code, and insights using LLM (Claude/Gemini)
- 📝 **Synthesizing** Obsidian-ready markdown briefs for engineering teams

**✨ Phase 8.1 Complete:** Corpus Infrastructure for Deep Research Agent — hybrid search (FAISS + BM25), paper ingestion pipeline, semantic chunking, and trajectory storage. Plus full Intelligence Services Consolidation (Phase 1), Human Feedback Loop (Phase 7.3), and 3,642 tests at 99%+ coverage!

## ✨ Key Features

### Discovery (Phase 1 + 1.5)
- **Multi-Provider Support**: ArXiv (default, no API key) + Semantic Scholar (optional)
- **Configurable Topics**: User-editable YAML configuration for research queries
- **Flexible Timeframes**: Recent (48h), since year (2020+), or custom date ranges
- **Intelligent Cataloging**: Automatic deduplication and topic organization
- **100% PDF Access**: ArXiv guarantees open access PDFs for all papers

### Extraction (Phase 2 + 2.5) ✅ Complete
- **LLM-Powered Analysis**: Claude 3.5 Sonnet or Gemini 3 Flash Preview
- **Configurable Targets**: Extract prompts, code, metrics, summaries per topic
- **Cost Controls**: Budget limits, usage tracking, smart filtering
- **Multi-Backend PDF Processing**: PyMuPDF (fast) → PDFPlumber (tables) → Pandoc (fallback)
- **Quality-Based Selection**: Automatic backend selection using heuristic scoring
- **Reliability-First**: 100% test coverage on all extractors, production-hardened
- **Enhanced Output**: Token/cost tracking, confidence scores, extraction summaries

### Intelligence (Phase 3) ✅ Complete
- **Multi-Level Caching**: API responses, PDFs, extractions with 99% hit rates
- **Smart Deduplication**: Two-stage (DOI + fuzzy title) matching with 90%+ accuracy
- **Quality Filtering**: Weighted ranking (citations + recency + relevance)
- **Checkpoint/Resume**: Atomic saves for crash-safe pipeline resumption
- **100% Service Coverage**: All Phase 3 services at 100% test coverage

### Concurrent Orchestration (Phase 3.1) ✅ Complete
- **Async Worker Pools**: Producer-consumer pattern with configurable workers
- **Resource Limiting**: Semaphore-based control for downloads, conversions, LLM calls
- **Backpressure Handling**: Bounded queues prevent memory exhaustion
- **Graceful Degradation**: Individual paper failures don't block pipeline
- **Full Integration**: Works with cache, dedup, filter, and checkpoint services

### Production (Phase 4) ✅ Complete
- **Observable**: Structured logging, Prometheus metrics, Grafana dashboards
- **Resilient**: Retry logic, circuit breakers, checkpoint/resume
- **Secure**: Security-first design, secrets scanning, input validation

### Global Registry & CLI (Phase 5.x) ✅ Complete
- **Paper Registry**: Global paper identity with Semantic Scholar, ArXiv, HuggingFace integration
- **LLM Decomposition**: Break complex queries into targeted search strategies
- **Research Pipeline**: Multi-source discovery with cross-provider deduplication
- **CLI Commands**: Full command-line interface for all pipeline operations

### Enhanced Discovery (Phase 6) ✅ Complete
- **Multi-Provider Orchestration**: Unified discovery across ArXiv, Semantic Scholar, HuggingFace
- **Provider Abstraction**: Pluggable provider interface with health tracking
- **Benchmark Mode**: Cross-provider comparison and quality scoring

### Human Feedback Loop (Phase 7.3) ✅ Complete
- **Preference Learning**: User feedback drives paper relevance scoring
- **Semantic Similarity**: Embedding-based topic matching for smarter discovery
- **Feedback Integration**: Phase 7.3 loop wired into the discovery pipeline

### Intelligence Services Consolidation (Phase 7.x) ✅ Complete
- **VenueRepository**: YAML-based venue quality scoring with LRU caching
- **QualityIntelligenceService**: Unified quality scoring with recency decay
- **QueryIntelligenceService**: Provider selection and LLM-powered query expansion
- **Hybrid Search**: FAISS + BM25 retrieval outperforming dense-only approaches

### Deep Research Agent — Corpus (Phase 8.1) ✅ Complete
- **Corpus Manager**: Offline indexed corpus from ARISP papers with semantic chunking
- **Hybrid Retrieval**: FAISS + BM25 hybrid search with <200ms latency targets
- **Paper Ingestion**: Automated pipeline to index and search over all discovered papers
- **Trajectory Storage**: Batch trajectory storage for learning from research sessions

## 🚀 Quick Start

### Prerequisites

**Required:**
- Python 3.14+
- LLM API key (Anthropic or Google) - for Phase 2 extraction

**Optional:**
- Semantic Scholar API key - only if you want to use Semantic Scholar instead of ArXiv

### Installation

```bash
# Clone repository
git clone https://github.com/leixiaoyu/research-assistant.git
cd research-assistant

# Create virtual environment (requires Python 3.14+)
python3.14 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.template .env
# Edit .env and add your LLM API key
# Semantic Scholar API key is optional (defaults to ArXiv)
```

### Development & Verification

Every push must pass the "Golden Path" verification:

```bash
# Run all quality checks (Formatting, Linting, Types, Tests, Coverage)
./verify.sh
```

### Configuration

**Minimal Configuration (ArXiv - No API Key Required):**

```yaml
# config/research_config.yaml
research_topics:
  - query: "attention mechanism transformers"
    timeframe:
      type: "recent"
      value: "7d"
    max_papers: 20

settings:
  output_base_dir: "./output"
  # No API key needed for ArXiv!
```

**Full Configuration (with Semantic Scholar and Extraction):**

```yaml
# config/research_config.yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    provider: "arxiv"  # or "semantic_scholar" (optional, defaults to arxiv)
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 50
    extraction_targets:
      - name: "system_prompts"
        description: "Extract LLM system prompts used in the paper"
        output_format: "list"
        required: false
      - name: "code_snippets"
        description: "Extract Python code implementing the methodology"
        output_format: "code"
        required: false
      - name: "engineering_summary"
        description: "Write a 2-paragraph summary for engineering teams"
        output_format: "text"
        required: true

  - query: "reinforcement learning robotics"
    provider: "semantic_scholar"  # Requires API key
    timeframe:
      type: "since_year"
      value: 2023
    max_papers: 30

settings:
  output_base_dir: "./output"
  enable_duplicate_detection: true

  # Optional: Only needed for Semantic Scholar
  semantic_scholar_api_key: "${SEMANTIC_SCHOLAR_API_KEY}"

  # Required for Phase 2 (LLM extraction)
  llm_settings:
    provider: "anthropic"  # or "google"
    model: "claude-3-5-sonnet-20250122"
    api_key: "${LLM_API_KEY}"
    max_tokens: 100000

  cost_limits:
    max_daily_spend_usd: 50.0
    max_total_spend_usd: 500.0
```

### Usage

```bash
# Run pipeline (Phase 1: Discovery only)
python -m src.cli run

# Run with custom config
python -m src.cli run --config custom_research.yaml

# Validate configuration
python -m src.cli validate config/research_config.yaml

# View catalog
python -m src.cli catalog show
```

**Example Output Structure:**
```
output/
├── catalog.json                    # Master index
├── attention-mechanism-transformers/
│   ├── 2026-01-23_Research.md    # ArXiv papers
│   └── papers/                    # Downloaded PDFs
└── tree-of-thoughts-translation/
    ├── 2026-01-23_Research.md
    └── papers/
```

## 📚 Documentation

### Architecture
- **[System Architecture](docs/SYSTEM_ARCHITECTURE.md)** - Complete architecture design ⭐ **PRIMARY REFERENCE**
- [Architecture Review](docs/ARCHITECTURE_REVIEW.md) - Gap analysis and architectural assessment
- [Phased Delivery Plan](docs/PHASED_DELIVERY_PLAN.md) - 5-phase, ~6-week implementation roadmap

### Phase Specifications
- [Phase 1: Foundation](docs/specs/PHASE_1_SPEC.md) - ✅ Complete (Discovery, Catalog, Config)
- [Phase 1.5: Provider Abstraction](docs/specs/PHASE_1_5_SPEC.md) - ✅ Complete (ArXiv Integration)
- [Phase 2: Extraction](docs/specs/PHASE_2_SPEC.md) - ✅ Complete (PDF & LLM Extraction)
- [Phase 2.5: PDF Reliability](docs/specs/PHASE_2.5_SPEC.md) - ✅ Complete (Multi-Backend Fallback Chain)
- [Phase 3: Intelligence Layer](docs/specs/PHASE_3_SPEC.md) - ✅ Complete (Cache, Dedup, Filters, Checkpoint)
- [Phase 3.1: Concurrent Orchestration](docs/specs/PHASE_3.1_SPEC.md) - ✅ Complete (Async Workers & Resource Limiting)
- [Phase 3.3: LLM Resilience](docs/specs/PHASE_3.3_LLM_FALLBACK_SPEC.md) - ✅ Complete (Retry, Circuit Breaker, Provider Failover)
- [Phase 3.4: Multi-Provider Discovery](docs/specs/PHASE_3.4_PDF_PRIORITY_SPEC.md) - ✅ Complete (HuggingFace, Cross-Provider)
- [Phase 3.5: Global Registry](docs/specs/PHASE_3.5_SPEC.md) - ✅ Complete (Paper Identity & Registry)
- [Phase 3.6: Delta Briefs](docs/specs/PHASE_3.6_SPEC.md) - ✅ Complete (Topic-Level Change Tracking)
- [Phase 3.8: Cross-Topic Synthesis](docs/specs/PHASE_3.8_SPEC.md) - ✅ Complete (Multi-Topic Query Synthesis)
- [Phase 4: Production Hardening](docs/specs/PHASE_4_SPEC.md) - ✅ Complete (Observability, Security, Deployment)
- [Phase 5.x: CLI & Decomposition](docs/specs/PHASE_5_OVERVIEW.md) - ✅ Complete (CLI, LLM Decomposition, Research Pipeline)
- [Phase 6: Enhanced Discovery](docs/specs/PHASE_6_DISCOVERY_ENHANCEMENT_SPEC.md) - ✅ Complete (Multi-Provider Orchestration)
- [Phase 7.1: Feedback Foundation](docs/specs/PHASE_7.1_SPEC.md) - ✅ Complete (Feedback Data Model)
- [Phase 7.2: Preference Learning](docs/specs/PHASE_7.2_SPEC.md) - ✅ Complete (Embedding-Based Topic Matching)
- [Phase 7.3: Human Feedback Loop](docs/specs/PHASE_7.3_SPEC.md) - ✅ Complete (Feedback Integration)
- [Phase 8.1: DRA Corpus Infrastructure](docs/specs/PHASE_8_DRA_SPEC.md) - ✅ Complete (Hybrid Search, Paper Ingestion, Trajectory Storage)

### Proposals
- [Proposal 001: Discovery Provider Strategy](docs/proposals/001_DISCOVERY_PROVIDER_STRATEGY.md) - ✅ Approved & Implemented
- [Proposal 002: PDF Extraction Reliability](docs/proposals/002_PDF_EXTRACTION_RELIABILITY.md) - ✅ Approved & Implemented
- [Proposal 004: Deep Research Agent (DRA)](docs/proposals/004_OPENRESEARCHER_OFFLINE_TRAJECTORY_SYNTHESIS.md) - 🔄 Phase 8.1 Complete (Corpus Infrastructure); Agent Loop (8.2) in progress

### Development
- [CLAUDE.md](CLAUDE.md) - Development guide for Claude Code integration
- [Pre-Commit Hooks](docs/operations/PRE_COMMIT_HOOKS.md) - Security and quality automation
- [Dependency Security](docs/security/DEPENDENCY_SECURITY_AUDIT.md) - Vulnerability scan results

## 🏗️ Project Status

**Current Status:** ✅ **Phase 8.1 Complete** - Corpus Infrastructure for Deep Research Agent + Intelligence Services Consolidation Phase 1 (PR #89 merged 2026-04-13). Full production pipeline with 3,642 tests at 99%+ coverage.

**Next Phase:** 📋 **Phase 8.2: DRA Agent Loop** (ReAct-style reasoning) or **Phase 9 planning** - Autonomous research agent with trajectory learning.

📊 **For detailed progress tracking, timelines, and phase-by-phase completion status, see:**
→ **[Phased Delivery Plan](docs/PHASED_DELIVERY_PLAN.md)** (Single Source of Truth)

## 🛠️ Tech Stack

### Core Technologies
| Category | Technology | Purpose |
|----------|-----------|---------|
| Language | Python 3.14+ | Rich ecosystem, async support, free-threading |
| Data Models | Pydantic V2 | Runtime validation, type safety |
| Discovery | **ArXiv API** (default) | **No API key required** |
| Discovery | Semantic Scholar API (optional) | Comprehensive coverage |
| PDF Processing | marker-pdf | Code-preserving conversion |
| LLM | Claude 3.5 Sonnet / Gemini 1.5 Pro | 1M+ context, high quality |
| CLI | typer | Modern, type-safe interface |
| Async | asyncio + aiohttp | High-performance I/O |

### Infrastructure
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Caching | diskcache | Fast local caching |
| Logging | structlog | Structured JSON logs |
| Metrics | Prometheus | Time-series metrics |
| Dashboards | Grafana | Visualization |
| Scheduling | APScheduler | Automated runs |
| Testing | pytest | >99% coverage |
| Security | pre-commit hooks | Secret scanning, linting |

## 📊 Performance & Quality

### Current Metrics
- ✅ **Test Coverage**: 99.25% (2181 automated tests, 100% pass rate)
- ✅ **Security**: 22/22 requirements met across all layers
- ✅ **Quality Gates**: Automated enforcement (Flake8, Black, Mypy, Pytest)
- ✅ **Configuration Validation**: <1s
- ✅ **Catalog Operations**: <100ms
- ✅ **Memory Usage**: <100MB idle
- ✅ **LLM Cost**: ~$0.005 per paper (abstract-only mode)
- ✅ **Rate Limiting**: ArXiv-compliant (3s minimum delay)
- ✅ **Environment**: Python 3.14+ (CI/CD enforced)

## 🔒 Security

**Security-First Design** - All 22 security requirements enforced across all layers:

**Core Security:**
- ✅ No hardcoded secrets (environment variables only)
- ✅ Input validation (Pydantic + security utilities)
- ✅ Path sanitization (directory traversal prevention)
- ✅ Rate limiting (exponential backoff, ArXiv compliance)
- ✅ Security logging (no secrets in logs)
- ✅ Dependency scanning (pip-audit, monthly audits)
- ✅ Pre-commit hooks (secret scanning, linting)
- ✅ Configuration validation (strict schemas)
- ✅ Error handling (graceful degradation)

**Infrastructure Security:**
- ✅ File system security (atomic writes, permissions)
- ✅ API security (HTTPS only, SSL validation)
- ✅ Provider input validation (query sanitization)
- ✅ PDF URL validation (HTTPS enforcement)
- ✅ API response validation (status codes, malformed data)
- ✅ Cache directory permissions restricted
- ✅ Checkpoint atomic writes with validation

See [Security Audit](docs/security/DEPENDENCY_SECURITY_AUDIT.md) for detailed vulnerability scan results.

## 🎓 Use Cases

### Research Teams
- Stay current with latest papers in your field
- Extract implementation details from papers
- Build knowledge base of research findings

### Engineering Teams
- Identify applicable techniques for production systems
- Extract code snippets and prompts from papers
- Generate technical summaries for non-researchers

### AI Practitioners
- Track developments in specific AI subfields
- Extract prompts and evaluation metrics
- Build prompt libraries from research

## 💡 Provider Comparison

| Provider | API Key | Coverage | PDF Access | Best For |
|----------|---------|----------|------------|----------|
| **ArXiv** ⭐ | ❌ No | AI/CS/Physics pre-prints | ✅ 100% | Cutting-edge AI research |
| **Semantic Scholar** | ✅ Yes (pending) | 200M+ papers, all fields | ⚠️ Varies | Comprehensive research |
| **OpenAlex** (future) | Optional | 250M+ works | ⚠️ Varies | Multi-disciplinary |
| **PubMed** (future) | ❌ No | Medical/life sciences | ⚠️ Varies | Biomedical research |

**Recommendation:** Start with ArXiv (no setup required), add Semantic Scholar when keys arrive.

## 🤝 Contributing

This project follows strict quality standards:
- ✅ Security-first development
- ✅ Test-driven development (>80% coverage)
- ✅ Complete verification before commits
- ✅ SOLID, KISS, DRY, YAGNI principles

Contributions welcome after Phase 1.5! See [CLAUDE.md](CLAUDE.md) for development guidelines.

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details

## 📧 Contact

- **Repository**: https://github.com/leixiaoyu/research-assistant
- **Issues**: https://github.com/leixiaoyu/research-assistant/issues

## 🙏 Acknowledgments

- **ArXiv** for open access research papers
- **Semantic Scholar** for research paper API
- **marker-pdf** for code-preserving PDF conversion
- **Anthropic** & **Google** for LLM APIs
- **Pydantic** for data validation
- **Open source community** for excellent tooling

---

## 📖 Quick Reference

### Environment Variables

```bash
# Required for Phase 2 (LLM extraction)
LLM_API_KEY=your_anthropic_or_google_api_key

# Optional (only for Semantic Scholar provider)
SEMANTIC_SCHOLAR_API_KEY=your_semantic_scholar_api_key
```

### Common Commands

```bash
# Run with ArXiv (no API key needed)
python -m src.cli run

# Run with Semantic Scholar
# (requires SEMANTIC_SCHOLAR_API_KEY in .env)
python -m src.cli run --provider semantic_scholar

# Validate config before running
python -m src.cli validate

# Check catalog of processed papers
python -m src.cli catalog show

# Run tests
pytest tests/ --cov=src --cov-report=term

# Run security checks
python -m pip_audit -r requirements.txt
pre-commit run --all-files
```

### Timeframe Examples

```yaml
# Last 48 hours
timeframe:
  type: "recent"
  value: "48h"

# Last 7 days
timeframe:
  type: "recent"
  value: "7d"

# Papers since 2023
timeframe:
  type: "since_year"
  value: 2023

# Custom date range
timeframe:
  type: "date_range"
  start_date: "2024-01-01"
  end_date: "2024-12-31"
```

---

**Built with ❤️ for research teams who want to stay ahead**

**Status**: Phase 8.1 Complete - Corpus Infrastructure for Deep Research Agent + Intelligence Services Consolidation Phase 1. 3,642 tests, 99%+ coverage 🚀
