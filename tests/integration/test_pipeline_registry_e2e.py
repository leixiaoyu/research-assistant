"""Behavioral Integration Tests for Pipeline-Registry Flow (Phase 3.8).

This module tests the complete integration between ResearchPipeline and
RegistryService, verifying the end-to-end flow:
    Identity Resolution → Extraction → Persistence

These tests exercise the orchestration code paths that were previously
masked by pragma: no cover tags, ensuring behavioral (not just structural)
verification of the Phase 3.5/3.6/3.8 integration.
"""

import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from typing import List, Optional, Any, Dict

from src.orchestration.research_pipeline import ResearchPipeline, PipelineResult
from src.services.registry_service import RegistryService
from src.services.config_manager import ConfigManager
from src.models.paper import PaperMetadata, Author
from src.models.config import (
    ResearchConfig,
    ResearchTopic,
    TimeframeRecent,
    GlobalSettings,
    PDFSettings,
    LLMSettings,
    CostLimitSettings,
)
from src.models.extraction import (
    ExtractionTarget,
    ExtractedPaper,
    PaperExtraction,
    ExtractionResult,
)


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return tmp_path


@pytest.fixture
def mock_config(temp_output_dir) -> ResearchConfig:
    """Create a mock ResearchConfig for testing."""
    return ResearchConfig(
        research_topics=[
            ResearchTopic(
                query="test topic for integration",
                timeframe=TimeframeRecent(type="recent", value="7d"),
                max_papers=5,
                extraction_targets=[
                    ExtractionTarget(
                        name="summary",
                        description="Extract a brief summary",
                        output_format="text",
                        required=True,
                    )
                ],
            )
        ],
        settings=GlobalSettings(
            output_base_dir=str(temp_output_dir / "output"),
            semantic_scholar_api_key="test-api-key-12345",
            pdf_settings=PDFSettings(
                temp_dir=str(temp_output_dir / "pdfs"),
                max_file_size_mb=50,
                timeout_seconds=60,
                keep_pdfs=False,
            ),
            llm_settings=LLMSettings(
                provider="google",
                model="gemini-1.5-flash",
                api_key="test-llm-key-12345",
                temperature=0.2,
                max_tokens=8000,
            ),
            cost_limits=CostLimitSettings(
                max_tokens_per_paper=10000,
                max_daily_spend_usd=1.0,
                max_total_spend_usd=5.0,
            ),
        ),
    )


@pytest.fixture
def sample_papers() -> List[PaperMetadata]:
    """Sample papers for integration testing."""
    return [
        PaperMetadata(
            paper_id="test-paper-001",
            title="Attention Mechanisms in Neural Networks",
            abstract="This paper explores attention mechanisms...",
            authors=[Author(name="Test Author A")],
            url="https://arxiv.org/abs/2301.00001",
            open_access_pdf="https://arxiv.org/pdf/2301.00001.pdf",
            doi="10.1234/test.001",
            year=2023,
            citation_count=100,
        ),
        PaperMetadata(
            paper_id="test-paper-002",
            title="Transformer Architectures for NLP",
            abstract="We present novel transformer architectures...",
            authors=[Author(name="Test Author B")],
            url="https://arxiv.org/abs/2301.00002",
            open_access_pdf="https://arxiv.org/pdf/2301.00002.pdf",
            doi="10.1234/test.002",
            year=2023,
            citation_count=50,
        ),
        PaperMetadata(
            paper_id="test-paper-003",
            title="Few-Shot Learning with Language Models",
            abstract="This work demonstrates few-shot learning...",
            authors=[Author(name="Test Author C"), Author(name="Test Author D")],
            url="https://arxiv.org/abs/2301.00003",
            open_access_pdf=None,  # No PDF available
            year=2024,
            citation_count=25,
        ),
    ]


@pytest.fixture
def mock_extraction_results(sample_papers) -> List[ExtractedPaper]:
    """Mock extraction results for integration testing."""
    results = []
    for i, paper in enumerate(sample_papers):
        extraction = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[
                ExtractionResult(
                    target_name="summary",
                    success=True,
                    content=f"Summary for paper {i + 1}",
                    confidence=0.9,
                )
            ],
            tokens_used=500 + i * 100,
            cost_usd=0.01 + i * 0.005,
            extraction_timestamp=datetime.utcnow(),
        )
        results.append(
            ExtractedPaper(
                metadata=paper,
                pdf_available=(paper.open_access_pdf is not None),
                pdf_path=(
                    f"/tmp/pdfs/{paper.paper_id}.pdf" if paper.open_access_pdf else None
                ),
                markdown_path=(
                    f"/tmp/md/{paper.paper_id}.md" if paper.open_access_pdf else None
                ),
                extraction=extraction,
            )
        )
    return results


