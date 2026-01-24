import pytest
from src.models.config import ResearchConfig, ResearchTopic, GlobalSettings, TimeframeRecent, ProviderType
from src.services.discovery_service import DiscoveryService
from src.services.providers.arxiv import ArxivProvider
from src.services.providers.semantic_scholar import SemanticScholarProvider

@pytest.mark.asyncio
async def test_provider_initialization():
    # 1. No API Key -> Only ArXiv
    service = DiscoveryService(api_key="")
    assert ProviderType.ARXIV in service.providers
    assert ProviderType.SEMANTIC_SCHOLAR not in service.providers
    assert isinstance(service.providers[ProviderType.ARXIV], ArxivProvider)

    # 2. With API Key -> Both
    service = DiscoveryService(api_key="test_key")
    assert ProviderType.ARXIV in service.providers
    assert ProviderType.SEMANTIC_SCHOLAR in service.providers
    assert isinstance(service.providers[ProviderType.SEMANTIC_SCHOLAR], SemanticScholarProvider)

@pytest.mark.asyncio
async def test_provider_routing():
    service = DiscoveryService(api_key="test_key")
    
    # Topic with ArXiv (Default)
    topic_arxiv = ResearchTopic(
        query="test",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=1
    )
    # Default is ArXiv
    assert topic_arxiv.provider == ProviderType.ARXIV
    
    # Topic with SS
    topic_ss = ResearchTopic(
        query="test",
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"),
        max_papers=1
    )
    
    # Mock providers to verify calls
    from unittest.mock import AsyncMock
    service.providers[ProviderType.ARXIV].search = AsyncMock(return_value=[])
    service.providers[ProviderType.SEMANTIC_SCHOLAR].search = AsyncMock(return_value=[])
    
    await service.search(topic_arxiv)
    service.providers[ProviderType.ARXIV].search.assert_called_once()
    service.providers[ProviderType.SEMANTIC_SCHOLAR].search.assert_not_called()
    
    service.providers[ProviderType.ARXIV].search.reset_mock()
    
    await service.search(topic_ss)
    service.providers[ProviderType.SEMANTIC_SCHOLAR].search.assert_called_once()
    service.providers[ProviderType.ARXIV].search.assert_not_called()

@pytest.mark.asyncio
async def test_missing_provider_error():
    service = DiscoveryService(api_key="") # SS not initialized
    
    topic_ss = ResearchTopic(
        query="test",
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"),
        max_papers=1
    )
    
    from src.services.providers.base import APIError
    with pytest.raises(APIError, match="configured but not available"):
        await service.search(topic_ss)
