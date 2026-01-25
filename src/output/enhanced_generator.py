"""Enhanced Markdown Generator for Phase 2: PDF Processing & LLM Extraction

This generator extends the base markdown generator to include:
- Extraction results (prompts, code, metrics, summaries)
- PDF availability status
- Token usage and cost information
- Enhanced formatting for extracted content
"""

from typing import List, Optional
from datetime import datetime
import yaml
import json

from src.models.config import ResearchTopic
from src.models.extraction import ExtractedPaper, ExtractionResult
from src.output.markdown_generator import MarkdownGenerator


class EnhancedMarkdownGenerator(MarkdownGenerator):
    """Generates enhanced markdown briefs with extraction results

    Extends base MarkdownGenerator to include Phase 2 features:
    - Extracted prompts and code snippets
    - Evaluation metrics
    - Engineering summaries
    - Token usage and cost tracking
    """

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

        # 4. Paper Statistics
        if extracted_papers:
            papers = [p.metadata for p in extracted_papers]
            avg_citations = sum(p.citation_count for p in papers) / len(papers)
            years = [p.year for p in papers if p.year]
            date_range = f"{min(years)}-{max(years)}" if years else "Unknown"

            md_lines.append("## Research Statistics\n")
            md_lines.append(f"- **Avg Citations:** {avg_citations:.1f}")
            md_lines.append(f"- **Year Range:** {date_range}\n")

        # 5. Papers with Extractions
        md_lines.append("## Papers\n")

        for i, extracted_paper in enumerate(extracted_papers, 1):
            md_lines.append(self._format_extracted_paper(extracted_paper, i))
            md_lines.append("\n---\n")

        return "\n".join(md_lines)

    def _format_extracted_paper(self, extracted: ExtractedPaper, index: int) -> str:
        """Format a single extracted paper with all extraction results

        Args:
            extracted: Extracted paper with metadata and results
            index: Paper number in list

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
        lines.append(f"**Authors:** {authors}")
        pub_year = paper.year or "Unknown"
        lines.append(
            f"**Published:** {pub_year} | **Citations:** {paper.citation_count}"
        )
        if paper.venue:
            lines.append(f"**Venue:** {paper.venue}")

        # PDF status
        if extracted.pdf_available:
            lines.append(f"**PDF Available:** ✅ **[PDF]({paper.open_access_pdf})**")
        else:
            lines.append("**PDF Available:** ❌ (Abstract only)")

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
