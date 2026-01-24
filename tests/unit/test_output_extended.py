from src.output.markdown_generator import MarkdownGenerator
from src.models.paper import PaperMetadata
from src.models.config import ResearchTopic, TimeframeDateRange
from datetime import date

def test_markdown_full_fields():
    gen = MarkdownGenerator()
    
    paper = PaperMetadata(
        paper_id="1",
        title="Full Paper",
        url="http://url",
        venue="Conference",
        open_access_pdf="http://pdf",
        abstract="Line 1\nLine 2"
    )
    
    topic = ResearchTopic(
        query="Q",
        timeframe=TimeframeDateRange(start_date=date(2023,1,1), end_date=date(2023,1,2)),
        max_papers=1
    )
    
    md = gen.generate([paper], topic, "run")
    
    

    # Assertions should match exact markdown formatting

    assert "**Venue:** Conference" in md

    assert "**[PDF](http://pdf/)" in md or "**[PDF](http://pdf)**" in md

    assert "> Line 1 Line 2" in md

    assert "timeframe: custom" in md