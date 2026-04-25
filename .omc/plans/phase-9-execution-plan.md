# Phase 9: Research Intelligence Layer - Execution Plan

**Version:** 1.1
**Created:** 2026-04-22
**Updated:** 2026-04-23
**Author:** Planner (Prometheus)
**Status:** REVISED - Corrected Track C dependency on Track B per team review

---

## Executive Summary

This plan details the week-by-week execution strategy for Phase 9: Research Intelligence Layer. The phase introduces four milestones (Monitoring, Citation Graph, Knowledge Graph, Frontier Detection) that transform ARISP from a reactive paper discovery system into a proactive, relationship-aware research intelligence platform.

**Key Insight from Spec:** Two tracks can run in parallel (9.1 Monitoring, 9.2 Citation), while both 9.3 Knowledge Graph and 9.4 Frontier Detection depend on 9.2 Citation Graph completion (9.4 requires citation burst and citation saturation data per REQ-9.4.2 and REQ-9.4.3). This still enables timeline optimization through early parallel work.

---

## Context

### Dependencies (Verified Complete)
- Phase 8 Complete (Deep Research Agent with corpus, browser, agent loop)
- Phase 3.5 Complete (Global Paper Registry)
- Phase 6 Core Complete (Enhanced Discovery with multi-provider support)

### Goal
Expand discovery capabilities to inject more papers into the learning synthesis process through:
1. Proactive paper monitoring (awareness intelligence)
2. Citation graph intelligence (relationship intelligence)
3. Knowledge graph synthesis (fact-level intelligence)
4. Research frontier detection (strategic intelligence)

---

## Work Objectives

### Primary Objectives
1. Implement all four Phase 9 milestones with 99%+ test coverage
2. Maintain parallel track execution where possible to optimize timeline
3. Ensure seamless integration with existing DRA, Discovery, and Registry services
4. Follow complete OMC workflow cycle for each track: autopilot -> code review -> ultraqa

### Secondary Objectives
1. Create shared infrastructure (GraphStore interface) usable by all milestones
2. Document all architectural decisions and integration points
3. Minimize LLM costs through tiered model selection and caching

---

## Guardrails

### Must Have
- 99%+ test coverage for all new modules (CLAUDE.md requirement)
- 100% test pass rate (0 failures)
- All security requirements (SR-9.1 through SR-9.5) verified
- GraphStore abstraction layer for SQLite -> Neo4j migration path
- Pydantic V2 models with strict validation for all data structures
- Structured logging with correlation IDs
- Rate limiting for all external API calls (S2, OpenAlex, ArXiv)
- Foreign key constraints and atomic transactions for graph integrity

### Must NOT Have
- Direct SQLite calls bypassing GraphStore interface
- Hardcoded API keys or credentials
- Breaking changes to existing CLI commands or APIs
- Entity resolution false merges (conservative thresholds only)
- Real-time streaming (batch/scheduled only per spec)
- Multi-user authentication (deferred to Phase 10+)

---

## Parallel Track Strategy

```
Week   0   1   2   3   4   5   6   7   8   9  10  11
       |---|---|---|---|---|---|---|---|---|---|---|
       |PRE|                                       |
       |   |=== TRACK A: 9.1 Monitoring (2w) ===| |
       |   |====== TRACK B: 9.2 Citation (3w) =====|
       |               |=== TRACK C: 9.4 Frontier (3w) ===|
       |               |====== TRACK D: 9.3 Knowledge (4w) ======|
       |                                           |=== INT ===|

PRE = Week 0: Shared Infrastructure (GraphStore, models, migrations)
INT = Weeks 10-11: Integration & Polish

Note: Track C (9.4 Frontier) depends on Track B (9.2 Citation) because
REQ-9.4.2 requires "citation burst" detection and REQ-9.4.3 requires
"citation saturation" analysis - both need citation graph data.
```

### Track Assignments

| Track | Milestone | Duration | Parallel? | Dependencies |
|-------|-----------|----------|-----------|--------------|
| **Prerequisite** | Shared Infrastructure | Week 0 | No | None |
| **Track A** | 9.1 Monitoring | Weeks 1-2 | Yes (with B) | Shared infra |
| **Track B** | 9.2 Citation Graph | Weeks 1-3 | Yes (with A) | Shared infra |
| **Track C** | 9.4 Frontier Detection | Weeks 4-6 | Yes (with D) | **9.2 complete** |
| **Track D** | 9.3 Knowledge Graph | Weeks 4-7 | Yes (with C) | 9.2 complete |
| **Integration** | Full Integration | Weeks 10-11 | No | All tracks |

