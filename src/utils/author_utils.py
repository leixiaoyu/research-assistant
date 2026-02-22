"""Utility functions for author data handling.

This module provides utilities for normalizing author data from various
formats into a consistent List[str] representation. This is needed because
author data can come in different forms:
- List[dict] from serialized Author objects (via model_dump)
- List[str] when already normalized
- Single string for single-author papers
- None/empty when no authors specified
"""

from typing import Any, List


def normalize_authors(authors: Any) -> List[str]:
    """Convert authors from various formats to List[str].

    Handles:
    - List[dict] with 'name' key (from serialized Author objects)
    - List[str] (already normalized)
    - Single string
    - None/empty

    Args:
        authors: Author data in various formats.

    Returns:
        List of author name strings.

    Examples:
        >>> normalize_authors([{"name": "John Doe", "authorId": "123"}])
        ['John Doe']
        >>> normalize_authors(["Jane Smith"])
        ['Jane Smith']
        >>> normalize_authors("Single Author")
        ['Single Author']
        >>> normalize_authors(None)
        []
    """
    if not authors:
        return []

    result: List[str] = []

    if isinstance(authors, list):
        for a in authors:
            if isinstance(a, dict):
                # Extract 'name' key, fallback to str representation
                name = a.get("name")
                result.append(name if name is not None else str(a))
            else:
                result.append(str(a))
    elif isinstance(authors, str):
        result.append(authors)

    return result
