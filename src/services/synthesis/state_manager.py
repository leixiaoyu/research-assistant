"""State management for cross-topic synthesis.

Handles configuration loading, state tracking, and incremental
synthesis detection.
"""

import hashlib
from pathlib import Path
from typing import Optional, List
import structlog
import yaml

from src.models.cross_synthesis import (
    SynthesisConfig,
    SynthesisState,
)
from src.models.registry import RegistryEntry
from src.services.registry_service import RegistryService

logger = structlog.get_logger()

# Default config path
DEFAULT_CONFIG_PATH = Path("config/synthesis_config.yaml")


class SynthesisStateManager:
    """Manages synthesis configuration and state.

    Provides methods for:
    - Loading and validating synthesis configuration
    - Tracking synthesis state for incremental mode
    - Detecting registry changes
    """

    def __init__(
        self,
        registry_service: RegistryService,
        config: Optional[SynthesisConfig] = None,
        config_path: Optional[Path] = None,
    ):
        """Initialize state manager.

        Args:
            registry_service: Registry service for paper access.
            config: Synthesis configuration (optional, loaded from file if None).
            config_path: Path to synthesis config YAML.
        """
        self.registry = registry_service
        self._config = config
        self._config_path = config_path or DEFAULT_CONFIG_PATH
        self._state: Optional[SynthesisState] = None

    @property
    def config(self) -> SynthesisConfig:
        """Get synthesis configuration, loading if needed."""
        if self._config is None:
            self._config = self.load_config()
        return self._config

    @property
    def state(self) -> Optional[SynthesisState]:
        """Get current synthesis state."""
        return self._state

    @state.setter
    def state(self, value: SynthesisState) -> None:
        """Set synthesis state."""
        self._state = value

    def load_config(self, config_path: Optional[Path] = None) -> SynthesisConfig:
        """Load synthesis configuration from YAML file.

        Args:
            config_path: Path to config file (uses default if None).

        Returns:
            Validated SynthesisConfig.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValueError: If config is invalid.
        """
        path = config_path or self._config_path

        if not path.exists():
            logger.warning(
                "synthesis_config_not_found",
                path=str(path),
            )
            # Return default config with no questions
            return SynthesisConfig()

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            config = SynthesisConfig.model_validate(data)

            logger.info(
                "synthesis_config_loaded",
                path=str(path),
                questions=len(config.questions),
                budget=config.budget_per_synthesis_usd,
            )

            return config

        except yaml.YAMLError as e:
            logger.error("synthesis_config_yaml_error", error=str(e))
            raise ValueError(f"Invalid YAML in synthesis config: {e}")
        except Exception as e:
            logger.error("synthesis_config_load_error", error=str(e))
            raise ValueError(f"Failed to load synthesis config: {e}")

    def calculate_registry_hash(self, entries: List[RegistryEntry]) -> str:
        """Calculate hash of registry state for change detection.

        Args:
            entries: List of registry entries.

        Returns:
            SHA-256 hash of registry entry IDs and timestamps.
        """
        entries_data = sorted(
            [f"{e.paper_id}:{e.processed_at.isoformat()}" for e in entries]
        )
        combined = "|".join(entries_data)
        return hashlib.sha256(combined.encode()).hexdigest()

    def should_skip_incremental(self, entries: List[RegistryEntry]) -> tuple[bool, int]:
        """Check if synthesis should be skipped in incremental mode.

        Args:
            entries: Current registry entries.

        Returns:
            Tuple of (should_skip, new_papers_count).
        """
        if not self.config.incremental_mode:
            return False, 0

        if self._state is None:
            return False, 0

        if self._state.last_registry_hash is None:
            return False, 0

        current_hash = self.calculate_registry_hash(entries)

        if current_hash == self._state.last_registry_hash:
            logger.info("incremental_skip_no_changes")
            return True, 0

        # Count new papers (simplified - just count difference)
        current_count = len(entries)

        # Estimate new papers (not perfectly accurate but useful)
        new_count = max(0, current_count - len(self._state.questions_processed) * 10)

        return False, new_count
