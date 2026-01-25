from unittest.mock import Mock
from datetime import datetime
import pytest

from src.services.extraction_service import ExtractionService
from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.models.paper import PaperMetadata, Author
from src.models.config import ResearchTopic, TimeframeRecent
from src.models.extraction import (
    ExtractionTarget,
    ExtractionResult,
    PaperExtraction,
    ExtractedPaper,
)
from typing import List


@pytest.fixture
def mock_papers() -> List[PaperMetadata]:
    """Provide a list of mock papers for testing"""
    return [
        PaperMetadata(
            paper_id="2301.12345",
            title="Attention is All You Need",
            abstract="We propose a new simple network architecture, the Transformer...",
            authors=[Author(name="Ashish Vaswani"), Author(name="Noam Shazeer")],
            url="https://arxiv.org/abs/2301.12345",
            open_access_pdf="https://arxiv.org/pdf/2301.12345.pdf",
            year=2017,
            citation_count=100000,
        ),
        PaperMetadata(
            paper_id="2301.67890",
            title="BERT: Pre-training of Deep Bidirectional Transformers",
            abstract=(
                "We introduce a new language representation model " "called BERT..."
            ),
            authors=[Author(name="Jacob Devlin"), Author(name="Ming-Wei Chang")],
            url="https://arxiv.org/abs/2301.67890",
            open_access_pdf="https://arxiv.org/pdf/2301.67890.pdf",
            year=2018,
            citation_count=50000,
        ),
        PaperMetadata(
            paper_id="2302.11111",
            title="Language Models are Few-Shot Learners",
            abstract=(
                "We demonstrate that scaling up language models greatly " "improves..."
            ),
            authors=[
                Author(name="Tom Brown"),
                Author(name="Benjamin Mann"),
                Author(name="Nick Ryder"),
                Author(name="Melanie Subbiah"),
            ],
            url="https://arxiv.org/abs/2302.11111",
            open_access_pdf="https://arxiv.org/pdf/2302.11111.pdf",
            year=2020,
            citation_count=20000,
        ),
    ]


@pytest.fixture
def mock_topic() -> ResearchTopic:
    """Provide a mock research topic for testing"""
    return ResearchTopic(
        query="transformer models",
        timeframe=TimeframeRecent(type="recent", value="7d"),
        max_papers=5,
        extraction_targets=[
            ExtractionTarget(
                name="system_prompts",
                description="Extract system prompts",
                output_format="list",
            ),
            ExtractionTarget(
                name="code_snippets",
                description="Extract code",
                output_format="code",
            ),
            ExtractionTarget(
                name="evaluation_metrics",
                description="Extract metrics",
                output_format="json",
            ),
        ],
    )


@pytest.fixture
def mock_extractions(mock_papers) -> List[ExtractedPaper]:
    """Provide a list of extracted papers for testing"""
    extraction1 = PaperExtraction(
        paper_id="2301.12345",
        extraction_results=[
            ExtractionResult(
                target_name="system_prompts",
                success=True,
                content=["You are an expert translator.", "Translate carefully."],
                confidence=0.95,
            ),
            ExtractionResult(
                target_name="code_snippets",
                success=True,
                content=(
                    "def translate(text, model):\n" "    return model.generate(text)"
                ),
                confidence=0.88,
            ),
            ExtractionResult(
                target_name="evaluation_metrics",
                success=True,
                content={
                    "BLEU": 35.2,
                    "METEOR": 0.72,
                    "accuracy": 0.91,
                },
                confidence=0.92,
            ),
        ],
        tokens_used=45000,
        cost_usd=0.18,
        extraction_timestamp=datetime.utcnow(),
    )

    extraction3 = PaperExtraction(
        paper_id="2302.11111",
        extraction_results=[
            ExtractionResult(
                target_name="system_prompts",
                success=False,
                content=None,
                confidence=0.0,
                error="No prompts found in paper",
            )
        ],
        tokens_used=32000,
        cost_usd=0.12,
        extraction_timestamp=datetime.utcnow(),
    )

    return [
        ExtractedPaper(
            metadata=mock_papers[0],
            pdf_available=True,
            pdf_path="/tmp/pdfs/2301.12345.pdf",
            markdown_path="/tmp/md/2301.12345.md",
            extraction=extraction1,
        ),
        ExtractedPaper(
            metadata=mock_papers[1],
            pdf_available=False,
            extraction=None,  # Failed extraction
        ),
        ExtractedPaper(
            metadata=mock_papers[2],
            pdf_available=True,
            pdf_path="/tmp/pdfs/2302.11111.pdf",
            markdown_path="/tmp/md/2302.11111.pdf",
            extraction=extraction3,
        ),
    ]


