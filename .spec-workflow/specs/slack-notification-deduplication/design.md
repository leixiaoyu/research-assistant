# Design Document: Slack Notification Deduplication

## Overview

This design implements deduplication-aware Slack notifications for the ARISP research pipeline. The feature ensures users see only NEW papers in daily notifications, eliminating confusion from repeated papers across runs.

**Key Design Decision:** Leverage the existing `RegistryService` for paper identity resolution, but implement notification-specific deduplication logic in a new `src/services/notification/` package to maintain separation of concerns.

## Code Reuse Analysis

### Existing Components to Leverage

| Component | Purpose | How Used |
|-----------|---------|----------|
| `RegistryService` | Global paper identity tracking | Query paper status (PROCESSED, FAILED, etc.) |
| `NotificationService` | Slack message sending | Extend with deduplication-aware summary creation |
| `SlackMessageBuilder` | Block Kit formatting | Add new paper list sections |
| `PipelineSummary` | Notification data model | Extend with new/retry/duplicate counts |
| `SlackConfig` | Notification configuration | Add new config options |

### Integration Points

- **Pipeline Result**: Intercept `papers_discovered` before notification to categorize as new/retry/duplicate
- **Registry Service**: Use `resolve_identity()` to check if paper exists
- **Notification Flow**: Insert deduplication step before `create_summary_from_result()`

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Pipeline Completion                             │
│                                                                      │
│   PipelineResult                                                     │
│   (raw papers_discovered)                                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              NotificationDeduplicator (NEW)                          │
│              src/services/notification/deduplicator.py              │
│                                                                      │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │ For each paper in discovered_papers:                         │   │
│   │   1. Query RegistryService.resolve_identity(paper)          │   │
│   │   2. Check entry status (PROCESSED/MAPPED vs FAILED/SKIPPED)│   │
│   │   3. Categorize: new_papers / retry_papers / duplicate_papers│   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│   Output: DeduplicationResult                                        │
│   - new_papers: List[PaperMetadata]                                 │
│   - retry_papers: List[PaperMetadata]                               │
│   - duplicate_papers: List[PaperMetadata]                           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Enhanced PipelineSummary                                │
│              (new fields added)                                      │
│                                                                      │
│   - new_papers_count: int                                           │
│   - retry_papers_count: int                                         │
│   - duplicate_papers_count: int                                     │
│   - new_paper_titles: List[str]  (top 5)                           │
│   - total_papers_checked: int                                       │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Enhanced SlackMessageBuilder                            │
│              (new sections added)                                    │
│                                                                      │
│   _build_stats_section() - Updated to show new/retry/dup counts     │
│   _build_new_papers_section() - NEW: Lists new paper titles         │
│   _build_retry_papers_section() - NEW: Shows retry papers           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Slack Webhook                                 │
│                    (existing integration)                            │
└─────────────────────────────────────────────────────────────────────┘
```

## Components and Interfaces

### Component 1: NotificationDeduplicator

- **Purpose:** Categorize discovered papers into new/retry/duplicate based on registry status
- **Location:** `src/services/notification/deduplicator.py`
- **Interfaces:**
  ```python
  class NotificationDeduplicator:
      def __init__(self, registry_service: RegistryService): ...

      def categorize_papers(
          self,
          papers: List[PaperMetadata]
      ) -> DeduplicationResult: ...
  ```
- **Dependencies:** `RegistryService`
- **Reuses:** Registry identity resolution logic

### Component 2: DeduplicationResult (Model)

- **Purpose:** Hold categorized paper lists for notification
- **Location:** `src/models/notification.py` (extend existing)
- **Interfaces:**
  ```python
  class DeduplicationResult(BaseModel):
      new_papers: List[PaperMetadata] = []
      retry_papers: List[PaperMetadata] = []  # FAILED/SKIPPED status
      duplicate_papers: List[PaperMetadata] = []  # PROCESSED/MAPPED status

      @property
      def new_count(self) -> int: ...
      @property
      def retry_count(self) -> int: ...
      @property
      def duplicate_count(self) -> int: ...
      @property
      def total_checked(self) -> int: ...
  ```

### Component 3: Enhanced PipelineSummary

- **Purpose:** Extend existing model with deduplication-aware fields
- **Location:** `src/models/notification.py` (extend existing)
- **New Fields:**
  ```python
  # Add to PipelineSummary
  new_papers_count: int = Field(default=0)
  retry_papers_count: int = Field(default=0)
  duplicate_papers_count: int = Field(default=0)
  new_paper_titles: List[str] = Field(default_factory=list)
  total_papers_checked: int = Field(default=0)
  ```

### Component 4: Enhanced SlackConfig

- **Purpose:** Add new configuration options
- **Location:** `src/models/notification.py` (extend existing)
- **New Fields:**
  ```python
  # Add to SlackConfig
  show_duplicates_count: bool = Field(default=True)
  show_retry_papers: bool = Field(default=True)
  max_new_papers_listed: int = Field(default=5, ge=1, le=20)
  include_total_checked: bool = Field(default=True)
  ```

### Component 5: Enhanced SlackMessageBuilder

- **Purpose:** Build Slack messages with new paper sections
- **Location:** `src/services/notification_service.py` (extend existing)
- **New Methods:**
  ```python
  def _build_dedup_stats_section(self, summary: PipelineSummary) -> Dict[str, Any]: ...
  def _build_new_papers_section(self, summary: PipelineSummary) -> List[Dict[str, Any]]: ...
  def _build_retry_papers_section(self, summary: PipelineSummary) -> Dict[str, Any]: ...
  ```

## Data Models

### DeduplicationResult

```python
class DeduplicationResult(BaseModel):
    """Result of categorizing papers for notification."""

    new_papers: List[PaperMetadata] = Field(
        default_factory=list,
        description="Papers not in registry (truly new)"
    )
    retry_papers: List[PaperMetadata] = Field(
        default_factory=list,
        description="Papers with FAILED/SKIPPED status (retry candidates)"
    )
    duplicate_papers: List[PaperMetadata] = Field(
        default_factory=list,
        description="Papers with PROCESSED/MAPPED status (already notified)"
    )

    @property
    def new_count(self) -> int:
        return len(self.new_papers)

    @property
    def total_checked(self) -> int:
        return len(self.new_papers) + len(self.retry_papers) + len(self.duplicate_papers)
