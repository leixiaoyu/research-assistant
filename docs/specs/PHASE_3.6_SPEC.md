# Phase 3.6: Cumulative Knowledge Synthesis (Living Knowledge Base)
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 1 week
**Dependencies:**
- Phase 3.5 Complete (Global Identity & Backfilling)
- Phase 3.4 Complete (Quality-First Discovery)

---

## Architecture Reference

This phase evolves the output generation layer from run-based logs to persistent knowledge assets, as defined in [SYSTEM_ARCHITECTURE.md §5.5 Storage Service](../SYSTEM_ARCHITECTURE.md#core-components).

**Architectural Gaps Addressed:**
- ❌ Gap: Research results are scattered across dated files, hindering synthesis.
- ❌ Gap: No unified "source of truth" for a research topic.
- ❌ Gap: Difficult to track "what changed" in a specific run vs. "what we know" overall.
- ❌ Gap: Quality rankings are lost between runs.

**Components Modified:**
- Output Layer: `EnhancedGenerator` (`src/output/enhanced_generator.py`)
- Service Layer: `RegistryService` (`src/services/registry_service.py`)
- Orchestration: `ResearchPipeline` (`src/orchestration/research_pipeline.py`)
- New Component: `SynthesisEngine` (`src/output/synthesis_engine.py`)

**Coverage Targets:**
- Synthesis logic: 100%
- Dual-stream generation: 100%
- File management: 100%

---

## 1. Executive Summary

Phase 3.6 transforms the ARISP output model from "event-based reporting" to **"knowledge-base synthesis."** It introduces a dual-stream output system:
1.  **Delta Briefs:** A run-specific snapshot of "What is new or updated today."
2.  **Living Knowledge Base:** A persistent, cumulative master document (`Knowledge_Base.md`) for each topic that represents the totality of learned information, automatically updated and quality-ranked.

---

## 2. Problem Statement

### 2.1 The Snapshot Problem
Currently, the pipeline creates a new markdown file for every run (e.g., `2026-02-08_Research.md`). If you run the same topic for a month, you end up with 30 files. To find a specific piece of information, you must search across all 30 files, which defeats the purpose of an automated assistant.

### 2.2 The Lack of Delta Awareness
When the pipeline runs and finds 50 papers, but only 5 are "new" (thanks to Phase 3.5), the current output doesn't clearly distinguish between the new findings and the papers it already knew about. The user loses visibility into the *incremental* value of the latest run.

### 2.3 The Quality Decay
Papers are ranked by quality within a single run (Phase 3.4), but that ranking is lost over time. There is no central place where the *highest quality papers ever found* for a topic are aggregated.

---

## 3. Requirements

### 3.1 Dual-Stream Output Model

#### REQ-3.6.1: Run-Specific Delta Briefs
Each run SHALL generate a `runs/YYYY-MM-DD_Delta.md` file in the topic directory.

**Requirements for Delta Briefs:**
- **New Section:** Details for papers processed for the first time.
- **Backfill Section:** Details for existing papers that were updated with new extraction targets.
- **Summary Metrics:** Total new papers, total backfilled, total ignored (duplicates).

#### REQ-3.6.2: Persistent Knowledge Base (Living Document)
Each topic SHALL maintain a `Knowledge_Base.md` file in its root directory.

**Requirements for Knowledge Base:**
- **Cumulative:** Includes every paper associated with the topic from the beginning of time.
- **Deduplicated:** Each paper appears exactly once.
- **Quality-Sorted:** Papers are ranked by `quality_score` (from Phase 3.4), ensuring the best research is always at the top of the file.
- **Automated Updates:** The file is re-synthesized at the end of every successful run.

### 3.2 Synthesis Engine

#### REQ-3.6.3: Multi-Topic Consistency
If a paper belongs to multiple topics (Topic A and Topic B), it SHALL be synthesized into the `Knowledge_Base.md` of *both* topics.

#### REQ-3.6.4: Anchor-Based Persistence
The Synthesis Engine SHALL attempt to preserve manual user annotations.
- If a user adds notes under a specific paper header in `Knowledge_Base.md`, the engine SHOULD attempt to preserve these notes during re-synthesis (using "Anchor Tags" like `<!-- USER_NOTES_START -->`).

### 3.3 Folder Structure Evolution

#### REQ-3.6.5: Organized Workspace
The system SHALL evolve the output directory structure to support dual-stream synthesis.

```
output/
  {topic-slug}/
    Knowledge_Base.md          # Cumulative, quality-ranked master document
    runs/                      # Historical delta snapshots
      2026-02-08_Delta.md      # What changed on this date
      2026-02-01_Delta.md
    papers/                    # Raw PDFs
      paper_id.pdf
```

---

## 4. Technical Design

### 4.1 Synthesis Logic Algorithm

```python
class SynthesisEngine:
    async def synthesize(self, topic_slug: str):
        """
        1. Fetch all RegistryEntries associated with topic_slug
        2. Sort entries by quality_score (descending)
        3. Load existing Knowledge_Base.md (if any)
        4. Extract manual user notes (Anchor matching)
        5. Render fresh Knowledge_Base.md:
           - Topic Header
           - Quality Table of Contents
           - Paper Entries (with badges + extraction results)
           - Integrated User Notes
        6. Atomic write to Knowledge_Base.md
        """
```

### 4.2 Delta Detection Logic

```python
class DeltaGenerator:
    def generate_delta(self, current_run_results: List[ProcessingResult]) -> str:
        """
        1. Filter for results where status == NEW
        2. Filter for results where status == BACKFILLED
        3. Render Delta Brief highlighting these two groups
        """
```

---

## 5. Implementation Tasks

### Task 1: Synthesis Engine Core (2 days)
**Files:** `src/output/synthesis_engine.py`
- Implement the core logic to aggregate papers from the registry by topic.
- Implement quality-based sorting and categorization.
- Implement the "Living Document" renderer.

### Task 2: Anchor Persistence (1 day)
**Files:** `src/output/synthesis_engine.py`
- Implement regex-based extraction of user notes from existing markdown files.
- Ensure re-synthesis doesn't destroy manual annotations.

### Task 3: Delta Stream Implementation (1 day)
**Files:** `src/output/delta_generator.py`, `src/orchestration/research_pipeline.py`
- Update pipeline to track "New" vs "Backfilled" status.
- Implement the Delta Brief markdown template.
- Update folder structure to include the `runs/` subfolder.

### Task 4: CLI & Orchestration Update (1 day)
**Files:** `src/cli.py`, `src/orchestration/research_pipeline.py`
- Integrate `SynthesisEngine` at the end of the `run` command.
- Ensure all topics are synthesized even if some papers failed.

---

## 6. Verification Criteria

### 6.1 Functional Tests
- `test_kb_includes_all_papers`: Verify cumulative inclusion across multiple runs.
- `test_kb_quality_sorting`: Verify top-quality papers appear at the beginning.
- `test_delta_shows_only_changes`: Verify Delta Brief doesn't include "known" unchanged papers.
- `test_note_persistence`: Verify that manual text added between anchors is preserved after a re-run.

### 6.2 Visual Verification
- Inspect `Knowledge_Base.md` for clarity and professional formatting.
- Verify `runs/` directory contains correctly dated Delta files.

---

## 7. Risks & Mitigations

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| **Document Bloat** | Medium | Implement truncation or "Summary Mode" for papers with low quality scores. |
| **Note Loss** | High | Use robust regex anchors and create a `Knowledge_Base.bak` before re-synthesis. |
| **Performance** | Low | Synthesis only runs once per topic at the end of the pipeline. |
