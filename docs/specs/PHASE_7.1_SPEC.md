# Requirements Document: Phase 7.1 - Discovery Foundation

## Introduction

Phase 7.1 addresses the core issue of the daily research pipeline returning the same papers repeatedly without discovering new content. This milestone implements foundational improvements to paper discovery:

1. **Pre-filtering at discovery time** - Filter discovered papers against the registry before returning results
2. **Incremental timeframes** - Query papers published since the last successful run instead of sliding windows
3. **Discovery-time registration** - Register papers in the registry at discovery (not just extraction)

These quick wins provide immediate value by ensuring the daily run surfaces only genuinely new papers while maintaining backward compatibility with existing pipeline architecture.

## Alignment with Product Vision

This feature directly supports ARISP's mission to automate the discovery of cutting-edge AI research:

- **Reduces noise**: Eliminates duplicate papers from daily notifications
- **Improves efficiency**: Saves LLM extraction costs by not re-processing seen papers
- **Enables research progression**: Creates foundation for deeper discovery features in Phase 7.2+
- **Maintains data integrity**: Leverages existing `RegistryService` for persistent cross-run deduplication

## Requirements

### Requirement 1: Pre-Filter Papers Against Registry at Discovery Time

**User Story:** As a researcher using the daily pipeline, I want discovered papers to be filtered against previously seen papers, so that I only receive notifications about genuinely new research.

#### Acceptance Criteria

1. WHEN `DiscoveryPhase._discover_topic()` returns papers THEN the system SHALL filter out papers already registered in `RegistryService`
2. IF a paper's DOI matches an existing registry entry THEN the system SHALL exclude it from discovery results
3. IF a paper's ArXiv ID matches an existing registry entry THEN the system SHALL exclude it from discovery results
4. IF a paper's normalized title matches an existing registry entry with ≥95% similarity THEN the system SHALL exclude it from discovery results
5. WHEN filtering is complete THEN the system SHALL log the count of papers filtered vs. new papers discovered
6. IF `config.settings.skip_registry_filter` is True THEN the system SHALL return all papers without filtering (for debugging)

### Requirement 2: Incremental Timeframe Queries

**User Story:** As a researcher, I want the pipeline to query papers published since my last successful run for a topic, so that I don't miss papers and don't receive duplicates from overlapping time windows.

#### Acceptance Criteria

1. WHEN a topic has been successfully processed before THEN the system SHALL query papers published after `last_successful_discovery_at` timestamp
2. IF a topic has never been processed THEN the system SHALL use the configured `timeframe` from `research_config.yaml`
3. WHEN calculating the incremental query window THEN the system SHALL add a 1-hour overlap buffer to prevent edge-case misses
4. IF `topic.force_full_timeframe` is True THEN the system SHALL ignore last run timestamp and use configured timeframe
5. WHEN a discovery run succeeds THEN the system SHALL update `last_successful_discovery_at` for that topic in the registry/catalog
6. IF a discovery run fails THEN the system SHALL NOT update the timestamp (next run retries from same point)

### Requirement 3: Discovery-Time Paper Registration

**User Story:** As a system operator, I want papers to be registered in the registry at discovery time, so that cross-run deduplication works even for papers filtered out before extraction.

#### Acceptance Criteria

1. WHEN a paper is discovered (new, not filtered) THEN the system SHALL register it in `RegistryService` with `discovery_only=True`
2. WHEN registering at discovery time THEN the system SHALL store: DOI, ArXiv ID, provider ID, normalized title, topic affiliation, discovered_at timestamp
3. IF a paper is later processed in extraction phase THEN the system SHALL update the existing registry entry (not create duplicate)
4. WHEN `discovery_only=True` THEN the system SHALL NOT require pdf_path or markdown_path fields
5. IF paper registration fails THEN the system SHALL log the error and continue processing (non-blocking)
6. WHEN the pipeline completes THEN the system SHALL persist registry state to disk atomically

### Requirement 4: Discovery Statistics and Observability

**User Story:** As a system operator, I want detailed statistics about paper discovery and filtering, so that I can monitor pipeline health and optimize discovery settings.

#### Acceptance Criteria

1. WHEN discovery phase completes THEN the system SHALL log: total_discovered, new_papers, filtered_as_duplicate, filter_method_breakdown (doi/arxiv/title)
2. WHEN daily run completes THEN the system SHALL include discovery stats in Slack notification
3. IF `config.settings.verbose_discovery_logging` is True THEN the system SHALL log each filtered paper with filter reason
4. WHEN discovery stats are generated THEN the system SHALL store them in `PipelineResult` for downstream access
5. IF a topic discovers 0 new papers after filtering THEN the system SHALL log a warning (may indicate stale query)

### Requirement 5: Topic Discovery State Persistence

**User Story:** As a researcher, I want the pipeline to remember when each topic was last successfully processed, so that incremental queries work correctly across restarts and updates.

#### Acceptance Criteria

1. WHEN saving topic discovery state THEN the system SHALL persist to catalog.json with per-topic timestamps
2. WHEN loading topic discovery state THEN the system SHALL read from catalog.json at pipeline startup
3. IF catalog.json is corrupted or missing THEN the system SHALL create a new catalog and log a warning
4. WHEN a topic query changes in config THEN the system SHALL detect the change and reset that topic's timestamp
5. IF multiple topics map to the same topic_slug THEN the system SHALL share discovery state (deduplication)
6. WHEN the system detects a config change THEN the system SHALL log which topics were reset

## Non-Functional Requirements

### Code Architecture and Modularity

- **Single Responsibility Principle**: Discovery filtering logic in separate `DiscoveryFilter` class
- **Modular Design**: Incremental timeframe calculation in `TimeframeResolver` utility
- **Dependency Management**: `DiscoveryPhase` depends on `RegistryService` via context (already available)
- **Clear Interfaces**: New methods added to existing services, no new service classes required
- **Backward Compatibility**: All new features opt-in via config flags, existing behavior preserved by default

### Performance

- Registry file I/O must use atomic writes to prevent corruption
- Memory usage must not increase significantly (lazy loading of registry entries)
- Note: Discovery latency is not a priority metric for this phase

### Security

- No new API keys or credentials required
- Registry file permissions remain 0600 (owner-only)
- No user data exposed in logs beyond paper titles/IDs

### Reliability

- Registry corruption must be recoverable via backup restore
- Failed discovery runs must not corrupt topic state
- All file operations must be atomic (write-rename pattern)
- Network failures during discovery must not affect registry state

### Usability

- Clear log messages explaining why papers were filtered
- Config flags well-documented in research_config.yaml schema
- Slack notifications include new vs. filtered counts
- CLI commands to inspect registry state (`python -m src.cli registry stats`)

## Dependencies

- **Phase 3.5 (Complete)**: `RegistryService` provides identity resolution infrastructure
- **Phase 3.7 (Complete)**: Notification system for enhanced stats reporting
- **catalog.json**: Extended to store per-topic discovery timestamps

## Out of Scope (Deferred to Phase 7.2+)

- Multi-source paper discovery (OpenAlex, additional MCPs)
- Citation network exploration
- Human feedback integration
- Query expansion and semantic search

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Duplicate papers in daily run | Less than 5% of discovered | `filtered_count / total_discovered` |
| New paper discovery rate | At least 20% new papers per run | `new_papers / total_discovered` |
| Registry accuracy | 99%+ correct identity resolution | Manual audit of matches |
| Incremental coverage | 100% of papers since last run captured | Cross-reference with direct API query |
| Test coverage | ≥99% | pytest --cov |
