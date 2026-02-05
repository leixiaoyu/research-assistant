"""Health check module for Phase 4: Production Hardening.

Provides:
- Health check implementations for service dependencies
- FastAPI health endpoints (/health, /ready, /live, /metrics)
- Integration with Prometheus metrics export

Usage:
    from src.health import HealthChecker, create_health_app

    # Create health checker
    checker = HealthChecker()

    # Run health checks
    status = await checker.check_all()

    # Create and run FastAPI health server
    app = create_health_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""

from src.health.checks import (
    HealthChecker,
    HealthStatus,
    CheckResult,
    HealthCheckError,
)
from src.health.server import create_health_app, run_health_server

__all__ = [
    "HealthChecker",
    "HealthStatus",
    "CheckResult",
    "HealthCheckError",
    "create_health_app",
    "run_health_server",
]
