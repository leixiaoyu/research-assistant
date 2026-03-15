import pytest
from unittest.mock import MagicMock
from datetime import datetime
import hashlib
from src.services.catalog_service import CatalogService
from src.models.catalog import Catalog, TopicCatalogEntry
from src.models.config import ResearchTopic, TimeframeRecent


@pytest.fixture
def mock_config():
    return MagicMock()


def test_get_or_create_topic_new(mock_config):
    mock_config.load_catalog.return_value = Catalog()
    mock_config.generate_topic_slug.return_value = "new-topic"

    service = CatalogService(mock_config)
    topic = service.get_or_create_topic("New Topic")

    assert topic.topic_slug == "new-topic"
    assert topic.query == "New Topic"
    assert "new-topic" in service.catalog.topics


def test_get_or_create_topic_duplicate(mock_config):
    # Setup catalog with existing topic
    existing = TopicCatalogEntry(
        topic_slug="existing-topic",
        query="Machine Learning",
        folder="existing-topic",
        created_at=datetime.utcnow(),
    )
    catalog = Catalog(topics={"existing-topic": existing})

    mock_config.load_catalog.return_value = catalog
    # Mock slug generation to return something that DOES NOT match existing-topic
    # to test the query-based fallback
    mock_config.generate_topic_slug.return_value = "machine-learning"

    service = CatalogService(mock_config)

    # Same query, different casing/spacing
    topic = service.get_or_create_topic("Machine   Learning")
    assert topic.topic_slug == "existing-topic"
    assert topic.query == "Machine Learning"


def test_get_or_create_topic_slug_collision(mock_config):
    # Setup catalog with existing topic
    existing = TopicCatalogEntry(
        topic_slug="machine-learning",
        query="Machine Learning",
        folder="machine-learning",
        created_at=datetime.utcnow(),
    )
    catalog = Catalog(topics={"machine-learning": existing})

    mock_config.load_catalog.return_value = catalog
    # New query but results in SAME slug
    mock_config.generate_topic_slug.return_value = "machine-learning"

    service = CatalogService(mock_config)

    topic = service.get_or_create_topic("Different Query Same Slug")
    assert topic.topic_slug == "machine-learning-1"
    assert topic.query == "Different Query Same Slug"
    assert len(service.catalog.topics) == 2


def test_is_paper_processed(mock_config):
    # Setup catalog with processed paper
    from src.models.catalog import ProcessedPaper

    paper = ProcessedPaper(
        paper_id="p1", doi="d1", title="T", processed_at=datetime.utcnow(), run_id="r1"
    )
    topic = TopicCatalogEntry(
        topic_slug="t1",
        query="Q",
        folder="t1",
        created_at=datetime.utcnow(),
        processed_papers=[paper],
    )
    catalog = Catalog(topics={"t1": topic})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    assert service.is_paper_processed("t1", "p1", "d1") is True
    assert service.is_paper_processed("t1", "p2", "d2") is False
    # Test with paper_id match but doi mismatch (still True)
    assert service.is_paper_processed("t1", "p1", "other-doi") is True
    # Test DOI-only match (different paper_id but same DOI)
    assert service.is_paper_processed("t1", "different_id", "d1") is True


def test_is_paper_processed_missing_topic(mock_config):
    mock_config.load_catalog.return_value = Catalog()
    service = CatalogService(mock_config)
    assert service.is_paper_processed("missing", "p1") is False


def test_add_run(mock_config):
    catalog = Catalog()
    catalog.get_or_create_topic("test-topic", "Test")
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    service.load()

    run = MagicMock()
    service.add_run("test-topic", run)

    assert len(service.catalog.topics["test-topic"].runs) == 1
    mock_config.save_catalog.assert_called_once()


def test_add_run_missing_topic(mock_config):
    """Test add_run raises error for non-existent topic"""
    mock_config.load_catalog.return_value = Catalog()

    service = CatalogService(mock_config)
    run = MagicMock()

    with pytest.raises(ValueError, match="Topic not found: missing-topic"):
        service.add_run("missing-topic", run)


# Phase 7.1: Discovery Foundation Tests


def test_get_last_discovery_at_existing(mock_config):
    """Test retrieving last discovery timestamp for existing topic"""
    timestamp = datetime(2025, 1, 15, 10, 30, 0)
    topic = TopicCatalogEntry(
        topic_slug="test-topic",
        query="Test Query",
        folder="test-topic",
        created_at=datetime.utcnow(),
        last_successful_discovery_at=timestamp,
    )
    catalog = Catalog(topics={"test-topic": topic})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    result = service.get_last_discovery_at("test-topic")

    assert result == timestamp


def test_get_last_discovery_at_not_set(mock_config):
    """Test retrieving last discovery timestamp when not set"""
    topic = TopicCatalogEntry(
        topic_slug="test-topic",
        query="Test Query",
        folder="test-topic",
        created_at=datetime.utcnow(),
        last_successful_discovery_at=None,
    )
    catalog = Catalog(topics={"test-topic": topic})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    result = service.get_last_discovery_at("test-topic")

    assert result is None


