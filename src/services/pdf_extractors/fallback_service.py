"""Fallback PDF Service for Phase 2.5: Reliability Improvements.

This service orchestrates the PDF extraction process by attempting multiple
backends in a configurable order (Fallback Chain). It validates the quality
of each extraction and returns the best result.
"""

from typing import List
from pathlib import Path
import structlog

from src.models.config import PDFSettings
from src.models.pdf_extraction import (
    PDFExtractionResult,
    PDFBackend,
    ExtractionMetadata,
)
from src.services.pdf_extractors.base import PDFExtractor
from src.services.pdf_extractors.validators.quality_validator import QualityValidator
from src.utils.exceptions import InvalidPDFPathError

# Import extractors
from src.services.pdf_extractors.pymupdf_extractor import PyMuPDFExtractor
from src.services.pdf_extractors.pdfplumber_extractor import PDFPlumberExtractor
from src.services.pdf_extractors.pandoc_extractor import PandocExtractor

logger = structlog.get_logger()


_REJECTED_URL_SCHEMES: tuple[str, ...] = (
    # Schemes the original PR #156 bug could produce by casting URL-typed
    # values to Path():
    "http:",
    "https:",
    # Other URI schemes a future caller might mistakenly hand to an
    # extractor. None of these are valid local file paths, and accepting
    # them risks information disclosure (file://) or arbitrary fetches
    # (ftp://, data:, javascript:) downstream:
    "file:",
    "ftp:",
    "ftps:",
    "data:",
    "javascript:",
    "gopher:",
)


def _reject_url_path(pdf_path: Path) -> None:
    """Defense-in-depth guard against the URL-as-Path bug (REQ-9.5.1.2).

    PR #156 documented that the orchestration layer was casting
    ``open_access_pdf`` URLs to ``Path()`` directly, which collapses
    ``https://`` to ``https:/`` and fails downstream as a non-existent
    file. The canonical fix is :func:`src.services.pdf_acquisition.acquire_pdf`
    which downloads the URL first. This guard catches any future caller
    that bypasses ``acquire_pdf`` so the bug cannot recur silently.

    The check covers more than http(s) — see :data:`_REJECTED_URL_SCHEMES`
    — because handing other URI schemes (``file://``, ``ftp://``, etc.)
    to a PDF extractor is never correct and a few of them have security
    implications if accepted by the underlying backend.
    """
    path_str = str(pdf_path).lower()
    if path_str.startswith(_REJECTED_URL_SCHEMES):
        raise InvalidPDFPathError(
            f"PDF path is a URL, not a local file: {pdf_path!r}. "
            "Call src.services.pdf_acquisition.acquire_pdf() to download "
            "the URL to a local Path before invoking extraction."
        )


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

        # Log health status at startup
        health = self.get_health_status()
        logger.info(
            "fallback_pdf_service_initialized",
            available_extractors=health["available_extractors"],
            enabled_extractors=health["enabled_extractors"],
            ready_extractors=health["enabled_and_available"],
            healthy=health["healthy"],
        )

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
                logger.info("extractor_initialized", backend=extractor.name.value)
            else:
                logger.warning("extractor_unavailable", backend=extractor.name.value)

    def get_health_status(self) -> dict:
        """Get health status of PDF extraction service.

        Returns:
            Dictionary with:
            - available_extractors: List of available backend names
            - enabled_extractors: List of enabled backend names from config
            - total_available: Count of available extractors
            - total_enabled: Count of enabled extractors
            - healthy: Boolean indicating if at least one extractor is enabled
        """
        enabled_backends = [
            cfg.backend for cfg in self.config.fallback_chain if cfg.enabled
        ]
        available_backends = list(self.extractors.keys())

        enabled_and_available = [
            backend for backend in enabled_backends if backend in available_backends
        ]

        return {
            "available_extractors": available_backends,
            "enabled_extractors": enabled_backends,
            "enabled_and_available": enabled_and_available,
            "total_available": len(available_backends),
            "total_enabled": len(enabled_backends),
            "total_ready": len(enabled_and_available),
            "healthy": len(enabled_and_available) > 0,
        }

    async def extract_with_fallback(self, pdf_path: Path) -> PDFExtractionResult:
        """
        Attempt extraction using the configured fallback chain.

        Args:
            pdf_path: Path to PDF file (MUST be a local file, NOT a URL —
                see :func:`src.services.pdf_acquisition.acquire_pdf`)

        Returns:
            Best PDFExtractionResult obtained from the chain

        Raises:
            InvalidPDFPathError: If ``pdf_path`` is a URL rather than a
                local file path (Phase 9.5 REQ-9.5.1.2 type guard).
        """
        # Phase 9.5 REQ-9.5.1.2: defense-in-depth against URL-as-Path bug
        _reject_url_path(pdf_path)

        results: List[PDFExtractionResult] = []

        # Filter enabled backends from config
        chain = [
            cfg
            for cfg in self.config.fallback_chain
            if cfg.enabled and cfg.backend in self.extractors
        ]

        if not chain:
            # Log health status for debugging
            health = self.get_health_status()
            logger.error(
                "no_enabled_extractors",
                available=health["available_extractors"],
                enabled_in_config=health["enabled_extractors"],
                enabled_and_available=health["enabled_and_available"],
            )
            return PDFExtractionResult(
                success=False,
                error="No enabled PDF extractors available",
                metadata=ExtractionMetadata(backend=PDFBackend.TEXT_ONLY),
            )

        for backend_cfg in chain:
            extractor = self.extractors[backend_cfg.backend]

            logger.info(
                "attempting_extraction",
                backend=backend_cfg.backend,
                pdf_path=str(pdf_path),
                timeout=backend_cfg.timeout_seconds,
            )

            try:
                # TODO: Enforce timeout here using asyncio.wait_for in Phase 3
                # For now, backends handle their own timeouts or are fast enough
                result = await extractor.extract(pdf_path)

                if result.success and result.markdown:
                    # Score the result
                    score = self.validator.score_extraction(result.markdown, pdf_path)
                    result.quality_score = score
                    results.append(result)

                    logger.info(
                        "extraction_attempt_finished",
                        backend=backend_cfg.backend,
                        success=True,
                        quality_score=score,
                    )

                    # Check stop condition
                    if self.config.stop_on_success and score >= backend_cfg.min_quality:
                        logger.info(
                            "fallback_chain_success",
                            backend=backend_cfg.backend,
                            reason="quality_threshold_met",
                        )
                        return result

                else:
                    logger.warning(
                        "extraction_attempt_failed",
                        backend=backend_cfg.backend,
                        error=result.error,
                    )
                    # Add failed result for debugging
                    results.append(result)

            except Exception as e:
                logger.error(
                    "extraction_unexpected_error",
                    backend=backend_cfg.backend,
                    error=str(e),
                )
                results.append(
                    PDFExtractionResult(
                        success=False,
                        metadata=ExtractionMetadata(
                            backend=PDFBackend(backend_cfg.backend)
                        ),
                        error=str(e),
                    )
                )

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
                score=best.quality_score,
            )
            return best

        # Total failure
        logger.error("fallback_chain_failed_all_backends", pdf_path=str(pdf_path))
        return PDFExtractionResult(
            success=False,
            metadata=ExtractionMetadata(backend=PDFBackend.TEXT_ONLY),
            error="All extraction backends failed",
        )
