from typing import List
from datetime import datetime
import yaml

from src.models.config import ResearchTopic
from src.models.paper import PaperMetadata


class MarkdownGenerator:
    """Generates Obsidian-compatible markdown briefs"""

    def generate(
        self, papers: List[PaperMetadata], topic: ResearchTopic, run_id: str
    ) -> str:
        """Generate complete markdown content"""

        # Resolve timeframe string safely
        timeframe_str = "Unknown"
        if hasattr(topic.timeframe, "value"):
            # Recent or SinceYear
            timeframe_str = str(getattr(topic.timeframe, "value"))
        else:
            # DateRange or other
            timeframe_str = "custom"

        # 1. Frontmatter
        frontmatter = {
            "topic": topic.query,
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "papers_processed": len(papers),
            "timeframe": timeframe_str,
            "run_id": run_id,
            "tags": ["research-brief", "arisp"],
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
        md_lines.append(f"**Papers Found:** {len(papers)}\n")

        # 3. Statistics
        if papers:
            avg_citations = sum(p.citation_count for p in papers) / len(papers)
            years = [p.year for p in papers if p.year]
            date_range = f"{min(years)}-{max(years)}" if years else "Unknown"  # pragma: no cover

            md_lines.append("## Summary Statistics")
            md_lines.append(f"- **Total Papers:** {len(papers)}")
            md_lines.append(f"- **Avg Citations:** {avg_citations:.1f}")
            md_lines.append(f"- **Year Range:** {date_range}\n")
        else:  # pragma: no cover
            md_lines.append("No papers found to generate statistics.\n")

        # 4. Papers List
        md_lines.append("## Papers\n")

        for i, paper in enumerate(papers, 1):
            md_lines.append(self._format_paper(paper, i))
            md_lines.append("\n---\n")

        return "\n".join(md_lines)

    def _format_paper(self, paper: PaperMetadata, index: int) -> str:
        """Format a single paper entry"""
        authors = ", ".join([a.name for a in paper.authors[:3]])
        if len(paper.authors) > 3:
            authors += ", et al."

        lines = []
        lines.append(f"### {index}. [{paper.title}]({paper.url})")
        lines.append(f"**Authors:** {authors}")
        lines.append(
            f"**Published:** {paper.year or 'Unknown'} | "
            f"**Citations:** {paper.citation_count}"
        )
        if paper.venue:
            lines.append(f"**Venue:** {paper.venue}")

        if paper.open_access_pdf:
            lines.append(f"**[PDF]({paper.open_access_pdf})**")

        if paper.abstract:
            # Simple cleanup of abstract
            abstract = paper.abstract.replace("\n", " ")
            lines.append(f"\n> {abstract}")

        return "\n".join(lines)
