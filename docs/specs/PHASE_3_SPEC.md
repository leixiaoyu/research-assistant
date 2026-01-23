# Phase 3: Intelligence & Optimization
**Version:** 1.0
**Status:** Draft
**Timeline:** 2 weeks
**Dependencies:** Phase 1 & 2 Complete

## Architecture Reference

This phase implements production-grade concurrency and intelligence features as defined in [SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md).

**Architectural Gaps Addressed:**
- ✅ Gap #2: Concurrency Model (async producer-consumer)
- ✅ Gap #6: Storage Strategy (retention, compression)
- ✅ Gap #9: Incremental Processing (checkpointing)
- ✅ Gap #10: Paper Quality Filters

**Components Implemented:**
- Orchestration Layer: Concurrent Pipeline (see [Architecture §5](../SYSTEM_ARCHITECTURE.md#core-components))
- Service Layer: Cache Service, Deduplication Service, Filter Service, Checkpoint Service
- Infrastructure Layer: Multi-level caching (see [Architecture §7](../SYSTEM_ARCHITECTURE.md#storage--caching))

**Concurrency Architecture:**
- Bounded queue with backpressure
- Semaphores for resource limiting
- Worker pool pattern (see [Architecture §6.1](../SYSTEM_ARCHITECTURE.md#concurrency-model))

**Performance Targets:**
- 50 papers in <30 minutes (vs 2+ hours sequential)
- Cache hit rate >60%
- Cost reduction >40%

## Overview

Transform the pipeline from sequential processing to intelligent, concurrent operations with sophisticated deduplication, caching, and optimization strategies. This phase focuses on performance, efficiency, and intelligent paper filtering to reduce costs and improve output quality.

## Objectives

### Primary Objectives
1. ✅ Implement concurrent paper processing using asyncio
2. ✅ Add multi-level caching (API responses, extractions, PDFs)
3. ✅ Enhance duplicate detection with paper-level deduplication
4. ✅ Implement paper quality filtering and ranking
5. ✅ Add incremental processing and checkpoint/resume
6. ✅ Optimize resource usage and reduce costs

### Success Criteria
- [ ] Process 50 papers in < 30 minutes (vs 2+ hours sequential)
- [ ] Cache hit rate > 60% on repeated queries
- [ ] Detect 95%+ duplicate papers across runs
- [ ] Reduce LLM costs by 40% through smart filtering
- [ ] Can resume from checkpoint after interruption
- [ ] Paper relevance score accuracy > 80%

## Architecture Additions

### Updated Module Structure
```
research-assist/
├── src/
│   ├── models/
│   │   ├── cache.py             # NEW: Cache models
│   │   └── filters.py           # NEW: Filter models
│   ├── services/
│   │   ├── concurrency.py       # NEW: Concurrent orchestration
│   │   ├── cache_service.py     # NEW: Caching layer
│   │   ├── dedup_service.py     # NEW: Deduplication
│   │   ├── filter_service.py    # NEW: Paper filtering
│   │   └── checkpoint_service.py # NEW: State management
│   └── utils/
│       └── similarity.py        # NEW: Text similarity
├── cache/                        # NEW: Cache storage
│   ├── api_responses/
│   ├── pdfs/
│   └── extractions/
└── checkpoints/                  # NEW: Checkpoint files
```

## Technical Specifications

### 1. Concurrent Processing (`src/services/concurrency.py`)

**Design Pattern:** Async producer-consumer with backpressure

**Architecture:**
```
                    ┌──────────────────┐
                    │  Topic Queue     │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  Paper Queue     │
                    │  (bounded)       │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
    ┌─────▼─────┐      ┌────▼────┐       ┌────▼────┐
    │  Worker 1 │      │ Worker 2│       │ Worker N│
    │  Download │      │ Download│       │ Download│
    │  Convert  │      │ Convert │       │ Convert │
    │  Extract  │      │ Extract │       │ Extract │
    └───────────┘      └─────────┘       └─────────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
                    ┌────────▼─────────┐
                    │  Results Queue   │
                    └──────────────────┘
```

**Implementation:**
```python
import asyncio
from typing import List, AsyncIterator
from dataclasses import dataclass

@dataclass
class ProcessingConfig:
    max_concurrent_downloads: int = 5
    max_concurrent_conversions: int = 3
    max_concurrent_llm: int = 2  # Respect API limits
    queue_size: int = 100
    checkpoint_interval: int = 10  # Papers

class ConcurrentPipeline:
    """Concurrent paper processing pipeline"""

    def __init__(
        self,
        config: ProcessingConfig,
        pdf_service: PDFService,
        llm_service: LLMService,
        checkpoint_service: CheckpointService
    ):
        self.config = config
        self.pdf_service = pdf_service
        self.llm_service = llm_service
        self.checkpoint_service = checkpoint_service

        # Semaphores for rate limiting
        self.download_sem = asyncio.Semaphore(config.max_concurrent_downloads)
        self.conversion_sem = asyncio.Semaphore(config.max_concurrent_conversions)
        self.llm_sem = asyncio.Semaphore(config.max_concurrent_llm)

    async def process_papers(
        self,
        papers: List[PaperMetadata],
        targets: List[ExtractionTarget],
        run_id: str
    ) -> AsyncIterator[ExtractedPaper]:
        """Process papers concurrently with backpressure

        Yields:
            ExtractedPaper as they complete (not in order)
        """
        # Load checkpoint
        processed_ids = self.checkpoint_service.load_processed(run_id)
        pending = [p for p in papers if p.paper_id not in processed_ids]

        logger.info(
            "Starting concurrent processing",
            total=len(papers),
            pending=len(pending),
            from_checkpoint=len(processed_ids)
        )

        # Create bounded queue
        queue = asyncio.Queue(maxsize=self.config.queue_size)

        # Start workers
        workers = [
            asyncio.create_task(
                self._worker(queue, targets, run_id, worker_id=i)
            )
            for i in range(self.config.max_concurrent_downloads)
        ]

        # Feed queue
        producer = asyncio.create_task(
            self._produce(queue, pending)
        )

        # Collect results
        completed = 0
        async for result in self._collect_results(workers):
            yield result
            completed += 1

            # Checkpoint periodically
            if completed % self.config.checkpoint_interval == 0:
                self.checkpoint_service.save_progress(
                    run_id,
                    result.metadata.paper_id
                )

        await producer
        await asyncio.gather(*workers)

    async def _worker(
        self,
        queue: asyncio.Queue,
        targets: List[ExtractionTarget],
        run_id: str,
        worker_id: int
    ):
        """Worker coroutine"""
        while True:
            try:
                paper = await asyncio.wait_for(
                    queue.get(),
                    timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if paper is None:  # Sentinel value
                break

            try:
                # Process with resource limits
                result = await self._process_single(paper, targets)
                yield result

            except Exception as e:
                logger.error(
                    "Worker failed processing paper",
                    worker_id=worker_id,
                    paper_id=paper.paper_id,
                    error=str(e)
                )
            finally:
                queue.task_done()

    async def _process_single(
        self,
        paper: PaperMetadata,
        targets: List[ExtractionTarget]
    ) -> ExtractedPaper:
        """Process single paper with semaphore limits"""

        # Download phase
        async with self.download_sem:
            pdf_path = await self.pdf_service.download_pdf(
                paper.open_access_pdf
            )

        # Conversion phase
        async with self.conversion_sem:
            md_path = await asyncio.to_thread(
                self.pdf_service.convert_to_markdown,
                pdf_path
            )

        # Extraction phase
        async with self.llm_sem:
            extraction = await self.llm_service.extract(
                md_path.read_text(),
                targets,
                paper
            )

        return ExtractedPaper(
            metadata=paper,
            pdf_available=True,
            extraction=extraction
        )
```

### 2. Caching Layer (`src/services/cache_service.py`)

**Multi-Level Cache Strategy:**

```
Level 1: API Responses (1 hour TTL)
  ↓
Level 2: PDFs (7 days TTL)
  ↓
Level 3: Markdown (7 days TTL)
  ↓
Level 4: Extractions (30 days TTL)
```

**Implementation:**
```python
import diskcache
from pathlib import Path
from typing import Optional, Any
import hashlib

class CacheService:
    """Multi-level disk cache"""

    def __init__(self, cache_dir: Path):
        self.api_cache = diskcache.Cache(cache_dir / "api", timeout=3600)
        self.pdf_cache = diskcache.Cache(cache_dir / "pdfs", timeout=604800)
        self.extraction_cache = diskcache.Cache(cache_dir / "extractions", timeout=2592000)

    def get_api_response(self, query_hash: str) -> Optional[dict]:
        """Get cached API response"""
        return self.api_cache.get(query_hash)

    def set_api_response(self, query_hash: str, response: dict):
        """Cache API response"""
        self.api_cache.set(query_hash, response)

    def get_pdf(self, paper_id: str) -> Optional[Path]:
        """Get cached PDF path"""
        path = self.pdf_cache.get(paper_id)
        if path and Path(path).exists():
            return Path(path)
        return None

    def set_pdf(self, paper_id: str, pdf_path: Path):
        """Cache PDF"""
        self.pdf_cache.set(paper_id, str(pdf_path))

    def get_extraction(
        self,
        paper_id: str,
        targets_hash: str
    ) -> Optional[PaperExtraction]:
        """Get cached extraction

        Cache key includes paper_id AND targets hash
        so changes to extraction targets invalidate cache
        """
        key = f"{paper_id}:{targets_hash}"
        data = self.extraction_cache.get(key)
        if data:
            return PaperExtraction.parse_obj(data)
        return None

    def set_extraction(
        self,
        paper_id: str,
        targets_hash: str,
        extraction: PaperExtraction
    ):
        """Cache extraction"""
        key = f"{paper_id}:{targets_hash}"
        self.extraction_cache.set(key, extraction.dict())

    @staticmethod
    def hash_query(query: str, timeframe: Timeframe) -> str:
        """Generate cache key for query"""
        content = f"{query}:{timeframe.type}:{timeframe.value}"
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def hash_targets(targets: List[ExtractionTarget]) -> str:
        """Generate hash for extraction targets"""
        content = "|".join(
            f"{t.name}:{t.description}:{t.output_format}"
            for t in sorted(targets, key=lambda x: x.name)
        )
        return hashlib.sha256(content.encode()).hexdigest()

    def get_stats(self) -> dict:
        """Get cache statistics"""
        return {
            "api_cache": {
                "size": len(self.api_cache),
                "hits": self.api_cache.stats()['hits'],
                "misses": self.api_cache.stats()['misses']
            },
            "pdf_cache": {
                "size": len(self.pdf_cache),
                "disk_mb": self._get_cache_size_mb(self.pdf_cache)
            },
            "extraction_cache": {
                "size": len(self.extraction_cache)
            }
        }
```

### 3. Enhanced Deduplication (`src/services/dedup_service.py`)

**Strategy:** Multi-stage deduplication

**Stages:**
1. **Exact DOI matching** (fastest)
2. **Title similarity** (fuzzy matching)
3. **Content fingerprinting** (for papers without DOI)

**Implementation:**
```python
from difflib import SequenceMatcher
from typing import Set, List, Tuple
import re

class DeduplicationService:
    """Detect duplicate papers across runs"""

    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self._build_indices()

    def _build_indices(self):
        """Build lookup indices from catalog"""
        self.doi_index: Set[str] = set()
        self.title_index: dict[str, str] = {}  # normalized_title → paper_id

        for topic in self.catalog.topics.values():
            for run in topic.runs:
                # Extract DOIs and titles from previous runs
                # (requires enhancing catalog to store this info)
                pass

    def find_duplicates(
        self,
        papers: List[PaperMetadata]
    ) -> Tuple[List[PaperMetadata], List[PaperMetadata]]:
        """Separate new papers from duplicates

        Returns:
            (new_papers, duplicate_papers)
        """
        new_papers = []
        duplicates = []

        for paper in papers:
            if self._is_duplicate(paper):
                duplicates.append(paper)
            else:
                new_papers.append(paper)

        logger.info(
            "Deduplication complete",
            total=len(papers),
            new=len(new_papers),
            duplicates=len(duplicates)
        )

        return new_papers, duplicates

    def _is_duplicate(self, paper: PaperMetadata) -> bool:
        """Check if paper is duplicate"""

        # Stage 1: Exact DOI match
        if paper.doi and paper.doi in self.doi_index:
            return True

        # Stage 2: Title similarity
        normalized_title = self._normalize_title(paper.title)
        for existing_title, existing_id in self.title_index.items():
            similarity = SequenceMatcher(
                None,
                normalized_title,
                existing_title
            ).ratio()

            if similarity > 0.90:  # 90% similar
                logger.debug(
                    "Duplicate found by title",
                    new_title=paper.title,
                    existing_id=existing_id,
                    similarity=similarity
                )
                return True

        # Stage 3: Could add abstract similarity here

        return False

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for comparison"""
        # Lowercase
        title = title.lower()
        # Remove punctuation
        title = re.sub(r'[^\w\s]', '', title)
        # Remove extra whitespace
        title = ' '.join(title.split())
        return title

    def update_indices(self, papers: List[PaperMetadata]):
        """Update indices with new papers"""
        for paper in papers:
            if paper.doi:
                self.doi_index.add(paper.doi)
            self.title_index[
                self._normalize_title(paper.title)
            ] = paper.paper_id
```

### 4. Paper Filtering (`src/services/filter_service.py`)

**Filter Types:**
- Citation count threshold
- Venue/conference allowlist
- Publication year range
- Relevance scoring (semantic similarity to query)

**Implementation:**
```python
from typing import List
from pydantic import BaseModel

class PaperFilter(BaseModel):
    """Paper filtering configuration"""
    min_citation_count: int = 0
    min_year: Optional[int] = None
    max_year: Optional[int] = None
    allowed_venues: Optional[List[str]] = None
    min_relevance_score: float = 0.0

class FilterService:
    """Filter and rank papers"""

    def filter_papers(
        self,
        papers: List[PaperMetadata],
        filter_config: PaperFilter
    ) -> List[PaperMetadata]:
        """Apply filters to paper list"""

        filtered = []
        for paper in papers:
            if self._passes_filters(paper, filter_config):
                filtered.append(paper)

        logger.info(
            "Filtering complete",
            input_count=len(papers),
            output_count=len(filtered),
            filtered_out=len(papers) - len(filtered)
        )

        return filtered

    def _passes_filters(
        self,
        paper: PaperMetadata,
        config: PaperFilter
    ) -> bool:
        """Check if paper passes all filters"""

        # Citation count
        if paper.citation_count < config.min_citation_count:
            return False

        # Year range
        if config.min_year and paper.year:
            if paper.year < config.min_year:
                return False

        if config.max_year and paper.year:
            if paper.year > config.max_year:
                return False

        # Venue allowlist
        if config.allowed_venues:
            # Would need venue info in PaperMetadata
            pass

        return True

    def rank_papers(
        self,
        papers: List[PaperMetadata],
        query: str
    ) -> List[PaperMetadata]:
        """Rank papers by relevance to query

        Uses combination of:
        - Citation count (log scale)
        - Recency (newer is better)
        - Title/abstract similarity to query
        """

        scored_papers = [
            (paper, self._calculate_score(paper, query))
            for paper in papers
        ]

        # Sort by score descending
        scored_papers.sort(key=lambda x: x[1], reverse=True)

        return [paper for paper, score in scored_papers]

    def _calculate_score(
        self,
        paper: PaperMetadata,
        query: str
    ) -> float:
        """Calculate relevance score (0-1)"""

        import math

        # Citation score (log scale, normalized)
        citation_score = min(1.0, math.log10(paper.citation_count + 1) / 3.0)

        # Recency score
        if paper.year:
            current_year = datetime.now().year
            years_old = current_year - paper.year
            recency_score = max(0.0, 1.0 - (years_old / 10.0))
        else:
            recency_score = 0.0

        # Text similarity (simple word overlap for now)
        # Could use sentence embeddings for better results
        text_score = self._text_similarity(
            query,
            f"{paper.title} {paper.abstract or ''}"
        )

        # Weighted combination
        score = (
            0.3 * citation_score +
            0.2 * recency_score +
            0.5 * text_score
        )

        return score

    @staticmethod
    def _text_similarity(query: str, text: str) -> float:
        """Calculate text similarity (simple word overlap)"""
        query_words = set(query.lower().split())
        text_words = set(text.lower().split())

        if not query_words:
            return 0.0

        overlap = len(query_words & text_words)
        return overlap / len(query_words)
```

### 5. Checkpoint Service (`src/services/checkpoint_service.py`)

**Purpose:** Enable resume from interruption

**Implementation:**
```python
import json
from pathlib import Path
from typing import Set

class CheckpointService:
    """Manage pipeline checkpoints"""

    def __init__(self, checkpoint_dir: Path):
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(exist_ok=True)

    def load_processed(self, run_id: str) -> Set[str]:
        """Load set of processed paper IDs"""
        checkpoint_file = self.checkpoint_dir / f"{run_id}.json"

        if not checkpoint_file.exists():
            return set()

        with open(checkpoint_file) as f:
            data = json.load(f)
            return set(data.get("processed_ids", []))

    def save_progress(self, run_id: str, paper_id: str):
        """Save progress checkpoint"""
        checkpoint_file = self.checkpoint_dir / f"{run_id}.json"

        # Load existing
        if checkpoint_file.exists():
            with open(checkpoint_file) as f:
                data = json.load(f)
        else:
            data = {"processed_ids": []}

        # Update
        if paper_id not in data["processed_ids"]:
            data["processed_ids"].append(paper_id)

        # Save atomically
        temp_file = checkpoint_file.with_suffix(".tmp")
        with open(temp_file, 'w') as f:
            json.dump(data, f)
        temp_file.rename(checkpoint_file)

    def clear_checkpoint(self, run_id: str):
        """Clear checkpoint after successful run"""
        checkpoint_file = self.checkpoint_dir / f"{run_id}.json"
        if checkpoint_file.exists():
            checkpoint_file.unlink()
```

## Updated Configuration

```yaml
# config/research_config.yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 50
    extraction_targets: [...]

    # NEW: Filtering configuration
    filters:
      min_citation_count: 5
      min_year: 2020
      allowed_venues:
        - "ACL"
        - "EMNLP"
        - "NAACL"
        - "NeurIPS"
        - "ICML"

settings:
  # NEW: Concurrency settings
  concurrency:
    max_concurrent_downloads: 5
    max_concurrent_conversions: 3
    max_concurrent_llm: 2
    checkpoint_interval: 10

  # NEW: Cache settings
  cache:
    enabled: true
    cache_dir: "./cache"
    ttl_api_hours: 1
    ttl_pdf_days: 7
    ttl_extraction_days: 30
```

## Testing Requirements

### Performance Tests
```python
# tests/performance/test_concurrency.py
async def test_concurrent_vs_sequential():
    """Verify concurrent processing is faster"""
    papers = generate_test_papers(50)

    # Sequential
    start = time.time()
    await process_sequential(papers)
    sequential_time = time.time() - start

    # Concurrent
    start = time.time()
    await process_concurrent(papers)
    concurrent_time = time.time() - start

    # Should be significantly faster
    assert concurrent_time < sequential_time * 0.3

def test_cache_hit_rate():
    """Verify cache effectiveness"""
    # Run twice with same query
    # Second run should have >80% cache hits
```

### Integration Tests
```python
# tests/integration/test_deduplication.py
async def test_duplicate_detection():
    """Test duplicate paper detection"""

async def test_checkpoint_resume():
    """Test resume from checkpoint"""
```

## Acceptance Criteria

### Functional Requirements
- [ ] Concurrent processing working correctly
- [ ] Cache hit rate > 60% on repeated runs
- [ ] Deduplication accuracy > 95%
- [ ] Filters reduce paper count appropriately
- [ ] Checkpoint/resume works correctly
- [ ] No race conditions in concurrent code

### Performance Requirements
- [ ] 50 papers processed in < 30 minutes
- [ ] Memory usage < 2GB
- [ ] Disk cache < 10GB for 1000 papers
- [ ] LLM cost reduction > 40% vs Phase 2

## Deliverables

1. ✅ Concurrent processing engine
2. ✅ Multi-level caching system
3. ✅ Enhanced deduplication
4. ✅ Paper filtering and ranking
5. ✅ Checkpoint/resume capability
6. ✅ Performance benchmarks
7. ✅ Updated documentation

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Race conditions in cache | HIGH | Use atomic operations, locking |
| Memory leaks in workers | MEDIUM | Monitor memory, limit lifetimes |
| Cache corruption | MEDIUM | Atomic writes, checksums |
| False positive duplicates | LOW | Tune similarity thresholds |

## Sign-off

- [ ] Product Owner Approval
- [ ] Technical Lead Approval
- [ ] Performance Review Complete
- [ ] Ready for Development