---

## Task Flow

### Week 0: Shared Infrastructure (Prerequisite)

**Objective:** Build foundation used by all milestones

**Deliverables:**
1. `src/services/intelligence/__init__.py` - Package initialization
2. `src/services/intelligence/models.py` - Shared data models (NodeType, EdgeType, etc.)
3. `src/services/intelligence/storage/unified_graph.py` - GraphStore Protocol + SQLite implementation
4. `src/services/intelligence/storage/migrations.py` - Schema migrations
5. `src/services/intelligence/storage/time_series.py` - Temporal data storage

**Detailed TODOs:**

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| 0.1 | Create intelligence package structure | Directory structure matches spec Section 3.2 |
| 0.2 | Implement NodeType and EdgeType enums | All types from spec Section 8.1 defined |
| 0.3 | Define GraphStore Protocol | Protocol matches spec Section 16.1 with all methods |
| 0.4 | Implement SQLiteGraphStore | CRUD for nodes/edges, traverse(), pagerank() stub |
| 0.5 | Create schema migrations | Tables: nodes, edges, time_series, subscriptions |
| 0.6 | Add PRAGMA foreign_keys enforcement | Connection initialization always enables FK |
| 0.7 | Implement optimistic locking | Version column with conflict detection |
| 0.8 | Write unit tests | 99%+ coverage for storage layer |

**Review Gate:** Code review after Week 0 completion

---

### Week 1-2: Track A - Milestone 9.1 Monitoring

**Objective:** Implement proactive paper monitoring with subscriptions and digests

**Package:** `src/services/intelligence/monitoring/`

**Week 1 Deliverables:**
- `subscription_manager.py` - CRUD for research subscriptions
- `arxiv_monitor.py` - ArXiv RSS/API monitoring
- Data models (ResearchSubscription, PaperSource, etc.)

**Week 2 Deliverables:**
- `relevance_scorer.py` - LLM-based relevance scoring
- `digest_generator.py` - Daily/weekly digest generation
- CLI commands: `arisp monitor add/list/check/digest`

**Detailed TODOs:**

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| 1.1 | Implement ResearchSubscription model | Pydantic V2, all fields from REQ-9.1.1 |
| 1.2 | Build SubscriptionManager | CRUD operations, validation, persistence to SQLite |
| 1.3 | Implement ArXivMonitor | RSS parsing with feedparser, date filtering |
| 1.4 | Add rate limiting for ArXiv | Max 3 req/sec enforced |
| 1.5 | Implement deduplication | Skip papers already in registry |
| 1.6 | Build RelevanceScorer | Gemini Flash for cost efficiency |
| 1.7 | Implement DigestGenerator | Daily digest with paper summaries |
| 1.8 | Create CLI commands | All commands from Section 4.3 |
| 1.9 | Write integration tests | End-to-end subscription -> digest flow |
| 1.10 | Integration with Registry | New papers added to registry |

**Success Criteria (from spec Section 13.1):**
- Paper detection latency < 24h from ArXiv publication
- Relevance precision > 80%
- Digest generation time < 30s
- Subscription CRUD 100% reliability

**Review Gate:** Code review + UltraQA after Week 2

---

### Week 1-3: Track B - Milestone 9.2 Citation Graph

**Objective:** Build citation graph for relationship-based paper discovery

**Package:** `src/services/intelligence/citation/`

**Week 1 Deliverables:**
- `graph_builder.py` - Build citation graph from APIs
- Semantic Scholar API integration
- OpenAlex API integration (fallback)

**Week 2 Deliverables:**
- `crawler.py` - BFS citation chain crawling
- `coupling_analyzer.py` - Bibliographic coupling analysis

**Week 3 Deliverables:**
- `influence_scorer.py` - PageRank, HITS scores
- `recommender.py` - Citation-based recommendations
- CLI commands: `arisp citation build/related/influence`

**Detailed TODOs:**

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| 2.1 | Implement CitationNode model | All fields from REQ-9.2.1 |
| 2.2 | Implement CitationEdge model | With context and section fields |
| 2.3 | Build SemanticScholarClient | Rate limited (100 req/5min) |
| 2.4 | Build OpenAlexClient (fallback) | Polite pool with email |
| 2.5 | Implement GraphBuilder | Fetch references and citations |
| 2.6 | Implement BFS Crawler | CrawlConfig with depth/direction |
| 2.7 | Add sort_by_influence ranking | influentialCitationCount, citationCount, date |
| 2.8 | Implement CouplingAnalyzer | Jaccard similarity of references |
| 2.9 | Implement InfluenceScorer | PageRank over citation graph |
| 2.10 | Build Recommender | Similar, influential, active, bridge papers |
| 2.11 | Create CLI commands | All commands from Section 5.3 |
| 2.12 | Write integration tests | API mocking, full crawl flow |

