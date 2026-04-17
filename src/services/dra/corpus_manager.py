"""Corpus manager for ingesting papers from registry into searchable corpus.

This module provides:
- Registry integration for paper ingestion
- Markdown parsing and chunking
- Incremental corpus updates
- Corpus statistics and health checks
"""

import json
import os
import re
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from src.utils.rate_limiter import RateLimiter
from pydantic import BaseModel, Field, field_serializer

from src.models.dra import ChunkType, CorpusChunk, CorpusConfig
from src.services.dra.search_engine import HybridSearchEngine
from src.services.dra.utils import (
    ChunkBuilder,
    SectionParser,
    TokenCounter,
    atomic_write_json,
    compute_checksum,
    set_secure_permissions,
)

# Pattern for valid paper IDs (alphanumeric, hyphen, underscore, dot)
VALID_PAPER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")

logger = structlog.get_logger()


class FreshnessStatus(str, Enum):
    """Freshness status for machine-to-machine interfaces.

    Provides an enum for agents to make decisions without parsing strings.
    """

    FRESH = "fresh"  # Corpus is up-to-date
    STALE = "stale"  # Corpus needs refresh
    EMPTY_CORPUS = "empty_corpus"  # No corpus data, registry has papers
    NO_REGISTRY = "no_registry"  # Registry not found


class FreshnessResult(BaseModel):
    """Result of corpus freshness check.

    Used to determine if corpus needs refresh before agent operations.

    Attributes:
        is_fresh: True if corpus is up-to-date with registry
        status: Machine-readable freshness status enum
        corpus_updated: Last corpus update timestamp (None if no corpus)
        registry_updated: Last registry update timestamp (None if no registry)
        stale_by_seconds: How many seconds the corpus is behind (0 if fresh)
        recommendation: Human-readable recommendation
        papers_to_refresh: Number of papers that need refreshing (if known)
    """

    is_fresh: bool = Field(..., description="Whether corpus is fresh")
    status: FreshnessStatus = Field(
        default=FreshnessStatus.FRESH, description="Machine-readable status"
    )
    corpus_updated: Optional[datetime] = Field(
        default=None, description="Corpus last update time"
    )
    registry_updated: Optional[datetime] = Field(
        default=None, description="Registry last update time"
    )
    stale_by_seconds: float = Field(
        default=0.0, ge=0.0, description="Seconds behind registry"
    )
    recommendation: str = Field(default="", description="Action recommendation")
    papers_to_refresh: int = Field(
        default=0, ge=0, description="Papers needing refresh"
    )


