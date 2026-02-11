"""Enhanced Markdown Generator for Phase 2 & 3.4

This generator extends the base markdown generator to include:
- Extraction results (prompts, code, metrics, summaries)
- PDF availability status
- Token usage and cost information
- Enhanced formatting for extracted content
- Phase 3.4: Quality badges and PDF availability tracking
"""

from typing import List, Optional
from datetime import datetime
import yaml
import json

from src.models.config import ResearchTopic, NoPDFAction
from src.models.extraction import ExtractedPaper, ExtractionResult
from src.output.markdown_generator import MarkdownGenerator


class EnhancedMarkdownGenerator(MarkdownGenerator):
    """Generates enhanced markdown briefs with extraction results

    Extends base MarkdownGenerator to include:
    - Phase 2: Extracted prompts and code snippets
    - Phase 2: Evaluation metrics and engineering summaries
    - Phase 2: Token usage and cost tracking
    - Phase 3.4: Quality badges and rankings
    - Phase 3.4: PDF availability tracking and statistics
    """

    def _quality_badge(self, score: float) -> str:
        """Generate quality badge based on score.

        Args:
            score: Quality score (0-100).

        Returns:
            Emoji badge string with score.
        """
        if score >= 80:
            return f"⭐⭐⭐ Excellent ({score:.0f})"
        elif score >= 60:
            return f"⭐⭐ Good ({score:.0f})"
        elif score >= 40:
            return f"⭐ Fair ({score:.0f})"
        else:
            return f"○ Low ({score:.0f})"

    def _pdf_badge(self, pdf_available: bool) -> str:
        """Generate PDF availability badge.

        Args:
            pdf_available: Whether PDF is available.

        Returns:
            Badge string.
        """
        if pdf_available:
            return "📄 PDF Available"
        else:
            return "📋 Abstract Only"

    def generate_enhanced(
        self,
        extracted_papers: List[ExtractedPaper],
        topic: ResearchTopic,
        run_id: str,
        summary_stats: Optional[dict] = None,
    ) -> str:
        """Generate enhanced markdown with extraction results

        Args:
            extracted_papers: Papers with extraction results
            topic: Research topic configuration
            run_id: Unique run identifier
            summary_stats: Optional summary statistics from extraction service

        Returns:
            Markdown-formatted string
        """
        # Resolve timeframe string safely
        timeframe_str = "Unknown"
        if hasattr(topic.timeframe, "value"):
            timeframe_str = str(getattr(topic.timeframe, "value"))
        else:
            timeframe_str = "custom"

        # Calculate statistics
        total_papers = len(extracted_papers)
        papers_with_pdf = sum(1 for p in extracted_papers if p.pdf_available)
        papers_with_extraction = sum(
            1 for p in extracted_papers if p.extraction is not None
        )

        total_tokens = sum(
            p.extraction.tokens_used
            for p in extracted_papers
            if p.extraction is not None
        )

        total_cost = sum(
            p.extraction.cost_usd for p in extracted_papers if p.extraction is not None
        )

        # 1. Enhanced Frontmatter
        frontmatter = {
            "topic": topic.query,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "papers_processed": total_papers,
            "papers_with_pdfs": papers_with_pdf,
            "papers_with_extractions": papers_with_extraction,
            "total_tokens_used": total_tokens,
            "total_cost_usd": round(total_cost, 2),
            "timeframe": timeframe_str,
            "run_id": run_id,
            "tags": ["research-brief", "arisp", "phase-2"],
        }

        md_lines = []
        md_lines.append("---")
        md_lines.append(yaml.dump(frontmatter, sort_keys=False).strip())
        md_lines.append("---\n")

        # 2. Header
        md_lines.append(f"# Research Brief: {topic.query}\n")
        md_lines.append(
            f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        md_lines.append(f"**Papers Found:** {total_papers}\n")

        # 3. Pipeline Summary
        md_lines.append("## Pipeline Summary\n")
        md_lines.append(f"- **Papers Processed:** {total_papers}")
        if total_papers > 0:
            pdf_pct = papers_with_pdf / total_papers * 100
            ext_pct = papers_with_extraction / total_papers * 100
            md_lines.append(f"- **With Full PDF:** {papers_with_pdf} ({pdf_pct:.1f}%)")
            md_lines.append(
                f"- **With Extractions:** {papers_with_extraction} ({ext_pct:.1f}%)"
            )
        else:
            md_lines.append("- **With Full PDF:** 0")
            md_lines.append("- **With Extractions:** 0")
        md_lines.append(f"- **Total Tokens Used:** {total_tokens:,}")
        md_lines.append(f"- **Total Cost:** ${total_cost:.2f}\n")

        if summary_stats:
            md_lines.append("### Extraction Statistics\n")
            pdf_rate = summary_stats.get("pdf_success_rate", 0)
            avg_tokens = summary_stats.get("avg_tokens_per_paper", 0)
            avg_cost = summary_stats.get("avg_cost_per_paper", 0)
            md_lines.append(f"- **PDF Success Rate:** {pdf_rate:.1f}%")
            md_lines.append(f"- **Avg Tokens/Paper:** {avg_tokens:,}")
            md_lines.append(f"- **Avg Cost/Paper:** ${avg_cost:.3f}\n")

        # 4. Paper Statistics (Phase 3.4: Quality metrics)
        if extracted_papers:
            papers = [p.metadata for p in extracted_papers]
            avg_citations = sum(p.citation_count for p in papers) / len(papers)
            years = [p.year for p in papers if p.year]
            date_range = f"{min(years)}-{max(years)}" if years else "Unknown"

            # Phase 3.4: Quality score statistics
            quality_scores = [p.quality_score for p in papers if p.quality_score > 0]
            avg_quality = (
                sum(quality_scores) / len(quality_scores) if quality_scores else 0
            )

            md_lines.append("## Research Statistics\n")
            md_lines.append(f"- **Avg Citations:** {avg_citations:.1f}")
            md_lines.append(f"- **Year Range:** {date_range}")
            if quality_scores:
                md_lines.append(f"- **Avg Quality Score:** {avg_quality:.1f}/100")
                md_lines.append(
                    f"- **Top Quality:** {max(quality_scores):.1f} | "
                    f"**Lowest:** {min(quality_scores):.1f}"
                )
            md_lines.append("")

        # 5. Papers with Extractions (Phase 3.4: Filter by NoPDFAction)
        md_lines.append("## Papers\n")

        # Filter papers based on no_pdf_action setting
        papers_to_include = []
        papers_flagged_manual = []
        papers_skipped = 0

        for extracted_paper in extracted_papers:
            if extracted_paper.pdf_available:
                papers_to_include.append(extracted_paper)
            else:
                # Handle papers without PDF based on config
                if topic.no_pdf_action == NoPDFAction.SKIP:
                    papers_skipped += 1
                elif topic.no_pdf_action == NoPDFAction.FLAG_FOR_MANUAL:
                    papers_flagged_manual.append(extracted_paper)
                    papers_to_include.append(extracted_paper)
                else:  # INCLUDE_METADATA (default)
                    papers_to_include.append(extracted_paper)

        # Log skipped papers if any
        if papers_skipped > 0:
            md_lines.append(
                f"> ⚠️ **{papers_skipped} papers skipped** (no PDF available, "
                f"configured to skip)\n"
            )

        for i, extracted_paper in enumerate(papers_to_include, 1):
            is_flagged = extracted_paper in papers_flagged_manual
            md_lines.append(
                self._format_extracted_paper(extracted_paper, i, is_flagged)
            )
            md_lines.append("\n---\n")

        # Phase 3.4: Manual acquisition list
        if papers_flagged_manual:
            md_lines.append("## Papers Requiring Manual PDF Acquisition\n")
            md_lines.append(
                "> The following papers need manual PDF acquisition. "
                "Use the DOI or URL to locate the full paper.\n"
            )
            for paper in papers_flagged_manual:
                meta = paper.metadata
                doi_str = f"DOI: {meta.doi}" if meta.doi else "No DOI"
                md_lines.append(f"- **{meta.title}** - {doi_str} - [Link]({meta.url})")
            md_lines.append("")

        return "\n".join(md_lines)

    def _format_extracted_paper(
        self, extracted: ExtractedPaper, index: int, is_flagged: bool = False
    ) -> str:
        """Format a single extracted paper with all extraction results

        Args:
            extracted: Extracted paper with metadata and results
            index: Paper number in list
            is_flagged: Whether paper is flagged for manual PDF acquisition

        Returns:
            Markdown-formatted string
        """
        paper = extracted.metadata
        lines = []

        # Paper header
        authors = ", ".join([a.name for a in (paper.authors or [])[:3]])
        if paper.authors and len(paper.authors) > 3:
            authors += ", et al."

        lines.append(f"### {index}. [{paper.title}]({paper.url})")

        # Phase 3.4: Quality badge and PDF status
        quality_badge = self._quality_badge(paper.quality_score)
        pdf_badge = self._pdf_badge(extracted.pdf_available)
        lines.append(f"**Quality:** {quality_badge} | **Status:** {pdf_badge}")

        lines.append(f"**Authors:** {authors}")
        pub_year = paper.year or "Unknown"
        lines.append(
            f"**Published:** {pub_year} | **Citations:** {paper.citation_count}"
        )
        if paper.venue:
            lines.append(f"**Venue:** {paper.venue}")

        # PDF status with link if available
        if extracted.pdf_available:
            lines.append(f"**PDF:** ✅ [Download]({paper.open_access_pdf})")
        else:
            lines.append("**PDF:** ❌ Not available via open access")
            if paper.doi:
                lines.append(f"**DOI:** {paper.doi}")

        # Phase 3.4: Flag for manual acquisition
        if is_flagged:
            lines.append("")
            lines.append(
                "> ⚠️ **ACTION REQUIRED:** PDF needs manual acquisition. "
                "Use DOI or URL to locate."
            )

        # Extraction info
        if extracted.extraction:
            ext = extracted.extraction
            lines.append(
                f"**Tokens Used:** {ext.tokens_used:,} | **Cost:** ${ext.cost_usd:.3f}"
            )
        lines.append("")

        # Abstract
        if paper.abstract:
            abstract = paper.abstract.replace("\n", " ")
            lines.append(f"> {abstract}\n")

        # Extraction Results
        if extracted.extraction:
            lines.append("#### Extraction Results\n")
            for result in extracted.extraction.extraction_results:
                if result.success:
                    lines.append(self._format_extraction_result(result))

        return "\n".join(lines)

    def _format_extraction_result(self, result: ExtractionResult) -> str:
        """Format a single extraction result

        Args:
            result: Extraction result

        Returns:
            Markdown-formatted string
        """
        lines = []

        # Format target name as header
        target_name_formatted = result.target_name.replace("_", " ").title()
        lines.append(
            f"**{target_name_formatted}** (confidence: {result.confidence:.0%})\n"
        )

        # Format content based on type
        content = result.content

        if content is None or content == "":
            lines.append("_No content extracted_\n")
            return "\n".join(lines)

        # Handle different content types
        if isinstance(content, list):
            # List format (e.g., prompts)
            for item in content:
                lines.append(f"- {item}")
            lines.append("")

        elif isinstance(content, dict):
            # JSON/dict format (e.g., metrics)
            # Try to format as table if it's simple key-value pairs
            if all(isinstance(v, (int, float, str, bool)) for v in content.values()):
                lines.append("| Metric | Value |")
                lines.append("|--------|-------|")
                for key, value in content.items():
                    lines.append(f"| {key} | {value} |")
                lines.append("")
            else:
                # Complex dict - use JSON formatting
                lines.append("```json")
                lines.append(json.dumps(content, indent=2))
                lines.append("```\n")

        elif isinstance(content, str):
            # Check if it looks like code
            if any(
                keyword in content.lower()
                for keyword in [
                    "def ",
                    "class ",
                    "import ",
                    "function ",
                    "const ",
                    "let ",
                    "var ",
                ]
            ):
                # Code format
                # Try to detect language
                lang = "python"  # Default
                if "function " in content or "const " in content or "let " in content:
                    lang = "javascript"
                elif "public class" in content or "private " in content:
                    lang = "java"

                lines.append(f"```{lang}")
                lines.append(content)
                lines.append("```\n")
            else:
                # Regular text
                lines.append(content)
                lines.append("")

        else:
            # Fallback: convert to string
            lines.append(str(content))
            lines.append("")

        return "\n".join(lines)
