"""FastAPI health server for production monitoring.

Provides HTTP endpoints for:
- /health - Full health check with all dependencies
- /ready - Readiness probe for Kubernetes
- /live - Liveness probe for Kubernetes
- /metrics - Prometheus metrics in text format

Usage:
    # Create and run server
    from src.health.server import run_health_server
    run_health_server(host="0.0.0.0", port=8000)

    # Or use with custom app
    from src.health.server import create_health_app
    app = create_health_app()
"""

from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
import structlog

from src.health.checks import (
    HealthChecker,
    HealthStatus,
)
from src.observability.metrics import get_metrics_text, get_metrics_content_type

logger = structlog.get_logger()

# Global health checker instance
_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Get or create the global health checker instance.

    Returns:
        HealthChecker instance
    """
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


def set_health_checker(checker: HealthChecker) -> None:
    """Set the global health checker instance.

    Args:
        checker: HealthChecker instance to use
    """
    global _health_checker
    _health_checker = checker


@asynccontextmanager
async def lifespan(app: FastAPI):  # pragma: no cover
    """Application lifespan context manager.

    Initializes health checker on startup and cleans up on shutdown.
    """
    logger.info("health_server_starting")
    get_health_checker()
    yield
    logger.info("health_server_stopping")


def create_health_app(
    title: str = "ARISP Health API",
    version: str = "1.0.0",
) -> FastAPI:
    """Create FastAPI application with health endpoints.

    Args:
        title: API title
        version: API version

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=title,
        version=version,
        description="Health check and metrics endpoints for ARISP pipeline",
        lifespan=lifespan,
    )

    @app.get(
        "/health",
        response_model=None,
        summary="Full health check",
        description="Run all health checks and return detailed status",
        responses={
            200: {"description": "All checks passed"},
            503: {"description": "One or more checks failed"},
        },
    )
    async def health_check() -> Response:
        """Full health check endpoint.

        Runs all health checks and returns detailed status.
        Returns 200 if healthy/degraded, 503 if unhealthy.
        """
        checker = get_health_checker()
        report = await checker.check_all()

        status_code = (
            status.HTTP_200_OK
            if report.status != HealthStatus.UNHEALTHY
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )

        return JSONResponse(content=report.to_dict(), status_code=status_code)

    @app.get(
        "/ready",
        response_model=None,
        summary="Readiness probe",
        description="Check if service is ready to accept traffic",
        responses={
            200: {"description": "Service is ready"},
            503: {"description": "Service is not ready"},
        },
    )
    async def readiness_probe() -> Response:
        """Kubernetes readiness probe.

        Checks if critical dependencies are available.
        Used by load balancers to determine if traffic should be sent.
        """
        checker = get_health_checker()
        is_ready = await checker.is_ready()

        if is_ready:
            return JSONResponse(
                content={"ready": True, "message": "Service is ready"},
                status_code=status.HTTP_200_OK,
            )
        else:
            return JSONResponse(
                content={"ready": False, "message": "Service is not ready"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    @app.get(
        "/live",
        response_model=None,
        summary="Liveness probe",
        description="Check if service is alive",
        responses={
            200: {"description": "Service is alive"},
        },
    )
    async def liveness_probe() -> Response:
        """Kubernetes liveness probe.

        Basic check that the service is running.
        If this fails, Kubernetes will restart the container.
        """
        checker = get_health_checker()
        is_alive = await checker.is_alive()

        return JSONResponse(
            content={"alive": is_alive, "message": "Service is alive"},
            status_code=status.HTTP_200_OK,
        )

    @app.get(
        "/metrics",
        response_class=PlainTextResponse,
        summary="Prometheus metrics",
        description="Export Prometheus metrics in text format",
    )
    async def prometheus_metrics() -> Response:
        """Prometheus metrics endpoint.

        Returns metrics in Prometheus exposition format for scraping.
        """
        metrics_text = get_metrics_text()
        return Response(
            content=metrics_text,
            media_type=get_metrics_content_type(),
        )

    @app.get(
        "/",
        response_model=None,
        summary="Root endpoint",
        description="Basic API information",
    )
    async def root() -> Dict[str, Any]:
        """Root endpoint with API information."""
        return {
            "name": title,
            "version": version,
            "endpoints": {
                "health": "/health",
                "ready": "/ready",
                "live": "/live",
                "metrics": "/metrics",
            },
        }

    return app


async def run_health_server_async(  # pragma: no cover
    host: str = "0.0.0.0",
    port: int = 8000,
    log_level: str = "info",
) -> None:
    """Run health server asynchronously.

    Args:
        host: Host to bind to
        port: Port to bind to
        log_level: Logging level
    """
    import uvicorn

    app = create_health_app()
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=True,
    )
    server = uvicorn.Server(config)

    logger.info("health_server_starting", host=host, port=port)
    await server.serve()


def run_health_server(  # pragma: no cover
    host: str = "0.0.0.0",
    port: int = 8000,
    log_level: str = "info",
) -> None:
    """Run health server (blocking).

    Args:
        host: Host to bind to
        port: Port to bind to
        log_level: Logging level
    """
    import uvicorn

    app = create_health_app()
    logger.info("health_server_starting", host=host, port=port)
    uvicorn.run(app, host=host, port=port, log_level=log_level)


# For running directly: python -m src.health.server
if __name__ == "__main__":  # pragma: no cover
    run_health_server()
