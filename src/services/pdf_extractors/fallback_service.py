"""Fallback PDF Service for Phase 2.5: Reliability Improvements.

This service orchestrates the PDF extraction process by attempting multiple
backends in a configurable order (Fallback Chain). It validates the quality
of each extraction and returns the best result.
"""

from typing import List, Optional
from pathlib import Path
import structlog

from src.models.config import PDFSettings, PDFBackendConfig
from src.models.pdf_extraction import PDFExtractionResult, PDFBackend
from src.services.pdf_extractors.base import PDFExtractor
from src.services.pdf_extractors.validators.quality_validator import QualityValidator

# Import extractors
from src.services.pdf_extractors.pymupdf_extractor import PyMuPDFExtractor
from src.services.pdf_extractors.pdfplumber_extractor import PDFPlumberExtractor
from src.services.pdf_extractors.pandoc_extractor import PandocExtractor

logger = structlog.get_logger()


class FallbackPDFService:
    """
    Orchestrates PDF extraction using a fallback chain of backends.

    Features:
    - Configurable backend order and timeouts
    - Quality scoring for each attempt
    - "Stop on success" or "Try all and pick best" strategies
    - Graceful degradation to text-only failure
    """

    def __init__(self, config: PDFSettings):
        """
        Initialize fallback service.

        Args:
            config: PDF settings containing fallback chain configuration
        """
        self.config = config
        self.validator = QualityValidator()
        self.extractors: dict[str, PDFExtractor] = {}
        self._initialize_extractors()

    def _initialize_extractors(self):
        """Initialize available extraction backends."""
        # Register all supported backends
        # Note: MarkerExtractor is omitted for now as it's legacy/heavy
        available = [
            PyMuPDFExtractor(),
            PDFPlumberExtractor(),
            PandocExtractor(),
        ]

        for extractor in available:
            if extractor.validate_setup():
                self.extractors[extractor.name.value] = extractor
                logger.info("extractor_initialized", backend=extractor.name)
            else:
                logger.warning("extractor_unavailable", backend=extractor.name)

    async def extract_with_fallback(self, pdf_path: Path) -> PDFExtractionResult:
        """
        Attempt extraction using the configured fallback chain.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Best PDFExtractionResult obtained from the chain
        """
        results: List[PDFExtractionResult] = []

        # Filter enabled backends from config
        chain = [
            cfg for cfg in self.config.fallback_chain
            if cfg.enabled and cfg.backend in self.extractors
        ]

        if not chain:
            return PDFExtractionResult(
                success=False,
                error="No enabled PDF extractors available",
                metadata={"backend": PDFBackend.TEXT_ONLY}
            )

        for backend_cfg in chain:
            extractor = self.extractors[backend_cfg.backend]
            
            logger.info(
                "attempting_extraction",
                backend=backend_cfg.backend,
                pdf_path=str(pdf_path),
                timeout=backend_cfg.timeout_seconds
            )

            try:
                # TODO: Enforce timeout here using asyncio.wait_for in Phase 3
                # For now, backends handle their own timeouts or are fast enough
                result = await extractor.extract(pdf_path)

                if result.success and result.markdown:
                    # Score the result
                    score = self.validator.score_extraction(
                        result.markdown,
                        pdf_path
                    )
                    result.quality_score = score
                    results.append(result)

                    logger.info(
                        "extraction_attempt_finished",
                        backend=backend_cfg.backend,
                        success=True,
                        quality_score=score
                    )

                    # Check stop condition
                    if (
                        self.config.stop_on_success
                        and score >= backend_cfg.min_quality
                    ):
                        logger.info(
                            "fallback_chain_success",
                            backend=backend_cfg.backend,
                            reason="quality_threshold_met"
                        )
                        return result

                else:
                    logger.warning(
                        "extraction_attempt_failed",
                        backend=backend_cfg.backend,
                        error=result.error
                    )
                    # Add failed result for debugging
                    results.append(result)

            except Exception as e:
                logger.error(
                    "extraction_unexpected_error",
                    backend=backend_cfg.backend,
                    error=str(e)
                )
                results.append(PDFExtractionResult(
                    success=False,
                    metadata={"backend": PDFBackend(backend_cfg.backend)},
                    error=str(e)
                ))

        # If we get here, either no result met the threshold (stop_on_success=True)
        # or we tried everything (stop_on_success=False)
        
        # Filter for successful results
        successful_results = [r for r in results if r.success]

        if successful_results:
            # Pick best by score
            best = max(successful_results, key=lambda r: r.quality_score)
            logger.info(
                "fallback_chain_completed",
                selected_backend=best.backend,
                score=best.quality_score
            )
            return best

        # Total failure
        logger.error("fallback_chain_failed_all_backends", pdf_path=str(pdf_path))
        return PDFExtractionResult(
            success=False,
            metadata={"backend": PDFBackend.TEXT_ONLY},
            error="All extraction backends failed"
        )
