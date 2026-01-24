import pytest
from unittest.mock import MagicMock
from src.services.catalog_service import CatalogService
from src.models.catalog import Catalog, TopicCatalogEntry

def test_get_or_create_topic_new():
    mock_config = MagicMock()
    mock_config.load_catalog.return_value = Catalog()
    mock_config.generate_topic_slug.return_value = "new-topic"
    
    service = CatalogService(mock_config)
    topic = service.get_or_create_topic("New Topic")
    
    assert topic.topic_slug == "new-topic"
    assert topic.query == "New Topic"
    assert "new-topic" in service.catalog.topics

def test_get_or_create_topic_duplicate():
    # Setup catalog with existing topic
    existing = TopicCatalogEntry(
        topic_slug="existing-topic",
        query="Machine Learning",
        folder="existing-topic",
        created_at="2023-01-01T00:00:00"
    )
    catalog = Catalog(topics={"existing-topic": existing})
    
    mock_config = MagicMock()
    mock_config.load_catalog.return_value = catalog
    
    service = CatalogService(mock_config)
    
    # Same query, different casing/spacing
    topic = service.get_or_create_topic("machine   learning")
    
    assert topic.topic_slug == "existing-topic" # Should return existing
    assert len(service.catalog.topics) == 1

def test_add_run():
    mock_config = MagicMock()
    catalog = Catalog()
    catalog.get_or_create_topic("test-topic", "Test")
    mock_config.load_catalog.return_value = catalog
    
    service = CatalogService(mock_config)
    service.load()
    
    run = MagicMock()
    service.add_run("test-topic", run)
    
    assert len(service.catalog.topics["test-topic"].runs) == 1
    mock_config.save_catalog.assert_called_once()
