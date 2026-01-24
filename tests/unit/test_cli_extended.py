import pytest
from typer.testing import CliRunner
from unittest.mock import MagicMock, patch, AsyncMock
from src.cli import app
from src.models.paper import PaperMetadata
from src.services.discovery_service import APIError

runner = CliRunner()


@pytest.fixture
def mock_components():
    with patch("src.cli.ConfigManager") as MockConfig, patch(
        "src.cli.DiscoveryService"
    ) as MockDiscovery, patch("src.cli.CatalogService") as MockCatalog, patch(
        "src.cli.MarkdownGenerator"
    ) as MockGen, patch(
        "src.cli.open", new_callable=MagicMock
    ) as mock_open:  # Mock file writing

        # Setup Config
        config_instance = MockConfig.return_value
        config = MagicMock()
        topic = MagicMock()
        topic.query = "Test Query"
        topic.timeframe.value = "48h"
        config.research_topics = [topic]
        config.settings.semantic_scholar_api_key = "key"
        config_instance.load_config.return_value = config
        config_instance.get_output_path.return_value = MagicMock()  # Path object

        # Setup Discovery
        discovery_instance = MockDiscovery.return_value
        discovery_instance.search = AsyncMock()
        discovery_instance.search.return_value = [
            PaperMetadata(
                paper_id="1", title="P1", url="http://u", year=2023  # type: ignore
            )
        ]

        # Setup Catalog
        catalog_instance = MockCatalog.return_value
        catalog_topic = MagicMock()
        catalog_topic.topic_slug = "slug"
        catalog_instance.get_or_create_topic.return_value = catalog_topic

        yield {
            "config": config_instance,
            "discovery": discovery_instance,
            "catalog": catalog_instance,
            "gen": MockGen.return_value,
            "open": mock_open,
        }


def test_run_full_flow(mock_components):
    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0

    # Check calls
    mock_components["discovery"].search.assert_called()
    mock_components["gen"].generate.assert_called()
    mock_components["catalog"].add_run.assert_called()


def test_run_discovery_no_papers(mock_components):
    mock_components["discovery"].search.return_value = []

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0

    mock_components["catalog"].add_run.assert_not_called()


def test_run_discovery_error(mock_components):
    mock_components["discovery"].search.side_effect = APIError("Fail")

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0  # Should continue to next topic or finish gracefully

    # Should log error but not crash CLI
    # We can't easily check log output with CliRunner unless we capture stderr
    # and logging is configured to print there.
    # structlog is configured to print to console.

    mock_components["catalog"].add_run.assert_not_called()


def test_run_unexpected_error(mock_components):
    mock_components["discovery"].search.side_effect = Exception("Boom")

    result = runner.invoke(app, ["run"])
    assert result.exit_code == 0
