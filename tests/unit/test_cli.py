import pytest
from typer.testing import CliRunner
from src.cli import app
from unittest.mock import patch, MagicMock

runner = CliRunner()


@pytest.fixture
def mock_config_manager():
    with patch("src.cli.ConfigManager") as MockConfigManager:
        yield MockConfigManager


@pytest.fixture
def mock_discovery_service():
    with patch("src.cli.DiscoveryService") as MockDiscoveryService:
        yield MockDiscoveryService


@pytest.fixture
def mock_catalog_service():
    with patch("src.cli.CatalogService") as MockCatalogService:
        yield MockCatalogService


def test_run_dry_run(mock_config_manager):
    # Setup mock
    mock_instance = mock_config_manager.return_value
    mock_config = MagicMock()
    mock_config.research_topics = []
    mock_instance.load_config.return_value = mock_config

    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run: Configuration valid." in result.stdout


def test_run_config_error(mock_config_manager):
    mock_instance = mock_config_manager.return_value
    mock_instance.load_config.side_effect = FileNotFoundError("Config not found")

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 1
    assert "Configuration Error" in result.stdout


def test_validate_success(mock_config_manager):
    result = runner.invoke(app, ["validate", "config.yaml"])
    assert result.exit_code == 0
    assert "Configuration is valid" in result.stdout


def test_validate_failure(mock_config_manager):
    mock_instance = mock_config_manager.return_value
    mock_instance.load_config.side_effect = Exception("Bad config")

    result = runner.invoke(app, ["validate", "config.yaml"])
    assert result.exit_code == 1
    assert "Validation failed" in result.stdout


def test_catalog_show(mock_config_manager):
    mock_instance = mock_config_manager.return_value
    mock_catalog = MagicMock()
    mock_catalog.topics = {"test-topic": MagicMock(query="Test", runs=[])}
    mock_instance.load_catalog.return_value = mock_catalog

    result = runner.invoke(app, ["catalog", "show"])
    assert result.exit_code == 0
    assert "Catalog contains 1 topics" in result.stdout
    assert "test-topic" in result.stdout


def test_catalog_history_success(mock_config_manager):
    mock_instance = mock_config_manager.return_value
    mock_catalog = MagicMock()
    mock_topic = MagicMock(query="Test")
    mock_run = MagicMock(date="2023-01-01", papers_found=5, output_file="out.md")
    mock_topic.runs = [mock_run]
    mock_catalog.topics = {"test-topic": mock_topic}
    mock_instance.load_catalog.return_value = mock_catalog

    result = runner.invoke(app, ["catalog", "history", "--topic", "test-topic"])
    assert result.exit_code == 0
    assert "History for Test" in result.stdout
    assert "Found 5 papers" in result.stdout


def test_catalog_history_missing_topic_arg(mock_config_manager):
    result = runner.invoke(app, ["catalog", "history"])
    assert result.exit_code == 0
    assert "Please provide --topic" in result.stdout


def test_catalog_history_topic_not_found(mock_config_manager):
    mock_instance = mock_config_manager.return_value
    mock_catalog = MagicMock()
    mock_catalog.topics = {}
    mock_instance.load_catalog.return_value = mock_catalog

    result = runner.invoke(app, ["catalog", "history", "--topic", "missing"])
    assert result.exit_code == 0
    assert "Topic 'missing' not found" in result.stdout
