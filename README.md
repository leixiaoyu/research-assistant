# ARISP - Automated Research Ingestion & Synthesis Pipeline

> Automate the discovery, extraction, and synthesis of cutting-edge AI research papers with intelligent LLM-powered analysis.

[![Python 3.10.19](https://img.shields.io/badge/python-3.10.19-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Security: High](https://img.shields.io/badge/security-high-green.svg)](docs/security/)
[![Test Coverage: 100%](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](tests/)

## 🎯 Overview

ARISP automates the research process by:
- 🔍 **Discovering** papers from multiple sources (ArXiv, Semantic Scholar)
- 📄 **Processing** PDFs with code-preserving markdown conversion
- 🤖 **Extracting** prompts, code, and insights using LLM (Claude/Gemini)
- 📝 **Synthesizing** Obsidian-ready markdown briefs for engineering teams

**✨ Phase 1.5 Stabilized:** The foundation is now production-grade with 100% test coverage and automated quality enforcement.

## ✨ Key Features

### Discovery (Phase 1 + 1.5)
- **Multi-Provider Support**: ArXiv (default, no API key) + Semantic Scholar (optional)
- **Configurable Topics**: User-editable YAML configuration for research queries
- **Flexible Timeframes**: Recent (48h), since year (2020+), or custom date ranges
- **Intelligent Cataloging**: Automatic deduplication and topic organization
- **100% PDF Access**: ArXiv guarantees open access PDFs for all papers

### Extraction (Phase 2)
- **LLM-Powered Analysis**: Claude 3.5 Sonnet or Gemini 1.5 Pro
- **Configurable Targets**: Extract prompts, code, metrics, summaries per topic
- **Cost Controls**: Budget limits, usage tracking, smart filtering
- **Fallback Strategies**: Abstract-only mode when PDFs unavailable

### Intelligence (Phase 3)
- **Concurrent Processing**: Process 50+ papers in <30 minutes
- **Multi-Level Caching**: API responses, PDFs, extractions
- **Quality Filtering**: Citation-based ranking, venue filtering
- **Autonomous Operation**: Intelligent stopping when research converges

### Production (Phase 4)
- **Observable**: Structured logging, Prometheus metrics, Grafana dashboards
- **Resilient**: Retry logic, circuit breakers, checkpoint/resume
- **Secure**: Security-first design, secrets scanning, input validation

## 🚀 Quick Start

### Prerequisites

**Required:**
- Python 3.10.19+
- LLM API key (Anthropic or Google) - for Phase 2 extraction

**Optional:**
- Semantic Scholar API key - only if you want to use Semantic Scholar instead of ArXiv

### Installation

```bash
# Clone repository
git clone https://github.com/leixiaoyu/research-assistant.git
cd research-assistant

# Create virtual environment (Python 3.10.19 required)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Set up environment
cp .env.template .env
# Edit .env and add your LLM API key
```

### Development & Verification

Every push must pass the "Golden Path" verification:

```bash
# Run all quality checks (Formatting, Linting, Types, Tests, Coverage)
./verify.sh
```

### Usage

```bash
# Run pipeline (Phase 1: Discovery only)
python -m src.cli run

# Validate configuration
python -m src.cli validate config/research_config.yaml

# View catalog
python -m src.cli catalog show
```

## 📚 Documentation

### Architecture
- **[System Architecture](docs/SYSTEM_ARCHITECTURE.md)** - Complete architecture design ⭐ **PRIMARY REFERENCE**
- [Architecture Review](docs/ARCHITECTURE_REVIEW.md) - Gap analysis and architectural assessment
- [Phased Delivery Plan](docs/PHASED_DELIVERY_PLAN.md) - 5-phase implementation roadmap

### Phase Specifications
- [Phase 1: Foundation](docs/specs/PHASE_1_SPEC.md) - ✅ Complete
- [Phase 1.5: Provider Abstraction](docs/specs/PHASE_1_5_SPEC.md) - ✅ Complete & Stabilized
- [Phase 2: Extraction](docs/specs/PHASE_2_SPEC.md) - ⏳ Next (PDF & LLM)
- [Phase 3: Optimization](docs/specs/PHASE_3_SPEC.md) - 📋 Planned
- [Phase 4: Hardening](docs/specs/PHASE_4_SPEC.md) - 📋 Planned

### Verification
- [Phase 1.5 Verification Report](docs/verification/PHASE_1_5_VERIFICATION_REPORT.md) - 🚀 100% Coverage Proof

### Development
- [GEMINI.md](GEMINI.md) - **Project Guidelines & PR Review Protocol**
- [CLAUDE.md](CLAUDE.md) - Legacy development guide

## 🏗️ Project Status

**Current Phase**: Phase 1.5 Complete / Phase 2 Ready

**Timeline**:
```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ Phase 1  │Phase 1.5 │ Phase 2  │ Phase 3  │ Phase 4  │
│ ✅ Done  │ ✅ Done  │📋 2wks   │📋 2wks   │📋 1wk    │
│          │          │          │          │          │
│Foundation│ Stabilize│Extraction│Optimize  │ Harden   │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

**Completed**:
- ✅ **Phase 1: Foundation & Core Pipeline** (Jan 2026)
- ✅ **Phase 1.5: Stabilization & Provider Abstraction** (Jan 2026)
  - Python 3.10.19 upgrade
  - **100% test coverage** for all modules
  - Automated quality enforcement (`verify.sh`)
  - High-standard PR Review Protocol
  - ArXiv integration (no API key required)

**Next**:
- 📋 **Phase 2: PDF Processing & LLM Extraction** (2 weeks)

## 📊 Performance & Quality

### Current Metrics (Phase 1.5 Final)
- ✅ **Test Coverage**: **100%**
- ✅ **Quality Enforcement**: Automated (Flake8, Black, Mypy, Pytest)
- ✅ **Security Compliance**: 100% Verified
- ✅ **Test Suite**: 116 automated tests (100% pass rate)
- ✅ **Environment**: Python 3.10.19 (Strict)

## 🔒 Security

**Security-First Design** - Non-negotiable standards:
- ✅ No hardcoded secrets
- ✅ Strict input validation (Pydantic + Security Utils)
- ✅ Path sanitization (Directory traversal prevention)
- ✅ Rate limiting (Token bucket + delay enforcement)
- ✅ Mandatory security checklist for every PR

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details