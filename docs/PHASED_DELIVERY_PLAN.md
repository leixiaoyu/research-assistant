# ARISP Phased Delivery Plan
**Automated Research Ingestion & Synthesis Pipeline**

**Version:** 1.7
**Date:** 2026-02-24
**Status:** Phase 5.1 Complete, Phase 5.2 Planning

---

## Executive Summary

This document outlines a phased delivery plan to build the Automated Research Ingestion & Synthesis Pipeline (ARISP) from concept to production-grade service.

### Timeline Overview
```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Phase 1  │Phase 1.5 │ Phase 2  │Phase 2.5 │ Phase 3  │Phase 3.1 │Phase 3.3 │Phase 5.1 │Phase 5.2 │
│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│(Planning)│
│          │          │          │          │          │          │          │          │          │
│Foundation│ Stabilize│Extraction│Reliability│Intelligence│Concurrent│Resilience│LLM       │Discovery │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
    MVP       Unblock     Full     Production  Optimize   Async      LLM        Decompose  Multi-
  Working     Phase 2    Features   Hardened   Grade      Workers    Fallback   Service    Provider
  End-to-End  ArXiv      + LLM    PDF Extract Performance Orchestration          Modular    Discovery
```

### Investment & Returns

| Metric | Value |
|--------|-------|
| **Development Time** | 3-4 weeks remaining |
| **Team Size** | 2-3 engineers |
| **Infrastructure Cost** | ~$100/month (LLM + hosting) |
| **Expected Savings** | 15+ hours/week of manual research |
| **ROI Timeframe** | 2-3 months |

---

## Phase Breakdown

[... Phases 1 to 3.1 remain unchanged ...]

### Phase 3.3: LLM Resilience & Provider Fallback
**Status:** ✅ **COMPLETED** (Feb 8, 2026)
**Duration:** 1 week
**Dependencies:** Phase 3.1 Complete
**Goal:** Production-grade LLM reliability with retries and failover

#### Key Deliverables
✅ `RetryHandler` with exponential backoff and jitter
✅ `CircuitBreaker` pattern for provider health management
✅ Multi-provider failover (Gemini <-> Claude)
✅ Per-provider usage and health tracking
✅ 100% test coverage for resilience components

#### Success Metrics
- 100% extraction success rate during transient API failures
- Automatic switch to fallback provider when quota is exhausted
- Zero pipeline crashes due to LLM provider outages

---

### Phase 5.1: LLMService Decomposition
**Status:** ✅ **COMPLETED** (Feb 24, 2026)
**Duration:** 3-4 days
**Dependencies:** Phase 3.3 Complete
**Goal:** Decompose monolithic LLMService into modular, maintainable package

#### Problem Addressed
The original `LLMService` (838 lines, 26 functions) violated the Single Responsibility Principle by handling 10 distinct responsibilities: provider abstraction, client initialization, retry logic, circuit breaker integration, fallback orchestration, cost tracking, prompt building, response parsing, health monitoring, and metrics export.

#### Key Deliverables
✅ Abstract `LLMProvider` interface with standardized response format
✅ `AnthropicProvider` for Claude models (<150 lines)
✅ `GoogleProvider` for Gemini models (<150 lines)
✅ `CostTracker` for budget enforcement and usage tracking
✅ `PromptBuilder` for structured extraction prompts
✅ `ResponseParser` for JSON response handling
✅ Backward-compatible imports (`from src.services.llm_service import LLMService`)
✅ 100% test coverage for all new modules

#### Package Structure
```
src/services/llm/
├── __init__.py           # Re-export LLMService for backward compat
├── service.py            # Main LLMService orchestrator (<200 lines)
├── providers/
│   ├── __init__.py
│   ├── base.py           # Abstract LLMProvider
│   ├── anthropic.py      # AnthropicProvider
│   └── google.py         # GoogleProvider
├── cost_tracker.py       # CostTracker class
├── prompt_builder.py     # PromptBuilder class
├── response_parser.py    # ResponseParser class
└── health.py             # ProviderHealth dataclass
```

