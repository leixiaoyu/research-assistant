"""Extended tests for PDF extractors base and fallback service."""

import sys
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from src.services.pdf_extractors.base import PDFExtractor
from src.services.pdf_extractors.fallback_service import FallbackPDFService
from src.models.pdf_extraction import (
    PDFBackend,
    PDFExtractionResult,
    ExtractionMetadata,
)
from src.models.config import PDFSettings, PDFBackendConfig


class ConcreteExtractor(PDFExtractor):
    @property
    def name(self) -> PDFBackend:
        return PDFBackend.TEXT_ONLY

    async def extract(self, pdf_path: Path) -> PDFExtractionResult:
        return PDFExtractionResult(
            success=True, metadata=ExtractionMetadata(backend=self.name)
        )

    def validate_setup(self) -> bool:
        return True


@pytest.fixture
def base_extractor():
    return ConcreteExtractor()


def test_base_get_page_count(base_extractor):
    """Test the shared _get_page_count implementation."""
    # Mock fitz module before it's imported
    mock_fitz = MagicMock()
    mock_doc = MagicMock()
    mock_doc.__len__.return_value = 10
    mock_fitz.open.return_value = mock_doc

    with patch.dict('sys.modules', {'fitz': mock_fitz}):
        assert base_extractor._get_page_count(Path("test.pdf")) == 10
        mock_doc.close.assert_called_once()

    # Test failure
    mock_fitz_error = MagicMock()
    mock_fitz_error.open.side_effect = Exception("Error")

    with patch.dict('sys.modules', {'fitz': mock_fitz_error}):
        assert base_extractor._get_page_count(Path("test.pdf")) == 0


@pytest.mark.asyncio
async def test_fallback_service_no_chain():
    """Test FallbackPDFService when no backends are enabled."""
    settings = PDFSettings(fallback_chain=[])
    service = FallbackPDFService(settings)

    result = await service.extract_with_fallback(Path("test.pdf"))
    assert result.success is False
    assert result.backend == PDFBackend.TEXT_ONLY
    assert "No enabled PDF extractors" in result.error


@pytest.mark.asyncio
async def test_fallback_service_exception_in_loop():
    """Test FallbackPDFService handling unexpected exceptions in the loop."""
    settings = PDFSettings(
        fallback_chain=[PDFBackendConfig(backend="pymupdf", enabled=True)],
        stop_on_success=True,
    )

    with patch(
        "src.services.pdf_extractors.fallback_service.PyMuPDFExtractor"
    ) as mock_cls:
        mock_inst = mock_cls.return_value
        mock_inst.validate_setup.return_value = True
        mock_inst.name = PDFBackend.PYMUPDF
        # Mock crash during extract
        mock_inst.extract.side_effect = Exception("Crashed")

        service = FallbackPDFService(settings)
        result = await service.extract_with_fallback(Path("test.pdf"))

        assert result.success is False
        assert "All extraction backends failed" in result.error
