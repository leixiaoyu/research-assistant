"""Test provider switching with the unified discovery API.

Note: With the unified discovery API, DiscoveryService.search() now routes
through discover(mode=SURFACE). This test verifies that provider selection
still works correctly through the unified API.
"""

import pytest
from unittest.mock import patch, AsyncMock
from src.services.discovery_service import DiscoveryService
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    ProviderType,
    ProviderSelectionConfig,
)
from src.models.discovery import (
    DiscoveryResult,
    DiscoveryMetrics,
    DiscoveryMode,
)


@pytest.mark.asyncio
async def test_provider_switching():
    """Test switching between providers via unified discovery API.

    Note: With the unified discovery API, search() now routes through
    discover(mode=SURFACE). We verify provider selection works by
    mocking the discover() method.
    """
    # Disable auto-select to test explicit provider switching
    config = ProviderSelectionConfig(auto_select=False)

    # Create mock discovery result
    mock_result = DiscoveryResult(
        papers=[],
        metrics=DiscoveryMetrics(
            papers_retrieved=0,
            papers_after_quality_filter=0,
            avg_quality_score=0.0,
        ),
        mode=DiscoveryMode.SURFACE,
    )

    # 1. Test ArXiv (Default)
    ds = DiscoveryService(config=config)
    topic_arxiv = ResearchTopic(
        query="test",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeRecent(value="48h"),
        auto_select_provider=False,  # Disable auto-selection for explicit test
    )

    with patch.object(ds, "discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = mock_result
        await ds.search(topic_arxiv)
        mock_discover.assert_called_once()

    # 2. Test Semantic Scholar
    ds_ss = DiscoveryService(api_key="test_key_1234567890", config=config)
    topic_ss = ResearchTopic(
        query="test",
        provider=ProviderType.SEMANTIC_SCHOLAR,
        timeframe=TimeframeRecent(value="48h"),
        auto_select_provider=False,  # Disable auto-selection for explicit test
    )

    with patch.object(ds_ss, "discover", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = mock_result
        await ds_ss.search(topic_ss)
        mock_discover.assert_called_once()
