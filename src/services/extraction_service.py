"""Extraction Service for Phase 2 & Phase 3.1: PDF Processing & LLM Extraction

This service orchestrates the complete extraction pipeline:
1. PDF Download → 2. PDF Conversion (with Fallback) → 3. LLM Extraction

Implements fallback strategies:
- If PDF unavailable → Use abstract only
- If PDF download fails → Use abstract only
- If PDF conversion fails → Use abstract only
- Continue pipeline even if individual papers fail

Phase 3.1: Adds concurrent processing support via ConcurrentPipeline integration.

This service ties together PDFService, FallbackPDFService, and LLMService.
"""

from typing import List, Optional, TYPE_CHECKING
import structlog

from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget, ExtractedPaper

from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.services.pdf_extractors.fallback_service import FallbackPDFService
from src.utils.exceptions import (
    PDFDownloadError,
    ConversionError,
    ExtractionError,
    FileSizeError,
    PDFValidationError,
)

# Phase 3.1: Concurrent pipeline (optional dependency)
if TYPE_CHECKING:
    from src.services.cache_service import CacheService
    from src.services.dedup_service import DeduplicationService
    from src.services.filter_service import FilterService
    from src.services.checkpoint_service import CheckpointService
    from src.models.concurrency import ConcurrencyConfig
    from src.orchestration.concurrent_pipeline import ConcurrentPipeline

logger = structlog.get_logger()


