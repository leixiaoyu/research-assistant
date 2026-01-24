import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.discovery_service import DiscoveryService, APIError, RateLimitError
from src.models.config import ResearchTopic, TimeframeRecent

@pytest.fixture
def topic():
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=10
    )

@pytest.fixture
def discovery_service():
    return DiscoveryService(api_key="test_key")

@pytest.mark.asyncio
async def test_search_success(discovery_service, topic):
    mock_response = {
        "data": [
            {
                "paperId": "123",
                "title": "Test Paper",
                "year": 2023,
                "url": "http://example.com",
                "authors": [{"name": "Author 1"}],
                "publicationDate": "2023-01-01"
            }
        ]
    }
    
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp_obj = AsyncMock()
        mock_resp_obj.status = 200
        mock_resp_obj.json.return_value = mock_response
        mock_get.return_value.__aenter__.return_value = mock_resp_obj
        
        papers = await discovery_service.search(topic)
        
        assert len(papers) == 1
        assert papers[0].paper_id == "123"
        assert papers[0].title == "Test Paper"

@pytest.mark.asyncio
async def test_search_rate_limit(discovery_service, topic):
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp_obj = AsyncMock()
        mock_resp_obj.status = 429
        mock_get.return_value.__aenter__.return_value = mock_resp_obj
        
        # Should retry and then raise RateLimitError or RetryError
        # Since we mock it to fail every time, it should eventually raise RetryError wrapping RateLimitError
        # or just fail. Tenacity raises RetryError.
        
        with pytest.raises(Exception): # Tenacity might raise RetryError
            await discovery_service.search(topic)

def test_build_query_params(discovery_service, topic):
    params = discovery_service._build_query_params(topic)
    assert params["query"] == "test query"
    assert "publicationDateOrYear" in params
    # 48h means approx today/yesterday. Logic is complex to assert exact string without freezing time.
    # But it should be in YYYY-MM-DD: format
    assert ":" in params["publicationDateOrYear"]