#### Success Metrics
- 838-line monolith → 6-7 focused modules, each <150 lines
- All 442+ existing tests pass unchanged
- Coverage maintained at ≥99%
- Zero breaking changes to existing callers

---

### Phase 3.5: Global Paper Identity & Incremental Backfilling
**Duration:** 1 week
**Status:** 📋 **PLANNING**
**Dependencies:** Phase 3.2 (Multi-provider) & Phase 3.3 (Resilience)
**Goal:** Shift from topic-local to system-global paper management.

#### Problem Statement
Redundant processing of the same paper across multiple topics and inability to "backfill" missing data when research requirements evolve.

#### Key Deliverables
- `RegistryService` for global paper tracking
- Multi-key identity resolution (DOI, Provider ID, Fuzzy Title)
- Incremental backfilling logic for extraction requirement drift
- Zero-cost cross-topic mapping

#### Security Requirements (MANDATORY) 🔒
- [ ] SR-3.5.1: Registry file permissions restricted (0600)
- [ ] SR-3.5.2: Atomic state operations (.tmp -> rename)
- [ ] SR-3.5.3: DOI and ID format validation
- [ ] SR-3.5.4: SHA-256 for extraction target hashing

#### Verification Requirements (MANDATORY) ✅
- [ ] Unit test coverage >= 99% for registry and identity components
- [ ] Integration tests for cross-topic deduplication
- [ ] Integration tests for backfill trigger and execution
- [ ] Verification of state consistency during concurrent runs

---

### Phase 3.6: Cumulative Knowledge Synthesis
**Duration:** 1 week
**Status:** 📋 **PLANNING**
**Dependencies:** Phase 3.5 Complete
**Goal:** Transform fragmented run logs into a cohesive, cumulative Knowledge Base.

#### Key Deliverables
- `SynthesisEngine` for cumulative master document generation
- Dual-stream output: `runs/Delta.md` and `Knowledge_Base.md`
- Anchor-based persistence for manual user notes
- Folder structure evolution for organized workspace

#### Security Requirements (MANDATORY) 🔒
- [ ] SR-3.6.1: Path sanitization for folder and slug generation
- [ ] SR-3.6.2: Anchor tag regex validation to prevent script injection
- [ ] SR-3.6.3: Atomic backup before KB re-synthesis
- [ ] SR-3.6.4: Content integrity validation for registry data

#### Verification Requirements (MANDATORY) ✅
- [ ] Unit tests for synthesis logic and note preservation
- [ ] Integration tests for dual-stream generation
- [ ] Verification of quality-ranked sorting in Knowledge Base
- [ ] 100% test coverage for synthesis components

---

### Phase 4: Production Hardening
**Duration:** 1 week
**Dependencies:** Phase 3.6 (with security gates passed)
**Goal:** Observable, maintainable, production-ready service

#### Key Deliverables
- Structured logging (JSON + correlation IDs)
- Prometheus metrics
- Comprehensive test suite (>99% coverage)
- Automated scheduling
- Grafana dashboards
- Health checks and alerts
- Deployment configs (Docker, systemd)
- Operational runbook

#### Success Metrics
- All errors traceable via correlation IDs
- Key metrics visualized in Grafana
- Test coverage > 99%
- Zero-downtime deployments
- Mean time to recovery < 15 minutes
- All security audits passed

---

## Success Criteria

### Functional Requirements
- [x] Process 50 papers in < 30 minutes
- [x] Resilient LLM extraction with provider failover
- [ ] Global deduplication across all topics
- [ ] Automated backfilling of evolving research goals
- [ ] Persistent, quality-ranked Knowledge Base per topic
- [ ] Preservation of user notes across automated updates

### Non-Functional Requirements
- [ ] 99.9% pipeline reliability
- [ ] Mean time to recovery < 10 minutes
- [ ] Test coverage >= 99% project-wide
- [ ] Zero security vulnerabilities (verified by scan)

[... Remaining sections unchanged ...]
