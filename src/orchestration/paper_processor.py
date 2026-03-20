"""Single paper processing logic.

Extracted from concurrent_pipeline.py for better separation of concerns.
Handles the processing of individual papers through the extraction pipeline.
"""

import asyncio
import time
from typing import List, Optional
from pathlib import Path
import structlog

from src.models.paper import PaperMetadata
from src.models.extraction import ExtractionTarget, ExtractedPaper

# Phase 2.5 integration
from src.services.pdf_extractors.fallback_service import FallbackPDFService

# Phase 3 integrations
from src.services.cache_service import CacheService
from src.services.llm import LLMService

# Phase 4: Prometheus metrics
from src.observability.metrics import (
    PDF_DOWNLOADS,
    PDF_CONVERSIONS,
    PAPER_PROCESSING_DURATION,
    EXTRACTION_ERRORS,
)

logger = structlog.get_logger()


class PaperProcessor:
    """Processes individual papers through the extraction pipeline.

    Handles:
    - Cache checking
    - PDF download and conversion
    - LLM extraction
    - Result caching
    """

    def __init__(
        self,
        fallback_pdf_service: FallbackPDFService,
        llm_service: LLMService,
        cache_service: CacheService,
        download_semaphore: asyncio.Semaphore,
        llm_semaphore: asyncio.Semaphore,
    ):
        """Initialize paper processor.

        Args:
            fallback_pdf_service: Multi-backend PDF service
            llm_service: LLM extraction service
            cache_service: Caching service
            download_semaphore: Semaphore for download concurrency
            llm_semaphore: Semaphore for LLM concurrency
        """
        self.fallback_pdf_service = fallback_pdf_service
        self.llm_service = llm_service
        self.cache_service = cache_service
        self.download_sem = download_semaphore
        self.llm_sem = llm_semaphore

    async def process(
        self,
        paper: PaperMetadata,
        targets: List[ExtractionTarget],
        worker_id: int,
    ) -> Optional[ExtractedPaper]:
        """Process single paper with full pipeline.

        1. Check extraction cache
        2. If not cached:
           a. Download + convert PDF (Phase 2.5)
           b. Extract with LLM
           c. Cache result

        Args:
            paper: Paper to process
            targets: Extraction targets
            worker_id: Worker ID (for logging)

        Returns:
            ExtractedPaper or None if processing failed
        """
        logger.debug(
            "processing_paper_start",
            worker_id=worker_id,
            paper_id=paper.paper_id,
            title=paper.title[:50] if paper.title else "Untitled",
        )

        # Check extraction cache (Phase 3)
        cached_extraction = self.cache_service.get_extraction(paper.paper_id, targets)

        if cached_extraction:
            logger.info(
                "extraction_cache_hit", worker_id=worker_id, paper_id=paper.paper_id
            )
            return ExtractedPaper(
                metadata=paper,
                extraction=cached_extraction,
                pdf_available=True,  # Assume PDF was available when cached
            )

        # Not cached - process from scratch
        markdown_content, pdf_available = await self._extract_content(paper, worker_id)

        if not markdown_content:
            logger.error(
                "no_content_available", worker_id=worker_id, paper_id=paper.paper_id
            )
            return None

        # Extract with LLM
        return await self._extract_with_llm(
            paper, targets, markdown_content, pdf_available, worker_id
        )

    async def _extract_content(
        self, paper: PaperMetadata, worker_id: int
    ) -> tuple[str, bool]:
        """Extract content from paper PDF or fallback to abstract.

        Args:
            paper: Paper to extract content from
            worker_id: Worker ID for logging

        Returns:
            Tuple of (markdown_content, pdf_available)
        """
        markdown_content = ""
        pdf_available = False

        if paper.open_access_pdf:
            async with self.download_sem:
                pdf_start = time.time()
                try:
                    # Phase 2.5 FallbackPDFService automatically tries:
                    # PyMuPDF → pdfplumber → marker → pandoc
                    pdf_result = await self.fallback_pdf_service.extract_with_fallback(
                        pdf_path=Path(str(paper.open_access_pdf))
                    )

                    if pdf_result and pdf_result.success and pdf_result.markdown:
                        markdown_content = pdf_result.markdown
                        pdf_available = True

                        # Track successful PDF conversion
                        backend_name = (
                            pdf_result.backend.value
                            if pdf_result.backend
                            else "unknown"
                        )
                        PDF_CONVERSIONS.labels(
                            backend=backend_name, status="success"
                        ).inc()
                        PDF_DOWNLOADS.labels(status="success").inc()

                        # Track processing duration
                        PAPER_PROCESSING_DURATION.labels(stage="conversion").observe(
                            time.time() - pdf_start
                        )

                        logger.info(
                            "pdf_extraction_complete",
                            worker_id=worker_id,
                            paper_id=paper.paper_id,
                            backend=backend_name,
                            quality_score=pdf_result.quality_score or 0.0,
                        )
                    else:
                        error_msg = pdf_result.error if pdf_result else "Unknown error"
                        PDF_DOWNLOADS.labels(status="failed").inc()
                        PDF_CONVERSIONS.labels(backend="unknown", status="failed").inc()
                        raise Exception(f"PDF extraction failed: {error_msg}")

                except Exception as e:
                    EXTRACTION_ERRORS.labels(error_type="conversion").inc()
                    logger.error(
                        "pdf_extraction_failed",
                        worker_id=worker_id,
                        paper_id=paper.paper_id,
                        error=str(e),
                    )

        # Fallback to abstract if no PDF content
        if not markdown_content and paper.abstract:
            markdown_content = f"# {paper.title or 'Untitled'}\n\n{paper.abstract}"
            pdf_available = False
            logger.warning(
                "using_abstract_fallback",
                worker_id=worker_id,
                paper_id=paper.paper_id,
            )

        return markdown_content, pdf_available

    async def _extract_with_llm(
        self,
        paper: PaperMetadata,
        targets: List[ExtractionTarget],
        markdown_content: str,
        pdf_available: bool,
        worker_id: int,
    ) -> Optional[ExtractedPaper]:
        """Extract information using LLM.

        Args:
            paper: Paper metadata
            targets: Extraction targets
            markdown_content: Content to extract from
            pdf_available: Whether PDF was available
            worker_id: Worker ID for logging

        Returns:
            ExtractedPaper or None if extraction failed
        """
        async with self.llm_sem:
            try:
                extraction = await self.llm_service.extract(
                    markdown_content, targets, paper
                )

                logger.info(
                    "llm_extraction_complete",
                    worker_id=worker_id,
                    paper_id=paper.paper_id,
                )

                # Cache extraction result (Phase 3)
                self.cache_service.set_extraction(paper.paper_id, targets, extraction)

                return ExtractedPaper(
                    metadata=paper, extraction=extraction, pdf_available=pdf_available
                )

            except Exception as e:
                logger.error(
                    "llm_extraction_failed",
                    worker_id=worker_id,
                    paper_id=paper.paper_id,
                    error=str(e),
                )
                return None
