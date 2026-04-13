"""Venue quality score repository.

This module provides venue reputation scoring for paper quality assessment.
Loads venue scores from YAML and provides normalized lookups.

Usage:
    from src.services.venue_repository import YamlVenueRepository

    # Default: loads from src/data/venue_scores.yaml
    repo = YamlVenueRepository()
    score = repo.get_score("neurips")  # Returns 0.0-1.0

    # Custom path and default
    repo = YamlVenueRepository(
        yaml_path=Path("custom_venues.yaml"),
        default_score=0.6
    )
"""

import re
from pathlib import Path
from typing import Dict, Optional, Protocol

import structlog
import yaml

logger = structlog.get_logger()


class VenueRepository(Protocol):
    """Protocol for venue score repositories.

    Defines the interface for venue quality scoring systems.
    """

    def get_score(self, venue: str) -> float:
        """Get normalized score (0-1) for a venue.

        Args:
            venue: Venue name (case-insensitive)

        Returns:
            Normalized score between 0.0 and 1.0
        """
        ...  # pragma: no cover

    def get_default_score(self) -> float:
        """Get the default score for unknown venues.

        Returns:
            Default score between 0.0 and 1.0
        """
        ...  # pragma: no cover

    def reload(self) -> None:
        """Reload venue data from source.

        Forces a fresh load, clearing any cached data.
        """
        ...  # pragma: no cover


