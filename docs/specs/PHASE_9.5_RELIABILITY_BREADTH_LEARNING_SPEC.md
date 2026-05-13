# Phase 9.5: Pipeline Reliability, Discovery Breadth, and Targeted Learning Synthesis

**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 4 weeks
**Date:** 2026-05-09
**Dependencies:**
- Phase 9.1 Complete (Monitoring service shipped — but currently degraded; see Problem Statement)
- Phase 9.2 Complete (Citation graph shipped — but not wired into daily flow; see Problem Statement)
- Phase 5.1 Complete (LLM Service Decomposition)
- Phase 3.7 Complete (Cross-Topic Synthesis)

**Blocks:** Phase 9.3 (Knowledge Graph) and Phase 9.4 (Frontier Detection) are deferred until Phase 9.5 completion.

---

## Architecture Reference

This phase addresses two production gaps observed in the live daily pipeline as of 2026-05-09:

1. **The ingestion pipeline produces degraded output.** ~54% of papers fail PDF extraction due to a URL-as-Path bug; ~63% of LLM extraction attempts fail due to free-tier quota exhaustion; the Anthropic fallback provider is offline (invalid API key). Daily Delta briefs are abstract-only title lists rather than the targeted learnings the system was designed to produce.

2. **Discovery is structurally narrow.** Topic queries are hand-picked and static; only ArXiv reliably returns PDF-bearing papers (HuggingFace returns 0 after filtering, Semantic Scholar reports `pdf_available: 0`); the Phase 9.2 citation graph exists but is not used in the daily discovery loop; the Phase 9.1 monitoring service returns 0 new papers per cycle because LLM-based query expansion fails silently when the Anthropic provider is unavailable.

**Architectural Gaps Addressed:**
- ❌ Gap: PDF download path is duplicated across `extraction_service.py` and `paper_processor.py`, with the orchestration layer bypassing `download_pdf()` entirely
- ❌ Gap: External provider failures (auth, quota) degrade silently into abstract-only fallback, with no clear runtime signal
- ❌ Gap: Daily discovery is single-source-effective (ArXiv) and single-query-per-topic, exhausting against narrow topic slices
- ❌ Gap: Citation graph (Phase 9.2) is queryable via CLI but not integrated into the discovery candidate pool
- ❌ Gap: Per-paper extraction outputs (prompts, code, metrics, summaries) are not synthesized into cross-paper learning briefs that answer "what advanced this week"

**Components Added:**
- Reliability: shared download pipeline, provider startup health checks, abstract-fallback SLO
- Breadth: `CitationExpansionService` (wraps existing `BFSCrawler` for daily-loop use), shared `QueryExpander` extracted from monitoring, multi-source PDF resolution audit
- Learning: `LearningBriefGenerator`, `LearningBriefJob` (APScheduler), CLI `arisp learning` namespace

**Components NOT Added** (explicitly out of scope):
- ❌ New paper-discovery providers beyond fixing existing ones (no Crossref/CORE in 9.5)
- ❌ Topic auto-rotation via frontier detection (depends on Phase 9.4, deferred)
- ❌ Replacement of LLM provider strategy (provider choice is an open question, see Section 11)
- ❌ Multi-user features

**Coverage Targets:**
- Reliability components: ≥99% (existing project standard)
- Breadth components: ≥99%
- Learning synthesis: ≥99%

---

## 1. Executive Summary

Phase 9.5 stabilizes ARISP's production pipeline and closes the loop between discovery, extraction, and learning. It addresses three interdependent problems:

| Workstream | Problem Today | Outcome |
|---|---|---|
| **A. Reliability** | 54% PDF extraction failure (URL-as-Path bug); silent provider degradation; ~70% of papers fall back to abstract-only | <20% abstract-fallback rate; loud failure on provider auth issues |
| **B. Discovery Breadth** | Static hand-picked topics; single effective provider (ArXiv); citation graph not in daily loop | Daily candidate pool 2-3× larger via citation expansion + LLM query variants |
| **C. Targeted Learning Synthesis** | Per-run Delta briefs are title lists; no cross-paper synthesis of "what advanced" | Weekly Learning Brief per topic answering "novel techniques, new benchmarks, contradictions, SOTA changes" with citations |

**What This Phase Is:**
- ✅ Production reliability hardening of an existing, shipping pipeline
- ✅ Activation of already-built Phase 9.2 citation work in the daily flow
- ✅ A new synthesis output that turns extraction into actionable learning briefs

**What This Phase Is NOT:**
- ❌ A redesign of discovery, extraction, or LLM architecture
- ❌ A new provider integration (existing broken ones get audited; nothing new added)
- ❌ Phase 9.3 or 9.4 work — those are explicitly deferred behind 9.5

