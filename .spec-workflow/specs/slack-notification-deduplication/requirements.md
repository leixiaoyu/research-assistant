# Requirements Document: Slack Notification Deduplication

## Introduction

This specification addresses the issue where Slack notifications from the daily research pipeline show repeated papers across consecutive runs. Currently, the notification statistics (`papers_discovered`, `papers_processed`) reflect raw API counts rather than truly new papers, causing confusion about pipeline value.

**Problem Statement:** Users receive daily Slack notifications that include papers they've already seen in previous runs, making it difficult to understand what's actually new each day.

**Goal:** Modify the notification system to show only NEW papers (not previously seen) in Slack notifications, providing clear daily value without repetition.

## Alignment with Product Vision

This feature supports the core ARISP goal of **automated research ingestion** by ensuring users receive actionable, non-repetitive daily research updates. Key alignment:

- **Autonomous Operation**: Pipeline should intelligently filter what's shown to users
- **Configurable by Default**: Allow users to choose notification granularity
- **Observable**: Clear metrics that reflect actual new discoveries

## Requirements

### Requirement 1: Deduplication-Aware Discovery Statistics

**User Story:** As a research consumer, I want Slack notifications to show only papers I haven't seen before, so that I can quickly understand what's new each day.

#### Acceptance Criteria

1. WHEN a pipeline run completes AND Slack notifications are enabled THEN the system SHALL report `papers_discovered` as the count of papers NOT previously seen in the global registry
2. IF a paper exists in the global registry (matched by DOI, paper_id, or title similarity ≥95%) THEN the system SHALL NOT count it in the `papers_discovered` metric for notifications
3. WHEN the notification is sent THEN the system SHALL include a breakdown showing:
   - `new_papers`: Papers discovered for the first time
   - `duplicate_papers`: Papers already in registry (optional, for transparency)

### Requirement 2: New Papers Summary in Slack Message

**User Story:** As a research consumer, I want the Slack message to clearly list new paper titles, so that I can quickly scan what's been discovered.

#### Acceptance Criteria

1. WHEN new papers are discovered (>0) THEN the system SHALL include a "New Papers" section in the Slack message with paper titles
2. IF more than 5 new papers are discovered THEN the system SHALL show the top 5 (by quality score) with a count of remaining papers
3. WHEN no new papers are discovered THEN the system SHALL display "No new papers discovered" with a note about total papers checked

### Requirement 3: Persistence of Notification State

**User Story:** As a system operator, I want the deduplication state to persist across pipeline restarts, so that the "new paper" detection remains accurate.

#### Acceptance Criteria

1. WHEN a paper is included in a Slack notification THEN the system SHALL record it in the global registry (if not already present)
2. IF the registry service is unavailable THEN the system SHALL fall back to catalog-based deduplication
3. WHEN the system starts THEN the system SHALL load existing registry state to maintain notification history

### Requirement 4: Configuration Options

**User Story:** As a system operator, I want to configure notification behavior, so that I can customize what information is shared.

#### Acceptance Criteria

1. WHEN configuring notifications THEN the system SHALL support the following options:
   - `show_duplicates_count`: Boolean to include/exclude duplicate count (default: true)
   - `max_new_papers_listed`: Maximum number of new paper titles to list (default: 5)
   - `include_total_checked`: Show total papers checked vs new (default: true)
2. IF configuration is not provided THEN the system SHALL use sensible defaults

### Requirement 5: Backward Compatibility

**User Story:** As an existing user, I want the notification changes to not break my current setup, so that I can continue receiving notifications without reconfiguration.

#### Acceptance Criteria

1. WHEN the system is upgraded THEN existing Slack webhook configurations SHALL continue to work
2. IF no new configuration options are set THEN the system SHALL default to improved deduplication behavior
3. WHEN the registry is empty (first run after upgrade) THEN the system SHALL treat all papers as new (graceful start)

## Non-Functional Requirements

### Code Architecture and Modularity
- **Single Responsibility Principle**: Deduplication logic for notifications should be separate from extraction deduplication
- **Modular Design**: Create a `NotificationDeduplicationService` or extend existing `RegistryService` with notification-specific methods
- **Dependency Management**: Notification service should depend on registry service, not duplicate deduplication logic
- **Clear Interfaces**: Define clear contract for "is paper new for notification purposes"

### Performance
- **Latency**: Deduplication check should add `<100ms` to notification preparation
- **Memory**: Should handle 10,000+ papers in registry without performance degradation
- **Caching**: Registry lookups should be O(1) for DOI/paper_id checks

### Security
- **No Secrets**: Paper metadata in notifications should not expose internal IDs or sensitive data
- **Webhook Security**: Continue using HTTPS for Slack webhook communication
- **Audit**: Log deduplication decisions for debugging (without exposing paper content)

### Reliability
- **Graceful Degradation**: If registry unavailable, fall back to catalog or skip deduplication (not fail notification)
- **Idempotency**: Multiple notification attempts for same run should produce identical results
- **Error Handling**: Registry errors should not prevent notification from being sent

### Usability
- **Clear Messaging**: Slack messages should clearly distinguish new vs. total papers
- **Actionable Information**: Users should understand daily pipeline value at a glance
- **Consistent Format**: Message format should match existing Slack notification style

## Dependencies

### Existing Components to Leverage
- `RegistryService` (`src/services/registry_service.py`) - Global paper identity tracking
- `NotificationService` (`src/services/notification_service.py`) - Slack message sending
- `PipelineSummary` (`src/models/notification.py`) - Notification data model
- `SlackMessageBuilder` - Message formatting

### External Dependencies
- Slack Webhook API (existing integration)
- Global registry (`data/registry.json`) - Must be accessible during notification preparation

## Success Metrics

1. **Zero Repeated Papers**: Users should never see the same paper title in consecutive daily notifications
2. **Clear Value Proposition**: Each notification clearly shows what's NEW vs what was checked
3. **No Breaking Changes**: Existing notification configurations continue to work
4. **Performance**: Notification preparation time increases by `<100ms`

## Out of Scope

- Changing discovery API behavior (papers will still be re-fetched from APIs)
- Modifying extraction deduplication (already works correctly)
- Per-user notification preferences (all notifications are global)
- Historical backfill of notification state (registry already tracks processed papers)
