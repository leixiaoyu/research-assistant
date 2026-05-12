"""Shared PDF acquisition: materialize a paper's PDF URL into a local Path.

Phase 9.5 Workstream A (REQ-9.5.1.1) — eliminates the URL-as-Path bug
documented in PR #156. Both the synchronous extraction path
(:class:`src.services.extraction_service.ExtractionService`) and the
concurrent path (:class:`src.orchestration.paper_processor.PaperProcessor`
via :class:`src.orchestration.concurrent_pipeline.ConcurrentPipeline`)
acquire PDFs through this single helper so they cannot diverge again.
"""

from pathlib import Path
from typing import Optional

import structlog

from src.models.paper import PaperMetadata
from src.services.pdf_service import PDFService

logger = structlog.get_logger()


async def acquire_pdf(
    pdf_service: PDFService,
    paper: PaperMetadata,
) -> Optional[Path]:
    """Materialize ``paper.open_access_pdf`` into a downloaded local Path.

    Returns ``None`` when the paper has no PDF URL — callers MUST handle
    this case (typically by falling back to abstract-only processing).
    Propagates typed exceptions from the underlying download so callers
    can apply their own fallback strategy:

    - :class:`src.utils.exceptions.PDFDownloadError` — HTTP/network failure
    - :class:`src.utils.exceptions.FileSizeError` — PDF exceeds size cap
    - :class:`src.utils.exceptions.PDFValidationError` — invalid PDF bytes

    Args:
        pdf_service: PDF service providing the ``download_pdf`` primitive.
        paper: Paper whose ``open_access_pdf`` URL to materialize.

    Returns:
        Local ``Path`` to the downloaded PDF, or ``None`` if the paper has
        no PDF URL.
    """
    if not paper.open_access_pdf:
        return None

    return await pdf_service.download_pdf(
        url=str(paper.open_access_pdf),
        paper_id=paper.paper_id,
    )
