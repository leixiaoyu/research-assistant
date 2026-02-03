import pytest
from unittest.mock import patch, AsyncMock
from src.services.discovery_service import DiscoveryService
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    ProviderType,
    ProviderSelectionConfig,
)


@pytest.mark.asyncio
async def test_provider_switching():
    """Test switching between providers"""
    # Disable auto-select to test explicit provider switching
    config = ProviderSelectionConfig(auto_select=False)

    # 1. Test ArXiv (Default)
    ds = DiscoveryService(config=config)
    topic_arxiv = ResearchTopic(
        query="test",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeRecent(value="48h"),
        auto_select_provider=False,  # Disable auto-selection for explicit test
    )

    with patch(
        "src.services.providers.arxiv.ArxivProvider.search", new_callable=AsyncMock
    ) as mock_arxiv:
        mock_arxiv.return_value = []
        await ds.search(topic_arxiv)
        mock_arxiv.assert_called_once()

    # 2. Test Semantic Scholar
    ds_ss = DiscoveryService(api_key="test_key_1234567890", config=config)
    topic_ss = ResearchTopic(
        query="test",
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"),
        auto_select_provider=False,  # Disable auto-selection for explicit test
    )

    with patch(
        "src.services.providers.semantic_scholar." "SemanticScholarProvider.search",
        new_callable=AsyncMock,
    ) as mock_ss:
        mock_ss.return_value = []
        await ds_ss.search(topic_ss)
        mock_ss.assert_called_once()
