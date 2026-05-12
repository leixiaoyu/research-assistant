"""Unit tests for the shared acquire_pdf helper (Phase 9.5 REQ-9.5.1.1).

The helper is intentionally minimal: it stringifies the URL, forwards it
plus the paper_id to ``PDFService.download_pdf``, and returns the
resulting Path. Callers are responsible for the up-front
``if paper.open_access_pdf:`` guard. Tests verify:

- Helper passes URL as a plain string (never via ``Path()``, the bug
  that PR #156 documented).
- Returned Path is the one ``download_pdf`` produced — no Optional, no
  intermediate casting.
- Typed download exceptions propagate so callers can apply an abstract
  fallback strategy.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src.services.pdf_acquisition import acquire_pdf
from src.utils.exceptions import PDFDownloadError


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

    result = await acquire_pdf(
        pdf_service,
        "https://arxiv.org/pdf/2605.06641v1",
        "test-paper-1",
    )

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
async def test_returns_path_directly_no_optional():
    """Helper return type is non-Optional Path (Phase 9.5 review fix).

    The original signature returned Optional[Path] which forced callers
    to ``assert local_path is not None`` for type narrowing. The
    refactor pushes the URL-presence check up to the caller so this
    helper always returns a real Path.
    """
    pdf_service = Mock()
    pdf_service.download_pdf = AsyncMock(return_value=Path("/tmp/x.pdf"))

    result = await acquire_pdf(pdf_service, "https://x.example/y.pdf", "id-1")

    assert isinstance(result, Path)


@pytest.mark.asyncio
async def test_propagates_download_errors():
    """Download failures bubble up so callers can apply abstract fallback."""
    pdf_service = Mock()
    pdf_service.download_pdf = AsyncMock(
        side_effect=PDFDownloadError("HTTP 404 for https://example.com/missing")
    )

    with pytest.raises(PDFDownloadError, match="HTTP 404"):
        await acquire_pdf(pdf_service, "https://example.com/missing", "id-2")
