# ARISP - Automated Research Ingestion & Synthesis Pipeline

> Automate the discovery, extraction, and synthesis of cutting-edge AI research papers with intelligent LLM-powered analysis.

[![Python 3.10.19](https://img.shields.io/badge/python-3.10.19-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Security: High](https://img.shields.io/badge/security-high-green.svg)](docs/security/)
[![Test Coverage: 99%](https://img.shields.io/badge/coverage-99%25-brightgreen.svg)](tests/)

## 🎯 Overview

ARISP automates the research process by:
- 🔍 **Discovering** papers from multiple sources (ArXiv, Semantic Scholar)
- 📄 **Processing** PDFs with code-preserving markdown conversion
- 🤖 **Extracting** prompts, code, and insights using LLM (Claude/Gemini)
- 📝 **Synthesizing** Obsidian-ready markdown briefs for engineering teams

**✨ Phase 3.1 Complete:** Concurrent orchestration with async worker pools, intelligent resource limiting, and full integration with intelligence layer - 99% test coverage, 442 tests!

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

### Production (Phase 4)
- **Observable**: Structured logging, Prometheus metrics, Grafana dashboards
- **Resilient**: Retry logic, circuit breakers, checkpoint/resume
- **Secure**: Security-first design, secrets scanning, input validation

## 🚀 Quick Start

### Prerequisites

**Required:**
- Python 3.10+
- LLM API key (Anthropic or Google) - for Phase 2 extraction

**Optional:**
- Semantic Scholar API key - only if you want to use Semantic Scholar instead of ArXiv

### Installation

```bash
# Clone repository
git clone https://github.com/leixiaoyu/research-assistant.git
cd research-assistant

# Create virtual environment (requires Python 3.10+)
python3.10 -m venv venv
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
- [Phase 3.2: Semantic Scholar Activation](docs/specs/PHASE_3.2_SPEC.md) - 🎯 Ready (Multi-Provider Intelligence)
- [Phase 4: Hardening](docs/specs/PHASE_4_SPEC.md) - 📋 Planned (Production Readiness)

### Proposals
- [Proposal 001: Discovery Provider Strategy](docs/proposals/001_DISCOVERY_PROVIDER_STRATEGY.md) - ✅ Approved & Implemented
- [Proposal 002: PDF Extraction Reliability](docs/proposals/002_PDF_EXTRACTION_RELIABILITY.md) - ✅ Approved & Implemented

### Development
- [CLAUDE.md](CLAUDE.md) - Development guide for Claude Code integration
- [Pre-Commit Hooks](docs/operations/PRE_COMMIT_HOOKS.md) - Security and quality automation
- [Dependency Security](docs/security/DEPENDENCY_SECURITY_AUDIT.md) - Vulnerability scan results

## 🏗️ Project Status

**Current Status:** ✅ **Phase 3.1 Complete** - Concurrent orchestration with async worker pools, resource limiting, and full integration with intelligence layer.

**Next Phase:** 📋 **Phase 3.2: Semantic Scholar Activation** or **Phase 4: Production Hardening** - Multi-provider intelligence or observability/monitoring.

📊 **For detailed progress tracking, timelines, and phase-by-phase completion status, see:**
→ **[Phased Delivery Plan](docs/PHASED_DELIVERY_PLAN.md)** (Single Source of Truth)

## 🛠️ Tech Stack

### Core Technologies
| Category | Technology | Purpose |
|----------|-----------|---------|
| Language | Python 3.10+ | Rich ecosystem, async support |
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
| Testing | pytest | >95% coverage |
| Security | pre-commit hooks | Secret scanning, linting |

## 📊 Performance & Quality

### Current Metrics
- ✅ **Test Coverage**: 99.1% (442 automated tests, 100% pass rate)
- ✅ **Security**: 22/22 requirements met across all layers
- ✅ **Quality Gates**: Automated enforcement (Flake8, Black, Mypy, Pytest)
- ✅ **Configuration Validation**: <1s
- ✅ **Catalog Operations**: <100ms
- ✅ **Memory Usage**: <100MB idle
- ✅ **LLM Cost**: ~$0.005 per paper (abstract-only mode)
- ✅ **Rate Limiting**: ArXiv-compliant (3s minimum delay)
- ✅ **Environment**: Python 3.10+ (CI/CD enforced)

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

**Status**: Phase 3.1 Complete - Concurrent orchestration with async workers, resource limiting, and full intelligence integration. 99.1% coverage, 442 tests 🚀
