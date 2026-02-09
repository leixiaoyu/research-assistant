# Phase 3.5: Global Paper Identity & Incremental Backfilling
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 1 week
**Dependencies:**
- Phase 3.2 Complete (Multi-provider discovery)
- Phase 3.3 Complete (LLM fallback & resilience)

---

## Architecture Reference

This phase evolves the system state from topic-local to system-global, as defined in [SYSTEM_ARCHITECTURE.md §7 Storage & Caching](../SYSTEM_ARCHITECTURE.md#storage--caching).

**Architectural Gaps Addressed:**
- ❌ Gap: Redundant processing of the same paper across different topics
- ❌ Gap: No mechanism to "backfill" data when extraction requirements evolve
- ❌ Gap: Inconsistent identity resolution between different discovery providers
- ❌ Gap: Fragile state management (potential for duplicate processing on restart)

**Components Modified:**
- Discovery Service (`src/services/discovery_service.py`)
- Concurrent Pipeline (`src/orchestration/concurrent_pipeline.py`)
- LLM Service (`src/services/llm_service.py`)
- Config Manager (`src/services/config_manager.py`)
- New Service: Registry Service (`src/services/registry_service.py`)

**Coverage Targets:**
- Registry logic: 100%
- Identity resolution: 100%
- Backfill detection: 100%
- State persistence: 100%

---

## 1. Executive Summary

Phase 3.5 transforms ARISP from a snapshot tool into a **stateful knowledge engine**. By implementing a **Global Identity Registry**, the system ensures that every research paper is processed exactly once regardless of which topic discovered it. Furthermore, it introduces **Incremental Backfilling**, which detects when an existing paper needs additional extraction because the user's research goals (extraction targets) have changed.

**Key Achievement:** Transform from topic-isolated processing to a unified global knowledge state with intelligent update detection.

---

## 2. Problem Statement

### 2.1 The Identity Problem
Currently, paper deduplication is primarily topic-local. If "Large Language Models" and "Transformer Architecture" both discover "Attention is All You Need," the system may process it twice, wasting API costs and local storage. Identity resolution is also difficult because ArXiv and Semantic Scholar often have different internal IDs for the same work.

### 2.2 The Requirement Drift Problem (Backfilling)
When a user updates their `research_config.yaml` to include a new extraction target (e.g., adding "Extract Code Snippets" to an existing topic), the system currently only applies this to *newly* found papers. There is no automated way to go back to the hundreds of already-processed papers and "fill in the blanks" for the new requirement.

### 2.3 The Knowledge Fragmentation
Knowledge is currently scattered across dated files. There is no "source of truth" for what we know about a specific paper that spans all topics it might be relevant to.

---

## 3. Requirements

### 3.1 Global Identity Resolution

#### REQ-3.5.1: Priority-Based Identity Mapping
The system SHALL resolve paper identity using a multi-stage priority logic.

**Scenario: DOI Resolution**
**Given** a paper has a valid DOI
**When** checking the registry
**Then** the DOI SHALL be the primary key for identity.

**Scenario: Provider ID Cross-Link**
**Given** a paper lacks a DOI
**When** checking the registry
**Then** the system SHALL match against `provider:id` (e.g., `arxiv:2301.12345` or `ss:paper_uuid`).

**Scenario: Fuzzy Title Matching**
**Given** both DOI and Provider IDs fail to match
**When** title similarity is > 95% (normalized alphanumeric strings)
**Then** the system SHALL treat the papers as identical.

### 3.2 Global Paper Registry

#### REQ-3.5.2: Persistent Identity Registry
The system SHALL maintain a `data/registry.json` file as the global source of truth.

**Data to Track per Paper:**
- Canonical `paper_id` (System-generated UUID)
- All known external identifiers (DOI, ArXiv ID, SS ID)
- Normalized title (for fuzzy matching)
- `extraction_target_hash` (Hash of targets + prompts used for the last extraction)
- `topic_affiliations` (Set of all topics this paper has been discovered for)
- `processed_at` timestamp

#### REQ-3.5.3: Atomic State Updates
Registry updates SHALL be atomic to prevent corruption.
- Write to `.tmp` file, then rename.
- Update registry immediately after a paper completes processing in the worker pool.

### 3.3 Incremental Backfilling

#### REQ-3.5.4: Extraction Hash Validation
The pipeline SHALL detect when a paper requires backfilling.

**Logic:**
1. Generate `current_hash` from the current topic's `extraction_targets` (names + descriptions).
2. Compare `current_hash` against the paper's `extraction_target_hash` in the registry.
3. If they differ → Mark for **BACKFILL**.

#### REQ-3.5.5: Partial Extraction Processing
The `LLMService` and `ConcurrentPipeline` SHALL support backfill mode.

**Scenario: Backfill Execution**
**Given** a paper is marked for BACKFILL
**Then** the system SHALL:
- Skip the Acquisition phase (reuse existing PDF/Markdown).
- Execute LLM extraction for the *entire* target set (to ensure consistent synthesis).
- Update the registry with the new extraction results and the new `extraction_target_hash`.

### 3.4 Cross-Topic Integration

#### REQ-3.5.6: Zero-Cost Topic Affiliation
If a paper is discovered for Topic B but was already fully processed for Topic A with the same extraction requirements:
- The system SHALL skip all processing.
- The system SHALL add Topic B to the paper's `topic_affiliations` in the registry.
- The paper SHALL be included in the synthesis for Topic B.

---

## 4. Technical Design

### 4.1 Registry Data Model

```python
class RegistryEntry(BaseModel):
    paper_id: str                      # UUID
    identifiers: Dict[str, str]        # {"doi": "...", "arxiv": "...", "ss": "..."}
    title_normalized: str              # Slugified/Normalized title
    processed_at: datetime
    extraction_target_hash: str        # Hash of targets
    topic_affiliations: List[str]      # List of topic slugs
    metadata: PaperMetadata            # Most recent metadata snapshot
```

### 4.2 Backfill Detection Algorithm

```python
def determine_processing_action(paper: PaperMetadata, topic: ResearchTopic) -> Action:
    # 1. Resolve Identity
    entry = registry.resolve(paper)
    
    # 2. If new paper -> Full process
    if not entry:
        return Action.FULL_PROCESS
        
    # 3. Check if targets have changed
    target_hash = calculate_target_hash(topic.extraction_targets)
    if entry.extraction_target_hash != target_hash:
        return Action.BACKFILL
        
    # 4. If already associated with this topic -> Skip
    if topic.slug in entry.topic_affiliations:
        return Action.SKIP
        
    # 5. Same requirements, different topic -> Map only
    return Action.MAP_ONLY
```

---

## 5. Implementation Tasks

### Task 1: Registry Infrastructure (1 day)
**Files:** `src/models/registry.py`, `src/services/registry_service.py`
- Implement `RegistryEntry` Pydantic model.
- Create `RegistryService` with atomic load/save.
- Implement identity resolution logic (DOI -> ID -> Fuzzy Title).

### Task 2: Requirement Tracking (1 day)
**Files:** `src/utils/hash.py`, `src/services/config_manager.py`
- Implement stable hashing for `extraction_targets`.
- Update `ResearchTopic` to include unique slug generation.

### Task 3: Backfill Logic Integration (2 days)
**Files:** `src/orchestration/concurrent_pipeline.py`, `src/services/llm_service.py`
- Modify pipeline to check registry before starting workers.
- Implement `Action.BACKFILL` path: skip download/convert, trigger LLM.
- Implement `Action.MAP_ONLY` path: update registry affiliations, skip processing.

### Task 4: State Synchronization (1 day)
**Files:** `src/services/catalog_service.py`
- Ensure `catalog.json` and `registry.json` remain synchronized.
- Handle edge cases like manual file deletions.

---

## 6. Verification Criteria

### 6.1 Unit Tests
- `test_resolve_identity_by_doi`: Resolve identical papers via DOI.
- `test_resolve_identity_by_fuzzy_title`: Resolve identical papers via normalized title.
- `test_backfill_trigger`: Detect hash mismatch when targets change.
- `test_atomic_write_recovery`: Ensure registry is not corrupted if process crashes during write.

### 6.2 Integration Tests
- `test_cross_topic_skip`: Process paper in Topic A, verify zero processing when same paper found in Topic B.
- `test_backfill_flow`: Process paper, change topic extraction target, verify re-extraction on next run.
- `test_duplicate_prevention`: Verify that even with multiple topics running concurrently, a paper is only processed once.

---

## 7. Risks & Mitigations

| Risk | Impact | Mitigation |
| :--- | :--- | :--- |
| **Identity Collision** | Medium | High-threshold fuzzy matching (95%+) and DOI priority. |
| **Registry Corruption** | High | Atomic writes with backup `.tmp` files. |
| **Performance Lag** | Low | In-memory registry cache with periodic sync. |
| **Stale Metadata** | Low | Update registry metadata snapshot on every discovery match. |
