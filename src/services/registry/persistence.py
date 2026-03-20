"""Registry persistence layer - handles JSON file I/O with atomic writes and locking.

This module provides safe file operations for the registry with:
- Advisory file locking for concurrent safety
- Atomic writes using temp file + rename pattern
- Backup creation on corruption
- Proper file permissions (0600)
"""

import fcntl
import os
import json
import tempfile
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone
import structlog

from src.models.registry import RegistryState

logger = structlog.get_logger()


class RegistryPersistence:
    """Handles safe persistence of registry state to disk.

    Provides:
    - Advisory file locking to prevent concurrent corruption
    - Atomic writes to prevent partial state corruption
    - Automatic backup creation on parse errors
    - Owner-only file permissions (0600)
    """

    def __init__(self, registry_path: Path):
        """Initialize persistence handler.

        Args:
            registry_path: Path to registry.json file.
        """
        self.registry_path = registry_path
        self._lock_fd: Optional[int] = None

        logger.debug(
            "persistence_initialized",
            path=str(self.registry_path),
        )

    def _ensure_directory(self) -> None:
        """Ensure the registry directory exists with proper permissions."""
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)

        # Set directory permissions to owner-only (0700)
        try:
            os.chmod(self.registry_path.parent, 0o700)
        except OSError as e:
            logger.warning("registry_dir_chmod_failed", error=str(e))

    def _set_file_permissions(self) -> None:
        """Set registry file permissions to owner-only (0600)."""
        if self.registry_path.exists():
            try:
                os.chmod(self.registry_path, 0o600)
            except OSError as e:
                logger.warning("registry_file_chmod_failed", error=str(e))

    def acquire_lock(self) -> bool:
        """Acquire an advisory lock on the registry file.

        Returns:
            True if lock acquired, False otherwise.
        """
        if self._lock_fd is not None:
            return True  # Already locked

        self._ensure_directory()

        try:
            # Create or open lock file
            lock_path = self.registry_path.with_suffix(".lock")
            self._lock_fd = os.open(
                str(lock_path),
                os.O_RDWR | os.O_CREAT,
                0o600,
            )

            # Acquire exclusive lock (blocking)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX)

            logger.debug("registry_lock_acquired", path=str(lock_path))
            return True

        except OSError as e:
            logger.warning("registry_lock_failed", error=str(e))
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            return False

    def release_lock(self) -> None:
        """Release the advisory lock on the registry file."""
        if self._lock_fd is None:
            return

        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            logger.debug("registry_lock_released")
        except OSError as e:
            logger.warning("registry_unlock_failed", error=str(e))
        finally:
            self._lock_fd = None

    def load(self) -> Optional[RegistryState]:
        """Load registry state from disk.

        Creates backup and returns None if file is corrupted.

        Returns:
            Registry state or None if file doesn't exist/is corrupted.
        """
        self._ensure_directory()

        if not self.registry_path.exists():
            logger.info("registry_file_not_found", path=str(self.registry_path))
            return None

        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            state = RegistryState.model_validate(data)

            logger.info(
                "registry_loaded",
                path=str(self.registry_path),
                entries=state.get_entry_count(),
            )
            return state

        except json.JSONDecodeError as e:
            logger.error(
                "registry_parse_error",
                path=str(self.registry_path),
                error=str(e),
            )
            # Create backup and return None
            backup_path = self.registry_path.with_suffix(".json.backup")
            if self.registry_path.exists():
                self.registry_path.rename(backup_path)
                logger.warning(
                    "registry_backed_up",
                    backup=str(backup_path),
                )
            return None

        except Exception as e:
            logger.error(
                "registry_load_error",
                path=str(self.registry_path),
                error=str(e),
            )
            return None

    def save(self, state: RegistryState) -> bool:
        """Save registry state to disk atomically.

        Uses temporary file + rename pattern to prevent corruption.

        Args:
            state: Registry state to save.

        Returns:
            True if save succeeded, False otherwise.
        """
        self._ensure_directory()

        # Update timestamp
        state.updated_at = datetime.now(timezone.utc)

        try:
            # Write to temporary file first
            fd, tmp_path = tempfile.mkstemp(
                dir=self.registry_path.parent,
                prefix=".registry_",
                suffix=".tmp",
            )

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(
                        state.model_dump(mode="json"),
                        f,
                        indent=2,
                        default=str,
                    )
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                os.rename(tmp_path, self.registry_path)

                # Set proper permissions
                self._set_file_permissions()

                logger.debug(
                    "registry_saved",
                    path=str(self.registry_path),
                    entries=state.get_entry_count(),
                )
                return True

            except Exception:
                # Clean up temp file on error
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise

        except Exception as e:
            logger.error(
                "registry_save_error",
                path=str(self.registry_path),
                error=str(e),
            )
            return False
