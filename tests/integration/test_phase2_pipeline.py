"""Integration tests for Phase 2: PDF Processing & LLM Extraction Pipeline

Tests service integration and data flow:
1. Enhanced markdown generator with real extraction data
2. Extraction service with real PDF/LLM service objects
3. End-to-end data transformation pipeline

Note: External APIs (Anthropic, Google) are mocked. File system operations
use temporary directories. Focus is on service integration, not external dependencies.
"""

import pytest
from pathlib import Path
from datetime import datetime
from typing import List

from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.models.paper import PaperMetadata, Author
from src.models.extraction import (
    ExtractionTarget,
    ExtractionResult,
    PaperExtraction,
    ExtractedPaper
)
from src.models.config import ResearchTopic, TimeframeRecent


@pytest.fixture
def sample_papers() -> List[PaperMetadata]:
    """Create sample papers for testing"""
    return [
        PaperMetadata(
            paper_id="2301.12345",
            title="Tree of Thoughts for Machine Translation",
            abstract="This paper explores ToT prompting techniques for MT tasks.",
            url="https://arxiv.org/abs/2301.12345",
            open_access_pdf="https://arxiv.org/pdf/2301.12345.pdf",
            authors=[
                Author(name="Alice Smith"),
                Author(name="Bob Johnson")
            ],
            year=2023,
            citation_count=42,
            venue="NeurIPS 2023"
        ),
        PaperMetadata(
            paper_id="2301.67890",
            title="Few-Shot Learning for NLP",
            abstract="Exploring few-shot techniques for natural language processing.",
            url="https://arxiv.org/abs/2301.67890",
            open_access_pdf=None,
            authors=[Author(name="Carol Davis")],
            year=2023,
            citation_count=15,
            venue="ACL 2023"
        ),
        PaperMetadata(
            paper_id="2302.11111",
            title="Prompt Engineering Best Practices",
            abstract="A comprehensive guide to prompt engineering.",
            url="https://arxiv.org/abs/2302.11111",
            open_access_pdf="https://arxiv.org/pdf/2302.11111.pdf",
            authors=[
                Author(name="David Lee"),
                Author(name="Emma Wilson"),
                Author(name="Frank Chen"),
                Author(name="Grace Kim")
            ],
            year=2024,
            citation_count=128,
            venue="ICML 2024"
        )
    ]


@pytest.fixture
def research_topic() -> ResearchTopic:
    """Create research topic"""
    return ResearchTopic(
        query="Tree of Thoughts AND machine translation",
        timeframe=TimeframeRecent(value="48h"),
        max_papers=50
    )


