"""Unit tests for LLM Service (Phase 2)

Tests for:
- LLM service initialization
- Prompt building
- Response parsing
- Cost calculation
- Budget enforcement
- Usage tracking
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timedelta
import json

from src.services.llm_service import LLMService
from src.models.llm import LLMConfig, CostLimits
from src.models.extraction import ExtractionTarget
from src.models.paper import PaperMetadata, Author
from src.utils.exceptions import CostLimitExceeded, LLMAPIError, JSONParseError


@pytest.fixture
def llm_config():
    """Create test LLM configuration"""
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
        max_tokens_per_paper=100000, max_daily_spend_usd=50.0, max_total_spend_usd=500.0
    )


@pytest.fixture
def llm_service(llm_config, cost_limits):
    """Create LLM service instance"""
    with patch("anthropic.AsyncAnthropic"):
        service = LLMService(config=llm_config, cost_limits=cost_limits)
    return service


@pytest.fixture
def paper_metadata():
    """Create test paper metadata"""
    return PaperMetadata(
        paper_id="2301.12345",
        title="Test Paper on Machine Learning",
        abstract="This is a test abstract about ML.",
        url="https://example.com/paper",
        authors=[Author(name="John Doe"), Author(name="Jane Smith")],
        year=2023,
        citation_count=10,
        venue="ArXiv",
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
        ExtractionTarget(
            name="code_snippets",
            description="Extract Python code",
            output_format="code",
            required=False,
        ),
    ]


def test_llm_service_initialization_anthropic(llm_config, cost_limits):
    """Test LLM service initializes with Anthropic"""
    with patch("anthropic.AsyncAnthropic") as mock_anthropic:
        service = LLMService(llm_config, cost_limits)

        assert service.config.provider == "anthropic"
        assert service.client is not None
        mock_anthropic.assert_called_once_with(api_key=llm_config.api_key)


def test_llm_service_initialization_google():
    """Test LLM service initializes with Google"""
    config = LLMConfig(
        provider="google", model="gemini-1.5-pro", api_key="google-test-key"
    )
    limits = CostLimits()

    mock_client = Mock()
    with patch("google.genai.Client", return_value=mock_client) as mock_client_class:
        service = LLMService(config, limits)

        assert service.config.provider == "google"
        mock_client_class.assert_called_once_with(api_key=config.api_key)
        assert service._google_model == "gemini-1.5-pro"


def test_build_extraction_prompt(llm_service, paper_metadata, extraction_targets):
    """Test extraction prompt building"""
    markdown = "# Test Paper\n\nThis is test content."

    prompt = llm_service._build_extraction_prompt(
        markdown, extraction_targets, paper_metadata
    )

    # Check prompt contains key elements
    assert paper_metadata.title in prompt
    assert "John Doe" in prompt
    assert "system_prompts" in prompt
    assert "code_snippets" in prompt
    assert markdown in prompt
    assert "JSON" in prompt


def test_parse_response_valid_json(llm_service, extraction_targets):
    """Test parsing valid JSON response"""
    # Mock Anthropic response
    mock_response = Mock()
    mock_response.content = [
        Mock(
            text=json.dumps(
                {
                    "extractions": [
                        {
                            "target_name": "system_prompts",
                            "success": True,
                            "content": ["Prompt 1", "Prompt 2"],
                            "confidence": 0.95,
                        },
                        {
                            "target_name": "code_snippets",
                            "success": True,
                            "content": "def example(): pass",
                            "confidence": 0.85,
                        },
                    ]
                }
            )
        )
    ]

    results = llm_service._parse_response(mock_response, extraction_targets)

    assert len(results) == 2
    assert results[0].target_name == "system_prompts"
    assert results[0].success is True
    assert len(results[0].content) == 2
    assert results[0].confidence == 0.95
    assert results[1].target_name == "code_snippets"


def test_parse_response_with_markdown_code_blocks(llm_service, extraction_targets):
    """Test parsing JSON wrapped in markdown code blocks"""
    # LLM sometimes wraps JSON in code blocks
    json_content = {
        "extractions": [
            {
                "target_name": "system_prompts",
                "success": True,
                "content": ["Test"],
                "confidence": 0.9,
            }
        ]
    }

    wrapped_json = f"```json\n{json.dumps(json_content)}\n```"

    mock_response = Mock()
    mock_response.content = [Mock(text=wrapped_json)]

    results = llm_service._parse_response(mock_response, extraction_targets)

    assert len(results) == 1
    assert results[0].target_name == "system_prompts"


def test_parse_response_invalid_json(llm_service, extraction_targets):
    """Test parsing invalid JSON raises JSONParseError"""
    mock_response = Mock()
    mock_response.content = [Mock(text="This is not valid JSON")]

    with pytest.raises(JSONParseError) as exc_info:
        llm_service._parse_response(mock_response, extraction_targets)

    assert "Invalid JSON" in str(exc_info.value)


def test_parse_response_missing_extractions_key(llm_service, extraction_targets):
    """Test parsing JSON without 'extractions' key"""
    mock_response = Mock()
    mock_response.content = [Mock(text='{"wrong_key": []}')]

    with pytest.raises(JSONParseError) as exc_info:
        llm_service._parse_response(mock_response, extraction_targets)

    assert "Missing 'extractions'" in str(exc_info.value)


def test_parse_response_required_target_missing(llm_service):
    """Test parsing adds error for missing required target"""
    targets = [
        ExtractionTarget(name="required_field", description="Test", required=True)
    ]

    # Response missing the required target
    mock_response = Mock()
    mock_response.content = [Mock(text=json.dumps({"extractions": []}))]

    results = llm_service._parse_response(mock_response, targets)

    # Should have one result with error
    assert len(results) == 1
    assert results[0].target_name == "required_field"
    assert results[0].success is False
    assert results[0].error is not None


def test_calculate_cost_anthropic(llm_service):
    """Test cost calculation for Claude"""
    mock_usage = Mock()
    mock_usage.input_tokens = 10000
    mock_usage.output_tokens = 5000

    cost = llm_service._calculate_cost_anthropic(mock_usage)

    # Expected: (10000/1M * 3.00) + (5000/1M * 15.00) = 0.03 + 0.075 = 0.105
    expected = 0.105
    assert abs(cost - expected) < 0.001


def test_calculate_cost_google(llm_service):
    """Test cost calculation for Gemini"""
    total_tokens = 15000

    cost = llm_service._calculate_cost_google(total_tokens)

    # Expected: 15000/1M * ((1.25 + 5.00) / 2) = 0.015 * 3.125 = 0.046875
    expected = 0.046875
    assert abs(cost - expected) < 0.001


def test_check_cost_limits_within_budget(llm_service):
    """Test cost check passes when within budget"""
    llm_service.usage_stats.total_cost_usd = 10.0

    # Should not raise
    llm_service._check_cost_limits()


def test_check_cost_limits_total_exceeded(llm_service):
    """Test cost check fails when total budget exceeded"""
    llm_service.usage_stats.total_cost_usd = 600.0  # Exceeds max_total_spend_usd (500)

    with pytest.raises(CostLimitExceeded) as exc_info:
        llm_service._check_cost_limits()

    assert "Total spending limit" in str(exc_info.value)


def test_check_cost_limits_daily_exceeded(llm_service):
    """Test cost check fails when daily budget exceeded"""
    llm_service.usage_stats.total_cost_usd = 55.0  # Exceeds max_daily_spend_usd (50)

    with pytest.raises(CostLimitExceeded) as exc_info:
        llm_service._check_cost_limits()

    assert "Daily spending limit" in str(exc_info.value)


def test_update_usage(llm_service):
    """Test usage statistics update"""
    initial_tokens = llm_service.usage_stats.total_tokens
    initial_cost = llm_service.usage_stats.total_cost_usd
    initial_papers = llm_service.usage_stats.papers_processed

    llm_service._update_usage(tokens=50000, cost=2.5)

    assert llm_service.usage_stats.total_tokens == initial_tokens + 50000
    assert llm_service.usage_stats.total_cost_usd == initial_cost + 2.5
    assert llm_service.usage_stats.papers_processed == initial_papers + 1


def test_get_usage_summary(llm_service):
    """Test usage summary generation"""
    llm_service.usage_stats.total_tokens = 100000
    llm_service.usage_stats.total_cost_usd = 5.0
    llm_service.usage_stats.papers_processed = 10

    summary = llm_service.get_usage_summary()

    assert summary["total_tokens"] == 100000
    assert summary["total_cost_usd"] == 5.0
    assert summary["papers_processed"] == 10
    assert summary["daily_budget_remaining"] == 45.0  # 50 - 5
    assert summary["total_budget_remaining"] == 495.0  # 500 - 5


@pytest.mark.asyncio
async def test_extract_success(llm_service, paper_metadata, extraction_targets):
    """Test successful extraction"""
    markdown = "# Test Paper\n\nContent here."

    # Mock LLM response
    mock_response = Mock()
    mock_response.content = [
        Mock(
            text=json.dumps(
                {
                    "extractions": [
                        {
                            "target_name": "system_prompts",
                            "success": True,
                            "content": ["Prompt 1"],
                            "confidence": 0.9,
                        }
                    ]
                }
            )
        )
    ]
    mock_response.usage = Mock(input_tokens=10000, output_tokens=5000)

    # Phase 3.3: Mock _call_anthropic_raw instead of _call_anthropic
    llm_service._call_anthropic_raw = AsyncMock(return_value=mock_response)

    result = await llm_service.extract(markdown, extraction_targets, paper_metadata)

    assert result.paper_id == "2301.12345"
    assert len(result.extraction_results) == 1
    assert result.tokens_used == 15000
    assert result.cost_usd > 0


@pytest.mark.asyncio
async def test_extract_daily_reset(llm_service, paper_metadata, extraction_targets):
    """Test extraction resets daily stats when needed"""
    # Set last_reset to yesterday
    yesterday = datetime.utcnow() - timedelta(days=1)
    llm_service.usage_stats.last_reset = yesterday
    llm_service.usage_stats.total_tokens = 100000
    llm_service.usage_stats.total_cost_usd = 10.0

    markdown = "# Test"

    mock_response = Mock()
    mock_response.content = [Mock(text=json.dumps({"extractions": []}))]
    mock_response.usage = Mock(input_tokens=1000, output_tokens=500)

    # Phase 3.3: Mock _call_anthropic_raw instead of _call_anthropic
    llm_service._call_anthropic_raw = AsyncMock(return_value=mock_response)

    await llm_service.extract(markdown, extraction_targets, paper_metadata)

    # Stats should be reset
    assert llm_service.usage_stats.total_tokens == 1500  # Only current extraction
    assert llm_service.usage_stats.last_reset > yesterday


@pytest.mark.asyncio
async def test_extract_cost_limit_check(
    llm_service, paper_metadata, extraction_targets
):
    """Test extraction checks cost limits before calling LLM"""
    # Set cost to exceed limit
    llm_service.usage_stats.total_cost_usd = 600.0

    markdown = "# Test"

    with pytest.raises(CostLimitExceeded):
        await llm_service.extract(markdown, extraction_targets, paper_metadata)


@pytest.mark.asyncio
async def test_extract_api_error(llm_service, paper_metadata, extraction_targets):
    """Test extraction handles API errors (all providers fail)"""
    from src.utils.exceptions import AllProvidersFailedError

    markdown = "# Test"

    # Phase 3.3: Mock _call_anthropic_raw to raise LLMAPIError
    llm_service._call_anthropic_raw = AsyncMock(side_effect=LLMAPIError("API Error"))

    with pytest.raises(AllProvidersFailedError) as exc_info:
        await llm_service.extract(markdown, extraction_targets, paper_metadata)

    # The error should include the provider error
    assert "anthropic" in str(exc_info.value).lower()
