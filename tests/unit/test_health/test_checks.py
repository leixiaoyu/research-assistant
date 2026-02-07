"""Tests for health check implementations."""

import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import tempfile

import pytest

from src.health.checks import (
    HealthChecker,
    HealthStatus,
    HealthReport,
    CheckResult,
    CheckStatus,
)


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    def test_create_with_defaults(self):
        """Should create with default values."""
        result = CheckResult(
            name="test",
            status=CheckStatus.PASS,
            message="Test passed",
        )

        assert result.name == "test"
        assert result.status == CheckStatus.PASS
        assert result.message == "Test passed"
        assert result.duration_ms == 0.0
        assert result.details == {}

    def test_create_with_all_fields(self):
        """Should create with all fields specified."""
        result = CheckResult(
            name="test",
            status=CheckStatus.WARN,
            message="Warning",
            duration_ms=123.45,
            details={"key": "value"},
        )

        assert result.duration_ms == 123.45
        assert result.details == {"key": "value"}

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = CheckResult(
            name="test",
            status=CheckStatus.PASS,
            message="OK",
            duration_ms=10.0,
            details={"foo": "bar"},
        )

        d = result.to_dict()

        assert d["name"] == "test"
        assert d["status"] == "pass"
        assert d["message"] == "OK"
        assert d["duration_ms"] == 10.0
        assert d["details"] == {"foo": "bar"}
        assert "timestamp" in d


class TestHealthReport:
    """Tests for HealthReport dataclass."""

    def test_create_report(self):
        """Should create health report."""
        checks = [
            CheckResult(name="check1", status=CheckStatus.PASS, message="OK"),
            CheckResult(name="check2", status=CheckStatus.PASS, message="OK"),
        ]

        report = HealthReport(status=HealthStatus.HEALTHY, checks=checks)

        assert report.status == HealthStatus.HEALTHY
        assert len(report.checks) == 2

    def test_to_dict(self):
        """Should convert to dictionary."""
        checks = [
            CheckResult(name="check1", status=CheckStatus.PASS, message="OK"),
        ]
        report = HealthReport(status=HealthStatus.HEALTHY, checks=checks)

        d = report.to_dict()

        assert d["status"] == "healthy"
        assert len(d["checks"]) == 1
        assert "timestamp" in d


class TestHealthChecker:
    """Tests for HealthChecker class."""

    def test_init_with_defaults(self):
        """Should initialize with default values."""
        checker = HealthChecker()

        assert checker.disk_threshold_gb == 1.0
        assert checker.disk_warning_gb == 5.0
        assert checker.cache_dir == Path(".cache")
        assert checker.output_dir == Path("output")
        assert checker.check_timeout_seconds == 10.0

    def test_init_with_custom_values(self):
        """Should initialize with custom values."""
        checker = HealthChecker(
            disk_threshold_gb=2.0,
            disk_warning_gb=10.0,
            cache_dir=Path("/custom/cache"),
            output_dir=Path("/custom/output"),
            check_timeout_seconds=5.0,
        )

        assert checker.disk_threshold_gb == 2.0
        assert checker.disk_warning_gb == 10.0
        assert checker.cache_dir == Path("/custom/cache")
        assert checker.output_dir == Path("/custom/output")
        assert checker.check_timeout_seconds == 5.0


class TestDiskSpaceCheck:
    """Tests for disk space check."""

    @pytest.mark.asyncio
    async def test_disk_space_pass(self):
        """Should pass when enough disk space."""
        checker = HealthChecker(disk_threshold_gb=0.001, disk_warning_gb=0.01)

        result = await checker.check_disk_space()

        assert result.name == "disk_space"
        assert result.status == CheckStatus.PASS
        assert "free_gb" in result.details
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_disk_space_fail_when_low(self):
        """Should fail when disk space below threshold."""
        # Set impossibly high threshold
        checker = HealthChecker(disk_threshold_gb=1000000)

        result = await checker.check_disk_space()

        assert result.status == CheckStatus.FAIL
        assert "critical" in result.message.lower()

    @pytest.mark.asyncio
    async def test_disk_space_warn_when_low(self):
        """Should warn when disk space below warning threshold."""
        checker = HealthChecker(disk_threshold_gb=0.001, disk_warning_gb=1000000)

        result = await checker.check_disk_space()

        assert result.status == CheckStatus.WARN
        assert "low" in result.message.lower()


