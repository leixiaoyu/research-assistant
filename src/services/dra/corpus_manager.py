"""Corpus manager for ingesting papers from registry into searchable corpus.

This module provides:
- Registry integration for paper ingestion
- Markdown parsing and chunking
- Incremental corpus updates
- Corpus statistics and health checks
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import structlog
from pydantic import BaseModel, Field

from src.models.dra import ChunkType, CorpusChunk, CorpusConfig
from src.services.dra.search_engine import HybridSearchEngine
from src.services.dra.utils import (
    ChunkBuilder,
    SectionParser,
    TokenCounter,
    compute_checksum,
)

# Pattern for valid paper IDs (alphanumeric, hyphen, underscore, dot)
VALID_PAPER_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")

logger = structlog.get_logger()


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

    def to_dict(self) -> dict:
        """Convert to dictionary (JSON-serializable)."""
        data = self.model_dump()
        data["last_updated"] = self.last_updated.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "CorpusStats":
        """Create from dictionary."""
        if data.get("last_updated") and isinstance(data["last_updated"], str):
            data = data.copy()
            data["last_updated"] = datetime.fromisoformat(data["last_updated"])
        return cls.model_validate(data)


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

    def to_dict(self) -> dict:
        """Convert to dictionary (JSON-serializable)."""
        data = self.model_dump()
        data["ingested_at"] = self.ingested_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PaperRecord":
        """Create from dictionary."""
        if data.get("ingested_at") and isinstance(data["ingested_at"], str):
            data = data.copy()
            data["ingested_at"] = datetime.fromisoformat(data["ingested_at"])
        return cls.model_validate(data)


class CorpusManager:
    """Manages corpus ingestion and maintenance.

    Integrates with the paper registry to ingest markdown content
    into searchable chunks with embeddings.
    """

    def __init__(
        self,
        config: Optional[CorpusConfig] = None,
        search_engine: Optional[HybridSearchEngine] = None,
    ):
        """Initialize corpus manager.

        Args:
            config: Corpus configuration
            search_engine: Search engine instance (created if not provided)
        """
        self.config = config or CorpusConfig()
        self.corpus_dir = Path(self.config.corpus_dir)

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
        """Get or create search engine."""
        if self._search_engine is None:
            from src.models.dra import SearchConfig

            self._search_engine = HybridSearchEngine(
                corpus_config=self.config,
                search_config=SearchConfig(),
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
        """Save corpus state to disk.

        Args:
            path: Directory to save (default from config)
        """
        save_path = path or self.corpus_dir
        save_path.mkdir(parents=True, exist_ok=True)

        # Save search engine
        self.search_engine.save(save_path)

        # Save paper records
        papers_data = {pid: record.to_dict() for pid, record in self._papers.items()}
        with open(save_path / "papers.json", "w") as f:
            json.dump(papers_data, f, indent=2)

        # Save stats
        with open(save_path / "stats.json", "w") as f:
            json.dump(self._stats.to_dict(), f, indent=2)

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

        # Load paper records
        papers_path = load_path / "papers.json"
        if papers_path.exists():
            with open(papers_path) as f:
                papers_data = json.load(f)
            self._papers = {
                pid: PaperRecord.from_dict(data) for pid, data in papers_data.items()
            }

        # Load stats
        stats_path = load_path / "stats.json"
        if stats_path.exists():
            with open(stats_path) as f:
                stats_data = json.load(f)
            self._stats = CorpusStats.from_dict(stats_data)

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
