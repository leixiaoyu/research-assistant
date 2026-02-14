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


class TestRunSynthesis:
    """Tests for _run_synthesis method (Phase 3.6)."""

    @pytest.mark.asyncio
    async def test_run_synthesis_services_not_initialized(self):
        """Should skip synthesis when services are not initialized (Lines 581-583)."""
        pipeline = ResearchPipeline()
        # Services not initialized - _synthesis_engine and _delta_generator are None
        pipeline._synthesis_engine = None
        pipeline._delta_generator = None

        # Should not raise, just log warning and return
        await pipeline._run_synthesis()

        # No errors should occur
        assert pipeline._synthesis_engine is None

    @pytest.mark.asyncio
    async def test_run_synthesis_full_execution(self):
        """Should execute synthesis for all topics (Lines 591-617)."""
        pipeline = ResearchPipeline()

        # Create mock synthesis engine
        mock_stats = Mock()
        mock_stats.total_papers = 5
        mock_stats.average_quality = 0.75
        mock_stats.synthesis_duration_ms = 100

        mock_synthesis_engine = Mock()
        mock_synthesis_engine.synthesize.return_value = mock_stats
        pipeline._synthesis_engine = mock_synthesis_engine

        # Create mock delta generator
        mock_delta_generator = Mock()
        mock_delta_generator.generate.return_value = Path("/output/topic/delta.md")
        pipeline._delta_generator = mock_delta_generator

        # Add processing results for a topic
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        pipeline._topic_processing_results = {
            "test-topic": [
                ProcessingResult(
                    paper_id="paper1",
                    title="Test Paper",
                    status=ProcessingStatus.NEW,
                    topic_slug="test-topic",
                )
            ]
        }

        await pipeline._run_synthesis()

        # Verify delta generator was called
        mock_delta_generator.generate.assert_called_once()
        # Verify synthesis engine was called
        mock_synthesis_engine.synthesize.assert_called_once_with("test-topic")

    @pytest.mark.asyncio
    async def test_run_synthesis_handles_exception(self):
        """Should handle synthesis exceptions gracefully (Lines 616-622)."""
        pipeline = ResearchPipeline()

        # Create mock that raises exception
        mock_synthesis_engine = Mock()
        mock_synthesis_engine.synthesize.side_effect = Exception("Synthesis failed")
        pipeline._synthesis_engine = mock_synthesis_engine

        mock_delta_generator = Mock()
        mock_delta_generator.generate.return_value = None
        pipeline._delta_generator = mock_delta_generator

        from src.models.synthesis import ProcessingResult, ProcessingStatus

        pipeline._topic_processing_results = {
            "failing-topic": [
                ProcessingResult(
                    paper_id="paper1",
                    title="Test Paper",
                    status=ProcessingStatus.NEW,
                    topic_slug="failing-topic",
                )
            ]
        }

        # Should not raise, exception is caught and logged
        await pipeline._run_synthesis()

    @pytest.mark.asyncio
    async def test_run_synthesis_delta_path_none(self):
        """Should handle when delta generator returns None."""
        pipeline = ResearchPipeline()

        mock_stats = Mock()
        mock_stats.total_papers = 3
        mock_stats.average_quality = 0.5
        mock_stats.synthesis_duration_ms = 50

        mock_synthesis_engine = Mock()
        mock_synthesis_engine.synthesize.return_value = mock_stats
        pipeline._synthesis_engine = mock_synthesis_engine

        # Delta generator returns None (no delta generated)
        mock_delta_generator = Mock()
        mock_delta_generator.generate.return_value = None
        pipeline._delta_generator = mock_delta_generator

        from src.models.synthesis import ProcessingResult, ProcessingStatus

        pipeline._topic_processing_results = {
            "topic-no-delta": [
                ProcessingResult(
                    paper_id="paper1",
                    title="Test Paper",
                    status=ProcessingStatus.NEW,
                    topic_slug="topic-no-delta",
                )
            ]
        }

        await pipeline._run_synthesis()

        # Should still call synthesize even if no delta
        mock_synthesis_engine.synthesize.assert_called_once()