class TestPhase2PipelineIntegration:
    """Integration tests for the complete Phase 2 pipeline data flow"""

    def test_markdown_generation_with_mixed_results(self, mock_extractions, mock_topic):
        """Test generating enhanced markdown with success and failure cases"""
        generator = EnhancedMarkdownGenerator()

        # Calculate summary stats
        summary_stats = {
            "total_papers": len(mock_extractions),
            "papers_with_pdf": 2,
            "papers_with_extraction": 2,
            "total_tokens_used": 77000,
            "total_cost_usd": 0.30,
            "pdf_success_rate": 66.7,
            "avg_tokens_per_paper": 38500,
            "avg_cost_per_paper": 0.15,
        }

        markdown = generator.generate_enhanced(
            extracted_papers=mock_extractions,
            topic=mock_topic,
            run_id="test-run-123",
            summary_stats=summary_stats,
        )

        # Verify content
        assert "# Research Brief: transformer models" in markdown
        assert "run_id: test-run-123" in markdown
        assert "## Pipeline Summary" in markdown
        assert "**Total Tokens Used:** 77,000" in markdown
        assert "**Total Cost:** $0.30" in markdown

        # Verify extraction results for Paper 1 (Success)
        assert "### 1. [Attention is All You Need]" in markdown
        assert "**System Prompts**" in markdown
        assert "- You are an expert translator." in markdown
        assert "def translate(text, model):" in markdown

        # Verify Paper 2 (PDF Unavailable)
        assert (
            "### 2. [BERT: Pre-training of Deep Bidirectional Transformers]" in markdown
        )
        assert "**PDF Available:** ❌" in markdown

        # Verify Paper 3 (No extraction results)
        assert "### 3. [Language Models are Few-Shot Learners]" in markdown

    def test_summary_stats_formatting(self, mock_extractions, mock_topic):
        """Test that summary statistics are correctly formatted in markdown"""
        generator = EnhancedMarkdownGenerator()

        # Test with empty stats (fallback behavior)
        markdown = generator.generate_enhanced(
            extracted_papers=mock_extractions, topic=mock_topic, run_id="test-run-empty"
        )

        assert "Extraction Statistics" not in markdown
        assert "**Total Tokens Used:** 77,000" in markdown  # Calculated from papers

        # Test with full stats
        summary_stats = {
            "total_papers": 3,
            "papers_with_pdf": 2,
            "papers_with_extraction": 2,
            "total_tokens_used": 77000,
            "total_cost_usd": 0.30,
            "pdf_success_rate": 66.7,
            "avg_tokens_per_paper": 38500,
            "avg_cost_per_paper": 0.15,
        }

        markdown = generator.generate_enhanced(
            extracted_papers=mock_extractions,
            topic=mock_topic,
            run_id="test-run-full",
            summary_stats=summary_stats,
        )

        assert "### Extraction Statistics" in markdown
        assert "**PDF Success Rate:** 66.7%" in markdown
        assert "**Avg Tokens/Paper:** 38,500" in markdown
        assert "**Avg Cost/Paper:** $0.150" in markdown

    def test_extraction_result_formatting_all_types(self, mock_papers):
        """Test formatting of all extraction content types"""
        generator = EnhancedMarkdownGenerator()

        results = [
            ExtractionResult(
                target_name="text_target",
                success=True,
                content="Sample text",
                confidence=0.9,
            ),
            ExtractionResult(
                target_name="list_target",
                success=True,
                content=["Item 1", "Item 2"],
                confidence=0.8,
            ),
            ExtractionResult(
                target_name="dict_target",
                success=True,
                content={"k1": "v1"},
                confidence=0.7,
            ),
            ExtractionResult(
                target_name="code_target",
                success=True,
                content="def hello():\n    print('hello')",
                confidence=0.95,
            ),
            ExtractionResult(
                target_name="empty_target", success=True, content=None, confidence=0.5
            ),
        ]

        extraction = PaperExtraction(
            paper_id="test-id",
            extraction_results=results,
            tokens_used=1000,
            cost_usd=0.01,
            extraction_timestamp=datetime.utcnow(),
        )

        extracted = ExtractedPaper(
            metadata=mock_papers[0], pdf_available=True, extraction=extraction
        )

        markdown = generator.generate_enhanced(
            extracted_papers=[extracted],
            topic=ResearchTopic(
                query="test", timeframe=TimeframeRecent(type="recent", value="1d")
            ),
            run_id="test",
        )

        assert "**Text Target**" in markdown
        assert "Sample text" in markdown
        assert "- Item 1" in markdown
        assert "| k1 | v1 |" in markdown
        assert "```python" in markdown
        assert "def hello():" in markdown
        assert "_No content extracted_" in markdown

    def test_empty_papers_edge_case(self, mock_topic):
        """Test pipeline behavior with empty paper list"""
        generator = EnhancedMarkdownGenerator()

        markdown = generator.generate_enhanced(
            extracted_papers=[], topic=mock_topic, run_id="empty-test"
        )

        assert "**Papers Processed:** 0" in markdown
        assert "**Total Tokens Used:** 0" in markdown

    def test_data_flow_transformation(self, mock_papers):
        """Test transformation of PaperMetadata to ExtractedPaper"""
        service = ExtractionService(pdf_service=Mock(), llm_service=Mock())

        # Create mock extraction results
        extractions = [
            PaperExtraction(
                paper_id=p.paper_id,
                extraction_results=[],
                tokens_used=500,
                cost_usd=0.005,
                extraction_timestamp=datetime.utcnow(),
            )
            for p in mock_papers
        ]

        # Manually assemble ExtractedPaper list
        results = [
            ExtractedPaper(
                metadata=mock_papers[i], pdf_available=True, extraction=extractions[i]
            )
            for i in range(len(mock_papers))
        ]

        summary = service.get_extraction_summary(results)

        assert summary["total_papers"] == 3
        assert summary["total_tokens_used"] == 1500
        assert (
            summary["total_cost_usd"] == 0.01
        )  # 0.015 rounds to 0.01 (banker's rounding)
        assert summary["avg_tokens_per_paper"] == 500
