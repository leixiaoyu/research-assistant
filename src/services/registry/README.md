# Registry Service Package

## Overview

The `registry` package provides modular paper identity resolution and persistence management with cross-topic deduplication, atomic state persistence, and backfill detection.

## Architecture

```
src/services/registry/
├── __init__.py           # Public API exports
├── service.py            # Main orchestration (~300 lines)
├── paper_registry.py     # Identity resolution & registration (~250 lines)
├── persistence.py        # JSON I/O with atomic writes, fcntl locking (~150 lines)
├── queries.py            # Search & filter operations (~75 lines)
└── README.md             # This file
```

## Module Responsibilities

### `service.py` - Main Orchestration
- **RegistryService**: Main facade that coordinates all registry operations
- Initialization and configuration management
- State caching and lifecycle management
- Coordination between persistence, registration, and query layers

**Key Methods:**
- `load()`: Load registry state from disk with file locking
- `save()`: Atomically save registry state to disk
- `register_paper()`: Register paper with identity resolution and deduplication
- `get_entry()`: Retrieve entry by paper ID
- `get_entries_for_topic()`: Filter entries by topic affiliation
- `get_stats()`: Retrieve registry statistics

### `paper_registry.py` - Identity Resolution & Registration
- **PaperRegistry**: Core logic for paper identity resolution and registration
- Three-stage identity resolution (DOI → Provider ID → Fuzzy Title)
- Paper registration with automatic deduplication
- Topic affiliation tracking
- Backfill detection based on extraction target changes

**Key Methods:**
- `resolve_identity()`: Match paper against existing registry entries
  - Stage 1: DOI exact match
  - Stage 2: Provider ID match (arxiv:xxx, semantic_scholar:xxx)
  - Stage 3: Fuzzy title matching (≥95% similarity by default)
- `register_paper()`: Create or update registry entry
- `determine_action()`: Decide SKIP, BACKFILL, or FULL_PROCESS
- `update_entry()`: Update existing entry with new metadata

**Identity Resolution Strategy:**
1. **DOI Match (Highest Priority)**: If paper has DOI and it exists in `doi_index`, match immediately
2. **Provider ID Match**: Check ArXiv IDs, Semantic Scholar IDs via `provider_id_index`
3. **Fuzzy Title Match**: Calculate similarity using normalized titles (default threshold: 0.95)

### `persistence.py` - Safe JSON I/O
- **RegistryPersistence**: Handles atomic writes and concurrent access protection
- Advisory file locking using `fcntl` (POSIX standard)
- Atomic writes via temp file + rename pattern
- Automatic backup creation on corruption detection
- Owner-only file permissions (0600 for file, 0700 for directory)

**Key Methods:**
- `acquire_lock()`: Acquire exclusive advisory lock (blocking)
- `release_lock()`: Release file lock
- `load()`: Read registry from disk with corruption recovery
- `save()`: Atomically write registry to disk
- `_ensure_directory()`: Create directory with proper permissions
- `_set_file_permissions()`: Enforce owner-only access

**Safety Features:**
- Advisory locking prevents concurrent write corruption
- Temp file + rename ensures atomic updates (no partial writes)
- JSON parse errors trigger automatic backup creation
- Proper cleanup of lock file descriptors

### `queries.py` - Search & Filter Operations
- **RegistryQueries**: Read-only query operations for registry data
- Lookup by canonical paper ID
- Filter entries by topic affiliation
- Statistics aggregation

**Key Methods:**
- `get_entry()`: Retrieve entry by paper ID
- `get_entries_for_topic()`: Get all entries for a topic slug
- `get_stats()`: Calculate registry statistics (entry count, index sizes, timestamps)

## Usage

### Basic Import (Backward Compatible)

```python
from src.services.registry_service import RegistryService

# Works exactly as before
service = RegistryService()
state = service.load()
```

### New Package Import

```python
from src.services.registry import RegistryService

# Same functionality, cleaner import
service = RegistryService()
state = service.load()
```

### Identity Resolution Example

```python
from src.services.registry import RegistryService
from src.models.paper import PaperMetadata

# Initialize service
service = RegistryService()
state = service.load()

# Register a paper with automatic deduplication
paper = PaperMetadata(
    paper_id="arxiv:2301.12345",
    title="Tree of Thoughts: Deliberate Problem Solving",
    doi="10.1234/example.doi",
    abstract="...",
    url="https://arxiv.org/abs/2301.12345"
)

result = service.register_paper(
    paper=paper,
    topic_slug="tot-reasoning",
    extraction_target="prompts"
)

# Check what action was determined
if result.action == "SKIP":
    print(f"Paper already processed: {result.entry.paper_id}")
elif result.action == "BACKFILL":
    print(f"Re-extract due to target change: {result.entry.paper_id}")
elif result.action == "FULL_PROCESS":
    print(f"New paper registered: {result.entry.paper_id}")
```