class TestCacheDirectoryCheck:
    """Tests for cache directory check."""

    @pytest.mark.asyncio
    async def test_cache_directory_pass(self):
        """Should pass when cache directory is accessible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = HealthChecker(cache_dir=Path(tmpdir))

            result = await checker.check_cache_directory()

            assert result.name == "cache_directory"
            assert result.status == CheckStatus.PASS
            assert "path" in result.details

    @pytest.mark.asyncio
    async def test_cache_directory_creates_if_missing(self):
        """Should create cache directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "new_cache"
            checker = HealthChecker(cache_dir=cache_path)

            result = await checker.check_cache_directory()

            assert result.status == CheckStatus.PASS
            assert cache_path.exists()

    @pytest.mark.asyncio
    async def test_cache_directory_fail_when_not_writable(self):
        """Should fail when cache directory is not writable."""
        # Use a path that doesn't exist and can't be created
        checker = HealthChecker(cache_dir=Path("/nonexistent/path/cache"))

        result = await checker.check_cache_directory()

        assert result.status == CheckStatus.FAIL


class TestOutputDirectoryCheck:
    """Tests for output directory check."""

    @pytest.mark.asyncio
    async def test_output_directory_pass(self):
        """Should pass when output directory is accessible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = HealthChecker(output_dir=Path(tmpdir))

            result = await checker.check_output_directory()

            assert result.name == "output_directory"
            assert result.status == CheckStatus.PASS

    @pytest.mark.asyncio
    async def test_output_directory_creates_if_missing(self):
        """Should create output directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "new_output"
            checker = HealthChecker(output_dir=output_path)

            result = await checker.check_output_directory()

            assert result.status == CheckStatus.PASS
            assert output_path.exists()


class TestAPIConnectivityChecks:
    """Tests for API connectivity checks."""

    @pytest.mark.asyncio
    async def test_semantic_scholar_api_pass(self):
        """Should pass when API is reachable."""
        checker = HealthChecker()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_semantic_scholar_api()

        assert result.name == "semantic_scholar_api"
        assert result.status == CheckStatus.PASS

    @pytest.mark.asyncio
    async def test_semantic_scholar_api_warn_on_non_200(self):
        """Should warn when API returns non-200 status."""
        checker = HealthChecker()

        mock_response = AsyncMock()
        mock_response.status = 503
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_semantic_scholar_api()

        assert result.status == CheckStatus.WARN
        assert "503" in result.message

    @pytest.mark.asyncio
    async def test_semantic_scholar_api_warn_on_timeout(self):
        """Should warn when API times out."""
        checker = HealthChecker(check_timeout_seconds=0.01)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_semantic_scholar_api()

        assert result.status == CheckStatus.WARN
        assert "timeout" in result.message.lower()

    @pytest.mark.asyncio
    async def test_arxiv_api_pass(self):
        """Should pass when ArXiv API is reachable."""
        checker = HealthChecker()

        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_arxiv_api()

        assert result.name == "arxiv_api"
        assert result.status == CheckStatus.PASS


class TestCheckAll:
    """Tests for check_all method."""

    @pytest.mark.asyncio
    async def test_check_all_healthy(self):
        """Should return healthy status when all checks pass."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = HealthChecker(
                cache_dir=Path(tmpdir) / "cache",
                output_dir=Path(tmpdir) / "output",
                disk_threshold_gb=0.001,
                disk_warning_gb=0.01,
            )

            # Mock API checks to pass
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session = AsyncMock()
            mock_session.get = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)

            with patch("aiohttp.ClientSession", return_value=mock_session):
                report = await checker.check_all()

            assert report.status == HealthStatus.HEALTHY
            assert len(report.checks) == 5

    @pytest.mark.asyncio
    async def test_check_all_unhealthy_on_fail(self):
        """Should return unhealthy when any check fails."""
        checker = HealthChecker(
            disk_threshold_gb=1000000,  # Impossible threshold
        )

        # Mock API checks
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            report = await checker.check_all()

        assert report.status == HealthStatus.UNHEALTHY


class TestReadinessAndLiveness:
    """Tests for is_ready and is_alive methods."""

    @pytest.mark.asyncio
    async def test_is_ready_true(self):
        """Should return True when ready."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = HealthChecker(
                cache_dir=Path(tmpdir) / "cache",
                output_dir=Path(tmpdir) / "output",
                disk_threshold_gb=0.001,
            )

            result = await checker.is_ready()

            assert result is True

    @pytest.mark.asyncio
    async def test_is_ready_false_on_disk_fail(self):
        """Should return False when disk check fails."""
        checker = HealthChecker(disk_threshold_gb=1000000)

        result = await checker.is_ready()

        assert result is False

    @pytest.mark.asyncio
    async def test_is_alive_always_true(self):
        """Should always return True."""
        checker = HealthChecker()

        result = await checker.is_alive()

        assert result is True