**Key Achievement:** Restore the pipeline's ability to produce useful per-paper extractions, then layer cross-paper weekly synthesis on top — so the user's daily output is a curated learning brief, not a list of titles.

---

## 2. Problem Statement

### 2.1 Diagnostic Findings (2026-05-09 daily run)

The following observations come from `logs/daily_run_2026-05-09.log` and direct code inspection. Each finding is reproducible.

#### 2.1.1 PDF extraction is broken via URL-as-Path

`src/orchestration/paper_processor.py:138-145`:

```python
if paper.open_access_pdf:
    ...
    pdf_result = await self.fallback_pdf_service.extract_with_fallback(
        pdf_path=Path(str(paper.open_access_pdf))   # ← bug
    )
```

The orchestration layer bypasses `PDFService.download_pdf()` and casts the URL string directly into a `Path`. `Path("https://...")` collapses double slashes to `https:/...`, which then fails as a non-existent local file:

```
{"error": "no such file: 'https:/arxiv.org/pdf/2605.06641v1'", "event": "pymupdf_extraction_failed"}
```

`src/services/extraction_service.py:172-218` does this correctly (downloads first, passes a real `Path`). The two paths have diverged.

**Impact:** 97 of 180 papers (54%) fail PDF extraction per daily run. All fall back to abstract-only.

#### 2.1.2 LLM extraction is throttled to ~5 RPM

The active provider is `gemini-2.5-flash` on the free tier (5 requests/minute):

```
"error": "429 RESOURCE_EXHAUSTED ... Quota exceeded for metric:
generate_content_free_tier_requests, limit: 5, model: gemini-2.5-flash"
```

**Impact:** 113 `llm_extraction_failed` events per run; many papers receive no extraction at all even when the PDF was successfully downloaded.

#### 2.1.3 Anthropic fallback is offline (invalid key)

```
"Provider anthropic failed: Error code: 401 - 'invalid x-api-key'"
```

**Impact:** Multi-provider failover (Phase 3.3) cannot engage; LLM-based query expansion in monitoring (Phase 9.1) silently disables itself; the user has no startup-time signal that this provider is unusable.

#### 2.1.4 Discovery is effectively single-source

From the same daily run, by provider:

| Provider | Returned | PDFs available |
|---|---|---|
| ArXiv | ~20/topic | 100% |
| Semantic Scholar | ~20/topic | **0%** (`pdf_available: 0` in every event) |
| HuggingFace | 0/topic | N/A (fetches 100, filters all out — likely returning models/datasets, not papers) |

**Impact:** Despite the multi-provider architecture, only ArXiv contributes papers to the extraction pipeline.

#### 2.1.5 Topics are hand-picked and never rotate

`config/research_config.yaml` contains 8 narrow topics (e.g., "Tree of Thoughts AND machine translation"). They have run daily for >30 days against ArXiv's narrow daily slice. Average duplication rate per daily run is ~28% (not "always," as the user perceived — but trending upward as ArXiv's recent slice is exhausted). Two topics on 2026-05-09 saw 80% and 48% duplication.

#### 2.1.6 Citation graph is built but not in the daily loop

