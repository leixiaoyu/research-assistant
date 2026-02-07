"""Tests for ResearchPipeline orchestration."""

import pytest
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import tempfile

from src.orchestration.research_pipeline import ResearchPipeline, PipelineResult
from src.services.providers.base import APIError


class TestPipelineResult:
    """Tests for PipelineResult class."""

    def test_init_defaults(self):
        """Should initialize with correct defaults."""
        result = PipelineResult()

        assert result.topics_processed == 0
        assert result.topics_failed == 0
        assert result.papers_discovered == 0
        assert result.papers_processed == 0
        assert result.papers_with_extraction == 0
        assert result.total_tokens_used == 0
        assert result.total_cost_usd == 0.0
        assert result.output_files == []
        assert result.errors == []

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = PipelineResult()
        result.topics_processed = 5
        result.papers_discovered = 20
        result.total_cost_usd = 1.5

        d = result.to_dict()

        assert d["topics_processed"] == 5
        assert d["papers_discovered"] == 20
        assert d["total_cost_usd"] == 1.5
        assert "output_files" in d
        assert "errors" in d


class TestResearchPipeline:
    """Tests for ResearchPipeline class."""

    def test_init_with_defaults(self):
        """Should initialize with default values."""
        pipeline = ResearchPipeline()

        assert pipeline.config_path == Path("config/research_config.yaml")
        assert pipeline.enable_phase2 is True

    def test_init_with_custom_values(self):
        """Should initialize with custom values."""
        custom_path = Path("/custom/config.yaml")
        pipeline = ResearchPipeline(config_path=custom_path, enable_phase2=False)

        assert pipeline.config_path == custom_path
        assert pipeline.enable_phase2 is False

    @pytest.mark.asyncio
    async def test_run_initializes_services(self):
        """Should initialize services on run."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_content = """
research_topics:
  - query: "test query"
    timeframe:
      type: "recent"
      value: "7d"

settings:
  max_papers_per_topic: 10
  output_base_dir: "./output"
  semantic_scholar_api_key: null
"""
            f.write(config_content.encode())
            config_path = Path(f.name)

        try:
            pipeline = ResearchPipeline(config_path=config_path, enable_phase2=False)

            with patch.object(pipeline, "_discovery_service", create=True) as mock_disc:
                mock_disc.search = AsyncMock(return_value=[])

                with patch(
                    "src.services.discovery_service.DiscoveryService"
                ) as mock_ds:
                    mock_ds.return_value.search = AsyncMock(return_value=[])

                    with patch(
                        "src.services.catalog_service.CatalogService"
                    ) as mock_cs:
                        mock_cs.return_value.get_or_create_topic.return_value = Mock(
                            topic_slug="test-query"
                        )

                        result = await pipeline.run()

            assert isinstance(result, PipelineResult)

        finally:
            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_run_handles_initialization_error(self):
        """Should handle errors during initialization."""
        pipeline = ResearchPipeline(
            config_path=Path("/nonexistent/config.yaml"), enable_phase2=False
        )

        result = await pipeline.run()

        assert result.topics_processed == 0
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_run_processes_topics(self):
        """Should process all topics."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_content = """
research_topics:
  - query: "test query 1"
    timeframe:
      type: "recent"
      value: "7d"
  - query: "test query 2"
    timeframe:
      type: "recent"
      value: "7d"

settings:
  max_papers_per_topic: 10
  output_base_dir: "./output"
  semantic_scholar_api_key: null
"""
            f.write(config_content.encode())
            config_path = Path(f.name)

        try:
            pipeline = ResearchPipeline(config_path=config_path, enable_phase2=False)

            with patch("src.services.discovery_service.DiscoveryService") as mock_ds:
                mock_ds.return_value.search = AsyncMock(return_value=[])

                with patch("src.services.catalog_service.CatalogService") as mock_cs:
                    mock_cs.return_value.get_or_create_topic.return_value = Mock(
                        topic_slug="test-query"
                    )

                    result = await pipeline.run()

            # Both topics should be processed (with no papers, so success)
            assert result.topics_processed == 2

        finally:
            Path(f.name).unlink()


class TestResearchPipelineProcessTopic:
    """Tests for _process_topic method."""

    @pytest.mark.asyncio
    async def test_process_topic_no_papers(self):
        """Should handle topic with no papers found."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_content = """
