# ARISP Phased Delivery Plan
**Automated Research Ingestion & Synthesis Pipeline**

**Version:** 1.8
**Date:** 2026-02-25
**Status:** Phase 5.2 Complete, Phase 5.3 Planning

---

## Executive Summary

This document outlines a phased delivery plan to build the Automated Research Ingestion & Synthesis Pipeline (ARISP) from concept to production-grade service.

### Timeline Overview
```
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Phase 1  │Phase 1.5 │ Phase 2  │Phase 2.5 │ Phase 3  │Phase 3.1 │Phase 3.3 │Phase 3.4 │Phase 3.5 │
│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│
│          │          │          │          │          │          │          │          │          │
│Foundation│ Stabilize│Extraction│Reliability│Intelligence│Concurrent│Resilience│HuggingFace│Registry │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘

┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│Phase 3.6 │Phase 3.7 │Phase 5.1 │Phase 5.2 │Phase 5.3 │Phase 5.4 │Phase 5.5 │
│✅Complete│✅Complete│✅Complete│✅Complete│(Planning)│(Future)  │(Future)  │
│          │          │          │          │          │          │          │
│ Delta    │Cross-    │   LLM    │Research  │   CLI    │ Utility  │ Model    │
│ Briefs   │Synthesis │ Decompose│ Pipeline │ Commands │ Patterns │Consolid. │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
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

### Phase 3.4: Multi-Provider Discovery (HuggingFace)
**Status:** ✅ **COMPLETED** (Feb 2026)
**Duration:** 3-4 days
**Dependencies:** Phase 3.3 Complete
**Goal:** Expand paper discovery beyond Semantic Scholar

#### Key Deliverables
✅ `HuggingFaceProvider` for HuggingFace Daily Papers API
✅ Provider abstraction via `BaseProvider` interface
✅ Multi-provider orchestration in DiscoveryService
✅ Benchmark mode for cross-provider comparison
✅ Quality filtering and paper deduplication
✅ 100% test coverage

#### Success Metrics
- Additional paper source integrated
- Cross-provider deduplication working
- Provider-agnostic paper processing

---

### Phase 3.5: Global Paper Identity & Registry
**Status:** ✅ **COMPLETED** (Feb 2026)
**Duration:** 1 week
**Dependencies:** Phase 3.4 Complete
**Goal:** System-global paper management with identity resolution

#### Key Deliverables
✅ `RegistryService` for global paper tracking
✅ Multi-key identity resolution (DOI, ArXiv ID, Semantic Scholar ID)
✅ `RegistryEntry` model with validated identifiers
✅ Atomic state operations with file locking
✅ SHA-256 extraction target hashing
✅ 100% test coverage

#### Security Requirements (COMPLETED) 🔒
✅ SR-3.5.1: Registry file permissions restricted (0600)
✅ SR-3.5.2: Atomic state operations (.tmp -> rename)
✅ SR-3.5.3: DOI and ID format validation
✅ SR-3.5.4: SHA-256 for extraction target hashing

---

### Phase 3.6: Delta Briefs & Incremental Output
**Status:** ✅ **COMPLETED** (Feb 2026)
**Duration:** 1 week
**Dependencies:** Phase 3.5 Complete
**Goal:** Generate incremental delta briefs for each run

#### Key Deliverables
✅ `DeltaGenerator` for delta brief creation
✅ `ProcessingResult` model with status tracking
✅ Quality-ranked paper sections
✅ Dual-stream output: `runs/YYYY-MM-DD_Delta.md`
✅ Path sanitization for folder and slug generation
✅ 100% test coverage

---

### Phase 3.7: Cross-Topic Synthesis
**Status:** ✅ **COMPLETED** (Feb 2026)
**Duration:** 1 week
**Dependencies:** Phase 3.6 Complete
**Goal:** LLM-powered synthesis across multiple research topics

#### Key Deliverables
✅ `CrossTopicSynthesisService` for multi-topic analysis
✅ `SynthesisQuestion` configurable question templates
✅ Quality-weighted paper selection
✅ Diversity sampling across topics
✅ Budget management and cost tracking
✅ Incremental synthesis mode
✅ `CrossTopicSynthesisGenerator` for output generation
✅ 100% test coverage

---

### Phase 5.1: LLMService Decomposition
**Status:** ✅ **COMPLETED** (Feb 24, 2026)
**Duration:** 3-4 days
**Dependencies:** Phase 3.7 Complete
**Goal:** Decompose monolithic LLMService into modular, maintainable package

#### Problem Addressed
The original `LLMService` (838 lines, 26 functions) violated the Single Responsibility Principle by handling 10 distinct responsibilities: provider abstraction, client initialization, retry logic, circuit breaker integration, fallback orchestration, cost tracking, prompt building, response parsing, health monitoring, and metrics export.

#### Key Deliverables
✅ Provider logic extracted to `src/services/llm/providers/` (anthropic.py, google.py)
✅ Cost tracking, prompt building, response parsing as separate modules
✅ Backward-compatible imports preserved
✅ 100% test coverage maintained

**Details:** See [PHASE_5.1_SPEC.md](specs/PHASE_5.1_SPEC.md) for full package structure and file sizes.

---

### Phase 5.2: ResearchPipeline Phase Extraction
**Status:** ✅ **COMPLETED** (Feb 25, 2026)
**Duration:** 3-4 days
**Dependencies:** Phase 5.1 Complete
**Goal:** Decompose monolithic ResearchPipeline into modular phase-based architecture

#### Problem Addressed
The original `ResearchPipeline` (824 lines, 14 functions) handled all pipeline phases in a single class: configuration, service initialization, discovery orchestration, extraction, synthesis, and cross-topic synthesis.

#### Key Deliverables
✅ Phase-based architecture: DiscoveryPhase, ExtractionPhase, SynthesisPhase, CrossSynthesisPhase
✅ Shared PipelineContext for state management
✅ Backward-compatible ResearchPipeline API preserved
✅ 100% test coverage maintained

**Details:** See [PHASE_5.2_SPEC.md](specs/PHASE_5.2_SPEC.md) for full package structure and file sizes.

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
- [x] Multi-provider discovery (Semantic Scholar, ArXiv, HuggingFace)
- [x] Global deduplication across all topics
- [x] Quality-ranked delta briefs per topic
- [x] Cross-topic synthesis with configurable questions
- [ ] Automated backfilling of evolving research goals
- [ ] Preservation of user notes across automated updates

### Non-Functional Requirements
- [ ] 99.9% pipeline reliability
- [ ] Mean time to recovery < 10 minutes
- [x] Test coverage >= 99% project-wide (currently 99.92%)
- [ ] Zero security vulnerabilities (verified by scan)

[... Remaining sections unchanged ...]
