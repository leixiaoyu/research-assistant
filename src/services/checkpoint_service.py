"""
Checkpoint service for resumable pipeline processing.

Saves progress after every N papers to enable resume from interruptions.
Uses atomic file writes to prevent corruption.
"""

import json
from pathlib import Path
from typing import Set, Optional, List
import structlog

from src.models.checkpoint import CheckpointConfig, Checkpoint

logger = structlog.get_logger()


class CheckpointService:
    """
    Manage pipeline checkpoints for resume capability.

    Provides atomic saves and efficient lookups.
    """

    def __init__(self, config: CheckpointConfig):
        """
        Initialize checkpoint service.

        Args:
            config: Checkpoint configuration
        """
        self.config = config
        self.checkpoint_dir = Path(config.checkpoint_dir)

        if not config.enabled:
            logger.info("checkpoint_service_disabled")
            return

        # Create checkpoint directory
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "checkpoint_service_initialized",
            checkpoint_dir=str(self.checkpoint_dir),
            interval=config.checkpoint_interval
        )

    def load_checkpoint(self, run_id: str) -> Optional[Checkpoint]:
        """
        Load checkpoint for a run.

        Args:
            run_id: Unique run identifier

        Returns:
            Checkpoint if exists, None otherwise
        """
        if not self.config.enabled:
            return None

        checkpoint_file = self._get_checkpoint_path(run_id)

        if not checkpoint_file.exists():
            logger.debug("no_checkpoint_found", run_id=run_id)
            return None

        try:
            with open(checkpoint_file, 'r') as f:
                data = json.load(f)

            checkpoint = Checkpoint(**data)

            logger.info(
                "checkpoint_loaded",
                run_id=run_id,
                processed=len(checkpoint.processed_paper_ids),
                completed=checkpoint.completed
            )

            return checkpoint

        except Exception as e:
            logger.error(
                "checkpoint_load_error",
                run_id=run_id,
                error=str(e)
            )
            return None

    def save_checkpoint(
        self,
        run_id: str,
        processed_paper_ids: List[str],
        completed: bool = False
    ) -> bool:
        """
        Save checkpoint atomically.

        Args:
            run_id: Unique run identifier
            processed_paper_ids: IDs of papers processed so far
            completed: Whether run is completed

        Returns:
            True if saved successfully
        """
        if not self.config.enabled:
            return True

        try:
            checkpoint = Checkpoint(
                run_id=run_id,
                processed_paper_ids=processed_paper_ids,
                total_processed=len(processed_paper_ids),
                completed=completed
            )

            checkpoint_file = self._get_checkpoint_path(run_id)

            # Atomic write: write to temp file, then rename
            temp_file = checkpoint_file.with_suffix('.tmp')

            with open(temp_file, 'w') as f:
                json.dump(checkpoint.model_dump(mode='json'), f, indent=2, default=str)

            # Atomic rename
            temp_file.rename(checkpoint_file)

            logger.debug(
                "checkpoint_saved",
                run_id=run_id,
                processed=len(processed_paper_ids),
                completed=completed
            )

            return True

        except Exception as e:
            logger.error(
                "checkpoint_save_error",
                run_id=run_id,
                error=str(e)
            )
            return False

    def get_processed_ids(self, run_id: str) -> Set[str]:
        """
        Get set of processed paper IDs for a run.

        Args:
            run_id: Unique run identifier

        Returns:
            Set of paper IDs already processed
        """
        checkpoint = self.load_checkpoint(run_id)

        if checkpoint is None:
            return set()

        return checkpoint.processed_set

    def mark_completed(self, run_id: str) -> bool:
        """
        Mark a run as completed.

        Args:
            run_id: Unique run identifier

        Returns:
            True if marked successfully
        """
        checkpoint = self.load_checkpoint(run_id)

        if checkpoint is None:
            logger.warning("cannot_mark_completed_no_checkpoint", run_id=run_id)
            return False

        return self.save_checkpoint(
            run_id,
            checkpoint.processed_paper_ids,
            completed=True
        )

    def clear_checkpoint(self, run_id: str) -> bool:
        """
        Clear checkpoint for a run.

        Args:
            run_id: Unique run identifier

        Returns:
            True if cleared successfully
        """
        if not self.config.enabled:
            return True

        checkpoint_file = self._get_checkpoint_path(run_id)

        if not checkpoint_file.exists():
            return True

        try:
            checkpoint_file.unlink()
            logger.info("checkpoint_cleared", run_id=run_id)
            return True

        except Exception as e:
            logger.error(
                "checkpoint_clear_error",
                run_id=run_id,
                error=str(e)
            )
            return False

    def list_checkpoints(self) -> List[str]:
        """
        List all checkpoint run IDs.

        Returns:
            List of run IDs with checkpoints
        """
        if not self.config.enabled:
            return []

        try:
            checkpoint_files = self.checkpoint_dir.glob("*.json")
            return [f.stem for f in checkpoint_files]

        except Exception as e:
            logger.error("checkpoint_list_error", error=str(e))
            return []

    def _get_checkpoint_path(self, run_id: str) -> Path:
        """Get checkpoint file path for a run"""
        return self.checkpoint_dir / f"{run_id}.json"
