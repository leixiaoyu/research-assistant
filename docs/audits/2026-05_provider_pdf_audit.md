# Provider PDF Resolution Audit (May 2026)

**Phase 9.5 Workstream A — Task A.8 (REQ-9.5.1.5)**
**Auditor:** Phase 9.5 Workstream A self-review
**Audit date:** 2026-05-12
**Audit window:** Production daily-run logs `2026-05-07` through `2026-05-09`

---

## Executive Summary

The Phase 9.5 spec (`PHASE_9.5_RELIABILITY_BREADTH_LEARNING_SPEC.md` §3.1
REQ-9.5.1.5) flagged that two non-ArXiv providers in the discovery chain
were returning zero PDFs in production: HuggingFace fetched 100 results
per query and filtered all of them out, and Semantic Scholar reported
`pdf_available: 0` on every event. The audit confirms both observations
but also confirms that **neither provider is bugged** — both are
operating as designed. The "zero PDF" outcome is a structural property
of the providers' data and the project's narrow query patterns, not a
broken integration.

**Recommendation: keep both providers in the default discovery chain
without code changes.** Document the expectations in operator-facing
docs so future on-call doesn't waste time chasing a non-bug. The real
discovery-breadth problem (a Phase 9.5 Workstream B concern, NOT
Workstream A) is structural and is addressed by the citation-expansion
work in Workstream B, not by patching these providers.

---

## Diagnostic Evidence

From `logs/daily_run_2026-05-09.log`, by-provider results across the 8
configured topics:

| Provider | Returned per query (avg) | `pdf_available` rate | Source code line |
|---|---|---|---|
| ArXiv | ~20 | ~100% | `src/services/providers/arxiv.py:394` |
| Semantic Scholar | ~20 | **0%** | `src/services/providers/semantic_scholar.py:185-223` |
| HuggingFace | **0** (after filter; 100 raw fetches) | n/a (none returned) | `src/services/providers/huggingface.py:184-188` |

The OpenAlex provider exists in the codebase but is not enabled in the
default daily-run pipeline (Phase 6 integration is pending per
`docs/PHASED_DELIVERY_PLAN.md`).

---

## Finding 1 — HuggingFace returns 0 papers (by design)

### What we observed

```
{"query": "neural machine translation low-resource language",
 "count": 0, "provider": "huggingface", "total_fetched": 100,
 "pdf_available": 0, "pdf_rate": "0.0%",
 "event": "papers_discovered"}
```

For every topic in `config/research_config.yaml`, the HuggingFace
provider fetches 100 papers from the API and filters down to zero.

### Root cause

The HuggingFace provider hits `https://huggingface.co/api/daily_papers`
(`huggingface.py:61`). This is **the daily-trending feed**, not a search
endpoint. The API does not support keyword search — there is no `q=`
parameter. The provider compensates by:

1. Fetching the 100 most-recent trending papers (the entire feed window)
2. Applying client-side keyword filter with **AND semantics**
   (`huggingface.py:335-365`): for the query
   `"Tree of Thoughts AND machine translation"`, the filter requires
   ALL of `tree`, `thoughts`, and `machine translation` to appear in
   either title or abstract.

For narrow research topics like the project's current 8 configurations
(e.g. `"document-level machine translation German"`,
`"chain-of-thought reasoning large language model"`), the trending
window of ~100 papers rarely contains anything that satisfies a 3-4-term
AND filter. The result: zero matches per topic.

### Is it bugged?

**No.** PDF URLs ARE populated when papers do match — the provider
correctly assigns `open_access_pdf` from ArXiv (`huggingface.py:293-296`)
since HuggingFace daily-papers wraps ArXiv preprints. The filter
behavior is the documented and expected design: HuggingFace daily papers
is a *discovery* signal (curated, trending), not a comprehensive index.

### Recommendation

**Keep HuggingFace in the default chain.** It contributes near-zero
papers today against the project's narrow queries, but on the
infrequent runs where a topic happens to align with current trending
papers (e.g., a query for "RAG" during a week of heavy RAG-paper
activity), it surfaces high-signal papers we might otherwise miss.
Removing it costs us those occasional hits at no per-run resource cost
worth speaking of (one HTTP call per topic, results filtered locally).

What we should NOT do: try to "fix" the AND-filter to be looser — that
would defeat the curation value. If the project later wants HF as a
broader contributor, the right path is OR-semantics behind a feature
flag, but that is out of scope for Phase 9.5.

---

## Finding 2 — Semantic Scholar returns `pdf_available: 0` (data limit)

### What we observed

