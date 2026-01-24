import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.services.providers.arxiv import ArxivProvider, APIError, RateLimitError
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
)
from datetime import date
from tenacity import RetryError, stop_after_attempt
import time


@pytest.fixture
def provider():
    p = ArxivProvider()
    p.search.retry.stop = stop_after_attempt(1)
    return p


@pytest.fixture
def topic():
    return ResearchTopic(
        query="test", timeframe=TimeframeRecent(value="48h"), max_papers=5
    )


@pytest.mark.asyncio
async def test_search_invalid_query_returns_empty(provider, topic):
    topic.query = "invalid; char"
    papers = await provider.search(topic)
    assert papers == []


@pytest.mark.asyncio
async def test_network_error(provider, topic):
    with patch("src.services.providers.arxiv.feedparser.parse") as mock_parse:
        mock_parse.side_effect = Exception("Connection reset")
        try:
            await provider.search(topic)
            assert False, "Should have raised"
        except RetryError as e:
            assert isinstance(e.last_attempt.exception(), APIError)
            assert "Connection reset" in str(e.last_attempt.exception())


@pytest.mark.asyncio
async def test_api_status_errors(provider, topic):
    # 403
    mock_feed_403 = MagicMock()
    mock_feed_403.status = 403
    with patch(
        "src.services.providers.arxiv.feedparser.parse", return_value=mock_feed_403
    ):
        try:
            await provider.search(topic)
            assert False, "Should have raised RateLimitError"
        except RetryError as e:
            assert isinstance(e.last_attempt.exception(), RateLimitError)

    # 500
    mock_feed_500 = MagicMock()
    mock_feed_500.status = 500
    with patch(
        "src.services.providers.arxiv.feedparser.parse", return_value=mock_feed_500
    ):
        try:
            await provider.search(topic)
            assert False, "Should have raised APIError"
        except RetryError as e:
            assert isinstance(e.last_attempt.exception(), APIError)
            assert "status 500" in str(e.last_attempt.exception())


@pytest.mark.asyncio
async def test_bozo_warning(provider, topic):
    mock_feed = MagicMock()
    mock_feed.status = 200
    mock_feed.bozo = 1
    mock_feed.bozo_exception = "XML Error"
    mock_feed.entries = []

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        with patch("src.services.providers.arxiv.logger") as mock_logger:
            await provider.search(topic)
            mock_logger.warning.assert_called_with(
                "arxiv_feed_parse_warning", error="XML Error"
            )


def test_build_query_timeframes(provider, topic):
    # Recent (Hours)
    topic.timeframe = TimeframeRecent(value="48h")
    q = provider._build_query_params(topic, "test")
    assert "submittedDate" in q

    # Recent (Days) - Covers lines 105-106
    topic.timeframe = TimeframeRecent(value="7d")
    q = provider._build_query_params(topic, "test")
    assert "submittedDate" in q

    # Since Year
    topic.timeframe = TimeframeSinceYear(value=2024)
    q = provider._build_query_params(topic, "test")
    assert "submittedDate" in q
    assert "202401010000" in q

    # Date Range
    topic.timeframe = TimeframeDateRange(
        start_date=date(2023, 1, 1), end_date=date(2023, 1, 2)
    )
    q2 = provider._build_query_params(topic, "test")
    assert "submittedDate" in q2
    assert "202301010000" in q2
    assert "202301022359" in q2


@pytest.mark.asyncio
async def test_parse_entry_exception(provider, topic):
    mock_feed = MagicMock()
    mock_feed.status = 200

    bad_entry = MagicMock()
    type(bad_entry).title = PropertyMock(side_effect=Exception("Parse fail"))

    mock_feed.entries = [bad_entry]

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        with patch("src.services.providers.arxiv.logger") as mock_logger:
            papers = await provider.search(topic)
            assert len(papers) == 0
            args, kwargs = mock_logger.warning.call_args
            assert args[0] == "arxiv_entry_parse_error"
            assert kwargs["error"] == "Parse fail"


def test_validate_pdf_url_upgrade(provider):
    url = provider._validate_pdf_url("http://arxiv.org/pdf/2301.12345.pdf")
    assert url == "https://arxiv.org/pdf/2301.12345.pdf"


@pytest.mark.asyncio
async def test_rate_limiting_enforces_3_second_delay():
    """
    SR-1.5-1: Runtime verification that ArXiv rate limiting enforces delay.
    """
    provider = ArxivProvider()

    # Create minimal topic for testing
    topic = ResearchTopic(
        query="test", timeframe=TimeframeRecent(value="48h"), max_papers=1
    )

    # Mock feedparser to return quickly
    mock_feed = MagicMock()
    mock_feed.status = 200
    mock_feed.bozo = False
    mock_feed.entries = []

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        # First request - establish baseline
        await provider.search(topic)

        # Second request - should be delayed by rate limiter
        start = time.time()
        await provider.search(topic)
        second_request_time = time.time() - start

        # The second request should have been delayed by ~3 seconds
        assert (
            second_request_time >= 2.9
        ), f"Rate limiter failed: second request took {second_request_time}s"

        # Verify it's not excessively delayed (sanity check)
        assert (
            second_request_time < 4.0
        ), f"Rate limiter delayed too much: {second_request_time}s"
