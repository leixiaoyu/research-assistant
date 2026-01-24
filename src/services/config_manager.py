import os
import yaml
import json
import re
from pathlib import Path
from string import Template
from typing import Optional
from dotenv import load_dotenv
import structlog
from pydantic import ValidationError

from src.models.config import ResearchConfig
from src.models.catalog import Catalog
from src.utils.security import PathSanitizer, SecurityError

logger = structlog.get_logger()


class ConfigValidationError(Exception):
    """Configuration validation failed"""

    pass


class ConfigManager:
    """Manages application configuration and catalog"""

    def __init__(
        self,
        config_path: str = "config/research_config.yaml",
        project_root: Optional[Path] = None,
    ):
        self.config_path = Path(config_path)
        self.env_loaded = False
        self._config: Optional[ResearchConfig] = None

        # Security: whitelist allowed base directories
        self.project_root = project_root or Path.cwd()
        self.path_sanitizer = PathSanitizer(allowed_bases=[self.project_root])

    def load_config(self) -> ResearchConfig:
        """Load and validate configuration"""
        if self._config:
            return self._config

        # 1. Load environment
        if not self.env_loaded:  # pragma: no cover
            load_dotenv()
            self.env_loaded = True

        # 2. Check file existence
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        # 3. Read YAML
        try:
            with open(self.config_path) as f:
                raw_content = f.read()
        except Exception as e:
            raise ConfigValidationError(f"Failed to read config file: {e}")

        # 4. Substitute env vars
        try:
            # Use safe_substitute to allow ${VAR} syntax
            template = Template(raw_content)
            substituted_content = template.safe_substitute(os.environ)
            config_data = yaml.safe_load(substituted_content)
        except Exception as e:
            raise ConfigValidationError(
                f"Failed to parse YAML or substitute variables: {e}"
            )

        # 5. Validate with Pydantic
        try:
            self._config = ResearchConfig(**config_data)
            logger.info("config_loaded", topics=len(self._config.research_topics))
            return self._config
        except ValidationError as e:
            raise ConfigValidationError(f"Invalid configuration: {e}")

    def generate_topic_slug(self, query: str) -> str:
        """Convert query to filesystem-safe slug"""
        slug = query.lower()
        # Remove special characters
        slug = re.sub(r"[^\w\s-]", "", slug)
        # Replace spaces with hyphens
        slug = re.sub(r"[\s_]+", "-", slug)
        # Remove consecutive hyphens
        slug = re.sub(r"-+", "-", slug)
        # Trim hyphens
        slug = slug.strip("-")
        # Limit length
        if len(slug) > 100:
            slug = slug[:100].rstrip("-")
        return slug

    def get_catalog_path(self) -> Path:
        """Get secure path to catalog.json"""
        if not self._config:
            self.load_config()

        assert self._config is not None
        output_base = Path(self._config.settings.output_base_dir)

        # Ensure output directory exists
        if not output_base.exists():
            output_base.mkdir(parents=True, exist_ok=True)

        # Securely resolve catalog path
        try:
            # We treat output_base as the base for the catalog
            sanitizer = PathSanitizer(allowed_bases=[output_base.resolve()])
            return sanitizer.safe_path(output_base, "catalog.json")
        except SecurityError as e:
            raise SecurityError(f"Security violation accessing catalog: {e}")

    def load_catalog(self) -> Catalog:
        """Load existing catalog or create new"""
        catalog_path = self.get_catalog_path()

        if not catalog_path.exists():
            logger.info("catalog_created", path=str(catalog_path))
            return Catalog()

        try:
            with open(catalog_path, "r") as f:
                data = json.load(f)
                return Catalog(**data)
        except Exception as e:
            logger.error("catalog_load_failed", error=str(e))
            return Catalog()

    def save_catalog(self, catalog: Catalog) -> None:
        """Save catalog to disk atomically"""
        catalog_path = self.get_catalog_path()

        # Atomic write: write to .tmp then rename
        temp_path = catalog_path.with_suffix(".tmp")

        try:
            with open(temp_path, "w") as f:
                f.write(catalog.model_dump_json(indent=2))

            temp_path.rename(catalog_path)
            logger.info("catalog_saved", path=str(catalog_path))
        except Exception as e:
            logger.error("catalog_save_failed", error=str(e))
            if temp_path.exists():  # pragma: no cover
                temp_path.unlink()
            raise

    def get_output_path(self, topic_slug: str) -> Path:
        """Determine output directory for topic"""
        if not self._config:
            self.load_config()

        assert self._config is not None
        output_base = Path(self._config.settings.output_base_dir)

        # Security: use sanitizer to ensure slug doesn't escape output dir
        try:
            # Re-init sanitizer with just this base to be specific
            sanitizer = PathSanitizer(allowed_bases=[output_base.resolve()])
            topic_path = sanitizer.safe_path(output_base, topic_slug)

            if not topic_path.exists():
                topic_path.mkdir(parents=True, exist_ok=True)

            return topic_path
        except SecurityError as e:  # pragma: no cover
            raise SecurityError(f"Invalid topic slug '{topic_slug}': {e}")
