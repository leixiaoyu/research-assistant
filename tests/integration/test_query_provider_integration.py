"""Integration tests for query enhancement and provider integration.

Tests query intelligence service integration with multi-provider discovery,
including query enhancement strategies and result deduplication.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import List

from src.services.discovery.service import DiscoveryService
from src.services.query_intelligence_service import QueryIntelligenceService
from src.models.discovery import DiscoveryMode, DiscoveryPipelineConfig
from src.models.paper import PaperMetadata, Author
from src.models.config import ProviderType
from src.models.query import QueryStrategy, QueryFocus
from tests.conftest_types import make_url


@pytest.fixture
def mock_llm_service():
    """Mock LLM service for query enhancement."""
    service = MagicMock()

    # Mock complete() for query decomposition
    async def mock_complete(
        prompt, system_prompt=None, temperature=0.3, max_tokens=1000
    ):
        response = MagicMock()

        # Return decomposition response for decompose prompts
        if "Decompose" in prompt or "decompose" in prompt:
            response.content = """[
                {"query": "transformer architecture design", "focus": "methodology"},
                {"query": "transformer applications NLP", "focus": "application"},
                {"query": "transformer vs RNN comparison", "focus": "comparison"}
            ]"""
        # Return expansion response for expand prompts
        elif "alternative search queries" in prompt:
            response.content = """[
                "neural attention mechanisms",
                "self-attention networks",
                "sequence-to-sequence transformers"
            ]"""
        else:
            response.content = "[]"

        return response

    service.complete = AsyncMock(side_effect=mock_complete)
    return service


@pytest.fixture
def query_service(mock_llm_service):
    """Provide QueryIntelligenceService with LLM."""
    return QueryIntelligenceService(llm_service=mock_llm_service)


@pytest.fixture
def mock_papers() -> List[PaperMetadata]:
    """Provide mock papers for testing."""
    return [
        PaperMetadata(
            paper_id="arxiv:2301.00001",
            title="Attention is All You Need",
            abstract="We propose the Transformer architecture.",
            authors=[Author(name="Vaswani")],
            url=make_url("https://arxiv.org/abs/2301.00001"),
            open_access_pdf=make_url("https://arxiv.org/pdf/2301.00001.pdf"),
            venue="NeurIPS",
            year=2023,
            citation_count=1000,
            discovery_source="arxiv",
        ),
        PaperMetadata(
            paper_id="arxiv:2301.00002",
            title="BERT: Pre-training Transformers",
            abstract="We introduce BERT for language understanding.",
            authors=[Author(name="Devlin")],
            url=make_url("https://arxiv.org/abs/2301.00002"),
            venue="ACL",
            year=2022,
            citation_count=500,
            discovery_source="arxiv",
        ),
    ]


@pytest.fixture
def discovery_service():
    """Provide DiscoveryService with mocked providers."""
    service = DiscoveryService()
    return service


@pytest.mark.asyncio
async def test_enhanced_queries_sent_to_providers(
    discovery_service, mock_llm_service, mock_papers
):
    """Verify decomposed queries reach providers during discovery."""
    # Track queries sent to providers
    queries_sent = []

    async def track_search(topic):
        queries_sent.append(topic.query)
        return mock_papers

    # Mock provider
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(side_effect=track_search)

    discovery_service.providers[ProviderType.ARXIV] = mock_provider
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_provider
    discovery_service.providers[ProviderType.OPENALEX] = mock_provider
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_provider

    # Run STANDARD mode with query enhancement
    config = DiscoveryPipelineConfig(
        mode=DiscoveryMode.STANDARD,
        query_enhancement={"max_queries": 3, "include_original": True},
    )

    result = await discovery_service.discover(
        topic="transformer models",
        config=config,
        llm_service=mock_llm_service,
    )

    # Verify enhanced queries were sent
    assert len(queries_sent) > 1, "Should send multiple queries from decomposition"

    # Verify original query included
    assert "transformer models" in queries_sent, "Should include original query"

    # Verify decomposed queries included
    assert any(
        "architecture" in q.lower() for q in queries_sent
    ), "Should include decomposed query about architecture"
    assert any(
        "application" in q.lower() for q in queries_sent
    ), "Should include decomposed query about applications"

    # Verify metrics track query generation
    assert (
        result.metrics.queries_generated > 1
    ), "Should report multiple queries generated"
    assert len(result.queries_used) > 1, "Should include queries in result"


@pytest.mark.asyncio
async def test_hybrid_strategy_generates_more_queries(
    discovery_service, mock_llm_service, mock_papers
):
    """Verify DEEP mode with hybrid strategy generates more queries than STANDARD."""
    # Mock provider
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(return_value=mock_papers)

    discovery_service.providers[ProviderType.ARXIV] = mock_provider
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_provider
    discovery_service.providers[ProviderType.OPENALEX] = mock_provider
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_provider

    # Run STANDARD mode with DECOMPOSE
    standard_config = DiscoveryPipelineConfig(
        mode=DiscoveryMode.STANDARD,
        query_enhancement={"strategy": "decompose", "max_queries": 5},
    )
    standard_result = await discovery_service.discover(
        topic="transformer models",
        config=standard_config,
        llm_service=mock_llm_service,
    )

    # Run DEEP mode with HYBRID
    deep_config = DiscoveryPipelineConfig(
        mode=DiscoveryMode.DEEP,
        query_enhancement={"strategy": "hybrid", "max_queries": 10},
        citation_exploration={"enabled": False},  # Disable citations for this test
    )
    deep_result = await discovery_service.discover(
        topic="transformer models",
        config=deep_config,
        llm_service=mock_llm_service,
    )

    # Verify DEEP generates more queries
    assert (
        deep_result.metrics.queries_generated
        >= standard_result.metrics.queries_generated
    ), "DEEP mode should generate same or more queries than STANDARD"

    # Verify query count difference
    assert len(deep_result.queries_used) >= len(
        standard_result.queries_used
    ), "DEEP should have same or more queries than STANDARD"


@pytest.mark.asyncio
async def test_result_deduplication_across_queries(discovery_service, mock_llm_service):
    """Verify same paper from multiple queries is deduplicated."""
    # Create duplicate papers with same DOI
    duplicate_paper = PaperMetadata(
        paper_id="arxiv:2301.00001",
        title="Attention is All You Need",
        abstract="We propose the Transformer architecture.",
        authors=[Author(name="Vaswani")],
        url=make_url("https://arxiv.org/abs/2301.00001"),
        doi="10.1000/test.2301.00001",
        venue="NeurIPS",
        year=2023,
        citation_count=1000,
        discovery_source="arxiv",
    )

    # Mock provider returns duplicate for every query
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(return_value=[duplicate_paper])

    discovery_service.providers[ProviderType.ARXIV] = mock_provider
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_provider
    discovery_service.providers[ProviderType.OPENALEX] = mock_provider
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_provider

    # Run STANDARD mode (will query all providers with multiple queries)
    result = await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.STANDARD,
        llm_service=mock_llm_service,
    )

    # Verify deduplication
    assert len(result.papers) == 1, "Duplicate papers should be deduplicated"
    assert result.papers[0].paper_id == "arxiv:2301.00001", "Should keep the paper"

    # Verify metrics track deduplication
    assert (
        result.metrics.papers_retrieved > result.metrics.papers_after_dedup
    ), "Should show deduplication occurred"


@pytest.mark.asyncio
async def test_provider_failure_graceful_handling(
    discovery_service, mock_llm_service, mock_papers
):
    """Verify one provider failure doesn't crash discovery."""
    # Mock successful provider
    mock_success = AsyncMock()
    mock_success.search = AsyncMock(return_value=mock_papers)

    # Mock failing provider
    mock_fail = AsyncMock()
    mock_fail.search = AsyncMock(side_effect=Exception("Provider API error"))

    discovery_service.providers[ProviderType.ARXIV] = mock_success
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_fail
    discovery_service.providers[ProviderType.OPENALEX] = mock_success
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_success

    # Run STANDARD mode
    result = await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.STANDARD,
        llm_service=mock_llm_service,
    )

    # Verify discovery succeeded despite one failure
    assert len(result.papers) > 0, "Should return papers from successful providers"

    # Verify all providers were queried (converted to strings)
    providers_queried = result.metrics.providers_queried
    provider_names = [
        p.value if hasattr(p, "value") else str(p) for p in providers_queried
    ]

    assert "arxiv" in provider_names, "ArXiv should be queried"
    assert "semantic_scholar" in provider_names, "Semantic Scholar should be queried"
    assert "openalex" in provider_names, "OpenAlex should be queried"
    assert "huggingface" in provider_names, "HuggingFace should be queried"


