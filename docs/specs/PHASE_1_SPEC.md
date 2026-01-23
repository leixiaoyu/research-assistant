# Phase 1: Foundation & Core Pipeline (MVP)
**Version:** 1.0
**Status:** Draft
**Timeline:** 2 weeks
**Dependencies:** None

## Overview

Establish the foundational architecture for ARISP with a working end-to-end pipeline for a single research topic. This phase focuses on core infrastructure, data models, configuration management, and basic research discovery without PDF processing.

## Objectives

### Primary Objectives
1. ✅ Establish type-safe data models using Pydantic
2. ✅ Implement configuration management with validation
3. ✅ Integrate Semantic Scholar API for paper discovery
4. ✅ Build intelligent catalog system with topic deduplication
5. ✅ Generate Obsidian-compatible markdown output
6. ✅ Create modern CLI using typer

### Success Criteria
- [ ] Can search Semantic Scholar for papers matching a query
- [ ] Can handle all three timeframe types (recent, since_year, date_range)
- [ ] Can detect duplicate topics and append to existing folders
- [ ] Can generate valid Obsidian markdown with metadata
- [ ] Can run via CLI: `python main.py`
- [ ] All data structures have type hints and Pydantic validation

## Architecture

### Module Structure
```
research-assist/
├── src/
│   ├── __init__.py
│   ├── models/               # Data models
│   │   ├── __init__.py
│   │   ├── config.py         # Config models
│   │   ├── paper.py          # Paper metadata
│   │   └── catalog.py        # Catalog models
│   ├── services/             # Business logic
│   │   ├── __init__.py
│   │   ├── config_manager.py
│   │   ├── search_service.py
│   │   └── catalog_service.py
│   ├── output/               # Output generation
│   │   ├── __init__.py
│   │   └── markdown_generator.py
│   ├── utils/                # Utilities
│   │   ├── __init__.py
│   │   ├── logging.py
│   │   └── slug.py
│   └── cli.py                # CLI entry point
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── config/
│   ├── research_config.yaml
│   └── .env.template
├── output/                   # Generated output
├── requirements.txt
├── setup.py
└── pytest.ini
```

## Technical Specifications

### 1. Data Models (`src/models/`)

#### 1.1 Configuration Models (`config.py`)
```python
from pydantic import BaseModel, Field, validator
from typing import Literal, Union, List
from datetime import date

class TimeframeRecent(BaseModel):
    """Recent timeframe (e.g., last 48 hours)"""
    type: Literal["recent"] = "recent"
    value: str  # e.g., "48h", "7d", "30d"

    @validator("value")
    def validate_recent_format(cls, v):
        import re
        if not re.match(r'^\d+[hd]$', v):
            raise ValueError("Recent format must be like '48h' or '7d'")
        return v

class TimeframeSinceYear(BaseModel):
    """Papers since a specific year"""
    type: Literal["since_year"] = "since_year"
    value: int  # e.g., 2008

    @validator("value")
    def validate_year(cls, v):
        if v < 1900 or v > 2100:
            raise ValueError("Year must be between 1900 and 2100")
        return v

class TimeframeDateRange(BaseModel):
    """Custom date range"""
    type: Literal["date_range"] = "date_range"
    start_date: date
    end_date: date

    @validator("end_date")
    def validate_date_range(cls, v, values):
        if "start_date" in values and v < values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v

Timeframe = Union[TimeframeRecent, TimeframeSinceYear, TimeframeDateRange]

class ResearchTopic(BaseModel):
    """A single research topic configuration"""
    query: str = Field(..., min_length=1, description="Search query string")
    timeframe: Timeframe
    max_papers: int = Field(50, ge=1, le=500, description="Max papers to fetch")

    @validator("query")
    def validate_query(cls, v):
        if len(v.strip()) == 0:
            raise ValueError("Query cannot be empty")
        return v.strip()

class GlobalSettings(BaseModel):
    """Global pipeline settings"""
    output_base_dir: str = Field("./output", description="Base output directory")
    enable_duplicate_detection: bool = Field(True, description="Enable topic deduplication")
    semantic_scholar_api_key: str = Field(..., min_length=1, description="Semantic Scholar API key")

class ResearchConfig(BaseModel):
    """Root configuration model"""
    research_topics: List[ResearchTopic] = Field(..., min_items=1)
    settings: GlobalSettings

    class Config:
        extra = "forbid"  # Reject unknown fields
```