research_topics:
  - query: "test query"
    timeframe:
      type: "recent"
      value: "7d"

settings:
  max_papers_per_topic: 10
  output_base_dir: "./output"
  semantic_scholar_api_key: null
"""
            f.write(config_content.encode())
            config_path = Path(f.name)

        try:
            pipeline = ResearchPipeline(config_path=config_path, enable_phase2=False)

            with patch("src.services.discovery_service.DiscoveryService") as mock_ds:
                mock_ds.return_value.search = AsyncMock(return_value=[])

                with patch("src.services.catalog_service.CatalogService") as mock_cs:
                    mock_cs.return_value.get_or_create_topic.return_value = Mock(
                        topic_slug="test-query"
                    )

                    result = await pipeline.run()

            assert result.topics_processed == 1
            assert result.papers_discovered == 0

        finally:
            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_process_topic_with_papers(self):
        """Should process topic with papers found."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            output_dir = Path(temp_dir) / "output"
            output_dir.mkdir()

            config_content = f"""
research_topics:
  - query: "test query"
    timeframe:
      type: "recent"
      value: "7d"

settings:
  max_papers_per_topic: 10
  output_base_dir: "{output_dir}"
  semantic_scholar_api_key: null
"""
            config_path.write_text(config_content)

            pipeline = ResearchPipeline(config_path=config_path, enable_phase2=False)

            # Create mock paper with proper author objects
            mock_author = Mock()
            mock_author.name = "Author 1"
            mock_paper = Mock()
            mock_paper.title = "Test Paper"
            mock_paper.paper_id = "123"
            mock_paper.doi = None
            mock_paper.abstract = "Abstract"
            mock_paper.authors = [mock_author]
            mock_paper.publication_date = None
            mock_paper.venue = None
            mock_paper.open_access_pdf = None
            mock_paper.citation_count = 0

            with patch("src.services.discovery_service.DiscoveryService") as mock_ds:
                mock_ds.return_value.search = AsyncMock(return_value=[mock_paper])

                with patch("src.services.catalog_service.CatalogService") as mock_cs:
                    mock_cs.return_value.get_or_create_topic.return_value = Mock(
                        topic_slug="test-query"
                    )

                    # Create the output directory structure
                    topic_dir = output_dir / "test-query"
                    topic_dir.mkdir(parents=True, exist_ok=True)

                    with patch.object(
                        pipeline,
                        "_config_manager",
                        create=True,
                    ) as mock_cm:
                        mock_cm.get_output_path.return_value = topic_dir

                        # Initialize services first
                        await pipeline._initialize_services()

                        # Now override the config_manager
                        pipeline._config_manager = mock_cm
                        mock_cm.get_output_path.return_value = topic_dir

                        result = await pipeline.run()

            assert result.topics_processed == 1
            assert result.papers_discovered == 1

    @pytest.mark.asyncio
    async def test_process_topic_api_error(self):
        """Should handle APIError gracefully."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_content = """
research_topics:
  - query: "test query"
    timeframe:
      type: "recent"
      value: "7d"

settings:
  max_papers_per_topic: 10
  output_base_dir: "./output"
  semantic_scholar_api_key: null
"""
            f.write(config_content.encode())
            config_path = Path(f.name)

        try:
            pipeline = ResearchPipeline(config_path=config_path, enable_phase2=False)

            with patch("src.services.discovery_service.DiscoveryService") as mock_ds:
                mock_ds.return_value.search = AsyncMock(
                    side_effect=APIError("API failed")
                )

                with patch("src.services.catalog_service.CatalogService") as mock_cs:
                    mock_cs.return_value.get_or_create_topic.return_value = Mock(
                        topic_slug="test-query"
                    )

                    result = await pipeline.run()

            assert result.topics_failed == 1
            assert len(result.errors) > 0

        finally:
            Path(f.name).unlink()

    @pytest.mark.asyncio
    async def test_process_topic_unexpected_error(self):
        """Should handle unexpected errors gracefully."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_content = """
research_topics:
  - query: "test query"
    timeframe:
      type: "recent"
      value: "7d"