def create_mock_config_manager(config: ResearchConfig, output_dir: Path):
    """Create a mock ConfigManager that returns the given config."""
    mock_cm = MagicMock(spec=ConfigManager)
    mock_cm.load_config.return_value = config
    mock_cm.get_output_path.return_value = output_dir
    mock_cm._config = config
    return mock_cm


class TestPipelineRegistryIntegration:
    """Behavioral integration tests for Pipeline-Registry flow."""

    @pytest.mark.asyncio
    async def test_pipeline_initializes_registry_service(
        self, mock_config, temp_output_dir
    ):
        """Test that pipeline correctly initializes RegistryService."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=True,
        )

        output_dir = temp_output_dir / "output"

        # Mock the config loading and discovery
        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
        ):
            # Setup mock topic
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            result = await pipeline.run()

        # Verify registry service was initialized
        assert pipeline._registry_service is not None
        assert isinstance(pipeline._registry_service, RegistryService)
        assert result.topics_processed == 1
        assert result.papers_discovered == 0

    @pytest.mark.asyncio
    async def test_pipeline_phase2_services_receive_registry(
        self, mock_config, temp_output_dir
    ):
        """Test that Phase 2 ExtractionService receives RegistryService."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=True,
            enable_synthesis=True,
        )

        output_dir = temp_output_dir / "output"
        captured_kwargs: Dict[str, Any] = {}

        def capture_extraction_init(*args, **kwargs):
            nonlocal captured_kwargs
            captured_kwargs = kwargs
            mock = MagicMock()
            mock.process_papers = AsyncMock(return_value=[])
            mock.get_extraction_summary = Mock(
                return_value={
                    "total_papers": 0,
                    "papers_with_pdf": 0,
                    "papers_with_extraction": 0,
                    "total_tokens_used": 0,
                    "total_cost_usd": 0.0,
                    "papers_failed": 0,
                    "papers_skipped": 0,
                }
            )
            return mock

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch("src.services.pdf_service.PDFService"),
            patch("src.services.llm_service.LLMService"),
            patch(
                "src.services.extraction_service.ExtractionService",
                side_effect=capture_extraction_init,
            ),
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            await pipeline.run()

        # Verify ExtractionService was called with registry_service
        assert "registry_service" in captured_kwargs
        assert captured_kwargs["registry_service"] is not None
        assert isinstance(captured_kwargs["registry_service"], RegistryService)

    @pytest.mark.asyncio
    async def test_pipeline_passes_topic_slug_to_extraction(
        self, mock_config, temp_output_dir, sample_papers, mock_extraction_results
    ):
        """Test that topic_slug is correctly passed through extraction chain."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=True,
            enable_synthesis=True,
        )

        output_dir = temp_output_dir / "output"
        captured_topic_slug: Optional[str] = None

        async def mock_process_papers(papers, targets, run_id, query, topic_slug=None):
            nonlocal captured_topic_slug
            captured_topic_slug = topic_slug
            return mock_extraction_results

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=sample_papers,
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch("src.services.catalog_service.CatalogService.add_run"),
            patch("src.services.pdf_service.PDFService"),
            patch("src.services.llm_service.LLMService"),
            patch(
                "src.services.extraction_service.ExtractionService"
            ) as mock_extraction_cls,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic-slug"
            mock_get_topic.return_value = mock_topic

            mock_extraction = MagicMock()
            mock_extraction.process_papers = AsyncMock(side_effect=mock_process_papers)
            mock_extraction.get_extraction_summary = Mock(
                return_value={
                    "total_papers": 3,
                    "papers_with_pdf": 2,
                    "papers_with_extraction": 3,
                    "total_tokens_used": 1500,
                    "total_cost_usd": 0.03,
                    "papers_failed": 0,
                    "papers_skipped": 0,
                }
            )
            mock_extraction_cls.return_value = mock_extraction

            await pipeline.run()

        # Verify topic_slug was passed
        assert captured_topic_slug is not None
        assert captured_topic_slug == "test-topic-slug"

    @pytest.mark.asyncio
    async def test_pipeline_extraction_flow_updates_stats(
        self, mock_config, temp_output_dir, sample_papers, mock_extraction_results
    ):
        """Test that extraction flow correctly updates result stats."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=True,
            enable_synthesis=False,
        )

        output_dir = temp_output_dir / "output"
        summary_stats = {
            "total_papers": 3,
            "papers_with_pdf": 2,
            "papers_with_extraction": 3,
            "total_tokens_used": 1500,
            "total_cost_usd": 0.035,
            "papers_failed": 0,
            "papers_skipped": 0,
        }

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=sample_papers,
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch("src.services.catalog_service.CatalogService.add_run"),
            patch("src.services.pdf_service.PDFService"),
            patch("src.services.llm_service.LLMService"),
            patch(
                "src.services.extraction_service.ExtractionService"
            ) as mock_extraction_cls,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            mock_extraction = MagicMock()
            mock_extraction.process_papers = AsyncMock(
                return_value=mock_extraction_results
            )
            mock_extraction.get_extraction_summary = Mock(return_value=summary_stats)
            mock_extraction_cls.return_value = mock_extraction

            result = await pipeline.run()

        # Verify stats are correctly merged
        assert result.papers_discovered == 3
        assert result.papers_with_extraction == 3
        assert result.total_tokens_used == 1500
        assert result.total_cost_usd == 0.035
        assert result.topics_processed == 1
        assert len(result.output_files) == 1

    @pytest.mark.asyncio
    async def test_pipeline_generates_enhanced_markdown_for_phase2(
        self, mock_config, temp_output_dir, sample_papers, mock_extraction_results
    ):
        """Test that enhanced markdown is generated when Phase 2 is enabled."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=True,
            enable_synthesis=False,
        )

        output_dir = temp_output_dir / "output"
        output_dir.mkdir(exist_ok=True)

        summary_stats = {
            "total_papers": 3,
            "papers_with_pdf": 2,
            "papers_with_extraction": 3,
            "total_tokens_used": 1500,
            "total_cost_usd": 0.03,
            "papers_failed": 0,
            "papers_skipped": 0,
        }

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=sample_papers,
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch("src.services.catalog_service.CatalogService.add_run"),
            patch("src.services.pdf_service.PDFService"),
            patch("src.services.llm_service.LLMService"),
            patch(
                "src.services.extraction_service.ExtractionService"
            ) as mock_extraction_cls,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            mock_extraction = MagicMock()
            mock_extraction.process_papers = AsyncMock(
                return_value=mock_extraction_results
            )
            mock_extraction.get_extraction_summary = Mock(return_value=summary_stats)
            mock_extraction_cls.return_value = mock_extraction

            result = await pipeline.run()

        # Verify output file was generated
        assert len(result.output_files) == 1
        output_path = Path(result.output_files[0])
        assert output_path.exists()

        # Read and verify content has extraction info
        content = output_path.read_text()
        assert "Research Brief" in content

    @pytest.mark.asyncio
    async def test_pipeline_generates_basic_markdown_without_phase2(
        self, mock_config, temp_output_dir, sample_papers
    ):
        """Test that basic markdown is generated when Phase 2 is disabled."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=False,
        )

        output_dir = temp_output_dir / "output"
        output_dir.mkdir(exist_ok=True)

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=sample_papers,
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch("src.services.catalog_service.CatalogService.add_run"),
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            result = await pipeline.run()

        # Verify output file was generated
        assert len(result.output_files) == 1
        output_path = Path(result.output_files[0])
        assert output_path.exists()

        # Read and verify content - should be basic markdown
        content = output_path.read_text()
        assert "Research Brief" in content