def test_get_last_discovery_at_missing_topic(mock_config):
    """Test retrieving last discovery timestamp for non-existent topic"""
    mock_config.load_catalog.return_value = Catalog()

    service = CatalogService(mock_config)
    result = service.get_last_discovery_at("missing-topic")

    assert result is None


def test_set_last_discovery_at_existing_topic(mock_config):
    """Test setting last discovery timestamp for existing topic"""
    topic = TopicCatalogEntry(
        topic_slug="test-topic",
        query="Test Query",
        folder="test-topic",
        created_at=datetime.utcnow(),
    )
    catalog = Catalog(topics={"test-topic": topic})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    timestamp = datetime(2025, 1, 15, 12, 0, 0)
    service.set_last_discovery_at("test-topic", timestamp)

    assert (
        service.catalog.topics["test-topic"].last_successful_discovery_at == timestamp
    )
    mock_config.save_catalog.assert_called_once()


def test_set_last_discovery_at_new_topic(mock_config):
    """Test setting last discovery timestamp creates topic if missing"""
    mock_config.load_catalog.return_value = Catalog()

    service = CatalogService(mock_config)
    timestamp = datetime(2025, 1, 15, 12, 0, 0)
    service.set_last_discovery_at("new-topic", timestamp)

    assert "new-topic" in service.catalog.topics
    assert service.catalog.topics["new-topic"].last_successful_discovery_at == timestamp
    assert service.catalog.topics["new-topic"].topic_slug == "new-topic"
    mock_config.save_catalog.assert_called_once()


def test_detect_query_change_no_previous_hash(mock_config):
    """Test query change detection when no previous hash exists"""
    topic_entry = TopicCatalogEntry(
        topic_slug="test-topic",
        query="Original Query",
        folder="test-topic",
        created_at=datetime.utcnow(),
        query_hash=None,
    )
    catalog = Catalog(topics={"test-topic": topic_entry})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    research_topic = ResearchTopic(
        query="Original Query",
        timeframe=TimeframeRecent(type="recent", value="48h"),
    )

    changed = service.detect_query_change(research_topic, "test-topic")

    assert changed is False  # First time tracking, not a "change"
    # Hash should be stored
    expected_hash = hashlib.sha256("Original Query".encode("utf-8")).hexdigest()
    assert service.catalog.topics["test-topic"].query_hash == expected_hash
    mock_config.save_catalog.assert_called_once()


def test_detect_query_change_query_unchanged(mock_config):
    """Test query change detection when query hasn't changed"""
    query = "Test Query"
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
    topic_entry = TopicCatalogEntry(
        topic_slug="test-topic",
        query=query,
        folder="test-topic",
        created_at=datetime.utcnow(),
        query_hash=query_hash,
    )
    catalog = Catalog(topics={"test-topic": topic_entry})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    research_topic = ResearchTopic(
        query=query,
        timeframe=TimeframeRecent(type="recent", value="48h"),
    )

    changed = service.detect_query_change(research_topic, "test-topic")

    assert changed is False
    assert service.catalog.topics["test-topic"].query_hash == query_hash


def test_detect_query_change_query_changed(mock_config):
    """Test query change detection when query has changed"""
    old_query = "Old Query"
    old_hash = hashlib.sha256(old_query.encode("utf-8")).hexdigest()
    topic_entry = TopicCatalogEntry(
        topic_slug="test-topic",
        query=old_query,
        folder="test-topic",
        created_at=datetime.utcnow(),
        query_hash=old_hash,
    )
    catalog = Catalog(topics={"test-topic": topic_entry})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    new_query = "New Query"
    research_topic = ResearchTopic(
        query=new_query,
        timeframe=TimeframeRecent(type="recent", value="48h"),
    )

    changed = service.detect_query_change(research_topic, "test-topic")

    assert changed is True
    # Hash and query should be updated
    new_hash = hashlib.sha256(new_query.encode("utf-8")).hexdigest()
    assert service.catalog.topics["test-topic"].query_hash == new_hash
    assert service.catalog.topics["test-topic"].query == new_query
    mock_config.save_catalog.assert_called_once()


def test_detect_query_change_missing_topic(mock_config):
    """Test query change detection for non-existent topic"""
    mock_config.load_catalog.return_value = Catalog()

    service = CatalogService(mock_config)
    research_topic = ResearchTopic(
        query="Test Query",
        timeframe=TimeframeRecent(type="recent", value="48h"),
    )

    changed = service.detect_query_change(research_topic, "missing-topic")

    assert changed is False  # No previous query to compare


def test_backward_compatibility_existing_catalog(mock_config):
    """Test that existing catalog entries without new fields load correctly"""
    # Simulate old catalog entry without Phase 7.1 fields
    topic = TopicCatalogEntry(
        topic_slug="old-topic",
        query="Old Query",
        folder="old-topic",
        created_at=datetime.utcnow(),
    )
    # Explicitly verify new fields have default values
    assert topic.last_successful_discovery_at is None
    assert topic.query_hash is None

    catalog = Catalog(topics={"old-topic": topic})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    service.load()

    # Should load without errors
    assert "old-topic" in service.catalog.topics
    assert service.catalog.topics["old-topic"].last_successful_discovery_at is None
    assert service.catalog.topics["old-topic"].query_hash is None
