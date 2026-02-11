"""Hash utilities for Phase 3.5: Extraction Target Hashing.

Provides secure, stable hashing for extraction targets to detect
when requirements change and backfilling is needed.
"""

import hashlib
import json
import re
from typing import List, Optional
import structlog

from src.models.extraction import ExtractionTarget

logger = structlog.get_logger()


def calculate_extraction_hash(targets: Optional[List[ExtractionTarget]]) -> str:
    """Calculate a stable SHA-256 hash of extraction targets.

    The hash is calculated from a normalized, sorted JSON representation
    of the targets to ensure consistent hashing across runs.

    Args:
        targets: List of extraction targets to hash.

    Returns:
        SHA-256 hash prefixed with 'sha256:' for clarity.
    """
    if not targets:
        # Empty targets get a special hash
        return "sha256:empty"

    # Normalize targets to a stable representation
    normalized = []
    for target in sorted(targets, key=lambda t: t.name):
        normalized.append(
            {
                "name": target.name.strip().lower(),
                "description": target.description.strip().lower(),
                "output_format": target.output_format,
                "required": target.required,
            }
        )

    # Create stable JSON representation
    json_str = json.dumps(normalized, sort_keys=True, separators=(",", ":"))

    # Calculate SHA-256
    hash_bytes = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    return f"sha256:{hash_bytes}"


def normalize_title(title: str) -> str:
    """Normalize a paper title for fuzzy matching.

    Normalizes to lowercase, removes punctuation, and collapses whitespace.
    This allows matching titles that differ only in formatting.

    Args:
        title: Original paper title.

    Returns:
        Normalized title string for comparison.
    """
    if not title:
        return ""

    # Convert to lowercase
    normalized = title.lower()

    # Remove all non-alphanumeric characters except spaces
    normalized = re.sub(r"[^a-z0-9\s]", "", normalized)

    # Collapse multiple spaces to single space
    normalized = re.sub(r"\s+", " ", normalized)

    # Strip leading/trailing whitespace
    normalized = normalized.strip()

    return normalized


def calculate_title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity between two titles using character-level comparison.

    Uses a simple Jaccard-like similarity on character trigrams for
    fuzzy matching that's robust to typos and minor variations.

    Args:
        title1: First title (will be normalized).
        title2: Second title (will be normalized).

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    # Normalize both titles
    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)

    # Handle edge cases
    if not norm1 or not norm2:
        return 0.0
    if norm1 == norm2:
        return 1.0

    # Generate character trigrams
    def get_trigrams(s: str) -> set:
        if len(s) < 3:
            return {s}
        return {s[i : i + 3] for i in range(len(s) - 2)}

    trigrams1 = get_trigrams(norm1)
    trigrams2 = get_trigrams(norm2)

    # Calculate Jaccard similarity
    intersection = len(trigrams1 & trigrams2)
    union = len(trigrams1 | trigrams2)

    if union == 0:
        return 0.0

    return intersection / union


def generate_topic_slug(query: str) -> str:
    """Generate a filesystem-safe slug from a research query.

    Creates a normalized, lowercase slug suitable for use as a
    directory name and topic identifier.

    Args:
        query: Research query string.

    Returns:
        Filesystem-safe slug (lowercase alphanumeric + hyphens).
    """
    if not query:
        return "unknown-topic"

    # Convert to lowercase
    slug = query.lower()

    # Replace common operators with hyphens
    slug = re.sub(r"\s+and\s+", "-", slug, flags=re.IGNORECASE)
    slug = re.sub(r"\s+or\s+", "-", slug, flags=re.IGNORECASE)

    # Replace spaces with hyphens
    slug = re.sub(r"\s+", "-", slug)

    # Remove all non-alphanumeric characters except hyphens
    slug = re.sub(r"[^a-z0-9-]", "", slug)

    # Collapse multiple hyphens
    slug = re.sub(r"-+", "-", slug)

    # Strip leading/trailing hyphens
    slug = slug.strip("-")

    # Truncate to reasonable length
    if len(slug) > 64:
        slug = slug[:64].rstrip("-")

    # Ensure we have a valid slug
    if not slug:
        return "unknown-topic"

    return slug
