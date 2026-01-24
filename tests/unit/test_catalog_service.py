import pytest
from unittest.mock import MagicMock
from datetime import datetime
from src.services.catalog_service import CatalogService
from src.models.catalog import Catalog, TopicCatalogEntry


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
        created_at=datetime.utcnow()
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
        created_at=datetime.utcnow()
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
        paper_id="p1", doi="d1", title="T",
        processed_at=datetime.utcnow(), run_id="r1"
    )
    topic = TopicCatalogEntry(
        topic_slug="t1", query="Q", folder="t1", created_at=datetime.utcnow(),
        processed_papers=[paper]
    )
    catalog = Catalog(topics={"t1": topic})
    mock_config.load_catalog.return_value = catalog

    service = CatalogService(mock_config)
    assert service.is_paper_processed("t1", "p1", "d1") is True
    assert service.is_paper_processed("t1", "p2", "d2") is False
    # Test with paper_id match but doi mismatch (still True)
    assert service.is_paper_processed("t1", "p1", "other-doi") is True


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