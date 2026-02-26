"""Abstract base class for pipeline phases.

Phase 5.2: Defines the interface for all pipeline phases.
"""

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

import structlog

from src.orchestration.context import PipelineContext

T = TypeVar("T")


class PipelinePhase(ABC, Generic[T]):
    """Abstract base class for pipeline phases.

    Each phase handles a specific part of the research pipeline workflow.
    Phases receive a shared context for accessing services and state.

    Type parameter T represents the return type of the execute method.
    """

    def __init__(self, context: PipelineContext) -> None:
        """Initialize the phase with shared context.

        Args:
            context: Shared pipeline context
        """
        self.context = context
        self.logger = structlog.get_logger().bind(phase=self.name)

    @property
    @abstractmethod
    def name(self) -> str:
        """Phase name for logging and identification.

        Returns:
            Human-readable phase name
        """
        pass  # pragma: no cover - abstract method

    @abstractmethod
    async def execute(self) -> T:
        """Execute the phase and return results.

        Returns:
            Phase-specific result type

        Raises:
            Exception: If phase execution fails
        """
        pass  # pragma: no cover - abstract method

    def is_enabled(self) -> bool:
        """Check if phase should run based on context configuration.

        Override in subclasses for conditional execution.

        Returns:
            True if phase should execute, False to skip
        """
        return True

    async def run(self) -> T:
        """Run the phase with logging and error handling.

        This is the main entry point for phase execution.
        Wraps execute() with standard logging.

        Returns:
            Phase-specific result type
        """
        if not self.is_enabled():
            self.logger.info("phase_skipped", reason="disabled by configuration")
            return self._get_default_result()

        self.logger.info("phase_starting")

        try:
            result = await self.execute()
            self.logger.info("phase_completed")
            return result
        except Exception as e:
            self.logger.exception("phase_failed", error=str(e))
            self.context.add_error(self.name, str(e))
            raise

    def _get_default_result(self) -> T:
        """Get default result when phase is skipped.

        Override in subclasses to provide meaningful defaults.

        Returns:
            Default result for skipped phase
        """
        return None  # type: ignore
