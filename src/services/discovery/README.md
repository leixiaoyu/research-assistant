# Discovery Service Package

## Overview

The `discovery` package provides modular paper discovery services with multi-provider intelligence, quality scoring, and performance metrics.

## Architecture

```
src/services/discovery/
├── __init__.py           # Public API exports
├── service.py            # Main orchestration (~300 lines)
├── metrics.py            # Performance metrics collection (~150 lines)
├── result_merger.py      # Result merging and deduplication (~150 lines)
└── README.md             # This file
```

## Module Responsibilities

### `service.py` - Main Orchestration
- **DiscoveryService**: Main facade that coordinates all discovery operations
- Provider initialization and management
- Search orchestration with fallback support
- Enhanced search pipeline integration (Phase 6)
- Multi-source search with citation exploration (Phase 7.2)

**Key Methods:**
- `search()`: Basic search with intelligent provider selection
- `enhanced_search()`: 4-stage pipeline with LLM integration
- `multi_source_search()`: Multi-provider search with citations
- `search_with_metrics()`: Search with performance tracking
- `compare_providers()`: Provider benchmark comparison

### `metrics.py` - Performance Metrics
- **MetricsCollector**: Collects and analyzes provider performance
- Execution time tracking
- Success/failure monitoring
- Quality statistics logging
- Provider comparison analysis

**Key Methods:**
- `search_with_metrics()`: Execute search with timing
- `compare_providers()`: Benchmark all providers
- `log_quality_stats()`: Log quality and PDF availability

### `result_merger.py` - Result Merging
- **ResultMerger**: Handles merging and deduplication of results
- Two-stage deduplication (DOI/ID + title matching)
- ArXiv supplementation for PDF availability
- Benchmark mode (query all providers)

**Key Methods:**
- `is_duplicate()`: Check for duplicate papers
- `apply_arxiv_supplement()`: Add ArXiv papers if needed
- `benchmark_search()`: Query all providers concurrently

## Usage

### Basic Import (Backward Compatible)

```python
from src.services.discovery_service import DiscoveryService

# Works exactly as before
service = DiscoveryService(api_key="your_key")
papers = await service.search(topic)
```

### New Package Import

```python
from src.services.discovery import DiscoveryService

# Same functionality, cleaner import
service = DiscoveryService(api_key="your_key")
papers = await service.search(topic)
```

## Design Principles

1. **Backward Compatibility**: All existing imports continue to work
2. **Single Responsibility**: Each module has a clear, focused purpose
3. **Dependency Injection**: Components can be tested independently
4. **Composition**: Service orchestrates specialized components
5. **Extensibility**: Easy to add new providers or metrics

## Migration Path

The refactoring maintains 100% backward compatibility:

1. **Old Import** (still works):
   ```python
   from src.services.discovery_service import DiscoveryService
   ```

2. **New Import** (recommended):
   ```python
   from src.services.discovery import DiscoveryService
   ```

All existing tests pass without modification.

## Testing

Each module can be tested independently:

```python
# Test metrics collection
from src.services.discovery.metrics import MetricsCollector

collector = MetricsCollector(providers)
comparison = await collector.compare_providers(topic)

# Test result merging
from src.services.discovery.result_merger import ResultMerger

merger = ResultMerger(providers)
merged = await merger.apply_arxiv_supplement(topic, papers)
```

## Benefits

1. **Modularity**: ~900 lines split into focused ~150-300 line modules
2. **Testability**: Each component can be tested in isolation
3. **Maintainability**: Clear separation of concerns
4. **Reusability**: Components can be used independently
5. **Readability**: Easier to understand and navigate

## Phase Integration

- **Phase 3.2**: Provider selection, fallback, metrics
- **Phase 3.4**: Quality ranking, PDF tracking, ArXiv supplement
- **Phase 6.0**: Enhanced 4-stage pipeline with LLM
- **Phase 7.2**: Multi-source discovery with citations
