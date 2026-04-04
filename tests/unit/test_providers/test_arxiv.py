import pytest
from unittest.mock import MagicMock, patch
from src.services.providers.arxiv import ArxivProvider, APIParameterError
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeSinceYear,
    TimeframeDateRange,
)
from datetime import date
from tenacity import RetryError


@pytest.fixture
def provider():
    return ArxivProvider()


@pytest.fixture
def topic_arxiv():
    return ResearchTopic(
        query="machine learning",
        provider="arxiv",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=5,
    )


def test_validate_query(provider):
    assert provider.validate_query("valid query") == "valid query"
    assert provider.validate_query("AI AND Robotics") == "AI AND Robotics"

    with pytest.raises(ValueError):
        provider.validate_query("test; rm -rf /")

    with pytest.raises(ValueError):
        provider.validate_query("$HOME")


def test_build_query_params(provider, topic_arxiv):
    # Recent - with structured query enabled by default
    q = provider._build_query_params(topic_arxiv, "machine learning")
    # Should use ti:/abs: fields (structured query) or all: (legacy)
    assert "search_query=" in q
    assert "submittedDate" in q
    # Verify structured query fields are present when enabled
    if provider.use_structured_query:
        assert "ti%3A" in q or "abs%3A" in q
    else:
        assert "all%3A" in q

    # Since Year
    topic_arxiv.timeframe = TimeframeSinceYear(value=2023)
    q = provider._build_query_params(topic_arxiv, "test")
    assert (
        "submittedDate%3A%5B202301010000%20TO%20300001010000%5D" in q
        or "submittedDate:[202301010000 TO 300001010000]" in q
    )

    # Date Range
    topic_arxiv.timeframe = TimeframeDateRange(
        start_date=date(2023, 1, 1), end_date=date(2023, 1, 2)
    )
    q = provider._build_query_params(topic_arxiv, "test")
    assert "submittedDate%3A%5B202301010000%20TO%20202301022359%5D" in q


def test_sortorder_parameter(provider, topic_arxiv):
    """Regression test: ArXiv requires 'descending', not 'desc'"""
    q = provider._build_query_params(topic_arxiv, "test")
    # Verify we use full word "descending" not abbreviated "desc"
    assert "sortOrder=descending" in q
    assert (
        "sortOrder=desc" not in q or "sortOrder=descending" in q
    )  # Ensure not just "desc"


@pytest.mark.asyncio
async def test_handles_301_with_valid_data(provider, topic_arxiv):
    """ArXiv returns 301 for redirects but may have valid data"""
    mock_feed = MagicMock()
    mock_feed.status = 301
    mock_feed.bozo = False

    # Valid data entry (not an error)
    entry = MagicMock()
    entry.id = "http://arxiv.org/abs/2301.12345v1"
    entry.title = "Test Paper"
    entry.summary = "Abstract"
    entry.link = "http://arxiv.org/abs/2301.12345v1"
    entry.published_parsed = (2023, 1, 1, 0, 0, 0, 0, 0, 0)
    author = MagicMock()
    author.name = "Author A"
    entry.authors = [author]
    link_pdf = MagicMock()
    link_pdf.type = "application/pdf"
    link_pdf.href = "https://arxiv.org/pdf/2301.12345.pdf"
    entry.links = [link_pdf]
    mock_feed.entries = [entry]

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        papers = await provider.search(topic_arxiv)
        # Should succeed despite 301 status
        assert len(papers) == 1
        assert papers[0].paper_id == "2301.12345v1"


@pytest.mark.asyncio
async def test_detects_301_error_response(provider, topic_arxiv):
    """ArXiv returns 301 with error message in entries for invalid params"""
    mock_feed = MagicMock()
    mock_feed.status = 301
    mock_feed.bozo = False

    # Error entry (ID points to help docs)
    error_entry = MagicMock()
    error_entry.id = "https://arxiv.org/help/api/user-manual#sort"
    error_entry.summary = "sortOrder must be in: ascending, descending"
    mock_feed.entries = [error_entry]

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        with pytest.raises(APIParameterError) as exc_info:
            await provider.search(topic_arxiv)
        assert "sortOrder must be in" in str(exc_info.value)


