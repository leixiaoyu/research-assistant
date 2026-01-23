# ARISP - Automated Research Ingestion & Synthesis Pipeline

> Automate the discovery, extraction, and synthesis of cutting-edge AI research papers with intelligent LLM-powered analysis.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🎯 Overview

ARISP automates the research process by:
- 🔍 **Discovering** papers from Semantic Scholar based on configurable topics
- 📄 **Processing** PDFs with code-preserving markdown conversion
- 🤖 **Extracting** prompts, code, and insights using LLM (Claude/Gemini)
- 📝 **Synthesizing** Obsidian-ready markdown briefs for engineering teams

## ✨ Key Features

- **Configurable Topics**: User-editable YAML configuration for research queries
- **Flexible Timeframes**: Query papers from recent (48h) to historical (since 2008)
- **Intelligent Cataloging**: Automatic deduplication and topic organization
- **LLM-Powered Extraction**: Configurable extraction targets per topic
- **Production-Grade**: Concurrent processing, caching, observability

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- Semantic Scholar API key
- LLM API key (Anthropic or Google)

### Installation

```bash
# Clone repository
git clone https://github.com/leixiaoyu/research-assistant.git
cd research-assistant

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.template .env
# Edit .env and add your API keys
```

### Configuration

Edit `config/research_config.yaml`:

```yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 50
    extraction_targets:
      - name: "system_prompts"
        description: "Extract LLM system prompts"
        output_format: "list"

settings:
  output_base_dir: "./output"
  semantic_scholar_api_key: "${SEMANTIC_SCHOLAR_API_KEY}"
  llm_settings:
    provider: "anthropic"
    api_key: "${LLM_API_KEY}"
```

### Usage

```bash
# Run pipeline
python -m src.cli run

# Run with custom config
python -m src.cli run --config custom.yaml

# Validate configuration
python -m src.cli validate

# View catalog
python -m src.cli catalog show
```

## 📚 Documentation

### Architecture
- **[System Architecture](docs/SYSTEM_ARCHITECTURE.md)** - Complete architecture design (PRIMARY REFERENCE)
- [Architecture Review](docs/ARCHITECTURE_REVIEW.md) - Gap analysis and architectural assessment
- [Phased Delivery Plan](docs/PHASED_DELIVERY_PLAN.md) - 4-phase, 7-week implementation roadmap

### Phase Specifications
- [Phase 1: Foundation](docs/specs/PHASE_1_SPEC.md) - Core pipeline (2 weeks)
- [Phase 2: Extraction](docs/specs/PHASE_2_SPEC.md) - PDF & LLM integration (2 weeks)
- [Phase 3: Optimization](docs/specs/PHASE_3_SPEC.md) - Performance & intelligence (2 weeks)
- [Phase 4: Hardening](docs/specs/PHASE_4_SPEC.md) - Production readiness (1 week)

### Development
- [CLAUDE.md](CLAUDE.md) - Development guide for Claude Code integration

## 🏗️ Project Status

**Current Phase**: Documentation & Planning Complete

**Roadmap**:
- [x] Architecture design
- [x] Phased delivery plan
- [x] Comprehensive specifications
- [ ] Phase 1: Foundation (Planned)
- [ ] Phase 2: Extraction (Planned)
- [ ] Phase 3: Optimization (Planned)
- [ ] Phase 4: Production (Planned)

## 🛠️ Tech Stack

- **Language**: Python 3.10+
- **Data Models**: Pydantic
- **APIs**: Semantic Scholar, Claude/Gemini
- **PDF Processing**: marker-pdf
- **Async**: asyncio + aiohttp
- **CLI**: typer
- **Testing**: pytest
- **Observability**: structlog + Prometheus + Grafana

## 📊 Expected Performance

- **Processing Speed**: 50 papers in <30 minutes
- **Cache Hit Rate**: >60% on repeated queries
- **Deduplication**: >95% accuracy
- **Cost Efficiency**: 40% reduction through smart filtering
- **Test Coverage**: >80%

## 🤝 Contributing

This project is currently in the planning phase. Contributions will be welcome once Phase 1 is complete.

## 📝 License

MIT License - see LICENSE file for details

## 📧 Contact

- **Repository**: https://github.com/leixiaoyu/research-assistant
- **Issues**: https://github.com/leixiaoyu/research-assistant/issues

## 🙏 Acknowledgments

- Semantic Scholar for research paper API
- marker-pdf for PDF conversion
- Anthropic & Google for LLM APIs

---

**Built with ❤️ for research teams**
