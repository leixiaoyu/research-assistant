"""Integration tests for Phase 3.5/3.6 backfill scenario.

Tests the complete flow:
1. Process a paper for the first time (NEW)
2. Change extraction targets
3. Verify the registry detects BACKFILL action
4. Verify synthesis generates correct delta briefs
"""

import pytest
from datetime import datetime, timezone

from src.models.paper import PaperMetadata, Author
from src.models.extraction import ExtractionTarget
from src.models.registry import ProcessingAction
from src.models.synthesis import ProcessingStatus
from src.services.registry_service import RegistryService
from src.output.synthesis_engine import SynthesisEngine
from src.output.delta_generator import DeltaGenerator


@pytest.fixture
def temp_registry(tmp_path):
    """Create a temporary registry for testing."""
    registry_path = tmp_path / "registry.json"
    return RegistryService(registry_path=registry_path)


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create temporary output directory."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture
def sample_paper():
    """Create a sample paper for testing."""
    return PaperMetadata(
        paper_id="test-paper-001",
        title="Test Paper on Machine Learning",
        abstract="A comprehensive study on ML techniques.",
        url="https://example.com/paper",
        authors=[Author(name="Author A"), Author(name="Author B")],
        publication_date=datetime(2025, 1, 15, tzinfo=timezone.utc),
    )


@pytest.fixture
def extraction_targets_v1():
    """Initial extraction targets."""
    return [
        ExtractionTarget(
            name="methodology",
            description="Extract methodology",
            format="text",
        ),
    ]


@pytest.fixture
def extraction_targets_v2():
    """Updated extraction targets (triggers backfill)."""
    return [
        ExtractionTarget(
            name="methodology",
            description="Extract methodology",
            format="text",
        ),
        ExtractionTarget(
            name="results",
            description="Extract key results",
            format="text",
        ),
    ]


class TestBackfillDetection:
    """Tests for backfill detection in RegistryService."""

    def test_new_paper_action(self, temp_registry, sample_paper, extraction_targets_v1):
        """Test that a new paper returns PROCESS_NEW action."""
        action, entry = temp_registry.determine_action(
            paper=sample_paper,
            topic_slug="test-topic",
            extraction_targets=extraction_targets_v1,
        )

        assert action == ProcessingAction.FULL_PROCESS
        assert entry is None

    def test_duplicate_paper_action(
        self, temp_registry, sample_paper, extraction_targets_v1
    ):
        """Test that a duplicate paper returns SKIP action."""
        # First, register the paper
        temp_registry.register_paper(
            paper=sample_paper,
            topic_slug="test-topic",
            extraction_targets=extraction_targets_v1,
            pdf_path=None,
        )

        # Now check the action - should be SKIP
        action, entry = temp_registry.determine_action(
            paper=sample_paper,
            topic_slug="test-topic",
            extraction_targets=extraction_targets_v1,
        )

        assert action == ProcessingAction.SKIP
        assert entry is not None
        # The registry uses its own UUID, but stores provider ID in identifiers
        assert entry.identifiers.get("semantic_scholar") == sample_paper.paper_id

    def test_backfill_action_on_target_change(
        self, temp_registry, sample_paper, extraction_targets_v1, extraction_targets_v2
    ):
        """Test that changing targets triggers BACKFILL action."""
        # Register paper with v1 targets
        temp_registry.register_paper(
            paper=sample_paper,
            topic_slug="test-topic",
            extraction_targets=extraction_targets_v1,
            pdf_path=None,
        )

        # Check action with v2 targets - should be BACKFILL
        action, entry = temp_registry.determine_action(
            paper=sample_paper,
            topic_slug="test-topic",
            extraction_targets=extraction_targets_v2,
        )

        assert action == ProcessingAction.BACKFILL
        assert entry is not None

    def test_map_topic_action(self, temp_registry, sample_paper, extraction_targets_v1):
        """Test that paper in different topic returns MAP_TOPIC action."""
        # Register paper in topic-a
        temp_registry.register_paper(
            paper=sample_paper,
            topic_slug="topic-a",
            extraction_targets=extraction_targets_v1,
            pdf_path=None,
        )

        # Check action for topic-b - should be MAP_TOPIC
        action, entry = temp_registry.determine_action(
            paper=sample_paper,
            topic_slug="topic-b",
            extraction_targets=extraction_targets_v1,
        )

        assert action == ProcessingAction.MAP_ONLY
        assert entry is not None