#### 1.2 Paper Models (`paper.py`)
```python
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime

class Author(BaseModel):
    """Paper author information"""
    name: str
    author_id: Optional[str] = None

class PaperMetadata(BaseModel):
    """Metadata for a single research paper"""
    paper_id: str = Field(..., description="Semantic Scholar paper ID")
    title: str
    abstract: Optional[str] = None
    url: HttpUrl
    doi: Optional[str] = None
    publication_date: Optional[datetime] = None
    year: Optional[int] = None
    authors: List[Author] = Field(default_factory=list)
    citation_count: int = 0
    open_access_pdf: Optional[HttpUrl] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            HttpUrl: lambda v: str(v)
        }

class SearchResult(BaseModel):
    """Result from a search query"""
    query: str
    timeframe: str
    total_found: int
    papers: List[PaperMetadata]
    search_timestamp: datetime = Field(default_factory=datetime.utcnow)
```

#### 1.3 Catalog Models (`catalog.py`)
```python
from pydantic import BaseModel, Field
from typing import List, Dict
from datetime import datetime

class CatalogRun(BaseModel):
    """A single pipeline run for a topic"""
    run_id: str
    date: datetime
    papers_found: int
    timeframe: str
    output_file: str

class TopicCatalogEntry(BaseModel):
    """Catalog entry for a research topic"""
    topic_slug: str
    query: str
    folder: str
    created_at: datetime
    runs: List[CatalogRun] = Field(default_factory=list)

class Catalog(BaseModel):
    """Master catalog of all research"""
    version: str = "1.0"
    topics: Dict[str, TopicCatalogEntry] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def get_or_create_topic(self, topic_slug: str, query: str) -> TopicCatalogEntry:
        """Get existing topic or create new entry"""
        if topic_slug not in self.topics:
            self.topics[topic_slug] = TopicCatalogEntry(
                topic_slug=topic_slug,
                query=query,
                folder=topic_slug,
                created_at=datetime.utcnow()
            )
        return self.topics[topic_slug]
```

### 2. Configuration Manager (`src/services/config_manager.py`)

**Responsibilities:**
- Load and validate `research_config.yaml`
- Merge with environment variables from `.env`
- Generate topic slugs
- Manage catalog.json
- Determine output paths

**Key Functions:**
```python
class ConfigManager:
    def __init__(self, config_path: str = "config/research_config.yaml"):
        """Initialize config manager"""

    def load_config(self) -> ResearchConfig:
        """Load and validate configuration"""

    def generate_topic_slug(self, query: str) -> str:
        """Convert query to filesystem-safe slug

        Example: "Tree of Thoughts AND machine translation"
                 → "tree-of-thoughts-and-machine-translation"
        """

    def load_catalog(self) -> Catalog:
        """Load existing catalog or create new"""

    def save_catalog(self, catalog: Catalog) -> None:
        """Save catalog to disk atomically"""

    def get_output_path(self, topic_slug: str, catalog: Catalog) -> Path:
        """Determine output directory for topic

        If topic exists in catalog, return existing folder
        Otherwise, create new folder
        """
```

**Implementation Details:**
- Use `pyyaml` for YAML parsing
- Use `python-dotenv` for .env loading
- Atomic writes for catalog.json (write to temp, then rename)
- File locking to prevent concurrent catalog corruption
- Validation errors should be user-friendly

### 3. Search Service (`src/services/search_service.py`)

**Responsibilities:**
- Query Semantic Scholar API
- Handle timeframe conversion
- Parse API responses into PaperMetadata
- Handle API errors and rate limits

