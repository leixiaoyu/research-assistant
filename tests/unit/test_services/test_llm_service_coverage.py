import pytest
from unittest.mock import Mock, patch, AsyncMock
from src.services.llm_service import LLMService
from src.models.llm import LLMConfig, CostLimits
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
    async def test_call_anthropic_success(self, llm_service):
        """Test Anthropic API success path"""
        mock_response = Mock()
        llm_service.client.messages.create = AsyncMock(return_value=mock_response)
        response = await llm_service._call_anthropic("prompt")
        assert response == mock_response

    @pytest.mark.asyncio
    async def test_call_anthropic_error(self, llm_service):
        """Test Anthropic API error"""
        llm_service.client.messages.create = AsyncMock(
            side_effect=Exception("API Error")
        )
        with pytest.raises(LLMAPIError, match="Anthropic API error"):
            await llm_service._call_anthropic("prompt")

    @pytest.mark.asyncio
    async def test_call_google_success(self, llm_config, cost_limits):
        """Test Google API success path"""
        llm_config.provider = "google"
        with patch("google.generativeai.GenerativeModel"):
            with patch("google.generativeai.configure"):
                service = LLMService(llm_config, cost_limits)
                mock_response = Mock()
                service.client.generate_content_async = AsyncMock(
                    return_value=mock_response
                )
                response = await service._call_google("prompt")
                assert response == mock_response

    @pytest.mark.asyncio
    async def test_call_google_error(self, llm_config, cost_limits):
        """Test Google API error"""
        llm_config.provider = "google"
        with patch("google.generativeai.GenerativeModel"):
            with patch("google.generativeai.configure"):
                service = LLMService(llm_config, cost_limits)
                service.client.generate_content_async = AsyncMock(
                    side_effect=Exception("API Error")
                )
                with pytest.raises(LLMAPIError, match="Google API error"):
                    await service._call_google("prompt")

    @pytest.mark.asyncio
    async def test_extract_google_path(self, llm_config, cost_limits):
        """Test extract() using Google provider path"""
        llm_config.provider = "google"
        with patch("google.generativeai.GenerativeModel"):
            with patch("google.generativeai.configure"):
                service = LLMService(llm_config, cost_limits)

                mock_response = Mock()
                mock_response.text = '{"extractions": []}'
                mock_response.usage_metadata.total_token_count = 1000

                service.client.generate_content_async = AsyncMock(
                    return_value=mock_response
                )

                metadata = Mock(paper_id="123", title="Test", authors=[])
                result = await service.extract("markdown", [], metadata)
                assert result.paper_id == "123"
                assert result.tokens_used == 1000

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
        """Test required target missing"""
        target = ExtractionTarget(
            name="req", description="desc", output_format="text", required=True
        )
        mock_response = Mock()
        mock_response.content = [Mock(text='{"extractions": []}')]
        results = llm_service._parse_response(mock_response, [target])
        assert len(results) == 1
        assert results[0].success is False

    def test_parse_response_google_format(self, llm_config, cost_limits):
        """Test Google format"""
        llm_config.provider = "google"
        with patch("google.generativeai.GenerativeModel"):
            with patch("google.generativeai.configure"):
                service = LLMService(llm_config, cost_limits)
                mock_response = Mock()
                mock_response.text = '{"extractions": []}'
                results = service._parse_response(mock_response, [])
                assert isinstance(results, list)

    def test_parse_response_markdown_json_variants(self, llm_service):
        """Test various markdown JSON wrappings"""
        mock_response = Mock()
        # With ```json
        mock_response.content = [Mock(text='```json\n{"extractions": []}\n```')]
        assert isinstance(llm_service._parse_response(mock_response, []), list)

        # With plain ```
        mock_response.content = [Mock(text='```\n{"extractions": []}\n```')]
        assert isinstance(llm_service._parse_response(mock_response, []), list)

    def test_calculate_cost_google(self, llm_service):
        """Test Google cost calculation"""
        cost = llm_service._calculate_cost_google(1000000)
        assert cost == 3.125

    @pytest.mark.asyncio
    async def test_extract_llm_api_error(self, llm_service):
        """Test extract catching LLMAPIError"""
        llm_service.client.messages.create = AsyncMock(
            side_effect=Exception("API Error")
        )
        metadata = Mock(paper_id="123", title="Test", authors=[])
        with pytest.raises(LLMAPIError):
            await llm_service.extract("markdown", [], metadata)

    @pytest.mark.asyncio
    async def test_extract_json_parse_error(self, llm_service):
        """Test extract catching JSONParseError"""
        mock_response = Mock()
        mock_response.usage.input_tokens = 500
        mock_response.usage.output_tokens = 500
        llm_service._call_anthropic = AsyncMock(return_value=mock_response)

        # Mock _parse_response to raise JSONParseError
        llm_service._parse_response = Mock(side_effect=JSONParseError("Parse failed"))

        metadata = Mock(paper_id="123", title="Test", authors=[])
        with pytest.raises(JSONParseError, match="Parse failed"):
            await llm_service.extract("markdown", [], metadata)

    def test_parse_response_json_decode_error(self, llm_service):
        """Test _parse_response raising JSONParseError"""
        mock_response = Mock()
        mock_response.content = [Mock(text="Invalid JSON")]
        with pytest.raises(JSONParseError):
            llm_service._parse_response(mock_response, [])