class TestGetProcessingResults:
    """Tests for _get_processing_results method."""

    def test_with_extracted_papers(self):
        """Should create results from extracted papers (Lines 647-666)."""
        pipeline = ResearchPipeline()

        # Create mock extracted papers
        mock_extraction = Mock()
        mock_extraction.quality_score = 0.85

        mock_metadata = Mock()
        mock_metadata.paper_id = "paper123"
        mock_metadata.title = "Test Paper Title"

        mock_extracted_paper = Mock()
        mock_extracted_paper.metadata = mock_metadata
        mock_extracted_paper.extraction = mock_extraction
        mock_extracted_paper.pdf_available = True

        extracted_papers = [mock_extracted_paper]
        papers = []  # Not used when extracted_papers is provided

        results = pipeline._get_processing_results(
            papers=papers,
            topic_slug="test-topic",
            extracted_papers=extracted_papers,
        )

        assert len(results) == 1
        assert results[0].paper_id == "paper123"
        assert results[0].title == "Test Paper Title"
        assert results[0].quality_score == 0.85
        assert results[0].pdf_available is True
        assert results[0].extraction_success is True
        assert results[0].topic_slug == "test-topic"

    def test_with_extracted_papers_no_extraction(self):
        """Should handle extracted papers without extraction result."""
        pipeline = ResearchPipeline()

        mock_metadata = Mock()
        mock_metadata.paper_id = "paper456"
        mock_metadata.title = "Paper Without Extraction"

        mock_extracted_paper = Mock()
        mock_extracted_paper.metadata = mock_metadata
        mock_extracted_paper.extraction = None  # No extraction
        mock_extracted_paper.pdf_available = False

        extracted_papers = [mock_extracted_paper]

        results = pipeline._get_processing_results(
            papers=[],
            topic_slug="test-topic",
            extracted_papers=extracted_papers,
        )

        assert len(results) == 1
        assert results[0].quality_score == 0.0  # Default when no extraction
        assert results[0].extraction_success is False

    def test_without_extracted_papers(self):
        """Should create results from papers in Phase 1 mode (Lines 667-677)."""
        pipeline = ResearchPipeline()

        # Create mock papers (PaperMetadata)
        mock_paper1 = Mock()
        mock_paper1.paper_id = "paper1"
        mock_paper1.title = "First Paper"

        mock_paper2 = Mock()
        mock_paper2.paper_id = "paper2"
        mock_paper2.title = None  # Test Untitled fallback

        papers = [mock_paper1, mock_paper2]

        results = pipeline._get_processing_results(
            papers=papers,
            topic_slug="phase1-topic",
            extracted_papers=None,  # Phase 1 mode
        )

        assert len(results) == 2
        assert results[0].paper_id == "paper1"
        assert results[0].title == "First Paper"
        assert results[0].topic_slug == "phase1-topic"
        assert results[1].paper_id == "paper2"
        assert results[1].title == "Untitled"  # Fallback for None title

    def test_empty_papers_list(self):
        """Should return empty list when no papers provided."""
        pipeline = ResearchPipeline()

        results = pipeline._get_processing_results(
            papers=[],
            topic_slug="empty-topic",
            extracted_papers=None,
        )

        assert results == []


class TestProcessTopicWithSynthesis:
    """Tests for _process_topic with synthesis enabled (Lines 376-385)."""

    @pytest.mark.asyncio
    async def test_process_topic_stores_synthesis_results(self):
        """Should store processing results when synthesis enabled (Lines 378-383)."""
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

            # Create pipeline with synthesis enabled
            pipeline = ResearchPipeline(
                config_path=config_path,
                enable_phase2=False,
                enable_synthesis=True,
            )

            # Create mock paper
            mock_paper = Mock()
            mock_paper.title = "Test Paper"
            mock_paper.paper_id = "123"
            mock_paper.doi = None
            mock_paper.abstract = "Abstract"
            mock_paper.authors = []
            mock_paper.publication_date = None
            mock_paper.venue = None
            mock_paper.open_access_pdf = None
            mock_paper.citation_count = 0

            with patch("src.services.discovery_service.DiscoveryService") as mock_ds:
                mock_ds.return_value.search = AsyncMock(return_value=[mock_paper])

                with patch("src.services.catalog_service.CatalogService") as mock_cs:
                    mock_catalog_topic = Mock(topic_slug="test-query")
                    mock_cs.return_value.get_or_create_topic.return_value = (
                        mock_catalog_topic
                    )
                    mock_cs.return_value.add_run = Mock()

                    # Initialize services
                    await pipeline._initialize_services()

                    # Mock the extraction service to trigger lines 376-385
                    pipeline._extraction_service = Mock()

                    # Create output directory
                    topic_dir = output_dir / "test-query"
                    topic_dir.mkdir(parents=True, exist_ok=True)

                    with patch.object(
                        pipeline._config_manager,
                        "get_output_path",
                        return_value=topic_dir,
                    ):
                        # Process the topic
                        from src.models.config import ResearchTopic, TimeframeRecent

                        topic = ResearchTopic(
                            query="test query",
                            timeframe=TimeframeRecent(type="recent", value="7d"),
                        )
                        result = await pipeline._process_topic(topic)

            # Verify synthesis results were stored
            assert result["success"] is True
            assert "test-query" in pipeline._topic_processing_results
            assert len(pipeline._topic_processing_results["test-query"]) == 1


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

    def test_merge_failure_missing_error_key(self):
        """Should handle failure when error key is missing (no KeyError)."""
        pipeline = ResearchPipeline()
        result = PipelineResult()

        # Topic result without 'error' key - should not raise KeyError
        topic_result = {
            "success": False,
            "papers_discovered": 0,
            "papers_processed": 0,
            "papers_with_extraction": 0,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "output_file": None,
            # Note: 'error' key intentionally missing
        }

        pipeline._merge_topic_result(result, topic_result)

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        assert len(result.errors) == 1
        assert result.errors[0]["error"] == "Unknown error"

    def test_merge_failure_empty_error(self):
        """Should not add error entry when error is empty string."""
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
            "error": "",  # Empty error string
        }

        pipeline._merge_topic_result(result, topic_result)

        assert result.topics_failed == 1
        # Empty string is falsy, so no error should be added
        assert len(result.errors) == 0
