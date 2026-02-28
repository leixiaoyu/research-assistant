"""Pipeline result data structure.

Phase 5.2: Extracted from research_pipeline.py.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.models.cross_synthesis import CrossTopicSynthesisReport


@dataclass
class PipelineResult:
    """Result of a pipeline run.

    Aggregates statistics and output from all pipeline phases.
    """

    topics_processed: int = 0
    topics_failed: int = 0
    papers_discovered: int = 0
    papers_processed: int = 0
    papers_with_extraction: int = 0
    total_tokens_used: int = 0
    total_cost_usd: float = 0.0
    output_files: List[str] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    # Phase 3.7: Cross-topic synthesis report
    cross_synthesis_report: Optional[CrossTopicSynthesisReport] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        result = {
            "topics_processed": self.topics_processed,
            "topics_failed": self.topics_failed,
            "papers_discovered": self.papers_discovered,
            "papers_processed": self.papers_processed,
            "papers_with_extraction": self.papers_with_extraction,
            "total_tokens_used": self.total_tokens_used,
            "total_cost_usd": self.total_cost_usd,
            "output_files": self.output_files,
            "errors": self.errors,
        }
        # Include cross-synthesis info if available
        if self.cross_synthesis_report:
            result["cross_synthesis"] = {
                "questions_answered": self.cross_synthesis_report.questions_answered,
                "synthesis_cost_usd": self.cross_synthesis_report.total_cost_usd,
                "synthesis_tokens": self.cross_synthesis_report.total_tokens_used,
            }
        return result

    def merge_topic_result(self, topic_result: Dict[str, Any]) -> None:
        """Merge topic result into pipeline result.

        Args:
            topic_result: Topic processing result dictionary
        """
        if topic_result.get("success", False):
            self.topics_processed += 1
        else:
            self.topics_failed += 1
            error_msg = topic_result.get("error")
            if error_msg:
                topic_name = topic_result.get("topic", "unknown")
                self.errors.append({"topic": topic_name, "error": error_msg})

        self.papers_discovered += topic_result.get("papers_discovered", 0)
        self.papers_processed += topic_result.get("papers_processed", 0)
        self.papers_with_extraction += topic_result.get("papers_with_extraction", 0)
        self.total_tokens_used += topic_result.get("tokens_used", 0)
        self.total_cost_usd += topic_result.get("cost_usd", 0.0)

        output_file = topic_result.get("output_file")
        if output_file:
            self.output_files.append(output_file)
