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
    with patch(
        "src.services.pdf_extractors.fallback_service.PyMuPDFExtractor",
        return_value=mock_extractors["pymupdf"],
    ), patch(
        "src.services.pdf_extractors.fallback_service.PDFPlumberExtractor",
        return_value=mock_extractors["pdfplumber"],
    ), patch(
        "src.services.pdf_extractors.fallback_service.PandocExtractor",
        return_value=Mock(validate_setup=Mock(return_value=False)),
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
