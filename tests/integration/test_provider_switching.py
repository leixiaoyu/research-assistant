import pytest
from unittest.mock import patch, AsyncMock
from src.services.discovery_service import DiscoveryService
from src.models.config import ResearchTopic, TimeframeRecent, ProviderType


@pytest.mark.asyncio
async def test_provider_switching():
    """Test switching between providers"""
    # 1. Test ArXiv (Default)
    ds = DiscoveryService()
    topic_arxiv = ResearchTopic(
        query="test",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeRecent(value="48h"),
    )

    with patch(
        "src.services.providers.arxiv.ArxivProvider.search", new_callable=AsyncMock
    ) as mock_arxiv:
        mock_arxiv.return_value = []
        await ds.search(topic_arxiv)
        mock_arxiv.assert_called_once()

    # 2. Test Semantic Scholar
    ds_ss = DiscoveryService(api_key="test_key_1234567890")
    topic_ss = ResearchTopic(
        query="test",
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"),
    )

    with patch(
        "src.services.providers.semantic_scholar." "SemanticScholarProvider.search",
        new_callable=AsyncMock,
    ) as mock_ss:
        mock_ss.return_value = []
        await ds_ss.search(topic_ss)
        mock_ss.assert_called_once()