**Key Functions:**
```python
class SearchService:
    def __init__(self, api_key: str):
        """Initialize with API key"""

    async def search(self, topic: ResearchTopic) -> SearchResult:
        """Search for papers matching topic

        Args:
            topic: ResearchTopic with query and timeframe

        Returns:
            SearchResult with list of papers

        Raises:
            APIError: If API call fails after retries
            RateLimitError: If rate limit exceeded
        """

    def _convert_timeframe(self, timeframe: Timeframe) -> dict:
        """Convert timeframe to API parameters

        Examples:
            TimeframeRecent("48h") → {"publicationDate": "2025-01-21:"}
            TimeframeSinceYear(2008) → {"year": "2008-"}
            TimeframeDateRange(...) → {"publicationDate": "2020-01-01:2020-12-31"}
        """

    def _parse_response(self, response: dict) -> List[PaperMetadata]:
        """Parse API response into PaperMetadata models"""
```

**API Integration:**
- Endpoint: `https://api.semanticscholar.org/graph/v1/paper/search`
- Fields to request: `paperId,title,abstract,url,authors,year,publicationDate,citationCount,openAccessPdf`
- Rate limit: 100 requests/5 minutes (use exponential backoff)
- Timeout: 30 seconds per request

### 4. Catalog Service (`src/services/catalog_service.py`)

**Responsibilities:**
- Topic normalization and deduplication
- Catalog CRUD operations
- Run tracking

**Key Functions:**
```python
class CatalogService:
    def __init__(self, catalog_path: Path):
        """Initialize catalog service"""

    def find_existing_topic(self, query: str, catalog: Catalog) -> Optional[str]:
        """Find existing topic by normalized query

        Uses fuzzy matching and normalization to detect duplicates:
        - Case insensitive
        - Ignore punctuation
        - Normalize whitespace
        - Remove common words (AND, OR)
        """

    def add_run(
        self,
        catalog: Catalog,
        topic_slug: str,
        query: str,
        papers_found: int,
        timeframe: str,
        output_file: str
    ) -> Catalog:
        """Add a run to the catalog"""

    def get_topic_history(self, catalog: Catalog, topic_slug: str) -> List[CatalogRun]:
        """Get all runs for a topic"""
```

### 5. Markdown Generator (`src/output/markdown_generator.py`)

**Responsibilities:**
- Generate Obsidian-compatible markdown
- Format paper metadata
- Add YAML frontmatter

**Output Format:**
```markdown
---
topic: "Tree of Thoughts AND machine translation"
date: 2025-01-23
papers_processed: 15
timeframe: "recent:48h"
run_id: "20250123-143052"
---

# Research Brief: Tree of Thoughts AND Machine Translation

**Generated:** 2025-01-23 14:30:52 UTC
**Papers Found:** 15
**Timeframe:** Last 48 hours

## Papers

### 1. [Paper Title](https://doi.org/...)
**Authors:** John Doe, Jane Smith
**Published:** 2025-01-22
**Citations:** 5

**Abstract:**
Lorem ipsum dolor sit amet...

---

### 2. [Another Paper](https://doi.org/...)
...

## Summary Statistics

- Total papers: 15
- Average citations: 12.3
- Date range: 2025-01-20 to 2025-01-22
```

**Key Functions:**
```python
class MarkdownGenerator:
    def generate(
        self,
        search_result: SearchResult,
        topic: ResearchTopic,
        run_id: str
    ) -> str:
        """Generate markdown content"""

    def _format_frontmatter(self, metadata: dict) -> str:
        """Generate YAML frontmatter"""

    def _format_paper(self, paper: PaperMetadata, index: int) -> str:
        """Format a single paper entry"""

    def _format_statistics(self, papers: List[PaperMetadata]) -> str:
        """Generate summary statistics"""
```

### 6. CLI (`src/cli.py`)

**Commands:**
```bash
# Run pipeline with default config
python -m src.cli run

# Run with custom config
python -m src.cli run --config custom.yaml

# Validate config without running
python -m src.cli validate --config research_config.yaml

# Show catalog
python -m src.cli catalog show

# Show history for a topic
python -m src.cli catalog history "tree-of-thoughts-and-machine-translation"

# Version info
python -m src.cli version
```