class TestEnhancedMarkdownGeneratorIntegration:
    """Test EnhancedMarkdownGenerator with realistic extraction data"""

    def test_generate_brief_with_mixed_extraction_results(self, sample_papers, research_topic):
        """Test generating markdown with papers that have different extraction states"""
        generator = EnhancedMarkdownGenerator()

        # Create extraction results with different types of content
        extraction1 = PaperExtraction(
            paper_id="2301.12345",
            extraction_results=[
                ExtractionResult(
                    target_name="system_prompts",
                    success=True,
                    content=["You are an expert translator.", "Translate carefully."],
                    confidence=0.95
                ),
                ExtractionResult(
                    target_name="code_snippets",
                    success=True,
                    content="def translate(text, model):\n    return model.generate(text)",
                    confidence=0.88
                ),
                ExtractionResult(
                    target_name="evaluation_metrics",
                    success=True,
                    content={"BLEU": 35.2, "METEOR": 0.72, "accuracy": 0.91},
                    confidence=0.92
                )
            ],
            tokens_used=45000,
            cost_usd=0.18,
            extraction_timestamp=datetime.utcnow()
        )

        extraction3 = PaperExtraction(
            paper_id="2302.11111",
            extraction_results=[
                ExtractionResult(
                    target_name="system_prompts",
                    success=True,
                    content=["Act as a helpful assistant."],
                    confidence=0.88
                )
            ],
            tokens_used=30000,
            cost_usd=0.12,
            extraction_timestamp=datetime.utcnow()
        )

        extracted_papers = [
            ExtractedPaper(
                metadata=sample_papers[0],
                pdf_available=True,
                pdf_path="/tmp/pdfs/2301.12345.pdf",
                markdown_path="/tmp/markdown/2301.12345.md",
                extraction=extraction1
            ),
            ExtractedPaper(
                metadata=sample_papers[1],
                pdf_available=False,
                pdf_path=None,
                markdown_path=None,
                extraction=None  # No extraction
            ),
            ExtractedPaper(
                metadata=sample_papers[2],
                pdf_available=True,
                pdf_path="/tmp/pdfs/2302.11111.pdf",
                markdown_path="/tmp/markdown/2302.11111.md",
                extraction=extraction3
            )
        ]

        # Generate markdown
        markdown = generator.generate_enhanced(
            extracted_papers=extracted_papers,
            topic=research_topic,
            run_id="integration-test-001"
        )

        # Verify frontmatter
        assert "---" in markdown
        assert "topic: Tree of Thoughts AND machine translation" in markdown
        assert "papers_processed: 3" in markdown
        assert "papers_with_pdfs: 2" in markdown
        assert "papers_with_extractions: 2" in markdown
        assert "total_tokens_used: 75000" in markdown  # 45000 + 30000
        assert "total_cost_usd: 0.3" in markdown  # 0.18 + 0.12
        assert "run_id: integration-test-001" in markdown

        # Verify structure
        assert "# Research Brief:" in markdown
        assert "## Pipeline Summary" in markdown
        assert "## Research Statistics" in markdown
        assert "## Papers" in markdown

        # Verify all papers are included
        assert "Tree of Thoughts for Machine Translation" in markdown
        assert "Few-Shot Learning for NLP" in markdown
        assert "Prompt Engineering Best Practices" in markdown

        # Verify PDF status indicators
        assert "✅" in markdown  # Has PDF
        assert "❌" in markdown  # No PDF

        # Verify extraction results formatting
        assert "System Prompts" in markdown or "system_prompts" in markdown.lower()
        assert "You are an expert translator" in markdown
        assert "```python" in markdown
        assert "def translate" in markdown
        assert "| Metric | Value |" in markdown  # Table for metrics
        assert "| BLEU | 35.2 |" in markdown

        # Verify author formatting with "et al."
        assert "David Lee, Emma Wilson, Frank Chen, et al." in markdown

    def test_generate_brief_with_summary_stats(self, sample_papers, research_topic):
        """Test markdown generation with summary statistics"""
        generator = EnhancedMarkdownGenerator()

        extraction = PaperExtraction(
            paper_id="2301.12345",
            extraction_results=[],
            tokens_used=50000,
            cost_usd=0.20,
            extraction_timestamp=datetime.utcnow()
        )

        extracted_papers = [
            ExtractedPaper(
                metadata=sample_papers[0],
                pdf_available=True,
                extraction=extraction
            )
        ]

        summary_stats = {
            "total_papers": 1,
            "papers_with_pdf": 1,
            "papers_with_extraction": 1,
            "pdf_success_rate": 100.0,
            "extraction_success_rate": 100.0,
            "total_tokens_used": 50000,
            "total_cost_usd": 0.20,
            "avg_tokens_per_paper": 50000,
            "avg_cost_per_paper": 0.200
        }

        markdown = generator.generate_enhanced(
            extracted_papers=extracted_papers,
            topic=research_topic,
            run_id="test-002",
            summary_stats=summary_stats
        )

        # Verify summary statistics section
        assert "### Extraction Statistics" in markdown
        assert "PDF Success Rate:** 100.0%" in markdown
        assert "Avg Tokens/Paper:** 50,000" in markdown
        assert "Avg Cost/Paper:** $0.200" in markdown

    def test_generate_brief_empty_papers(self, research_topic):
        """Test markdown generation with no papers"""
        generator = EnhancedMarkdownGenerator()

        markdown = generator.generate_enhanced(
            extracted_papers=[],
            topic=research_topic,
            run_id="test-empty"
        )

        # Should still generate valid structure
        assert "---" in markdown
        assert "# Research Brief:" in markdown
        assert "Papers Found:** 0" in markdown
        assert "Papers Processed:** 0" in markdown

    def test_extraction_result_formatting_all_types(self):
        """Test that all content types are formatted correctly"""
        generator = EnhancedMarkdownGenerator()

        # Test list formatting
        list_result = ExtractionResult(
            target_name="prompts_list",
            success=True,
            content=["Prompt 1", "Prompt 2", "Prompt 3"],
            confidence=0.9
        )
        list_md = generator._format_extraction_result(list_result)
        assert "- Prompt 1" in list_md
        assert "- Prompt 2" in list_md
        assert "confidence: 90%" in list_md

        # Test code formatting (Python)
        code_result = ExtractionResult(
            target_name="python_code",
            success=True,
            content="def hello():\n    print('world')",
            confidence=0.85
        )
        code_md = generator._format_extraction_result(code_result)
        assert "```python" in code_md
        assert "def hello" in code_md

        # Test code formatting (JavaScript)
        js_result = ExtractionResult(
            target_name="js_code",
            success=True,
            content="const hello = () => console.log('world');",
            confidence=0.85
        )
        js_md = generator._format_extraction_result(js_result)
        assert "```javascript" in js_md
        assert "const hello" in js_md

        # Test dict formatting (simple)
        dict_result = ExtractionResult(
            target_name="metrics",
            success=True,
            content={"accuracy": 0.95, "f1": 0.89, "recall": 0.92},
            confidence=0.91
        )
        dict_md = generator._format_extraction_result(dict_result)
        assert "| Metric | Value |" in dict_md
        assert "| accuracy | 0.95 |" in dict_md

        # Test dict formatting (complex/nested)
        complex_dict_result = ExtractionResult(
            target_name="complex_data",
            success=True,
            content={"nested": {"key": "value"}, "list": [1, 2, 3]},
            confidence=0.80
        )
        complex_md = generator._format_extraction_result(complex_dict_result)
        assert "```json" in complex_md

        # Test text formatting
        text_result = ExtractionResult(
            target_name="summary",
            success=True,
            content="This is a summary of the findings.",
            confidence=0.87
        )
        text_md = generator._format_extraction_result(text_result)
        assert "This is a summary" in text_md

        # Test empty content
        empty_result = ExtractionResult(
            target_name="missing",
            success=False,
            content=None,
            confidence=0.0
        )
        empty_md = generator._format_extraction_result(empty_result)
        assert "_No content extracted_" in empty_md


