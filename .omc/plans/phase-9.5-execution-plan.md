# Phase 9.5: Pipeline Reliability, Discovery Breadth, and Learning Synthesis - Execution Plan

**Version:** 1.0
**Created:** 2026-05-09
**Status:** DRAFT — pending user review
**Spec:** [docs/specs/PHASE_9.5_RELIABILITY_BREADTH_LEARNING_SPEC.md](../../docs/specs/PHASE_9.5_RELIABILITY_BREADTH_LEARNING_SPEC.md)

---

## Executive Summary

This plan details the four-week execution strategy for Phase 9.5, which inserts before Phases 9.3 (Knowledge Graph) and 9.4 (Frontier Detection) to address two production gaps: (1) the ingestion pipeline produces degraded output (54% PDF extraction failure, ~70% abstract-only fallback, silent provider auth failures), (2) discovery is structurally narrow (single effective provider, static topics, citation graph not in daily loop, monitoring service returning 0 new papers).

Three workstreams are executed largely sequentially because each depends on the previous: Workstream A (Reliability) gates Workstream C (Learning Synthesis) — there is no value in synthesizing when extraction is broken. Workstream B (Breadth) is largely independent of A and can run in parallel during Week 2.

---

## Context

### Dependencies (Verified Complete)
- Phase 9.1 Complete (Monitoring service) — degraded in production; will be repaired by Workstream A
- Phase 9.2 Complete (Citation graph) — built but not in daily loop; will be wired by Workstream B
- Phase 5.1 Complete (LLM Service Decomposition) — `QueryExpander` extraction in B builds on this
- Phase 3.7 Complete (Cross-Topic Synthesis) — `LearningBriefGenerator` in C builds on this

### Goal
Restore the production pipeline to producing useful per-paper extractions, then layer cross-paper weekly synthesis on top — so the user's daily output is curated learning, not a list of titles.

---

## Work Objectives

### Primary Objectives
1. Eliminate the URL-as-Path bug in `paper_processor.py` and prevent recurrence via type guard
2. Surface LLM provider failures at startup with explicit, actionable signals
3. Wire Phase 9.2 citation expansion into the daily discovery loop
4. Extract `QueryExpander` to a shared service used by both monitoring and discovery
5. Ship a weekly Learning Brief output that synthesizes per-paper extraction into cross-paper learning

### Secondary Objectives
1. Audit HuggingFace and Semantic Scholar provider PDF resolution; fix or document
2. Establish a `using_abstract_fallback` SLO indicator in daily-run logs
3. Tag candidate provenance (`source` field) for downstream attribution and diagnostics

---

## Guardrails

### Must Have
- 99%+ test coverage for all new modules (CLAUDE.md requirement)
- 100% test pass rate (0 failures)
- All security requirements (SR-9.5.A.x, SR-9.5.B.x, SR-9.5.C.x) verified
- Integration test that exercises a real ArXiv URL end-to-end (regression guard for REQ-9.5.1.1)
- All new structured-log events documented in observability docs
- Backward compatibility for existing CLI commands and config files
- LearningBriefJob registered with APScheduler following `MonitoringCheckJob` pattern

### Must NOT Have
- Direct PDF URL → Path conversion in any new code (REQ-9.5.1.2 type guard enforces)
- Silent fallback to abstract-only without logging the underlying failure cause
- Citation expansion bypassing existing rate limiters
- Learning Brief regenerating from raw PDF text (must consume only structured extraction outputs)
- Hardcoded LLM provider in any new code (provider chosen via config per OQ-9.5.1)
- New paper-discovery providers (Crossref, CORE, etc. are explicitly out of scope)

---

## Sequencing Strategy

```
Week   1   2   3   4
       |---|---|---|---|
       |== A: Reliability ==|
           |== B: Breadth ==|
               |== C: Learning ==========|

A blocks C (no value synthesizing broken extractions)
B is independent of A; runs Weeks 2-3 in parallel with C ramp-up
C ramps Week 3 (data models, generator, CLI), runs first brief Week 4
```

### Track Assignments

| Track | Workstream | Duration | Parallel? | Dependencies |
|---|---|---|---|---|
| **A** | Reliability | Week 1 | No | None |
| **B** | Breadth | Weeks 2-3 | Yes (with C ramp) | A complete (provider health needed for shared QueryExpander) |
| **C** | Learning Synthesis | Weeks 3-4 | Yes (with B) | A complete (extraction quality), B optional (broader corpus improves brief) |

---

## Task Flow

