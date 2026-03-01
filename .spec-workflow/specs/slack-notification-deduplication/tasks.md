# Tasks Document: Slack Notification Deduplication

## Overview
Implementation tasks for deduplication-aware Slack notifications, categorizing papers as new/retry/duplicate.

---

## Phase 1: Data Models

- [x] 1.1 Create DeduplicationResult model in src/models/notification.py
  - File: src/models/notification.py (extend existing)
  - Add DeduplicationResult Pydantic model with new_papers, retry_papers, duplicate_papers lists
  - Add computed properties: new_count, retry_count, duplicate_count, total_checked
  - Purpose: Hold categorized paper lists for notification processing
  - _Leverage: src/models/notification.py (existing models), src/models/paper.py (PaperMetadata)_
  - _Requirements: R1, R3_

- [x] 1.2 Extend PipelineSummary with deduplication fields
  - File: src/models/notification.py (extend existing)
  - Add fields: new_papers_count, retry_papers_count, duplicate_papers_count, new_paper_titles, total_papers_checked
  - Ensure backward compatibility with default values
  - Purpose: Surface deduplication stats in notifications
  - _Leverage: src/models/notification.py (PipelineSummary)_
  - _Requirements: R1, R5_

- [x] 1.3 Extend SlackConfig with deduplication options
  - File: src/models/notification.py (extend existing)
  - Add fields: show_duplicates_count, show_retry_papers, max_new_papers_listed, include_total_checked
  - Set sensible defaults for backward compatibility
  - Purpose: Allow users to configure notification display preferences
  - _Leverage: src/models/notification.py (SlackConfig)_
  - _Requirements: R4, R5_

---

## Phase 2: Core Service

- [x] 2.1 Create notification package structure
  - File: src/services/notification/__init__.py
  - Create package directory and __init__.py with exports
  - Purpose: Establish module structure for notification deduplication
  - _Leverage: src/services/ (existing package patterns)_
  - _Requirements: R1_

- [x] 2.2 Implement NotificationDeduplicator service
  - File: src/services/notification/deduplicator.py
  - Create NotificationDeduplicator class with RegistryService dependency
  - Implement categorize_papers() method that:
    - Queries RegistryService.resolve_identity() for each paper
    - Categorizes based on entry status (PROCESSED/MAPPED → duplicate, FAILED/SKIPPED → retry, not found → new)
  - Add graceful fallback when registry unavailable
  - Purpose: Core deduplication logic for notification categorization
  - _Leverage: src/services/registry_service.py (RegistryService, resolve_identity), src/models/registry.py (ProcessingAction)_
  - _Requirements: R1, R3_

---

## Phase 3: Message Builder Enhancement

- [x] 3.1 Add dedup stats section to SlackMessageBuilder
  - File: src/services/notification_service.py (extend existing)
  - Add _build_dedup_stats_section() method for new/retry/duplicate counts
  - Update _build_stats_section() to include deduplication info when available
  - Purpose: Display deduplication statistics in Slack messages
  - _Leverage: src/services/notification_service.py (SlackMessageBuilder)_
  - _Requirements: R1, R4_

- [x] 3.2 Add new papers section to SlackMessageBuilder
  - File: src/services/notification_service.py (extend existing)
  - Add _build_new_papers_section() method to list new paper titles
  - Respect max_new_papers_listed config option
  - Purpose: Highlight truly new papers in notifications
  - _Leverage: src/services/notification_service.py (SlackMessageBuilder)_
  - _Requirements: R2, R4_

- [x] 3.3 Add retry papers section to SlackMessageBuilder
  - File: src/services/notification_service.py (extend existing)
  - Add _build_retry_papers_section() method for papers being retried
  - Respect show_retry_papers config option
  - Purpose: Show papers that previously failed and are being retried
  - _Leverage: src/services/notification_service.py (SlackMessageBuilder)_
  - _Requirements: R2, R4_

