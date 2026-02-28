# Phase 5.2: ResearchPipeline Phase Extraction
**Version:** 1.1
**Status:** ✅ Complete
**Timeline:** 3-4 days (Completed Feb 25, 2026)
**Dependencies:**
- Phase 5.1 Complete (LLMService Decomposition)
- All existing pipeline tests passing

---

## Architecture Reference

This phase refactors the orchestration layer as defined in [SYSTEM_ARCHITECTURE.md §3 Orchestration Layer](../SYSTEM_ARCHITECTURE.md#orchestration-layer).

**Architectural Gaps Addressed:**
- ❌ Gap: Single 824-line orchestrator handles all pipeline phases
- ❌ Gap: 12+ service dependencies initialized in one class
- ❌ Gap: Phase logic interleaved with service management
- ❌ Gap: Difficult to test individual phases in isolation

**Components Modified:**
- Orchestration: ResearchPipeline (src/orchestration/research_pipeline.py)
- New: Phase-specific orchestrators

**Coverage Targets:**
- All new phase modules: ≥99%
- Overall coverage: Maintain ≥99%

---

## 1. Executive Summary

Phase 5.2 decomposes the monolithic `ResearchPipeline` (824 lines, 14 functions) into a clean orchestration architecture with dedicated phase handlers. Each pipeline phase (Discovery, Extraction, Synthesis, Cross-Synthesis) becomes an independent, testable module coordinated by a slim main orchestrator.

**What This Phase Is:**
- ✅ Extraction of phase-specific logic into dedicated modules.
- ✅ Creation of shared pipeline context for state management.
- ✅ Clear separation between service initialization and phase execution.
- ✅ Maintained backward compatibility with CLI and scheduler.

**What This Phase Is NOT:**
- ❌ Adding new pipeline phases.
- ❌ Changing execution order or phase dependencies.
- ❌ Modifying service initialization logic.
- ❌ Altering concurrent processing behavior.

**Key Achievement:** Transform 824-line orchestrator into 5-6 focused modules, each <200 lines.

---

## 2. Problem Statement

### 2.1 The Monolithic Orchestrator
`ResearchPipeline` currently manages:
1. Configuration loading
2. Service initialization (12+ services)
3. Phase 1: Discovery orchestration
4. Phase 2: Extraction orchestration
5. Phase 3.6: Per-topic synthesis
6. Phase 3.7: Cross-topic synthesis
7. Result aggregation
8. Error handling and recovery
9. Progress tracking

### 2.2 The Service Sprawl
The `__init__` method initializes 12+ optional services, leading to complex conditional logic and difficult dependency management.

### 2.3 The Testing Challenge
Testing a single phase requires initializing the entire pipeline with all its dependencies.

---

## 3. Requirements

### 3.1 Phase Extraction

#### REQ-5.2.1: Discovery Phase Module
Discovery logic SHALL be extracted to `DiscoveryPhase` class.

**Responsibilities:**
- Execute paper discovery for topics
- Apply deduplication
- Apply quality filtering
- Return discovered papers with metadata

#### REQ-5.2.2: Extraction Phase Module
Extraction logic SHALL be extracted to `ExtractionPhase` class.

**Responsibilities:**
- Coordinate PDF download and conversion
- Execute LLM extraction
- Handle extraction failures gracefully
- Return extraction results

#### REQ-5.2.3: Synthesis Phase Module
Per-topic synthesis SHALL be extracted to `SynthesisPhase` class.

**Responsibilities:**
- Generate Knowledge Base documents
- Generate Delta Briefs
- Update topic registries

#### REQ-5.2.4: Cross-Synthesis Phase Module
Cross-topic synthesis SHALL be extracted to `CrossSynthesisPhase` class.

**Responsibilities:**
- Execute cross-topic synthesis questions
- Generate Global_Synthesis.md
- Aggregate insights across topics

### 3.2 Pipeline Context

#### REQ-5.2.5: Shared Pipeline Context
A `PipelineContext` class SHALL manage shared state across phases.

**Contents:**
- Configuration (ResearchConfig)
- Service references
- Current run metadata (run_id, timestamps)
- Accumulated results
- Error collection

#### REQ-5.2.6: Result Aggregation
`PipelineResult` SHALL be extracted to its own module.

### 3.3 Backward Compatibility

#### REQ-5.2.7: API Preservation
The refactored `ResearchPipeline` SHALL maintain its existing public API.

```python
# This MUST continue to work:
pipeline = ResearchPipeline(
    config_path=Path("config/research.yaml"),
    enable_phase2=True,
    enable_synthesis=True,
)
result = await pipeline.run()
```

### 3.4 Package Structure

#### REQ-5.2.8: Module Organization

```
src/orchestration/
├── __init__.py           # Re-export ResearchPipeline
├── pipeline.py           # Main ResearchPipeline (<200 lines)
├── context.py            # PipelineContext class
├── result.py             # PipelineResult class
├── phases/
│   ├── __init__.py
│   ├── base.py           # Abstract PipelinePhase
│   ├── discovery.py      # DiscoveryPhase
│   ├── extraction.py     # ExtractionPhase
│   ├── synthesis.py      # SynthesisPhase
│   └── cross_synthesis.py # CrossSynthesisPhase
└── concurrent_pipeline.py # Unchanged (already separate)
```

---

## 4. Technical Design

### 4.1 Abstract Phase Interface

```python
# src/orchestration/phases/base.py
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar('T')

class PipelinePhase(ABC, Generic[T]):
    """Abstract base class for pipeline phases."""

    def __init__(self, context: PipelineContext):
        self.context = context
        self.logger = structlog.get_logger().bind(phase=self.name)

    @property
    @abstractmethod
    def name(self) -> str:
        """Phase name for logging."""
        pass

    @abstractmethod
    async def execute(self) -> T:
        """Execute the phase and return results."""
        pass

    def is_enabled(self) -> bool:
        """Check if phase should run based on config."""
        return True
```

### 4.2 Pipeline Context

```python
# src/orchestration/context.py
@dataclass
class PipelineContext:
    """Shared context for pipeline phases."""

    # Configuration
    config: ResearchConfig
    run_id: str
    started_at: datetime

    # Feature flags
    enable_phase2: bool = True
    enable_synthesis: bool = True
    enable_cross_synthesis: bool = True

    # Services (lazy-initialized)
    _services: Dict[str, Any] = field(default_factory=dict)

    # Accumulated state (Note: Use explicit methods for state transitions)
    discovered_papers: Dict[str, List[PaperMetadata]] = field(default_factory=dict)
    extraction_results: Dict[str, List[ExtractedPaper]] = field(default_factory=dict)
    synthesis_results: Dict[str, ProcessingResult] = field(default_factory=dict)

    # Error tracking
    errors: List[Dict[str, str]] = field(default_factory=list)

    # State modification methods (thread-safe for future concurrent phases)
    def add_discovered_papers(self, topic: str, papers: List[PaperMetadata]) -> None:
        """Add discovered papers for a topic (explicit state transition)."""
        self.discovered_papers[topic] = papers

    def add_extraction_result(self, topic: str, results: List[ExtractedPaper]) -> None:
        """Add extraction results for a topic (explicit state transition)."""
        self.extraction_results[topic] = results

    def add_error(self, phase: str, error: str) -> None:
        """Record an error (thread-safe append)."""
        self.errors.append({"phase": phase, "error": error})

    def get_service(self, name: str) -> Any:
        """Get service by name, initializing if needed."""
        if name not in self._services:
            self._services[name] = self._initialize_service(name)
        return self._services[name]
```

### 4.3 Refactored ResearchPipeline

```python
# src/orchestration/pipeline.py
class ResearchPipeline:
    """Orchestrates the complete research pipeline.

    Coordinates phase execution while delegating logic to phase modules.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        enable_phase2: bool = True,
        enable_synthesis: bool = True,
        enable_cross_synthesis: bool = True,
    ):
        self.config_path = config_path or Path("config/research_config.yaml")
        self.enable_phase2 = enable_phase2
        self.enable_synthesis = enable_synthesis
        self.enable_cross_synthesis = enable_cross_synthesis

    async def run(self) -> PipelineResult:
        """Execute the complete research pipeline."""
        # Initialize context
        context = await self._create_context()
        result = PipelineResult()

        try:
            # Phase 1: Discovery
            discovery = DiscoveryPhase(context)
            await discovery.execute()

            # Phase 2: Extraction (if enabled)
            if self.enable_phase2:
                extraction = ExtractionPhase(context)
                await extraction.execute()

            # Phase 3.6: Per-topic Synthesis (if enabled)
            if self.enable_synthesis:
                synthesis = SynthesisPhase(context)
                await synthesis.execute()

            # Phase 3.7: Cross-topic Synthesis (if enabled)
            if self.enable_cross_synthesis:
                cross_synthesis = CrossSynthesisPhase(context)
                await cross_synthesis.execute()

            # Aggregate results
            result = self._aggregate_results(context)

        except Exception as e:
            self.logger.exception("pipeline_failed")
            result.errors.append({"phase": "unknown", "error": str(e)})

        return result
```

---

## 5. Security Requirements (MANDATORY) 🔒

### SR-5.2.1: Context Security
- [ ] PipelineContext does not store API keys.
- [ ] Service references do not expose credentials.
- [ ] Context serialization excludes sensitive data.

### SR-5.2.2: Phase Isolation
- [ ] Phase failures do not leak data to other phases.
- [ ] Error messages do not expose internal state.
- [ ] Each phase validates its inputs independently.

### SR-5.2.3: Result Security
- [ ] PipelineResult does not contain raw credentials.
- [ ] Error details sanitized before logging.
- [ ] Output paths validated with PathSanitizer.

---

## 6. Implementation Tasks

### Task 1: Create Package Structure (0.5 day)
**Files:** src/orchestration/phases/__init__.py, etc.

1. Create directory structure.
2. Move `PipelineResult` to `result.py`.
3. Create `PipelineContext` in `context.py`.

### Task 2: Extract Discovery Phase (1 day)
**Files:** src/orchestration/phases/discovery.py

1. Extract topic discovery loop.
2. Extract deduplication integration.
3. Extract quality filtering integration.
4. Add comprehensive tests.

### Task 3: Extract Extraction Phase (1 day)
**Files:** src/orchestration/phases/extraction.py

1. Extract extraction orchestration logic.
2. Handle concurrent pipeline integration.
3. Extract result aggregation.
4. Add comprehensive tests.

### Task 4: Extract Synthesis Phases (1 day)
**Files:** src/orchestration/phases/synthesis.py, cross_synthesis.py

1. Extract per-topic synthesis logic.
2. Extract cross-topic synthesis logic.
3. Add comprehensive tests.

### Task 5: Refactor Main Pipeline (0.5 day)
**Files:** src/orchestration/pipeline.py

1. Refactor to use phase classes.
2. Implement context passing.
3. Verify backward compatibility.

### Task 6: Update Integration Points (0.5 day)
**Files:** src/cli.py, src/scheduling/jobs.py

1. Verify CLI integration works.
2. Verify scheduler integration works.
3. Add deprecation warnings if needed.

### Task 7: Update ConcurrentPipeline Integration (0.5 day)
**Files:** src/orchestration/concurrent_pipeline.py

1. Update ConcurrentPipeline to use new phase classes.
2. Ensure worker pools integrate with phase execution.
3. Verify concurrent processing behavior unchanged.
4. Add integration tests for concurrent + phase class interaction.

---

## 7. Verification Criteria

### 7.1 Unit Tests (New)
- `test_discovery_phase_executes`: Discovery phase finds papers.
- `test_extraction_phase_executes`: Extraction phase processes papers.
- `test_synthesis_phase_executes`: Synthesis generates KB.
- `test_cross_synthesis_phase_executes`: Cross-synthesis generates report.
- `test_pipeline_context_services`: Context lazy-loads services.
- `test_phase_error_isolation`: Phase error doesn't crash pipeline.

### 7.2 Regression Tests
- All 1,468 existing tests MUST pass.
- Coverage MUST remain ≥99%.

### 7.3 Integration Tests
- `test_full_pipeline_backward_compat`: CLI `run` command works.
- `test_scheduler_backward_compat`: DailyResearchJob works.
- `test_partial_phases`: --no-synthesis flag works.

---

## 8. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking pipeline flow | High | Low | Comprehensive integration tests |
| Service initialization order | Medium | Medium | Lazy initialization in context |
| Phase dependency errors | Medium | Low | Clear phase contracts |
| State leakage | Low | Low | Immutable context pattern |

---

## 9. Rollback Plan

If critical issues are discovered post-merge:

1. **Immediate Rollback:** Revert the PR entirely (single commit revert).
2. **Original Preserved:** `research_pipeline.py` is preserved in git history.
3. **No Data Migration:** Purely code structure change, no data format changes.
4. **State Validation:** Run state validation tests to verify pipeline output integrity.

### State Validation Strategy

Before merge, create snapshot tests that capture:
- Pipeline output structure for a reference run
- Synthesis file contents (hash comparison)
- Registry state after processing

```python
def test_pipeline_output_equivalence():
    """Verify refactored pipeline produces identical output."""
    # Run with original implementation
    original_result = run_original_pipeline(test_config)
    original_hash = hash_output_files(original_result.output_files)

    # Run with refactored implementation
    refactored_result = run_refactored_pipeline(test_config)
    refactored_hash = hash_output_files(refactored_result.output_files)

    # Verify byte-for-byte equivalence
    assert original_hash == refactored_hash
    assert original_result.papers_processed == refactored_result.papers_processed
```

---

## 10. File Size Targets

| File | Current | Target |
|------|---------|--------|
| research_pipeline.py | 824 lines | <200 lines |
| phases/discovery.py | N/A | <150 lines |
| phases/extraction.py | N/A | <180 lines |
| phases/synthesis.py | N/A | <150 lines |
| phases/cross_synthesis.py | N/A | <150 lines |
| context.py | N/A | <100 lines |
| result.py | N/A | <80 lines |