### Week 1: Workstream A — Pipeline Reliability

**Objective:** Fix the broken extraction path; make provider failures loud.

**Deliverables:**
1. `src/services/pdf_acquisition.py` — shared `acquire_pdf()` helper (new)
2. `src/orchestration/paper_processor.py` — refactored to use `acquire_pdf()`
3. `src/services/extraction_service.py` — refactored to use `acquire_pdf()`
4. PDF extractor entry-point type guard rejecting `http:`/`https:` paths
5. `src/services/llm/health_check.py` — `ProviderHealthChecker` class (new)
6. Health check invoked at startup of services in `src/services/extraction_service.py`, `src/services/intelligence/monitoring/`, `src/services/learning/` (when shipped)
7. `pipeline_health_abstract_fallback_rate` event emitted at end of `DailyResearchJob`
8. Provider audit notes: `docs/audits/2026-05_provider_pdf_audit.md`

**Detailed TODOs:**

| ID | Task | Acceptance Criteria | REQ |
|---|---|---|---|
| A.1 | Create `pdf_acquisition.py` with `acquire_pdf()` | Returns `Path` on success, `None` if no URL, raises typed exceptions on download failure | REQ-9.5.1.1 |
| A.2 | Refactor `paper_processor.py:138-145` to call `acquire_pdf()` | No `Path(str(url))` pattern remains in source; integration test with real ArXiv URL passes | REQ-9.5.1.1 |
| A.3 | Refactor `extraction_service.py:172-179` to call `acquire_pdf()` | Behavior unchanged; existing tests still pass; no duplicate download logic remains | REQ-9.5.1.1 |
| A.4 | Add type guard at extractor entry | `pdf_path.startswith(('http:', 'https:'))` raises `InvalidPDFPathError` with calling-site name | REQ-9.5.1.2 |
| A.5 | Implement `ProviderHealthChecker` | Probes Anthropic + Google with 1-token completions in parallel; ≤2s budget; logs structured events | REQ-9.5.1.3 |
| A.6 | Wire health check into service startup | Each LLM-using service calls checker on first use per process; failed providers marked unavailable | REQ-9.5.1.3 |
| A.7 | Implement `pipeline_health_abstract_fallback_rate` metric | Event emitted at `DailyResearchJob` completion with `rate: float` over current run | REQ-9.5.1.4 |
| A.8 | Audit HuggingFace + Semantic Scholar PDF resolution | Documented in `docs/audits/2026-05_provider_pdf_audit.md`; either bug fixed OR provider deprecated in default chain | REQ-9.5.1.5 |
| A.9 | Unit + integration tests for all of A | 99%+ coverage on new modules; regression test using real ArXiv URL passes | All A REQs |

**Review Gate G1:** End of Week 1
- ✅ All A REQs implemented
- ✅ `verify.sh` passes
- ✅ Manual run of `python -m src.cli run --config config/research_config.yaml` shows `using_abstract_fallback` rate ≤ 30% on next daily-equivalent run (target ≤20% measured over 7 days post-merge)
- ✅ Provider health check fails loudly when Anthropic key is invalid (verified by deliberately bad-key test)

**Risk:** A.8 audit may reveal that HuggingFace fundamentally returns models/datasets, not papers, requiring removal from the default chain. This is an acceptable outcome documented in spec Section 11 OQ-9.5.4.

---

### Weeks 2-3: Workstream B — Discovery Breadth

> **Plan revision (PR α, 2026-05-12):** Pre-execution audit revealed **Phase 7.2 already shipped the core mechanisms** — `QueryExpander` (`src/utils/query_expander.py`), `CitationExplorer` (`src/services/citation_explorer.py`), and DEEP-mode wiring in `DiscoveryPhase` (`discovery.py:227-228`). The original B.1–B.9 task list assumed greenfield; reality is that production never *activated* Phase 7.2 (no `query_expansion`/`citation_exploration` keys in `research_config.yaml`).
>
> **Revised execution: two PRs.**
>
> - **PR α (this commit):** Add `citation_exploration: enabled: true` to prod config to activate what already exists; amend spec/plan to reflect as-built reality. Citation expansion runs without LLM, so it ships today even with OQ-9.5.1 unresolved. Query expansion stays off until OQ-9.5.1 is sorted.
> - **PR β (next):** Six concrete gaps tracked as B-G1 through B-G6 in the spec. Highest priority is **B-G6** (`pipeline_health_breadth_metric` event) — without it we can't verify activation broadens the funnel.
>
> The original B.1–B.9 task list below is preserved for traceability; each item is annotated with its as-built status from the audit.