class TestDeltaGenerationWithBackfill:
    """Tests for delta generation with backfill results."""

    def test_delta_includes_backfilled_papers(self, temp_output_dir):
        """Test that delta brief includes backfilled papers section."""
        from src.models.synthesis import ProcessingResult

        generator = DeltaGenerator(output_base_dir=temp_output_dir)

        # Create results with both new and backfilled papers
        results = [
            ProcessingResult(
                paper_id="new-paper",
                title="New Paper",
                status=ProcessingStatus.NEW,
                quality_score=80.0,
                topic_slug="test-topic",
            ),
            ProcessingResult(
                paper_id="backfill-paper",
                title="Backfilled Paper",
                status=ProcessingStatus.BACKFILLED,
                quality_score=70.0,
                topic_slug="test-topic",
            ),
        ]

        # Generate delta
        path = generator.generate(
            results=results,
            topic_slug="test-topic",
        )

        assert path is not None
        assert path.exists()

        # Verify content
        content = path.read_text()
        assert "## 🆕 New Papers" in content
        assert "New Paper" in content
        assert "## 🔄 Backfilled Papers" in content
        assert "Backfilled Paper" in content

    def test_delta_summary_counts(self, temp_output_dir):
        """Test that delta summary shows correct counts."""
        from src.models.synthesis import ProcessingResult

        generator = DeltaGenerator(output_base_dir=temp_output_dir)

        results = [
            ProcessingResult(
                paper_id="new-1",
                title="New 1",
                status=ProcessingStatus.NEW,
                topic_slug="test-topic",
            ),
            ProcessingResult(
                paper_id="new-2",
                title="New 2",
                status=ProcessingStatus.NEW,
                topic_slug="test-topic",
            ),
            ProcessingResult(
                paper_id="backfill-1",
                title="Backfill 1",
                status=ProcessingStatus.BACKFILLED,
                topic_slug="test-topic",
            ),
            ProcessingResult(
                paper_id="skip-1",
                title="Skip 1",
                status=ProcessingStatus.SKIPPED,
                topic_slug="test-topic",
            ),
        ]

        path = generator.generate(results=results, topic_slug="test-topic")
        content = path.read_text()

        # Verify summary table
        assert "| 🆕 New Papers | 2 |" in content
        assert "| 🔄 Backfilled | 1 |" in content
        assert "| ⏭️ Skipped | 1 |" in content


