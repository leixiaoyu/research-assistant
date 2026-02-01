"""LLM Service Failure Scenario Tests

Additional tests for edge cases in LLM service response parsing.
"""

import pytest
from unittest.mock import Mock, patch

from src.services.llm_service import LLMService
from src.models.llm import LLMConfig, CostLimits
from src.models.extraction import ExtractionTarget
from src.utils.exceptions import JSONParseError


@pytest.fixture
def anthropic_config():
    """Create test Anthropic LLM configuration"""
    return LLMConfig(
        provider="anthropic",
        model="claude-3-5-sonnet-20250122",
        api_key="sk-ant-test12345",
        max_tokens=100000,
        temperature=0.0,
        timeout=300,
    )


@pytest.fixture
def cost_limits():
    """Create test cost limits"""
    return CostLimits(
        max_tokens_per_paper=100000,
        max_daily_spend_usd=50.0,
        max_total_spend_usd=500.0,
    )


@pytest.fixture
def extraction_targets():
    """Create test extraction targets"""
    return [
        ExtractionTarget(
            name="system_prompts",
            description="Extract system prompts",
            output_format="list",
            required=False,
        ),
    ]


class TestResponseParsingEdgeCases:
    """Tests for response parsing edge cases"""

    def test_parse_response_with_non_json_text(
        self, anthropic_config, cost_limits, extraction_targets
    ):
        """Test handling of non-JSON response text"""
        with patch("anthropic.AsyncAnthropic"):
            service = LLMService(anthropic_config, cost_limits)

            mock_response = Mock()
            mock_response.content = [Mock(text="This is plain text, not JSON")]

            with pytest.raises(JSONParseError):
                service._parse_response(mock_response, extraction_targets)

    def test_parse_response_with_malformed_json(
        self, anthropic_config, cost_limits, extraction_targets
    ):
        """Test handling of malformed JSON"""
        with patch("anthropic.AsyncAnthropic"):
            service = LLMService(anthropic_config, cost_limits)

            mock_response = Mock()
            mock_response.content = [Mock(text="{invalid json structure")]

            with pytest.raises(JSONParseError):
                service._parse_response(mock_response, extraction_targets)

    def test_parse_response_missing_extractions_key(
        self, anthropic_config, cost_limits, extraction_targets
    ):
        """Test handling of JSON without extractions key"""
        with patch("anthropic.AsyncAnthropic"):
            service = LLMService(anthropic_config, cost_limits)

            mock_response = Mock()
            mock_response.content = [Mock(text='{"wrong_key": []}')]

            with pytest.raises(JSONParseError):
                service._parse_response(mock_response, extraction_targets)


class TestCostCalculationEdgeCases:
    """Tests for cost calculation edge cases"""

    def test_calculate_cost_anthropic_zero_tokens(self, anthropic_config, cost_limits):
        """Test cost calculation with zero tokens"""
        with patch("anthropic.AsyncAnthropic"):
            service = LLMService(anthropic_config, cost_limits)

            mock_usage = Mock()
            mock_usage.input_tokens = 0
            mock_usage.output_tokens = 0

            cost = service._calculate_cost_anthropic(mock_usage)
            assert cost == 0.0

    def test_calculate_cost_anthropic_large_tokens(self, anthropic_config, cost_limits):
        """Test cost calculation with large token counts"""
        with patch("anthropic.AsyncAnthropic"):
            service = LLMService(anthropic_config, cost_limits)

            mock_usage = Mock()
            mock_usage.input_tokens = 1000000  # 1M tokens
            mock_usage.output_tokens = 100000  # 100K tokens

            cost = service._calculate_cost_anthropic(mock_usage)
            # Expected: (1M/1M * 3.00) + (100K/1M * 15.00) = 3.0 + 1.5 = 4.5
            assert abs(cost - 4.5) < 0.01


class TestProviderInitialization:
    """Tests for provider initialization"""

    def test_anthropic_initialization(self, anthropic_config, cost_limits):
        """Test Anthropic client initialization"""
        with patch("anthropic.AsyncAnthropic") as mock_client:
            service = LLMService(anthropic_config, cost_limits)

            assert service.client is not None
            mock_client.assert_called_once_with(api_key=anthropic_config.api_key)

    def test_google_initialization(self, cost_limits):
        """Test Google client initialization"""
        config = LLMConfig(
            provider="google",
            model="gemini-1.5-pro",
            api_key="google-test-key",
        )

        with (
            patch("google.generativeai.configure") as mock_configure,
            patch("google.generativeai.GenerativeModel") as mock_model,
        ):
            service = LLMService(config, cost_limits)

            assert service.client is not None
            mock_configure.assert_called_once_with(api_key=config.api_key)
            mock_model.assert_called_once_with(config.model)