**Objective:** Activate citation expansion in the daily flow; share QueryExpander across monitoring + discovery.

**PR α Deliverables (this commit):**
1. `config/research_config.yaml` — add `citation_exploration` section (`enabled: true`, depth=1, fwd+bwd both on, 10 each)
2. `docs/specs/PHASE_9.5_RELIABILITY_BREADTH_LEARNING_SPEC.md` §4 — annotate each REQ with as-built status; add §4.3 gap summary
3. `.omc/plans/phase-9.5-execution-plan.md` — this revision block

**PR β Deliverables (deferred, depends on OQ-9.5.1 partly):**
1. `pipeline_health_breadth_metric` event in `DiscoveryPhase.execute()` end-of-run (B-G6, HIGH)
2. Seed-selection algorithm aligned with spec (B-G1, MED)
3. Reconcile field naming for provenance (B-G5, LOW)
4. After OQ-9.5.1 resolves: activate query expansion + add `recent_paper_titles` + 7-day TTL (B-G2/G3/G4)

**Original detailed TODOs (B.1–B.9), annotated with as-built status:**

| ID | Task | As-built status | REQ |
|---|---|---|---|
| B.1 | Extract `QueryExpander` from monitoring | ✅ **Already shipped** in Phase 7.2 at `src/utils/query_expander.py`; monitoring consumes it (`_tier1_factory.py:35,78`). Discovery uses a different class (`QueryIntelligenceService`) — see B-G3. | REQ-9.5.2.2 |
| B.2 | Add 7-day cache to `QueryExpander` | ⚠️ In-memory cache exists (`query_expander.py:57`); 7-day TTL not implemented. Tracked as **B-G4**. | REQ-9.5.2.2 |
| B.3 | Build `CitationExpansionService` | ✅ Already exists as `CitationExplorer` (`src/services/citation_explorer.py`); uses Phase 7.2's own implementation, NOT the Phase 9.2 `BFSCrawler` the original spec referenced. Functionally equivalent for daily-loop use. | REQ-9.5.2.1 |
| B.4 | Wire citation expansion into `DiscoveryPhase` | ✅ Wired via `pipeline.py:_create_discovery_phase` → `DiscoveryPhase(multi_source_enabled=True)` → DEEP mode. Gated on config presence. PR α flips the config switch. | REQ-9.5.2.1 |
| B.5 | Wire query variants into `DiscoveryPhase` | ✅ Wired in DEEP mode (same path). PR α does NOT activate (blocked on OQ-9.5.1); tracked as **B-G2**. | REQ-9.5.2.2 |
| B.6 | Add `source` and `seed_paper_id` to `ScoredPaper` | ⚠️ Phase 7.2 ships `discovery_source` + `discovery_method` on `PaperMetadata` with values like `"arxiv"`, `"forward_citation"`. Field names differ from spec's `source`/`seed_paper_id`. Tracked as **B-G5**. | REQ-9.5.2.3 |
| B.7 | Implement `pipeline_health_breadth_metric` | ❌ **Not done.** Per-source counts are logged separately (`discover_deep_citation_exploration` event) but no aggregated end-of-run event. Tracked as **B-G6 (HIGH)**. | REQ-9.5.2.4 |
| B.8 | Display source in Delta brief | ❌ **Not done.** `DeltaGenerator` doesn't show provenance. Tracked as part of **B-G5**. | REQ-9.5.2.3 |
| B.9 | Unit + integration tests for B | ⚠️ Existing Phase 7.2 tests (`tests/unit/test_phase_7_2_integration.py`) cover aggregation + query-expansion fallback. PR β adds tests for B-G1, B-G6 specifically. | All B REQs |

**Review Gate G2:** End of PR β
- ✅ All B REQs implemented OR explicitly deferred with rationale
- ✅ `verify.sh` passes
- ✅ Manual run after PR α shows DEEP mode activated (`phase72_discovery_enabled` log event present); manual run after PR β shows ≥10 net-new papers from citation expansion in a single run via the new `pipeline_health_breadth_metric` event
- ✅ Monitoring service still functions identically (regression check via existing `tests/unit/services/intelligence/monitoring/`)

**Risk:** Citation expansion may produce many low-relevance candidates if seed papers are noisy. Mitigation: existing `QualityFilterService` runs after expansion, filtering as for any other provider result. Additional mitigation in B-G1: replace top-10-by-discovery-order seed selection with last-7-days quality-≥-0.7 cohort for higher-signal seeds.

