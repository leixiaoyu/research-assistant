"""Tests for ResearchPipeline orchestration.

Phase 5.2: Updated to test new modular phase-based architecture.
Tests now import from src.orchestration directly and test the new
PipelineContext and phase classes where appropriate.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, AsyncMock, patch
import tempfile

# Import from new location (not deprecated stub)
from src.orchestration import ResearchPipeline, PipelineResult, PipelineContext
from src.orchestration.phases import SynthesisPhase, CrossSynthesisPhase
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

    def test_to_dict_with_cross_synthesis_report(self):
        """Should include cross_synthesis info when report is present (Line 75)."""
        result = PipelineResult()
        result.topics_processed = 3
        result.papers_discovered = 15

        # Create mock cross-synthesis report
        mock_report = Mock()
        mock_report.questions_answered = 5
        mock_report.total_cost_usd = 0.25
        mock_report.total_tokens_used = 5000
        result.cross_synthesis_report = mock_report

        d = result.to_dict()

        assert "cross_synthesis" in d
        assert d["cross_synthesis"]["questions_answered"] == 5
        assert d["cross_synthesis"]["synthesis_cost_usd"] == 0.25
        assert d["cross_synthesis"]["synthesis_tokens"] == 5000


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
        """Should initialize services on run.

        Phase 5.2: Updated to patch services at the module level since
        the new architecture uses a context object for service management.
        """
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
        """Should process topic with papers found.

        Phase 5.2: Updated to work with new context-based architecture.
        """
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

                    with patch(
                        "src.services.config_manager.ConfigManager"
                    ) as mock_cm_class:
                        mock_cm = MagicMock()
                        mock_cm.get_output_path.return_value = topic_dir
                        mock_cm_class.return_value = mock_cm
                        # Load config should return proper config
                        mock_cm.load_config.return_value = MagicMock(
                            research_topics=[
                                MagicMock(
                                    query="test query",
                                    extraction_targets=None,
                                    timeframe=MagicMock(value="7d"),
                                )
                            ],
                            settings=MagicMock(
                                output_base_dir=str(output_dir),
                                semantic_scholar_api_key=None,
                                pdf_settings=None,
                                llm_settings=None,
                                cost_limits=None,
                                concurrency=None,
                            ),
                        )

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
        """Should skip Phase 2 services when disabled.

        Phase 5.2: Updated to test via running the pipeline, as context
        creation is internal to run().
        """
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
                    await pipeline.run()

            # Extraction service should not be initialized when Phase 2 is disabled
            assert pipeline._extraction_service is None

        finally:
            Path(f.name).unlink()


class TestRunSynthesis:
    """Tests for SynthesisPhase (Phase 3.6).

    Phase 5.2: Updated to test SynthesisPhase directly with PipelineContext,
    as the new architecture uses phase objects instead of internal methods.
    """

    @pytest.mark.asyncio
    async def test_run_synthesis_services_not_initialized(self):
        """Should skip synthesis when services are not initialized."""
        from src.models.config import ResearchConfig

        # Create context without synthesis services
        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=True,
        )
        # synthesis_engine and delta_generator are None by default

        phase = SynthesisPhase(context)
        result = await phase.run()

        # Should complete with no topics processed
        assert result.topics_processed == 0
        assert result.topics_failed == 0

    @pytest.mark.asyncio
    async def test_run_synthesis_full_execution(self):
        """Should execute synthesis for all topics."""
        from src.models.config import ResearchConfig
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=True,
        )

        # Set up synthesis services
        mock_stats = MagicMock()
        mock_stats.total_papers = 5
        mock_stats.average_quality = 0.75
        mock_stats.synthesis_duration_ms = 100

        context.synthesis_engine = MagicMock()
        context.synthesis_engine.synthesize.return_value = mock_stats

        context.delta_generator = MagicMock()
        context.delta_generator.generate.return_value = Path("/output/topic/delta.md")

        # Add processing results
        context.add_processing_results(
            "test-topic",
            [
                ProcessingResult(
                    paper_id="paper1",
                    title="Test Paper",
                    status=ProcessingStatus.NEW,
                    topic_slug="test-topic",
                )
            ],
        )

        phase = SynthesisPhase(context)
        result = await phase.run()

        # Verify synthesis was called
        context.synthesis_engine.synthesize.assert_called_once_with("test-topic")
        assert result.topics_processed == 1

    @pytest.mark.asyncio
    async def test_run_synthesis_handles_exception(self):
        """Should handle synthesis exceptions gracefully."""
        from src.models.config import ResearchConfig
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=True,
        )

        context.synthesis_engine = MagicMock()
        context.synthesis_engine.synthesize.side_effect = Exception("Synthesis failed")
        context.delta_generator = MagicMock()
        context.delta_generator.generate.return_value = None

        context.add_processing_results(
            "failing-topic",
            [
                ProcessingResult(
                    paper_id="paper1",
                    title="Test Paper",
                    status=ProcessingStatus.NEW,
                    topic_slug="failing-topic",
                )
            ],
        )

        phase = SynthesisPhase(context)
        result = await phase.run()

        # Exception caught, topic marked as failed
        assert result.topics_failed == 1

    @pytest.mark.asyncio
    async def test_run_synthesis_delta_path_none(self):
        """Should handle when delta generator returns None."""
        from src.models.config import ResearchConfig
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=True,
        )

        mock_stats = MagicMock()
        mock_stats.total_papers = 3
        mock_stats.average_quality = 0.5
        mock_stats.synthesis_duration_ms = 50

        context.synthesis_engine = MagicMock()
        context.synthesis_engine.synthesize.return_value = mock_stats
        context.delta_generator = MagicMock()
        context.delta_generator.generate.return_value = None

        context.add_processing_results(
            "topic-no-delta",
            [
                ProcessingResult(
                    paper_id="paper1",
                    title="Test Paper",
                    status=ProcessingStatus.NEW,
                    topic_slug="topic-no-delta",
                )
            ],
        )

        phase = SynthesisPhase(context)
        result = await phase.run()

        # Should still call synthesize even if no delta
        context.synthesis_engine.synthesize.assert_called_once()
        assert result.topics_processed == 1


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
    """Tests for ExtractionPhase with synthesis enabled.

    Phase 5.2: Updated to test ExtractionPhase directly with PipelineContext,
    as the new architecture uses phase objects for topic processing.
    """

    @pytest.mark.asyncio
    async def test_extraction_phase_stores_synthesis_results(self):
        """Should store processing results in context when synthesis enabled."""
        from src.models.config import ResearchConfig, ResearchTopic, TimeframeRecent
        from src.orchestration.phases import ExtractionPhase

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "output"
            topic_dir = output_dir / "test-query"
            topic_dir.mkdir(parents=True)

            # Create mock topic
            mock_topic = MagicMock(spec=ResearchTopic)
            mock_topic.query = "test query"
            mock_topic.extraction_targets = None
            mock_topic.timeframe = TimeframeRecent(type="recent", value="7d")

            # Create mock config
            mock_config = MagicMock(spec=ResearchConfig)
            mock_config.research_topics = [mock_topic]

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

            # Create mock catalog topic
            mock_catalog_topic = Mock(topic_slug="test-query")

            # Create mock services
            mock_catalog_service = MagicMock()
            mock_catalog_service.get_or_create_topic.return_value = mock_catalog_topic
            mock_catalog_service.add_run = Mock()

            mock_config_manager = MagicMock()
            mock_config_manager.get_output_path.return_value = topic_dir

            mock_md_generator = MagicMock()
            mock_md_generator.generate.return_value = "# Test Report"

            # Create context with synthesis enabled
            context = PipelineContext(
                config=mock_config,
                config_path=Path("test.yaml"),
                config_manager=mock_config_manager,
                discovery_service=MagicMock(),
                catalog_service=mock_catalog_service,
                registry_service=MagicMock(),
                enable_phase2=False,
                enable_synthesis=True,
            )

            # Add discovered papers to context
            context.discovered_papers["test-query"] = [mock_paper]
            context.md_generator = mock_md_generator

            # Run extraction phase
            phase = ExtractionPhase(context)
            result = await phase.run()

            # Verify processing results were stored in context
            assert result.topics_processed == 1
            assert "test-query" in context.topic_processing_results
            assert len(context.topic_processing_results["test-query"]) == 1


class TestMergeTopicResult:
    """Tests for PipelineResult.merge_topic_result method.

    Phase 5.2: Updated to test PipelineResult.merge_topic_result directly,
    as the method has been moved from ResearchPipeline to PipelineResult.
    """

    def test_merge_success(self):
        """Should merge successful topic result."""
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

        result.merge_topic_result(topic_result)

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
        result = PipelineResult()

        topic_result = {
            "success": False,
            "topic": "test-topic",
            "papers_discovered": 0,
            "papers_processed": 0,
            "papers_with_extraction": 0,
            "tokens_used": 0,
            "cost_usd": 0.0,
            "output_file": None,
            "error": "Search failed",
        }

        result.merge_topic_result(topic_result)

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        assert len(result.errors) == 1
        assert result.errors[0]["error"] == "Search failed"

    def test_merge_multiple_results(self):
        """Should accumulate results from multiple topics."""
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

        result.merge_topic_result(topic_result_1)
        result.merge_topic_result(topic_result_2)

        assert result.topics_processed == 2
        assert result.papers_discovered == 15
        assert result.papers_processed == 11
        assert result.papers_with_extraction == 7
        assert result.total_tokens_used == 1500
        assert result.total_cost_usd == 0.75
        assert len(result.output_files) == 2

    def test_merge_failure_missing_error_key(self):
        """Should handle failure when error key is missing."""
        result = PipelineResult()

        # Topic result without 'error' key - should handle gracefully
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

        result.merge_topic_result(topic_result)

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        # No error message means no error added
        assert len(result.errors) == 0

    def test_merge_failure_empty_error(self):
        """Should not add error entry when error is empty string."""
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

        result.merge_topic_result(topic_result)

        assert result.topics_failed == 1
        # Empty string is falsy, so no error should be added
        assert len(result.errors) == 0


class TestResearchPipelinePhase38:
    """Tests for Phase 3.8 registry integration.

    Phase 5.2: Updated to use new modular architecture paths.
    """

    def test_extraction_service_initialized_with_registry(self):
        """Verify ExtractionService accepts registry_service parameter."""
        from src.services.extraction_service import ExtractionService
        import inspect

        # Check constructor signature includes registry_service
        sig = inspect.signature(ExtractionService.__init__)
        params = list(sig.parameters.keys())
        assert "registry_service" in params

    def test_pipeline_passes_registry_to_extraction(self):
        """Verify pipeline.py _initialize_phase2_services passes registry."""
        import ast

        # Read the source file to check that registry_service is passed
        # Phase 5.2: Now reads from pipeline.py (not deprecated research_pipeline.py)
        source_file = Path("src/orchestration/pipeline.py")
        source_code = source_file.read_text()

        # Parse the AST to find the ExtractionService call
        tree = ast.parse(source_code)

        found_registry_arg = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Look for ExtractionService(...) call
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "ExtractionService"
                ):
                    for keyword in node.keywords:
                        if keyword.arg == "registry_service":
                            found_registry_arg = True
                            break

        assert found_registry_arg, (
            "ExtractionService call in pipeline.py should include "
            "registry_service parameter"
        )

    def test_extraction_phase_run_extraction_accepts_topic_slug(self):
        """Verify ExtractionPhase._run_extraction signature accepts topic_slug."""
        import inspect
        from src.orchestration.phases import ExtractionPhase

        # Phase 5.2: Now tests ExtractionPhase instead of ResearchPipeline
        sig = inspect.signature(ExtractionPhase._run_extraction)
        params = list(sig.parameters.keys())

        # Should have topic_slug parameter
        assert "topic_slug" in params

    def test_process_papers_call_includes_topic_slug(self):
        """Verify that process_papers is called with topic_slug."""
        # This is a structural test - the actual call happens in _run_extraction
        # which is tested via integration tests (pragma: no cover)
        # Here we just verify the API contract exists
        from src.services.extraction_service import ExtractionService
        import inspect

        sig = inspect.signature(ExtractionService.process_papers)
        params = list(sig.parameters.keys())

        # Should have topic_slug parameter
        assert "topic_slug" in params


class TestRunCrossSynthesis:
    """Tests for CrossSynthesisPhase.

    Phase 5.2: Updated to test CrossSynthesisPhase directly with PipelineContext,
    as the new architecture uses phase objects instead of internal methods.
    """

    @pytest.mark.asyncio
    async def test_run_cross_synthesis_services_not_initialized(self):
        """Should skip when services not initialized."""
        from src.models.config import ResearchConfig

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=True,
        )
        # cross_synthesis_service is None

        phase = CrossSynthesisPhase(context)
        result = await phase.run()

        assert result.report is None

    @pytest.mark.asyncio
    async def test_run_cross_synthesis_no_enabled_questions(self):
        """Should skip when no enabled questions."""
        from src.models.config import ResearchConfig

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=True,
        )

        mock_service = MagicMock()
        mock_service.get_enabled_questions.return_value = []
        context.cross_synthesis_service = mock_service
        context.cross_synthesis_generator = MagicMock()

        phase = CrossSynthesisPhase(context)
        result = await phase.run()

        assert result.report is None
        mock_service.get_enabled_questions.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_cross_synthesis_write_fails(self):
        """Should handle write failure gracefully."""
        from src.models.config import ResearchConfig

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=True,
        )

        mock_question = MagicMock()
        mock_report = MagicMock()
        mock_report.results = [MagicMock()]
        mock_report.questions_answered = 1
        mock_report.total_cost_usd = 0.1

        mock_service = MagicMock()
        mock_service.get_enabled_questions.return_value = [mock_question]
        mock_service.synthesize_all = AsyncMock(return_value=mock_report)
        context.cross_synthesis_service = mock_service

        mock_generator = MagicMock()
        mock_generator.write.return_value = None  # Write failure
        context.cross_synthesis_generator = mock_generator

        phase = CrossSynthesisPhase(context)
        result = await phase.run()

        # Should still return report despite write failure
        assert result.report is mock_report
        mock_generator.write.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_cross_synthesis_exception_handling(self):
        """Should handle exceptions gracefully."""
        from src.models.config import ResearchConfig

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=True,
        )

        mock_question = MagicMock()
        mock_service = MagicMock()
        mock_service.get_enabled_questions.return_value = [mock_question]
        mock_service.synthesize_all = AsyncMock(
            side_effect=Exception("Synthesis failed")
        )
        context.cross_synthesis_service = mock_service
        context.cross_synthesis_generator = MagicMock()

        phase = CrossSynthesisPhase(context)
        result = await phase.run()

        # Should return result with None report and not raise
        assert result.report is None

    @pytest.mark.asyncio
    async def test_run_cross_synthesis_success(self):
        """Should successfully run cross-synthesis."""
        from src.models.config import ResearchConfig

        mock_config = MagicMock(spec=ResearchConfig)
        mock_config.research_topics = []

        context = PipelineContext(
            config=mock_config,
            config_path=Path("test.yaml"),
            config_manager=MagicMock(),
            discovery_service=MagicMock(),
            catalog_service=MagicMock(),
            registry_service=MagicMock(),
            enable_phase2=False,
            enable_synthesis=False,
            enable_cross_synthesis=True,
        )

        mock_question = MagicMock()
        mock_report = MagicMock()
        mock_report.results = [MagicMock()]
        mock_report.questions_answered = 2
        mock_report.total_cost_usd = 0.15

        mock_service = MagicMock()
        mock_service.get_enabled_questions.return_value = [mock_question]
        mock_service.synthesize_all = AsyncMock(return_value=mock_report)
        context.cross_synthesis_service = mock_service

        mock_generator = MagicMock()
        mock_generator.write.return_value = Path("/output/cross_synthesis.md")
        context.cross_synthesis_generator = mock_generator

        phase = CrossSynthesisPhase(context)
        result = await phase.run()

        assert result.report is mock_report


class TestGetProcessingResultsWithExtractionService:
    """Tests for _get_processing_results with extraction service.

    Phase 5.2: Updated to set pipeline._context instead of the read-only
    _extraction_service property.
    """

    def test_returns_topic_results_from_extraction_service(self):
        """Should return topic_results when extraction service has them."""
        pipeline = ResearchPipeline()

        # Create mock processing results
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        mock_result = ProcessingResult(
            paper_id="paper123",
            title="Test Paper",
            status=ProcessingStatus.NEW,
            topic_slug="test-topic",
        )

        # Create mock context with extraction service
        mock_extraction_service = Mock()
        mock_extraction_service.get_processing_results.return_value = [mock_result]

        mock_context = MagicMock()
        mock_context.extraction_service = mock_extraction_service
        pipeline._context = mock_context

        # Call with matching topic_slug
        results = pipeline._get_processing_results(
            papers=[],
            topic_slug="test-topic",
            extracted_papers=None,
        )

        # Should return the results from extraction service
        assert len(results) == 1
        assert results[0].paper_id == "paper123"
        assert results[0].topic_slug == "test-topic"

    def test_filters_results_by_topic_slug(self):
        """Should only return results matching the topic_slug."""
        pipeline = ResearchPipeline()

        from src.models.synthesis import ProcessingResult, ProcessingStatus

        result1 = ProcessingResult(
            paper_id="paper1",
            title="Paper 1",
            status=ProcessingStatus.NEW,
            topic_slug="topic-a",
        )
        result2 = ProcessingResult(
            paper_id="paper2",
            title="Paper 2",
            status=ProcessingStatus.NEW,
            topic_slug="topic-b",
        )

        mock_extraction_service = Mock()
        mock_extraction_service.get_processing_results.return_value = [result1, result2]

        mock_context = MagicMock()
        mock_context.extraction_service = mock_extraction_service
        pipeline._context = mock_context

        # Request only topic-a results
        results = pipeline._get_processing_results(
            papers=[],
            topic_slug="topic-a",
            extracted_papers=None,
        )

        assert len(results) == 1
        assert results[0].paper_id == "paper1"

    def test_falls_back_when_no_matching_topic_results(self):
        """Should fall back to extracted_papers when no matching topic results."""
        pipeline = ResearchPipeline()

        # Mock extraction service with results for different topic
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        result = ProcessingResult(
            paper_id="paper1",
            title="Paper 1",
            status=ProcessingStatus.NEW,
            topic_slug="other-topic",
        )

        mock_extraction_service = Mock()
        mock_extraction_service.get_processing_results.return_value = [result]

        mock_context = MagicMock()
        mock_context.extraction_service = mock_extraction_service
        pipeline._context = mock_context

        # Create mock extracted papers for fallback
        mock_metadata = Mock()
        mock_metadata.paper_id = "fallback-paper"
        mock_metadata.title = "Fallback Paper"

        mock_extracted_paper = Mock()
        mock_extracted_paper.metadata = mock_metadata
        mock_extracted_paper.extraction = None
        mock_extracted_paper.pdf_available = False

        # Request for non-matching topic
        results = pipeline._get_processing_results(
            papers=[],
            topic_slug="my-topic",
            extracted_papers=[mock_extracted_paper],
        )

        # Should fall back to extracted_papers
        assert len(results) == 1
        assert results[0].paper_id == "fallback-paper"