```

### Extended SlackConfig

```python
# Additional fields for SlackConfig
show_duplicates_count: bool = True
show_retry_papers: bool = True
max_new_papers_listed: int = 5
include_total_checked: bool = True
```

## Error Handling

### Error Scenarios

1. **Registry Unavailable**
   - **Handling:** Fall back to raw counts (all papers as "new"), log warning
   - **User Impact:** User sees old behavior until registry is restored

2. **Registry Load Error (corrupted file)**
   - **Handling:** Log error, treat all papers as new (graceful degradation)
   - **User Impact:** One-time reset of dedup state, returns to normal next run

3. **Paper Missing from Registry (edge case)**
   - **Handling:** Count as "new" paper
   - **User Impact:** None (correct behavior)

4. **Empty Paper List**
   - **Handling:** Show "No papers discovered" message
   - **User Impact:** Clear feedback that query returned no results

## Testing Strategy

### Unit Testing

- `test_notification_deduplicator.py`
  - `test_categorize_all_new_papers` - Empty registry, all papers are new
  - `test_categorize_all_duplicates` - All papers in registry with PROCESSED status
  - `test_categorize_mixed` - Mix of new, retry, and duplicate papers
  - `test_categorize_failed_papers_as_retry` - Papers with FAILED status
  - `test_categorize_skipped_papers_as_retry` - Papers with SKIPPED status
  - `test_graceful_fallback_registry_unavailable` - Registry error handling

- `test_enhanced_pipeline_summary.py`
  - `test_new_fields_default_values` - New fields have correct defaults
  - `test_new_paper_titles_truncated` - Top N titles only

- `test_enhanced_slack_message_builder.py`
  - `test_build_dedup_stats_section` - Correct formatting
  - `test_build_new_papers_section` - Paper titles listed
  - `test_config_respects_show_duplicates_count` - Config honored

### Integration Testing

- `test_notification_integration.py`
  - `test_full_dedup_flow` - End-to-end with real registry
  - `test_backward_compatibility` - Existing configs still work
  - `test_first_run_all_papers_new` - Empty registry scenario

### Coverage Target

- All new code: ≥99% coverage
- Overall project: Maintain ≥99%

## File Structure

```
src/services/notification/
├── __init__.py           # Export NotificationDeduplicator
└── deduplicator.py       # NotificationDeduplicator class (~100 lines)

src/models/notification.py  # Extended (add ~50 lines)
src/services/notification_service.py  # Extended (add ~80 lines)

tests/unit/test_services/
└── test_notification_deduplicator.py  # New (~200 lines)

tests/unit/test_models/
└── test_notification.py  # Extended (~50 lines)
```

## Backward Compatibility

1. **Existing Slack configs** continue to work (new fields have defaults)
2. **First run after upgrade** treats all papers as new (empty registry = graceful start)
3. **CLI/scheduler integration** unchanged (deduplication is transparent)
4. **No database migrations** required (registry already tracks paper status)

## Performance Considerations

- **Registry lookups**: O(1) for DOI/paper_id via indexes
- **Fuzzy title matching**: Only used when DOI/ID not found (~O(n) worst case)
- **Expected overhead**: `<50ms` for typical 100-paper batch
- **Memory**: Minimal (no caching beyond registry state)