@pytest.mark.asyncio
async def test_detects_301_generic_error(provider, topic_arxiv):
    """ArXiv returns 301 without entries or recognized error"""
    mock_feed = MagicMock()
    mock_feed.status = 301
    mock_feed.entries = []

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        with pytest.raises(RetryError) as exc_info:
            await provider.search(topic_arxiv)
        # Check the underlying exception
        assert "returned status 301" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_search_success(provider, topic_arxiv):
    # Mock feedparser
    mock_feed = MagicMock()
    mock_feed.status = 200
    mock_feed.bozo = False

    entry = MagicMock()
    entry.id = "http://arxiv.org/abs/2301.12345v1"
    entry.title = "Test Paper"
    entry.summary = "Abstract"
    entry.link = "http://arxiv.org/abs/2301.12345v1"
    entry.published_parsed = (2023, 1, 1, 0, 0, 0, 0, 0, 0)

    author = MagicMock()
    author.name = "Author A"
    entry.authors = [author]

    link_pdf = MagicMock()
    link_pdf.type = "application/pdf"
    link_pdf.href = "https://arxiv.org/pdf/2301.12345.pdf"
    entry.links = [link_pdf]

    mock_feed.entries = [entry]

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        # We need to mock event loop run_in_executor?
        # Actually default loop handles it fine in pytest-asyncio usually.
        # But we mocked feedparser.parse which is called inside lambda.

        papers = await provider.search(topic_arxiv)

        assert len(papers) == 1
        assert papers[0].paper_id == "2301.12345v1"
        assert papers[0].title == "Test Paper"
        assert str(papers[0].open_access_pdf) == "https://arxiv.org/pdf/2301.12345.pdf"


def test_validate_pdf_url(provider):
    # Valid
    provider._validate_pdf_url("https://arxiv.org/pdf/2301.12345.pdf")
    provider._validate_pdf_url("https://arxiv.org/pdf/2301.12345v1.pdf")

    # Invalid
    from src.utils.security import SecurityError

    with pytest.raises(SecurityError):
        provider._validate_pdf_url("https://evil.com/malware.pdf")

    with pytest.raises(SecurityError):
        provider._validate_pdf_url("https://arxiv.org/pdf/../hack.pdf")


def test_arxiv_properties(provider):
    """Cover name and requires_api_key properties"""
    assert provider.name == "arxiv"
    assert provider.requires_api_key is False


# Phase 7 Fix I1: ArXiv Structured Query Tests


def test_structured_query_simple_terms():
    """Test structured query with simple terms"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.CL", "cs.LG"],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query("machine learning")

    # Exact match for two-term query
    expected = "((ti:machine OR abs:machine) (ti:learning OR abs:learning)) AND (cat:cs.CL OR cat:cs.LG)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_structured_query_quoted_phrases():
    """Test structured query with quoted phrases for exact matching"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query('"tree of thoughts" reasoning')

    # Exact match for quoted phrase + term
    expected = '((ti:"tree of thoughts" OR abs:"tree of thoughts") (ti:reasoning OR abs:reasoning)) AND (cat:cs.AI)'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_structured_query_no_categories():
    """Test structured query without category filter"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=[],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query("neural networks")

    # Exact match for two terms without category filter
    expected = "(ti:neural OR abs:neural) (ti:networks OR abs:networks)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_legacy_query_when_disabled():
    """Test that legacy all: query is used when structured query is disabled"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=False,
    )
    provider = ArxivProvider(settings=settings)

    topic = ResearchTopic(
        query="machine learning",
        provider="arxiv",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=5,
    )

    params = provider._build_query_params(topic, "machine learning")

    # Should use legacy all: field
    assert "all%3Amachine%20learning" in params or "all:machine learning" in params


def test_structured_query_in_build_params():
    """Test that structured query is used in _build_query_params"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.CL"],
    )
    provider = ArxivProvider(settings=settings)

    topic = ResearchTopic(
        query="transformers attention",
        provider="arxiv",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=10,
    )

    params = provider._build_query_params(topic, "transformers attention")

    # Should NOT use all: field
    assert "all%3A" not in params
    # Should include title/abstract fields
    assert "ti%3A" in params or "abs%3A" in params
    # Should include category
    assert "cat%3A" in params or "cat:" in params


def test_structured_query_with_timeframe():
    """Test structured query preserves timeframe filtering"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    topic = ResearchTopic(
        query="GPT",
        provider="arxiv",
        timeframe=TimeframeSinceYear(value=2023),
        max_papers=20,
    )

    params = provider._build_query_params(topic, "GPT")

    # Should have structured query
    assert "ti%3A" in params or "abs%3A" in params
    # Should have timeframe
    assert "submittedDate" in params
    assert "202301010000" in params


