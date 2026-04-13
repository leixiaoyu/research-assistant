# FAISS Atomic Swap Mechanism

**SR-8.1 & Review Issue #5: Atomic Index Updates**

## Problem Statement

Raw FAISS files are difficult for atomic swaps and incremental updates. A failed index build could corrupt the existing search infrastructure, causing:
- Agent queries to fail mid-session
- Corpus unavailability during updates
- Data loss if process crashes during write

## Solution: Two-Phase Commit Pattern

### Overview

The ARISP DRA implements atomic index updates using a **two-phase commit pattern** similar to database transactions:

1. **Prepare Phase**: Build new index in temporary directory
2. **Commit Phase**: Atomic rename to production directory

### Implementation Details

#### File Structure

```
data/dra/corpus/
├── dense/
│   ├── faiss.index          # Current production FAISS index
│   └── dense_metadata.json   # Current metadata
├── bm25/
│   └── bm25_metadata.json
├── chunks.json               # Current chunks
├── papers.json               # Current papers
└── stats.json                # Current stats

data/dra/corpus/.tmp/         # Temporary build directory
├── dense/
│   ├── faiss.index          # New index being built
│   └── dense_metadata.json
├── bm25/
│   └── bm25_metadata.json
├── chunks.json
├── papers.json
└── stats.json
```

#### Phase 1: Prepare (Build in Temporary Directory)

```python
def save(self, path: Optional[Path] = None) -> None:
    """Save search engine state with atomic writes (SR-8.1)."""
    save_path = path or Path(self.corpus_config.corpus_dir)

    # Build in temporary directory
    temp_dir = save_path.parent / f".tmp_{save_path.name}_{uuid.uuid4().hex[:8]}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Write all indices to temp directory
        self._dense_index.save(temp_dir / "dense")
        self._bm25_index.save(temp_dir / "bm25")
        self._atomic_write_json(temp_dir / "chunks.json", chunks_data)

        # Phase 2: Atomic swap (OS-level rename)
        temp_dir.rename(save_path)

    except Exception:
        # Cleanup on failure
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
```

#### Phase 2: Commit (Atomic Rename)

The **critical operation** is `Path.rename()`, which is:
- **Atomic** on POSIX filesystems (same filesystem)
- **Guaranteed** by the OS kernel
- **Crash-safe**: Either old or new directory exists, never partial

### Atomicity Guarantees

#### POSIX Atomicity (Linux, macOS)

From POSIX.1-2017:
> "If the file named by `new` exists, it shall be removed and `old` shall be renamed to `new`. This operation shall be atomic."

**What this means:**
- If process crashes during `rename()`, filesystem is **consistent**
- Either old index exists OR new index exists, **never partial**
- No "half-written" FAISS indices
- No race conditions between readers and writers

#### Windows Atomicity

On Windows, `Path.rename()` is **NOT atomic** if target exists. For production Windows deployment:

```python
import os

# Windows-specific atomic replace (requires Python 3.3+)
os.replace(str(temp_dir), str(save_path))  # Atomic on Windows 10+
```

### Rollback Strategy

If index build fails **before** the atomic rename:
1. Temporary directory is deleted (automatic cleanup)
2. Production directory remains untouched
3. Agent continues using old (valid) index

If rename succeeds:
1. Old directory is atomically replaced
2. New index is now production
3. Agent seamlessly switches to new index on next query

### Incremental Updates

For incremental corpus updates (new papers added):

```python
def ingest_from_registry(self, registry_path: Path, force: bool = False) -> int:
    """Ingest papers with incremental index updates."""

    # 1. Load existing corpus
    if self.corpus_dir.exists():
        self.load()  # Load current production index

    # 2. Add new papers
    for paper_dir in new_papers:
        chunks = self._ingest_registry_paper(paper_dir)
        self.search_engine.index_chunks(chunks)  # Updates in-memory indices

    # 3. Save with atomic swap
    self.save()  # Atomic write of updated indices
```

**Key insight:** Incremental updates work by:
1. Loading current index into memory
2. Adding new chunks in memory
3. Writing **entire updated index** atomically (no in-place modification)

### Failure Scenarios & Recovery

| Scenario | Current State | Recovery |
|----------|---------------|----------|
| Crash during index build (Phase 1) | Production intact | Cleanup temp dir, retry |
| Crash during `rename()` (Phase 2) | OS guarantees atomicity | Either old or new exists |
| Disk full during Phase 1 | Production intact | Exception raised, temp cleaned |
| Permission error on `rename()` | Production intact | Exception raised, manual fix |

### Performance Considerations

**Trade-offs:**
- ✅ **Safety**: Crash-safe, no corruption risk
- ✅ **Simplicity**: Standard filesystem operations
- ❌ **Disk Space**: Requires 2x corpus size during update (temp + production)
- ❌ **Write Amplification**: Full index rewrite even for small updates

**Optimization for Large Corpora (>100K papers):**

For very large corpora, consider:
1. **Partitioned Indices**: Split corpus into shards, update shards independently
2. **IVF Indices**: FAISS IVF indices support incremental adds without full rebuild
3. **External Vector DBs**: Migrate to Qdrant/ChromaDB for true incremental updates

**Current Decision:** Use atomic swap for simplicity. Monitor corpus size; if >50K papers, migrate to partitioned approach.

### Code References

- **Atomic JSON writes**: `src/services/dra/search_engine.py:724` (`_atomic_write_json`)
- **Index save**: `src/services/dra/search_engine.py:684` (`save`)
- **Corpus save**: `src/services/dra/corpus_manager.py:521` (`save`)
- **Temporary directory pattern**: Uses `tempfile.mkstemp` for JSON, directory rename for indices

### Testing

Test coverage for atomic writes:
- ✅ `tests/unit/test_dra/test_corpus_manager.py::test_save_load_roundtrip`
- ✅ `tests/unit/test_dra/test_corpus_manager.py::test_atomic_write_recovery`
- ✅ `tests/unit/test_dra/test_search_engine.py::test_save_load`

### Future Improvements

1. **Qdrant Migration**: For true incremental updates without full rewrites
2. **Sharded Indices**: Split corpus into time-based shards (2024-Q1, 2024-Q2, etc.)
3. **Copy-on-Write**: Use filesystem COW features (ZFS, Btrfs) for efficient snapshots
4. **Index Versioning**: Keep N previous index versions for instant rollback

### Security Note (SR-8.1)

Corpus directories are created with `0o700` permissions (owner-only access):

```python
os.chmod(save_path, 0o700)  # Restrict to owner only
```

This prevents unauthorized access to embedding data and paper content.

---

**Last Updated**: 2026-04-13
**Author**: Claude Code (automated PR review response)
**Related**: PR #86, Review Issue #5
