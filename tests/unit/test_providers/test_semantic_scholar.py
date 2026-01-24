import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.providers.semantic_scholar import SemanticScholarProvider, APIError, RateLimitError
from src.models.config import ResearchTopic, TimeframeRecent

@pytest.fixture
def topic():
    return ResearchTopic(
        query="test query",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=10
    )

@pytest.fixture
def provider():
    return SemanticScholarProvider(api_key="test_key")

@pytest.mark.asyncio
async def test_search_success(provider, topic):
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
        
        papers = await provider.search(topic)
        
        assert len(papers) == 1
        assert papers[0].paper_id == "123"
        assert papers[0].title == "Test Paper"

@pytest.mark.asyncio
async def test_search_rate_limit(provider, topic):
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp_obj = AsyncMock()
        mock_resp_obj.status = 429
        mock_get.return_value.__aenter__.return_value = mock_resp_obj
        
        with pytest.raises(Exception): # Tenacity retry error
            await provider.search(topic)

def test_build_query_params(provider, topic):
    params = provider._build_query_params(topic, topic.query)
    assert params["query"] == "test query"
    assert "publicationDateOrYear" in params
    assert ":" in params["publicationDateOrYear"]