```
{"query": "neural machine translation low-resource language",
 "count": 20, "provider": "semantic_scholar",
 "pdf_available": 0, "pdf_rate": "0.0%",
 "event": "papers_discovered"}
```

S2 returns 20 papers per query consistently, but **none** of them have a
populated `open_access_pdf` URL.

### Root cause

The S2 client requests the `openAccessPdf` field correctly
(`semantic_scholar.py:142`) and parses it correctly
(`semantic_scholar.py:185-191`). When the field is present and contains
a `url`, `pdf_available=True` and `open_access_pdf` is populated;
otherwise both are unset.

The reality is that **S2's `openAccessPdf` field is sparsely populated**.
S2 indexes ~200M papers but only links open-access PDFs for a subset —
their own [API docs](https://api.semanticscholar.org/api-docs/) note
that `openAccessPdf` is set when "an open access version of the paper is
available". For our specific narrow research-topic queries (which select
recent NMT/LLM research papers), most matches are either not yet
indexed for OA or are paywalled.

We DO have a `SEMANTIC_SCHOLAR_API_KEY` configured (per `.env`), so this
is not an auth/quota issue. The 0% rate is genuine data sparsity.

### Is it bugged?

**No.** The provider faithfully reports what S2's API returns. PDFs
would surface here if S2 had them; they don't.

### Recommendation

**Keep Semantic Scholar in the default chain.** S2 is essential for
non-PDF metadata: citation counts, venue info, author IDs, abstracts.
Even though it doesn't currently contribute PDFs for the project's
queries, it powers downstream features (Phase 9.2 citation graph, Phase
6 quality scoring). Its 20 results per query are deduplicated against
ArXiv's 20 results, so the registry growth is incremental.

What we should NOT do: try to "fix" S2's PDF coverage from our side —
the field is opaque to us. If we want PDFs for S2-only papers, the
right path is integrating Unpaywall (`api.unpaywall.org`) which
specialises in OA PDF resolution. That is explicitly out of scope for
Phase 9.5 (REQ-9.5.1.5 says "fixed or documented", and we choose
"documented").

---

## Net Effect on Discovery Pipeline

Despite the multi-provider architecture, **only ArXiv contributes
PDF-bearing papers** to the extraction pipeline today. This means:

- The **abstract-fallback SLO** (REQ-9.5.1.4, addressed in this same
  PR) measures what fraction of ArXiv-extracted papers had to fall back
  to abstract-only — it does NOT measure non-ArXiv providers, because
  they don't supply PDFs.
- Adding new PDF-bearing providers (Crossref, CORE, Unpaywall) is the
  proper way to broaden PDF coverage. Phase 9.5 explicitly defers this
  per the user's AskUserQuestion answer on 2026-05-09 (Workstream B
  scope: citation expansion + LLM query auto-expansion only; new
  providers explicitly out of scope).
- Phase 9.5 Workstream B (citation expansion) provides a different
  axis of breadth: more *kinds of papers* per topic via the citation
  neighbourhood of high-quality seeds, even if all are still
  ArXiv-sourced.

---

## Action Items

1. ✅ **No code changes** — both providers behave as designed.
2. ✅ **Spec updated** — REQ-9.5.1.5 satisfied: this audit document
   serves as the "documented as non-PDF-bearing" path the spec
   explicitly allows for.
3. ⏭️ **Future work** (NOT this PR): add Unpaywall provider for
   genuine PDF broadening. Track in Phase 10+ backlog.
4. ⏭️ **Operator runbook update** (follow-up): note that HF/S2 are
   non-PDF-bearing in current production so on-call doesn't chase
   `pdf_rate: "0.0%"` events from these providers.

---

## Appendix: Verification Steps Reproducible By Reviewer

To independently confirm this audit's findings:

```bash
# 1. Confirm HuggingFace fetches but filters out
grep -E '"provider": "huggingface".*total_fetched' logs/daily_run_*.log | head

# 2. Confirm Semantic Scholar returns papers but no PDFs
grep -E '"provider": "semantic_scholar".*pdf_available' logs/daily_run_*.log | head

# 3. Confirm ArXiv is the sole PDF-bearing source
grep -E '"provider": "arxiv".*pdf_rate' logs/daily_run_*.log | head

# 4. Inspect HuggingFace AND-filter implementation
sed -n '335,365p' src/services/providers/huggingface.py

# 5. Inspect Semantic Scholar openAccessPdf parsing
sed -n '180,225p' src/services/providers/semantic_scholar.py
```

All findings reproduce against `feature/phase-9.5-pipeline-reliability`
HEAD as of audit date.