class TestDirectorySizeMB:
    """Tests for _get_directory_size_mb helper."""

    def test_get_directory_size_empty(self):
        """Should return 0 for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = HealthChecker()
            size = checker._get_directory_size_mb(Path(tmpdir))

            assert size == 0.0

    def test_get_directory_size_with_files(self):
        """Should return correct size for directory with files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file with known size
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_bytes(b"x" * 1024 * 1024)  # 1MB

            checker = HealthChecker()
            size = checker._get_directory_size_mb(Path(tmpdir))

            assert size >= 0.9  # Allow some tolerance

    def test_get_directory_size_nonexistent(self):
        """Should return 0 for non-existent directory."""
        checker = HealthChecker()
        size = checker._get_directory_size_mb(Path("/nonexistent/path"))

        assert size == 0.0


class TestCheckAllEdgeCases:
    """Tests for check_all edge cases."""

    @pytest.mark.asyncio
    async def test_check_all_handles_check_exception(self):
        """Should handle exception from individual check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            checker = HealthChecker(
                cache_dir=Path(tmpdir) / "cache",
                output_dir=Path(tmpdir) / "output",
            )

            # Mock one check to raise exception
            with patch.object(
                checker, "check_disk_space", side_effect=Exception("Check error")
            ):
                report = await checker.check_all()

            # Should have recorded the exception as a failed check
            failed_checks = [c for c in report.checks if c.status == CheckStatus.FAIL]
            assert len(failed_checks) >= 1

    @pytest.mark.asyncio
    async def test_determine_overall_status_degraded(self):
        """Should return DEGRADED when only warnings present."""
        checker = HealthChecker()

        checks = [
            CheckResult(name="check1", status=CheckStatus.PASS, message="OK"),
            CheckResult(name="check2", status=CheckStatus.WARN, message="Warning"),
        ]

        status = checker._determine_overall_status(checks)

        assert status == HealthStatus.DEGRADED


class TestAPICheckEdgeCases:
    """Tests for API check edge cases."""

    @pytest.mark.asyncio
    async def test_semantic_scholar_non_200(self):
        """Should return WARN for non-200 status."""
        checker = HealthChecker()

        mock_response = AsyncMock()
        mock_response.status = 503  # Service unavailable
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_semantic_scholar_api()

        assert result.status == CheckStatus.WARN
        assert "503" in result.message

    @pytest.mark.asyncio
    async def test_arxiv_non_200(self):
        """Should return WARN for non-200 status."""
        checker = HealthChecker()

        mock_response = AsyncMock()
        mock_response.status = 500  # Server error
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_arxiv_api()

        assert result.status == CheckStatus.WARN
        assert "500" in result.message

    @pytest.mark.asyncio
    async def test_semantic_scholar_timeout(self):
        """Should return WARN on timeout."""
        import asyncio as aio

        checker = HealthChecker(check_timeout_seconds=0.001)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_semantic_scholar_api()

        assert result.status == CheckStatus.WARN
        assert "timeout" in result.message.lower()

    @pytest.mark.asyncio
    async def test_arxiv_timeout(self):
        """Should return WARN on timeout."""
        import asyncio as aio

        checker = HealthChecker(check_timeout_seconds=0.001)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=aio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_arxiv_api()

        assert result.status == CheckStatus.WARN
        assert "timeout" in result.message.lower()

    @pytest.mark.asyncio
    async def test_semantic_scholar_connection_error(self):
        """Should return WARN on connection error."""
        checker = HealthChecker()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_semantic_scholar_api()

        assert result.status == CheckStatus.WARN
        assert "unreachable" in result.message.lower()

    @pytest.mark.asyncio
    async def test_arxiv_connection_error(self):
        """Should return WARN on connection error."""
        checker = HealthChecker()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(side_effect=Exception("Connection refused"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await checker.check_arxiv_api()

        assert result.status == CheckStatus.WARN
        assert "unreachable" in result.message.lower()


class TestIsReadyEdgeCases:
    """Tests for is_ready edge cases."""

    @pytest.mark.asyncio
    async def test_is_ready_exception_returns_false(self):
        """Should return False when exception occurs."""
        checker = HealthChecker()

        # Mock a check to raise exception
        with patch.object(checker, "check_disk_space", side_effect=Exception("Error")):
            result = await checker.is_ready()

        assert result is False
