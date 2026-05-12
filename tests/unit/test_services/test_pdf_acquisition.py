"""Unit tests for the shared acquire_pdf helper (Phase 9.5 REQ-9.5.1.1).

Verifies that the helper:

- Returns ``None`` when the paper has no ``open_access_pdf`` URL.
- Delegates to ``PDFService.download_pdf`` with the URL stringified and
  the paper_id forwarded (i.e. it does NOT cast the URL to ``Path``,
  which is the bug PR #156 documented).
- Propagates download errors so callers can apply their own fallback.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src.models.paper import PaperMetadata
from src.services.pdf_acquisition import acquire_pdf
from src.utils.exceptions import PDFDownloadError


def _make_paper(
    pdf_url: str | None = "https://arxiv.org/pdf/2605.06641v1",
) -> PaperMetadata:
    return PaperMetadata(
        paper_id="test-paper-1",
        title="Test Paper",
        abstract="Test abstract",
        url="https://example.com/paper",
        open_access_pdf=pdf_url,
    )


@pytest.mark.asyncio
async def test_returns_none_for_paper_without_pdf_url():
    """When paper has no PDF URL, helper returns None and never downloads."""
    pdf_service = Mock()
    pdf_service.download_pdf = AsyncMock()

    result = await acquire_pdf(pdf_service, _make_paper(pdf_url=None))

    assert result is None
    pdf_service.download_pdf.assert_not_called()


@pytest.mark.asyncio
async def test_delegates_to_download_pdf_with_string_url_not_path():
    """Helper passes URL as a string, never casting it to Path.

    This is the regression guard for PR #156's URL-as-Path bug — the prior
    code path called ``Path(str(url))`` which collapsed ``https://`` to
    ``https:/``. The helper MUST send the raw string to download_pdf.
    """
    expected_path = Path("/tmp/downloaded.pdf")
    pdf_service = Mock()
    pdf_service.download_pdf = AsyncMock(return_value=expected_path)

    result = await acquire_pdf(pdf_service, _make_paper())

    assert result == expected_path
    pdf_service.download_pdf.assert_awaited_once_with(
        url="https://arxiv.org/pdf/2605.06641v1",
        paper_id="test-paper-1",
    )
    # Critical regression guard: the URL passed must contain '://', not ':/'
    call_url = pdf_service.download_pdf.await_args.kwargs["url"]
    assert call_url.startswith("https://"), (
        "URL must preserve scheme separator '://'; mangled to "
        f"{call_url!r} would reproduce the original bug"
    )


@pytest.mark.asyncio
async def test_propagates_download_errors():
    """Download failures bubble up so callers can apply abstract fallback."""
    pdf_service = Mock()
    pdf_service.download_pdf = AsyncMock(
        side_effect=PDFDownloadError("HTTP 404 for https://example.com/missing")
    )

    with pytest.raises(PDFDownloadError, match="HTTP 404"):
        await acquire_pdf(pdf_service, _make_paper())