---

### Weeks 3-4: Workstream C — Targeted Learning Synthesis

**Objective:** Generate the first weekly Learning Brief.

**Week 3 Deliverables (parallel with B):**
1. `src/models/learning.py` — `LearningBriefRequest`, `LearningBriefSection`, `LearningBrief` Pydantic models
2. `src/services/learning/__init__.py` — package init
3. `src/services/learning/brief_generator.py` — `LearningBriefGenerator` class (consumes structured extraction outputs, calls LLM, parses response, sanitizes)
4. CLI commands `arisp learning generate|latest|list`

**Week 4 Deliverables:**
1. `src/scheduling/learning_brief_job.py` — `LearningBriefJob(BaseJob)` registered with APScheduler
2. Configuration support in `config/research_config.yaml`
3. Cost guardrail enforced (per-brief cap; sample by quality if over budget)
4. First production weekly brief generated; user reviews; iterate on prompt if needed

**Detailed TODOs:**

| ID | Task | Acceptance Criteria | REQ |
|---|---|---|---|
| C.1 | Define `LearningBrief*` Pydantic models | Strict Pydantic V2; serialization round-trips clean | REQ-9.5.3.1 |
| C.2 | Build `LearningBriefGenerator` | Loads papers from registry by date range + quality threshold; assembles prompt; calls LLM with cost cap; parses response into sections | REQ-9.5.3.1, REQ-9.5.3.2 |
| C.3 | Add prompt template for synthesis | System message, user message format, citation requirement; stored in `src/services/learning/prompts/` | REQ-9.5.3.2 |
| C.4 | Cost guardrail | Pre-flight estimate of token count; sample papers by quality if estimate exceeds budget; hard-stop if budget exceeded mid-call | REQ-9.5.3.2 |
| C.5 | Engineering Tips section selection | LLM-judged criteria documented in prompt; output validated to contain ≥3 tips when input has ≥10 papers | REQ-9.5.3.3 |
| C.6 | Empty-week skip logic | If `len(papers) < min_papers_for_brief`, log `learning_brief_skipped_insufficient_papers` and exit cleanly | REQ-9.5.3.6 |
| C.7 | LLM response sanitization | Markdown parsed permissively; active content stripped; orphan citations removed with warning | SR-9.5.C.2 |
| C.8 | CLI commands | `generate`, `latest`, `list` work; `--dry-run` shows input papers without LLM call | REQ-9.5.3.4 |
| C.9 | `LearningBriefJob` APScheduler integration | Pattern after `MonitoringCheckJob`; default Sunday 23:00 UTC; failures logged not raised | REQ-9.5.3.5 |
| C.10 | Unit + integration tests for C | 99%+ coverage; integration test with 10 fixture papers + stubbed LLM returning structured response | All C REQs |
| C.11 | Generate first production brief | Manually trigger via CLI; user reviews; iterate prompt if needed | REQ-9.5.3.1 |

**Review Gate G3:** End of Week 4
- ✅ All C REQs implemented
- ✅ `verify.sh` passes
- ✅ First production weekly Learning Brief generated and contains substantive cross-paper findings (manual user review)
- ✅ LLM cost ≤$5

**Risk:** First brief may be unusable if extraction quality is still degraded (Workstream A insufficient) or if LLM provider is misconfigured (OQ-9.5.1 unresolved). Mitigation: `--dry-run` mode to validate input before spending; manual review gate before declaring REQ-9.5.3 complete.

---

## Success Criteria

### Per-Workstream Verification

Each workstream must pass before proceeding:

1. **Test Coverage:** 99%+ for all new modules
2. **Test Pass Rate:** 100% (0 failures)
3. **Code Quality:** Black, Flake8, Mypy clean (`./verify.sh` green)
4. **Security:** All SR-9.5.x requirements verified
5. **Documentation:** Docstrings complete, CLI `--help` accurate, new structured-log events documented
6. **Integration:** No regressions to existing daily-run pipeline

### Phase 9.5 Overall Success
- All three workstreams complete and integrated
- `using_abstract_fallback` rate ≤20% on 7-day rolling window post-merge
- ≥1 weekly Learning Brief generated with substantive findings
- Phase 9.3 and 9.4 unblocked

---

## Risk Mitigation