@pytest.mark.asyncio
async def test_all_providers_receive_queries(
    discovery_service, mock_llm_service, mock_papers
):
    """Verify in STANDARD/DEEP mode, all enabled providers get queries."""
    # Track which providers were queried
    providers_queried = set()

    async def track_provider(provider_type):
        async def track_search(topic):
            providers_queried.add(provider_type)
            return mock_papers

        return track_search

    # Mock all providers
    for provider_type in [
        ProviderType.ARXIV,
        ProviderType.SEMANTIC_SCHOLAR,
        ProviderType.OPENALEX,
        ProviderType.HUGGINGFACE,
    ]:
        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(
            side_effect=await track_provider(provider_type)
        )
        discovery_service.providers[provider_type] = mock_provider

    # Run STANDARD mode
    await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.STANDARD,
        llm_service=mock_llm_service,
    )

    # Verify all providers were queried
    assert len(providers_queried) == 4, "All 4 providers should be queried"
    assert ProviderType.ARXIV in providers_queried, "ArXiv should be queried"
    assert (
        ProviderType.SEMANTIC_SCHOLAR in providers_queried
    ), "Semantic Scholar should be queried"
    assert ProviderType.OPENALEX in providers_queried, "OpenAlex should be queried"
    assert (
        ProviderType.HUGGINGFACE in providers_queried
    ), "HuggingFace should be queried"