def test_default_settings_use_structured_query():
    """Test that provider defaults to structured query when no settings provided"""
    provider = ArxivProvider()

    # Should default to structured query enabled
    assert provider.use_structured_query is True
    assert provider.default_categories == ["cs.CL", "cs.LG", "cs.AI"]


def test_structured_query_boolean_operators():
    """Test structured query handles Boolean operators correctly"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    # Query with AND operator
    query = provider._build_structured_query("neural AND networks")

    # Exact match with AND operator preserved
    expected = (
        "((ti:neural OR abs:neural) AND (ti:networks OR abs:networks)) AND (cat:cs.AI)"
    )
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_structured_query_or_operator():
    """Test structured query preserves OR operator"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query("transformers OR attention")

    # Exact match with OR operator preserved
    expected = "((ti:transformers OR abs:transformers) OR (ti:attention OR abs:attention)) AND (cat:cs.AI)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_structured_query_not_operator():
    """Test structured query preserves NOT operator"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query("transformers NOT reinforcement")

    # Exact match with NOT operator preserved
    expected = "((ti:transformers OR abs:transformers) NOT (ti:reinforcement OR abs:reinforcement)) AND (cat:cs.AI)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_structured_query_mixed_operators():
    """Test structured query with multiple Boolean operators"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query("GPT AND (summarization OR translation)")

    # Exact match with parentheses and mixed operators
    expected = "((ti:GPT OR abs:GPT) AND ((ti:summarization OR abs:summarization) OR (ti:translation OR abs:translation))) AND (cat:cs.AI)"   # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_structured_query_quoted_phrase_with_boolean():
    """Test structured query with quoted phrases and Boolean operators"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.CL"],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query(
        '"machine learning" OR "deep learning" AND neural'
    )

    # Exact match with quoted phrases and Boolean operators
    expected = '((ti:"machine learning" OR abs:"machine learning") OR (ti:"deep learning" OR abs:"deep learning") AND (ti:neural OR abs:neural)) AND (cat:cs.CL)'  # noqa: E501
    assert query == expected, f"Expected: {expected}\nGot: {query}"


def test_structured_query_empty_string():
    """Test that empty query raises ValueError"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    with pytest.raises(ValueError, match="Query cannot be empty"):
        provider._build_structured_query("")

    with pytest.raises(ValueError, match="Query cannot be empty"):
        provider._build_structured_query("   ")


def test_structured_query_only_quotes():
    """Test query with only empty quoted phrases"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.AI"],
    )
    provider = ArxivProvider(settings=settings)

    # Query with only quotes but no content - should still have category filter
    query = provider._build_structured_query('""')

    # Should have category filter at minimum
    assert "cat:cs.AI" in query


def test_structured_query_multiple_quoted_phrases():
    """Test structured query with multiple quoted phrases"""
    from src.models.config import GlobalSettings

    settings = GlobalSettings(
        arxiv_use_structured_query=True,
        arxiv_default_categories=["cs.CL"],
    )
    provider = ArxivProvider(settings=settings)

    query = provider._build_structured_query(
        '"large language models" "in-context learning"'
    )

    # Should have both exact phrase matches
    assert (
        'ti:"large language models"' in query or 'abs:"large language models"' in query
    )
    assert 'ti:"in-context learning"' in query or 'abs:"in-context learning"' in query


@pytest.mark.asyncio
async def test_arxiv_search_bozo_warning(provider, topic_arxiv):
    """Cover bozo warning in search"""
    mock_feed = MagicMock()
    mock_feed.status = 200
    mock_feed.bozo = True
    mock_feed.bozo_exception = Exception("Mock bozo")
    mock_feed.entries = []

    with patch("src.services.providers.arxiv.feedparser.parse", return_value=mock_feed):
        with patch("src.services.providers.arxiv.logger") as mock_logger:
            await provider.search(topic_arxiv)
            mock_logger.warning.assert_any_call(
                "arxiv_feed_parse_warning", error="Mock bozo"
            )