| Risk | Mitigation |
|---|---|
| URL-as-Path fix breaks existing tests using mocked Path("http...") | Audit test suite first (`grep -rn 'Path.*http' tests/`); update fixtures with the fix in same PR |
| LLM provider question (OQ-9.5.1) unresolved when Workstream C ships | C is provider-agnostic via config; spec accommodates any choice; user can decide before C ships without rework |
| Citation expansion explodes candidate pool | Hard caps in REQ-9.5.2.1; existing QualityFilterService runs after expansion |
| Provider audit removes HuggingFace from default chain | Documented as acceptable outcome (spec OQ-9.5.4); 9.5 remains valuable with ArXiv-only |
| First weekly brief is low quality | `--dry-run` mode for validation; manual review gate; iterative prompt tuning before declaring complete |
| Workstream B introduces N+1 LLM calls (one per query variant per topic) | Variant cache (7-day TTL) bounds LLM calls; per-topic variant cap (default 3) bounds per-run cost |
| Schedule slip cascades into 9.3/9.4 | Workstreams are independently shippable; if C slips, A+B can ship as 9.5.1 with C as 9.5.2 |

---

## Handoff Points

### Workstream A → Workstream C
- Reliable extraction outputs (`Source: PDF` not `Source: Abstract`) for Learning Brief input
- Provider health checks confirm LLM availability before brief generation

### Workstream B → Phase 9.4
- Citation expansion service is reusable by future frontier-detection work
- `QueryExpander` is reusable by future topic auto-discovery

### Workstream C → User
- Weekly learning brief delivered to `output/learning_briefs/`
- CLI `arisp learning latest` for on-demand review

---

## Review/QA Gates

| Gate | Timing | Scope | Exit Criteria |
|---|---|---|---|
| G0 | Plan approval | All workstreams | User approves spec + execution plan |
| G1 | End Week 1 | Workstream A | All A REQs pass; abstract-fallback rate ≤30% on next manual run |
| G2 | End Week 3 | Workstream B | All B REQs pass; ≥10 net-new papers from citation_expansion in a manual run |
| G3 | End Week 4 | Workstream C + integration | First weekly brief generated; user reviews; ≥3 substantive findings cited |

### Gate Protocol
1. Implementation completes in worktree
2. Code review verifies quality, security, coverage
3. Manual verification end-to-end against acceptance criteria
4. Gate passes only when all three approve

---

## Estimated Effort

| Workstream | Duration | Complexity |
|---|---|---|
| A: Reliability | 1 week | LOW-MEDIUM |
| B: Breadth | 2 weeks (parallel) | MEDIUM |
| C: Learning Synthesis | 2 weeks (parallel) | MEDIUM |
| **Total** | **4 weeks** | N/A |

---

## Open Questions (Persisted)

See `.omc/plans/open-questions.md` for tracked decisions and open items (Phase 9.5 section).

### Key Open Question Blocking Workstream C
**OQ-9.5.1: LLM provider strategy** — The current Gemini free-tier (5 RPM) is incompatible with daily volume; Anthropic key is invalid. Workstream A surfaces this; Workstream C requires a working provider. Options documented in spec Section 11. **User decision needed before Workstream C Week 4.**

---

## Appendix: New File Structure

```
src/services/pdf_acquisition.py       # NEW (Workstream A)
src/services/llm/health_check.py      # NEW (Workstream A)
src/services/llm/query_expander.py    # NEW (extracted from monitoring) (Workstream B)
src/services/discovery/
    citation_expansion.py             # NEW (Workstream B)
src/services/learning/
    __init__.py                       # NEW (Workstream C)
    brief_generator.py                # NEW (Workstream C)
    prompts/
        synthesis_system.txt          # NEW (Workstream C)
        synthesis_user_template.txt   # NEW (Workstream C)
src/scheduling/learning_brief_job.py  # NEW (Workstream C)
src/models/learning.py                # NEW (Workstream C)
src/cli/learning.py                   # NEW (Workstream C)

docs/audits/
    2026-05_provider_pdf_audit.md     # NEW (Workstream A)

config/research_config.yaml           # EXTENDED (B + C config blocks)
src/orchestration/paper_processor.py  # MODIFIED (Workstream A)
src/services/extraction_service.py    # MODIFIED (Workstream A)
src/orchestration/phases/discovery.py # MODIFIED (Workstream B)
src/models/discovery.py               # MODIFIED (source field, Workstream B)
src/output/delta_generator.py         # MODIFIED (display source, Workstream B)
src/services/intelligence/monitoring/ # MODIFIED (consume shared QueryExpander, Workstream B)
```

---

**Document Status:** DRAFT
**Next Step:** User review/approval, then handoff to implementation in `feature/phase-9.5-pipeline-reliability` worktree (Workstream A first)
