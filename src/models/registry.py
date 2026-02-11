"""Registry data models for Phase 3.5: Global Paper Identity.

This module defines the data structures for:
- Registry entries (canonical paper identity)
- Processing actions (full process, backfill, skip, map only)
- Identity resolution results
"""

import re
import uuid
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, ConfigDict


class ProcessingAction(str, Enum):
    """Actions to take when processing a paper (Phase 3.5).

    Determines whether a paper needs full processing, partial backfill,
    topic affiliation only, or can be skipped entirely.
    """

    FULL_PROCESS = "full_process"  # New paper: full acquisition and extraction
    BACKFILL = "backfill"  # Existing paper with changed extraction targets
    MAP_ONLY = "map_only"  # Already processed, just add topic affiliation
    SKIP = "skip"  # Already processed for this topic, nothing to do


class RegistryEntry(BaseModel):
    """A single paper entry in the global registry.

    Tracks the canonical identity, all known identifiers, extraction state,
    and topic affiliations for cross-run deduplication and backfilling.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "paper_id": "550e8400-e29b-41d4-a716-446655440000",
                "identifiers": {
                    "doi": "10.1234/example",
                    "arxiv": "2301.12345",
                    "semantic_scholar": "abc123",
                },
                "title_normalized": "attention is all you need",
                "processed_at": "2025-01-24T10:00:00Z",
                "extraction_target_hash": "sha256:abc123...",
                "topic_affiliations": ["transformer-models", "nlp-research"],
                "pdf_path": "/data/pdfs/2301.12345.pdf",
                "markdown_path": "/data/markdown/2301.12345.md",
            }
        }
    )

    paper_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Canonical UUID for this paper (system-generated)",
    )

    identifiers: Dict[str, str] = Field(
        default_factory=dict,
        description="External identifiers: doi, arxiv, semantic_scholar",
    )

    title_normalized: str = Field(
        ...,
        min_length=1,
        description="Normalized title for fuzzy matching (lowercase, alphanumeric)",
    )

    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the paper was last fully processed",
    )

    extraction_target_hash: str = Field(
        ...,
        description="SHA-256 hash of extraction targets used for last extraction",
    )

    topic_affiliations: List[str] = Field(
        default_factory=list,
        description="List of topic slugs this paper is affiliated with",
    )

    # Paths to processed artifacts (for backfill reuse)
    pdf_path: Optional[str] = Field(
        default=None,
        description="Path to downloaded PDF (reused in backfill)",
    )
    markdown_path: Optional[str] = Field(
        default=None,
        description="Path to converted markdown (reused in backfill)",
    )

    # Metadata snapshot for synthesis without re-discovery
    metadata_snapshot: Optional[Dict] = Field(
        default=None,
        description="Serialized PaperMetadata for reference",
    )

    @field_validator("identifiers")
    @classmethod
    def validate_identifiers(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate identifier formats."""
        validated = {}

        for key, value in v.items():
            if not value or not value.strip():
                continue  # Skip empty values

            value = value.strip()

            # Validate DOI format
            if key == "doi":
                # DOI format: 10.XXXX/...
                if not re.match(r"^10\.\d{4,}/.*$", value):
                    raise ValueError(f"Invalid DOI format: {value}")

            # Validate ArXiv ID format
            elif key == "arxiv":
                # ArXiv: YYMM.NNNNN or category/YYMMNNN
                if not re.match(r"^(\d{4}\.\d{4,5}|[a-z-]+/\d{7})$", value):
                    raise ValueError(f"Invalid ArXiv ID format: {value}")

            # Validate Semantic Scholar ID (alphanumeric, 40 chars hex)
            elif key == "semantic_scholar":
                if not re.match(r"^[a-f0-9]{40}$", value):
                    # Allow other formats too (some are shorter)
                    if not re.match(r"^[a-zA-Z0-9_-]+$", value):
                        raise ValueError(f"Invalid Semantic Scholar ID format: {value}")

            validated[key] = value

        return validated

    @field_validator("topic_affiliations")
    @classmethod
    def validate_topic_affiliations(cls, v: List[str]) -> List[str]:
        """Validate topic slugs are filesystem-safe."""
        validated = []
        for slug in v:
            if not slug:
                continue
            # Topic slugs must be alphanumeric + hyphen only
            if not re.match(r"^[a-z0-9-]+$", slug):
                raise ValueError(
                    f"Invalid topic slug: {slug} "
                    "(must be lowercase alphanumeric + hyphen)"
                )
            validated.append(slug)
        return validated

    def add_topic_affiliation(self, topic_slug: str) -> bool:
        """Add a topic affiliation if not already present.

        Args:
            topic_slug: Sanitized topic slug to add.

        Returns:
            True if added, False if already present.
        """
        if topic_slug not in self.topic_affiliations:
            self.topic_affiliations.append(topic_slug)
            return True
        return False


class IdentityMatch(BaseModel):
    """Result of identity resolution against the registry.

    Contains the matched entry (if found) and the match method used.
    """

    matched: bool = Field(..., description="Whether a match was found")
    entry: Optional[RegistryEntry] = Field(
        default=None, description="Matched registry entry"
    )
    match_method: Optional[str] = Field(
        default=None,
        description="How the match was made: doi, arxiv, semantic_scholar, title",
    )
    similarity_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Title similarity score if matched by title",
    )


class RegistryState(BaseModel):
    """Complete registry state for persistence.

    Contains all registry entries and metadata about the registry itself.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(
        default="1.0",
        description="Registry format version for migration support",
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the registry was first created",
    )

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the registry was last modified",
    )

    entries: Dict[str, RegistryEntry] = Field(
        default_factory=dict,
        description="Map of paper_id to RegistryEntry",
    )

    # Index for fast DOI lookup
    doi_index: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of DOI to paper_id for fast lookup",
    )

    # Index for fast provider ID lookup
    provider_id_index: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of provider:id to paper_id (e.g., arxiv:2301.12345)",
    )

    def add_entry(self, entry: RegistryEntry) -> None:
        """Add or update an entry and rebuild indexes.

        Args:
            entry: Registry entry to add.
        """
        self.entries[entry.paper_id] = entry
        self.updated_at = datetime.now(timezone.utc)

        # Update DOI index
        if "doi" in entry.identifiers:
            self.doi_index[entry.identifiers["doi"]] = entry.paper_id

        # Update provider ID index
        for provider in ["arxiv", "semantic_scholar"]:
            if provider in entry.identifiers:
                key = f"{provider}:{entry.identifiers[provider]}"
                self.provider_id_index[key] = entry.paper_id

    def get_entry_count(self) -> int:
        """Return the number of entries in the registry."""
        return len(self.entries)
