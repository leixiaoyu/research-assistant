import pytest
import aiohttp
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, date
from pathlib import Path

from src.services.discovery_service import DiscoveryService, APIError, RateLimitError
from src.services.catalog_service import CatalogService
from src.services.config_manager import ConfigManager, ConfigValidationError
from src.models.config import ResearchTopic, TimeframeRecent, TimeframeSinceYear, TimeframeDateRange
from src.models.catalog import Catalog, TopicCatalogEntry

# --- Discovery Service Tests ---

@pytest.fixture
def discovery_service():
    return DiscoveryService("key")

@pytest.fixture
def topic_recent():
    return ResearchTopic(
        query="test", 
        timeframe=TimeframeRecent(value="48h"), 
        max_papers=5
    )

@pytest.fixture
def topic_since_year():
    return ResearchTopic(
        query="test", 
        timeframe=TimeframeSinceYear(value=2023), 
        max_papers=5
    )

@pytest.fixture
def topic_date_range():
    return ResearchTopic(
        query="test", 
        timeframe=TimeframeDateRange(start_date=date(2023,1,1), end_date=date(2023,1,2)), 
        max_papers=5
    )

def test_build_query_params_timeframes(discovery_service, topic_recent, topic_since_year, topic_date_range):
    # Recent (hours)
    params = discovery_service._build_query_params(topic_recent)
    assert ":" in params["publicationDateOrYear"]
    
    # Recent (days)
    topic_recent.timeframe = TimeframeRecent(value="2d")
    params = discovery_service._build_query_params(topic_recent)
    assert ":" in params["publicationDateOrYear"]
    
    # Since Year
    params = discovery_service._build_query_params(topic_since_year)
    assert params["year"] == "2023-"
    
    # Date Range
    params = discovery_service._build_query_params(topic_date_range)
    assert params["publicationDateOrYear"] == "2023-01-01:2023-01-02"

@pytest.mark.asyncio
async def test_search_api_errors(discovery_service, topic_recent):
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = AsyncMock()
        mock_get.return_value.__aenter__.return_value = mock_resp
        
        # 500 Error
        mock_resp.status = 500
        with pytest.raises(Exception): # Tenacity retry error
            await discovery_service.search(topic_recent)
            
        # 400 Error (Non-retriable)
        mock_resp.status = 400
        mock_resp.text.return_value = "Bad Request"
        with pytest.raises(APIError):
            await discovery_service.search(topic_recent)

@pytest.mark.asyncio
async def test_search_timeout(discovery_service, topic_recent):
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_get.side_effect = asyncio.TimeoutError
        with pytest.raises(APIError, match="timed out"):
             await discovery_service.search(topic_recent)

def test_parse_response_edge_cases(discovery_service):
    # Empty data
    assert discovery_service._parse_response({}) == []
    assert discovery_service._parse_response({"data": []}) == []
    
    # Malformed item (should skip)
    data = {
        "data": [
            {"paperId": "1", "title": "Good"},
            {"title": "Missing ID"} # Missing paperId -> KeyError -> caught -> continue
        ]
    }
    papers = discovery_service._parse_response(data)
    assert len(papers) == 1
    assert papers[0].paper_id == "1"

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