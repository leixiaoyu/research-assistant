from src.output.markdown_generator import MarkdownGenerator
from src.models.paper import PaperMetadata, Author
from src.models.config import ResearchTopic, TimeframeRecent


def test_generate_markdown():
    gen = MarkdownGenerator()

    papers = [
        PaperMetadata(
            paper_id="1",
            title="Paper 1",
            url="http://example.com/1",
            authors=[Author(name="A. Smith")],
            year=2023,
            citation_count=10,
        )
    ]

    topic = ResearchTopic(
        query="Test Query", timeframe=TimeframeRecent(value="48h"), max_papers=10
    )

    md = gen.generate(papers, topic, "run-1")

    assert "# Research Brief: Test Query" in md
    assert "Paper 1" in md
    assert "A. Smith" in md
    assert "## Summary Statistics" in md


def test_generate_markdown_many_authors():
    """Test that papers with more than 3 authors show 'et al.'"""
    gen = MarkdownGenerator()

    papers = [
        PaperMetadata(
            paper_id="1",
            title="Multi-Author Paper",
            url="http://example.com/1",
            authors=[
                Author(name="A. Smith"),
                Author(name="B. Jones"),
                Author(name="C. Brown"),
                Author(name="D. Wilson"),
                Author(name="E. Davis"),
            ],
            year=2023,
            citation_count=50,
        )
    ]

    topic = ResearchTopic(
        query="Test Query", timeframe=TimeframeRecent(value="48h"), max_papers=10
    )

    md = gen.generate(papers, topic, "run-1")

    assert "A. Smith, B. Jones, C. Brown, et al." in md
    # D. Wilson and E. Davis should not appear in the author list
    assert "D. Wilson" not in md
    assert "E. Davis" not in md
