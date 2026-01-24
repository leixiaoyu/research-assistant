"""Extraction Service for Phase 2: PDF Processing & LLM Extraction

This service orchestrates the complete extraction pipeline:
1. PDF Download → 2. PDF Conversion → 3. LLM Extraction

Implements fallback strategies:
- If PDF unavailable → Use abstract only
- If PDF download fails → Use abstract only
- If PDF conversion fails → Use abstract only
- Continue pipeline even if individual papers fail

This service ties together PDFService and LLMService.
"""

from pathlib import Path
from typing import List
import structlog

from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget, ExtractedPaper, PaperExtraction
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.utils.exceptions import (
    PDFDownloadError,
    ConversionError,
    ExtractionError,
    FileSizeError,
    PDFValidationError
)

logger = structlog.get_logger()


class ExtractionService:
    """Orchestrates PDF download, conversion, and LLM extraction

    Implements graceful degradation:
    - Prefers full PDF extraction
    - Falls back to abstract-only if PDF unavailable
    - Continues processing even if individual papers fail
    """

    def __init__(
        self,
        pdf_service: PDFService,
        llm_service: LLMService,
        keep_pdfs: bool = True
    ):
        """Initialize extraction service

        Args:
            pdf_service: Service for PDF operations
            llm_service: Service for LLM extraction
            keep_pdfs: Whether to keep PDFs after processing
        """
        self.pdf_service = pdf_service
        self.llm_service = llm_service
        self.keep_pdfs = keep_pdfs

        logger.info(
            "extraction_service_initialized",
            keep_pdfs=keep_pdfs
        )

    async def process_paper(
        self,
        paper: PaperMetadata,
        targets: List[ExtractionTarget]
    ) -> ExtractedPaper:
        """Process a single paper through the full pipeline

        Pipeline stages:
        1. Try to download PDF (if available)
        2. If successful, convert to markdown
        3. Extract using LLM
        4. If PDF fails at any stage, fall back to abstract only

        Args:
            paper: Paper metadata
            targets: List of extraction targets

        Returns:
            ExtractedPaper with all available information

        Note:
            This method never raises exceptions for individual paper failures.
            It always returns an ExtractedPaper, even if extraction failed.
        """
        extracted = ExtractedPaper(
            metadata=paper,
            pdf_available=False
        )

        markdown_content: str = ""

        # Attempt PDF pipeline
        if paper.open_access_pdf:
            try:
                # Download PDF
                pdf_path = await self.pdf_service.download_pdf(
                    url=str(paper.open_access_pdf),
                    paper_id=paper.paper_id
                )
                extracted.pdf_available = True
                extracted.pdf_path = str(pdf_path)

                # Convert to markdown
                md_path = self.pdf_service.convert_to_markdown(
                    pdf_path=pdf_path,
                    paper_id=paper.paper_id
                )
                extracted.markdown_path = str(md_path)

                # Read markdown content
                markdown_content = md_path.read_text(encoding='utf-8')

                logger.info(
                    "pdf_pipeline_success",
                    paper_id=paper.paper_id,
                    pdf_size=pdf_path.stat().st_size,
                    md_size=len(markdown_content)
                )

            except (PDFDownloadError, FileSizeError, PDFValidationError, ConversionError) as e:
                logger.warning(
                    "pdf_pipeline_failed_fallback_to_abstract",
                    paper_id=paper.paper_id,
                    error_type=type(e).__name__,
                    error=str(e)
                )
                markdown_content = self._format_abstract(paper)

            except Exception as e:
                # Catch-all for unexpected errors
                logger.error(
                    "pdf_pipeline_unexpected_error",
                    paper_id=paper.paper_id,
                    error=str(e)
                )
                markdown_content = self._format_abstract(paper)

        else:
            # No PDF available, use abstract
            logger.info(
                "no_pdf_available_using_abstract",
                paper_id=paper.paper_id
            )
            markdown_content = self._format_abstract(paper)

        # LLM Extraction (always attempted, even for abstract-only)
        try:
            extraction = await self.llm_service.extract(
                markdown_content=markdown_content,
                targets=targets,
                paper_metadata=paper
            )
            extracted.extraction = extraction

            logger.info(
                "extraction_success",
                paper_id=paper.paper_id,
                tokens_used=extraction.tokens_used,
                cost_usd=extraction.cost_usd
            )

        except ExtractionError as e:
            logger.error(
                "extraction_failed",
                paper_id=paper.paper_id,
                error=str(e)
            )
            # Don't raise - return extracted paper without extraction results

        except Exception as e:
            logger.error(
                "extraction_unexpected_error",
                paper_id=paper.paper_id,
                error=str(e)
            )

        # Cleanup temporary files
        try:
            self.pdf_service.cleanup_temp_files(
                paper_id=paper.paper_id,
                keep_pdfs=self.keep_pdfs
            )
        except Exception as e:
            logger.warning(
                "cleanup_failed",
                paper_id=paper.paper_id,
                error=str(e)
            )

        return extracted

    async def process_papers(
        self,
        papers: List[PaperMetadata],
        targets: List[ExtractionTarget]
    ) -> List[ExtractedPaper]:
        """Process multiple papers sequentially

        Args:
            papers: List of papers to process
            targets: Extraction targets

        Returns:
            List of ExtractedPaper objects

        Note:
            Papers are processed sequentially to control costs and
            comply with rate limits. Phase 3 will add concurrent processing.
        """
        logger.info(
            "batch_processing_started",
            total_papers=len(papers),
            targets=len(targets)
        )

        results = []
        for i, paper in enumerate(papers, 1):
            logger.info(
                "processing_paper",
                paper_id=paper.paper_id,
                progress=f"{i}/{len(papers)}"
            )

            extracted = await self.process_paper(paper, targets)
            results.append(extracted)

        # Log summary
        successful = sum(1 for r in results if r.extraction is not None)
        with_pdf = sum(1 for r in results if r.pdf_available)

        logger.info(
            "batch_processing_completed",
            total_papers=len(papers),
            successful_extractions=successful,
            papers_with_pdf=with_pdf
        )

        return results

    def _format_abstract(self, paper: PaperMetadata) -> str:
        """Format paper metadata as markdown when PDF unavailable

        Args:
            paper: Paper metadata

        Returns:
            Markdown-formatted string with available information
        """
        # Format authors
        if paper.authors:
            authors = ', '.join(a.name for a in paper.authors)
        else:
            authors = 'Unknown'

        # Format venue
        venue = paper.venue or 'Unknown'

        # Format markdown
        markdown = f"""# {paper.title or 'Untitled Paper'}

**Authors:** {authors}
**Year:** {paper.year or 'Unknown'}
**Venue:** {venue}
**Citations:** {paper.citation_count or 0}

## Abstract

{paper.abstract or 'No abstract available.'}

---

**Note:** Full PDF was not available for this paper. Extraction is based on abstract only.
"""

        return markdown

    def get_extraction_summary(self, results: List[ExtractedPaper]) -> dict:
        """Generate summary statistics for batch extraction

        Args:
            results: List of extraction results

        Returns:
            Dictionary with summary statistics
        """
        total = len(results)
        with_pdf = sum(1 for r in results if r.pdf_available)
        with_extraction = sum(1 for r in results if r.extraction is not None)

        total_tokens = sum(
            r.extraction.tokens_used
            for r in results
            if r.extraction is not None
        )

        total_cost = sum(
            r.extraction.cost_usd
            for r in results
            if r.extraction is not None
        )

        return {
            "total_papers": total,
            "papers_with_pdf": with_pdf,
            "papers_with_extraction": with_extraction,
            "pdf_success_rate": round(with_pdf / total * 100, 1) if total > 0 else 0.0,
            "extraction_success_rate": round(with_extraction / total * 100, 1) if total > 0 else 0.0,
            "total_tokens_used": total_tokens,
            "total_cost_usd": round(total_cost, 2),
            "avg_tokens_per_paper": round(total_tokens / with_extraction) if with_extraction > 0 else 0,
            "avg_cost_per_paper": round(total_cost / with_extraction, 3) if with_extraction > 0 else 0.0
        }
