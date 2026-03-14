# ARISP Phased Delivery Plan
**Automated Research Ingestion & Synthesis Pipeline**

**Version:** 2.0
**Date:** 2026-03-11
**Status:** Phase 6 Cleanup Complete (Deprecated Modules Removed)

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

┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│Phase 3.6 │Phase 3.7 │Phase 5.1 │Phase 5.2 │Phase 5.3 │Phase 5.4 │Phase 5.5 │ Phase 6  │
│✅Complete│✅Complete│✅Complete│✅Complete│✅Complete│(Future)  │(Future)  │🔄 Core   │
│          │          │          │          │          │          │          │ Complete │
│ Delta    │Cross-    │   LLM    │Research  │   CLI    │ Utility  │ Model    │ Enhanced │
│ Briefs   │Synthesis │ Decompose│ Pipeline │ Commands │ Patterns │Consolid. │ Discovery│
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
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

### Phase 5.3: CLI Command Splitting
**Status:** ✅ **COMPLETED** (Feb 28, 2026)
**Duration:** 2 days
**Dependencies:** Phase 5.2 Complete
**Goal:** Split monolithic CLI into modular command structure

#### Problem Addressed
The original `cli.py` (716 lines) contained all CLI commands in a single file, making it difficult to test individual commands in isolation and maintain clear separation of concerns.

#### Key Deliverables
✅ CLI package with 9 focused modules (`src/cli/`)
✅ Dedicated modules: run.py (265), schedule.py (217), synthesize.py (159), utils.py (120), catalog.py (82)
✅ Shared utilities module for config loading and error handling
✅ Backward-compatible CLI invocations preserved
✅ 51 CLI tests passing with full coverage

**Details:** See [PHASE_5.3_SPEC.md](specs/PHASE_5.3_SPEC.md) for full package structure and file sizes.

---

### Phase 6: Enhanced Discovery Pipeline
**Status:** 🔄 **IN PROGRESS** (Core Components Complete, Cleanup Done - Mar 11, 2026)
**Duration:** 2-3 weeks (estimated)
**Dependencies:** Phase 3.4 (HuggingFace Provider), Phase 5.1 (LLMService)
**Goal:** Improve paper relevance through 4-stage intelligent discovery pipeline

#### Phase 6 Cleanup (Complete - Mar 11, 2026)
✅ Removed deprecated `src/cli.py` (stub re-exporting from src.cli package)
✅ Removed deprecated `src/services/llm_service.py` (replaced by src/services/llm/)
✅ Removed deprecated `src/orchestration/research_pipeline.py` (replaced by pipeline.py)
✅ Updated all imports across source and test files
✅ Added LLM service coverage tests for edge cases
✅ 2181 tests passing with 99.25% coverage

#### Problem Addressed
Despite retrieving 90+ papers, the synthesis phase covered 0 topics due to poor paper-query relevance matching. Single-query retrieval misses semantically related papers, and API default ordering includes irrelevant results.

#### Key Deliverables (Core Components - Complete)
✅ Data models: `QueryFocus`, `DecomposedQuery`, `QualityWeights`, `ScoredPaper`, `DiscoveryMetrics`, `DiscoveryResult`
✅ `EnhancedDiscoveryConfig` model for pipeline configuration
✅ `OpenAlexProvider` for 260M+ scholarly works access
✅ `QueryDecomposer` for LLM-based query expansion (3-5 sub-queries)
✅ `QualityFilterService` with 6-signal scoring (citation, venue, recency, engagement, completeness, author)
✅ `RelevanceRanker` for LLM-based semantic relevance scoring
✅ `EnhancedDiscoveryService` orchestrating 4-stage pipeline
✅ 162 unit tests with 100% coverage on all Phase 6 modules

#### Key Deliverables (Integration - Pending)
❌ Integration with main `DiscoveryService`
❌ CLI commands for enhanced discovery mode
❌ Feature flag for gradual rollout
❌ Integration and end-to-end tests
❌ Performance benchmarking and cost analysis

#### 4-Stage Pipeline Architecture
1. **Query Decomposition** - LLM generates focused sub-queries
2. **Multi-Source Retrieval** - ArXiv, Semantic Scholar, OpenAlex (comprehensive) + HuggingFace (trending)
3. **Quality Filtering** - Multi-signal scoring with configurable weights
4. **Relevance Ranking** - LLM-based semantic relevance scoring

**Details:** See [PHASE_6_DISCOVERY_ENHANCEMENT_SPEC.md](specs/PHASE_6_DISCOVERY_ENHANCEMENT_SPEC.md) for full specification.

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
- [x] Test coverage >= 99% project-wide (currently 99.25%)
- [ ] Zero security vulnerabilities (verified by scan)

[... Remaining sections unchanged ...]
