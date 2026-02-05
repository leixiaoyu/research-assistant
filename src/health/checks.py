"""Health check implementations for service dependencies.

Provides checks for:
- Disk space availability
- Cache service connectivity
- API connectivity (Semantic Scholar, ArXiv)
- LLM provider health (optional)

Usage:
    checker = HealthChecker(
        disk_threshold_gb=1.0,
        cache_dir=Path(".cache"),
    )

    # Run all checks
    status = await checker.check_all()

    # Run specific check
    disk_result = await checker.check_disk_space()
"""

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio
import aiohttp
import structlog

logger = structlog.get_logger()


class HealthStatus(str, Enum):
    """Overall health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CheckStatus(str, Enum):
    """Individual check status."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    """Result of a single health check."""

    name: str
    status: CheckStatus
    message: str
    duration_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 2),
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class HealthReport:
    """Complete health report with all check results."""

    status: HealthStatus
    checks: List[CheckResult]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": self.timestamp.isoformat(),
        }


class HealthCheckError(Exception):
    """Exception raised when a health check fails."""

    pass


class HealthChecker:
    """Health checker for ARISP service dependencies.

    Performs health checks on:
    - Disk space
    - Cache directory accessibility
    - External API connectivity
    - LLM provider health (optional)
    """

    # External API endpoints for connectivity checks
    SEMANTIC_SCHOLAR_HEALTH_URL = "https://api.semanticscholar.org/"
    ARXIV_HEALTH_URL = (
        "https://export.arxiv.org/api/query?search_query=test&max_results=1"
    )

    def __init__(
        self,
        disk_threshold_gb: float = 1.0,
        disk_warning_gb: float = 5.0,
        cache_dir: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        check_timeout_seconds: float = 10.0,
    ):
        """Initialize health checker.

        Args:
            disk_threshold_gb: Minimum disk space (GB) for healthy status
            disk_warning_gb: Disk space (GB) threshold for warning
            cache_dir: Cache directory to check (default: .cache)
            output_dir: Output directory to check (default: output)
            check_timeout_seconds: Timeout for external API checks
        """
        self.disk_threshold_gb = disk_threshold_gb
        self.disk_warning_gb = disk_warning_gb
        self.cache_dir = cache_dir or Path(".cache")
        self.output_dir = output_dir or Path("output")
        self.check_timeout_seconds = check_timeout_seconds

    async def check_all(self) -> HealthReport:
        """Run all health checks and return comprehensive report.

        Returns:
            HealthReport with status and all check results
        """
        checks: List[CheckResult] = []

        # Run checks concurrently
        results = await asyncio.gather(
            self.check_disk_space(),
            self.check_cache_directory(),
            self.check_output_directory(),
            self.check_semantic_scholar_api(),
            self.check_arxiv_api(),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                checks.append(
                    CheckResult(
                        name="unknown",
                        status=CheckStatus.FAIL,
                        message=f"Check failed: {str(result)}",
                    )
                )
            elif isinstance(result, CheckResult):
                checks.append(result)

        # Determine overall status
        status = self._determine_overall_status(checks)

        return HealthReport(status=status, checks=checks)

    def _determine_overall_status(self, checks: List[CheckResult]) -> HealthStatus:
        """Determine overall health status from individual checks.

        Args:
            checks: List of check results

        Returns:
            Overall HealthStatus
        """
        has_fail = any(c.status == CheckStatus.FAIL for c in checks)
        has_warn = any(c.status == CheckStatus.WARN for c in checks)

        if has_fail:
            return HealthStatus.UNHEALTHY
        elif has_warn:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    async def check_disk_space(self) -> CheckResult:
        """Check available disk space.

        Returns:
            CheckResult with disk space status
        """
        import time

        start = time.time()
        name = "disk_space"

        try:
            # Get disk usage for the current directory
            total, used, free = shutil.disk_usage(Path.cwd())

            free_gb = free / (1024**3)
            total_gb = total / (1024**3)
            used_percent = (used / total) * 100

            duration_ms = (time.time() - start) * 1000

            details = {
                "free_gb": round(free_gb, 2),
                "total_gb": round(total_gb, 2),
                "used_percent": round(used_percent, 1),
            }

            if free_gb < self.disk_threshold_gb:
                return CheckResult(
                    name=name,
                    status=CheckStatus.FAIL,
                    message=f"Disk space critical: {free_gb:.1f}GB free",
                    duration_ms=duration_ms,
                    details=details,
                )
            elif free_gb < self.disk_warning_gb:
                return CheckResult(
                    name=name,
                    status=CheckStatus.WARN,
                    message=f"Disk space low: {free_gb:.1f}GB free",
                    duration_ms=duration_ms,
                    details=details,
                )
            else:
                return CheckResult(
                    name=name,
                    status=CheckStatus.PASS,
                    message=f"Disk space OK: {free_gb:.1f}GB free",
                    duration_ms=duration_ms,
                    details=details,
                )

        except Exception as e:  # pragma: no cover (defensive code for OS errors)
            duration_ms = (time.time() - start) * 1000
            logger.error("disk_space_check_failed", error=str(e))
            return CheckResult(
                name=name,
                status=CheckStatus.FAIL,
                message=f"Disk check failed: {str(e)}",
                duration_ms=duration_ms,
            )

    async def check_cache_directory(self) -> CheckResult:
        """Check cache directory accessibility.

        Returns:
            CheckResult with cache directory status
        """
        import time

        start = time.time()
        name = "cache_directory"

        try:
            # Check if directory exists
            if not self.cache_dir.exists():
                # Try to create it
                self.cache_dir.mkdir(parents=True, exist_ok=True)

            # Check if writable
            test_file = self.cache_dir / ".health_check"
            test_file.write_text("health_check")
            test_file.unlink()

            duration_ms = (time.time() - start) * 1000

            # Get cache size
            cache_size_mb = self._get_directory_size_mb(self.cache_dir)

            return CheckResult(
                name=name,
                status=CheckStatus.PASS,
                message="Cache directory accessible",
                duration_ms=duration_ms,
                details={
                    "path": str(self.cache_dir.absolute()),
                    "size_mb": round(cache_size_mb, 2),
                },
            )

        except PermissionError as e:  # pragma: no cover (requires FS permission issues)
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.FAIL,
                message=f"Cache directory not writable: {str(e)}",
                duration_ms=duration_ms,
            )
        except Exception as e:  # pragma: no cover (defensive code for OS errors)
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.FAIL,
                message=f"Cache check failed: {str(e)}",
                duration_ms=duration_ms,
            )

    async def check_output_directory(self) -> CheckResult:
        """Check output directory accessibility.

        Returns:
            CheckResult with output directory status
        """
        import time

        start = time.time()
        name = "output_directory"

        try:
            # Check if directory exists
            if not self.output_dir.exists():
                self.output_dir.mkdir(parents=True, exist_ok=True)

            # Check if writable
            test_file = self.output_dir / ".health_check"
            test_file.write_text("health_check")
            test_file.unlink()

            duration_ms = (time.time() - start) * 1000

            return CheckResult(
                name=name,
                status=CheckStatus.PASS,
                message="Output directory accessible",
                duration_ms=duration_ms,
                details={"path": str(self.output_dir.absolute())},
            )

        except PermissionError as e:  # pragma: no cover (requires FS permission issues)
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.FAIL,
                message=f"Output directory not writable: {str(e)}",
                duration_ms=duration_ms,
            )
        except Exception as e:  # pragma: no cover (defensive code for OS errors)
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.FAIL,
                message=f"Output check failed: {str(e)}",
                duration_ms=duration_ms,
            )

    async def check_semantic_scholar_api(self) -> CheckResult:
        """Check Semantic Scholar API connectivity.

        Returns:
            CheckResult with API status
        """
        import time

        start = time.time()
        name = "semantic_scholar_api"

        try:
            timeout = aiohttp.ClientTimeout(total=self.check_timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.SEMANTIC_SCHOLAR_HEALTH_URL) as response:
                    duration_ms = (time.time() - start) * 1000

                    if response.status == 200:
                        return CheckResult(
                            name=name,
                            status=CheckStatus.PASS,
                            message="Semantic Scholar API reachable",
                            duration_ms=duration_ms,
                            details={"status_code": response.status},
                        )
                    else:
                        return CheckResult(
                            name=name,
                            status=CheckStatus.WARN,
                            message=f"API returned status {response.status}",
                            duration_ms=duration_ms,
                            details={"status_code": response.status},
                        )

        except asyncio.TimeoutError:
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.WARN,
                message="API timeout",
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.WARN,
                message=f"API unreachable: {str(e)}",
                duration_ms=duration_ms,
            )

    async def check_arxiv_api(self) -> CheckResult:
        """Check ArXiv API connectivity.

        Returns:
            CheckResult with API status
        """
        import time

        start = time.time()
        name = "arxiv_api"

        try:
            timeout = aiohttp.ClientTimeout(total=self.check_timeout_seconds)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.ARXIV_HEALTH_URL) as response:
                    duration_ms = (time.time() - start) * 1000

                    if response.status == 200:
                        return CheckResult(
                            name=name,
                            status=CheckStatus.PASS,
                            message="ArXiv API reachable",
                            duration_ms=duration_ms,
                            details={"status_code": response.status},
                        )
                    else:
                        return CheckResult(
                            name=name,
                            status=CheckStatus.WARN,
                            message=f"API returned status {response.status}",
                            duration_ms=duration_ms,
                            details={"status_code": response.status},
                        )

        except asyncio.TimeoutError:
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.WARN,
                message="API timeout",
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            return CheckResult(
                name=name,
                status=CheckStatus.WARN,
                message=f"API unreachable: {str(e)}",
                duration_ms=duration_ms,
            )

    def _get_directory_size_mb(self, path: Path) -> float:
        """Calculate directory size in MB.

        Args:
            path: Directory path

        Returns:
            Size in MB
        """
        try:
            total_size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            return total_size / (1024 * 1024)
        except Exception:  # pragma: no cover (defensive code for FS errors)
            return 0.0

    async def is_ready(self) -> bool:
        """Check if service is ready to accept requests.

        Checks critical dependencies only (disk, directories).

        Returns:
            True if ready, False otherwise
        """
        try:
            disk = await self.check_disk_space()
            cache = await self.check_cache_directory()
            output = await self.check_output_directory()

            return all(c.status != CheckStatus.FAIL for c in [disk, cache, output])
        except Exception:
            return False

    async def is_alive(self) -> bool:
        """Check if service is alive (basic liveness).

        Returns:
            True always (service is running if this is called)
        """
        return True
