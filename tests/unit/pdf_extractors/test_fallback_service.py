"""Unit tests for FallbackPDFService."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path

from src.models.config import PDFSettings, PDFBackendConfig
from src.models.pdf_extraction import (
    PDFExtractionResult,
    PDFBackend,
    ExtractionMetadata,
)
from src.services.pdf_extractors.fallback_service import FallbackPDFService
from src.utils.exceptions import InvalidPDFPathError


@pytest.fixture
def pdf_settings():
    return PDFSettings(
        fallback_chain=[
            PDFBackendConfig(backend="pymupdf", timeout_seconds=10, min_quality=0.5),
            PDFBackendConfig(backend="pdfplumber", timeout_seconds=10, min_quality=0.5),
        ],
        stop_on_success=True,
    )


@pytest.fixture
def mock_extractors():
    pymupdf = Mock()
    pymupdf.name = PDFBackend.PYMUPDF
    pymupdf.validate_setup.return_value = True

    pdfplumber = Mock()
    pdfplumber.name = PDFBackend.PDFPLUMBER
    pdfplumber.validate_setup.return_value = True

    return {"pymupdf": pymupdf, "pdfplumber": pdfplumber}


@pytest.fixture
def service(pdf_settings, mock_extractors):
    with (
        patch(
            "src.services.pdf_extractors.fallback_service.PyMuPDFExtractor",
            return_value=mock_extractors["pymupdf"],
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PDFPlumberExtractor",
            return_value=mock_extractors["pdfplumber"],
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PandocExtractor",
            return_value=Mock(validate_setup=Mock(return_value=False)),
        ),
    ):

        return FallbackPDFService(pdf_settings)


@pytest.mark.asyncio
async def test_fallback_success_first_try(service, mock_extractors):
    """Test success on first backend"""
    mock_result = PDFExtractionResult(
        success=True,
        markdown="Valid content",
        metadata=ExtractionMetadata(backend=PDFBackend.PYMUPDF),
    )
    mock_extractors["pymupdf"].extract = AsyncMock(return_value=mock_result)

    with patch.object(service.validator, "score_extraction", return_value=0.8):

        result = await service.extract_with_fallback(Path("test.pdf"))

        assert result.success is True
        assert result.backend == PDFBackend.PYMUPDF
        assert result.quality_score == 0.8
        mock_extractors["pdfplumber"].extract.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_to_second_backend(service, mock_extractors):
    """Test fallback when first backend fails"""
    fail_result = PDFExtractionResult(
        success=False,
        error="Failed",
        metadata=ExtractionMetadata(backend=PDFBackend.PYMUPDF),
    )
    success_result = PDFExtractionResult(
        success=True,
        markdown="Valid content",
        metadata=ExtractionMetadata(backend=PDFBackend.PDFPLUMBER),
    )

    mock_extractors["pymupdf"].extract = AsyncMock(return_value=fail_result)
    mock_extractors["pdfplumber"].extract = AsyncMock(return_value=success_result)

    with patch.object(service.validator, "score_extraction", return_value=0.7):
        result = await service.extract_with_fallback(Path("test.pdf"))

        assert result.success is True
        assert result.backend == PDFBackend.PDFPLUMBER
        mock_extractors["pdfplumber"].extract.assert_called_once()


@pytest.mark.asyncio
async def test_fallback_low_quality(service, mock_extractors):
    """Test fallback when first backend produces low quality"""
    low_quality_result = PDFExtractionResult(
        success=True,
        markdown="Bad content",
        metadata=ExtractionMetadata(backend=PDFBackend.PYMUPDF),
    )
    high_quality_result = PDFExtractionResult(
        success=True,
        markdown="Good content",
        metadata=ExtractionMetadata(backend=PDFBackend.PDFPLUMBER),
    )

    mock_extractors["pymupdf"].extract = AsyncMock(return_value=low_quality_result)
    mock_extractors["pdfplumber"].extract = AsyncMock(return_value=high_quality_result)

    # First scores 0.2 (below 0.5 threshold), second scores 0.9
    with patch.object(service.validator, "score_extraction", side_effect=[0.2, 0.9]):
        result = await service.extract_with_fallback(Path("test.pdf"))

        assert result.success is True
        assert result.backend == PDFBackend.PDFPLUMBER
        assert result.quality_score == 0.9


@pytest.mark.asyncio
async def test_all_backends_fail(service, mock_extractors):
    """Test when all backends fail"""
    fail_result = PDFExtractionResult(
        success=False, error="Failed", metadata={"backend": PDFBackend.PYMUPDF}
    )

    mock_extractors["pymupdf"].extract = AsyncMock(return_value=fail_result)
    mock_extractors["pdfplumber"].extract = AsyncMock(return_value=fail_result)

    result = await service.extract_with_fallback(Path("test.pdf"))

    assert result.success is False
    assert result.backend == PDFBackend.TEXT_ONLY


@pytest.mark.asyncio
async def test_multiple_successful_backends_picks_best(service, mock_extractors):
    """Test multiple backends - picks one with highest quality"""
    result1 = PDFExtractionResult(
        success=True,
        markdown="Content 1",
        metadata=ExtractionMetadata(backend=PDFBackend.PYMUPDF),
    )
    result2 = PDFExtractionResult(
        success=True,
        markdown="Content 2",
        metadata=ExtractionMetadata(backend=PDFBackend.PDFPLUMBER),
    )

    mock_extractors["pymupdf"].extract = AsyncMock(return_value=result1)
    mock_extractors["pdfplumber"].extract = AsyncMock(return_value=result2)

    # First scores 0.6, second scores 0.9 (both pass threshold)
    # stop_on_success=True means we still try both to compare
    service.config.stop_on_success = False  # Force trying both
    with patch.object(service.validator, "score_extraction", side_effect=[0.6, 0.9]):
        result = await service.extract_with_fallback(Path("test.pdf"))

        assert result.success is True
        assert result.backend == PDFBackend.PDFPLUMBER
        assert result.quality_score == 0.9  # Higher quality selected


def test_get_health_status_all_available(service):
    """Test health status when all extractors are available"""
    health = service.get_health_status()

    assert health["healthy"] is True
    assert "pymupdf" in health["available_extractors"]
    assert "pdfplumber" in health["available_extractors"]
    assert health["total_available"] == 2
    assert health["total_enabled"] == 2
    assert health["total_ready"] == 2


def test_get_health_status_none_available():
    """Test health status when no extractors are available"""
    settings = PDFSettings(
        fallback_chain=[
            PDFBackendConfig(backend="pymupdf", enabled=True),
        ],
    )

    with (
        patch(
            "src.services.pdf_extractors.fallback_service.PyMuPDFExtractor",
            return_value=Mock(
                name=PDFBackend.PYMUPDF, validate_setup=Mock(return_value=False)
            ),
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PDFPlumberExtractor",
            return_value=Mock(
                name=PDFBackend.PDFPLUMBER, validate_setup=Mock(return_value=False)
            ),
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PandocExtractor",
            return_value=Mock(
                name=PDFBackend.PANDOC, validate_setup=Mock(return_value=False)
            ),
        ),
    ):
        service = FallbackPDFService(settings)
        health = service.get_health_status()

        assert health["healthy"] is False
        assert health["total_available"] == 0
        assert health["total_ready"] == 0


def test_get_health_status_some_enabled_some_disabled():
    """Test health status when some extractors are disabled in config"""
    settings = PDFSettings(
        fallback_chain=[
            PDFBackendConfig(backend="pymupdf", enabled=True),
            PDFBackendConfig(backend="pdfplumber", enabled=False),
        ],
    )

    # Create mocks with proper name attribute (not Mock's special name parameter)
    pymupdf_mock = Mock()
    pymupdf_mock.name = PDFBackend.PYMUPDF
    pymupdf_mock.validate_setup.return_value = True

    pdfplumber_mock = Mock()
    pdfplumber_mock.name = PDFBackend.PDFPLUMBER
    pdfplumber_mock.validate_setup.return_value = True

    pandoc_mock = Mock()
    pandoc_mock.name = PDFBackend.PANDOC
    pandoc_mock.validate_setup.return_value = False

    with (
        patch(
            "src.services.pdf_extractors.fallback_service.PyMuPDFExtractor",
            return_value=pymupdf_mock,
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PDFPlumberExtractor",
            return_value=pdfplumber_mock,
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PandocExtractor",
            return_value=pandoc_mock,
        ),
    ):
        service = FallbackPDFService(settings)
        health = service.get_health_status()

        assert health["healthy"] is True
        assert health["total_available"] == 2
        assert health["total_enabled"] == 1
        assert health["total_ready"] == 1
        assert "pymupdf" in health["enabled_and_available"]
        assert "pdfplumber" not in health["enabled_and_available"]


@pytest.mark.asyncio
async def test_no_enabled_extractors_returns_error():
    """Test that no enabled extractors returns proper error (Issue I3 fix)"""
    settings = PDFSettings(
        fallback_chain=[
            PDFBackendConfig(backend="pymupdf", enabled=False),
            PDFBackendConfig(backend="pdfplumber", enabled=False),
        ],
    )

    # Create mocks with proper name attribute
    pymupdf_mock = Mock()
    pymupdf_mock.name = PDFBackend.PYMUPDF
    pymupdf_mock.validate_setup.return_value = True

    pdfplumber_mock = Mock()
    pdfplumber_mock.name = PDFBackend.PDFPLUMBER
    pdfplumber_mock.validate_setup.return_value = True

    pandoc_mock = Mock()
    pandoc_mock.name = PDFBackend.PANDOC
    pandoc_mock.validate_setup.return_value = False

    with (
        patch(
            "src.services.pdf_extractors.fallback_service.PyMuPDFExtractor",
            return_value=pymupdf_mock,
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PDFPlumberExtractor",
            return_value=pdfplumber_mock,
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PandocExtractor",
            return_value=pandoc_mock,
        ),
    ):
        service = FallbackPDFService(settings)
        result = await service.extract_with_fallback(Path("test.pdf"))

        assert result.success is False
        assert result.error == "No enabled PDF extractors available"
        assert result.backend == PDFBackend.TEXT_ONLY


@pytest.mark.asyncio
async def test_enabled_but_not_installed_extractors():
    """Test that enabled extractors that aren't installed are skipped"""
    settings = PDFSettings(
        fallback_chain=[
            PDFBackendConfig(backend="pymupdf", enabled=True),
            PDFBackendConfig(backend="pdfplumber", enabled=True),
        ],
    )

    # Create mocks with proper name attribute
    # PyMuPDF not installed (validate_setup returns False)
    pymupdf_mock = Mock()
    pymupdf_mock.name = PDFBackend.PYMUPDF
    pymupdf_mock.validate_setup.return_value = False

    # PDFPlumber installed and working
    pdfplumber_mock = Mock()
    pdfplumber_mock.name = PDFBackend.PDFPLUMBER
    pdfplumber_mock.validate_setup.return_value = True
    pdfplumber_mock.extract = AsyncMock(
        return_value=PDFExtractionResult(
            success=True,
            markdown="Content",
            metadata=ExtractionMetadata(backend=PDFBackend.PDFPLUMBER),
        )
    )

    pandoc_mock = Mock()
    pandoc_mock.name = PDFBackend.PANDOC
    pandoc_mock.validate_setup.return_value = False

    with (
        patch(
            "src.services.pdf_extractors.fallback_service.PyMuPDFExtractor",
            return_value=pymupdf_mock,
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PDFPlumberExtractor",
            return_value=pdfplumber_mock,
        ),
        patch(
            "src.services.pdf_extractors.fallback_service.PandocExtractor",
            return_value=pandoc_mock,
        ),
    ):
        service = FallbackPDFService(settings)

        with patch.object(service.validator, "score_extraction", return_value=0.8):
            result = await service.extract_with_fallback(Path("test.pdf"))

        # Should succeed with pdfplumber even though pymupdf is not installed
        assert result.success is True
        assert result.backend == PDFBackend.PDFPLUMBER


