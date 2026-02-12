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
