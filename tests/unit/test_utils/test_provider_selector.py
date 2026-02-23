"""Comprehensive tests for ProviderSelector (Phase 3.2)."""

import pytest
from src.utils.provider_selector import (
    ProviderSelector,
    PROVIDER_CAPABILITIES,
    ARXIV_TERMS,
    CROSS_DISCIPLINARY_TERMS,
    HUGGINGFACE_TERMS,
)
from src.models.config import ResearchTopic, TimeframeRecent, ProviderType


@pytest.fixture
def selector():
    """Default provider selector."""
    return ProviderSelector()


@pytest.fixture
def topic_basic():
    """Basic topic for testing."""
    return ResearchTopic(
        query="machine learning",
        provider=ProviderType.ARXIV,
        timeframe=TimeframeRecent(value="48h"),
    )


class TestProviderCapabilities:
    """Test the provider capability matrix."""

    def test_capability_matrix_complete(self):
        """Verify all providers have capability entries."""
        assert ProviderType.ARXIV in PROVIDER_CAPABILITIES
        assert ProviderType.SEMANTIC_SCHOLAR in PROVIDER_CAPABILITIES
        assert ProviderType.HUGGINGFACE in PROVIDER_CAPABILITIES

    def test_capability_matrix_arxiv_values(self):
        """Verify ArXiv capability values."""
        arxiv_caps = PROVIDER_CAPABILITIES[ProviderType.ARXIV]
        assert arxiv_caps["citation_support"] is False
        assert arxiv_caps["pdf_access_rate"] == 1.0
        assert arxiv_caps["api_key_required"] is False

    def test_capability_matrix_semantic_scholar_values(self):
        """Verify Semantic Scholar capability values."""
        ss_caps = PROVIDER_CAPABILITIES[ProviderType.SEMANTIC_SCHOLAR]
        assert ss_caps["citation_support"] is True
        assert ss_caps["pdf_access_rate"] == 0.6
        assert ss_caps["api_key_required"] is True

    def test_capability_matrix_huggingface_values(self):
        """Verify HuggingFace capability values."""
        hf_caps = PROVIDER_CAPABILITIES[ProviderType.HUGGINGFACE]
        assert hf_caps["citation_support"] is False
        assert hf_caps["pdf_access_rate"] == 1.0
        assert hf_caps["api_key_required"] is False
        assert hf_caps["trending_support"] is True


class TestGetCapability:
    """Test get_capability method."""

    def test_get_capability_valid(self, selector):
        """Test retrieving valid capability."""
        result = selector.get_capability(ProviderType.ARXIV, "pdf_access_rate")
        assert result == 1.0

    def test_get_capability_missing_capability(self, selector):
        """Test retrieving missing capability."""
        result = selector.get_capability(ProviderType.ARXIV, "nonexistent")
        assert result is None

    def test_get_capability_invalid_provider(self, selector):
        """Test with non-existent provider."""
        # Create a mock invalid provider type
        result = selector.get_capability("invalid", "pdf_access_rate")  # type: ignore
        assert result is None


class TestExplicitProviderSelection:
    """Test explicit provider selection (auto_select_provider=False)."""

    def test_explicit_provider_available(self, selector):
        """Test explicit provider when available."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )
        result = selector.select_provider(topic, [ProviderType.ARXIV])
        assert result == ProviderType.ARXIV

    def test_explicit_provider_not_available(self, selector):
        """Test explicit provider when not available."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )
        with pytest.raises(ValueError, match="not available"):
            selector.select_provider(topic, [ProviderType.ARXIV])


class TestCitationBasedSelection:
    """Test selection based on min_citations requirement."""

    def test_min_citations_selects_semantic_scholar(self, selector):
        """Test min_citations selects Semantic Scholar."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            min_citations=10,
        )
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
            min_citations=10,
        )
        assert result == ProviderType.SEMANTIC_SCHOLAR

    def test_min_citations_without_semantic_scholar(self, selector):
        """Test min_citations when Semantic Scholar not available."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            min_citations=10,
        )
        # Should fall through to preference order
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV],
            min_citations=10,
        )
        assert result == ProviderType.ARXIV

    def test_min_citations_from_topic(self, selector):
        """Test min_citations from topic.min_citations."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            min_citations=5,
        )
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        )
        assert result == ProviderType.SEMANTIC_SCHOLAR


class TestArxivTermsDetection:
    """Test ArXiv-specific term detection."""

    @pytest.mark.parametrize(
        "query",
        [
            "arxiv preprint",
            "cs.ai paper",
            "cs.lg model",
            "stat.ml algorithm",
            "physics simulation",
            "quant-ph experiment",
        ],
    )
    def test_arxiv_terms_detected(self, selector, query):
        """Test various ArXiv terms are detected."""
        topic = ResearchTopic(
            query=query,
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        )
        assert result == ProviderType.ARXIV

    def test_arxiv_terms_not_detected(self, selector):
        """Test non-ArXiv query doesn't select ArXiv."""
        topic = ResearchTopic(
            query="general search",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        )
        # Falls through to preference order (ArXiv first by default)
        assert result == ProviderType.ARXIV


