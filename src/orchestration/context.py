"""Pipeline context for shared state across phases.

Phase 5.2: Shared context for pipeline phases.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import structlog

from src.models.config import ResearchConfig
from src.models.paper import PaperMetadata
from src.models.synthesis import ProcessingResult
from src.output.markdown_generator import MarkdownGenerator
from src.output.enhanced_generator import EnhancedMarkdownGenerator

# Conditional type imports
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.config_manager import ConfigManager
    from src.services.discovery_service import DiscoveryService
    from src.services.catalog_service import CatalogService
    from src.services.extraction_service import ExtractionService
    from src.services.registry_service import RegistryService
    from src.services.cross_synthesis_service import CrossTopicSynthesisService
    from src.output.synthesis_engine import SynthesisEngine
    from src.output.delta_generator import DeltaGenerator
    from src.output.cross_synthesis_generator import CrossSynthesisGenerator

logger = structlog.get_logger()


@dataclass
class PipelineContext:
    """Shared context for pipeline phases.

    Manages configuration, services, and accumulated state across phases.
    Services are lazy-initialized to avoid circular dependencies and
    allow phases to work independently.
    """

    # Configuration
    config: ResearchConfig
    config_path: Path
    run_id: str = field(
        default_factory=lambda: datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    )
    started_at: datetime = field(default_factory=datetime.utcnow)

    # Feature flags
    enable_phase2: bool = True
    enable_synthesis: bool = True
    enable_cross_synthesis: bool = True

    # Core services (set during initialization)
    config_manager: Optional["ConfigManager"] = None
    discovery_service: Optional["DiscoveryService"] = None
    catalog_service: Optional["CatalogService"] = None
    extraction_service: Optional["ExtractionService"] = None
    registry_service: Optional["RegistryService"] = None

    # Synthesis services
    synthesis_engine: Optional["SynthesisEngine"] = None
    delta_generator: Optional["DeltaGenerator"] = None

    # Cross-synthesis services
    cross_synthesis_service: Optional["CrossTopicSynthesisService"] = None
    cross_synthesis_generator: Optional["CrossSynthesisGenerator"] = None

    # Markdown generator (varies by phase2 flag)
    md_generator: Optional[Union[MarkdownGenerator, EnhancedMarkdownGenerator]] = None

    # Accumulated state (populated during execution)
    discovered_papers: Dict[str, List[PaperMetadata]] = field(default_factory=dict)
    extraction_results: Dict[str, List[Any]] = field(default_factory=dict)
    topic_processing_results: Dict[str, List[ProcessingResult]] = field(
        default_factory=dict
    )

    # Error tracking
    errors: List[Dict[str, str]] = field(default_factory=list)

    def add_discovered_papers(
        self, topic_slug: str, papers: List[PaperMetadata]
    ) -> None:
        """Add discovered papers for a topic.

        Args:
            topic_slug: Topic identifier
            papers: List of discovered papers
        """
        self.discovered_papers[topic_slug] = papers

    def add_extraction_results(self, topic_slug: str, results: List[Any]) -> None:
        """Add extraction results for a topic.

        Args:
            topic_slug: Topic identifier
            results: List of extracted papers
        """
        self.extraction_results[topic_slug] = results

    def add_processing_results(
        self, topic_slug: str, results: List[ProcessingResult]
    ) -> None:
        """Add processing results for synthesis.

        Args:
            topic_slug: Topic identifier
            results: List of processing results
        """
        self.topic_processing_results[topic_slug] = results

    def add_error(self, phase: str, error: str, topic: Optional[str] = None) -> None:
        """Record an error.

        Args:
            phase: Phase where error occurred
            error: Error message
            topic: Optional topic identifier
        """
        error_entry: Dict[str, str] = {"phase": phase, "error": error}
        if topic:
            error_entry["topic"] = topic
        self.errors.append(error_entry)
        logger.error(
            "pipeline_error",
            phase=phase,
            error=error,
            topic=topic,
        )

    def get_output_path(self, topic_slug: str) -> Path:
        """Get output directory path for a topic.

        Args:
            topic_slug: Topic identifier

        Returns:
            Path to topic output directory
        """
        if self.config_manager:
            return self.config_manager.get_output_path(topic_slug)
        return Path(self.config.settings.output_base_dir) / topic_slug
