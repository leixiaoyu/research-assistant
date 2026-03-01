# Phase 3.8: Slack Notification Deduplication
**Version:** 1.0
**Status:** Implementation Complete
**Timeline:** 1 day
**Dependencies:**
- Phase 3.5 Complete (Global Paper Identity Registry)
- Phase 3.7 Complete (Slack Notifications)

---

## Architecture Reference

This phase extends the notification system to provide deduplication-aware reporting, building on the Global Paper Identity Registry (Phase 3.5) and Slack Notification infrastructure (Phase 3.7).

**Architectural Gaps Addressed:**
- Gap: Notifications report total papers without distinguishing new vs. previously seen
- Gap: Users cannot easily identify genuinely new discoveries vs. cross-topic duplicates
- Gap: No integration between registry deduplication and notification summaries

**Components Modified:**
- Notification Service (`src/services/notification_service.py`)
- Slack Message Builder (`src/services/notification/slack_builder.py`)
- CLI Run Command (`src/cli/run.py`)
- Scheduler Jobs (`src/scheduling/jobs.py`)

**New Components:**
- Notification Deduplicator (`src/services/notification/deduplicator.py`)
- Deduplication Result Model (`src/models/notification.py`)

**Components Extended:**
- Research Pipeline (`src/orchestration/pipeline.py`) - Added public `context` property

**Coverage Targets:**
- Deduplicator logic: 100%
- Slack message formatting: 100%
- Pipeline integration: 100%

---

## 1. Executive Summary

Phase 3.8 enhances Slack notifications with deduplication awareness, allowing users to immediately identify which papers in a research run are genuinely new discoveries versus papers that were previously processed (either in the current run or in previous runs).

**What This Phase Is:**
- Categorization of discovered papers as "new" or "duplicate" based on registry presence
- Enhanced Slack notifications showing deduplication statistics
- Visual differentiation of new papers in notification summaries
- Integration with the existing Global Paper Identity Registry (Phase 3.5)

**What This Phase Is NOT:**
- Adding a processing status field to RegistryEntry (reserved for future phase)
- Retry logic for failed papers (requires status tracking not yet implemented)
- Modification of the registry's identity resolution logic
- Changes to the deduplication during pipeline execution

---

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority | Status |
|----|-------------|----------|--------|
| FR-1 | Categorize papers as "new" (not in registry) or "duplicate" (in registry) | Must Have | Done |
| FR-2 | Display deduplication statistics in Slack notifications | Must Have | Done |
| FR-3 | List new paper titles in notification summary | Should Have | Done |
| FR-4 | Graceful degradation when registry is unavailable | Must Have | Done |
| FR-5 | Integration with CLI run command | Must Have | Done |
| FR-6 | Integration with scheduled jobs | Must Have | Done |

### 2.2 Non-Functional Requirements

