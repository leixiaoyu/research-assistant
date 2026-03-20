"""Test factories for creating model instances.

This module provides factory functions for creating test data with sensible
defaults. Use these factories to reduce duplication across test files.

Usage:
    from tests.factories import PaperFactory, TopicFactory, AuthorFactory

    # Create a paper with defaults
    paper = PaperFactory.create()

    # Create with custom fields
    paper = PaperFactory.create(title="Custom Title", citation_count=100)

    # Create multiple papers
    papers = PaperFactory.create_batch(5)

    # Create papers with specific scenarios
    paper = PaperFactory.with_citations(count=500)
    paper = PaperFactory.with_pdf()
    paper = PaperFactory.minimal()
"""

from tests.factories.paper_factory import (
    PaperFactory,
    AuthorFactory,
    ScoredPaperFactory,
)
from tests.factories.topic_factory import TopicFactory, TimeframeFactory
from tests.factories.extraction_factory import (
    ExtractionTargetFactory,
    ExtractionResultFactory,
)
from tests.factories.config_factory import (
    FilterConfigFactory,
    DedupConfigFactory,
    QueryExpansionConfigFactory,
    CitationConfigFactory,
    AggregationConfigFactory,
)

__all__ = [
    # Paper factories
    "PaperFactory",
    "AuthorFactory",
    "ScoredPaperFactory",
    # Topic factories
    "TopicFactory",
    "TimeframeFactory",
    # Extraction factories
    "ExtractionTargetFactory",
    "ExtractionResultFactory",
    # Config factories
    "FilterConfigFactory",
    "DedupConfigFactory",
    "QueryExpansionConfigFactory",
    "CitationConfigFactory",
    "AggregationConfigFactory",
]
