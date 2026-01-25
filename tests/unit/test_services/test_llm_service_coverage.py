import pytest
import json
from unittest.mock import Mock, patch, AsyncMock
from src.services.llm_service import LLMService
from src.models.llm import LLMConfig, CostLimits, UsageStats
from src.models.extraction import ExtractionTarget
from src.utils.exceptions import (
    ExtractionError,
    CostLimitExceeded,
    LLMAPIError,
    JSONParseError,
)


@pytest.fixture
def llm_config():
    return LLMConfig(
        provider="anthropic",
        model="claude-3-5-sonnet-20250122",
        api_key="test-key",
        max_tokens=1000,
    )


@pytest.fixture
def cost_limits():
    return CostLimits(
        max_tokens_per_paper=10000, max_daily_spend_usd=10.0, max_total_spend_usd=100.0
    )


@pytest.fixture
def llm_service(llm_config, cost_limits):
    with patch("anthropic.AsyncAnthropic"):
        return LLMService(llm_config, cost_limits)


class TestLLMServiceCoverage:
    def test_init_anthropic_import_error(self, llm_config, cost_limits):
        """Test missing anthropic package"""
        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(
                ExtractionError, match="anthropic package not installed"
            ):
                LLMService(llm_config, cost_limits)

    def test_init_google_import_error(self, llm_config, cost_limits):
        """Test missing google-generativeai package"""
        llm_config.provider = "google"
        with patch.dict("sys.modules", {"google.generativeai": None}):
            with pytest.raises(
                ExtractionError, match="google-generativeai package not installed"
            ):
                LLMService(llm_config, cost_limits)

    def test_check_cost_limits_total(self, llm_service):
        """Test total cost limit exceeded"""
        llm_service.usage_stats.total_cost_usd = 101.0
        with pytest.raises(CostLimitExceeded, match="Total spending limit reached"):
            llm_service._check_cost_limits()

    def test_check_cost_limits_daily(self, llm_service):
        """Test daily cost limit exceeded"""
        llm_service.usage_stats.total_cost_usd = 11.0
        with pytest.raises(CostLimitExceeded, match="Daily spending limit reached"):
            llm_service._check_cost_limits()

    @pytest.mark.asyncio
    async def test_call_anthropic_error(self, llm_service):
        """Test Anthropic API error"""
        llm_service.client.messages.create.side_effect = Exception("API Error")
        with pytest.raises(LLMAPIError, match="Anthropic API error"):
            await llm_service._call_anthropic("prompt")

    @pytest.mark.asyncio
    async def test_call_google_error(self, llm_config, cost_limits):
        """Test Google API error"""
        llm_config.provider = "google"
        with patch("google.generativeai.GenerativeModel") as mock_model:
            with patch("google.generativeai.configure"):
                service = LLMService(llm_config, cost_limits)
                service.client.generate_content_async.side_effect = Exception(
                    "API Error"
                )

                with pytest.raises(LLMAPIError, match="Google API error"):
                    await service._call_google("prompt")

    def test_parse_response_invalid_json(self, llm_service):
        """Test parsing invalid JSON"""
        mock_response = Mock()
        mock_response.content = [Mock(text="Not JSON")]

        with pytest.raises(JSONParseError, match="Invalid JSON"):
            llm_service._parse_response(mock_response, [])

    def test_parse_response_missing_extractions(self, llm_service):
        """Test JSON missing 'extractions' key"""
        mock_response = Mock()
        mock_response.content = [Mock(text='{"foo": "bar"}')]

        with pytest.raises(JSONParseError, match="Missing 'extractions' key"):
            llm_service._parse_response(mock_response, [])

    def test_parse_response_extractions_not_list(self, llm_service):
        """Test 'extractions' is not a list"""
        mock_response = Mock()
        mock_response.content = [Mock(text='{"extractions": {}}')]

        with pytest.raises(JSONParseError, match="'extractions' must be a list"):
            llm_service._parse_response(mock_response, [])

    def test_parse_response_missing_target_name(self, llm_service):
        """Test extraction missing target_name"""
        mock_response = Mock()
        mock_response.content = [Mock(text='{"extractions": [{"success": true}]}')]

        # Should just warn and continue (log check hard here, but ensures no crash)
        results = llm_service._parse_response(mock_response, [])
        assert len(results) == 0

    def test_parse_response_unknown_target(self, llm_service):
        """Test extraction with unknown target name"""
        mock_response = Mock()
        mock_response.content = [
            Mock(text='{"extractions": [{"target_name": "unknown"}]}')
        ]

        results = llm_service._parse_response(mock_response, [])
        assert len(results) == 0

    def test_parse_response_required_missing(self, llm_service):
        """Test required target missing from response"""
        target = ExtractionTarget(
            name="req", description="desc", output_format="text", required=True
        )
        mock_response = Mock()
        mock_response.content = [Mock(text='{"extractions": []}')]

        results = llm_service._parse_response(mock_response, [target])
        assert len(results) == 1
        assert results[0].success is False
        assert "Required target not found" in results[0].error

    def test_parse_response_google_format(self, llm_config, cost_limits):
        """Test parsing response from Google (different structure)"""
        llm_config.provider = "google"
        with patch("google.generativeai.GenerativeModel"):
            with patch("google.generativeai.configure"):
                service = LLMService(llm_config, cost_limits)
                mock_response = Mock()
                mock_response.text = '{"extractions": []}'

                results = service._parse_response(mock_response, [])
                assert isinstance(results, list)

        def test_parse_response_markdown_json(self, llm_service):

            """Test parsing JSON wrapped in markdown code blocks"""

            mock_response = Mock()

            mock_response.content = [Mock(text='```json\n{"extractions": []}\n```')]

            

            results = llm_service._parse_response(mock_response, [])

            assert isinstance(results, list)

    

        @pytest.mark.asyncio

        async def test_extract_llm_api_error(self, llm_service):

            """Test extract catching LLMAPIError"""

            llm_service.client.messages.create.side_effect = Exception("API Error")

            

            # Mock metadata

            metadata = Mock()

            metadata.paper_id = "123"

            metadata.title = "Test"

            

            with pytest.raises(LLMAPIError, match="LLM API call failed"):

                await llm_service.extract("markdown", [], metadata)

    

        @pytest.mark.asyncio

        async def test_extract_json_parse_error(self, llm_service):

            """Test extract catching JSONParseError"""

            # Mock successful API response but invalid JSON

            mock_response = Mock()

            mock_response.content = [Mock(text="Invalid JSON")]

            llm_service.client.messages.create.return_value = mock_response

            

            # Mock metadata

            metadata = Mock()

            metadata.paper_id = "123"

            metadata.title = "Test"

            

            with pytest.raises(JSONParseError):

                await llm_service.extract("markdown", [], metadata)

    

        def test_parse_response_json_decode_error(self, llm_service):

            """Test _parse_response raising JSONParseError on decode error"""

            mock_response = Mock()

            mock_response.content = [Mock(text="Invalid JSON")]

            

            with pytest.raises(JSONParseError, match="Invalid JSON in LLM response"):

                llm_service._parse_response(mock_response, [])

    