### Custom Title Similarity Threshold

```python
# Use stricter title matching (99% similarity)
service = RegistryService(title_similarity_threshold=0.99)

# Or more permissive (85% similarity)
service = RegistryService(title_similarity_threshold=0.85)
```

### Query Operations

```python
# Get all papers for a topic
entries = service.get_entries_for_topic("tot-reasoning")
print(f"Found {len(entries)} papers for topic")

# Get specific entry
entry = service.get_entry("550e8400-e29b-41d4-a716-446655440000")
if entry:
    print(f"Title: {entry.title}")
    print(f"Topics: {entry.topic_affiliations}")

# Get registry statistics
stats = service.get_stats()
print(f"Total papers: {stats['total_entries']}")
print(f"Unique DOIs: {stats['total_dois']}")
```

## Design Principles

1. **Backward Compatibility**: All existing imports continue to work
2. **Single Responsibility**: Each module has a clear, focused purpose
   - `service.py`: Orchestration and public API
   - `paper_registry.py`: Core identity and registration logic
   - `persistence.py`: Safe file I/O with locking
   - `queries.py`: Read-only search and filter operations
3. **Dependency Injection**: Components can be tested independently
4. **Composition**: Service orchestrates specialized components
5. **Atomic Operations**: State changes are all-or-nothing (no partial corruption)
6. **Concurrent Safety**: Advisory locking prevents race conditions

## Migration Path

The refactoring maintains 100% backward compatibility:

1. **Old Import** (still works):
   ```python
   from src.services.registry_service import RegistryService
   ```

2. **New Import** (recommended):
   ```python
   from src.services.registry import RegistryService
   ```

All existing tests pass without modification.

## Testing

Each module can be tested independently:

```python
# Test persistence layer
from src.services.registry.persistence import RegistryPersistence

persistence = RegistryPersistence(Path("data/test_registry.json"))
assert persistence.acquire_lock()
state = persistence.load()
persistence.save(state)
persistence.release_lock()

# Test identity resolution
from src.services.registry.paper_registry import PaperRegistry

registry = PaperRegistry(title_similarity_threshold=0.90)
match = registry.resolve_identity(paper, state)
if match.matched:
    print(f"Matched via: {match.match_method}")

# Test query operations
from src.services.registry.queries import RegistryQueries

queries = RegistryQueries()
entries = queries.get_entries_for_topic("tot-reasoning", state)
stats = queries.get_stats(state)
```

## Benefits

1. **Modularity**: ~700 lines split into focused ~75-300 line modules
2. **Testability**: Each component can be tested in isolation
3. **Maintainability**: Clear separation of concerns
4. **Safety**: Atomic writes and file locking prevent corruption
5. **Flexibility**: Configurable title similarity threshold
6. **Observability**: Structured logging at all key decision points

## Phase Integration

- **Phase 4 (R4.3)**: Decomposed RegistryService into modular package
- **Phase 3.3**: Cross-topic deduplication and identity resolution
- **Phase 3.2**: Backfill detection based on extraction target changes

## File Locking Details

The persistence layer uses POSIX advisory file locking (`fcntl.flock`) to prevent concurrent corruption:

- **Lock File**: `data/registry.lock` (created automatically)
- **Lock Type**: Exclusive (LOCK_EX) - only one process can hold the lock
- **Blocking**: Lock acquisition blocks until available (no busy-waiting)
- **Cleanup**: Locks automatically released on process termination
- **Platform Support**: POSIX-compliant systems (Linux, macOS, BSD)

**Note**: Advisory locks require cooperation - processes must use `acquire_lock()` before modifications.

## Security Considerations

1. **File Permissions**: Registry files use 0600 (owner-only read/write)
2. **Directory Permissions**: Registry directory uses 0700 (owner-only access)
3. **Atomic Writes**: Temp file + rename prevents partial corruption
4. **No Secrets in Registry**: Never log or persist API keys or credentials
5. **Input Validation**: All paper metadata validated via Pydantic models

## Performance Characteristics

- **Identity Resolution**: O(1) for DOI/Provider ID lookup, O(n) for title fuzzy matching
- **Registration**: O(1) for new papers, O(1) for updates
- **File I/O**: Single read on load, single atomic write on save
- **Locking Overhead**: Minimal (kernel-level advisory locks)
- **Memory Footprint**: Entire registry state cached in memory (acceptable for <100k papers)

## Future Enhancements

Potential improvements (not currently planned):

- **Database Backend**: Replace JSON with SQLite for large-scale deployments (>100k papers)
- **Incremental Saves**: Append-only log for reducing write overhead
- **Distributed Locking**: Redis-based locks for multi-host setups
- **Index Optimization**: B-tree or hash-based indexes for faster fuzzy matching
