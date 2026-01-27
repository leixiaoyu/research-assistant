"""Unit tests for Pandoc Extractor."""

import pytest
import subprocess
from unittest.mock import patch
from pathlib import Path
from src.services.pdf_extractors.pandoc_extractor import PandocExtractor
from src.models.pdf_extraction import PDFBackend


@pytest.fixture
def extractor():
    return PandocExtractor()


def test_name(extractor):
    assert extractor.name == PDFBackend.PANDOC


def test_validate_setup(extractor):
    with patch("shutil.which", return_value="/usr/bin/pandoc"):
        assert extractor.validate_setup() is True

    with patch("shutil.which", return_value=None):
        assert extractor.validate_setup() is False


@pytest.mark.asyncio
async def test_extract_pandoc_not_found(extractor):
    with patch("shutil.which", return_value=None):
        result = await extractor.extract(Path("test.pdf"))
        assert result.success is False
        assert "not found" in result.error


@pytest.mark.asyncio
async def test_extract_success(extractor):
    with patch("shutil.which", return_value="/usr/bin/pandoc"):
        # Mock Path stats and operations
        with patch.object(Path, "stat") as mock_stat, patch.object(
            Path, "exists", return_value=True
        ), patch.object(Path, "read_text", return_value="Pandoc output"), patch.object(
            Path, "unlink"
        ):

            mock_stat.return_value.st_size = 1024

            # Mock subprocess and temp file
            with patch("subprocess.run") as mock_run, patch(
                "tempfile.NamedTemporaryFile"
            ) as mock_temp:

                mock_temp.return_value.__enter__.return_value.name = "/tmp/fake.md"
                mock_run.return_value.returncode = 0

                result = await extractor.extract(Path("test.pdf"))

                assert result.success is True
                assert result.markdown == "Pandoc output"
                assert result.backend == PDFBackend.PANDOC


@pytest.mark.asyncio
async def test_extract_timeout(extractor):
    with patch("shutil.which", return_value="/usr/bin/pandoc"):
        with patch.object(Path, "exists", return_value=True):
            with patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="pandoc", timeout=60),
            ):
                result = await extractor.extract(Path("test.pdf"))
                assert result.success is False
                assert "timed out" in result.error


@pytest.mark.asyncio
async def test_extract_error(extractor):
    with patch("shutil.which", return_value="/usr/bin/pandoc"):
        with patch.object(Path, "exists", return_value=True):
            # Mock CalledProcessError
            mock_error = subprocess.CalledProcessError(1, "pandoc")
            mock_error.stderr = b"Pandoc error message"

            with patch("subprocess.run", side_effect=mock_error):
                result = await extractor.extract(Path("test.pdf"))
                assert result.success is False
                assert "Pandoc failed" in result.error
                assert "Pandoc error message" in result.error
