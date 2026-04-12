"""Integration tests for unified discovery with quality scoring.

Tests end-to-end discovery with quality intelligence across all three modes:
SURFACE, STANDARD, and DEEP.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List

from src.services.discovery.service import DiscoveryService
from src.services.quality_intelligence_service import QualityIntelligenceService
from src.services.venue_repository import YamlVenueRepository
from src.models.discovery import (
    DiscoveryMode,
    DiscoveryPipelineConfig,
    ScoredPaper,
)
from src.models.paper import PaperMetadata, Author
from src.models.config import ProviderType


@pytest.fixture
def venue_repository():
    """Provide YamlVenueRepository for quality scoring."""
    return YamlVenueRepository()


@pytest.fixture
def quality_service(venue_repository):
    """Provide QualityIntelligenceService with venue repository."""
    return QualityIntelligenceService(venue_repository=venue_repository)


@pytest.fixture
def mock_llm_service():
    """Mock LLM service for query enhancement."""
    service = MagicMock()

    # Mock complete() for query decomposition
    async def mock_complete(
        prompt, system_prompt=None, temperature=0.3, max_tokens=1000
    ):
        response = MagicMock()
        # Return decomposed queries
        response.content = """[
            {"query": "transformer architecture optimization", "focus": "methodology"},
            {"query": "transformer applications NLP", "focus": "application"}
        ]"""
        return response

    service.complete = AsyncMock(side_effect=mock_complete)
    return service


@pytest.fixture
def mock_papers() -> List[PaperMetadata]:
    """Provide realistic mock papers with varying quality signals."""
    return [
        # High quality: Top venue, many citations, recent
        PaperMetadata(
            paper_id="arxiv:2301.00001",
            title="Attention is All You Need",
            abstract=(
                "We propose the Transformer, a novel architecture based "
                "entirely on attention mechanisms."
            ),
            authors=[Author(name="Vaswani"), Author(name="Shazeer")],
            url="https://arxiv.org/abs/2301.00001",
            open_access_pdf="https://arxiv.org/pdf/2301.00001.pdf",
            venue="NeurIPS",
            publication_date="2023",
            citation_count=1000,
            source=ProviderType.ARXIV,
        ),
        # Good quality: Good venue, moderate citations
        PaperMetadata(
            paper_id="arxiv:2301.00002",
            title="BERT: Pre-training of Deep Bidirectional Transformers",
            abstract="We introduce BERT, a new language representation model.",
            authors=[Author(name="Devlin"), Author(name="Chang")],
            url="https://arxiv.org/abs/2301.00002",
            open_access_pdf="https://arxiv.org/pdf/2301.00002.pdf",
            venue="ACL",
            publication_date="2022",
            citation_count=500,
            source=ProviderType.ARXIV,
        ),
        # Fair quality: Medium venue, low citations
        PaperMetadata(
            paper_id="arxiv:2301.00003",
            title="GPT-3: Language Models are Few-Shot Learners",
            abstract=(
                "We demonstrate that scaling up language models improves "
                "task performance."
            ),
            authors=[Author(name="Brown"), Author(name="Mann")],
            url="https://arxiv.org/abs/2301.00003",
            venue="EMNLP",
            publication_date="2021",
            citation_count=50,
            source=ProviderType.ARXIV,
        ),
        # Low quality: No venue, few citations, old
        PaperMetadata(
            paper_id="arxiv:2301.00004",
            title="A Simple Neural Network Approach",
            abstract="We present a basic neural network for text processing.",
            authors=[Author(name="Smith")],
            url="https://arxiv.org/abs/2301.00004",
            publication_date="2015",
            citation_count=5,
            source=ProviderType.ARXIV,
        ),
    ]


@pytest.fixture
def discovery_service():
    """Provide DiscoveryService with mocked providers."""
    service = DiscoveryService()
    return service


@pytest.mark.asyncio
async def test_discover_surface_with_real_quality_scoring(
    discovery_service, quality_service, mock_papers
):
    """Verify SURFACE mode scores papers correctly with real quality service."""
    # Mock provider to return papers
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(return_value=mock_papers)
    discovery_service.providers[ProviderType.ARXIV] = mock_provider

    # Execute SURFACE discovery
    result = await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.SURFACE,
    )

    # Verify papers are scored
    assert len(result.papers) > 0, "Should return scored papers"

    for paper in result.papers:
        assert isinstance(paper, ScoredPaper), "Papers should be ScoredPaper instances"
        assert 0.0 <= paper.quality_score <= 1.0, "Quality score should be normalized"
        assert paper.quality_score > 0.0, "Papers should have non-zero quality scores"

    # Verify papers are sorted by quality
    scores = [p.quality_score for p in result.papers]
    assert scores == sorted(
        scores, reverse=True
    ), "Papers should be sorted by quality score"

    # Verify high-quality paper (NeurIPS, 1000 citations) has highest score
    top_paper = result.papers[0]
    assert top_paper.venue == "NeurIPS", "Top paper should be from top venue"
    assert top_paper.citation_count == 1000, "Top paper should have most citations"

    # Verify metrics
    assert result.metrics.avg_quality_score > 0.0, "Should report average quality"
    assert result.mode == DiscoveryMode.SURFACE, "Should report correct mode"


@pytest.mark.asyncio
async def test_discover_standard_with_quality_filtering(
    discovery_service, mock_llm_service, mock_papers
):
    """Verify STANDARD mode applies quality threshold correctly."""
    # Mock provider to return papers
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(return_value=mock_papers)
    discovery_service.providers[ProviderType.ARXIV] = mock_provider
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_provider
    discovery_service.providers[ProviderType.OPENALEX] = mock_provider
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_provider

    # Set strict quality threshold
    config = DiscoveryPipelineConfig(
        mode=DiscoveryMode.STANDARD,
        min_quality_score=0.5,  # Filter out low-quality papers
    )

    result = await discovery_service.discover(
        topic="transformer models",
        config=config,
        llm_service=mock_llm_service,
    )

    # Verify filtering applied
    assert len(result.papers) < len(mock_papers), "Should filter out low-quality papers"

    # Verify all returned papers meet threshold
    for paper in result.papers:
        assert paper.quality_score >= 0.5, f"Paper {paper.title} below threshold"

    # Verify metrics track filtering
    assert (
        result.metrics.papers_after_quality_filter <= result.metrics.papers_after_dedup
    )
    assert result.metrics.avg_quality_score >= 0.5, "Average should be above threshold"


@pytest.mark.asyncio
async def test_discover_deep_with_full_scoring(
    discovery_service, mock_llm_service, mock_papers
):
    """Verify DEEP mode uses all quality signals including relevance."""
    # Mock provider to return papers
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(return_value=mock_papers)
    discovery_service.providers[ProviderType.ARXIV] = mock_provider
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_provider
    discovery_service.providers[ProviderType.OPENALEX] = mock_provider
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_provider

    # Mock RelevanceRanker to add relevance scores
    with patch("src.services.relevance_ranker.RelevanceRanker") as MockRanker:
        mock_ranker = MagicMock()

        async def mock_rank(papers, query):
            # Add relevance scores to papers
            ranked = []
            for paper in papers:
                scored = ScoredPaper.from_paper_metadata(
                    paper=paper,
                    quality_score=(
                        paper.quality_score if hasattr(paper, "quality_score") else 0.5
                    ),
                    relevance_score=0.8,  # High relevance
                )
                ranked.append(scored)
            return ranked

        mock_ranker.rank = AsyncMock(side_effect=mock_rank)
        MockRanker.return_value = mock_ranker

        config = DiscoveryPipelineConfig(
            mode=DiscoveryMode.DEEP,
            enable_relevance_ranking=True,
            min_relevance_score=0.5,
            citation_exploration={"enabled": False},  # Disable citations for this test
        )

        result = await discovery_service.discover(
            topic="transformer models",
            config=config,
            llm_service=mock_llm_service,
        )

        # Verify relevance scores assigned
        for paper in result.papers:
            assert (
                paper.relevance_score is not None
            ), "DEEP mode should assign relevance"
            assert 0.0 <= paper.relevance_score <= 1.0, "Relevance should be normalized"

        # Verify final_score combines quality and relevance
        for paper in result.papers:
            expected_final = 0.4 * paper.quality_score + 0.6 * paper.relevance_score
            assert (
                abs(paper.final_score - expected_final) < 0.01
            ), "Final score formula mismatch"

        # Verify metrics
        assert (
            result.metrics.avg_relevance_score > 0.0
        ), "Should report average relevance"


@pytest.mark.asyncio
async def test_score_consistency_across_modes(
    discovery_service, quality_service, mock_papers
):
    """Verify same papers get same quality scores regardless of mode."""
    # Mock provider
    mock_provider = AsyncMock()
    mock_provider.search = AsyncMock(return_value=mock_papers)
    discovery_service.providers[ProviderType.ARXIV] = mock_provider
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_provider
    discovery_service.providers[ProviderType.OPENALEX] = mock_provider
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_provider

    # Run SURFACE mode
    surface_result = await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.SURFACE,
    )

    # Run STANDARD mode (no LLM to avoid expansion)
    standard_result = await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.STANDARD,
    )

    # Build quality score maps
    surface_scores = {p.paper_id: p.quality_score for p in surface_result.papers}
    standard_scores = {p.paper_id: p.quality_score for p in standard_result.papers}

    # Verify overlapping papers have same scores
    common_ids = set(surface_scores.keys()) & set(standard_scores.keys())
    assert len(common_ids) > 0, "Should have overlapping papers"

    for paper_id in common_ids:
        assert abs(surface_scores[paper_id] - standard_scores[paper_id]) < 0.01, (
            f"Paper {paper_id} has different scores: "
            f"{surface_scores[paper_id]} vs {standard_scores[paper_id]}"
        )


@pytest.mark.asyncio
async def test_quality_tier_classification(
    discovery_service, quality_service, mock_papers
):
    """Verify papers are classified into correct quality tiers."""
    # Score papers with quality service
    scored_papers = [quality_service.score_paper(p) for p in mock_papers]

    # Verify tier classification
    for paper in scored_papers:
        tier = quality_service.get_tier(paper.quality_score)

        if paper.quality_score >= 0.80:
            assert (
                tier == "excellent"
            ), f"Paper with score {paper.quality_score} should be excellent"
        elif paper.quality_score >= 0.60:
            assert (
                tier == "good"
            ), f"Paper with score {paper.quality_score} should be good"
        elif paper.quality_score >= 0.40:
            assert (
                tier == "fair"
            ), f"Paper with score {paper.quality_score} should be fair"
        else:
            assert (
                tier == "low"
            ), f"Paper with score {paper.quality_score} should be low"

    # Verify high-quality papers in top tiers
    neurips_paper = next(p for p in scored_papers if p.venue == "NeurIPS")
    neurips_tier = quality_service.get_tier(neurips_paper.quality_score)
    assert neurips_tier in [
        "excellent",
        "good",
    ], "Top venue paper should be in top tiers"


@pytest.mark.asyncio
async def test_source_breakdown_accuracy(discovery_service, mock_papers):
    """Verify source tracking is accurate in discovery results."""
    # Mock multiple providers with different papers
    arxiv_papers = [mock_papers[0], mock_papers[1]]
    semantic_papers = [mock_papers[2]]
    openalex_papers = [mock_papers[3]]

    mock_arxiv = AsyncMock()
    mock_arxiv.search = AsyncMock(return_value=arxiv_papers)

    mock_semantic = AsyncMock()
    mock_semantic.search = AsyncMock(return_value=semantic_papers)

    mock_openalex = AsyncMock()
    mock_openalex.search = AsyncMock(return_value=openalex_papers)

    mock_hf = AsyncMock()
    mock_hf.search = AsyncMock(return_value=[])

    discovery_service.providers[ProviderType.ARXIV] = mock_arxiv
    discovery_service.providers[ProviderType.SEMANTIC_SCHOLAR] = mock_semantic
    discovery_service.providers[ProviderType.OPENALEX] = mock_openalex
    discovery_service.providers[ProviderType.HUGGINGFACE] = mock_hf

    # Run STANDARD mode to query all providers
    result = await discovery_service.discover(
        topic="transformer models",
        mode=DiscoveryMode.STANDARD,
    )

    # Verify source breakdown
    assert "arxiv" in result.source_breakdown, "Should track ArXiv source"
    assert (
        "semantic_scholar" in result.source_breakdown
    ), "Should track Semantic Scholar"
    assert "openalex" in result.source_breakdown, "Should track OpenAlex"

    # Verify counts match
    assert result.source_breakdown["arxiv"] == 2, "Should track 2 ArXiv papers"
    assert result.source_breakdown["semantic_scholar"] == 1, "Should track 1 SS paper"
    assert result.source_breakdown["openalex"] == 1, "Should track 1 OpenAlex paper"

    # Verify total matches
    total_from_breakdown = sum(result.source_breakdown.values())
    assert total_from_breakdown == len(
        result.papers
    ), "Breakdown should sum to total papers"