class YamlVenueRepository:
    """YAML-based venue score repository.

    Loads venue quality scores from a YAML file, normalizes them to 0-1 scale,
    and provides cached lookups with advanced venue name normalization.

    Normalization:
    - Lowercase conversion
    - Digit removal
    - Special character removal
    - Common word removal (proceedings, conference, journal, etc.)

    Matching Priority:
    1. Exact match on normalized name
    2. Substring match in normalized name

    Thread Safety:
        This class is not thread-safe. For concurrent access, create separate
        instances or use external synchronization.

    Attributes:
        yaml_path: Path to venue scores YAML file
        default_score: Score for unknown venues (0-1 scale)
    """

    def __init__(
        self,
        yaml_path: Optional[Path] = None,
        default_score: float = 0.5,
    ) -> None:
        """Initialize venue repository.

        Args:
            yaml_path: Path to YAML file. Defaults to src/data/venue_scores.yaml
            default_score: Score for unknown venues (0-1 scale). Defaults to 0.5

        Raises:
            ValueError: If default_score not in [0.0, 1.0]
        """
        if not 0.0 <= default_score <= 1.0:
            raise ValueError(
                f"default_score must be in [0.0, 1.0], got {default_score}"
            )

        # Default to project's venue_scores.yaml
        if yaml_path is None:
            project_root = Path(__file__).parent.parent.parent
            yaml_path = project_root / "src" / "data" / "venue_scores.yaml"

        # Security: Resolve path and validate it exists
        self._yaml_path = yaml_path.resolve()
        self._default_score = default_score

        # Lazy-loaded cache
        self._venues: Optional[Dict[str, float]] = None

        logger.info(
            "venue_repository_initialized",
            yaml_path=str(self._yaml_path),
            default_score=default_score,
        )

    def get_score(self, venue: str) -> float:
        """Get normalized score (0-1) for a venue.

        Lazy-loads venue data on first call. Uses advanced normalization
        and tries exact match first, then substring matching.

        Args:
            venue: Venue name (case-insensitive)

        Returns:
            Normalized score between 0.0 and 1.0
        """
        if not venue:
            return self._default_score

        # Lazy load
        if self._venues is None:
            self._venues = self._load_venues()

        # Normalize venue name
        normalized = self._normalize_venue(venue)

        # Try exact match first
        if normalized in self._venues:
            return self._venues[normalized]

        # Try substring match (prefer longest match)
        # Only match when input venue CONTAINS a known venue key
        # Prevents "nature" (1.0) from wrongly matching "nature communications"
        best_match: Optional[str] = None
        best_length = 0

        for venue_key in self._venues.keys():
            if venue_key in normalized:
                if len(venue_key) > best_length:
                    best_match = venue_key
                    best_length = len(venue_key)

        if best_match:
            logger.debug(
                "venue_substring_match",
                venue=venue,
                normalized=normalized,
                matched_key=best_match,
                score=self._venues[best_match],
            )
            return self._venues[best_match]

        # No match found
        logger.debug(
            "venue_not_found",
            venue=venue,
            normalized=normalized,
            using_default=self._default_score,
        )
        return self._default_score

    def get_default_score(self) -> float:
        """Get the default score for unknown venues.

        Returns:
            Default score between 0.0 and 1.0
        """
        return self._default_score

    def reload(self) -> None:
        """Reload venue data from YAML file.

        Forces a fresh load, clearing the cached data.
        Use after modifying the YAML file to pick up changes.
        """
        logger.info("venue_repository_reload", yaml_path=str(self._yaml_path))
        self._venues = None
        # Trigger reload by calling get_score which lazy-loads
        # This ensures reload() works even when called after initialization
        self._venues = self._load_venues()

    def _normalize_venue(self, venue: str) -> str:
        """Normalize venue name for matching.

        Normalization steps:
        1. Lowercase
        2. Remove digits
        3. Remove special characters (keep spaces and hyphens)
        4. Remove common words
        5. Strip and collapse whitespace

        Args:
            venue: Raw venue name

        Returns:
            Normalized venue name
        """
        # Lowercase
        normalized = venue.lower()

        # Remove digits
        normalized = re.sub(r"\d+", "", normalized)

        # Remove special characters (keep spaces, hyphens, apostrophes)
        normalized = re.sub(r"[^\w\s\-']", " ", normalized)

        # Remove common words
        common_words = {
            "proceedings",
            "conference",
            "journal",
            "international",
            "workshop",
            "symposium",
            "transactions",
            "annual",
            "of",
            "the",
            "on",
            "for",
            "and",
            "in",
        }

        words = normalized.split()
        filtered_words = [w for w in words if w not in common_words]
        normalized = " ".join(filtered_words)

        # Strip and collapse whitespace
        normalized = " ".join(normalized.split())

        return normalized.strip()

    def _load_venues(self) -> Dict[str, float]:
        """Load and normalize venue scores from YAML.

        Reads the YAML file, extracts venue scores (0-30 scale),
        and normalizes them to 0-1 by dividing by 30.0.

        Returns:
            Dict mapping normalized venue names to scores (0-1)

        Notes:
            - Returns empty dict if file not found or parse error
            - Logs warnings for errors but continues gracefully
        """
        try:
            # Security: Check path exists and is a file
            if not self._yaml_path.exists():
                logger.warning(
                    "venue_yaml_not_found",
                    path=str(self._yaml_path),
                    using_empty_dict=True,
                )
                return {}

            if not self._yaml_path.is_file():
                logger.warning(
                    "venue_yaml_not_file",
                    path=str(self._yaml_path),
                    using_empty_dict=True,
                )
                return {}

            # Load YAML
            with open(self._yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                logger.warning(
                    "venue_yaml_invalid_format",
                    path=str(self._yaml_path),
                    expected="dict",
                    got=type(data).__name__,
                )
                return {}

            # Extract venues (expect 0-30 scale in YAML)
            venues_raw = data.get("venues", {})
            if not isinstance(venues_raw, dict):
                logger.warning(
                    "venue_yaml_missing_venues",
                    path=str(self._yaml_path),
                    using_empty_dict=True,
                )
                return {}

            # Normalize names and scores
            venues_normalized: Dict[str, float] = {}
            for venue_name, score in venues_raw.items():
                # Normalize venue name
                normalized_name = self._normalize_venue(venue_name)

                # Normalize score from 0-30 to 0-1
                if isinstance(score, (int, float)):
                    normalized_score = max(0.0, min(1.0, score / 30.0))
                    venues_normalized[normalized_name] = normalized_score
                else:
                    logger.warning(
                        "venue_yaml_invalid_score",
                        venue=venue_name,
                        score=score,
                        expected="int or float",
                    )

            logger.info(
                "venue_data_loaded",
                venue_count=len(venues_normalized),
                yaml_path=str(self._yaml_path),
            )

            return venues_normalized

        except yaml.YAMLError as e:
            logger.error(
                "venue_yaml_parse_error",
                path=str(self._yaml_path),
                error=str(e),
                using_empty_dict=True,
            )
            return {}

        except Exception as e:
            logger.error(
                "venue_data_load_error",
                path=str(self._yaml_path),
                error=str(e),
                error_type=type(e).__name__,
                using_empty_dict=True,
            )
            return {}