settings:
  max_papers_per_topic: 10
  output_base_dir: "./output"
  semantic_scholar_api_key: null
"""
            f.write(config_content.encode())
            config_path = Path(f.name)

        try:
            pipeline = ResearchPipeline(config_path=config_path, enable_phase2=False)

            with patch("src.services.discovery_service.DiscoveryService") as mock_ds:
                mock_ds.return_value.search = AsyncMock(
                    side_effect=Exception("Unexpected error")
                )

                with patch("src.services.catalog_service.CatalogService") as mock_cs:
                    mock_cs.return_value.get_or_create_topic.return_value = Mock(
                        topic_slug="test-query"
                    )

                    result = await pipeline.run()

            assert result.topics_failed == 1
            assert len(result.errors) > 0

        finally:
            Path(f.name).unlink()


class TestResearchPipelinePhase2:
    """Tests for Phase 2 functionality."""

    @pytest.mark.asyncio
    async def test_phase2_disabled(self):
        """Should skip Phase 2 services when disabled."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            config_content = """
research_topics:
  - query: "test query"
    timeframe:
      type: "recent"
      value: "7d"

settings:
  max_papers_per_topic: 10
  output_base_dir: "./output"
  semantic_scholar_api_key: null
"""
            f.write(config_content.encode())
            config_path = Path(f.name)

        try:
            pipeline = ResearchPipeline(config_path=config_path, enable_phase2=False)

            with patch("src.services.discovery_service.DiscoveryService") as mock_ds:
                mock_ds.return_value.search = AsyncMock(return_value=[])

                with patch("src.services.catalog_service.CatalogService"):
                    await pipeline._initialize_services()

            # Extraction service should not be initialized
            assert pipeline._extraction_service is None

        finally:
            Path(f.name).unlink()


class TestMergeTopicResult:
    """Tests for _merge_topic_result method."""

    def test_merge_success(self):
        """Should merge successful topic result."""
        pipeline = ResearchPipeline()
        result = PipelineResult()

        topic_result = {
            "success": True,
            "papers_discovered": 10,
            "papers_processed": 8,
            "papers_with_extraction": 5,
            "tokens_used": 1000,
            "cost_usd": 0.5,
            "output_file": "/path/to/output.md",
            "error": None,
        }

        pipeline._merge_topic_result(result, topic_result)

        assert result.topics_processed == 1
        assert result.topics_failed == 0
        assert result.papers_discovered == 10
        assert result.papers_processed == 8
        assert result.papers_with_extraction == 5
        assert result.total_tokens_used == 1000
        assert result.total_cost_usd == 0.5
        assert "/path/to/output.md" in result.output_files

    def test_merge_failure(self):
        """Should merge failed topic result."""
        pipeline = ResearchPipeline()
        result = PipelineResult()

        topic_result = {
            "success": False,
            "papers_discovered": 0,
            "papers_processed": 0,
            "papers_with_extraction": 0,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "output_file": None,
            "error": "Search failed",
        }

        pipeline._merge_topic_result(result, topic_result)

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        assert len(result.errors) == 1
        assert result.errors[0]["error"] == "Search failed"

    def test_merge_multiple_results(self):
        """Should accumulate results from multiple topics."""
        pipeline = ResearchPipeline()
        result = PipelineResult()

        topic_result_1 = {
            "success": True,
            "papers_discovered": 10,
            "papers_processed": 8,
            "papers_with_extraction": 5,
            "tokens_used": 1000,
            "cost_usd": 0.5,
            "output_file": "/path/1.md",
            "error": None,
        }

        topic_result_2 = {
            "success": True,
            "papers_discovered": 5,
            "papers_processed": 3,
            "papers_with_extraction": 2,
            "tokens_used": 500,
            "cost_usd": 0.25,
            "output_file": "/path/2.md",
            "error": None,
        }

        pipeline._merge_topic_result(result, topic_result_1)
        pipeline._merge_topic_result(result, topic_result_2)

        assert result.topics_processed == 2
        assert result.papers_discovered == 15
        assert result.papers_processed == 11
        assert result.papers_with_extraction == 7
        assert result.total_tokens_used == 1500
        assert result.total_cost_usd == 0.75
        assert len(result.output_files) == 2