- [x] 3.4 Update build_pipeline_summary to use new sections
  - File: src/services/notification_service.py (extend existing)
  - Integrate new sections into build_pipeline_summary() flow
  - Respect all config toggles (show_duplicates_count, show_retry_papers, etc.)
  - Purpose: Complete message builder with all new sections
  - _Leverage: src/services/notification_service.py (build_pipeline_summary)_
  - _Requirements: R1, R2, R4_

---

## Phase 4: Integration

- [x] 4.1 Update create_summary_from_result with deduplication
  - File: src/services/notification_service.py (extend existing)
  - Modify create_summary_from_result() to accept DeduplicationResult
  - Populate new PipelineSummary fields from DeduplicationResult
  - Maintain backward compatibility (optional parameter with default)
  - Purpose: Connect deduplication results to notification pipeline
  - _Leverage: src/services/notification_service.py (create_summary_from_result)_
  - _Requirements: R1, R5_

---

## Phase 5: Testing

- [x] 5.1 Unit tests for DeduplicationResult model
  - File: tests/unit/test_models/test_notification.py (extend existing)
  - Test model creation, computed properties, edge cases
  - Test empty lists, mixed lists, large lists
  - Purpose: Ensure model reliability
  - _Leverage: tests/unit/test_models/test_notification.py_
  - _Requirements: R1_

- [x] 5.2 Unit tests for extended PipelineSummary
  - File: tests/unit/test_models/test_notification.py (extend existing)
  - Test new fields, default values, backward compatibility
  - Purpose: Ensure extended model works correctly
  - _Leverage: tests/unit/test_models/test_notification.py_
  - _Requirements: R1, R5_

- [x] 5.3 Unit tests for extended SlackConfig
  - File: tests/unit/test_models/test_notification.py (extend existing)
  - Test new config options, validation, defaults
  - Purpose: Ensure config options work correctly
  - _Leverage: tests/unit/test_models/test_notification.py_
  - _Requirements: R4_

- [x] 5.4 Unit tests for NotificationDeduplicator
  - File: tests/unit/test_services/test_notification_deduplicator.py (new)
  - Test categorize_papers() with:
    - All new papers (empty registry)
    - All duplicates (all PROCESSED status)
    - All retry (all FAILED/SKIPPED status)
    - Mixed scenarios
    - Registry unavailable (graceful fallback)
  - Purpose: Ensure deduplication logic is correct
  - _Leverage: src/services/notification/deduplicator.py, tests/conftest.py_
  - _Requirements: R1, R3_

- [x] 5.5 Unit tests for enhanced SlackMessageBuilder
  - File: tests/unit/test_services/test_notification_service.py (extend existing)
  - Test new section methods
  - Test config toggles are respected
  - Test message format with all combinations
  - Purpose: Ensure message builder produces correct output
  - _Leverage: tests/unit/test_services/test_notification_service.py_
  - _Requirements: R2, R4_

- [-] 5.6 Integration tests for notification deduplication
  - File: tests/integration/test_notification_integration.py (new or extend)
  - Test full flow: papers → deduplication → summary → message
  - Test backward compatibility with existing configs
  - Test first run scenario (empty registry)
  - Purpose: Ensure end-to-end functionality
  - _Leverage: tests/integration/, src/services/registry_service.py_
  - _Requirements: All_
  - **Note:** Unit tests provide comprehensive coverage; integration tests deferred to later phase

---

## Phase 6: Verification

- [x] 6.1 Run full verification suite
  - Run ./verify.sh to ensure all checks pass
  - Verify ≥99% coverage for all new/modified modules
  - Ensure no regressions in existing functionality
  - Purpose: Quality gate before completion
  - _Requirements: All_
  - **Result:** All checks passed - 1905 tests, 99.35% coverage

- [x] 6.2 Manual verification of Slack message format
  - Create test notification with sample data
  - Verify Block Kit formatting is correct
  - Check all config options work as expected
  - Purpose: Visual verification of output
  - _Requirements: R2_
