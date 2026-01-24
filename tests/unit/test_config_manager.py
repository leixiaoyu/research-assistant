import pytest
import os
import yaml
from src.services.config_manager import ConfigManager, ConfigValidationError
from src.models.catalog import Catalog

@pytest.fixture
def valid_config_file(tmp_path):
    config_content = {
        "research_topics": [
            {
                "query": "test query",
                "timeframe": {"type": "recent", "value": "48h"},
                "max_papers": 10
            }
        ],
        "settings": {
            "output_base_dir": str(tmp_path / "output"),
            "enable_duplicate_detection": True,
            "semantic_scholar_api_key": "test_api_key_1234567890"
        }
    }
    config_file = tmp_path / "research_config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_content, f)
    return config_file

def test_load_valid_config(valid_config_file):
    manager = ConfigManager(config_path=str(valid_config_file))
    # Mock cwd to be tmp_path so allowed_bases check passes
    manager.project_root = valid_config_file.parent
    manager.path_sanitizer.allowed_bases.append(valid_config_file.parent)

    config = manager.load_config()
    assert len(config.research_topics) == 1
    assert config.research_topics[0].query == "test query"

def test_load_missing_config():
    manager = ConfigManager(config_path="nonexistent.yaml")
    with pytest.raises(FileNotFoundError):
        manager.load_config()

def test_generate_slug():
    manager = ConfigManager()
    slug = manager.generate_topic_slug("Tree of Thoughts & LLMs")
    # & is removed, spaces to hyphens
    assert slug == "tree-of-thoughts-llms" 
    
    slug2 = manager.generate_topic_slug("  Multiple   Spaces  ")
    assert slug2 == "multiple-spaces"

def test_catalog_operations(valid_config_file, tmp_path):
    manager = ConfigManager(config_path=str(valid_config_file))
    manager.project_root = valid_config_file.parent
    manager.path_sanitizer.allowed_bases.append(valid_config_file.parent)
    
    # Load (should create new)
    catalog = manager.load_catalog()
    assert isinstance(catalog, Catalog)
    assert len(catalog.topics) == 0
    
    # Save
    catalog.get_or_create_topic("test-slug", "test query")
    manager.save_catalog(catalog)
    
    # Verify file exists
    catalog_path = manager.get_catalog_path()
    assert catalog_path.exists()
    
    # Reload
    catalog_reloaded = manager.load_catalog()
    assert "test-slug" in catalog_reloaded.topics