Phase 9.2 shipped `BFSCrawler`, `BibliographicCouplingAnalyzer`, `CitationRecommender`, and the `arisp citation` CLI (#147, #150, #151, #152). None of these are invoked by `DiscoveryPhase` in the daily pipeline. The citation neighborhood of high-quality recently-extracted papers is not added to the candidate pool.

#### 2.1.7 Monitoring service returns 0 new papers per cycle

`logs/monitor_check_2026-05-09.log` shows `monitor_cycle_complete` events with `seen: 0, new: 0` consistently. Three contributing causes: (a) ArXiv-only by ADR decision (`open-questions.md` 2026-04-24), (b) query expansion fails because the only configured expander provider is Anthropic (broken — see 2.1.3), (c) subscription windows are narrower than the discovery service's.

#### 2.1.8 Output is title-only

Inspection of `output/prompt-engineering-machine-translation-multilingual/runs/2026-05-09_Delta.md` shows every paper marked `Source: 📋 Abstract` — no full-text extraction, no extracted prompts/code/metrics. The "delta brief" is a list of titles plus quality scores. There is no cross-paper synthesis at the daily level beyond Phase 3.7's optional cross-topic synthesis (which is per-run, not weekly, and is bypassed when extractions fail).

### 2.2 Why the Existing Phase 9 Plan Doesn't Cover This

The Phase 9 plan (`.omc/plans/phase-9-execution-plan.md`) assumes a working ingestion pipeline and layers four intelligence pillars on top: 9.1 Monitoring, 9.2 Citation, 9.3 Knowledge, 9.4 Frontier. The plan does not address:

- Pipeline reliability regressions in the underlying extraction path
- Activation of 9.2 in the production daily loop (it ships standalone CLI capabilities only)
- Synthesis of per-paper extraction into cross-paper learning briefs distinct from the existing per-run Delta and per-topic synthesis outputs

Phase 9.5 inserts before 9.3 and 9.4 to close these gaps.

---

## 3. Workstream A — Pipeline Reliability

**Objective:** Restore the extraction pipeline to producing useful per-paper output. This workstream blocks Workstreams B and C — there is no value in broadening discovery or synthesizing learnings if extraction itself is broken.

### 3.1 Requirements

#### REQ-9.5.1.1: Single download path for all PDF extraction
The system SHALL use exactly one code path to materialize a PDF URL into a local file before extraction. Both `src/services/extraction_service.py` and `src/orchestration/paper_processor.py` SHALL invoke `PDFService.download_pdf()` (or a shared helper) before passing a `Path` to any extractor.

**Scenario: Orchestration uses shared download**
**Given** a `PaperMetadata` with `open_access_pdf="https://arxiv.org/pdf/2605.06641v1"`
**When** `paper_processor.py` processes the paper
**Then** the URL SHALL be downloaded to a local `Path` via `PDFService.download_pdf()`
**And** the local `Path` SHALL be passed to `FallbackPDFService.extract_with_fallback()`
**And no** event SHALL be logged with `pdf_path` matching `^https?:/`.

#### REQ-9.5.1.2: Type guard against URL-as-Path
The PDF extractor entry points SHALL reject any `pdf_path` value whose string representation begins with `http:` or `https:` (case-insensitive). Rejection SHALL raise a typed exception with an actionable message naming the calling site.

**Rationale:** Defense-in-depth so a future caller cannot recreate the bug silently.

#### REQ-9.5.1.3: Provider startup health check
On startup of any service that uses an LLM provider (extraction, monitoring, learning brief generation), each configured provider SHALL be probed with a single minimal request. Results SHALL be logged as one of:

- `provider_health_check_passed` (level=info)
- `provider_health_check_failed` (level=error) with provider name, error class, and remediation hint

Probes that fail SHALL NOT prevent service startup, but the failed provider SHALL be marked unavailable in the provider registry until the next probe. A subsequent runtime call to an unavailable provider SHALL fail-fast (no retry), so the user sees the issue immediately rather than buried in retry noise.

**Probe Examples:**
- Anthropic: 1-token completion against `claude-haiku-*` (cheapest)
- Google: 1-token completion against `gemini-*-flash` (cheapest)

**Cost:** ≈$0.00001 per probe per startup, run once per process.

#### REQ-9.5.1.4: Abstract-fallback SLO
The system SHALL track the percentage of papers that fall back to abstract-only extraction over a rolling 7-day window. The metric SHALL be exposed as a structured log event `pipeline_health_abstract_fallback_rate` emitted at the end of each daily run, with the rate as a float.

**SLO:** `using_abstract_fallback` rate ≤ 20% on any 7-day rolling window.
**Current baseline:** ~70% (per 2026-05-09 sample).

**Note:** The metric is an SLO indicator, not a hard gate. Phase 9.5 does not add automated alerting (deferred to Phase 4 production-hardening); the metric is for human review of `logs/daily_run_*.log`.

> **Implementation status (PR #157):** ✅ implemented. `PipelineResult` now carries `papers_with_pdf`, `papers_with_abstract_fallback`, `abstract_fallback_rate_pct`, and `abstract_fallback_within_slo`. `DailyResearchJob.run()` emits `pipeline_health_abstract_fallback_rate` as the per-run building block of the rolling SLO. The 20% threshold is centralised in `src.orchestration.result.ABSTRACT_FALLBACK_RATE_SLO_PCT`.

#### REQ-9.5.1.5: Provider integration audit
For each non-ArXiv provider in the discovery chain (HuggingFace, Semantic Scholar), the implementation SHALL be audited and either:

- (a) Fixed so that PDF-bearing papers are returned with a usable `open_access_pdf` URL, OR
- (b) Documented as non-PDF-bearing (e.g., "Semantic Scholar API plan does not return open-access PDFs") with a deprecation notice in the daily-run log if the provider continues to return zero PDFs

**Out of scope:** Adding new providers (Crossref, CORE, OpenAlex-as-PDF-source). Phase 9.5 audits and either fixes or documents existing ones; new provider work is left to a future phase.

> **Implementation status (PR #157):** ✅ audited; outcome (b). See [`docs/audits/2026-05_provider_pdf_audit.md`](../audits/2026-05_provider_pdf_audit.md). Both providers operate as designed — HuggingFace's daily-papers feed plus AND-semantics filter genuinely cannot match the project's narrow queries; Semantic Scholar's `openAccessPdf` field is sparsely populated by S2 itself, not gated by our auth or code. Both providers stay in the default chain (they contribute non-PDF metadata that downstream features depend on); broader PDF coverage is deferred to a future phase that adds Unpaywall or similar.

### 3.2 Security Requirements

#### SR-9.5.A.1: Provider health probes MUST NOT log API keys
Health probe events SHALL include provider name and HTTP status / error class only. No auth header values, request bodies containing secrets, or response bodies SHALL be logged.

#### SR-9.5.A.2: Type guard MUST NOT replace existing path validation
The URL-scheme rejection guard at the extractor entry point is a defense-in-depth complement to (NOT a replacement for) any path-validation logic that lives in upstream callers (e.g. `PDFService.download_pdf` enforces HTTPS; `src/utils/path_sanitization.py` is available for callers that need traversal-safe filename construction). The guard's job is to catch URL-shaped values; traversal-safe path handling remains the responsibility of whoever constructs the path.

> **Implementation note (review fix #4 in PR #157):** the guard rejects more than just `http:`/`https:` schemes — see `_REJECTED_URL_SCHEMES` in `src/services/pdf_extractors/fallback_service.py` for the full list (`file:`, `ftp:`, `ftps:`, `data:`, `javascript:`, `gopher:` are also covered as defense-in-depth against future regressions). `extract_with_fallback` does not currently invoke `path_sanitization.py` directly; integrating that is tracked as a follow-up hardening item.

---

## 4. Workstream B — Discovery Breadth

**Objective:** Increase the diversity of papers reaching extraction without adding new providers. Two mechanisms: (1) citation expansion using the already-shipped Phase 7.2 `CitationExplorer`, (2) LLM-driven query variants via the already-shipped Phase 7.2 `QueryIntelligenceService`.

> **Audit correction (PR α, 2026-05-12):** The original wording of this section assumed Workstream B was greenfield work. A code audit at branch creation time revealed that **Phase 7.2 (Discovery Expansion) already shipped both mechanisms** — `src/utils/query_expander.py`, `src/services/citation_explorer.py`, and the `multi_source_enabled` path in `src/orchestration/phases/discovery.py:227-228`. What was missing was production *activation* (the prod `research_config.yaml` had no `query_expansion` or `citation_exploration` section, so `_create_discovery_phase` fell through to single-source mode) and a small set of genuine gaps listed at the end of this section. Each REQ below is annotated with its **as-built status** plus the residual gap.

### 4.1 Requirements

#### REQ-9.5.2.1: Citation expansion in daily discovery
The `DiscoveryPhase` SHALL, after running provider queries and quality filtering, expand the candidate pool by traversing the citation neighborhood of recently extracted high-quality papers.

**Algorithm (as-spec'd):**

1. Identify "seed" papers: papers extracted in the last 7 days for the current topic with `quality_score >= 0.7`. Cap at 10 seeds per topic (highest-scored first).
2. For each seed, traverse 1 hop in both directions (forward citations + backward references).
3. Deduplicate candidates against:
   - The current run's discovery results (in-memory)
   - The global registry (already extracted)
4. Cap the citation-expansion contribution at 50 candidates per topic per run (to bound API cost and avoid swamping the deduplication stage).
5. Tag candidates with `source: "citation_expansion"` and `seed_paper_id` for downstream attribution in the Delta brief.

**Configuration** (`config/research_config.yaml`):

```yaml
settings:
  citation_exploration:
    enabled: true
    forward: true
    backward: true
    max_citation_depth: 1
    max_forward_per_paper: 10
    max_backward_per_paper: 10
```

> **As-built status (PR α activates; PR β closes gaps):** The traversal infrastructure is shipped — `src/services/citation_explorer.py` walks Semantic Scholar forward/backward citations and `DiscoveryPhase._discover_topic` invokes it via DEEP mode (`discovery.py:227-228`). PR α turns the feature on in `config/research_config.yaml`. The seed-selection algorithm in Phase 7.2 differs from the spec: it takes the top 10 papers from the *current* run's provider results (`src/services/discovery/service.py:1131`), not "papers extracted in the last 7 days with quality_score ≥ 0.7". This divergence is acceptable for PR α (still broadens vs. single-source) and is tracked as **Gap B-G1** for PR β.

#### REQ-9.5.2.2: Shared query expansion service
Phase 9.1 monitoring contains LLM-based query expansion logic. This SHALL be extracted into a shared `QueryExpander` service usable by both monitoring and the daily discovery flow.

**Interface (as-spec'd):**
```python
class QueryExpander:
    async def expand(
        self,
        base_query: str,
        recent_paper_titles: list[str],   # ≤20 titles
        n_variants: int = 3,
    ) -> list[str]:
        """Generate n_variants alternative queries informed by recent corpus."""
```

**Caching:** Variants SHALL be cached for 7 days per `(base_query, hash(sorted(recent_paper_titles)))` key. Daily runs reuse the same variants for a week unless titles change materially.

**Activation in daily flow:** `DiscoveryPhase` SHALL run the original query plus expanded variants through each provider, deduplicating across queries.

> **As-built status:** Two query-expansion paths exist in the codebase, neither matching the spec interface:
> - `src/utils/query_expander.py::QueryExpander.expand(query, max_variants)` — used by Phase 9.1 monitoring; in-memory cache, no TTL.
> - `src/services/discovery/service.py` calls `QueryIntelligenceService.enhance(...)` from DEEP mode — used by discovery.
>
> Both ignore `recent_paper_titles`. **PR α does NOT activate query expansion** in `research_config.yaml` because it requires a working LLM, which is currently blocked on **OQ-9.5.1 (LLM provider strategy)**. Citation expansion (above) runs without LLM, so DEEP mode still adds value via citation traversal alone (the `query_service is None` branch at `service.py:1056-1064` falls through to the original query and continues with citation work). Once OQ-9.5.1 is resolved, PR β will:
>
> - **Gap B-G2:** Add `query_expansion: enabled: true` to prod config to activate the existing path.
> - **Gap B-G3:** Add `recent_paper_titles` parameter to `QueryExpander` (and reconcile with `QueryIntelligenceService`).
> - **Gap B-G4:** Add 7-day TTL to `QueryExpander._cache`.

#### REQ-9.5.2.3: Tag candidate provenance
Every paper added to the candidate pool SHALL carry a `source` field with one of: `provider:arxiv`, `provider:semantic_scholar`, `provider:huggingface`, `citation_expansion`, `query_variant`. This is used in the Delta brief and for diagnostic tracking.

> **As-built status:** Phase 7.2 ships `discovery_source` and `discovery_method` fields on `PaperMetadata` (`src/models/paper.py:63`) and `ResultAggregator` populates them with values like `"arxiv"`, `"semantic_scholar"`, `"forward_citation"`, `"backward_citation"` (`src/services/citation_explorer.py:135, 151`). Field name and value vocabulary differ from the spec but the *function* is provided. **Gap B-G5:** PR β should either align the spec to the as-built names or rename the as-built fields to match the spec; either way, no new tracking is needed.

#### REQ-9.5.2.4: Discovery breadth metric
The system SHALL emit `pipeline_health_breadth_metric` at end-of-run with:
- Total candidates discovered
- Breakdown by `source`
- Net new papers (post-dedup) by `source`

**SLO indicator:** Citation-expansion contribution SHALL be ≥ 20 net-new papers per run averaged over 7 days, once enabled.

> **As-built status:** Per-source counts are logged separately (e.g. `discover_deep_citation_exploration` event with `forward` + `backward` counts at `discovery/service.py:1150-1152`) but there is no aggregated `pipeline_health_breadth_metric` event analogous to the Phase 9.5 Workstream A `pipeline_health_abstract_fallback_rate` event. **Gap B-G6:** PR β implements this single new event in `DiscoveryPhase.execute()` end-of-run, with the same shape as the abstract-fallback SLO event (rate, counts, threshold, within_slo).

### 4.3 Gap summary for follow-up PR β

| Gap | Description | Source REQ | Priority |
|---|---|---|---|
| **B-G1** | Seed selection: replace hardcoded top-10 with "last-7-days, quality ≥ 0.7" cohort | REQ-9.5.2.1 | MED — current behavior still broadens; spec algorithm gives higher-signal seeds |
| **B-G2** | Activate `query_expansion: enabled: true` in `research_config.yaml` | REQ-9.5.2.2 | BLOCKED on OQ-9.5.1 |
| **B-G3** | Add `recent_paper_titles` param to `QueryExpander.expand` | REQ-9.5.2.2 | LOW — only matters if seeds inform variant generation |
| **B-G4** | Add 7-day TTL to `QueryExpander._cache` | REQ-9.5.2.2 | LOW — bounded cache size; current in-memory is fine for single-process runs |
| **B-G5** | Reconcile `discovery_source` / `discovery_method` field naming with spec's `source` / `seed_paper_id` (or amend spec) | REQ-9.5.2.3 | LOW — function works; cosmetic |
| **B-G6** | Implement `pipeline_health_breadth_metric` end-of-run event | REQ-9.5.2.4 | **HIGH** — without this, we can't verify the activation actually broadens the funnel |

### 4.2 Security Requirements

#### SR-9.5.B.1: Citation expansion respects rate limits
The shared `BFSCrawler` already implements Semantic Scholar / OpenAlex rate limiting (Phase 9.2). Daily-loop activation SHALL NOT bypass these limits. If rate limits are hit, citation expansion SHALL gracefully degrade (skip remaining seeds for this run) rather than blocking the discovery phase.

#### SR-9.5.B.2: Query variants subject to existing input validation
LLM-generated query variants SHALL pass through the same input validation as user-configured queries before being sent to providers. Specifically: length cap, character whitelist, and provider-specific syntax sanitization.

---

## 5. Workstream C — Targeted Learning Synthesis

**Objective:** Convert successfully-extracted per-paper data into a weekly cross-paper learning brief that answers: "what actually advanced our understanding this week?"

### 5.1 Requirements

#### REQ-9.5.3.1: Learning Brief output type
The system SHALL produce a new artifact `output/learning_briefs/YYYY-WW_Learning_Brief.md` weekly, distinct from per-run Delta briefs and per-run cross-topic syntheses.

**Cadence:** Weekly by default (configurable). Generated at end-of-week (Sunday UTC).

**Scope:** All papers extracted in the last 7 days across all topics with `extraction_status == "success"` and `Source: PDF` (i.e., excluding abstract-only fallbacks).

**Format:**

```markdown
---
date_range: 2026-05-03 to 2026-05-09
papers_analyzed: 47
topics_covered: ["tree-of-thoughts-and-mt", "rl-robotics", ...]
quality_threshold: 0.7
---

# Learning Brief: Week 19 of 2026

## Novel Techniques Introduced
- [paper_id_1] introduced X technique that achieves Y on benchmark Z
- ...

## New Benchmarks & Datasets
- ...

## Contradictions With Prior Claims
- [paper_id_3] reports finding contrary to [paper_id_4] on ...

## Results That Change Current SOTA
- ...

## Practical Engineering Tips
- For implementing X, see [paper_id_5]'s Section 3.2 on ...

## Cross-Topic Connections
- The [paper_id_6] approach in MT may be transferable to RL setup in [paper_id_7]
```

#### REQ-9.5.3.2: LLM prompt structure for synthesis
The brief SHALL be generated by a single LLM call (or chunked if context exceeds 200K tokens) with the following prompt structure:

- System message: Defines role, output structure, citation requirements
- User message: Concatenated extraction outputs (`engineering_summary`, `code_snippets`, `evaluation_metrics`, `system_prompts`) for each paper, prefixed with `[paper_id]`
- Output requirement: Every claim in the brief must cite at least one `[paper_id]`

**Provider:** Whichever LLM provider is selected per the open question in Section 11. Defaults to the same provider used for extraction.

**Cost guardrail:** Each weekly brief is capped at $5 USD of LLM spend (configurable). If the corpus exceeds the budget, papers SHALL be sampled by `quality_score` (highest first).

#### REQ-9.5.3.3: Cross-topic engineering tips
The brief SHALL include a dedicated "Practical Engineering Tips" section that surfaces extracted code snippets and system prompts judged most likely to be implementable by an engineering team. Selection criteria (LLM-judged):

- Clarity of implementation
- Generality (transferable across tasks)
- Reproducibility (specific hyperparameters, datasets named)

#### REQ-9.5.3.4: CLI commands
```
arisp learning generate [--week N] [--year YYYY] [--dry-run]
arisp learning latest
arisp learning list
```

- `generate` invokes the synthesis on demand. `--dry-run` shows the input papers without LLM call.
- `latest` prints the most recent brief to stdout.
- `list` shows all generated briefs with date ranges and paper counts.

#### REQ-9.5.3.5: Scheduled job integration
A `LearningBriefJob(BaseJob)` SHALL be added to `src/scheduling/`, following the pattern of `DailyResearchJob` and `MonitoringCheckJob`. It SHALL run weekly (default: Sunday 23:00 UTC, configurable). Failures SHALL log `learning_brief_generation_failed` and SHALL NOT crash the scheduler.

#### REQ-9.5.3.6: Empty-week handling
If the previous 7 days produced fewer than `min_papers_for_brief` papers (default: 5), the job SHALL log `learning_brief_skipped_insufficient_papers` and SHALL NOT generate a brief or call the LLM.

### 5.2 Security Requirements

#### SR-9.5.C.1: Learning brief MUST NOT leak per-paper PDF content beyond extraction targets
The synthesis prompt SHALL only consume already-extracted structured fields (`engineering_summary`, `code_snippets`, etc.). Raw PDF text SHALL NOT be re-loaded or re-sent to the LLM. This bounds privacy/copyright exposure to what extraction has already approved.

#### SR-9.5.C.2: LLM response sanitization
The brief output SHALL be parsed with a permissive Markdown parser before write. Any embedded `<script>`, `<iframe>`, or other active content SHALL be stripped. Citations matching `[paper_id_X]` SHALL be validated against the actual paper IDs in the input set; orphan citations SHALL be removed with a log warning.

---

## 6. Data Models

New Pydantic models in `src/models/learning.py`:

```python
class LearningBriefRequest(BaseModel):
    week_iso: str                     # "2026-W19"
    start_date: date
    end_date: date
    min_quality_score: float = 0.7
    min_papers: int = 5
    max_cost_usd: float = 5.0
    llm_provider: str | None = None   # default: extraction provider

class LearningBriefSection(BaseModel):
    heading: str
    items: list[str]                  # markdown bullet text
    cited_paper_ids: list[str]

class LearningBrief(BaseModel):
    week_iso: str
    generated_at: datetime
    papers_analyzed: list[str]        # paper_ids
    topics_covered: list[str]
    cost_usd: float
    sections: list[LearningBriefSection]
    output_path: Path
```

New Pydantic models in `src/models/discovery.py` (additions):

```python
class CandidateSource(str, Enum):
    PROVIDER_ARXIV = "provider:arxiv"
    PROVIDER_SEMANTIC_SCHOLAR = "provider:semantic_scholar"
    PROVIDER_HUGGINGFACE = "provider:huggingface"
    CITATION_EXPANSION = "citation_expansion"
    QUERY_VARIANT = "query_variant"

# Add to existing ScoredPaper:
class ScoredPaper(BaseModel):
    ...
    source: CandidateSource
    seed_paper_id: str | None = None  # for citation_expansion only
```

---

## 7. Success Metrics

### 7.1 Per-Workstream Metrics

| Workstream | Metric | Baseline (2026-05-09) | Target (post-9.5) |
|---|---|---|---|
| A — Reliability | `using_abstract_fallback` rate | ~70% | ≤20% |
| A — Reliability | PDF extraction success rate | ~46% (83/180) | ≥95% |
| A — Reliability | Provider health visible at startup | ❌ buried in retries | ✅ explicit event |
| B — Breadth | Net new papers via citation_expansion (avg/run) | 0 | ≥20 |
| B — Breadth | Topics with query variants active | 0 | all |
| B — Breadth | Effective providers contributing PDFs | 1 (ArXiv) | 1 fixed + audit complete on others |
| C — Learning | Weekly briefs generated | 0 | 1/week |
| C — Learning | Briefs containing ≥3 cited "novel techniques" findings | N/A | ≥80% of briefs |
| C — Learning | LLM cost per brief | N/A | ≤$5 |

### 7.2 Phase 9.5 Overall Success

Phase 9.5 is considered complete when:
1. All three workstreams' requirements pass with 99%+ test coverage
2. The next daily run after deployment shows `using_abstract_fallback` rate < 20% (verified manually from `logs/daily_run_*.log`)
3. The first weekly Learning Brief is generated and contains substantive cross-paper findings (manually reviewed)
4. Phase 9.3 and 9.4 are unblocked (their dependencies on 9.5 are satisfied)

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| URL-as-Path fix breaks existing tests that mocked the old path | Audit test suite for `Path("https://...")` patterns before code change; update fixtures together with the fix |
| Provider health checks add startup latency | Probes are async and run in parallel; budget ≤2s total for 2-3 providers |
| Citation expansion explodes API call count | Hard caps on seeds and candidates per topic; existing rate limiters from Phase 9.2 enforced |
| Learning Brief LLM cost exceeds budget | Per-brief cost cap; sample by quality if over budget; weekly cadence (not daily) bounds spend |
| Audit of HuggingFace/SS reveals they're fundamentally not PDF-bearing | Document and remove from default chain; this is an acceptable outcome for 9.5, not a blocker |
| LLM provider question unresolved at start of Workstream C | Workstream C is implementation-agnostic on provider; specific provider plumbed via config; user decision can land before C ships |
| Learning Brief synthesis quality is poor on first attempt | Iterative prompt tuning during Week 4; manual review of first 2-3 briefs before declaring success |

---

## 9. Resequencing of Phase 9.3 and 9.4

Phase 9.5 inserts before 9.3 (Knowledge Graph) and 9.4 (Frontier Detection). The original Phase 9 plan dependencies still hold:
- 9.3 requires 9.2 (✅ shipped)
- 9.4 requires 9.2 (✅ shipped)

Both will benefit from 9.5's reliability improvements (their LLM-heavy work cannot succeed if extraction is broken or providers are silently down). Both will benefit from 9.5's broader candidate pool (more papers → richer knowledge graph and frontier signal).

**Recommended order after 9.5:** 9.4 (Frontier) before 9.3 (Knowledge), because frontier detection enables the topic auto-rotation deferred from 9.5's Workstream B and provides the highest-leverage discovery improvement. This is a reversal of the original Phase 9 plan order; revisit during 9.5 closeout.

---

## 10. Implementation Notes

### 10.1 Shared Download Path (Workstream A)

The cleanest refactor: extract PDF acquisition into a small helper used by both `extraction_service.py` and `paper_processor.py`:

```python
# src/services/pdf_acquisition.py (new)
async def acquire_pdf(
    pdf_service: PDFService,
    paper: PaperMetadata,
) -> Path | None:
    """Materialize a paper's open_access_pdf URL into a local Path.

    Returns None if the paper has no PDF URL. Raises typed exceptions
    on download failure.
    """
    if not paper.open_access_pdf:
        return None
    return await pdf_service.download_pdf(
        url=str(paper.open_access_pdf),
        paper_id=paper.paper_id,
    )
```

Both call sites then call `acquire_pdf(...)` and pass the result to extractors. The type guard in REQ-9.5.1.2 lives at the extractor entry point as defense-in-depth.

### 10.2 QueryExpander Extraction (Workstream B)

The expander already exists inside `src/services/intelligence/monitoring/`. Extract to `src/services/llm/query_expander.py` as a provider-agnostic class. Update monitoring to consume from the shared location. No behavior change for monitoring; gain is reuse by `DiscoveryPhase`.

### 10.3 LearningBriefJob (Workstream C)

Pattern after `MonitoringCheckJob` (Phase 9.1) and `DailyResearchJob`. Schedule via APScheduler with a cron trigger:

```yaml
schedule:
  learning_brief:
    cron: "0 23 * * 0"        # Sunday 23:00 UTC
    enabled: true
```

### 10.4 Test Strategy

- **Unit:** Each new component covered ≥99%
- **Integration:**
  - End-to-end test using a real ArXiv URL (not a mocked Path) to prevent regression of REQ-9.5.1.1
  - Provider health check test using mocked HTTP failures
  - Citation expansion test using a recorded `BFSCrawler` response fixture
  - Learning brief test with a corpus of 10 fixture papers and a stubbed LLM that returns a structured response
- **Manual:** First 2-3 production weekly briefs reviewed by user before declaring REQ-9.5.3.x complete

---

## 11. Open Questions

These are surfaced here and tracked in `.omc/plans/open-questions.md`:

### OQ-9.5.1: LLM provider strategy
**Context:** Workstream A surfaces that the current Gemini free-tier (5 RPM) is incompatible with the daily volume (~180 papers), and the Anthropic key is invalid. Workstream C adds weekly synthesis cost. Decision needed before Workstream A ships.

**Options:**
- (a) Move to paid Gemini tier (raises RPM substantially)
- (b) Rotate Anthropic key and use Claude Haiku/Sonnet as primary
- (c) Stay on free tier; throttle pipeline (fewer topics, slower extraction)
- (d) Local LLM for extraction (Ollama + a small model); paid API only for synthesis

**Status:** Deferred to user (per AskUserQuestion 2026-05-09). 9.5 plan accommodates any choice via config.

### OQ-9.5.2: Citation expansion seed selection
**Context:** REQ-9.5.2.1 caps seeds at 10 per topic by `quality_score`. Should seeds also be biased toward papers the user has interacted with (Phase 7 feedback signals)?

**Default:** Pure quality_score for 9.5; revisit when integrating with Phase 9.4 frontier detection.

### OQ-9.5.3: Learning Brief cadence
**Context:** Spec defaults to weekly. Some users may want daily mini-briefs and a weekly comprehensive one.

**Default:** Weekly only for 9.5. Daily briefs deferred until weekly is proven valuable.

### OQ-9.5.4: HuggingFace and Semantic Scholar provider audit outcome
**Context:** REQ-9.5.1.5 audits these and either fixes or documents. Outcome of the audit determines whether either is removed from the default discovery chain.

**Default:** Resolve during Workstream A implementation; update spec if the outcome materially changes Workstream B's "single effective provider" framing.

---

## 12. References

- `logs/daily_run_2026-05-09.log` — diagnostic source
- `logs/monitor_check_2026-05-09.log` — diagnostic source
- `src/orchestration/paper_processor.py:138-145` — bug location
- `src/services/extraction_service.py:172-218` — correct download pattern
- [PHASE_9_RESEARCH_INTELLIGENCE_SPEC.md](PHASE_9_RESEARCH_INTELLIGENCE_SPEC.md) — parent phase spec
- [.omc/plans/phase-9-execution-plan.md](../../.omc/plans/phase-9-execution-plan.md) — original Phase 9 execution plan
- [.omc/plans/phase-9.5-execution-plan.md](../../.omc/plans/phase-9.5-execution-plan.md) — Phase 9.5 execution plan (this phase)

---

**Document Status:** DRAFT — pending user review
**Next Step:** User review of this spec; on approval, execute per `phase-9.5-execution-plan.md`