class TestKnowledgeBaseSynthesis:
    """Tests for Knowledge Base synthesis with registry."""

    def test_synthesis_includes_all_topic_papers(
        self, temp_registry, temp_output_dir, sample_paper, extraction_targets_v1
    ):
        """Test that Knowledge Base includes all papers for a topic."""
        # Register multiple papers for the topic
        papers = [
            PaperMetadata(
                paper_id=f"paper-{i}",
                title=f"Paper {i}",
                abstract=f"Abstract {i}",
                url=f"https://example.com/paper-{i}",
            )
            for i in range(3)
        ]

        for paper in papers:
            temp_registry.register_paper(
                paper=paper,
                topic_slug="test-topic",
                extraction_targets=extraction_targets_v1,
                pdf_path=None,
            )

        # Create synthesis engine
        engine = SynthesisEngine(
            registry_service=temp_registry,
            output_base_dir=temp_output_dir,
        )

        # Synthesize
        stats = engine.synthesize("test-topic")

        # Verify
        assert stats.total_papers == 3

        # Check Knowledge Base exists
        kb_path = temp_output_dir / "test-topic" / "Knowledge_Base.md"
        assert kb_path.exists()

        content = kb_path.read_text()
        for paper in papers:
            assert paper.title in content

    def test_synthesis_includes_multiple_papers(
        self, temp_registry, temp_output_dir, extraction_targets_v1
    ):
        """Test that Knowledge Base includes all registered papers."""
        # Register multiple papers
        paper_a = PaperMetadata(
            paper_id="paper-a",
            title="Paper A on Neural Networks",
            url="https://example.com/paper-a",
        )
        paper_b = PaperMetadata(
            paper_id="paper-b",
            title="Paper B on Deep Learning",
            url="https://example.com/paper-b",
        )

        temp_registry.register_paper(
            paper=paper_a,
            topic_slug="test-topic",
            extraction_targets=extraction_targets_v1,
            pdf_path=None,
        )
        temp_registry.register_paper(
            paper=paper_b,
            topic_slug="test-topic",
            extraction_targets=extraction_targets_v1,
            pdf_path=None,
        )

        engine = SynthesisEngine(
            registry_service=temp_registry,
            output_base_dir=temp_output_dir,
        )

        stats = engine.synthesize("test-topic")

        # Verify stats
        assert stats.total_papers == 2

        # Verify content
        kb_path = temp_output_dir / "test-topic" / "Knowledge_Base.md"
        content = kb_path.read_text()

        # Both papers should be in the Knowledge Base
        assert "Paper A on Neural Networks" in content
        assert "Paper B on Deep Learning" in content