class CorpusStats(BaseModel):
    """Statistics about the corpus.

    Attributes:
        total_papers: Number of papers in corpus
        total_chunks: Number of chunks in corpus
        total_tokens: Total token count
        chunks_by_section: Chunk count by section type
        last_updated: Last update timestamp
    """

    total_papers: int = Field(default=0, ge=0, description="Number of papers")
    total_chunks: int = Field(default=0, ge=0, description="Number of chunks")
    total_tokens: int = Field(default=0, ge=0, description="Total token count")
    chunks_by_section: dict[str, int] = Field(
        default_factory=dict, description="Chunk count by section"
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Last update timestamp"
    )

    @field_serializer("last_updated")
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize datetime to ISO format for JSON."""
        return dt.isoformat()


class PaperRecord(BaseModel):
    """Record of an ingested paper.

    Attributes:
        paper_id: Registry paper ID
        title: Paper title
        checksum: Content checksum for change detection
        chunk_ids: List of chunk IDs for this paper
        ingested_at: Ingestion timestamp
        metadata: Additional metadata
    """

    paper_id: str = Field(..., max_length=256, description="Registry paper ID")
    title: str = Field(..., max_length=500, description="Paper title")
    checksum: str = Field(..., max_length=64, description="SHA-256 checksum")
    chunk_ids: list[str] = Field(default_factory=list, description="Chunk IDs")
    ingested_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Ingestion timestamp"
    )
    metadata: dict = Field(default_factory=dict, description="Additional metadata")

    @field_serializer("ingested_at")
    def serialize_datetime(self, dt: datetime) -> str:
        """Serialize datetime to ISO format for JSON."""
        return dt.isoformat()


class CorpusManager:
    """Manages corpus ingestion and maintenance.

    Integrates with the paper registry to ingest markdown content
    into searchable chunks with embeddings.

    SR-8.7: Supports rate limiting for hosted embedding APIs.
    """

    def __init__(
        self,
        config: Optional[CorpusConfig] = None,
        search_engine: Optional[HybridSearchEngine] = None,
        rate_limiter: Optional["RateLimiter"] = None,
    ):
        """Initialize corpus manager.

        Args:
            config: Corpus configuration
            search_engine: Search engine instance (created if not provided)
            rate_limiter: Optional rate limiter for embedding API (SR-8.7)
        """
        self.config = config or CorpusConfig()
        self.corpus_dir = Path(self.config.corpus_dir)
        self.rate_limiter = rate_limiter  # SR-8.7

        self._search_engine = search_engine
        self._section_parser = SectionParser()
        self._chunk_builder = ChunkBuilder(
            max_tokens=self.config.chunk_max_tokens,
            overlap_tokens=self.config.chunk_overlap_tokens,
        )
        self._token_counter = TokenCounter()

        # Paper tracking
        self._papers: dict[str, PaperRecord] = {}
        self._stats = CorpusStats()

    @property
    def search_engine(self) -> HybridSearchEngine:
        """Get or create search engine.

        SR-8.7: Passes rate_limiter to search engine for embedding API rate limiting.
        """
        if self._search_engine is None:
            from src.models.dra import SearchConfig

            self._search_engine = HybridSearchEngine(
                corpus_config=self.config,
                search_config=SearchConfig(),
                rate_limiter=self.rate_limiter,  # SR-8.7
            )
        return self._search_engine

    @property
    def stats(self) -> CorpusStats:
        """Get current corpus statistics."""
        return self._stats

    @property
    def paper_count(self) -> int:
        """Get number of papers in corpus."""
        return len(self._papers)

    def ingest_paper(
        self,
        paper_id: str,
        title: str,
        markdown_content: str,
        metadata: Optional[dict] = None,
        force: bool = False,
    ) -> list[CorpusChunk]:
        """Ingest a single paper into the corpus.

        Args:
            paper_id: Registry paper ID
            title: Paper title
            markdown_content: Markdown content to ingest
            metadata: Additional metadata
            force: Force re-ingestion even if unchanged

        Returns:
            List of created chunks
        """
        if not markdown_content or not markdown_content.strip():
            logger.warning("ingest_paper_empty_content", paper_id=paper_id)
            return []

        # Check if paper needs update
        content_checksum = compute_checksum(markdown_content)

        if not force and paper_id in self._papers:
            existing = self._papers[paper_id]
            if existing.checksum == content_checksum:
                logger.debug(
                    "paper_unchanged",
                    paper_id=paper_id,
                    checksum=content_checksum[:16],
                )
                # Return existing chunks
                existing_chunks: list[CorpusChunk] = [
                    c
                    for cid in existing.chunk_ids
                    if (c := self.search_engine.get_chunk(cid)) is not None
                ]
                return existing_chunks

        logger.info("ingesting_paper", paper_id=paper_id, title=title[:50])

        # Parse sections
        sections = self._section_parser.parse(markdown_content)

        if not sections:
            # If no sections found, treat entire content as OTHER
            sections = [(ChunkType.OTHER, "", markdown_content)]

        # Build chunks
        chunks = self._chunk_builder.build_chunks(
            paper_id=paper_id,
            title=title,
            sections=sections,
            metadata=metadata,
        )

        if not chunks:
            logger.warning("ingest_paper_no_chunks", paper_id=paper_id)
            return []

        # Index chunks
        self.search_engine.index_chunks(chunks)

        # Record paper
        self._papers[paper_id] = PaperRecord(
            paper_id=paper_id,
            title=title,
            checksum=content_checksum,
            chunk_ids=[c.chunk_id for c in chunks],
            metadata=metadata or {},
        )

        # Update stats
        self._update_stats()

        logger.info(
            "paper_ingested",
            paper_id=paper_id,
            chunks=len(chunks),
            tokens=sum(c.token_count for c in chunks),
        )

        return chunks

    def ingest_from_registry(
        self,
        registry_path: Path,
        paper_ids: Optional[list[str]] = None,
        force: bool = False,
    ) -> int:
        """Ingest papers from registry directory.

        Expected registry structure:
        registry_path/
          papers/
            {paper_id}/
              metadata.json  # Contains title, DOI, etc.
              content.md     # Markdown content

        Args:
            registry_path: Path to registry directory
            paper_ids: Specific paper IDs to ingest (all if None)
            force: Force re-ingestion

        Returns:
            Number of papers ingested
        """
        papers_dir = registry_path / "papers"
        if not papers_dir.exists():
            logger.error("registry_papers_dir_not_found", path=str(papers_dir))
            return 0

        # Resolve papers_dir to prevent traversal during validation
        papers_dir_resolved = papers_dir.resolve()

        ingested_count = 0
        failed_papers: list[tuple[str, str]] = []

        # Build list of paper directories with validation
        if paper_ids is None:
            paper_dirs = list(papers_dir.iterdir())
        else:
            paper_dirs = []
            for pid in paper_ids:
                # Security: Validate paper_id format
                if not VALID_PAPER_ID_PATTERN.match(pid):
                    logger.warning("invalid_paper_id_format", paper_id=pid)
                    failed_papers.append((pid, "Invalid paper_id format"))
                    continue

                paper_path = (papers_dir / pid).resolve()

                # Security: Ensure path stays within papers_dir
                if not str(paper_path).startswith(str(papers_dir_resolved)):
                    logger.warning("path_traversal_attempt", paper_id=pid)
                    failed_papers.append((pid, "Path traversal attempt blocked"))
                    continue

                paper_dirs.append(papers_dir / pid)

        for paper_dir in paper_dirs:
            if not paper_dir.is_dir():
                continue

            paper_id = paper_dir.name

            # Skip if already ingested and not forced
            if not force and paper_id in self._papers:
                continue

            try:
                chunks = self._ingest_registry_paper(paper_dir, force=force)
                if chunks:
                    ingested_count += 1
            except (IOError, json.JSONDecodeError, ValueError) as e:
                logger.error(
                    "paper_ingestion_failed",
                    paper_id=paper_id,
                    error=str(e),
                )
                failed_papers.append((paper_id, str(e)))

        logger.info(
            "registry_ingestion_complete",
            ingested=ingested_count,
            failed=len(failed_papers),
            total_papers=self.paper_count,
        )

        if failed_papers:
            logger.warning(
                "registry_ingestion_failures",
                failures=[{"paper_id": p, "error": e} for p, e in failed_papers],
            )

        return ingested_count

    def _ingest_registry_paper(
        self, paper_dir: Path, force: bool = False
    ) -> list[CorpusChunk]:
        """Ingest a single paper from registry directory.

        Args:
            paper_dir: Path to paper directory
            force: Force re-ingestion

        Returns:
            List of created chunks
        """
        paper_id = paper_dir.name

        # Read metadata
        metadata_path = paper_dir / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
            title = metadata.get("title", paper_id)
        else:
            metadata = {}
            title = paper_id

        # Read content
        content_path = paper_dir / "content.md"
        if not content_path.exists():
            # Try alternative names
            for alt_name in ["paper.md", "extracted.md", "markdown.md"]:
                alt_path = paper_dir / alt_name
                if alt_path.exists():
                    content_path = alt_path
                    break
            else:
                logger.warning(
                    "paper_content_not_found",
                    paper_id=paper_id,
                )
                return []

        with open(content_path, encoding="utf-8") as f:
            content = f.read()

        return self.ingest_paper(
            paper_id=paper_id,
            title=title,
            markdown_content=content,
            metadata=metadata,
            force=force,
        )

    def remove_paper(self, paper_id: str) -> bool:
        """Remove a paper from the corpus.

        Note: This marks the paper as removed but doesn't rebuild indices.
        Call rebuild_indices() to fully remove from search.

        Args:
            paper_id: Paper ID to remove

        Returns:
            True if paper was found and removed
        """
        if paper_id not in self._papers:
            return False

        del self._papers[paper_id]
        self._update_stats()

        logger.info("paper_removed", paper_id=paper_id)
        return True

    def get_paper_info(self, paper_id: str) -> Optional[PaperRecord]:
        """Get paper record by ID.

        Args:
            paper_id: Paper ID

        Returns:
            PaperRecord if found, None otherwise
        """
        return self._papers.get(paper_id)

    def list_papers(self) -> list[PaperRecord]:
        """List all papers in corpus.

        Returns:
            List of paper records
        """
        return list(self._papers.values())

    def rebuild_indices(self) -> None:
        """Rebuild search indices from scratch.

        Use after removing papers or if indices are corrupted.
        """
        logger.info("rebuilding_indices", paper_count=self.paper_count)

        # Collect all chunks from current papers
        all_chunks: list[CorpusChunk] = []
        for paper_record in self._papers.values():
            for chunk_id in paper_record.chunk_ids:
                chunk = self.search_engine.get_chunk(chunk_id)
                if chunk:
                    all_chunks.append(chunk)

        # Reset search engine and re-index
        from src.models.dra import SearchConfig

        self._search_engine = HybridSearchEngine(
            corpus_config=self.config,
            search_config=SearchConfig(),
        )

        if all_chunks:
            self.search_engine.index_chunks(all_chunks)

        self._update_stats()

        logger.info(
            "indices_rebuilt",
            chunks=len(all_chunks),
        )

    def _update_stats(self) -> None:
        """Update corpus statistics."""
        chunks_by_section: dict[str, int] = {}
        total_tokens = 0

        for paper_record in self._papers.values():
            for chunk_id in paper_record.chunk_ids:
                chunk = self.search_engine.get_chunk(chunk_id)
                if chunk:
                    section_key = chunk.section_type.value
                    chunks_by_section[section_key] = (
                        chunks_by_section.get(section_key, 0) + 1
                    )
                    total_tokens += chunk.token_count

        self._stats = CorpusStats(
            total_papers=len(self._papers),
            total_chunks=self.search_engine.corpus_size,
            total_tokens=total_tokens,
            chunks_by_section=chunks_by_section,
            last_updated=datetime.now(UTC),
        )

    def save(self, path: Optional[Path] = None) -> None:
        """Save corpus state to disk with atomic writes.

        Uses atomic write pattern (write to temp -> fsync -> rename) to ensure
        corpus integrity per SR-8.1 security requirement.

        SR-8.1 Permission Model:
        - Directory: 0700 (owner rwx only)
        - Files: 0600 (owner rw only)

        Args:
            path: Directory to save (default from config)
        """
        save_path = path or self.corpus_dir

        # SR-8.1: Create directory with secure permissions (avoid TOCTOU)
        # Using umask prevents the permission window vulnerability
        old_umask = os.umask(0o077)  # Ensure restrictive default
        try:
            save_path.mkdir(parents=True, exist_ok=True)
            # Set directory permissions (mkdir may not honor mode)
            set_secure_permissions(save_path, 0o700)
        finally:
            os.umask(old_umask)

        # Save search engine
        self.search_engine.save(save_path)

        # SR-8.1: Atomic write for paper records with file permissions
        papers_data = {
            pid: record.model_dump(mode="json") for pid, record in self._papers.items()
        }
        papers_path = save_path / "papers.json"
        atomic_write_json(papers_path, papers_data, file_mode=0o600)

        # SR-8.1: Atomic write for stats with file permissions
        stats_path = save_path / "stats.json"
        atomic_write_json(
            stats_path, self._stats.model_dump(mode="json"), file_mode=0o600
        )

        logger.info(
            "corpus_saved",
            path=str(save_path),
            papers=len(self._papers),
        )

    def load(self, path: Optional[Path] = None) -> None:
        """Load corpus state from disk.

        Args:
            path: Directory to load from (default from config)
        """
        load_path = path or self.corpus_dir

        if not load_path.exists():
            logger.warning("corpus_path_not_found", path=str(load_path))
            return

        # Load search engine
        self.search_engine.load(load_path)

        # Load paper records using Pydantic v2 model_validate
        papers_path = load_path / "papers.json"
        if papers_path.exists():
            with open(papers_path) as f:
                papers_data = json.load(f)
            self._papers = {
                pid: PaperRecord.model_validate(data)
                for pid, data in papers_data.items()
            }

        # Load stats using Pydantic v2 model_validate
        stats_path = load_path / "stats.json"
        if stats_path.exists():
            with open(stats_path) as f:
                stats_data = json.load(f)
            self._stats = CorpusStats.model_validate(stats_data)

        logger.info(
            "corpus_loaded",
            path=str(load_path),
            papers=len(self._papers),
            chunks=self.search_engine.corpus_size,
        )

    def health_check(self) -> dict:
        """Perform corpus health check.

        Returns:
            Dict with health status and any issues
        """
        issues: list[str] = []

        # Check paper/chunk consistency
        for paper_id, record in self._papers.items():
            for chunk_id in record.chunk_ids:
                if self.search_engine.get_chunk(chunk_id) is None:
                    issues.append(f"Missing chunk {chunk_id} for paper {paper_id}")

        # Check search engine readiness
        if not self.search_engine.is_ready and self.paper_count > 0:
            issues.append("Search engine not ready but papers exist")

        # Check minimum corpus size
        if self.paper_count < 10:
            issues.append(
                f"Corpus too small ({self.paper_count} papers, recommend 50+)"
            )

        return {
            "healthy": len(issues) == 0,
            "paper_count": self.paper_count,
            "chunk_count": self.search_engine.corpus_size,
            "search_ready": self.search_engine.is_ready,
            "issues": issues,
        }

    def check_freshness(
        self,
        registry_path: Path,
        deep_check: bool = False,
        verify_checksums: bool = False,
    ) -> FreshnessResult:
        """Check if corpus is fresh relative to the registry.

        Compares the corpus last_updated timestamp against the registry's
        most recent modification time to determine if the corpus needs
        refreshing before agent operations.

        Performance Optimization (SR-8.1):
            By default, uses a fast timestamp-based check that avoids O(N)
            stat() calls. Set deep_check=True to perform per-paper validation
            when precise counts are needed.

        Containerized Environment Support:
            File modification times (mtime) can be unreliable in containers,
            Docker volumes, or when files are restored from backup. Set
            verify_checksums=True to use content-based change detection
            instead of mtime. This is slower but more reliable.

        Note:
            This check is not atomic. If the registry is being modified
            concurrently (e.g., by another process ingesting papers), results
            may be inconsistent. For production use with concurrent writers,
            consider a registry-level lock or version counter.

        Args:
            registry_path: Path to the registry directory
            deep_check: If True, perform per-paper freshness validation (slower)
            verify_checksums: If True, use checksum comparison instead of mtime
                for modified paper detection (recommended for containers)

        Returns:
            FreshnessResult with freshness status and recommendation
        """
        papers_dir = registry_path / "papers"

        # Check if registry exists
        if not papers_dir.exists():
            logger.warning("freshness_check_no_registry", path=str(registry_path))
            return FreshnessResult(
                is_fresh=True,  # No registry = nothing to refresh from
                status=FreshnessStatus.NO_REGISTRY,
                corpus_updated=self._stats.last_updated if self._papers else None,
                registry_updated=None,
                recommendation="Registry not found. No refresh needed.",
            )

        # Fast path: Get registry directory mtime for quick comparison
        # This avoids O(N) stat() calls for the common "already fresh" case
        try:
            registry_dir_mtime = datetime.fromtimestamp(
                papers_dir.stat().st_mtime, tz=UTC
            )
        except OSError:
            registry_dir_mtime = None

        corpus_updated = self._stats.last_updated if self._papers else None

        # Short-circuit: If corpus is newer than registry dir and no deep check needed
        if (
            not deep_check
            and corpus_updated is not None
            and registry_dir_mtime is not None
            and corpus_updated >= registry_dir_mtime
        ):
            logger.debug(
                "freshness_short_circuit",
                corpus_updated=corpus_updated.isoformat(),
                registry_dir_mtime=registry_dir_mtime.isoformat(),
            )
            return FreshnessResult(
                is_fresh=True,
                status=FreshnessStatus.FRESH,
                corpus_updated=corpus_updated,
                registry_updated=registry_dir_mtime,
                stale_by_seconds=0.0,
                recommendation="Corpus is up-to-date with registry.",
                papers_to_refresh=0,
            )

        # Full check: Iterate through papers for precise status
        registry_updated: Optional[datetime] = None
        papers_to_refresh = 0
        paper_ids_in_corpus = set(self._papers.keys())  # O(1) lookups

        for paper_dir in papers_dir.iterdir():
            if not paper_dir.is_dir():
                continue

            # Check metadata.json or content.md modification time
            for check_file in ["metadata.json", "content.md"]:
                file_path = paper_dir / check_file
                if file_path.exists():
                    mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC)
                    if registry_updated is None or mtime > registry_updated:
                        registry_updated = mtime
                    break

            # Count papers not in corpus or modified since ingestion
            paper_id = paper_dir.name
            if paper_id not in paper_ids_in_corpus:
                papers_to_refresh += 1
            else:
                # Check if paper was modified after ingestion
                paper_record = self._papers[paper_id]
                content_path = paper_dir / "content.md"
                if content_path.exists():
                    if verify_checksums:
                        # Checksum-based: More reliable for containers/Docker
                        try:
                            content = content_path.read_text(encoding="utf-8")
                            current_checksum = compute_checksum(content)
                            if current_checksum != paper_record.checksum:
                                papers_to_refresh += 1
                        except (OSError, UnicodeDecodeError):
                            # If we can't read the file, assume it needs refresh
                            papers_to_refresh += 1
                    else:
                        # mtime-based: Faster but unreliable in containers
                        content_mtime = datetime.fromtimestamp(
                            content_path.stat().st_mtime, tz=UTC
                        )
                        if content_mtime > paper_record.ingested_at:
                            papers_to_refresh += 1

        # No papers in registry
        if registry_updated is None:
            return FreshnessResult(
                is_fresh=True,
                status=FreshnessStatus.FRESH,
                corpus_updated=corpus_updated,
                registry_updated=None,
                recommendation="Registry is empty. No refresh needed.",
            )

        # Corpus is empty - definitely stale if registry has papers
        if corpus_updated is None:
            stale_seconds = (datetime.now(UTC) - registry_updated).total_seconds()
            return FreshnessResult(
                is_fresh=False,
                status=FreshnessStatus.EMPTY_CORPUS,
                corpus_updated=None,
                registry_updated=registry_updated,
                stale_by_seconds=max(0.0, stale_seconds),
                recommendation="Corpus is empty. Run ensure_fresh() to build corpus.",
                papers_to_refresh=papers_to_refresh,
            )

        # Compare timestamps
        if registry_updated > corpus_updated:
            stale_seconds = (registry_updated - corpus_updated).total_seconds()
            return FreshnessResult(
                is_fresh=False,
                status=FreshnessStatus.STALE,
                corpus_updated=corpus_updated,
                registry_updated=registry_updated,
                stale_by_seconds=stale_seconds,
                recommendation=f"Corpus is stale by {stale_seconds:.0f}s. "
                f"{papers_to_refresh} paper(s) need refreshing.",
                papers_to_refresh=papers_to_refresh,
            )

        # Corpus is fresh
        return FreshnessResult(
            is_fresh=True,
            status=FreshnessStatus.FRESH,
            corpus_updated=corpus_updated,
            registry_updated=registry_updated,
            stale_by_seconds=0.0,
            recommendation="Corpus is up-to-date with registry.",
            papers_to_refresh=0,
        )

    def ensure_fresh(
        self,
        registry_path: Path,
        auto_refresh: bool = True,
        force: bool = False,
        verify_checksums: bool = False,
    ) -> FreshnessResult:
        """Ensure corpus is fresh before agent operations.

        This is the main entry point for agent startup. It checks freshness
        and optionally triggers an incremental refresh if the corpus is stale.

        Args:
            registry_path: Path to the registry directory
            auto_refresh: If True, automatically refresh stale corpus
            force: If True, refresh even if corpus appears fresh
            verify_checksums: If True, use checksum comparison instead of mtime
                for modified paper detection (recommended for containers)

        Returns:
            FreshnessResult with final freshness status
        """
        # Check current freshness
        result = self.check_freshness(registry_path, verify_checksums=verify_checksums)

        logger.info(
            "freshness_check_result",
            is_fresh=result.is_fresh,
            stale_by_seconds=result.stale_by_seconds,
            papers_to_refresh=result.papers_to_refresh,
        )

        # If fresh and not forced, return immediately
        if result.is_fresh and not force:
            return result

        # If auto_refresh is disabled, just return the stale result
        if not auto_refresh:
            logger.warning(
                "corpus_stale_no_auto_refresh",
                stale_by_seconds=result.stale_by_seconds,
                papers_to_refresh=result.papers_to_refresh,
            )
            return result

        # Perform incremental refresh
        logger.info(
            "corpus_auto_refresh_starting",
            papers_to_refresh=result.papers_to_refresh,
        )

        ingested = self.ingest_from_registry(registry_path, force=force)

        logger.info(
            "corpus_auto_refresh_complete",
            papers_ingested=ingested,
        )

        # Return updated freshness result
        return FreshnessResult(
            is_fresh=True,
            status=FreshnessStatus.FRESH,
            corpus_updated=self._stats.last_updated,
            registry_updated=result.registry_updated,
            stale_by_seconds=0.0,
            recommendation=f"Corpus refreshed. {ingested} paper(s) ingested.",
            papers_to_refresh=0,
        )
