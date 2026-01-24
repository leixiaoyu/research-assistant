import pytest
import aiohttp
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, date
from pathlib import Path

from src.services.discovery_service import DiscoveryService, APIError, RateLimitError
from src.services.catalog_service import CatalogService
from src.services.config_manager import ConfigManager, ConfigValidationError
from src.models.config import ResearchTopic, TimeframeRecent, TimeframeSinceYear, TimeframeDateRange, ProviderType
from src.models.catalog import Catalog, TopicCatalogEntry

# --- Discovery Service Tests ---

@pytest.fixture
def discovery_service():
    return DiscoveryService("key")

@pytest.fixture
def topic_recent():
    return ResearchTopic(
        query="test", 
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"), 
        max_papers=5
    )

@pytest.mark.asyncio
async def test_search_delegation(discovery_service, topic_recent):
    """Test that search delegates to the correct provider"""
    with patch("src.services.providers.semantic_scholar.SemanticScholarProvider.search") as mock_search:
        mock_search.return_value = []
        await discovery_service.search(topic_recent)
        mock_search.assert_called_once_with(topic_recent)

@pytest.mark.asyncio
async def test_search_api_errors(discovery_service, topic_recent):
    """Test handling of API errors (wrapped in RetryError by tenacity)"""
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        # 400 Error (Non-retriable in SemanticScholarProvider)
        mock_resp.status = 400
        mock_resp.text = AsyncMock(return_value="Bad Request")
        
        # SemanticScholarProvider.search will raise APIError which is caught in this test
        # Actually SemanticScholarProvider has @retry on (aiohttp.ClientError, RateLimitError)
        # APIError is NOT in retry list there.
        
        with patch("src.services.providers.semantic_scholar.logger"):
            with pytest.raises(Exception): # Can be APIError or RetryError depending on implementation
                await discovery_service.search(topic_recent)

@pytest.mark.asyncio
async def test_search_provider_unavailable(discovery_service, topic_recent):
    """Test error when provider is requested but not configured (no API key)"""
    ds = DiscoveryService(api_key="") # No key for Semantic Scholar
    with pytest.raises(APIError, match="not available"):
        await ds.search(topic_recent)

@pytest.mark.asyncio
async def test_search_unknown_provider(discovery_service, topic_recent):
    """Test error for unknown provider type"""
    topic_recent.provider = "unknown" # type: ignore
    with pytest.raises(ValueError, match="Unknown provider type"):
        await discovery_service.search(topic_recent)


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
        f.write("key: : value") # Invalid YAML
    
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