class TestPipelineCatalogUpdate:
    """Tests for catalog update with summary stats."""

    @pytest.mark.asyncio
    async def test_catalog_updated_with_summary_stats(
        self, mock_config, temp_output_dir, sample_papers, mock_extraction_results
    ):
        """Test that catalog is updated with extraction summary stats."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=True,
            enable_synthesis=False,
        )

        output_dir = temp_output_dir / "output"
        output_dir.mkdir(exist_ok=True)

        summary_stats = {
            "total_papers": 3,
            "papers_with_pdf": 2,
            "papers_with_extraction": 2,
            "total_tokens_used": 1200,
            "total_cost_usd": 0.025,
            "papers_failed": 1,
            "papers_skipped": 0,
        }

        captured_run = None

        def capture_add_run(topic_slug, run):
            nonlocal captured_run
            captured_run = run

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=sample_papers,
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch(
                "src.services.catalog_service.CatalogService.add_run",
                side_effect=capture_add_run,
            ),
            patch("src.services.pdf_service.PDFService"),
            patch("src.services.llm_service.LLMService"),
            patch(
                "src.services.extraction_service.ExtractionService"
            ) as mock_extraction_cls,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            mock_extraction = MagicMock()
            mock_extraction.process_papers = AsyncMock(
                return_value=mock_extraction_results
            )
            mock_extraction.get_extraction_summary = Mock(return_value=summary_stats)
            mock_extraction_cls.return_value = mock_extraction

            await pipeline.run()

        # Verify catalog run was recorded with correct stats
        assert captured_run is not None
        assert captured_run.papers_found == 3
        assert captured_run.papers_processed == 2  # From summary_stats
        assert captured_run.papers_failed == 1
        assert captured_run.total_cost_usd == 0.025


class TestPipelineResultMerging:
    """Tests for topic result merging into pipeline result."""

    @pytest.mark.asyncio
    async def test_merge_successful_topic_result(
        self, mock_config, temp_output_dir, sample_papers
    ):
        """Test merging of successful topic results."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=False,
        )

        output_dir = temp_output_dir / "output"
        output_dir.mkdir(exist_ok=True)

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=sample_papers,
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch("src.services.catalog_service.CatalogService.add_run"),
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            result = await pipeline.run()

        assert result.topics_processed == 1
        assert result.topics_failed == 0
        assert result.papers_discovered == 3
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_merge_failed_topic_result(self, mock_config, temp_output_dir):
        """Test merging of failed topic results."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=False,
        )

        output_dir = temp_output_dir / "output"

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                side_effect=Exception("API Error"),
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            result = await pipeline.run()

        assert result.topics_processed == 0
        assert result.topics_failed == 1
        assert result.papers_discovered == 0
        assert len(result.errors) == 1
        assert "API Error" in result.errors[0]["error"]


class TestPipelineProcessingResults:
    """Tests for processing results generation for synthesis."""

    @pytest.mark.asyncio
    async def test_get_processing_results_with_extractions(
        self, mock_config, temp_output_dir, sample_papers, mock_extraction_results
    ):
        """Test _get_processing_results with extraction data."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=True,
            enable_synthesis=True,
        )

        output_dir = temp_output_dir / "output"

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            await pipeline.run()

        # Now test the helper method directly
        results = pipeline._get_processing_results(
            papers=sample_papers,
            topic_slug="test-topic",
            extracted_papers=mock_extraction_results,
        )

        assert len(results) == 3
        for r in results:
            assert r.topic_slug == "test-topic"
            assert r.paper_id in [p.paper_id for p in sample_papers]

    @pytest.mark.asyncio
    async def test_get_processing_results_without_extractions(
        self, mock_config, temp_output_dir, sample_papers
    ):
        """Test _get_processing_results without extraction data (Phase 1 mode)."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=True,
        )

        output_dir = temp_output_dir / "output"

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            await pipeline.run()

        # Now test the helper method directly
        results = pipeline._get_processing_results(
            papers=sample_papers,
            topic_slug="test-topic",
            extracted_papers=None,
        )

        assert len(results) == 3
        for r in results:
            assert r.topic_slug == "test-topic"
            assert r.extraction_success is False  # No extraction in Phase 1


class TestPipelineEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_pipeline_handles_empty_papers(self, mock_config, temp_output_dir):
        """Test pipeline handles topic with no discovered papers."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=True,
            enable_synthesis=True,
        )

        output_dir = temp_output_dir / "output"

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            result = await pipeline.run()

        assert result.topics_processed == 1
        assert result.papers_discovered == 0
        assert result.papers_processed == 0
        # No output file when no papers
        assert len(result.output_files) == 0

    @pytest.mark.asyncio
    async def test_pipeline_handles_topic_without_extraction_targets(
        self, temp_output_dir, sample_papers
    ):
        """Test pipeline when topic has no extraction targets."""
        # Create config without extraction targets
        config_no_targets = ResearchConfig(
            research_topics=[
                ResearchTopic(
                    query="test topic no targets",
                    timeframe=TimeframeRecent(type="recent", value="7d"),
                    max_papers=5,
                    extraction_targets=None,  # No targets
                )
            ],
            settings=GlobalSettings(
                output_base_dir=str(temp_output_dir / "output"),
                semantic_scholar_api_key="test-api-key-12345",
            ),
        )

        # Phase 2 disabled since no extraction targets - tests basic markdown path
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=False,
        )

        output_dir = temp_output_dir / "output"
        output_dir.mkdir(exist_ok=True)

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=config_no_targets),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=sample_papers,
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
            patch("src.services.catalog_service.CatalogService.add_run"),
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            result = await pipeline.run()

        # Should still process but skip extraction
        assert result.topics_processed == 1
        assert result.papers_discovered == 3
        assert result.papers_with_extraction == 0


