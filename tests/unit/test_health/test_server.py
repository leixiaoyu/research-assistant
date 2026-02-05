"""Tests for FastAPI health server."""

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from src.health.server import (
    create_health_app,
    get_health_checker,
    set_health_checker,
)
from src.health.checks import (
    HealthChecker,
    HealthStatus,
    HealthReport,
    CheckResult,
    CheckStatus,
)


@pytest.fixture
def app():
    """Create test application."""
    return create_health_app()


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_healthy_checker():
    """Create mock health checker that returns healthy status."""
    checker = MagicMock(spec=HealthChecker)

    async def mock_check_all():
        return HealthReport(
            status=HealthStatus.HEALTHY,
            checks=[
                CheckResult(
                    name="disk_space",
                    status=CheckStatus.PASS,
                    message="OK",
                ),
                CheckResult(
                    name="cache_directory",
                    status=CheckStatus.PASS,
                    message="OK",
                ),
            ],
        )

    async def mock_is_ready():
        return True

    async def mock_is_alive():
        return True

    checker.check_all = mock_check_all
    checker.is_ready = mock_is_ready
    checker.is_alive = mock_is_alive

    return checker


@pytest.fixture
def mock_unhealthy_checker():
    """Create mock health checker that returns unhealthy status."""
    checker = MagicMock(spec=HealthChecker)

    async def mock_check_all():
        return HealthReport(
            status=HealthStatus.UNHEALTHY,
            checks=[
                CheckResult(
                    name="disk_space",
                    status=CheckStatus.FAIL,
                    message="Critical",
                ),
            ],
        )

    async def mock_is_ready():
        return False

    async def mock_is_alive():
        return True

    checker.check_all = mock_check_all
    checker.is_ready = mock_is_ready
    checker.is_alive = mock_is_alive

    return checker


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root_returns_info(self, client):
        """Should return API information."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data
        assert "/health" in data["endpoints"]["health"]


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_returns_200_when_healthy(self, client, mock_healthy_checker):
        """Should return 200 when all checks pass."""
        set_health_checker(mock_healthy_checker)

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert len(data["checks"]) == 2

    def test_health_returns_503_when_unhealthy(self, client, mock_unhealthy_checker):
        """Should return 503 when checks fail."""
        set_health_checker(mock_unhealthy_checker)

        response = client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"

    def test_health_includes_timestamp(self, client, mock_healthy_checker):
        """Should include timestamp in response."""
        set_health_checker(mock_healthy_checker)

        response = client.get("/health")

        data = response.json()
        assert "timestamp" in data


class TestReadyEndpoint:
    """Tests for /ready endpoint."""

    def test_ready_returns_200_when_ready(self, client, mock_healthy_checker):
        """Should return 200 when service is ready."""
        set_health_checker(mock_healthy_checker)

        response = client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True

    def test_ready_returns_503_when_not_ready(self, client, mock_unhealthy_checker):
        """Should return 503 when service is not ready."""
        set_health_checker(mock_unhealthy_checker)

        response = client.get("/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["ready"] is False


class TestLiveEndpoint:
    """Tests for /live endpoint."""

    def test_live_returns_200(self, client, mock_healthy_checker):
        """Should return 200 when service is alive."""
        set_health_checker(mock_healthy_checker)

        response = client.get("/live")

        assert response.status_code == 200
        data = response.json()
        assert data["alive"] is True


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""

    def test_metrics_returns_prometheus_format(self, client):
        """Should return metrics in Prometheus format."""
        response = client.get("/metrics")

        assert response.status_code == 200
        # Check content type
        assert "text" in response.headers["content-type"]
        # Check content contains metric names
        content = response.text
        assert "arisp_" in content


class TestGetHealthChecker:
    """Tests for get_health_checker function."""

    def test_creates_default_checker(self):
        """Should create default checker if none set."""
        # Reset global state
        import src.health.server as server_module

        server_module._health_checker = None

        checker = get_health_checker()

        assert checker is not None
        assert isinstance(checker, HealthChecker)

    def test_returns_same_instance(self):
        """Should return same instance on subsequent calls."""
        import src.health.server as server_module

        server_module._health_checker = None

        checker1 = get_health_checker()
        checker2 = get_health_checker()

        assert checker1 is checker2


class TestSetHealthChecker:
    """Tests for set_health_checker function."""

    def test_sets_custom_checker(self):
        """Should set custom health checker."""
        custom_checker = HealthChecker(disk_threshold_gb=999)

        set_health_checker(custom_checker)

        assert get_health_checker() is custom_checker


class TestCreateHealthApp:
    """Tests for create_health_app function."""

    def test_creates_fastapi_app(self):
        """Should create FastAPI application."""
        from fastapi import FastAPI

        app = create_health_app()

        assert isinstance(app, FastAPI)

    def test_app_has_custom_title(self):
        """Should use custom title."""
        app = create_health_app(title="Custom Title", version="2.0.0")

        assert app.title == "Custom Title"
        assert app.version == "2.0.0"

    def test_app_has_all_routes(self):
        """Should have all required routes."""
        app = create_health_app()

        routes = [route.path for route in app.routes]

        assert "/" in routes
        assert "/health" in routes
        assert "/ready" in routes
        assert "/live" in routes
        assert "/metrics" in routes