**Success Criteria (from spec Section 13.2):**
- Graph build time < 60s for depth=2
- Citation coverage > 95% of S2 data
- Coupling accuracy > 85%
- Related paper precision > 70%

**Review Gate:** Code review + UltraQA after Week 3

**Handoff:** Citation graph data available for 9.3 Knowledge Graph

---

### Week 4-6: Track C - Milestone 9.4 Frontier Detection

**Objective:** Identify emerging trends, saturated areas, and research gaps

**Package:** `src/services/intelligence/frontier/`

**Dependencies:** Milestone 9.2 Citation Graph must be complete (requires citation burst and citation saturation data per REQ-9.4.2 and REQ-9.4.3)

**Week 4 Deliverables:**
- `trend_analyzer.py` - Topic velocity tracking
- Time series data collection
- Integration with citation graph data

**Week 5 Deliverables:**
- `emergence_detector.py` - New concept detection (uses citation burst from 9.2)
- `saturation_scorer.py` - Topic maturity scoring (uses citation saturation from 9.2)

**Week 6 Deliverables:**
- `gap_finder.py` - Research gap detection
- `strategic_advisor.py` - Research recommendations
- CLI commands: `arisp frontier trends/gaps/recommend`

**Detailed TODOs:**

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| 4.1 | Implement TopicTrend model | TrendPoint time series, TrendStatus enum |
| 4.2 | Build TrendAnalyzer | Velocity and acceleration calculation |
| 4.3 | Implement EmergingConcept model | All fields from REQ-9.4.2 |
| 4.4 | Build EmergenceDetector | Term frequency, citation burst detection |
| 4.5 | Implement SaturationAnalysis model | Novelty decay, result plateau signals |
| 4.6 | Build SaturationScorer | Newcomer ratio, citation saturation |
| 4.7 | Implement ResearchGap model | GapType enum, opportunity score |
| 4.8 | Build GapFinder | Intersection analysis, method-domain matrix |
| 4.9 | Implement StrategicRecommendation model | Difficulty and impact estimates |
| 4.10 | Build StrategicAdvisor | Recommendation generation |
| 4.11 | Create CLI commands | All commands from Section 7.3 |
| 4.12 | Write integration tests | Trend calculation, gap detection |

**Success Criteria (from spec Section 13.4):**
- Trend prediction accuracy > 70%
- Gap identification precision > 60%
- Recommendation usefulness > 3.5/5

**Review Gate:** Code review + UltraQA after Week 6

---

### Week 4-7: Track D - Milestone 9.3 Knowledge Graph

**Objective:** Extract and connect facts across papers for comparative analysis

**Package:** `src/services/intelligence/knowledge/`

**Dependencies:** Milestone 9.2 Citation Graph must be complete (uses graph data)

**Week 4 Deliverables:**
- `entity_extractor.py` - Structured entity extraction
- Extraction prompt templates

**Week 5 Deliverables:**
- `relation_linker.py` - Relationship extraction
- `graph_store.py` - Knowledge graph storage integration

**Week 6 Deliverables:**
- Entity resolution (conservative auto-merge)
- `query_engine.py` - Natural language queries

**Week 7 Deliverables:**
- `contradiction_detector.py` - Conflicting claims detection
- CLI commands: `arisp knowledge extract/query/compare`

**Detailed TODOs:**

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| 3.1 | Implement EntityType enum | All types: METHOD, DATASET, METRIC, MODEL, TASK, RESULT, HYPERPARAM |
| 3.2 | Implement ExtractedEntity model | With confidence scores, aliases |
| 3.3 | Build EntityExtractor | Claude Sonnet for quality |
| 3.4 | Design extraction prompts | Section-aware extraction |
| 3.5 | Implement RelationType enum | ACHIEVES, USES, EVALUATES_ON, IMPROVES, etc. |
| 3.6 | Implement ExtractedRelation model | With context and confidence |
| 3.7 | Build RelationLinker | Entity-to-entity relationship extraction |
| 3.8 | Implement EntityCluster model | For entity resolution |
| 3.9 | Build conservative entity resolution | Exact match + alias match only for AUTO_MERGE |
| 3.10 | Implement KnowledgeQuery model | QueryType enum |
| 3.11 | Build QueryEngine | ENTITY_SEARCH, RELATION_SEARCH, COMPARISON, AGGREGATION |
| 3.12 | Implement Contradiction model | ContradictionType, severity scoring |
| 3.13 | Build ContradictionDetector | Result conflict, claim conflict detection |
| 3.14 | Create CLI commands | All commands from Section 6.3 |
| 3.15 | Write integration tests | Full extraction -> query flow |