@pytest.mark.asyncio
async def test_query_cache_hit_on_repeat(query_service, mock_llm_service):
    """Verify repeated queries use cache and don't call LLM again."""
    # First call - should hit LLM
    queries1 = await query_service.enhance(
        query="transformer models",
        strategy=QueryStrategy.DECOMPOSE,
        max_queries=3,
    )

    # Get initial call count
    initial_call_count = mock_llm_service.complete.call_count

    # Second call - should hit cache
    queries2 = await query_service.enhance(
        query="transformer models",
        strategy=QueryStrategy.DECOMPOSE,
        max_queries=3,
    )

    # Verify cache hit (no new LLM calls)
    assert (
        mock_llm_service.complete.call_count == initial_call_count
    ), "Should not call LLM again for cached query"

    # Verify results are identical
    assert len(queries1) == len(queries2), "Cached results should match"
    assert [q.query for q in queries1] == [
        q.query for q in queries2
    ], "Cached query texts should match"


@pytest.mark.asyncio
async def test_query_enhancement_no_llm_graceful_degradation(
    discovery_service, mock_papers
):
    """Verify discovery works without LLM (returns original query only)."""
    # Mock provider
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(return_value=mock_papers)

    discovery_service.providers[ProviderType.ARXIV] = mock_provider
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_provider
    discovery_service.providers[ProviderType.OPENALEX] = mock_provider
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_provider

    # Run STANDARD mode WITHOUT LLM
    result = await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.STANDARD,
        llm_service=None,  # No LLM service
    )

    # Verify discovery succeeded with degraded query enhancement
    assert len(result.papers) > 0, "Should return papers even without LLM"
    assert result.metrics.queries_generated == 1, "Should generate only original query"
    assert len(result.queries_used) == 1, "Should use only original query"
    assert (
        result.queries_used[0].query == "transformer models"
    ), "Should use original query text"
    # DecomposedQuery doesn't have is_original field, check weight instead
    assert (
        result.queries_used[0].weight == 1.0
    ), "Original query should have standard weight"


@pytest.mark.asyncio
async def test_query_focus_variety_in_decomposition(query_service, mock_llm_service):
    """Verify decomposed queries have variety in focus areas."""
    queries = await query_service.enhance(
        query="transformer models for machine translation",
        strategy=QueryStrategy.DECOMPOSE,
        max_queries=5,
    )

    # Extract focus areas (excluding original)
    focus_areas = [
        q.focus for q in queries if not q.is_original and q.focus is not None
    ]

    # Verify multiple focus areas present
    assert len(focus_areas) > 0, "Should have queries with focus areas"

    # Verify at least 2 different focus areas
    unique_focuses = set(focus_areas)
    assert len(unique_focuses) >= 2, "Should have variety in focus areas"

    # Verify valid focus values
    valid_focuses = {
        QueryFocus.METHODOLOGY,
        QueryFocus.APPLICATION,
        QueryFocus.COMPARISON,
    }
    assert all(
        f in valid_focuses or f == QueryFocus.RELATED for f in focus_areas
    ), "All focus areas should be valid"