class TestDataFlowIntegration:
    """Test data flow through the Phase 2 pipeline"""

    def test_paper_metadata_to_extracted_paper_transformation(self, sample_papers):
        """Test that paper metadata flows correctly through extraction"""
        paper = sample_papers[0]

        # Simulate extraction result
        extraction = PaperExtraction(
            paper_id=paper.paper_id,
            extraction_results=[
                ExtractionResult(
                    target_name="test",
                    success=True,
                    content="test content",
                    confidence=0.9
                )
            ],
            tokens_used=10000,
            cost_usd=0.04,
            extraction_timestamp=datetime.utcnow()
        )

        # Create extracted paper
        extracted = ExtractedPaper(
            metadata=paper,
            pdf_available=True,
            pdf_path="/tmp/test.pdf",
            markdown_path="/tmp/test.md",
            extraction=extraction
        )

        # Verify data integrity
        assert extracted.metadata.paper_id == paper.paper_id
        assert extracted.metadata.title == paper.title
        assert extracted.extraction.paper_id == paper.paper_id
        assert extracted.pdf_available is True

    def test_extraction_results_aggregation(self, sample_papers):
        """Test aggregating extraction results from multiple papers"""
        from src.services.extraction_service import ExtractionService

        # Create mock services (not testing actual extraction, just aggregation)
        extraction_service = ExtractionService(
            pdf_service=None,  # type: ignore
            llm_service=None,  # type: ignore
            keep_pdfs=False
        )

        # Create extracted papers with various states
        extracted_papers = [
            ExtractedPaper(
                metadata=sample_papers[0],
                pdf_available=True,
                extraction=PaperExtraction(
                    paper_id="2301.12345",
                    extraction_results=[],
                    tokens_used=50000,
                    cost_usd=0.20,
                    extraction_timestamp=datetime.utcnow()
                )
            ),
            ExtractedPaper(
                metadata=sample_papers[1],
                pdf_available=False,
                extraction=None
            ),
            ExtractedPaper(
                metadata=sample_papers[2],
                pdf_available=True,
                extraction=PaperExtraction(
                    paper_id="2302.11111",
                    extraction_results=[],
                    tokens_used=30000,
                    cost_usd=0.12,
                    extraction_timestamp=datetime.utcnow()
                )
            )
        ]

        # Test summary statistics
        summary = extraction_service.get_extraction_summary(extracted_papers)

        assert summary["total_papers"] == 3
        assert summary["papers_with_pdf"] == 2
        assert summary["papers_with_extraction"] == 2
        assert summary["pdf_success_rate"] == 66.7  # 2/3 * 100
        assert summary["extraction_success_rate"] == 66.7  # 2/3 * 100
        assert summary["total_tokens_used"] == 80000  # 50000 + 30000
        assert summary["total_cost_usd"] == 0.32  # 0.20 + 0.12
        assert summary["avg_tokens_per_paper"] == 40000  # 80000 / 2
        assert summary["avg_cost_per_paper"] == 0.160  # 0.32 / 2