| ID | Requirement | Target | Status |
|----|-------------|--------|--------|
| NFR-1 | Test coverage | >= 99% | Done |
| NFR-2 | No breaking changes to existing notification flow | 100% | Done |
| NFR-3 | Fail-safe operation (errors don't break pipeline) | 100% | Done |

---

## 3. Technical Design

### 3.1 Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Research Pipeline                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐   │
│  │  Discovery   │───>│  Extraction  │───>│  Notification    │   │
│  │    Phase     │    │    Phase     │    │     Phase        │   │
│  └──────────────┘    └──────────────┘    └────────┬─────────┘   │
│                                                    │             │
│                                          ┌────────▼─────────┐   │
│                                          │ Pipeline.context │   │
│                                          │   (public prop)  │   │
│                                          └────────┬─────────┘   │
└───────────────────────────────────────────────────┼─────────────┘
                                                    │
                        ┌───────────────────────────▼───────────────┐
                        │       NotificationDeduplicator            │
                        │  ┌─────────────────────────────────────┐  │
                        │  │ categorize_papers(papers) -> Result │  │
                        │  └──────────────┬──────────────────────┘  │
                        │                 │                         │
                        │        ┌────────▼────────┐                │
                        │        │ RegistryService │                │
                        │        │ resolve_identity│                │
                        │        └─────────────────┘                │
                        └───────────────────────────────────────────┘
                                          │
                                          ▼
                        ┌───────────────────────────────────────────┐
                        │         DeduplicationResult               │
                        │  ┌─────────────┬─────────────┬─────────┐  │
                        │  │ new_papers  │retry_papers │duplicate│  │
                        │  │   (list)    │  (empty*)   │ (list)  │  │
                        │  └─────────────┴─────────────┴─────────┘  │
                        └───────────────────────────────────────────┘
                                          │
                                          ▼
                        ┌───────────────────────────────────────────┐
                        │           SlackMessageBuilder             │
                        │  ┌─────────────────────────────────────┐  │
                        │  │ Dedup Stats Block:                  │  │
                        │  │ "New: 5 | Previously Seen: 3"       │  │
                        │  │                                     │  │
                        │  │ New Papers Section:                 │  │
                        │  │ • Paper Title 1                     │  │
                        │  │ • Paper Title 2                     │  │
                        │  └─────────────────────────────────────┘  │
                        └───────────────────────────────────────────┘

* retry_papers is reserved for future use when RegistryEntry gains status tracking
```

### 3.2 Data Models

```python
class DeduplicationResult(BaseModel):
    """Result of paper categorization for notifications."""

    new_papers: List[dict] = []      # Papers not in registry
    retry_papers: List[dict] = []    # Reserved for future (always empty)
    duplicate_papers: List[dict] = [] # Papers found in registry

    @property
    def new_count(self) -> int: ...
    @property
    def retry_count(self) -> int: ...
    @property
    def duplicate_count(self) -> int: ...
    @property
    def total_checked(self) -> int: ...
```

### 3.3 Categorization Logic

The `NotificationDeduplicator` uses a simple presence-based categorization:

```python
def _categorize_single_paper(self, paper: PaperMetadata) -> str:
    """Categorize based on registry presence only."""
    match = self.registry_service.resolve_identity(paper)

    if not match.matched:
        return "new"      # Not in registry = new discovery

    if match.entry is None:
        return "new"      # Edge case: matched but no entry

    return "duplicate"    # In registry = already processed
```

**Note on Retry Logic:**
The `retry_papers` category is reserved for future implementation when `RegistryEntry` gains a `status` field to track processing outcomes (PROCESSED, FAILED, SKIPPED). Currently, we cannot distinguish between successfully processed papers and those that failed, so all registered papers are categorized as duplicates.

### 3.4 Pipeline Integration

The pipeline exposes a public `context` property for post-execution access:

```python
class ResearchPipeline:
    @property
    def context(self) -> Optional[PipelineContext]:
        """Get the pipeline context after execution."""
        return self._context
```

CLI and scheduler access the context via this public property:

```python
# In CLI run.py and scheduler jobs.py
if pipeline is not None:
    context = pipeline.context  # Use public property
    if context is not None:
        all_papers = []
        for papers in context.discovered_papers.values():
            all_papers.extend(papers)

        deduplicator = NotificationDeduplicator(context.registry_service)
        dedup_result = deduplicator.categorize_papers(all_papers)
```

---

## 4. Verification Criteria

### 4.1 Unit Tests

| Test Case | Description | Status |
|-----------|-------------|--------|
| `test_categorize_all_new_papers` | All papers not in registry → new | Pass |
| `test_categorize_all_duplicates` | All papers in registry → duplicate | Pass |
| `test_categorize_mixed_papers` | Mix of new and duplicate | Pass |
| `test_retry_always_empty_without_status_tracking` | Retry category always empty | Pass |
| `test_graceful_fallback_no_registry` | No registry → all treated as new | Pass |
| `test_graceful_fallback_registry_error` | Registry error → all treated as new | Pass |
| `test_empty_paper_list` | Empty input handled correctly | Pass |
| `test_matched_but_no_entry_treated_as_new` | Edge case handling | Pass |
| `test_paper_data_preserved_in_result` | Paper data in result | Pass |
| `test_duplicate_paper_data_preserved` | Duplicate data preserved | Pass |
| `test_partial_error_handling` | Partial errors don't break categorization | Pass |
| `test_resolve_identity_called_for_each_paper` | Registry called per paper | Pass |

### 4.2 Integration Tests

| Test Case | Description | Status |
|-----------|-------------|--------|
| CLI with dedup notifications | End-to-end CLI with dedup stats | Pass |
| Scheduler job with dedup | Scheduled job sends dedup notifications | Pass |
| Pipeline context access | Public context property accessible | Pass |

---

## 5. Future Enhancements

### 5.1 Status Tracking (Future Phase)

To enable true retry logic, the following changes would be needed:

1. Add `status` field to `RegistryEntry`:
   ```python
   class ProcessingStatus(str, Enum):
       PROCESSED = "processed"
       FAILED = "failed"
       SKIPPED = "skipped"

   class RegistryEntry(BaseModel):
       status: ProcessingStatus = ProcessingStatus.PROCESSED
   ```

2. Update `RegistryService.register_paper()` to record outcomes

3. Update `NotificationDeduplicator._categorize_single_paper()` to check status:
   ```python
   if entry.status in (ProcessingStatus.FAILED, ProcessingStatus.SKIPPED):
       return "retry"
   return "duplicate"
   ```

---

## 6. Security Considerations

- No sensitive data exposed in notifications (only paper titles/counts)
- Slack webhook URLs remain in environment variables
- Registry access is read-only for deduplication checks
- Fail-safe design prevents notification errors from breaking pipeline

---

## 7. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-02-28 | Initial implementation with new/duplicate categorization |
