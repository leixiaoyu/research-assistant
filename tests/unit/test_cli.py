"""Tests for CLI commands."""

import pytest
from typer.testing import CliRunner
from src.cli import app
from unittest.mock import patch, MagicMock

runner = CliRunner()


@pytest.fixture
def mock_run_config_manager():
    """Mock ConfigManager for run command tests (via utils)."""
    with patch("src.cli.utils.ConfigManager") as MockConfigManager:
        yield MockConfigManager


@pytest.fixture
def mock_catalog_config_manager():
    """Mock ConfigManager for catalog command tests (direct import)."""
    with patch("src.cli.catalog.ConfigManager") as MockConfigManager:
        yield MockConfigManager


def test_run_dry_run(mock_run_config_manager):
    # Setup mock - Phase 1 only (no Phase 2 settings)
    mock_instance = mock_run_config_manager.return_value
    mock_config = MagicMock()
    mock_config.research_topics = []
    # Disable Phase 2 by setting Phase 2 settings to None
    mock_config.settings.pdf_settings = None
    mock_config.settings.llm_settings = None
    mock_config.settings.cost_limits = None
    mock_instance.load_config.return_value = mock_config

    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run: Configuration valid." in result.stdout


def test_run_config_error(mock_run_config_manager):
    mock_instance = mock_run_config_manager.return_value
    mock_instance.load_config.side_effect = FileNotFoundError("Config not found")

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "Configuration Error" in result.stdout


def test_validate_success():
    """Test validate command with valid config."""
    with patch("src.cli.validate.ConfigManager") as mock_cm:
        mock_cm.return_value.load_config.return_value = MagicMock()
        result = runner.invoke(app, ["validate", "config.yaml"])
        assert result.exit_code == 0
        assert "Configuration is valid" in result.stdout


def test_validate_failure():
    """Test validate command with invalid config."""
    with patch("src.cli.validate.ConfigManager") as mock_cm:
        mock_cm.return_value.load_config.side_effect = Exception("Bad config")
        result = runner.invoke(app, ["validate", "config.yaml"])
        assert result.exit_code == 1
        assert "Validation failed" in result.stdout


def test_catalog_show(mock_catalog_config_manager):
    mock_instance = mock_catalog_config_manager.return_value
    mock_catalog = MagicMock()
    mock_catalog.topics = {"test-topic": MagicMock(query="Test", runs=[])}
    mock_instance.load_catalog.return_value = mock_catalog

    result = runner.invoke(app, ["catalog", "show"])
    assert result.exit_code == 0
    assert "Catalog contains 1 topics" in result.stdout
    assert "test-topic" in result.stdout


def test_catalog_history_success(mock_catalog_config_manager):
    mock_instance = mock_catalog_config_manager.return_value
    mock_catalog = MagicMock()
    mock_topic = MagicMock(query="Test")
    mock_run = MagicMock(date="2023-01-01", papers_found=5, output_file="out.md")
    mock_topic.runs = [mock_run]
    mock_catalog.topics = {"test-topic": mock_topic}
    mock_instance.load_catalog.return_value = mock_catalog

    # Use positional argument (new API)
    result = runner.invoke(app, ["catalog", "history", "test-topic"])
    assert result.exit_code == 0
    assert "History for Test" in result.stdout
    assert "Found 5 papers" in result.stdout


def test_catalog_history_missing_topic_arg():
    """Test catalog history without topic argument."""
    result = runner.invoke(app, ["catalog", "history"])
    # Should show usage error for missing argument
    assert result.exit_code == 2
    assert "Missing argument" in result.stdout


def test_catalog_history_topic_not_found(mock_catalog_config_manager):
    mock_instance = mock_catalog_config_manager.return_value
    mock_catalog = MagicMock()
    mock_catalog.topics = {}
    mock_instance.load_catalog.return_value = mock_catalog

    # Use positional argument (new API)
    result = runner.invoke(app, ["catalog", "history", "missing"])
    assert result.exit_code == 1
    assert "Topic 'missing' not found" in result.stdout