**Success Criteria (from spec Section 13.3):**
- Entity extraction precision > 85%
- Entity extraction recall > 75%
- Relation extraction F1 > 70%
- Query latency < 2s

**Review Gate:** Code review + UltraQA after Week 7

---

### Week 10-11: Integration & Polish

**Objective:** Full system integration and production readiness

**Week 10 Deliverables:**
- DRA Browser V2 with new primitives (cite_expand, knowledge_query, frontier_status)
- Enhanced Discovery Service V2 with citation expansion
- Monitoring -> Registry -> DRA Corpus integration

**Week 11 Deliverables:**
- Performance benchmarks
- User documentation
- Final test coverage verification (99%+ overall)

**Detailed TODOs:**

| ID | Task | Acceptance Criteria |
|----|------|---------------------|
| 5.1 | Implement ResearchBrowserV2 | cite_expand(), knowledge_query(), frontier_status() |
| 5.2 | Update DRA system prompt | Include Phase 9 tool documentation |
| 5.3 | Implement EnhancedDiscoveryServiceV2 | Citation expansion, knowledge filtering |
| 5.4 | Wire monitoring -> registry | Auto-register high-relevance papers |
| 5.5 | Wire monitoring -> corpus | Auto-ingest for score >= 0.9 |
| 5.6 | Create unified_query.py | Cross-layer query engine |
| 5.7 | Performance benchmark | All timing targets from spec |
| 5.8 | Write user documentation | CLI usage, configuration examples |
| 5.9 | Final coverage verification | 99%+ with documented gaps |
| 5.10 | Integration regression tests | Verify no breaks to existing features |

**Review Gate:** Final UltraQA + Production readiness review

---

## Success Criteria

### Per-Milestone Verification
Each milestone must pass before proceeding:

1. **Test Coverage:** 99%+ for all new modules
2. **Test Pass Rate:** 100% (0 failures)
3. **Code Quality:** Black, Flake8, Mypy clean
4. **Security:** All SR-9.x requirements verified
5. **Documentation:** Docstrings complete, CLI --help accurate
6. **Integration:** No regressions to existing functionality

### Phase 9 Overall Success
- All four milestones complete and integrated
- DRA Browser enhanced with 3 new primitives
- 99%+ overall test coverage maintained
- Performance targets met (see spec Section 13)
- User documentation complete

---

## Risk Mitigation Strategies

| Risk | Mitigation |
|------|------------|
| API rate limits too restrictive | Aggressive caching (24h TTL relevance, 7d TTL citations), request batching |
| LLM extraction quality insufficient | Iterative prompt tuning, conservative confidence thresholds |
| Graph storage too slow at scale | GraphStore abstraction ready for Neo4j migration |
| Entity resolution false merges | Conservative thresholds (exact + alias only for AUTO_MERGE) |
| Trend detection too noisy | Longer time windows, smoothing, manual validation |
| Scope creep delays milestones | Strict MVP scope per milestone (spec Section 16.8) |
| Citation data incomplete for recent papers | Multi-source fallback (S2 -> OpenAlex) |
| Cost exceeds budget | Tiered models (Gemini Flash for scoring, Sonnet for extraction) |

---

## Handoff Points

### Track A (9.1) -> Integration
- Subscription data available in SQLite
- New paper stream for registry integration
- Digest generation ready for notification hooks

### Track B (9.2) -> Track D (9.3)
- Citation graph populated with nodes and edges
- GraphStore API available for knowledge graph
- Influence metrics computed for paper ranking

### Track C (9.4) -> Integration
- Trend data in time_series table
- Frontier status queryable by topic
- Gap analysis available for recommendations

### Track D (9.3) -> Integration
- Entity and relation data in graph
- Query engine ready for DRA integration
- Contradiction data for research insights

---

## Review/QA Gates