class TestRegistryPersistenceE2E:
    """E2E tests for registry persistence loop.

    Verifies that:
    1. ConcurrentPipeline persists papers to registry after extraction
    2. Subsequent runs detect existing papers
    3. BACKFILL is triggered when targets change
    4. registry.json is automatically updated by the pipeline
    """

    @pytest.fixture
    def mock_services(self):
        """Create mock services for ConcurrentPipeline."""
        from unittest.mock import Mock, AsyncMock

        services = {
            "fallback_pdf": Mock(),
            "llm": Mock(),
            "cache": Mock(),
            "dedup": Mock(),
            "filter": Mock(),
            "checkpoint": Mock(),
        }

        # Configure mocks
        services["fallback_pdf"].extract_with_fallback = AsyncMock()
        services["llm"].extract = AsyncMock()
        services["cache"].get_extraction = Mock(return_value=None)
        services["cache"].set_extraction = Mock()
        services["dedup"].find_duplicates = Mock(
            side_effect=lambda papers: (papers, [])
        )
        services["filter"].filter_and_rank = Mock(side_effect=lambda papers, q: papers)
        services["checkpoint"].get_processed_ids = Mock(return_value=set())
        services["checkpoint"].save_checkpoint = Mock()
        services["checkpoint"].clear_checkpoint = Mock()

        return services

    @pytest.mark.asyncio
    async def test_pipeline_persists_to_registry(
        self, tmp_path, mock_services, extraction_targets_v1
    ):
        """Test that ConcurrentPipeline automatically persists papers to registry."""
        from src.orchestration.concurrent_pipeline import ConcurrentPipeline
        from src.models.concurrency import ConcurrencyConfig
        from src.models.extraction import PaperExtraction
        import json

        # Create registry with temp path
        registry_path = tmp_path / "registry.json"
        registry_service = RegistryService(registry_path=registry_path)

        # Create pipeline with registry
        config = ConcurrencyConfig(
            max_concurrent_downloads=2,
            max_concurrent_conversions=1,
            max_concurrent_llm=1,
            queue_size=10,
        )

        pipeline = ConcurrentPipeline(
            config=config,
            fallback_pdf_service=mock_services["fallback_pdf"],
            llm_service=mock_services["llm"],
            cache_service=mock_services["cache"],
            dedup_service=mock_services["dedup"],
            filter_service=mock_services["filter"],
            checkpoint_service=mock_services["checkpoint"],
            registry_service=registry_service,
        )

        # Create test paper
        paper = PaperMetadata(
            paper_id="e2e-test-paper-001",
            title="E2E Test Paper on Persistence",
            abstract="Testing automatic registry persistence.",
            url="https://example.com/e2e-paper",
            authors=[Author(name="Test Author")],
        )

        # Configure mock to return successful extraction
        from unittest.mock import Mock as MockClass

        mock_result = MockClass()
        mock_result.metadata = paper
        mock_result.pdf_path = None

        mock_services["fallback_pdf"].extract_with_fallback.return_value = MockClass(
            success=True, content="# Test Content", backend="test"
        )
        mock_services["llm"].extract.return_value = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )

        # Process the paper
        results = []
        async for result in pipeline.process_papers_concurrent(
            papers=[paper],
            targets=extraction_targets_v1,
            run_id="e2e-run-1",
            query="test",
            topic_slug="e2e-topic",
        ):
            results.append(result)

        # Verify paper was processed
        assert len(results) == 1

        # CRITICAL CHECK: Verify registry.json was created and contains the paper
        assert registry_path.exists(), "registry.json should be created automatically"

        with open(registry_path) as f:
            registry_data = json.load(f)

        assert "entries" in registry_data
        assert len(registry_data["entries"]) == 1

        # Find the entry
        entry_id = list(registry_data["entries"].keys())[0]
        entry = registry_data["entries"][entry_id]

        assert entry["title_normalized"] == "e2e test paper on persistence"
        assert "e2e-topic" in entry["topic_affiliations"]
        assert entry["identifiers"]["semantic_scholar"] == "e2e-test-paper-001"

    @pytest.mark.asyncio
    async def test_backfill_triggered_on_target_change(
        self, tmp_path, mock_services, extraction_targets_v1, extraction_targets_v2
    ):
        """Test that BACKFILL is triggered when extraction targets change."""
        from src.orchestration.concurrent_pipeline import ConcurrentPipeline
        from src.models.concurrency import ConcurrencyConfig
        from src.models.extraction import PaperExtraction
        import json

        # Create registry with temp path
        registry_path = tmp_path / "registry.json"
        registry_service = RegistryService(registry_path=registry_path)

        config = ConcurrencyConfig(
            max_concurrent_downloads=2,
            max_concurrent_conversions=1,
            max_concurrent_llm=1,
            queue_size=10,
        )

        pipeline = ConcurrentPipeline(
            config=config,
            fallback_pdf_service=mock_services["fallback_pdf"],
            llm_service=mock_services["llm"],
            cache_service=mock_services["cache"],
            dedup_service=mock_services["dedup"],
            filter_service=mock_services["filter"],
            checkpoint_service=mock_services["checkpoint"],
            registry_service=registry_service,
        )

        paper = PaperMetadata(
            paper_id="backfill-e2e-paper",
            title="Backfill E2E Test Paper",
            abstract="Testing backfill detection with changed extraction targets.",
            url="https://example.com/backfill-paper",
        )

        # Configure mocks for successful extraction
        from unittest.mock import Mock as MockClass

        mock_services["fallback_pdf"].extract_with_fallback.return_value = MockClass(
            success=True, content="# Test Content", backend="test"
        )
        mock_services["llm"].extract.return_value = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[],
            tokens_used=100,
            cost_usd=0.001,
        )

        # RUN 1: Process with v1 targets
        results1 = []
        async for result in pipeline.process_papers_concurrent(
            papers=[paper],
            targets=extraction_targets_v1,
            run_id="backfill-run-1",
            query="test",
            topic_slug="backfill-topic",
        ):
            results1.append(result)

        assert len(results1) == 1

        # Verify initial state
        processing_results_1 = pipeline.get_processing_results()
        assert len(processing_results_1) == 1
        assert processing_results_1[0].status == ProcessingStatus.NEW

        # Read initial extraction hash
        with open(registry_path) as f:
            registry_data_1 = json.load(f)
        entry_id = list(registry_data_1["entries"].keys())[0]
        initial_hash = registry_data_1["entries"][entry_id]["extraction_target_hash"]

        # RUN 2: Process same paper with v2 targets (should trigger BACKFILL)
        pipeline2 = ConcurrentPipeline(
            config=config,
            fallback_pdf_service=mock_services["fallback_pdf"],
            llm_service=mock_services["llm"],
            cache_service=mock_services["cache"],
            dedup_service=mock_services["dedup"],
            filter_service=mock_services["filter"],
            checkpoint_service=mock_services["checkpoint"],
            registry_service=registry_service,
        )

        results2 = []
        async for result in pipeline2.process_papers_concurrent(
            papers=[paper],
            targets=extraction_targets_v2,  # Different targets!
            run_id="backfill-run-2",
            query="test",
            topic_slug="backfill-topic",
        ):
            results2.append(result)

        # CRITICAL CHECK: Verify BACKFILL was detected
        processing_results_2 = pipeline2.get_processing_results()
        assert len(processing_results_2) == 1
        assert processing_results_2[0].status == ProcessingStatus.BACKFILLED

        # Verify extraction hash was updated
        with open(registry_path) as f:
            registry_data_2 = json.load(f)

        updated_hash = registry_data_2["entries"][entry_id]["extraction_target_hash"]
        assert updated_hash != initial_hash, "Extraction hash should be updated"

    @pytest.mark.asyncio
    async def test_skip_on_same_targets(
        self, tmp_path, mock_services, extraction_targets_v1
    ):
        """Test that SKIP is returned when processing same paper with same targets."""
        from src.orchestration.concurrent_pipeline import ConcurrentPipeline
        from src.models.concurrency import ConcurrencyConfig
        from src.models.extraction import PaperExtraction

        registry_path = tmp_path / "registry.json"
        registry_service = RegistryService(registry_path=registry_path)

        config = ConcurrencyConfig(
            max_concurrent_downloads=2,
            max_concurrent_conversions=1,
            max_concurrent_llm=1,
            queue_size=10,
        )

        pipeline = ConcurrentPipeline(
            config=config,
            fallback_pdf_service=mock_services["fallback_pdf"],
            llm_service=mock_services["llm"],
            cache_service=mock_services["cache"],
            dedup_service=mock_services["dedup"],
            filter_service=mock_services["filter"],
            checkpoint_service=mock_services["checkpoint"],
            registry_service=registry_service,
        )

        paper = PaperMetadata(
            paper_id="skip-e2e-paper",
            title="Skip E2E Test Paper",
            abstract="Testing skip detection when targets are the same.",
            url="https://example.com/skip-paper",
        )

        from unittest.mock import Mock as MockClass

        mock_services["fallback_pdf"].extract_with_fallback.return_value = MockClass(
            success=True, content="# Test", backend="test"
        )
        mock_services["llm"].extract.return_value = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[],
            tokens_used=50,
            cost_usd=0.0005,
        )

        # RUN 1: First processing
        results1 = []
        async for result in pipeline.process_papers_concurrent(
            papers=[paper],
            targets=extraction_targets_v1,
            run_id="skip-run-1",
            query="test",
            topic_slug="skip-topic",
        ):
            results1.append(result)

        assert len(results1) == 1

        # RUN 2: Same paper, same targets - should be SKIPPED
        pipeline2 = ConcurrentPipeline(
            config=config,
            fallback_pdf_service=mock_services["fallback_pdf"],
            llm_service=mock_services["llm"],
            cache_service=mock_services["cache"],
            dedup_service=mock_services["dedup"],
            filter_service=mock_services["filter"],
            checkpoint_service=mock_services["checkpoint"],
            registry_service=registry_service,
        )

        results2 = []
        async for result in pipeline2.process_papers_concurrent(
            papers=[paper],
            targets=extraction_targets_v1,  # Same targets
            run_id="skip-run-2",
            query="test",
            topic_slug="skip-topic",
        ):
            results2.append(result)

        # No results should be yielded (paper was skipped)
        assert len(results2) == 0

        # Verify SKIP status
        processing_results_2 = pipeline2.get_processing_results()
        assert len(processing_results_2) == 1
        assert processing_results_2[0].status == ProcessingStatus.SKIPPED
