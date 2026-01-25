import pytest
import yaml
from unittest.mock import MagicMock, patch
from src.services.config_manager import ConfigManager, ConfigValidationError
from src.models.catalog import Catalog


@pytest.fixture
def valid_config_file(tmp_path):
    config_content = {
        "research_topics": [
            {
                "query": "test query",
                "timeframe": {"type": "recent", "value": "48h"},
                "max_papers": 10,
            }
        ],
        "settings": {
            "output_base_dir": str(tmp_path / "output"),
            "enable_duplicate_detection": True,
            "semantic_scholar_api_key": "test_api_key_1234567890",
        },
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


def test_load_config_read_error(tmp_path):
    """Cover lines 51-52: Failed to read config file"""
    config_file = tmp_path / "broken.yaml"
    config_file.touch()
    manager = ConfigManager(config_path=str(config_file))
    from unittest.mock import patch, mock_open

    # Mock open to raise exception only for the config file, not .env
    original_open = open

    def selective_open(file, *args, **kwargs):
        if str(config_file) in str(file):
            raise Exception("Read error")
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=selective_open):
        with pytest.raises(ConfigValidationError, match="Failed to read config file"):
            manager.load_config()


def test_load_config_validation_error(tmp_path):
    """Cover lines 69-70: Invalid configuration (ValidationError)"""
    config_file = tmp_path / "invalid.yaml"
    with open(config_file, "w") as f:
        f.write("invalid: data")
    manager = ConfigManager(config_path=str(config_file))
    with pytest.raises(ConfigValidationError, match="Invalid configuration"):
        manager.load_config()


def test_generate_topic_slug_long():
    """Cover line 86: if len(slug) > 100"""
    long_query = "a" * 120
    manager = ConfigManager()
    slug = manager.generate_topic_slug(long_query)
    assert len(slug) == 100


def test_get_catalog_path_security_error():
    """Cover lines 106-108: SecurityError in get_catalog_path"""
    manager = ConfigManager()
    manager._config = MagicMock()
    manager._config.settings.output_base_dir = "/tmp/mock_output"
    from src.utils.security import SecurityError

    with patch("src.services.config_manager.Path.mkdir"):
        with patch(
            "src.services.config_manager.PathSanitizer.safe_path",
            side_effect=SecurityError("Mock security error"),
        ):
            with pytest.raises(
                SecurityError, match="Security violation accessing catalog"
            ):
                manager.get_catalog_path()


def test_load_catalog_corrupted(tmp_path):
    """Cover lines 123-128: catalog_load_failed"""
    catalog_file = tmp_path / "catalog.json"
    with open(catalog_file, "w") as f:
        f.write("not json")
    manager = ConfigManager()
    from unittest.mock import patch

    with patch.object(manager, "get_catalog_path", return_value=catalog_file):
        catalog = manager.load_catalog()
        assert isinstance(catalog, Catalog)
        assert len(catalog.topics) == 0


def test_save_catalog_error(tmp_path):
    """Cover lines 143-147, 152: catalog_save_failed and cleanup"""
    catalog_file = tmp_path / "catalog.json"
    manager = ConfigManager()
    catalog = Catalog()
    # Ensure we use a path that actually exists so open() works but rename() fails
    with patch.object(manager, "get_catalog_path", return_value=catalog_file):
        with patch(
            "src.services.config_manager.Path.rename",
            side_effect=Exception("Rename failed"),
        ):
            # Create the temp file manually to ensure it exists for unlink
            temp_path = catalog_file.with_suffix(".tmp")
            temp_path.touch()
            with pytest.raises(Exception, match="Rename failed"):
                manager.save_catalog(catalog)
            assert not temp_path.exists()


def test_get_output_path_security_error():
    """Cover lines 164-167: SecurityError in get_output_path"""
    manager = ConfigManager()
    manager._config = MagicMock()
    manager._config.settings.output_base_dir = "./output"
    from src.utils.security import SecurityError

    # Use real sanitizer but with a bad slug
    with pytest.raises(SecurityError, match="Invalid topic slug"):
        manager.get_output_path("../outside")


def test_config_manager_project_root():
    """Cover line 36: self.project_root = Path.cwd()"""
    from pathlib import Path

    with patch("src.services.config_manager.Path.cwd") as mock_cwd:
        mock_cwd.return_value = Path("/mock/project/root")
        manager = ConfigManager()
        assert manager.project_root == Path("/mock/project/root")
