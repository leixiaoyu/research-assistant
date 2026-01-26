"""Quality validator for PDF extractions.

Scores extraction quality from 0.0 (failed) to 1.0 (perfect) based on
text density, structural elements, code blocks, and tables.
"""

import re
from pathlib import Path
import structlog

logger = structlog.get_logger()


class QualityValidator:
    """
    Validates and scores PDF extraction quality.

    Uses a weighted formula:
    - 40% Text Density (length vs. page count)
    - 30% Structural Elements (headers, lists)
    - 15% Code Block Detection
    - 15% Table Detection
    """

    def __init__(self, min_quality_score: float = 0.5):
        self.min_quality_score = min_quality_score

    def score_extraction(
        self, markdown: str, pdf_path: Path, page_count: int = 0
    ) -> float:
        """
        Calculate quality score for extraction.

        Args:
            markdown: Extracted markdown content
            pdf_path: Original PDF path (for page count)
            page_count: Optional page count (if known)

        Returns:
            Quality score from 0.0 to 1.0
        """
        if not markdown or len(markdown) < 100:
            return 0.0

        # Get page count if unknown
        if page_count <= 0:
            page_count = self._get_page_count(pdf_path)

        # 1. Text Density (40%)
        density_score = self._calculate_text_density_score(markdown, page_count)

        # 2. Structural Elements (30%)
        structure_score = self._calculate_structure_score(markdown)

        # 3. Code Detection (15%)
        code_score = self._calculate_code_detection_score(markdown)

        # 4. Table Detection (15%)
        table_score = self._calculate_table_detection_score(markdown)

        # Weighted calculation
        total_score = (
            0.40 * density_score
            + 0.30 * structure_score
            + 0.15 * code_score
            + 0.15 * table_score
        )

        logger.debug(
            "quality_scored",
            total_score=round(total_score, 2),
            density=round(density_score, 2),
            structure=round(structure_score, 2),
            code=round(code_score, 2),
            table=round(table_score, 2),
            pdf_path=str(pdf_path),
        )

        return float(total_score)

    def _calculate_text_density_score(self, markdown: str, page_count: int) -> float:
        """
        Expect ~500-2000 chars per page for academic papers.
        """
        if page_count <= 0:
            return 0.5  # Neutral if page count unknown

        chars_per_page = len(markdown) / page_count

        if 500 <= chars_per_page <= 2000:
            return 1.0
        elif chars_per_page < 100:
            return 0.0  # Extraction likely failed
        else:
            # Decay outside ideal range
            # 1.0 at 500 or 2000, drops to 0.0 at very far ranges
            return max(0.0, 1.0 - abs(chars_per_page - 1250) / 2500)

    def _calculate_structure_score(self, markdown: str) -> float:
        """
        Check for markdown structural elements (headers, lists).
        """
        headers = len(re.findall(r"^#{1,6}\s", markdown, re.MULTILINE))
        lists = len(re.findall(r"^\s*[-\*+]\s", markdown, re.MULTILINE))

        # Normalize by document length (elements per 1000 characters)
        structures_per_1k = (headers + lists) / max(1, len(markdown) / 1000)

        # Academic papers typically have ~5-15 structures per 1000 chars
        if 5 <= structures_per_1k <= 15:
            return 1.0
        else:
            return max(0.0, 1.0 - abs(structures_per_1k - 10) / 20)

    def _calculate_code_detection_score(self, markdown: str) -> float:
        """
        Check for code block presence.
        """
        code_blocks = len(re.findall(r"```[\w]*\n", markdown))
        if code_blocks == 0:
            return 0.5  # Neutral (could be a survey paper)

        # Found code blocks - good sign for fidelity
        return min(1.0, 0.5 + (code_blocks / 5))

    def _calculate_table_detection_score(self, markdown: str) -> float:
        """
        Check for table presence.
        """
        # Count markdown table header separators
        # Look for | --- | style lines
        tables = len(re.findall(r"|[\s\-:\|]+\|", markdown))
        if tables == 0:
            return 0.5  # Neutral

        return min(1.0, 0.5 + (tables / 3))

    def _get_page_count(self, pdf_path: Path) -> int:
        """Lightweight page count detection."""
        try:
            import fitz

            doc = fitz.open(pdf_path)
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return 0
