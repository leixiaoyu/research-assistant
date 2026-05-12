"""Shared PDF acquisition: materialize a URL into a local Path.

Phase 9.5 Workstream A (REQ-9.5.1.1) — eliminates the URL-as-Path bug
documented in PR #156. Both the synchronous extraction path
(:class:`src.services.extraction_service.ExtractionService`) and the
concurrent path (:class:`src.orchestration.paper_processor.PaperProcessor`
via :class:`src.orchestration.concurrent_pipeline.ConcurrentPipeline`)
acquire PDFs through this single helper so they cannot diverge again.
"""

from pathlib import Path

from src.services.pdf_service import PDFService


async def acquire_pdf(
    pdf_service: PDFService,
    pdf_url: str,
    paper_id: str,
) -> Path:
    """Materialize a PDF URL into a downloaded local Path.

    Callers are responsible for first verifying the paper actually has a
    URL (e.g. ``if paper.open_access_pdf:``); passing an empty or invalid
    URL here will surface as ``PDFDownloadError`` from the underlying
    download primitive.

    Propagates typed exceptions from the underlying download so callers
    can apply their own fallback strategy:

    - :class:`src.utils.exceptions.PDFDownloadError` — HTTP/network failure
    - :class:`src.utils.exceptions.FileSizeError` — PDF exceeds size cap
    - :class:`src.utils.exceptions.PDFValidationError` — invalid PDF bytes

    Args:
        pdf_service: PDF service providing the ``download_pdf`` primitive.
        pdf_url: HTTPS URL of the PDF to download. Must be a string —
            passing a Pydantic ``HttpUrl`` works because Pydantic
            stringifies cleanly, but callers should ``str(...)``-coerce
            for clarity at the call site.
        paper_id: Stable identifier used to build the local filename.

    Returns:
        Local ``Path`` to the downloaded PDF. The caller can pass this
        directly to any extractor without intermediate ``Path()``
        casting (which is the bug this helper exists to prevent).
    """
    return await pdf_service.download_pdf(url=pdf_url, paper_id=paper_id)
