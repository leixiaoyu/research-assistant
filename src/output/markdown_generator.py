"""Base Markdown Generator for Phase 1

This generator creates Obsidian-compatible markdown briefs from paper metadata.
Phase 2's EnhancedMarkdownGenerator extends this to include extraction results.
"""

from typing import List
from datetime import datetime
import yaml

from src.models.paper import PaperMetadata
from src.models.config import ResearchTopic


class MarkdownGenerator:
    """Generates markdown briefs from paper metadata

    Creates Obsidian-compatible markdown files with:
    - YAML frontmatter with metadata
    - Research statistics
    - Formatted paper listings
    """

    def generate(
        self,
        papers: List[PaperMetadata],
        topic: ResearchTopic,
        run_id: str
    ) -> str:
        """Generate markdown brief from paper metadata

        Args:
            papers: List of paper metadata
            topic: Research topic configuration
            run_id: Unique run identifier

        Returns:
            Markdown-formatted string
        """
        # Resolve timeframe string safely
        timeframe_str = "Unknown"
        if hasattr(topic.timeframe, 'value'):
            timeframe_str = str(getattr(topic.timeframe, 'value'))
        else:
            timeframe_str = "custom"

        # 1. Frontmatter with YAML
        frontmatter = {
            "topic": topic.query,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "papers_found": len(papers),
            "timeframe": timeframe_str,
            "run_id": run_id,
            "tags": ["research-brief", "arisp"]
        }

        md_lines = []
        md_lines.append("---")
        md_lines.append(yaml.dump(frontmatter, sort_keys=False).strip())
        md_lines.append("---\n")

        # 2. Header
        md_lines.append(f"# Research Brief: {topic.query}\n")
        md_lines.append(f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        md_lines.append(f"**Papers Found:** {len(papers)}\n")

        # 3. Statistics
        if papers:
            avg_citations = sum(p.citation_count for p in papers) / len(papers)
            years = [p.year for p in papers if p.year]
            date_range = f"{min(years)}-{max(years)}" if years else "Unknown"

            md_lines.append("## Research Statistics\n")
            md_lines.append(f"- **Avg Citations:** {avg_citations:.1f}")
            md_lines.append(f"- **Year Range:** {date_range}\n")

        # 4. Papers
        md_lines.append("## Papers\n")

        for i, paper in enumerate(papers, 1):
            md_lines.append(self._format_paper(paper, i))
            md_lines.append("\n---\n")

        return "\n".join(md_lines)

    def _format_paper(self, paper: PaperMetadata, index: int) -> str:
        """Format a single paper

        Args:
            paper: Paper metadata
            index: Paper number in list

        Returns:
            Markdown-formatted string
        """
        lines = []

        # Paper header
        authors = ", ".join([a.name for a in (paper.authors or [])[:3]])
        if paper.authors and len(paper.authors) > 3:
            authors += ", et al."

        lines.append(f"### {index}. [{paper.title}]({paper.url})")
        lines.append(f"**Authors:** {authors}")
        lines.append(f"**Published:** {paper.year or 'Unknown'} | **Citations:** {paper.citation_count}")
        if paper.venue:
            lines.append(f"**Venue:** {paper.venue}")
        lines.append("")

        # Abstract
        if paper.abstract:
            abstract = paper.abstract.replace("\n", " ")
            lines.append(f"> {abstract}\n")

        return "\n".join(lines)