class TestCrossDisciplinaryDetection:
    """Test cross-disciplinary term detection."""

    @pytest.mark.parametrize(
        "query",
        [
            "medicine and AI",
            "medical imaging",
            "psychology research",
            "sociology study",
            "biomedical engineering",
            "neuroscience paper",
            "clinical trial",
        ],
    )
    def test_cross_disciplinary_selects_semantic_scholar(self, selector, query):
        """Test cross-disciplinary queries select Semantic Scholar."""
        topic = ResearchTopic(
            query=query,
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        )
        assert result == ProviderType.SEMANTIC_SCHOLAR


class TestPreferenceOrder:
    """Test preference order fallback."""

    def test_default_preference_order(self, selector):
        """Test default preference order."""
        topic = ResearchTopic(
            query="general query",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        )
        # Default order: ArXiv first
        assert result == ProviderType.ARXIV

    def test_custom_preference_order(self):
        """Test custom preference order."""
        selector = ProviderSelector(
            preference_order=[ProviderType.SEMANTIC_SCHOLAR, ProviderType.ARXIV]
        )
        topic = ResearchTopic(
            query="general query",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )
        result = selector.select_provider(
            topic,
            [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        )
        assert result == ProviderType.SEMANTIC_SCHOLAR


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_no_providers_available(self, selector):
        """Test error when no providers available."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )
        with pytest.raises(ValueError, match="No providers available"):
            selector.select_provider(topic, [])

    def test_single_provider_available(self, selector):
        """Test with only one provider available."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )
        result = selector.select_provider(topic, [ProviderType.ARXIV])
        assert result == ProviderType.ARXIV

    def test_fallback_to_first_available_when_preference_not_available(self):
        """Test fallback to first available when preference order not available."""
        # Custom preference order that doesn't match available providers
        selector = ProviderSelector(
            preference_order=[ProviderType.SEMANTIC_SCHOLAR]  # Only SS in preference
        )
        topic = ResearchTopic(
            query="general query no special terms",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )
        # Only ArXiv available, but SS is the only preference
        result = selector.select_provider(topic, [ProviderType.ARXIV])
        # Should fallback to first available (ArXiv)
        assert result == ProviderType.ARXIV


class TestGetRecommendation:
    """Test get_recommendation method."""

    def test_recommendation_with_explicit_provider(self, selector):
        """Test recommendation with explicit provider."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            auto_select_provider=False,
        )
        provider, reason = selector.get_recommendation(topic, [ProviderType.ARXIV])
        assert provider == ProviderType.ARXIV
        assert "Explicit provider selection" in reason

    def test_recommendation_with_citations(self, selector):
        """Test recommendation with citation requirement."""
        topic = ResearchTopic(
            query="test",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
            min_citations=10,
        )
        provider, reason = selector.get_recommendation(
            topic, [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR]
        )
        assert provider == ProviderType.SEMANTIC_SCHOLAR
        assert "Citation filter" in reason

    def test_recommendation_with_arxiv_terms(self, selector):
        """Test recommendation with ArXiv terms."""
        topic = ResearchTopic(
            query="cs.ai paper",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )
        provider, reason = selector.get_recommendation(
            topic, [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR]
        )
        assert provider == ProviderType.ARXIV
        assert "ArXiv-specific terms" in reason

    def test_recommendation_with_cross_disciplinary(self, selector):
        """Test recommendation with cross-disciplinary terms."""
        topic = ResearchTopic(
            query="medicine research",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )
        provider, reason = selector.get_recommendation(
            topic, [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR]
        )
        assert provider == ProviderType.SEMANTIC_SCHOLAR
        assert "multiple disciplines" in reason

    def test_recommendation_with_preference_order(self, selector):
        """Test recommendation with preference order fallback."""
        topic = ResearchTopic(
            query="general query",
            provider=ProviderType.SEMANTIC_SCHOLAR,
            timeframe=TimeframeRecent(value="48h"),
        )
        provider, reason = selector.get_recommendation(
            topic, [ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR]
        )
        assert provider == ProviderType.ARXIV
        assert "preference order" in reason


class TestInternalMethods:
    """Test internal helper methods."""

    def test_has_arxiv_terms_true(self, selector):
        """Test _has_arxiv_terms returns True for ArXiv terms."""
        assert selector._has_arxiv_terms("arxiv preprint") is True
        assert selector._has_arxiv_terms("cs.ai research") is True
        assert selector._has_arxiv_terms("physics simulation") is True

    def test_has_arxiv_terms_false(self, selector):
        """Test _has_arxiv_terms returns False for non-ArXiv terms."""
        assert selector._has_arxiv_terms("general query") is False
        assert selector._has_arxiv_terms("medicine research") is False

    def test_has_cross_disciplinary_terms_true(self, selector):
        """Test _has_cross_disciplinary_terms returns True."""
        assert selector._has_cross_disciplinary_terms("medicine research") is True
        assert selector._has_cross_disciplinary_terms("psychology study") is True

    def test_has_cross_disciplinary_terms_false(self, selector):
        """Test _has_cross_disciplinary_terms returns False."""
        assert selector._has_cross_disciplinary_terms("general query") is False
        assert selector._has_cross_disciplinary_terms("cs.ai research") is False

    def test_has_huggingface_terms_true(self, selector):
        """Test _has_huggingface_terms returns True."""
        assert selector._has_huggingface_terms("llm training") is True
        assert selector._has_huggingface_terms("transformers library") is True
        assert selector._has_huggingface_terms("stable diffusion model") is True

    def test_has_huggingface_terms_false(self, selector):
        """Test _has_huggingface_terms returns False."""
        assert selector._has_huggingface_terms("general query") is False
        assert selector._has_huggingface_terms("medicine research") is False


class TestTermConstants:
    """Test term constant sets."""

    def test_arxiv_terms_contains_expected(self):
        """Test ARXIV_TERMS contains expected terms."""
        assert "arxiv" in ARXIV_TERMS
        assert "preprint" in ARXIV_TERMS
        assert "cs.ai" in ARXIV_TERMS
        assert "physics" in ARXIV_TERMS

    def test_cross_disciplinary_terms_contains_expected(self):
        """Test CROSS_DISCIPLINARY_TERMS contains expected terms."""
        assert "medicine" in CROSS_DISCIPLINARY_TERMS
        assert "psychology" in CROSS_DISCIPLINARY_TERMS
        assert "sociology" in CROSS_DISCIPLINARY_TERMS
        assert "neuroscience" in CROSS_DISCIPLINARY_TERMS

    def test_huggingface_terms_contains_expected(self):
        """Test HUGGINGFACE_TERMS contains expected terms."""
        assert "huggingface" in HUGGINGFACE_TERMS
        assert "llm" in HUGGINGFACE_TERMS
        assert "transformers" in HUGGINGFACE_TERMS
        assert "diffusion" in HUGGINGFACE_TERMS
        assert "rlhf" in HUGGINGFACE_TERMS


class TestHuggingFaceTermsDetection:
    """Test HuggingFace-specific term detection."""

    @pytest.mark.parametrize(
        "query",
        [
            "huggingface transformers",
            "large language model llm",
            "gpt fine-tuning",
            "stable diffusion",
            "rlhf training",
            "multimodal vision language model",
            "rag retrieval augmented generation",
        ],
    )
    def test_huggingface_terms_detected(self, selector, query):
        """Test various HuggingFace terms are detected."""
        topic = ResearchTopic(
            query=query,
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )
        result = selector.select_provider(
            topic,
            [
                ProviderType.ARXIV,
                ProviderType.SEMANTIC_SCHOLAR,
                ProviderType.HUGGINGFACE,
            ],
        )
        assert result == ProviderType.HUGGINGFACE

    def test_huggingface_recommendation_reason(self, selector):
        """Test recommendation reason for HuggingFace."""
        topic = ResearchTopic(
            query="llm fine-tuning",
            provider=ProviderType.ARXIV,
            timeframe=TimeframeRecent(value="48h"),
        )
        provider, reason = selector.get_recommendation(
            topic,
            [
                ProviderType.ARXIV,
                ProviderType.SEMANTIC_SCHOLAR,
                ProviderType.HUGGINGFACE,
            ],
        )
        assert provider == ProviderType.HUGGINGFACE
        assert "HuggingFace" in reason or "AI/ML trending" in reason