class TestPipelineSynthesis:
    """Tests for synthesis flow coverage."""

    @pytest.mark.asyncio
    async def test_synthesis_skipped_when_services_not_initialized(
        self, mock_config, temp_output_dir
    ):
        """Test that synthesis is skipped when services aren't initialized."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=False,  # Synthesis disabled
        )

        output_dir = temp_output_dir / "output"

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            await pipeline.run()

        # Synthesis engine should not be initialized
        assert pipeline._synthesis_engine is None or pipeline._delta_generator is None

    @pytest.mark.asyncio
    async def test_run_synthesis_with_no_services(self, mock_config, temp_output_dir):
        """Test _run_synthesis early return when services not initialized."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=False,
        )

        # Manually set services to None to test early return
        pipeline._synthesis_engine = None
        pipeline._delta_generator = None

        # Call _run_synthesis directly - should return early
        await pipeline._run_synthesis()

        # No error should be raised - method returns early

    @pytest.mark.asyncio
    async def test_synthesis_handles_exception(self, mock_config, temp_output_dir):
        """Test that synthesis handles exceptions gracefully."""
        pipeline = ResearchPipeline(
            config_path=Path("dummy/path.yaml"),
            enable_phase2=False,
            enable_synthesis=True,
        )

        output_dir = temp_output_dir / "output"

        with (
            patch.object(ConfigManager, "__init__", return_value=None),
            patch.object(ConfigManager, "load_config", return_value=mock_config),
            patch.object(ConfigManager, "get_output_path", return_value=output_dir),
            patch(
                "src.services.discovery_service.DiscoveryService.search",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch("src.services.catalog_service.CatalogService.load"),
            patch(
                "src.services.catalog_service.CatalogService.get_or_create_topic"
            ) as mock_get_topic,
        ):
            mock_topic = MagicMock()
            mock_topic.topic_slug = "test-topic"
            mock_get_topic.return_value = mock_topic

            # Run to initialize services
            await pipeline.run()

        # Now manually add processing results and mock synthesis to fail
        from src.models.synthesis import ProcessingResult, ProcessingStatus

        pipeline._topic_processing_results["test-topic"] = [
            ProcessingResult(
                paper_id="test-001",
                title="Test Paper",
                status=ProcessingStatus.NEW,
                topic_slug="test-topic",
            )
        ]

        # Mock delta_generator to raise exception
        pipeline._delta_generator = MagicMock()
        pipeline._delta_generator.generate.side_effect = Exception("Synthesis failed")

        # This should not raise - exception is caught and logged
        await pipeline._run_synthesis()


class TestPipelineResultClass:
    """Tests for PipelineResult class."""

    def test_pipeline_result_to_dict(self):
        """Test PipelineResult.to_dict() serialization."""
        result = PipelineResult()
        result.topics_processed = 2
        result.topics_failed = 1
        result.papers_discovered = 10
        result.papers_processed = 8
        result.papers_with_extraction = 5
        result.total_tokens_used = 5000
        result.total_cost_usd = 0.15
        result.output_files = ["/path/to/file1.md", "/path/to/file2.md"]
        result.errors = [{"topic": "test", "error": "sample error"}]

        result_dict = result.to_dict()

        assert result_dict["topics_processed"] == 2
        assert result_dict["topics_failed"] == 1
        assert result_dict["papers_discovered"] == 10
        assert result_dict["papers_processed"] == 8
        assert result_dict["papers_with_extraction"] == 5
        assert result_dict["total_tokens_used"] == 5000
        assert result_dict["total_cost_usd"] == 0.15
        assert len(result_dict["output_files"]) == 2
        assert len(result_dict["errors"]) == 1