# Phase 9.5 REQ-9.5.1.2 — defense-in-depth type guard at the extractor
# entry point. PR #156 documented the URL-as-Path bug; this guard ensures
# the bug cannot recur silently if a future caller bypasses acquire_pdf().


class TestExtractorRejectsUrlPath:
    """Type guard: extract_with_fallback MUST reject URL strings."""

    @pytest.mark.asyncio
    async def test_rejects_https_url_as_path(self, service):
        """A pdf_path that looks like an https URL raises InvalidPDFPathError."""
        with pytest.raises(InvalidPDFPathError, match="URL"):
            await service.extract_with_fallback(
                Path("https://arxiv.org/pdf/2605.06641v1")
            )

    @pytest.mark.asyncio
    async def test_rejects_http_url_as_path(self, service):
        """Plain http URLs are rejected too (defense-in-depth)."""
        with pytest.raises(InvalidPDFPathError, match="URL"):
            await service.extract_with_fallback(Path("http://example.com/paper.pdf"))

    @pytest.mark.asyncio
    async def test_rejects_collapsed_url_pattern(self, service):
        """The exact bug pattern (collapsed 'https:/' single slash) is caught.

        The original bug produced ``Path("https://...")`` whose string
        repr is ``"https:/..."`` (single slash). The guard matches both
        forms via lowercase-prefix check on ``http:``/``https:``.
        """
        with pytest.raises(InvalidPDFPathError, match="URL"):
            await service.extract_with_fallback(
                Path("https:/arxiv.org/pdf/2605.06641v1")
            )

    @pytest.mark.asyncio
    async def test_accepts_local_path(self, service, mock_extractors):
        """Local file paths pass the guard (regression check)."""
        mock_extractors["pymupdf"].extract = AsyncMock(
            return_value=PDFExtractionResult(
                success=True,
                markdown="ok",
                metadata=ExtractionMetadata(backend=PDFBackend.PYMUPDF),
            )
        )
        with patch.object(service.validator, "score_extraction", return_value=0.9):
            result = await service.extract_with_fallback(Path("/tmp/local.pdf"))
        assert result.success is True