class ExtractionService:
    """Orchestrates PDF download, conversion, and LLM extraction

    Implements graceful degradation:
    - Prefers full PDF extraction
    - Falls back to abstract-only if PDF unavailable
    - Continues processing even if individual papers fail

    Phase 3.1: Supports concurrent processing when Phase 3 services are provided.
    """

    def __init__(
        self,
        pdf_service: PDFService,
        llm_service: LLMService,
        fallback_service: Optional[FallbackPDFService] = None,
        keep_pdfs: bool = True,
        # Phase 3.1: Optional concurrent processing dependencies
        cache_service: Optional["CacheService"] = None,
        dedup_service: Optional["DeduplicationService"] = None,
        filter_service: Optional["FilterService"] = None,
        checkpoint_service: Optional["CheckpointService"] = None,
        concurrency_config: Optional["ConcurrencyConfig"] = None,
    ):
        """Initialize extraction service

        Args:
            pdf_service: Service for PDF operations (download)
            llm_service: Service for LLM extraction
            fallback_service: Service for multi-backend PDF extraction
            keep_pdfs: Whether to keep PDFs after processing
            cache_service: Phase 3 caching service (optional)
            dedup_service: Phase 3 deduplication service (optional)
            filter_service: Phase 3 filtering service (optional)
            checkpoint_service: Phase 3 checkpoint service (optional)
            concurrency_config: Phase 3.1 concurrency configuration (optional)
        """
        self.pdf_service = pdf_service
        self.llm_service = llm_service
        self.fallback_service = fallback_service
        self.keep_pdfs = keep_pdfs

        # Phase 3 services (optional)
        self.cache_service = cache_service
        self.dedup_service = dedup_service
        self.filter_service = filter_service
        self.checkpoint_service = checkpoint_service
        self.concurrency_config = concurrency_config

        # Phase 3.1: Concurrent pipeline (initialized on demand)
        self._concurrent_pipeline: Optional["ConcurrentPipeline"] = None

        logger.info(
            "extraction_service_initialized",
            keep_pdfs=keep_pdfs,
            has_fallback_service=fallback_service is not None,
            has_phase3_services=all(
                [cache_service, dedup_service, filter_service, checkpoint_service]
            ),
            concurrent_enabled=concurrency_config is not None,
        )

    async def process_paper(
        self, paper: PaperMetadata, targets: List[ExtractionTarget]
    ) -> ExtractedPaper:
        """Process a single paper through the full pipeline

        Pipeline stages:
        1. Try to download PDF (if available)
        2. If successful, convert to markdown (using FallbackService if available)
        3. Extract using LLM
        4. If PDF fails at any stage, fall back to abstract only

        Args:
            paper: Paper metadata
            targets: List of extraction targets

        Returns:
            ExtractedPaper with all available information
        """
        extracted = ExtractedPaper(metadata=paper, pdf_available=False)

        markdown_content: str = ""

        # Attempt PDF pipeline
        if paper.open_access_pdf:
            try:
                # Download PDF
                pdf_path = await self.pdf_service.download_pdf(
                    url=str(paper.open_access_pdf), paper_id=paper.paper_id
                )
                extracted.pdf_available = True
                extracted.pdf_path = str(pdf_path)

                # Convert to markdown
                if self.fallback_service:
                    # Phase 2.5: Use FallbackPDFService
                    pdf_result = await self.fallback_service.extract_with_fallback(
                        pdf_path
                    )

                    if pdf_result.success and pdf_result.markdown:
                        markdown_content = pdf_result.markdown
                        # Note: We don't save the markdown file to disk in Phase 2.5
                        # architecture unless we want to for debugging.
                        # The content is in memory.
                        # For compatibility with ExtractedPaper model which
                        # expects a path, we could save it, or just use content.
                        # The ExtractedPaper model has 'markdown_path' (Optional[str]).
                        # We can skip setting markdown_path if we don't save it.

                        logger.info(
                            "pdf_pipeline_success",
                            paper_id=paper.paper_id,
                            backend=pdf_result.backend,
                            quality_score=pdf_result.quality_score,
                            md_size=len(markdown_content),
                        )
                    else:
                        raise ConversionError(f"Extraction failed: {pdf_result.error}")
                else:
                    # Phase 2: Use legacy PDFService conversion
                    md_path = self.pdf_service.convert_to_markdown(
                        pdf_path=pdf_path, paper_id=paper.paper_id
                    )
                    extracted.markdown_path = str(md_path)
                    markdown_content = md_path.read_text(encoding="utf-8")

                    logger.info(
                        "pdf_pipeline_success",
                        paper_id=paper.paper_id,
                        pdf_size=pdf_path.stat().st_size,
                        md_size=len(markdown_content),
                    )

            except (
                PDFDownloadError,
                FileSizeError,
                PDFValidationError,
                ConversionError,
            ) as e:
                logger.warning(
                    "pdf_pipeline_failed_fallback_to_abstract",
                    paper_id=paper.paper_id,
                    error_type=type(e).__name__,
                    error=str(e),
                )
                # Reset PDF status on failure
                extracted.pdf_available = False
                extracted.pdf_path = None
                extracted.markdown_path = None
                markdown_content = self._format_abstract(paper)

            except Exception as e:
                # Catch-all for unexpected errors
                logger.error(
                    "pdf_pipeline_unexpected_error",
                    paper_id=paper.paper_id,
                    error=str(e),
                )
                # Reset PDF status on failure
                extracted.pdf_available = False
                extracted.pdf_path = None
                extracted.markdown_path = None
                markdown_content = self._format_abstract(paper)

        else:
            # No PDF available, use abstract
            logger.info("no_pdf_available_using_abstract", paper_id=paper.paper_id)
            markdown_content = self._format_abstract(paper)

        # LLM Extraction (always attempted, even for abstract-only)
        try:
            extraction = await self.llm_service.extract(
                markdown_content=markdown_content, targets=targets, paper_metadata=paper
            )
            extracted.extraction = extraction

            logger.info(
                "extraction_success",
                paper_id=paper.paper_id,
                tokens_used=extraction.tokens_used,
                cost_usd=extraction.cost_usd,
            )

        except ExtractionError as e:
            logger.error("extraction_failed", paper_id=paper.paper_id, error=str(e))
            # Don't raise - return extracted paper without extraction results

        except Exception as e:
            logger.error(
                "extraction_unexpected_error", paper_id=paper.paper_id, error=str(e)
            )

        # Cleanup temporary files
        try:
            self.pdf_service.cleanup_temp_files(
                paper_id=paper.paper_id, keep_pdfs=self.keep_pdfs
            )
        except Exception as e:
            logger.warning("cleanup_failed", paper_id=paper.paper_id, error=str(e))

        return extracted

    async def process_papers(
        self, papers: List[PaperMetadata], targets: List[ExtractionTarget]
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
            "batch_processing_started", total_papers=len(papers), targets=len(targets)
        )

        results = []
        for i, paper in enumerate(papers, 1):
            logger.info(
                "processing_paper",
                paper_id=paper.paper_id,
                progress=f"{i}/{len(papers)}",
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
            papers_with_pdf=with_pdf,
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
            authors = ", ".join(a.name for a in paper.authors)
        else:
            authors = "Unknown"

        # Format venue
        venue = paper.venue or "Unknown"

        # Format markdown
        markdown = f"""# {paper.title or 'Untitled Paper'}

**Authors:** {authors}
**Year:** {paper.year or 'Unknown'}
**Venue:** {venue}
**Citations:** {paper.citation_count or 0}

## Abstract

{paper.abstract or 'No abstract available.'}

---

**Note:** Full PDF was not available for this paper.
Extraction is based on abstract only.
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
            r.extraction.tokens_used for r in results if r.extraction is not None
        )

        total_cost = sum(
            r.extraction.cost_usd for r in results if r.extraction is not None
        )

        return {
            "total_papers": total,
            "papers_with_pdf": with_pdf,
            "papers_with_extraction": with_extraction,
            "pdf_success_rate": round(with_pdf / total * 100, 1) if total > 0 else 0.0,
            "extraction_success_rate": (
                round(with_extraction / total * 100, 1) if total > 0 else 0.0
            ),
            "total_tokens_used": total_tokens,
            "total_cost_usd": round(total_cost, 2),
            "avg_tokens_per_paper": (
                round(total_tokens / with_extraction) if with_extraction > 0 else 0
            ),
            "avg_cost_per_paper": (
                round(total_cost / with_extraction, 3) if with_extraction > 0 else 0.0
            ),
        }

    async def process_papers_concurrent(
        self,
        papers: List[PaperMetadata],
        targets: List[ExtractionTarget],
        run_id: str,
        query: str,
    ) -> List[ExtractedPaper]:
        """Process papers concurrently using Phase 3.1 concurrent pipeline.

        This method requires Phase 3 services to be initialized.
        If Phase 3 services are not available, falls back to sequential processing.

        Args:
            papers: Papers to process
            targets: Extraction targets
            run_id: Unique run identifier for checkpointing
            query: Search query for relevance filtering

        Returns:
            List of ExtractedPaper objects

        Raises:
            ValueError: If concurrent processing requested but Phase 3
                services unavailable
        """
        # Check if Phase 3 services are available
        if not all(
            [
                self.cache_service,
                self.dedup_service,
                self.filter_service,
                self.checkpoint_service,
                self.concurrency_config,
                self.fallback_service,
            ]
        ):
            logger.warning(
                "concurrent_processing_unavailable_falling_back_to_sequential",
                missing_services={
                    "cache": self.cache_service is None,
                    "dedup": self.dedup_service is None,
                    "filter": self.filter_service is None,
                    "checkpoint": self.checkpoint_service is None,
                    "concurrency_config": (self.concurrency_config is None),
                    "fallback_pdf": self.fallback_service is None,
                },
            )
            # Fallback to sequential processing
            return await self.process_papers(papers, targets)

        # Lazy initialization of concurrent pipeline
        if self._concurrent_pipeline is None:
            from src.orchestration.concurrent_pipeline import ConcurrentPipeline

            # Type narrowing assertions - we've already checked these are not None
            assert self.fallback_service is not None
            assert self.concurrency_config is not None
            assert self.cache_service is not None
            assert self.dedup_service is not None
            assert self.filter_service is not None
            assert self.checkpoint_service is not None

            self._concurrent_pipeline = ConcurrentPipeline(
                config=self.concurrency_config,
                fallback_pdf_service=self.fallback_service,
                llm_service=self.llm_service,
                cache_service=self.cache_service,
                dedup_service=self.dedup_service,
                filter_service=self.filter_service,
                checkpoint_service=self.checkpoint_service,
            )

        logger.info(
            "concurrent_processing_started",
            run_id=run_id,
            total_papers=len(papers),
            num_workers=self.concurrency_config.max_concurrent_downloads,  # type: ignore  # noqa: E501
        )

        # Process concurrently
        results: List[ExtractedPaper] = []
        async for (
            extracted_paper
        ) in self._concurrent_pipeline.process_papers_concurrent(
            papers=papers, targets=targets, run_id=run_id, query=query
        ):
            results.append(extracted_paper)

        logger.info(
            "concurrent_processing_complete",
            run_id=run_id,
            total_papers=len(papers),
            successful=len(results),
        )

        return results