| Gate | Timing | Scope | Exit Criteria |
|------|--------|-------|---------------|
| G0 | End Week 0 | Shared Infrastructure | GraphStore tests pass, schema migrations work |
| G1 | End Week 2 | Track A (9.1 Monitoring) | All 9.1 tests pass, CLI functional |
| G2 | End Week 3 | Track B (9.2 Citation) | All 9.2 tests pass, graph builds correctly |
| G3 | End Week 6 | Track C (9.4 Frontier) | All 9.4 tests pass, trends calculated (uses citation data) |
| G4 | End Week 7 | Track D (9.3 Knowledge) | All 9.3 tests pass, queries work |
| G5 | End Week 11 | Full Integration | All integration tests pass, 99%+ coverage |

### Gate Protocol
1. **autopilot** completes implementation
2. **Code review** verifies quality, security, coverage
3. **ultraqa** validates functionality end-to-end
4. Gate passes only when all three approve

---

## Integration Milestones

| Milestone | Week | Integration Points |
|-----------|------|-------------------|
| IM1 | Week 2 | Monitoring -> Registry (new paper registration) |
| IM2 | Week 3 | Citation -> Discovery (expansion in search) |
| IM3 | Week 6 | Frontier -> Monitoring (priority boost for emerging topics) |
| IM4 | Week 7 | Knowledge -> DRA (knowledge_query primitive) |
| IM5 | Week 11 | Full DRA V2 (all primitives integrated) |

---

## Estimated Effort

| Track | Duration | Complexity |
|-------|----------|------------|
| Week 0: Shared Infra | 1 week | MEDIUM |
| Track A: 9.1 Monitoring | 2 weeks (Weeks 1-2) | LOW-MEDIUM |
| Track B: 9.2 Citation | 3 weeks (Weeks 1-3) | MEDIUM |
| Track C: 9.4 Frontier | 3 weeks (Weeks 4-6) | MEDIUM |
| Track D: 9.3 Knowledge | 4 weeks (Weeks 4-7) | HIGH |
| Integration | 2 weeks (Weeks 10-11) | MEDIUM |
| **Total** | **11-12 weeks** | N/A |

**Note:** Parallelization of Tracks A and B during Weeks 1-3, and Tracks C and D during Weeks 4-7, reduces total timeline from 15 sequential weeks to ~11 weeks. Track C (9.4 Frontier) must wait for Track B (9.2 Citation) because it requires citation burst and citation saturation data (REQ-9.4.2, REQ-9.4.3).

---

## Open Questions (Persisted)

See `/Users/raymondl/Documents/research-assist/.omc/plans/open-questions.md` for tracked decisions and open items.

### Resolved (2026-04-22/23)

1. ✅ **Digest delivery mechanism** - RESOLVED: File-based MVP (`./output/digests/`)

2. ✅ **Monitoring schedule persistence** - RESOLVED: Use APScheduler with `MonitoringCheckJob(BaseJob)` subclass, following the pattern of existing scheduled jobs (DRACorpusRefreshJob, DailyResearchJob)

3. ✅ **Auto-ingest threshold** - RESOLVED: Relevance >= 0.7 for auto-ingest to DRA corpus

### Still Open

1. **Neo4j trigger threshold** - Spec says "migrate when >100K nodes" but should we start monitoring node count proactively?

2. **Multi-user field usage** - `user_id: str = Field(default="default")` is in spec, but should we index this field now or defer?

---

## Appendix: File Structure

```
src/services/intelligence/
├── __init__.py
├── models.py                    # Shared data models
│
├── monitoring/                  # Milestone 9.1
│   ├── __init__.py
│   ├── subscription_manager.py
│   ├── arxiv_monitor.py
│   ├── relevance_scorer.py
│   └── digest_generator.py
│
├── citation/                    # Milestone 9.2
│   ├── __init__.py
│   ├── graph_builder.py
│   ├── crawler.py
│   ├── coupling_analyzer.py
│   ├── influence_scorer.py
│   └── recommender.py
│
├── knowledge/                   # Milestone 9.3
│   ├── __init__.py
│   ├── entity_extractor.py
│   ├── relation_linker.py
│   ├── graph_store.py
│   ├── query_engine.py
│   └── contradiction_detector.py
│
├── frontier/                    # Milestone 9.4
│   ├── __init__.py
│   ├── trend_analyzer.py
│   ├── emergence_detector.py
│   ├── saturation_scorer.py
│   ├── gap_finder.py
│   └── strategic_advisor.py
│
├── storage/                     # Unified storage layer
│   ├── __init__.py
│   ├── unified_graph.py
│   ├── time_series.py
│   └── migrations.py
│
└── unified_query.py             # Cross-layer query engine
```

---

**Document Status:** DRAFT
**Next Step:** User confirmation required before handoff to implementation