**Implementation:**
```python
import typer
from pathlib import Path
from typing import Optional

app = typer.Typer()

@app.command()
def run(
    config: Path = typer.Option(
        "config/research_config.yaml",
        "--config", "-c",
        help="Path to research config YAML"
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Validate and plan without executing"
    )
):
    """Run the research pipeline"""

@app.command()
def validate(
    config: Path = typer.Argument(..., help="Config file to validate")
):
    """Validate configuration file"""

@app.command()
def catalog(subcommand: str, topic: Optional[str] = None):
    """Manage catalog (show, history)"""

if __name__ == "__main__":
    app()
```

## Implementation Requirements

### Dependencies
```txt
# requirements.txt
pydantic>=2.0.0
pyyaml>=6.0
python-dotenv>=1.0.0
typer>=0.9.0
aiohttp>=3.9.0
structlog>=23.1.0
pytest>=7.4.0
pytest-asyncio>=0.21.0
black>=23.0.0
mypy>=1.5.0
```

### Environment Variables
```bash
# .env.template
SEMANTIC_SCHOLAR_API_KEY=your_api_key_here
```

### Configuration Template
```yaml
# config/research_config.yaml
research_topics:
  - query: "Tree of Thoughts AND machine translation"
    timeframe:
      type: "recent"
      value: "48h"
    max_papers: 50

settings:
  output_base_dir: "./output"
  enable_duplicate_detection: true
  semantic_scholar_api_key: "${SEMANTIC_SCHOLAR_API_KEY}"
```

## Testing Requirements

### Unit Tests (80% coverage target)
```python
# tests/unit/test_models.py
def test_timeframe_recent_validation():
    """Test recent timeframe validation"""

def test_config_loading():
    """Test config loading and validation"""

def test_topic_slug_generation():
    """Test slug generation from queries"""

# tests/unit/test_search_service.py
def test_timeframe_conversion():
    """Test timeframe to API parameter conversion"""

# tests/unit/test_catalog_service.py
def test_duplicate_detection():
    """Test topic deduplication logic"""
```

### Integration Tests
```python
# tests/integration/test_end_to_end.py
async def test_full_pipeline():
    """Test complete pipeline flow"""
    # 1. Load config
    # 2. Search Semantic Scholar (mocked)
    # 3. Update catalog
    # 4. Generate markdown
    # 5. Verify output
```

### Test Fixtures
```python
# tests/fixtures/sample_config.yaml
# tests/fixtures/sample_api_response.json
# tests/fixtures/sample_catalog.json
```

## Acceptance Criteria

### Functional Requirements
- [ ] Load and validate research_config.yaml
- [ ] Query Semantic Scholar API successfully
- [ ] Handle all three timeframe types correctly
- [ ] Generate topic slugs consistently
- [ ] Detect duplicate topics (>90% accuracy)
- [ ] Create output directories automatically
- [ ] Generate valid Obsidian markdown
- [ ] Update catalog.json atomically
- [ ] CLI works for all commands
- [ ] Error messages are user-friendly

### Non-Functional Requirements
- [ ] All data models use Pydantic
- [ ] 100% type hint coverage
- [ ] 80%+ test coverage
- [ ] Code formatted with black
- [ ] Type checking passes (mypy)
- [ ] All tests pass
- [ ] Documentation complete (docstrings)
- [ ] README.md updated

### Performance Requirements
- [ ] Config validation < 1s
- [ ] Single topic search < 10s
- [ ] Catalog operations < 100ms
- [ ] Markdown generation < 1s

## Deliverables

1. ✅ Source code for all modules
2. ✅ Unit and integration tests
3. ✅ Configuration templates (.env.template, research_config.yaml)
4. ✅ Updated requirements.txt
5. ✅ CLI documentation
6. ✅ Developer setup guide

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Semantic Scholar API changes | HIGH | Pin API version, abstract API client |
| API rate limits | MEDIUM | Implement backoff, cache responses |
| Config validation too strict | LOW | Provide helpful error messages |
| Slug collision | LOW | Add hash suffix if needed |

## Future Considerations (Not in Phase 1)

- PDF processing (Phase 2)
- LLM extraction (Phase 2)
- Concurrent processing (Phase 3)
- Caching (Phase 3)
- Metrics/monitoring (Phase 4)

## Sign-off

- [ ] Product Owner Approval
- [ ] Technical Lead Approval
- [ ] Security Review Complete
- [ ] Ready for Development
