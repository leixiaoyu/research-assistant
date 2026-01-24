import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from src.services.providers.arxiv import ArxivProvider, APIError, RateLimitError, APIParameterError
from src.models.config import ResearchTopic, TimeframeRecent, TimeframeSinceYear, TimeframeDateRange
from src.models.paper import PaperMetadata
from datetime import date

@pytest.fixture
def provider():
    return ArxivProvider()

@pytest.fixture
def topic_arxiv():
    return ResearchTopic(
        query="machine learning",
        provider="arxiv",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=5
    )

def test_validate_query(provider):
    assert provider.validate_query("valid query") == "valid query"
    assert provider.validate_query("AI AND Robotics") == "AI AND Robotics"
    
    with pytest.raises(ValueError):
        provider.validate_query("test; rm -rf /")
        
    with pytest.raises(ValueError):
        provider.validate_query("$HOME")

def test_build_query_params(provider, topic_arxiv):
    # Recent
    q = provider._build_query_params(topic_arxiv, "machine learning")
    assert "search_query=all%3Amachine%20learning" in q
    assert "submittedDate" in q

    # Since Year
    topic_arxiv.timeframe = TimeframeSinceYear(value=2023)
    q = provider._build_query_params(topic_arxiv, "test")
    assert "submittedDate%3A%5B202301010000%20TO%20300001010000%5D" in q or "submittedDate:[202301010000 TO 300001010000]" in q # Encoded?

    # Date Range
    topic_arxiv.timeframe = TimeframeDateRange(start_date=date(2023,1,1), end_date=date(2023,1,2))
    q = provider._build_query_params(topic_arxiv, "test")
    assert "submittedDate%3A%5B202301010000%20TO%20202301022359%5D" in q

def test_sortorder_parameter(provider, topic_arxiv):
    """Regression test: ArXiv requires 'descending', not 'desc'"""
    q = provider._build_query_params(topic_arxiv, "test")
    # Verify we use full word "descending" not abbreviated "desc"
    assert "sortOrder=descending" in q
    assert "sortOrder=desc" not in q or "sortOrder=descending" in q  # Ensure not just "desc"

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
    
    # Auto-upgrade http
    # Note: _validate_pdf_url returns None, but might raise error.
    # It modifies local variable 'url' inside function scope, doesn't return it.
    # Wait, looking at implementation:
    # if url.startswith("http://"): url = ...
    # if not re.match(...): raise ...
    # So it validates.
    
    # Invalid
    from src.utils.security import SecurityError
    with pytest.raises(SecurityError):
        provider._validate_pdf_url("https://evil.com/malware.pdf")
        
    with pytest.raises(SecurityError):
        provider._validate_pdf_url("https://arxiv.org/pdf/../hack.pdf")
