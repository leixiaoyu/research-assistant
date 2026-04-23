# Open Questions - Implementation Plans

This file tracks unresolved questions, decisions deferred to the user, and items needing clarification.

---

## Phase 8: Deep Research Agent - 2026-04-04

### Architecture Decisions

- [ ] **GPU acceleration strategy** - Should we support optional GPU acceleration for SPECTER2 embeddings? The spec mentions "GPU acceleration optional" but doesn't specify how to detect/configure this. This affects installation complexity and performance.

- [ ] **Torch variant selection** - Should we use `torch` (full) or `torch-cpu` (smaller)? Full torch is ~2GB but supports GPU; torch-cpu is smaller but CPU-only. Trade-off between install size and future GPU support.

- [ ] **Corpus storage location** - Spec suggests `./data/dra/corpus` but should this be configurable at install time? Large corpora could exceed disk space in default location.

### Scope Clarifications

- [ ] **Minimum corpus size for meaningful retrieval** - Spec mentions risk "Corpus too small for meaningful retrieval" with mitigation "Supplement with OpenResearcher's FineWeb subset." Should we implement FineWeb integration or document as future enhancement?

- [ ] **SFT export format** - Spec mentions "SFT export is optional" but the trajectory export uses ShareGPT format. Is ShareGPT sufficient or should we also support other formats (Alpaca, ChatML)?

- [ ] **Multi-user support** - Spec explicitly says "NOT multi-user collaborative research platform" but should trajectory storage be per-user or global? Affects privacy and learning isolation.

### Integration Points

- [ ] **Registry service markdown format** - The corpus manager ingests from registry. Need to verify the exact format of `markdown_path` content from `RegistryEntry`. Does it include YAML frontmatter? Section headers?

- [ ] **LLM provider selection for agent** - Should agent use the same provider as extraction pipeline or have independent config? Current spec suggests independent `dra_settings.agent.llm_provider`.

### Quality Thresholds

- [ ] **"Measurable performance improvement" definition** - Phase 8.3 success criteria says "Measurable performance improvement after 10+ trajectories." How do we measure this? Specific metrics needed (e.g., turns to answer, answer quality score).

- [ ] **"70%+ test questions answered" baseline** - Phase 8.2 success criteria mentions 70%+ of test questions. What constitutes "answered"? Need to define test question set and evaluation criteria.

### Security Considerations

- [ ] **Embedding model download security** - SPECTER2 downloads from HuggingFace Hub. Should we verify model checksums? Cache in specific location? Air-gapped environment support?

- [ ] **Trajectory data retention policy** - How long should trajectories be retained? Should there be an auto-purge mechanism? GDPR considerations if user questions contain PII?

---

## Phase 8.2 Completion - 2026-04-17

### CLI Design Decisions

- [ ] **Progress display library** - Should CLI use `rich` for progress spinners or stick with `typer.progressbar`? Rich offers better UX but adds dependency. Current codebase doesn't use rich.

- [ ] **Batch output format** - For `--question-file` batch mode, should results be written to individual files per question or consolidated into single report? Affects downstream processing.

- [ ] **Interactive vs non-interactive mode** - Should there be an `--interactive` flag for step-by-step execution where user can see each turn? Useful for debugging but adds complexity.

### System Prompt Design

- [ ] **Prompt versioning** - Should system prompts be versioned for reproducibility? Trajectories would need to record which prompt version was used.

- [ ] **Tip injection limit** - How many tips should be injected maximum? Too many tips could overwhelm context. Suggest limit of 5 tips.

### Integration Test Scope

- [ ] **Real embedding tests** - Should integration tests include at least one test with real SPECTER2 embeddings (slow but validates full stack)? Or keep all integration tests mocked for speed?

- [ ] **Test question corpus** - Need to define the "test questions" mentioned in success criteria. Should create `tests/fixtures/dra_test_questions.json` with 20+ diverse questions.

---

---

## Phase 9: Research Intelligence Layer - 2026-04-22

### Architecture Decisions

- [ ] **Neo4j migration trigger threshold** - Spec says "migrate when >100K nodes" but should we start monitoring node count proactively? Consider adding metrics/alerting when approaching threshold (e.g., 75K nodes warning).

- [ ] **Multi-user field indexing** - `user_id: str = Field(default="default")` is in spec for future multi-user support. Should we index this field now in SQLite schema, or defer until multi-user is actually implemented? Indexing now has minimal cost but ensures migration-free scaling.

- [ ] **GraphStore backend configuration** - Spec shows config in `research_config.yaml` but current config structure doesn't have `intelligence` section. Should we add it now or use environment variables for storage backend selection?

### Scope Clarifications

- [x] **Digest delivery mechanism** - ✅ DECIDED (2026-04-22): File-based MVP (`./output/digests/`) confirmed. Optional notification service hook for post-MVP.

- [x] **Monitoring schedule persistence** - ✅ DECIDED (2026-04-22, REVISED 2026-04-23): Integrate with existing APScheduler infrastructure in `src/scheduling/`. Implement `MonitoringCheckJob(BaseJob)` subclass following the pattern of `DRACorpusRefreshJob`. This maintains architectural consistency with existing scheduled jobs (DailyResearchJob, CacheCleanupJob, etc.) and avoids fragmenting deployment/monitoring across external cron and internal scheduler.

- [ ] **ArXiv-only MVP scope** - Spec explicitly notes "MVP Scope: Only ARXIV has RSS/Atom feeds." Other sources (S2, HuggingFace, OpenAlex) require polling. Confirm ArXiv-only for initial 9.1 release.

### Integration Points

- [ ] **DRA Browser primitive naming** - New primitives are `cite_expand()`, `knowledge_query()`, `frontier_status()`. Should these match existing browser method naming conventions? Current browser uses `search()`, `retrieve()`, `summarize()`.

- [x] **Monitoring -> Corpus auto-ingest threshold** - ✅ DECIDED (2026-04-22): Lower threshold to relevance >= 0.7 for auto-ingest. This allows more papers to flow into the learning synthesis process while still filtering low-relevance content.

### Security Considerations

- [ ] **Entity extraction content sanitization** - REQ SR-9.3 requires sanitizing extracted entities. Define allowed character patterns for entity names. Recommend: alphanumeric, spaces, hyphens, periods, parentheses only. Reject scripts, HTML, control characters.

- [ ] **Subscription limits enforcement** - SR-9.5 specifies max 50 subscriptions, 100 keywords, 1000 papers/cycle. Should violations raise exceptions or silently truncate? Recommend raising `SubscriptionLimitError` with clear message.

---

*Last updated: 2026-04-23 (3 Phase 9 decisions resolved, 1 revised per team review)*
