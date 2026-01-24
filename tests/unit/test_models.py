import pytest
from datetime import date, datetime
from pydantic import ValidationError
from src.models.config import (
    ResearchTopic,
    TimeframeRecent,
    TimeframeDateRange,
)
from src.models.paper import PaperMetadata
from src.models.catalog import Catalog


def test_timeframe_recent_validation():
    # Valid
    t = TimeframeRecent(value="48h")
    assert t.value == "48h"

    # Valid
    t = TimeframeRecent(value="7d")
    assert t.value == "7d"

    # Invalid format
    with pytest.raises(ValidationError):
        TimeframeRecent(value="48")  # type: ignore

    # Invalid value (too high hours)
    with pytest.raises(ValidationError):
        TimeframeRecent(value="1000h")

    # Invalid value (too high days)
    with pytest.raises(ValidationError):
        TimeframeRecent(value="400d")


def test_timeframe_date_range_validation():
    # Valid
    t = TimeframeDateRange(start_date=date(2023, 1, 1), end_date=date(2023, 1, 31))
    assert t.end_date == date(2023, 1, 31)

    # Invalid (end before start)
    with pytest.raises(ValidationError):
        TimeframeDateRange(start_date=date(2023, 1, 31), end_date=date(2023, 1, 1))


def test_research_topic_validation():
    # Valid
    topic = ResearchTopic(
        query="machine learning", timeframe=TimeframeRecent(value="48h"), max_papers=10
    )
    assert topic.query == "machine learning"

    # Empty query
    with pytest.raises(ValidationError):
        ResearchTopic(
            query="   ", timeframe=TimeframeRecent(value="48h")  # type: ignore
        )

    # Injection attempt
    with pytest.raises(ValidationError):
        ResearchTopic(
            query="test; rm -rf /",
            timeframe=TimeframeRecent(value="48h"),  # type: ignore
        )


def test_paper_metadata():
    # Valid
    paper = PaperMetadata(
        paper_id="123",
        title="Test Paper",
        url="https://example.com/paper",  # type: ignore
        year=2023,
    )
    assert paper.year == 2023

    # Invalid year
    with pytest.raises(ValidationError):
        PaperMetadata(
            paper_id="123",
            title="Test",
            url="https://example.com",  # type: ignore
            year=1800,
        )


def test_catalog_logic():
    catalog = Catalog()
    topic = catalog.get_or_create_topic("test-topic", "Test Query")

    assert topic.topic_slug == "test-topic"
    assert "test-topic" in catalog.topics

    # Get existing
    topic2 = catalog.get_or_create_topic("test-topic", "Changed Query")
    assert topic2 is topic


def test_catalog_has_paper():
    from src.models.catalog import ProcessedPaper

    catalog = Catalog()
    topic = catalog.get_or_create_topic("test-topic", "Test Query")

    # Setup processed paper
    paper = ProcessedPaper(
        paper_id="p1",
        doi="10.1234/test",
        title="Test Paper",
        processed_at=datetime.utcnow(),
        run_id="run1",
    )
    topic.processed_papers.append(paper)

    # Check by ID
    assert topic.has_paper(paper_id="p1") is True
    assert topic.has_paper(paper_id="p2") is False

    # Check by DOI
    assert topic.has_paper(paper_id="other", doi="10.1234/test") is True
    assert topic.has_paper(paper_id="other", doi="10.1234/other") is False
