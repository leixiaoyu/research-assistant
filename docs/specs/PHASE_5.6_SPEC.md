# Phase 5.6: Service Layer Improvements
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 3-4 days
**Dependencies:**
- Phase 5.1 Complete (LLMService Decomposition)
- Phase 5.2 Complete (ResearchPipeline Refactoring)
- All existing service tests passing

**Priority:** LOW (Optional - can be deferred based on capacity)

---

## Architecture Reference

This phase improves the service layer as defined in [SYSTEM_ARCHITECTURE.md §4 Service Layer](../SYSTEM_ARCHITECTURE.md#service-layer).

**Architectural Gaps Addressed:**
- ❌ Gap: No abstract service interface (inconsistent lifecycle management)
- ❌ Gap: Services instantiate dependencies directly (hard to test)
- ❌ Gap: RegistryService too large (602 lines)
- ❌ Gap: Inconsistent error handling across services

**Components Modified:**
- Services: All service classes
- New: Service base classes and interfaces

**Coverage Targets:**
- All new service modules: ≥99%
- Overall coverage: Maintain ≥99%

---

## 1. Executive Summary

Phase 5.6 establishes consistent patterns across the service layer through abstract interfaces, dependency injection preparation, and decomposition of large services. This improves testability, consistency, and maintainability.

**What This Phase Is:**
- ✅ Creation of abstract service interfaces.
- ✅ Preparation for dependency injection pattern.
- ✅ Decomposition of RegistryService (602 lines).
- ✅ Standardized service lifecycle management.

**What This Phase Is NOT:**
- ❌ Adding new service functionality.
- ❌ Implementing a DI container.
- ❌ Changing service behavior or outputs.
- ❌ Breaking existing service callers.

**Key Achievement:** Establish consistent service patterns and reduce largest service from 602 to <200 lines.

---

## 2. Problem Statement

### 2.1 No Abstract Service Interface
Services lack a common interface, leading to:
- Inconsistent initialization patterns
- Inconsistent shutdown/cleanup handling
- Inconsistent health check implementations

**Current pattern variance:**
```python
# DiscoveryService
def __init__(self, config: DiscoveryConfig):
    self._config = config
    # No explicit initialize()

# CacheService
def __init__(self, config: CacheConfig):
    self._cache = diskcache.Cache(config.cache_dir)
    # Initialization in __init__

# PDFService
async def download_pdf(self, ...):
    # No health check available
```

### 2.2 Direct Dependency Instantiation
Services create their dependencies directly:

```python
# Current pattern (extraction_service.py)
class ExtractionService:
    def __init__(self, config: ExtractionConfig):
        self._pdf_service = PDFService(config.pdf_config)  # Direct instantiation
        self._llm_service = LLMService(config.llm_config)  # Direct instantiation
```

This makes testing difficult and creates tight coupling.

### 2.3 Large RegistryService
`RegistryService` at 602 lines handles multiple responsibilities:
- Paper registration and lookup
- Metadata snapshots
- Deduplication checking
- State persistence (JSON I/O)
- Query operations

---

## 3. Requirements

### 3.1 Service Interfaces

#### REQ-5.6.1: AsyncService Base Class
An abstract `AsyncService` base class SHALL define the service lifecycle.

```python
class AsyncService(ABC):
    """Base class for async services with lifecycle management."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize service resources."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up service resources."""
        pass

    @abstractmethod
    async def health_check(self) -> ServiceHealth:
        """Check service health."""
        pass
```

#### REQ-5.6.2: Service Health Model
A standardized `ServiceHealth` model SHALL report service status.

**Fields:**
- `name`: Service name
- `healthy`: Boolean health status
- `latency_ms`: Optional health check latency
- `details`: Optional diagnostic details
- `dependencies`: List of dependency health

### 3.2 Dependency Injection Preparation

#### REQ-5.6.3: Constructor Injection Pattern
Services SHALL accept dependencies via constructor injection.

```python
# New pattern
class ExtractionService(AsyncService):
    def __init__(
        self,
        config: ExtractionConfig,
        pdf_service: PDFService,    # Injected
        llm_service: LLMService,    # Injected
    ):
        self._config = config
        self._pdf_service = pdf_service
        self._llm_service = llm_service
```

#### REQ-5.6.4: Factory Functions
Factory functions SHALL provide convenient service creation.

```python
def create_extraction_service(config: ExtractionConfig) -> ExtractionService:
    """Factory to create fully-configured ExtractionService."""
    pdf_service = PDFService(config.pdf_config)
    llm_service = LLMService(config.llm_config)
    return ExtractionService(config, pdf_service, llm_service)
```

### 3.3 RegistryService Decomposition

#### REQ-5.6.5: Registry Core
Core registry logic SHALL be extracted to `PaperRegistry` class (<200 lines).

**Responsibilities:**
- Paper registration
- Lookup by ID/DOI/title
- In-memory state management

#### REQ-5.6.6: Registry Persistence
Persistence logic SHALL be extracted to `RegistryPersistence` class.

**Responsibilities:**
- Load/save JSON state
- Atomic file operations
- Backup management

#### REQ-5.6.7: Registry Queries
Query operations SHALL be extracted to `RegistryQueries` class.

**Responsibilities:**
- Search by criteria
- Filter by date/topic
- Aggregation queries

### 3.4 Package Structure

#### REQ-5.6.8: Service Organization

```
src/services/
├── __init__.py               # Re-export public services
├── base.py                   # AsyncService, ServiceHealth
├── factories.py              # Service factory functions
├── registry/
│   ├── __init__.py           # Re-export RegistryService
│   ├── service.py            # RegistryService (orchestrator)
│   ├── core.py               # PaperRegistry
│   ├── persistence.py        # RegistryPersistence
│   └── queries.py            # RegistryQueries
├── discovery_service.py      # Updated to extend AsyncService
├── extraction_service.py     # Updated for DI pattern
├── llm_service.py            # (or llm/ package from Phase 5.1)
├── pdf_service.py            # Updated to extend AsyncService
└── ... (other services)
```

---

## 4. Technical Design

### 4.1 Service Base Classes

```python
# src/services/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class ServiceHealth:
    """Health status for a service."""
    name: str
    healthy: bool
    latency_ms: Optional[float] = None
    details: Optional[str] = None
    dependencies: List["ServiceHealth"] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "checked_at": self.checked_at.isoformat(),
        }


class AsyncService(ABC):
    """Abstract base class for async services.

    All services should extend this class to ensure consistent
    lifecycle management and health checking.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Service name for logging and health checks."""
        pass

    async def initialize(self) -> None:
        """Initialize service resources.

        Override to set up connections, caches, etc.
        Called once before first use.
        """
        pass  # Default: no initialization needed

    async def shutdown(self) -> None:
        """Clean up service resources.

        Override to close connections, flush caches, etc.
        Called during graceful shutdown.
        """
        pass  # Default: no cleanup needed

    async def health_check(self) -> ServiceHealth:
        """Check service health.

        Override to provide meaningful health status.
        Default implementation returns healthy.
        """
        return ServiceHealth(name=self.name, healthy=True)


class SyncService(ABC):
    """Abstract base class for synchronous services."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Service name for logging and health checks."""
        pass

    def initialize(self) -> None:
        """Initialize service resources."""
        pass

    def shutdown(self) -> None:
        """Clean up service resources."""
        pass

    def health_check(self) -> ServiceHealth:
        """Check service health."""
        return ServiceHealth(name=self.name, healthy=True)
```

### 4.2 Service Factory

```python
# src/services/factories.py
"""Factory functions for creating fully-configured services.

These factories provide convenient service creation while maintaining
testability through dependency injection.
"""
from typing import Optional

from src.models.config import ResearchConfig
from src.services.discovery_service import DiscoveryService
from src.services.extraction_service import ExtractionService
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService


def create_discovery_service(config: ResearchConfig) -> DiscoveryService:
    """Create a configured DiscoveryService."""
    return DiscoveryService(
        config=config.settings.discovery_config,
        api_key=config.settings.api_key,
    )


def create_extraction_service(
    config: ResearchConfig,
    pdf_service: Optional[PDFService] = None,
    llm_service: Optional[LLMService] = None,
) -> ExtractionService:
    """Create a configured ExtractionService.

    Args:
        config: Research configuration.
        pdf_service: Optional pre-configured PDFService (for testing).
        llm_service: Optional pre-configured LLMService (for testing).

    Returns:
        Configured ExtractionService.
    """
    if pdf_service is None:
        pdf_service = PDFService(config.settings.pdf_settings)

    if llm_service is None:
        llm_service = LLMService(
            config.settings.llm_settings,
            config.settings.cost_limits,
        )

    return ExtractionService(
        config=config.settings.extraction_config,
        pdf_service=pdf_service,
        llm_service=llm_service,
    )
```

### 4.3 Registry Decomposition

```python
# src/services/registry/core.py
"""Core paper registry functionality."""
from typing import Dict, List, Optional
from src.models.core.paper import PaperMetadata
from src.models.core.registry import RegistryEntry


class PaperRegistry:
    """In-memory paper registry with fast lookups."""

    def __init__(self):
        self._entries: Dict[str, RegistryEntry] = {}
        self._doi_index: Dict[str, str] = {}  # DOI -> paper_id
        self._title_index: Dict[str, str] = {}  # normalized_title -> paper_id

    def register(self, paper: PaperMetadata, topic: str) -> RegistryEntry:
        """Register a paper and return its entry."""
        entry = RegistryEntry.from_paper(paper, topic)
        self._entries[entry.paper_id] = entry
        self._update_indexes(entry)
        return entry

    def get_by_id(self, paper_id: str) -> Optional[RegistryEntry]:
        """Get entry by paper ID."""
        return self._entries.get(paper_id)

    def get_by_doi(self, doi: str) -> Optional[RegistryEntry]:
        """Get entry by DOI."""
        paper_id = self._doi_index.get(doi)
        return self._entries.get(paper_id) if paper_id else None

    def exists(self, paper: PaperMetadata) -> bool:
        """Check if paper is already registered."""
        if paper.doi and paper.doi in self._doi_index:
            return True
        normalized = self._normalize_title(paper.title)
        return normalized in self._title_index

    def _update_indexes(self, entry: RegistryEntry) -> None:
        """Update lookup indexes."""
        if entry.doi:
            self._doi_index[entry.doi] = entry.paper_id
        self._title_index[self._normalize_title(entry.title)] = entry.paper_id

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for comparison."""
        return title.lower().strip()


# src/services/registry/persistence.py
"""Registry persistence layer."""
import json
from pathlib import Path
from typing import Dict
from src.models.core.registry import RegistryEntry
from src.utils.path_sanitizer import PathSanitizer


class RegistryPersistence:
    """Handles registry state persistence."""

    def __init__(self, registry_path: Path):
        self._path = PathSanitizer.sanitize(registry_path)

    def load(self) -> Dict[str, RegistryEntry]:
        """Load registry state from disk."""
        if not self._path.exists():
            return {}

        with open(self._path, "r") as f:
            data = json.load(f)

        return {
            paper_id: RegistryEntry.model_validate(entry)
            for paper_id, entry in data.items()
        }

    def save(self, entries: Dict[str, RegistryEntry]) -> None:
        """Save registry state to disk atomically."""
        # Write to temp file first
        temp_path = self._path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(
                {k: v.model_dump() for k, v in entries.items()},
                f,
                indent=2,
            )

        # Atomic rename
        temp_path.rename(self._path)


# src/services/registry/service.py
"""Main RegistryService orchestrator."""
from pathlib import Path
from src.services.base import AsyncService, ServiceHealth
from src.services.registry.core import PaperRegistry
from src.services.registry.persistence import RegistryPersistence
from src.services.registry.queries import RegistryQueries


class RegistryService(AsyncService):
    """Paper registry service with persistence."""

    def __init__(self, registry_path: Path):
        self._registry = PaperRegistry()
        self._persistence = RegistryPersistence(registry_path)
        self._queries = RegistryQueries(self._registry)

    @property
    def name(self) -> str:
        return "registry"

    async def initialize(self) -> None:
        """Load registry state from disk."""
        entries = self._persistence.load()
        for entry in entries.values():
            self._registry._entries[entry.paper_id] = entry
            self._registry._update_indexes(entry)

    async def shutdown(self) -> None:
        """Save registry state to disk."""
        self._persistence.save(self._registry._entries)

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            name=self.name,
            healthy=True,
            details=f"{len(self._registry._entries)} papers registered",
        )

    # Delegate to components
    def register(self, paper, topic):
        return self._registry.register(paper, topic)

    def get_by_id(self, paper_id):
        return self._registry.get_by_id(paper_id)

    def exists(self, paper):
        return self._registry.exists(paper)

    def search(self, **criteria):
        return self._queries.search(**criteria)
```

---

## 5. Security Requirements (MANDATORY) 🔒

### SR-5.6.1: Service Isolation
- [ ] Services do not expose internal state directly.
- [ ] Service boundaries enforce access control.
- [ ] Health checks do not expose sensitive info.

### SR-5.6.2: Dependency Injection Safety
- [ ] Injected dependencies validated before use.
- [ ] No untrusted dependencies accepted.
- [ ] Factory functions validate configuration.

### SR-5.6.3: Persistence Security
- [ ] Registry persistence uses atomic operations.
- [ ] Backup files secured appropriately.
- [ ] No sensitive data in plain-text persistence.

---

## 6. Implementation Tasks

### Task 1: Create Service Base Classes (0.5 day)
**Files:** src/services/base.py

1. Create AsyncService abstract class.
2. Create SyncService abstract class.
3. Create ServiceHealth dataclass.
4. Add comprehensive tests.

### Task 2: Decompose RegistryService (1.5 days)
**Files:** src/services/registry/

1. Extract PaperRegistry (core logic).
2. Extract RegistryPersistence (JSON I/O).
3. Extract RegistryQueries (search operations).
4. Refactor RegistryService as orchestrator.
5. Add comprehensive tests.

### Task 3: Update Services to Extend Base (1 day)
**Files:** src/services/*.py

1. Update DiscoveryService to extend AsyncService.
2. Update PDFService to extend AsyncService.
3. Update CacheService to extend SyncService.
4. Add health_check implementations.
5. Update tests.

### Task 4: Implement DI Pattern (0.5 day)
**Files:** src/services/factories.py, extraction_service.py

1. Create factory functions module.
2. Update ExtractionService for DI.
3. Preserve backward compatibility.
4. Add factory tests.

### Task 5: Integration & Verification (0.5 day)
**Files:** All services, tests/

1. Verify all services work together.
2. Verify all existing tests pass.
3. Verify health endpoints work.
4. Document migration path.

---

## 7. Verification Criteria

### 7.1 Unit Tests (New)
- `test_async_service_lifecycle`: Initialize/shutdown called.
- `test_service_health_check`: Health check returns valid status.
- `test_paper_registry_register`: Registration works.
- `test_registry_persistence_atomic`: Save is atomic.
- `test_factory_creates_service`: Factory creates configured service.
- `test_di_allows_mock_injection`: Can inject mock dependencies.

### 7.2 Regression Tests
- All 1,468 existing tests MUST pass unchanged.
- Coverage MUST remain ≥99%.
- Service behavior unchanged.

### 7.3 Integration Tests
- `test_service_lifecycle_integration`: Full lifecycle works.
- `test_health_endpoint_aggregation`: Health aggregates correctly.
- `test_registry_persistence_roundtrip`: Load/save works.

---

## 8. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking service instantiation | High | Low | Backward-compat factories |
| Registry data loss during migration | High | Low | Careful atomic operations |
| Circular dependencies | Medium | Medium | Careful import ordering |
| Performance regression | Low | Low | Benchmark critical paths |

---

## 9. File Size Targets

| File | Current | Target |
|------|---------|--------|
| registry_service.py | 602 lines | <100 lines (orchestrator) |
| registry/core.py | N/A | <150 lines |
| registry/persistence.py | N/A | <100 lines |
| registry/queries.py | N/A | <150 lines |
| base.py | N/A | <100 lines |
| factories.py | N/A | <150 lines |

---

## 10. Benefits Summary

### 10.1 Testability
- Services can be tested with mock dependencies
- Health checks provide testable status
- Factory functions allow test configuration

### 10.2 Consistency
- All services follow same lifecycle
- Health checks use same format
- Error handling standardized

### 10.3 Maintainability
- RegistryService reduced from 602 to ~100 lines
- Clear separation of concerns
- Easier to understand each component

### 10.4 Extensibility
- New services follow established pattern
- DI pattern allows easy swapping
- Base classes provide common functionality
