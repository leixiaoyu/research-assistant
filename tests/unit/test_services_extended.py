import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime
from pathlib import Path

from src.services.discovery_service import DiscoveryService
from src.services.providers.base import APIError
from src.services.catalog_service import CatalogService
from src.services.config_manager import ConfigManager, ConfigValidationError
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    ProviderType,
    ProviderSelectionConfig,
)
from src.models.catalog import Catalog, TopicCatalogEntry

# --- Discovery Service Tests ---


@pytest.fixture
def discovery_service():
    # Disable auto-select for explicit provider tests
    config = ProviderSelectionConfig(auto_select=False, fallback_enabled=False)
    return DiscoveryService("test_key_1234567890", config=config)


@pytest.fixture
def topic_recent():
    return ResearchTopic(
        query="test",
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"),
        max_papers=5,
        auto_select_provider=False,  # Disable auto-selection for explicit tests
    )


@pytest.mark.asyncio
async def test_search_delegation(discovery_service, topic_recent):
    """Test that search delegates to the correct provider"""
    with patch(
        "src.services.providers.semantic_scholar." "SemanticScholarProvider.search"
    ) as mock_search:
        mock_search.return_value = []
        await discovery_service.search(topic_recent)
        mock_search.assert_called_once_with(topic_recent)


@pytest.mark.asyncio
async def test_search_api_errors(discovery_service, topic_recent):
    """Test handling of API errors with fallback disabled"""
    with patch(
        "src.services.providers.semantic_scholar.SemanticScholarProvider.search",
        new_callable=AsyncMock,
    ) as mock_search:
        # Simulate API error
        mock_search.side_effect = APIError("API Error")

        with patch("src.services.discovery_service.logger"):
            # With fallback disabled, API errors propagate up
            with pytest.raises(APIError, match="API Error"):
                await discovery_service.search(topic_recent)


@pytest.mark.asyncio
async def test_search_provider_unavailable():
    """Test error when provider is requested but not configured"""
    # No API key, and disable auto-select so it doesn't fallback to ArXiv
    config = ProviderSelectionConfig(auto_select=False, fallback_enabled=False)
    ds = DiscoveryService(api_key="", config=config)

    topic = ResearchTopic(
        query="test",
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"),
        auto_select_provider=False,
    )
    with pytest.raises(APIError, match="not available"):
        await ds.search(topic)


@pytest.mark.asyncio
async def test_search_unknown_provider():
    """Test error for unknown provider type"""
    config = ProviderSelectionConfig(auto_select=False, fallback_enabled=False)
    ds = DiscoveryService(api_key="test_key_1234567890", config=config)

    topic = ResearchTopic(
        query="test",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeRecent(value="48h"),
        auto_select_provider=False,
    )
    # Remove ArXiv from providers to trigger unknown provider error
    del ds.providers[ProviderType.ARXIV]

    with pytest.raises(ValueError, match="Unknown provider type"):
        await ds.search(topic)


# --- Catalog Service Tests ---


def test_collision_logic():
    cm = MagicMock()
    cm.generate_topic_slug.return_value = "slug"

    existing_topic = TopicCatalogEntry(
        topic_slug="slug", query="Other", folder="slug", created_at=datetime.utcnow()
    )
    catalog = Catalog(topics={"slug": existing_topic})

    cm.load_catalog.return_value = catalog

    service = CatalogService(cm)

    new_topic = service.get_or_create_topic("Target")

    assert new_topic.topic_slug.startswith("slug-")
    assert new_topic.query == "Target"
    assert new_topic.topic_slug != "slug"


def test_add_run_missing_topic():
    cm = MagicMock()
    cm.load_catalog.return_value = Catalog()
    service = CatalogService(cm)

    with pytest.raises(ValueError, match="Topic not found"):
        service.add_run("missing", MagicMock())


# --- Config Manager Tests ---


def test_config_validation_errors():
    cm = ConfigManager("bad_path.yaml")

    # File not found
    with pytest.raises(FileNotFoundError):
        cm.load_config()

    # Bad YAML content
    with open("bad.yaml", "w") as f:
        f.write("key: : value")  # Invalid YAML

    # Fix: ensure Path object
    cm.config_path = Path("bad.yaml")

    with pytest.raises(ConfigValidationError):
        cm.load_config()
    import os

    os.remove("bad.yaml")


def test_get_output_path_security():
    cm = ConfigManager()
    cm._config = MagicMock()
    cm._config.settings.output_base_dir = "."

    # Invalid traversal
    from src.utils.security import SecurityError

    with pytest.raises(SecurityError):
        cm.get_output_path("../oops")
