# Phase 5.5: Model Consolidation
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 3-4 days
**Dependencies:**
- Phase 5.1 Complete (LLMService Decomposition)
- Phase 5.2 Complete (ResearchPipeline Refactoring)
- All existing model tests passing

**Priority:** LOW (Optional - can be deferred based on capacity)

---

## Architecture Reference

This phase refactors the model layer as defined in [SYSTEM_ARCHITECTURE.md §5 Model Layer](../SYSTEM_ARCHITECTURE.md#model-layer).

**Architectural Gaps Addressed:**
- ❌ Gap: 17 model files with some conceptual overlap
- ❌ Gap: No clear model categorization (core vs config vs processing)
- ❌ Gap: Some large model files (378, 350, 305 lines)
- ❌ Gap: Import complexity across model categories

**Components Modified:**
- Models: src/models/ reorganization

**Coverage Targets:**
- All model modules: ≥99%
- Overall coverage: Maintain ≥99%

---

## 1. Executive Summary

Phase 5.5 reorganizes the 17 model files into a logical hierarchy based on domain concepts. This improves discoverability, reduces import complexity, and establishes clear model categories.

**What This Phase Is:**
- ✅ Reorganization of models into logical categories.
- ✅ Creation of clear model subpackages.
- ✅ Improved import paths for common models.
- ✅ Maintained backward compatibility via re-exports.

**What This Phase Is NOT:**
- ❌ Changing model schemas or validation.
- ❌ Adding new model fields.
- ❌ Removing existing models.
- ❌ Breaking existing imports.

**Key Achievement:** Transform flat 17-file structure into organized 4-category hierarchy.

---

## 2. Problem Statement

### 2.1 Current Model Structure
```
src/models/                    # 17 files, 2,348 total lines
├── __init__.py               # Empty
├── cache.py                  # 73 lines
├── catalog.py                # 75 lines
├── checkpoint.py             # 32 lines
├── concurrency.py            # 54 lines
├── config.py                 # 305 lines (LARGE)
├── cross_synthesis.py        # 350 lines (LARGE)
├── dedup.py                  # 34 lines
├── extraction.py             # 165 lines
├── filters.py                # 45 lines
├── llm.py                    # 378 lines (LARGE)
├── notification.py           # 243 lines
├── paper.py                  # 64 lines
├── pdf_extraction.py         # 52 lines
├── provider.py               # 27 lines
├── registry.py               # 253 lines
└── synthesis.py              # 198 lines
```

### 2.2 Lack of Categorization
Models are not organized by domain:
- **Core domain models** (paper, author) mixed with **configuration** (config, llm)
- **Processing models** (extraction, synthesis) mixed with **infrastructure** (cache, checkpoint)

### 2.3 Import Complexity
Current imports require knowing specific file names:
```python
from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget
from src.models.config import ResearchConfig
```

---

## 3. Requirements

### 3.1 Model Categories

#### REQ-5.5.1: Core Domain Models
Core domain models SHALL be grouped in `models/core/`.

**Contents:**
- `paper.py` - PaperMetadata, Author, Journal
- `topic.py` - Topic-related models (extracted from config)
- `registry.py` - Registry entries and snapshots

#### REQ-5.5.2: Configuration Models
Configuration models SHALL be grouped in `models/config/`.

**Contents:**
- `research.py` - ResearchConfig, ResearchSettings
- `llm.py` - LLMConfig, CostLimits, LLMSettings
- `pipeline.py` - ConcurrencyConfig, FilterConfig

#### REQ-5.5.3: Processing Models
Processing-related models SHALL be grouped in `models/processing/`.

**Contents:**
- `extraction.py` - ExtractionTarget, PaperExtraction
- `synthesis.py` - SynthesisModels, KnowledgeBase
- `cross_synthesis.py` - CrossSynthesisModels

#### REQ-5.5.4: Infrastructure Models
Infrastructure models SHALL be grouped in `models/infra/`.

**Contents:**
- `cache.py` - CacheEntry, CacheConfig
- `checkpoint.py` - CheckpointData
- `notification.py` - NotificationModels

### 3.2 Backward Compatibility

#### REQ-5.5.5: Import Preservation
All existing imports SHALL continue to work.

```python
# These MUST continue to work:
from src.models.paper import PaperMetadata
from src.models.config import ResearchConfig
from src.models.extraction import ExtractionTarget
```

#### REQ-5.5.6: Convenience Re-exports
Common models SHALL be re-exported from `src/models/__init__.py`.

```python
# New convenient imports:
from src.models import PaperMetadata, ResearchConfig, ExtractionTarget
```

### 3.3 Package Structure

#### REQ-5.5.7: Model Organization

```
src/models/
├── __init__.py               # Re-export common models
├── core/
│   ├── __init__.py
│   ├── paper.py              # PaperMetadata, Author
│   ├── topic.py              # ResearchTopic, Timeframe
│   └── registry.py           # RegistryEntry, MetadataSnapshot
├── config/
│   ├── __init__.py
│   ├── research.py           # ResearchConfig, ResearchSettings
│   ├── llm.py                # LLMConfig, CostLimits
│   └── pipeline.py           # ConcurrencyConfig, FilterConfig
├── processing/
│   ├── __init__.py
│   ├── extraction.py         # ExtractionTarget, PaperExtraction
│   ├── synthesis.py          # KBEntry, DeltaBrief
│   └── cross_synthesis.py    # CrossSynthesis models
└── infra/
    ├── __init__.py
    ├── cache.py              # CacheEntry, CacheConfig
    ├── checkpoint.py         # CheckpointData
    └── notification.py       # NotificationConfig, SlackConfig
```

---

## 4. Technical Design

### 4.1 Root __init__.py Re-exports

```python
# src/models/__init__.py
"""
Research Assistant Models

This module provides Pydantic models for the research pipeline.

Categories:
- core: Domain models (Paper, Author, Topic)
- config: Configuration models (ResearchConfig, LLMConfig)
- processing: Processing models (Extraction, Synthesis)
- infra: Infrastructure models (Cache, Checkpoint)

Convenience Imports:
    from src.models import PaperMetadata, ResearchConfig, ExtractionTarget
"""

# Core domain models
from src.models.core.paper import PaperMetadata, Author
from src.models.core.topic import ResearchTopic, Timeframe
from src.models.core.registry import RegistryEntry, MetadataSnapshot

# Configuration models
from src.models.config.research import ResearchConfig, ResearchSettings
from src.models.config.llm import LLMConfig, CostLimits

# Processing models
from src.models.processing.extraction import ExtractionTarget, PaperExtraction
from src.models.processing.synthesis import KnowledgeBaseEntry

# Backward compatibility re-exports
from src.models.paper import *  # noqa: F401, F403
from src.models.config import *  # noqa: F401, F403

__all__ = [
    # Core
    "PaperMetadata",
    "Author",
    "ResearchTopic",
    "Timeframe",
    "RegistryEntry",
    "MetadataSnapshot",
    # Config
    "ResearchConfig",
    "ResearchSettings",
    "LLMConfig",
    "CostLimits",
    # Processing
    "ExtractionTarget",
    "PaperExtraction",
    "KnowledgeBaseEntry",
]
```

### 4.2 Legacy File Preservation

```python
# src/models/paper.py (LEGACY - preserved for backward compatibility)
"""
DEPRECATED: Import from src.models.core.paper instead.

This file is preserved for backward compatibility only.
"""
import warnings
from src.models.core.paper import *  # noqa: F401, F403

warnings.warn(
    "Importing from src.models.paper is deprecated. "
    "Use src.models.core.paper or src.models instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

### 4.3 Category __init__.py

```python
# src/models/core/__init__.py
"""Core domain models for the research pipeline."""
from src.models.core.paper import PaperMetadata, Author
from src.models.core.topic import ResearchTopic, Timeframe
from src.models.core.registry import RegistryEntry, MetadataSnapshot

__all__ = [
    "PaperMetadata",
    "Author",
    "ResearchTopic",
    "Timeframe",
    "RegistryEntry",
    "MetadataSnapshot",
]
```

---

## 5. Security Requirements (MANDATORY) 🔒

### SR-5.5.1: Model Validation
- [ ] All model validation logic preserved exactly.
- [ ] No new security vulnerabilities from reorganization.
- [ ] Pydantic validators unchanged.

### SR-5.5.2: Sensitive Data Handling
- [ ] Models handling secrets (LLMConfig) properly exclude from serialization.
- [ ] No credential exposure in model repr/str.
- [ ] All field exclusions preserved.

---

## 6. Implementation Tasks

### Task 1: Create Package Structure (0.5 day)
**Files:** src/models/core/, config/, processing/, infra/

1. Create directory structure with __init__.py files.
2. Create category __init__.py with exports.

### Task 2: Migrate Core Models (1 day)
**Files:** src/models/core/paper.py, topic.py, registry.py

1. Move PaperMetadata, Author to core/paper.py.
2. Extract topic models to core/topic.py.
3. Move registry models to core/registry.py.
4. Update all imports.

### Task 3: Migrate Config Models (0.5 day)
**Files:** src/models/config/research.py, llm.py, pipeline.py

1. Move ResearchConfig to config/research.py.
2. Move LLMConfig to config/llm.py.
3. Consolidate pipeline config models.
4. Update all imports.

### Task 4: Migrate Processing Models (0.5 day)
**Files:** src/models/processing/extraction.py, synthesis.py, cross_synthesis.py

1. Move extraction models.
2. Move synthesis models.
3. Move cross-synthesis models.
4. Update all imports.

### Task 5: Migrate Infra Models (0.5 day)
**Files:** src/models/infra/cache.py, checkpoint.py, notification.py

1. Move infrastructure models.
2. Update all imports.

### Task 6: Legacy Compatibility & Verification (1 day)
**Files:** src/models/*.py (legacy), all importers

1. Create legacy re-export files with deprecation warnings.
2. Update root __init__.py with convenience exports.
3. Verify all existing imports work.
4. Run full test suite.

---

## 7. Verification Criteria

### 7.1 Import Tests
- `test_legacy_imports_work`: All old import paths work.
- `test_new_imports_work`: New category imports work.
- `test_convenience_imports`: Root package imports work.
- `test_deprecation_warnings`: Legacy imports emit warnings.

### 7.2 Regression Tests
- All 1,468 existing tests MUST pass unchanged.
- Coverage MUST remain ≥99%.
- Model validation behavior unchanged.

### 7.3 Static Analysis
- No circular imports detected.
- Mypy passes with no new errors.
- All type hints preserved.

---

## 8. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Circular import issues | High | Medium | Careful dependency ordering |
| Breaking existing imports | High | Low | Legacy compatibility files |
| Type checking failures | Medium | Low | Preserve all type hints |
| Missing model exports | Medium | Low | Comprehensive export lists |

---

## 9. File Size Targets

Files are being reorganized, not reduced. Target is logical organization:

| Category | Files | Approx Lines |
|----------|-------|--------------|
| core/ | 3 | ~400 |
| config/ | 3 | ~450 |
| processing/ | 3 | ~750 |
| infra/ | 3 | ~350 |
| Legacy (re-exports) | 17 | ~170 (10 lines each) |

---

## 10. Migration Guide

### For Existing Code
No changes required. Existing imports will continue to work (with deprecation warnings).

### For New Code
Use the new category-based imports:

```python
# Old (deprecated but works):
from src.models.paper import PaperMetadata

# New (preferred):
from src.models.core.paper import PaperMetadata

# Convenience (also preferred):
from src.models import PaperMetadata
```

### Updating Existing Code (Optional)
When updating existing files for other reasons, consider updating imports:

```python
# Before
from src.models.paper import PaperMetadata
from src.models.config import ResearchConfig
from src.models.extraction import ExtractionTarget

# After
from src.models import PaperMetadata, ResearchConfig, ExtractionTarget
```
