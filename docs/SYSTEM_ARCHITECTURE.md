# ARISP System Architecture
**Version:** 2.2
**Status:** Phase 5.2 Complete - Modular Orchestration Architecture
**Last Updated:** 2026-02-27

---

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Design Principles](#design-principles)
3. [System Architecture](#system-architecture)
4. [Data Models](#data-models)
5. [Core Components](#core-components)
6. [Concurrency & Resilience](#concurrency--resilience)
7. [Storage & Caching](#storage--caching)
8. [Observability](#observability)
9. [Security](#security)
10. [Deployment Architecture](#deployment-architecture)
11. [Gap Resolution Matrix](#gap-resolution-matrix)

---

## Architecture Overview

### System Context

ARISP (Automated Research Ingestion & Synthesis Pipeline) is a production-grade system for automated research paper discovery, processing, and synthesis using LLM-powered extraction.

```
┌─────────────────────────────────────────────────────────────┐
│                         ARISP System                        │
│                                                             │
│  ┌────────────┐    ┌─────────────┐    ┌────────────────┐  │
│  │   User     │───▶│   ARISP     │───▶│   Research     │  │
│  │   Config   │    │   Pipeline  │    │   Briefs       │  │
│  └────────────┘    └─────────────┘    └────────────────┘  │
│                            │                                │
│                            ▼                                │
│         ┌──────────────────┴──────────────────┐           │
│         │                                      │           │
│    ┌────▼────┐  ┌────────┐  ┌─────────┐  ┌───▼────┐     │
│    │ ArXiv   │  │  PDFs  │  │   LLM   │  │ Catalog│     │
│    │   API   │  │(marker)│  │(Claude/ │  │   DB   │     │
│    │(Default)│  │        │  │Gemini)  │  │        │     │
│    └────┬────┘  └────────┘  └─────────┘  └────────┘     │
│         │                                                  │
│    ┌────▼────┐                                            │
│    │Semantic │                                            │
│    │Scholar  │                                            │
│    │(Optional)                                            │
│    └─────────┘                                            │
└─────────────────────────────────────────────────────────────┘
```

### Key Capabilities
- **Discovery**: Multi-provider support (ArXiv default, Semantic Scholar optional) with flexible queries
- **Processing**: PDF→Markdown conversion with code preservation
- **Extraction**: LLM-powered content analysis with configurable targets
- **Intelligence**: Deduplication, caching, quality filtering
- **Observability**: Structured logging, metrics, monitoring

---

## Design Principles

### 1. **Security First** ⚠️ **CRITICAL**
Security is the #1 priority and cannot be compromised in any situation:
- **Never hardcode secrets**: All credentials via environment variables or secure vaults
- **Input validation**: All user inputs validated with Pydantic before processing
- **Path sanitization**: Prevent directory traversal attacks
- **Secret scanning**: Automated checks before commits
- **Least privilege**: Minimal permissions required
- **Audit logging**: All security-relevant operations logged
- **Community safe**: Tool can be shared without exposing sensitive data

### 2. **Autonomous Operation**
System operates intelligently without constant human intervention:
- **Intelligent stopping criteria**: Knows when research is complete
- **Quality convergence detection**: Stops when no new high-quality papers found
- **Incremental search**: Continues from last checkpoint
- **Self-optimization**: Learns from past runs to improve filters

### 3. **Separation of Concerns**
Each layer and component has a single, well-defined responsibility.

### 4. **Fail-Safe Operation**
System degrades gracefully rather than failing completely:
- No PDF? Use abstract only
- LLM fails? Skip extraction, keep metadata
- Partial failures don't abort entire pipeline

### 5. **Type Safety**
All data structures use Pydantic models with runtime validation.

### 6. **Async-First**
I/O-bound operations use asyncio for maximum throughput.

### 7. **Configurable by Default**
Every behavior is configurable via YAML/environment variables.

### 8. **Observable**
Every operation emits structured logs and metrics.

### 9. **Cost-Aware**
LLM usage is tracked, limited, and optimized.

### 10. **Idempotent**
Pipeline can be safely re-run; checkpoints enable resume.

### 11. **Test-Driven Development**
No code pushed without complete verification (automated tests or manual validation).
- **Target**: 100% test coverage for all modules.
- **Minimum**: 99% test coverage per module (Non-negotiable blocking gate).
- **CI Enforcement**: Automated coverage checks, linting (Flake8/Black), and type checking (Mypy).

---

## System Architecture

### Layered Architecture

```
┌────────────────────────────────────────────────────────────────┐
│                    CLI / API Layer                             │
│  - Command-line interface (typer)                              │
│  - Future: REST API for programmatic access                    │
└────────────────────────────────────────────────────────────────┘
                              │
┌────────────────────────────────────────────────────────────────┐
│                 Orchestration Layer                            │
│  ┌──────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ PipelineExecutor │  │ WorkflowEngine  │  │  Checkpoint  │ │
│  │  - Coordinates   │  │ - State machine │  │   Manager    │ │
│  │    services      │  │ - Error recovery│  │ - Resume cap │ │
│  └──────────────────┘  └─────────────────┘  └──────────────┘ │
└────────────────────────────────────────────────────────────────┘
                              │
┌────────────────────────────────────────────────────────────────┐
│                    Service Layer                               │
│  ┌─────────────┐ ┌──────────────┐ ┌────────────┐ ┌─────────┐ │
│  │  Discovery  │ │ Acquisition  │ │Extraction  │ │ Storage │ │
│  │   Service   │ │   Service    │ │  Service   │ │ Service │ │
│  │             │ │              │ │            │ │         │ │
│  │ - Search    │ │ - Download   │ │ - PDF→MD   │ │ - Files │ │
│  │ - Filter    │ │ - Convert    │ │ - LLM      │ │ - Catalog│
│  │ - Rank      │ │ - Validate   │ │ - Parse    │ │ - Cache │ │
│  └─────────────┘ └──────────────┘ └────────────┘ └─────────┘ │
└────────────────────────────────────────────────────────────────┘
                              │
┌────────────────────────────────────────────────────────────────┐
│                Infrastructure Layer                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │  Config  │ │ Logging  │ │ Metrics  │ │   Resilience    │  │
│  │ Manager  │ │(structlog│ │(Prom)    │ │  (tenacity)     │  │
│  └──────────┘ └──────────┘ └──────────┘ └─────────────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────────┐  │
│  │  Cache   │ │  Error   │ │Security  │ │  Concurrency    │  │
│  │(diskcache│ │ Handler  │ │          │ │   (asyncio)     │  │
│  └──────────┘ └──────────┘ └──────────┘ └─────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### Data Flow Architecture

```
[User Config YAML]
        │
        ▼
┌───────────────────┐
│ ConfigManager     │ ◀─── Validates with Pydantic
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ DiscoveryService  │ ◀─── Semantic Scholar API
│  - Search papers  │      + Rate limiting
│  - Apply filters  │      + Caching
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ DeduplicationSvc  │ ◀─── Check catalog.json
│  - DOI matching   │      + Title similarity
│  - Title fuzzy    │      + Content fingerprint
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ FilterService     │ ◀─── Quality filters
│  - Citations      │      + Venue ranking
│  - Recency        │      + Relevance score
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ ConcurrentPool    │ ◀─── Worker pool (async)
│  Workers:         │      + Semaphores
│  ├─ Download PDF  │      + Backpressure
│  ├─ Convert PDF   │      + Error handling
│  ├─ Extract LLM   │
│  └─ Save result   │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ StorageService    │ ◀─── Atomic writes
│  - Save markdown  │      + Directory structure
│  - Update catalog │      + Compression
│  - Archive PDFs   │      + Retention policy
└────────┬──────────┘
         │
         ▼
[Research Briefs + Catalog]
```

---

## Data Models

### Core Domain Models

All models use **Pydantic** for validation, serialization, and type safety.

#### Configuration Models

```python
from pydantic import BaseModel, Field, validator, HttpUrl
from typing import Literal, Union, List, Optional
from datetime import date, datetime
from enum import Enum

# ============= Timeframe Models =============

class TimeframeType(str, Enum):
    """Enumeration of supported timeframe types"""
    RECENT = "recent"
    SINCE_YEAR = "since_year"
    DATE_RANGE = "date_range"

class TimeframeRecent(BaseModel):
    """Recent timeframe (e.g., last 48 hours)"""
    type: Literal[TimeframeType.RECENT] = TimeframeType.RECENT
    value: str = Field(..., pattern=r'^\d+[hd]$')

    @validator("value")
    def validate_recent_format(cls, v):
        """Ensure format is like '48h' or '7d'"""
        unit = v[-1]
        amount = int(v[:-1])
        if unit == 'h' and amount > 720:  # Max 30 days
            raise ValueError("Hour-based timeframe cannot exceed 720h (30 days)")
        if unit == 'd' and amount > 365:
            raise ValueError("Day-based timeframe cannot exceed 365d (1 year)")
        return v

class TimeframeSinceYear(BaseModel):
    """Papers since a specific year"""
    type: Literal[TimeframeType.SINCE_YEAR] = TimeframeType.SINCE_YEAR
    value: int = Field(..., ge=1900, le=2100)

class TimeframeDateRange(BaseModel):
    """Custom date range"""
    type: Literal[TimeframeType.DATE_RANGE] = TimeframeType.DATE_RANGE
    start_date: date
    end_date: date

    @validator("end_date")
    def validate_date_range(cls, v, values):
        if "start_date" in values and v < values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v

Timeframe = Union[TimeframeRecent, TimeframeSinceYear, TimeframeDateRange]

# ============= Extraction Models =============

class ExtractionOutputFormat(str, Enum):
    """Supported extraction output formats"""
    TEXT = "text"
    CODE = "code"
    JSON = "json"
    LIST = "list"

class ExtractionTarget(BaseModel):
    """Definition of what to extract from a paper"""
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=10, max_length=500)
    output_format: ExtractionOutputFormat = ExtractionOutputFormat.TEXT
    required: bool = Field(False, description="Fail pipeline if not found")
    examples: Optional[List[str]] = Field(None, max_items=5)

    @validator("name")
    def validate_name(cls, v):
        """Ensure name is slug-friendly"""
        if not v.replace('_', '').isalnum():
            raise ValueError("Name must be alphanumeric with underscores only")
        return v

# ============= Filter Models =============

class PaperFilter(BaseModel):
    """Paper quality and relevance filters"""
    min_citation_count: int = Field(0, ge=0, le=10000)
    min_year: Optional[int] = Field(None, ge=1900, le=2100)
    max_year: Optional[int] = Field(None, ge=1900, le=2100)
    allowed_venues: Optional[List[str]] = Field(None, max_items=50)
    min_relevance_score: float = Field(0.0, ge=0.0, le=1.0)

    @validator("max_year")
    def validate_year_range(cls, v, values):
        if v and "min_year" in values and values["min_year"]:
            if v < values["min_year"]:
                raise ValueError("max_year must be >= min_year")
        return v

# ============= Autonomous Operation Models =============

class StoppingCriteria(BaseModel):
    """Criteria for autonomous stopping of research"""
    max_papers: int = Field(50, ge=1, le=1000, description="Stop after N papers")
    max_runs_without_new: int = Field(3, ge=1, le=10,
                                      description="Stop after N runs with no new quality papers")
    min_quality_score: float = Field(0.7, ge=0.0, le=1.0,
                                     description="Minimum quality score to count as 'new quality paper'")
    convergence_window: int = Field(7, ge=1, le=30,
                                    description="Days to check for convergence")
    enable_auto_stop: bool = Field(True, description="Enable autonomous stopping")

class AutonomousSettings(BaseModel):
    """Settings for autonomous operation"""
    enabled: bool = Field(False, description="Enable autonomous mode")
    stopping_criteria: StoppingCriteria = Field(default_factory=StoppingCriteria)
    search_frequency_hours: int = Field(24, ge=1, le=168,
                                        description="How often to search for new papers")
    incremental_search: bool = Field(True,
                                     description="Only search for papers newer than last run")

# ============= Research Topic Model =============

class ResearchTopic(BaseModel):
    """Complete research topic configuration"""
    query: str = Field(..., min_length=1, max_length=500)
    timeframe: Timeframe
    max_papers: int = Field(50, ge=1, le=1000)
    extraction_targets: List[ExtractionTarget] = Field(default_factory=list)
    filters: PaperFilter = Field(default_factory=PaperFilter)
    autonomous: AutonomousSettings = Field(default_factory=AutonomousSettings)

    @validator("query")
    def validate_query(cls, v):
        v = v.strip()
        if len(v) == 0:
            raise ValueError("Query cannot be empty")
        # Security: Prevent command injection
        dangerous_chars = [";", "|", "&", "`", "$", "$(", "&&", "||"]
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"Query contains forbidden character sequence: {char}")
        return v

# ============= Global Settings =============

class PDFSettings(BaseModel):
    """PDF processing configuration"""
    temp_dir: str = "./temp"
    keep_pdfs: bool = True
    max_file_size_mb: int = Field(50, ge=1, le=500)
    timeout_seconds: int = Field(300, ge=30, le=1800)
    compression_enabled: bool = True

class LLMProvider(str, Enum):
    """Supported LLM providers"""
    ANTHROPIC = "anthropic"
    GOOGLE = "google"

class LLMSettings(BaseModel):
    """LLM API configuration"""
    provider: LLMProvider = LLMProvider.ANTHROPIC
    model: str = "claude-3-5-sonnet-20250122"
    api_key: str = Field(..., min_length=10)
    max_tokens: int = Field(100000, ge=1000, le=1000000)
    temperature: float = Field(0.0, ge=0.0, le=1.0)
    timeout: int = Field(300, ge=30, le=1800)

class CostLimits(BaseModel):
    """LLM cost control configuration"""
    max_tokens_per_paper: int = Field(100000, ge=1000, le=1000000)
    max_daily_spend_usd: float = Field(50.0, ge=0.01, le=10000.0)
    max_total_spend_usd: float = Field(500.0, ge=0.01, le=100000.0)
    alert_threshold_usd: float = Field(40.0, ge=0.01)

class ConcurrencySettings(BaseModel):
    """Concurrent processing configuration"""
    max_concurrent_downloads: int = Field(5, ge=1, le=20)
    max_concurrent_conversions: int = Field(3, ge=1, le=10)
    max_concurrent_llm: int = Field(2, ge=1, le=5)
    checkpoint_interval: int = Field(10, ge=1, le=100)

class CacheSettings(BaseModel):
    """Caching configuration"""
    enabled: bool = True
    cache_dir: str = "./cache"
    ttl_api_hours: int = Field(1, ge=0, le=168)  # Max 1 week
    ttl_pdf_days: int = Field(7, ge=0, le=365)
    ttl_extraction_days: int = Field(30, ge=0, le=365)
    max_size_gb: float = Field(10.0, ge=0.1, le=1000.0)

class GlobalSettings(BaseModel):
    """Global pipeline settings"""
    output_base_dir: str = "./output"
    enable_duplicate_detection: bool = True
    semantic_scholar_api_key: str = Field(..., min_length=10)
    pdf_settings: PDFSettings = Field(default_factory=PDFSettings)
    llm_settings: LLMSettings
    cost_limits: CostLimits = Field(default_factory=CostLimits)
    concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)

class ResearchConfig(BaseModel):
    """Root configuration model"""
    research_topics: List[ResearchTopic] = Field(..., min_items=1, max_items=100)
    settings: GlobalSettings

    class Config:
        extra = "forbid"  # Reject unknown fields
        use_enum_values = True
```

#### Paper Models

```python
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Any
from datetime import datetime

class Author(BaseModel):
    """Paper author information"""
    name: str
    author_id: Optional[str] = None
    affiliation: Optional[str] = None

class PaperMetadata(BaseModel):
    """Complete metadata for a research paper"""
    # Identifiers
    paper_id: str = Field(..., description="Semantic Scholar paper ID")
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None

    # Content
    title: str = Field(..., min_length=1, max_length=1000)
    abstract: Optional[str] = Field(None, max_length=10000)

    # Links
    url: HttpUrl
    open_access_pdf: Optional[HttpUrl] = None

    # Metadata
    authors: List[Author] = Field(default_factory=list)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    publication_date: Optional[datetime] = None
    venue: Optional[str] = None

    # Metrics
    citation_count: int = Field(0, ge=0)
    influential_citation_count: int = Field(0, ge=0)

    # Computed fields
    relevance_score: float = Field(0.0, ge=0.0, le=1.0)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            HttpUrl: lambda v: str(v)
        }

class ExtractionResult(BaseModel):
    """Result of extracting a single target"""
    target_name: str
    success: bool
    content: Any  # Type depends on output_format
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    error: Optional[str] = None
    tokens_used: int = Field(0, ge=0)

class PaperExtraction(BaseModel):
    """Complete extraction for a single paper"""
    paper_id: str
    extraction_results: List[ExtractionResult]
    total_tokens_used: int = Field(0, ge=0)
    cost_usd: float = Field(0.0, ge=0.0)
    extraction_timestamp: datetime = Field(default_factory=datetime.utcnow)
    extraction_duration_seconds: float = Field(0.0, ge=0.0)

class ProcessingStatus(str, Enum):
    """Paper processing status"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"

class ExtractedPaper(BaseModel):
    """Paper with complete processing results"""
    metadata: PaperMetadata
    status: ProcessingStatus = ProcessingStatus.PENDING

    # Processing artifacts
    pdf_available: bool = False
    pdf_path: Optional[str] = None
    markdown_path: Optional[str] = None

    # Extraction results
    extraction: Optional[PaperExtraction] = None

    # Processing metadata
    processing_started_at: Optional[datetime] = None
    processing_completed_at: Optional[datetime] = None
    processing_duration_seconds: Optional[float] = None

    # Error tracking
    error: Optional[str] = None
    retry_count: int = Field(0, ge=0)
```

#### Catalog Models

```python
from pydantic import BaseModel, Field
from typing import List, Dict, Optional
from datetime import datetime

class CatalogRun(BaseModel):
    """A single pipeline run for a topic"""
    run_id: str = Field(..., min_length=1)
    date: datetime
    papers_found: int = Field(0, ge=0)
    papers_processed: int = Field(0, ge=0)
    papers_failed: int = Field(0, ge=0)
    papers_skipped: int = Field(0, ge=0)
    timeframe: str
    output_file: str
    total_cost_usd: float = Field(0.0, ge=0.0)
    total_duration_seconds: float = Field(0.0, ge=0.0)

class ProcessedPaper(BaseModel):
    """Reference to a processed paper"""
    paper_id: str
    doi: Optional[str] = None
    title: str
    processed_at: datetime
    run_id: str

class TopicCatalogEntry(BaseModel):
    """Catalog entry for a research topic"""
    topic_slug: str
    query: str
    folder: str
    created_at: datetime
    last_updated: datetime = Field(default_factory=datetime.utcnow)
    runs: List[CatalogRun] = Field(default_factory=list)
    processed_papers: List[ProcessedPaper] = Field(default_factory=list)

    def add_run(self, run: CatalogRun):
        """Add a run and update timestamp"""
        self.runs.append(run)
        self.last_updated = datetime.utcnow()

    def has_paper(self, paper_id: str, doi: Optional[str] = None) -> bool:
        """Check if paper already processed"""
        for p in self.processed_papers:
            if p.paper_id == paper_id:
                return True
            if doi and p.doi and p.doi == doi:
                return True
        return False

class Catalog(BaseModel):
    """Master catalog of all research"""
    version: str = "1.0"
    topics: Dict[str, TopicCatalogEntry] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def get_or_create_topic(
        self,
        topic_slug: str,
        query: str
    ) -> TopicCatalogEntry:
        """Get existing topic or create new entry"""
        if topic_slug not in self.topics:
            self.topics[topic_slug] = TopicCatalogEntry(
                topic_slug=topic_slug,
                query=query,
                folder=topic_slug,
                created_at=datetime.utcnow()
            )
        self.last_updated = datetime.utcnow()
        return self.topics[topic_slug]
```

---

## Core Components

### 1. Configuration Manager

**Responsibility**: Load, validate, and provide configuration

```python
class ConfigManager:
    """Manages application configuration with validation"""

    def __init__(self, config_path: str = "config/research_config.yaml"):
        self.config_path = Path(config_path)
        self.env_loaded = False

    def load_config(self) -> ResearchConfig:
        """Load and validate configuration

        Process:
        1. Load .env file
        2. Read YAML
        3. Substitute environment variables
        4. Validate with Pydantic
        5. Return ResearchConfig

        Raises:
            ConfigValidationError: If config is invalid
            FileNotFoundError: If config file missing
        """
        # Load environment
        if not self.env_loaded:
            load_dotenv()
            self.env_loaded = True

        # Read YAML
        with open(self.config_path) as f:
            raw_config = yaml.safe_load(f)

        # Substitute env vars
        config_str = yaml.dump(raw_config)
        config_str = Template(config_str).safe_substitute(os.environ)
        config_data = yaml.safe_load(config_str)

        # Validate
        try:
            config = ResearchConfig(**config_data)
            logger.info("config_loaded", topics=len(config.research_topics))
            return config
        except ValidationError as e:
            raise ConfigValidationError(f"Invalid config: {e}")

    def generate_topic_slug(self, query: str) -> str:
        """Convert query to filesystem-safe slug

        Examples:
            "Tree of Thoughts AND machine translation"
            → "tree-of-thoughts-and-machine-translation"

            "reinforcement learning robotics"
            → "reinforcement-learning-robotics"
        """
        import re
        slug = query.lower()
        # Remove special characters
        slug = re.sub(r'[^\w\s-]', '', slug)
        # Replace spaces with hyphens
        slug = re.sub(r'[\s_]+', '-', slug)
        # Remove consecutive hyphens
        slug = re.sub(r'-+', '-', slug)
        # Trim hyphens
        slug = slug.strip('-')
        # Limit length
        if len(slug) > 100:
            slug = slug[:100].rstrip('-')
        return slug
```

### 2. Discovery Service

**Responsibility**: Abstract paper discovery across multiple research paper APIs

**Architecture**: Provider Pattern (Strategy Pattern) implemented in Phase 1.5

**Supported Providers:**
- **ArXiv** (default): Open access AI/CS pre-prints, no API key required
- **Semantic Scholar** (optional): Comprehensive research database, requires API key
- **Future**: OpenAlex, PubMed, CORE, etc.

#### Provider Interface

```python
from abc import ABC, abstractmethod

class DiscoveryProvider(ABC):
    """Abstract interface for research paper discovery"""

    @abstractmethod
    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers matching topic"""
        pass

    @abstractmethod
    def validate_query(self, query: str) -> str:
        """Validate query syntax"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name"""
        pass

    @property
    @abstractmethod
    def requires_api_key(self) -> bool:
        """Whether API key is required"""
        pass
```

#### Concrete Providers

**ArXiv Provider** (Phase 1.5):
```python
class ArxivProvider(DiscoveryProvider):
    """ArXiv API provider - no API key required"""

    ARXIV_API_URL = "http://export.arxiv.org/api/query"
    ARXIV_RATE_LIMIT_SECONDS = 3.0  # Per ArXiv ToS

    def __init__(self):
        self.rate_limiter = RateLimiter(
            max_requests=1,
            time_window=3.0,
            min_delay=3.0
        )

    @property
    def name(self) -> str:
        return "arxiv"

    @property
    def requires_api_key(self) -> bool:
        return False

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search ArXiv for papers

        Process:
        1. Enforce rate limiting (3s minimum)
        2. Build ArXiv query from topic
        3. Parse timeframe into date range
        4. Fetch from ArXiv API (feedparser)
        5. Filter by publication date
        6. Validate PDF URLs
        7. Map to PaperMetadata model
        8. Return papers with guaranteed PDF access
        """
        await self.rate_limiter.acquire()
        # Implementation details in Phase 1.5 spec
```

**Semantic Scholar Provider** (Phase 1, refactored in Phase 1.5):
```python
class SemanticScholarProvider(DiscoveryProvider):
    """Semantic Scholar API provider - requires API key"""

    def __init__(self, api_key: str, cache_service: CacheService):
        self.api_key = api_key
        self.cache = cache_service
        self.rate_limiter = RateLimiter(
            max_requests=100,
            time_window=300
        )

    @property
    def name(self) -> str:
        return "semantic_scholar"

    @property
    def requires_api_key(self) -> bool:
        return True

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search Semantic Scholar for papers

        Process (unchanged from Phase 1):
        1. Check cache
        2. Build API query
        3. Execute with rate limiting
        4. Parse response
        5. Convert to PaperMetadata
        6. Cache results

        Returns:
            List of paper metadata
        """
        # Check cache
        query_hash = self._hash_query(topic)
        cached = await self.cache.get_api_response(query_hash)
        if cached:
            logger.info("cache_hit", query=topic.query)
            return [PaperMetadata(**p) for p in cached]

        # Build query
        params = self._build_query_params(topic)

        # Execute with rate limiting
        await self.rate_limiter.acquire()

        async with self.get_session() as session:
            async with session.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params=params,
                headers={"x-api-key": self.api_key},
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                data = await response.json()

        # Parse response
        papers = self._parse_response(data)

        # Cache
        await self.cache.set_api_response(
            query_hash,
            [p.dict() for p in papers]
        )

        logger.info(
            "papers_discovered",
            query=topic.query,
            count=len(papers)
        )

        return papers

    def _build_query_params(self, topic: ResearchTopic) -> dict:
        """Convert topic to API parameters"""
        params = {
            "query": topic.query,
            "limit": topic.max_papers,
            "fields": "paperId,title,abstract,url,authors,year,"
                     "publicationDate,citationCount,influentialCitationCount,"
                     "venue,openAccessPdf"
        }

        # Add timeframe filter
        if isinstance(topic.timeframe, TimeframeRecent):
            date_filter = self._convert_recent_to_date(topic.timeframe.value)
            params["publicationDateOrYear"] = f"{date_filter}:"
        elif isinstance(topic.timeframe, TimeframeSinceYear):
            params["year"] = f"{topic.timeframe.value}-"
        elif isinstance(topic.timeframe, TimeframeDateRange):
            start = topic.timeframe.start_date.isoformat()
            end = topic.timeframe.end_date.isoformat()
            params["publicationDate"] = f"{start}:{end}"

        return params
```

#### Discovery Service Orchestrator

**Discovery Service** (Phase 1.5+):
```python
class DiscoveryService:
    """Paper discovery service with provider abstraction"""

    def __init__(self, provider: DiscoveryProvider = None):
        """Initialize with provider instance (for testing)"""
        self.provider = provider

    @classmethod
    def from_config(
        cls,
        topic: ResearchTopic,
        api_keys: dict
    ) -> "DiscoveryService":
        """Factory method to create service with provider from config

        Args:
            topic: Research topic with provider specification
            api_keys: Dictionary of API keys by provider name

        Returns:
            DiscoveryService with appropriate provider

        Example:
            api_keys = {
                "semantic_scholar": os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
                "openalex": os.getenv("OPENALEX_API_KEY")
            }
            service = DiscoveryService.from_config(topic, api_keys)
        """
        if topic.provider == ProviderType.ARXIV:
            provider = ArxivProvider()
        elif topic.provider == ProviderType.SEMANTIC_SCHOLAR:
            api_key = api_keys.get("semantic_scholar")
            if not api_key:
                raise ValueError(
                    "Semantic Scholar provider requires API key. "
                    "Set SEMANTIC_SCHOLAR_API_KEY environment variable."
                )
            provider = SemanticScholarProvider(
                api_key=api_key,
                cache_service=cache_service
            )
        else:
            raise ValueError(f"Unknown provider: {topic.provider}")

        return cls(provider=provider)

    async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
        """Search for papers using configured provider

        Delegates to provider-specific implementation
        """
        return await self.provider.search(topic)
```

**Provider Selection Matrix:**

| Provider | API Key? | Cost | Coverage | PDF Access | Best For |
|----------|----------|------|----------|------------|----------|
| **ArXiv** (default) | ❌ No | Free | AI/CS/Physics pre-prints | 100% | Cutting-edge AI research |
| **Semantic Scholar** | ✅ Yes | Free | 200M+ papers, all fields | Varies | Comprehensive research |
| **OpenAlex** (future) | Optional | Free | 250M+ works | Varies | Multi-disciplinary |
| **PubMed** (future) | ❌ No | Free | Medical/life sciences | Varies | Biomedical research |

### 2.5 PDF Extraction Service (Multi-Backend Fallback)

**Responsibility**: Reliable PDF-to-Markdown conversion with automatic fallback and quality scoring

**Phase**: 2.5 (Production-hardened reliability layer)

**Architecture**: Fallback chain with quality-based selection

```
┌─────────────────────────────────────────────────────┐
│         FallbackPDFService (Orchestrator)           │
│                                                     │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────┐ │
│  │  PyMuPDF    │ → │  PDFPlumber  │ → │ Pandoc  │ │
│  │  (Primary)  │   │  (Secondary) │   │(Fallback)│
│  └─────────────┘   └──────────────┘   └─────────┘ │
│         ↓                  ↓                ↓       │
│  ┌───────────────────────────────────────────────┐ │
│  │       QualityValidator (Scoring 0.0-1.0)      │ │
│  └───────────────────────────────────────────────┘ │
│                        ↓                            │
│           Select Highest Quality Result            │
└─────────────────────────────────────────────────────┘
```

#### Fallback Chain Strategy

```python
class FallbackPDFService:
    """Multi-backend PDF extraction with quality-based selection

    Implements the "try all, pick best" strategy:
    1. Attempt all configured backends concurrently or sequentially
    2. Score each successful extraction (0.0-1.0)
    3. Return highest quality result
    4. Gracefully degrade to text-only if all fail
    """

    def __init__(
        self,
        config: PDFSettings,
        validator: QualityValidator
    ):
        self.config = config
        self.validator = validator

        # Initialize extractors
        self.extractors = {
            PDFBackend.PYMUPDF: PyMuPDFExtractor(),
            PDFBackend.PDFPLUMBER: PDFPlumberExtractor(),
            PDFBackend.PANDOC: PandocExtractor()
        }

    async def extract_with_fallback(
        self,
        pdf_path: Path
    ) -> PDFExtractionResult:
        """Extract with fallback chain

        Process:
        1. Try each backend in fallback_chain order
        2. Skip backends that fail setup validation
        3. Score successful extractions
        4. Stop on first ≥ min_quality if stop_on_success=True
        5. Otherwise try all and return best
        6. Return TEXT_ONLY backend if all fail

        Returns:
            Best quality extraction or graceful degradation
        """
        results = []

        for backend_config in self.config.fallback_chain:
            extractor = self.extractors[backend_config.backend]

            # Skip if backend not available
            if not extractor.validate_setup():
                continue

            # Try extraction with timeout
            try:
                result = await asyncio.wait_for(
                    extractor.extract(pdf_path),
                    timeout=backend_config.timeout_seconds
                )

                if result.success:
                    # Score quality
                    score = self.validator.score_extraction(
                        result.markdown,
                        pdf_path,
                        result.metadata.page_count
                    )
                    result.quality_score = score
                    results.append(result)

                    # Early exit if quality threshold met
                    if score >= backend_config.min_quality and self.config.stop_on_success:
                        break

            except asyncio.TimeoutError:
                logger.warning("extraction_timeout", backend=backend_config.backend)

        # Return best result or TEXT_ONLY fallback
        if results:
            return max(results, key=lambda r: r.quality_score)
        else:
            return PDFExtractionResult(
                success=False,
                error="All backends failed",
                backend=PDFBackend.TEXT_ONLY,
                metadata=ExtractionMetadata(backend=PDFBackend.TEXT_ONLY)
            )
```

#### Backend Characteristics

| Backend | Speed | Tables | Code | Complexity | Best For |
|---------|-------|--------|------|------------|----------|
| **PyMuPDF** | ⚡⚡⚡ Fast | ✅ Good | ✅ Excellent | Simple | Text-heavy papers, code snippets |
| **PDFPlumber** | ⚡⚡ Medium | ⭐⭐⭐ Best | ✅ Good | Medium | Papers with complex tables |
| **Pandoc** | ⚡ Slow | ⚠️ Basic | ⚠️ Fair | Complex | System-level fallback |

#### Quality Scoring Heuristics

```python
class QualityValidator:
    """Scores extraction quality using heuristics (0.0-1.0)"""

    def score_extraction(
        self,
        markdown: str,
        pdf_path: Path,
        page_count: int = 0
    ) -> float:
        """Calculate quality score

        Metrics (weighted average):
        - Text density: 500-2000 chars/page ideal (30%)
        - Structure: Headers/lists ~10 per 1k chars (25%)
        - Code detection: Presence of code blocks (20%)
        - Table detection: Presence of markdown tables (25%)

        Returns:
            Score 0.0 (poor) to 1.0 (excellent)
        """
        if len(markdown) < 100:
            return 0.0

        scores = {
            'density': self._calculate_text_density_score(markdown, page_count),
            'structure': self._calculate_structure_score(markdown),
            'code': self._calculate_code_detection_score(markdown),
            'tables': self._calculate_table_detection_score(markdown)
        }

        weights = {'density': 0.30, 'structure': 0.25, 'code': 0.20, 'tables': 0.25}

        return sum(scores[k] * weights[k] for k in scores)
```

#### Configuration

```yaml
# research_config.yaml (Phase 2.5 settings)
pdf:
  fallback_chain:
    - backend: pymupdf
      timeout_seconds: 60
      min_quality: 0.7
    - backend: pdfplumber
      timeout_seconds: 90
      min_quality: 0.6
    - backend: pandoc
      timeout_seconds: 120
      min_quality: 0.5
  stop_on_success: true  # Stop at first backend ≥ min_quality
  max_file_size_mb: 50
```

#### Benefits

1. **Reliability**: No single point of failure - if one backend fails, others compensate
2. **Quality**: Automatic selection of highest quality extraction
3. **Performance**: `stop_on_success=true` ensures fast path when quality is good
4. **Graceful Degradation**: TEXT_ONLY fallback ensures pipeline never crashes
5. **Testability**: 100% test coverage on all extractors and fallback logic

#### Integration Points

- **ExtractionService**: Uses `FallbackPDFService` instead of direct marker-pdf calls
- **Concurrent Pipeline**: Each worker uses fallback service for PDF processing
- **Cache Service**: Caches extracted markdown to avoid re-processing

---

### 3. Concurrent Processing Engine

**Responsibility**: Process multiple papers concurrently with resource limits

```python
class ConcurrentPipeline:
    """Concurrent paper processing with backpressure"""

    def __init__(
        self,
        config: ConcurrencySettings,
        pdf_service: PDFService,
        llm_service: LLMService,
        checkpoint_service: CheckpointService
    ):
        self.config = config
        self.pdf_service = pdf_service
        self.llm_service = llm_service
        self.checkpoint = checkpoint_service

        # Semaphores for resource limiting
        self.download_sem = asyncio.Semaphore(config.max_concurrent_downloads)
        self.conversion_sem = asyncio.Semaphore(config.max_concurrent_conversions)
        self.llm_sem = asyncio.Semaphore(config.max_concurrent_llm)

    async def process_papers(
        self,
        papers: List[PaperMetadata],
        targets: List[ExtractionTarget],
        run_id: str
    ) -> AsyncIterator[ExtractedPaper]:
        """Process papers concurrently

        Architecture:
        - Producer feeds papers to bounded queue
        - N workers process from queue
        - Results yielded as completed (unordered)
        - Checkpoints saved periodically
        - Errors don't stop pipeline

        Yields:
            ExtractedPaper as they complete
        """
        # Load checkpoint
        processed_ids = await self.checkpoint.load_processed(run_id)
        pending = [p for p in papers if p.paper_id not in processed_ids]

        logger.info(
            "concurrent_processing_started",
            total=len(papers),
            pending=len(pending),
            from_checkpoint=len(processed_ids)
        )

        # Create bounded queue
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        # Start workers
        num_workers = self.config.max_concurrent_downloads
        workers = [
            asyncio.create_task(
                self._worker(queue, targets, run_id, i)
            )
            for i in range(num_workers)
        ]

        # Producer
        async def produce():
            for paper in pending:
                await queue.put(paper)
            # Send sentinel values
            for _ in range(num_workers):
                await queue.put(None)

        producer = asyncio.create_task(produce())

        # Collect results
        completed = 0
        async for result in self._collect_results(workers):
            yield result
            completed += 1

            # Checkpoint periodically
            if completed % self.config.checkpoint_interval == 0:
                await self.checkpoint.save_progress(
                    run_id,
                    result.metadata.paper_id
                )

        await producer
        await asyncio.gather(*workers)

        logger.info(
            "concurrent_processing_completed",
            total=completed
        )

    async def _worker(
        self,
        queue: asyncio.Queue,
        targets: List[ExtractionTarget],
        run_id: str,
        worker_id: int
    ):
        """Worker coroutine processes papers from queue"""
        while True:
            paper = await queue.get()
            if paper is None:  # Sentinel
                break

            try:
                result = await self._process_single(paper, targets)
                yield result
            except Exception as e:
                logger.error(
                    "worker_error",
                    worker_id=worker_id,
                    paper_id=paper.paper_id,
                    error=str(e),
                    exc_info=True
                )
                # Yield failed result
                yield ExtractedPaper(
                    metadata=paper,
                    status=ProcessingStatus.FAILED,
                    error=str(e)
                )
            finally:
                queue.task_done()

    async def _process_single(
        self,
        paper: PaperMetadata,
        targets: List[ExtractionTarget]
    ) -> ExtractedPaper:
        """Process single paper with resource limits"""
        result = ExtractedPaper(
            metadata=paper,
            processing_started_at=datetime.utcnow()
        )

        try:
            # Download phase
            if paper.open_access_pdf:
                async with self.download_sem:
                    result.status = ProcessingStatus.DOWNLOADING
                    pdf_path = await self.pdf_service.download_pdf(
                        str(paper.open_access_pdf),
                        paper.paper_id
                    )
                    result.pdf_path = str(pdf_path)
                    result.pdf_available = True

            # Conversion phase
            if result.pdf_available:
                async with self.conversion_sem:
                    result.status = ProcessingStatus.CONVERTING
                    md_path = await self.pdf_service.convert_to_markdown(
                        Path(result.pdf_path)
                    )
                    result.markdown_path = str(md_path)

            # Extraction phase
            async with self.llm_sem:
                result.status = ProcessingStatus.EXTRACTING

                # Get markdown content
                if result.markdown_path:
                    content = Path(result.markdown_path).read_text()
                else:
                    # Fallback to abstract
                    content = self._format_abstract(paper)

                # Extract with LLM
                extraction = await self.llm_service.extract(
                    content,
                    targets,
                    paper
                )
                result.extraction = extraction

            result.status = ProcessingStatus.COMPLETED

        except Exception as e:
            result.status = ProcessingStatus.FAILED
            result.error = str(e)
            raise

        finally:
            result.processing_completed_at = datetime.utcnow()
            result.processing_duration_seconds = (
                result.processing_completed_at -
                result.processing_started_at
            ).total_seconds()

        return result
```

### 3.5 LLM Service Layer (Phase 5.1)

**Responsibility**: Modular LLM extraction with provider abstraction, cost tracking, and resilience

**Phase**: 5.1 (LLM Service Decomposition)

**Architecture**: Package-based decomposition with single-responsibility modules

```
src/services/llm/
├── __init__.py           # Re-export LLMService for backward compatibility
├── service.py            # Main LLMService orchestrator (872 lines)
├── providers/
│   ├── __init__.py
│   ├── base.py           # Abstract LLMProvider interface (186 lines)
│   ├── anthropic.py      # AnthropicProvider for Claude (230 lines)
│   └── google.py         # GoogleProvider for Gemini (250 lines)
├── cost_tracker.py       # CostTracker with budget enforcement (233 lines)
├── prompt_builder.py     # PromptBuilder for structured prompts (165 lines)
├── response_parser.py    # ResponseParser for JSON extraction (241 lines)
├── health.py             # ProviderHealth dataclass
└── exceptions.py         # LLMProviderError hierarchy (133 lines)
```

#### Component Responsibilities

| Component | Responsibility |
|-----------|---------------|
| `LLMService` | Orchestrates extraction with fallback and resilience |
| `LLMProvider` (abstract) | Defines provider interface: `extract()`, `calculate_cost()`, `get_health()` |
| `AnthropicProvider` | Claude model integration with rate limiting |
| `GoogleProvider` | Gemini model integration with safety handling |
| `CostTracker` | Per-session usage tracking, daily/total limits, budget enforcement |
| `PromptBuilder` | Constructs structured extraction prompts from targets |
| `ResponseParser` | Parses and validates JSON responses from LLMs |

#### Provider Abstraction

```python
class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def extract(self, prompt: str, max_tokens: int) -> LLMResponse:
        """Execute extraction and return standardized response."""
        pass

    @abstractmethod
    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD for token usage."""
        pass
```

#### Key Benefits

| Before (Monolithic) | After (Modular) |
|---------------------|-----------------|
| 838 lines in single file | 7 focused modules with single responsibility |
| Provider logic mixed with orchestration | Separate provider classes (Anthropic, Google) |
| Cost tracking tightly coupled | Independent CostTracker with budget enforcement |
| Difficult to add new providers | Abstract LLMProvider interface for extensibility |
| Testing requires full class mock | Each component testable in isolation |

**Details:** See [PHASE_5.1_SPEC.md](specs/PHASE_5.1_SPEC.md) for implementation details and API specifications.

### 4. Pipeline Orchestration (Phase 5.2)

**Responsibility**: Coordinate pipeline phases with shared context and modular execution

**Architecture**: Phase-based orchestration pattern with dedicated modules for each stage:
- `DiscoveryPhase`: Paper discovery and filtering
- `ExtractionPhase`: PDF download and LLM extraction
- `SynthesisPhase`: Per-topic knowledge base generation
- `CrossSynthesisPhase`: Cross-topic analysis and insights

**Key Components:**
- `PipelineContext`: Shared state, services, and error tracking across phases
- `PipelineResult`: Aggregated results from all phases
- Abstract `PipelinePhase` base class for consistent phase interface

**Details:** See [PHASE_5.2_SPEC.md](specs/PHASE_5.2_SPEC.md) for package structure and implementation details.

#### Phase Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    ResearchPipeline                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                 PipelineContext                       │  │
│  │  (shared state, services, config, error tracking)    │  │
│  └──────────────────────────────────────────────────────┘  │
│                           │                                  │
│     ┌─────────────────────┼─────────────────────┐          │
│     ▼                     ▼                     ▼          │
│ ┌──────────┐      ┌──────────────┐      ┌───────────────┐ │
│ │Discovery │  ──▶ │ Extraction   │  ──▶ │  Synthesis    │ │
│ │  Phase   │      │    Phase     │      │    Phase      │ │
│ └──────────┘      └──────────────┘      └───────────────┘ │
│                                                │            │
│                                                ▼            │
│                                    ┌───────────────────┐   │
│                                    │ CrossSynthesis    │   │
│                                    │     Phase         │   │
│                                    └───────────────────┘   │
│                                                │            │
│                                                ▼            │
│                                    ┌───────────────────┐   │
│                                    │  PipelineResult   │   │
│                                    │  (aggregated)     │   │
│                                    └───────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

#### Key Benefits

| Before (Monolithic) | After (Phase-Based) |
|---------------------|---------------------|
| 824 lines in one file | Core phases <160 lines each (discovery, synthesis, cross_synthesis) |
| 14 functions interleaved | Clear phase separation with pipeline.py (415 lines) as coordinator |
| Difficult to test phases | Each phase testable in isolation |
| 12+ service dependencies in __init__ | Lazy service initialization via PipelineContext |
| State scattered across methods | Centralized PipelineContext (147 lines) |

**Note:** `pipeline.py` (415 lines) and `extraction.py` (456 lines) exceed ideal targets and may be further decomposed in future phases.

---

## Concurrency & Resilience

### Concurrency Model

**Pattern**: Async producer-consumer with bounded queues and semaphores

```
┌─────────────────────────────────────────────────┐
│           Bounded Queue (100 items)             │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐           │
│  │ P1 │ │ P2 │ │ P3 │ │... │ │ PN │           │
│  └────┘ └────┘ └────┘ └────┘ └────┘           │
└────────────────┬────────────────────────────────┘
                 │
    ┌────────────┼────────────┬────────────┐
    │            │            │            │
┌───▼───┐   ┌───▼───┐   ┌───▼───┐   ┌───▼───┐
│Worker1│   │Worker2│   │Worker3│   │WorkerN│
│       │   │       │   │       │   │       │
│ ┌──┐  │   │ ┌──┐  │   │ ┌──┐  │   │ ┌──┐  │
│ │DL│  │   │ │DL│  │   │ │DL│  │   │ │DL│  │
│ └┬─┘  │   │ └┬─┘  │   │ └┬─┘  │   │ └┬─┘  │
│  │    │   │  │    │   │  │    │   │  │    │
│ ┌▼──┐ │   │ ┌▼──┐ │   │ ┌▼──┐ │   │ ┌▼──┐ │
│ │CV │ │   │ │CV │ │   │ │CV │ │   │ │CV │ │
│ └┬──┘ │   │ └┬──┘ │   │ └┬──┘ │   │ └┬──┘ │
│  │    │   │  │    │   │  │    │   │  │    │
│ ┌▼──┐ │   │ ┌▼──┐ │   │ ┌▼──┐ │   │ ┌▼──┐ │
│ │LLM│ │   │ │LLM│ │   │ │LLM│ │   │ │LLM│ │
│ └───┘ │   │ └───┘ │   │ └───┘ │   │ └───┘ │
└───┬───┘   └───┬───┘   └───┬───┘   └───┬───┘
    │           │           │           │
    └───────────┴───────────┴───────────┘
                 │
            [Results Queue]

DL = Download (Semaphore: 5)
CV = Convert  (Semaphore: 3)
LLM = Extract (Semaphore: 2)
```

### Resilience Patterns

#### 1. Retry with Exponential Backoff

```python
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(TransientError)
)
async def fetch_with_retry(url: str) -> bytes:
    """Fetch with automatic retry on transient failures"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 429:  # Rate limit
                    raise TransientError("Rate limited")
                if 500 <= response.status < 600:  # Server error
                    raise TransientError(f"Server error: {response.status}")
                response.raise_for_status()
                return await response.read()
    except asyncio.TimeoutError:
        raise TransientError("Timeout")
    except aiohttp.ClientError as e:
        raise TransientError(str(e))
```

#### 2. Circuit Breaker

```python
class CircuitBreaker:
    """Circuit breaker pattern for external APIs"""

    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: int = 60
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout_seconds
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.state: Literal["closed", "open", "half_open"] = "closed"

    async def call(self, func, *args, **kwargs):
        """Execute function through circuit breaker"""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
            else:
                raise CircuitBreakerOpenError(
                    "Circuit breaker is open, skipping call"
                )

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Reset circuit breaker on success"""
        self.failures = 0
        self.state = "closed"

    def _on_failure(self):
        """Increment failures and maybe open circuit"""
        self.failures += 1
        self.last_failure_time = datetime.utcnow()

        if self.failures >= self.failure_threshold:
            self.state = "open"
            logger.warning(
                "circuit_breaker_opened",
                failures=self.failures
            )
```

#### 3. Checkpoint/Resume

```python
class CheckpointService:
    """Enable resume from interruption"""

    async def save_progress(self, run_id: str, paper_id: str):
        """Atomically save checkpoint"""
        checkpoint_file = self.checkpoint_dir / f"{run_id}.json"

        # Load existing
        if checkpoint_file.exists():
            data = json.loads(checkpoint_file.read_text())
        else:
            data = {
                "run_id": run_id,
                "started_at": datetime.utcnow().isoformat(),
                "processed_ids": []
            }

        # Update
        if paper_id not in data["processed_ids"]:
            data["processed_ids"].append(paper_id)
        data["last_updated"] = datetime.utcnow().isoformat()

        # Atomic write
        temp_file = checkpoint_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(data, indent=2))
        temp_file.rename(checkpoint_file)
```

---

## Storage & Caching

### Storage Architecture

```
output/
├── catalog.json                    # Master catalog (atomic writes)
├── topic-a/
│   ├── 2025-01-23_Run.md          # Daily research briefs
│   ├── 2025-01-24_Run.md
│   ├── papers/                     # Archived PDFs (compressed)
│   │   ├── paper1.pdf.gz
│   │   └── paper2.pdf.gz
│   └── extractions/                # Cached extraction results
│       ├── paper1.json
│       └── paper2.json
└── topic-b/
    └── ...

cache/                              # Multi-level cache
├── api/                            # Semantic Scholar responses (1h TTL)
├── pdfs/                           # Downloaded PDFs (7d TTL)
└── extractions/                    # LLM results (30d TTL)

temp/                               # Temporary processing
├── pdfs/                           # Pending conversion
└── markdown/                       # Converted markdown

checkpoints/                        # Resume state
└── run_20250123_143052.json       # Processed paper IDs
```

### Caching Strategy

**Multi-Level Cache** with different TTLs:

```python
class CacheService:
    """Multi-tier caching with automatic expiration"""

    def __init__(self, cache_dir: Path, settings: CacheSettings):
        self.settings = settings

        # Separate caches with different TTLs
        self.api_cache = diskcache.Cache(
            cache_dir / "api",
            timeout=settings.ttl_api_hours * 3600
        )
        self.pdf_cache = diskcache.Cache(
            cache_dir / "pdfs",
            timeout=settings.ttl_pdf_days * 86400
        )
        self.extraction_cache = diskcache.Cache(
            cache_dir / "extractions",
            timeout=settings.ttl_extraction_days * 86400
        )

    async def get_extraction(
        self,
        paper_id: str,
        targets_hash: str
    ) -> Optional[PaperExtraction]:
        """Get cached extraction

        Key includes targets_hash so changing extraction
        targets invalidates cache
        """
        key = f"{paper_id}:{targets_hash}"
        data = self.extraction_cache.get(key)
        if data:
            metrics.cache_hits.labels(cache_type="extraction").inc()
            return PaperExtraction.parse_obj(data)
        metrics.cache_misses.labels(cache_type="extraction").inc()
        return None
```

### Retention Policy

```python
class StorageManager:
    """Manage storage with retention policies"""

    async def apply_retention_policy(self):
        """Clean up old files based on policy"""
        # Compress PDFs older than 30 days
        for pdf_path in self.find_pdfs_older_than(days=30):
            if not pdf_path.name.endswith('.gz'):
                await self.compress_pdf(pdf_path)

        # Delete PDFs older than 365 days
        for pdf_path in self.find_pdfs_older_than(days=365):
            pdf_path.unlink()
            logger.info("pdf_deleted", path=str(pdf_path))

        # Check disk usage
        total_size = self.calculate_total_size()
        if total_size > self.max_size_bytes:
            await self.evict_oldest_until_under_limit()
```

---

## Observability

### Structured Logging

**Format**: JSON with correlation IDs

```python
# Setup
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_id,
        add_service_context,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True
)

# Usage
logger = structlog.get_logger()

# Set correlation ID for request
run_id = set_correlation_id()

logger.info(
    "pipeline_started",
    run_id=run_id,
    topic=topic.query,
    max_papers=topic.max_papers
)

# All subsequent logs include run_id automatically
logger.info("paper_processed", paper_id="abc123", duration_ms=4500)

# Output:
# {
#   "event": "paper_processed",
#   "level": "info",
#   "timestamp": "2025-01-23T14:30:52.123Z",
#   "correlation_id": "a1b2c3d4-...",
#   "service": "arisp",
#   "version": "1.0.0",
#   "paper_id": "abc123",
#   "duration_ms": 4500
# }
```

### Metrics

**Prometheus metrics** for monitoring:

```python
from prometheus_client import Counter, Gauge, Histogram

# Counters
papers_processed = Counter(
    'arisp_papers_processed_total',
    'Total papers processed',
    ['status']  # success, failed, skipped
)

llm_tokens = Counter(
    'arisp_llm_tokens_total',
    'LLM tokens consumed',
    ['provider', 'type']  # anthropic/google, input/output
)

llm_cost = Counter(
    'arisp_llm_cost_usd_total',
    'LLM costs in USD',
    ['provider']
)

# Gauges
active_workers = Gauge(
    'arisp_active_workers',
    'Active worker coroutines',
    ['type']  # download, conversion, llm
)

cache_size_bytes = Gauge(
    'arisp_cache_size_bytes',
    'Cache size',
    ['cache_type']
)

# Histograms
paper_processing_duration = Histogram(
    'arisp_paper_processing_duration_seconds',
    'Paper processing time',
    buckets=[10, 30, 60, 120, 300, 600]
)

llm_extraction_duration = Histogram(
    'arisp_llm_extraction_duration_seconds',
    'LLM extraction time',
    buckets=[10, 30, 60, 120, 300]
)
```

### Monitoring Dashboards

**Grafana panels**:
1. Papers processed rate (success/fail)
2. LLM costs (daily trend)
3. Processing duration (p50, p95, p99)
4. Cache hit rate
5. Error rate by type
6. Active workers
7. Queue depth

---

## Security

**⚠️ SECURITY IS THE #1 PRIORITY ⚠️**

This section defines mandatory security requirements that cannot be compromised. Every phase MUST implement these security controls before completion.

### Security Principles

1. **Defense in Depth**: Multiple layers of security controls
2. **Least Privilege**: Minimal permissions required for each operation
3. **Zero Trust**: Validate everything, trust nothing
4. **Fail Secure**: Security failures result in denial of access
5. **Audit Everything**: All security events logged
6. **Community Safe**: Code can be shared without exposing secrets

### 1. Credential Management ⚠️ CRITICAL

**Requirements:**
- **NEVER** hardcode credentials in source code
- **NEVER** commit secrets to version control
- **ALWAYS** use environment variables or secure vaults
- **ALWAYS** validate credentials on startup

```python
# ✅ CORRECT: Use environment variables
import os
from pathlib import Path

def load_credentials() -> dict:
    """Load credentials securely from environment"""
    # Load from .env (never committed)
    from dotenv import load_dotenv
    load_dotenv()

    # Validate required credentials exist
    required = [
        "SEMANTIC_SCHOLAR_API_KEY",
        "LLM_API_KEY"
    ]

    credentials = {}
    missing = []

    for key in required:
        value = os.environ.get(key)
        if not value or len(value) < 10:
            missing.append(key)
        else:
            credentials[key] = value

    if missing:
        raise SecurityError(
            f"Missing required credentials: {', '.join(missing)}\n"
            f"Please set them in .env file (see .env.template)"
        )

    # Log that credentials loaded (but NOT the values)
    logger.info("credentials_loaded", keys=list(credentials.keys()))

    return credentials

# ❌ WRONG: Hardcoded credentials
API_KEY = "sk-1234567890abcdef"  # NEVER DO THIS!
```

**Secret Scanning:**
```yaml
# .github/workflows/security.yml
name: Secret Scanning
on: [push, pull_request]
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Scan for secrets
        uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: main
          head: HEAD
```

**Credential Rotation:**
- API keys should be rotatable without code changes
- Support multiple key formats (for smooth rotation)
- Log credential usage for audit trails

### 2. Input Validation ⚠️ CRITICAL

**Requirements:**
- **ALWAYS** validate all user inputs before processing
- **NEVER** trust user input
- **ALWAYS** use Pydantic for runtime validation
- **ALWAYS** sanitize inputs before using in shell/API calls

```python
from pydantic import BaseModel, Field, validator
import re

class SecureResearchTopic(BaseModel):
    """Research topic with comprehensive security validation"""
    query: str = Field(..., min_length=1, max_length=500)

    @validator("query")
    def validate_query_security(cls, v):
        """Prevent injection attacks"""
        v = v.strip()

        # Check for command injection patterns
        dangerous_patterns = [
            r";\s*\w+",           # Command chaining
            r"\|\s*\w+",          # Pipe to command
            r"&&",                # AND operator
            r"\|\|",              # OR operator
            r"`[^`]+`",           # Backticks
            r"\$\([^)]+\)",       # Command substitution
            r">\s*\w+",           # Output redirection
            r"<\s*\w+",           # Input redirection
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, v):
                logger.warning(
                    "input_validation_failed",
                    query=v,
                    pattern=pattern,
                    reason="Potential injection attack"
                )
                raise ValueError(
                    f"Query contains forbidden pattern that could be used for injection"
                )

        # Check for SQL injection patterns (if using database)
        sql_patterns = [
            r"'\s*(OR|AND)\s*'",
            r"--",
            r"/\*",
            r"xp_",
            r"UNION\s+SELECT",
        ]

        for pattern in sql_patterns:
            if re.search(pattern, v, re.IGNORECASE):
                raise ValueError("Query contains SQL injection pattern")

        # Enforce whitelist of allowed characters
        allowed_chars = re.compile(r'^[a-zA-Z0-9\s\-_+.,"()]+$')
        if not allowed_chars.match(v):
            raise ValueError(
                "Query contains characters outside allowed set: "
                "alphanumeric, spaces, hyphens, underscores, +.,()\""
            )

        return v

# Example usage
try:
    topic = SecureResearchTopic(query="machine learning AND $(whoami)")
except ValueError as e:
    logger.error("malicious_input_blocked", error=str(e))
    # Input blocked, attack prevented
```

### 3. Path Sanitization ⚠️ CRITICAL

**Requirements:**
- **ALWAYS** validate file paths before use
- **NEVER** trust user-provided paths
- **ALWAYS** check paths are within expected directories
- **ALWAYS** prevent directory traversal attacks

```python
from pathlib import Path
from typing import Union

class PathSanitizer:
    """Secure path validation and sanitization"""

    def __init__(self, allowed_bases: List[Path]):
        """Initialize with allowed base directories"""
        self.allowed_bases = [p.resolve() for p in allowed_bases]

    def safe_path(
        self,
        base_dir: Path,
        user_input: str,
        must_exist: bool = False
    ) -> Path:
        """Get safe path within base directory

        Prevents:
        - Directory traversal (../)
        - Absolute path injection
        - Symlink attacks

        Raises:
            SecurityError: If path is outside base_dir
            FileNotFoundError: If must_exist=True and path doesn't exist
        """
        # Normalize base directory
        base_dir = base_dir.resolve()

        # Check base directory is allowed
        if base_dir not in self.allowed_bases:
            if not any(base_dir.is_relative_to(b) for b in self.allowed_bases):
                raise SecurityError(
                    f"Base directory not in allowed list: {base_dir}"
                )

        # Remove dangerous characters
        safe_input = user_input.replace('\0', '')  # Null byte

        # Build requested path
        requested = (base_dir / safe_input).resolve()

        # Ensure it's within base directory
        try:
            requested.relative_to(base_dir)
        except ValueError:
            logger.warning(
                "path_traversal_blocked",
                base_dir=str(base_dir),
                user_input=user_input,
                resolved=str(requested)
            )
            raise SecurityError(
                f"Path traversal attempt detected: {user_input}"
            )

        # Check if symlink points outside base (symlink attack)
        if requested.is_symlink():
            real_path = requested.resolve()
            try:
                real_path.relative_to(base_dir)
            except ValueError:
                raise SecurityError(
                    f"Symlink points outside base directory: {requested}"
                )

        # Optionally check existence
        if must_exist and not requested.exists():
            raise FileNotFoundError(f"Path does not exist: {requested}")

        return requested

# Example usage
sanitizer = PathSanitizer(
    allowed_bases=[
        Path("./output"),
        Path("./cache"),
        Path("./temp")
    ]
)

# ✅ CORRECT: Validate all user paths
user_folder = request.params.get("folder")
safe_folder = sanitizer.safe_path(Path("./output"), user_folder)

# ❌ WRONG: Use user input directly
output_path = Path("./output") / user_folder  # UNSAFE!
```

### 4. Rate Limiting ⚠️ REQUIRED

**Requirements:**
- **ALWAYS** rate limit external API calls
- **ALWAYS** rate limit user actions (if exposing API)
- **ALWAYS** implement backoff on rate limit errors

```python
import asyncio
import time
from collections import deque
from datetime import datetime, timedelta

class RateLimiter:
    """Token bucket rate limiter with security logging"""

    def __init__(
        self,
        requests_per_minute: int = 100,
        burst_size: int = None
    ):
        self.rate = requests_per_minute / 60.0
        self.burst_size = burst_size or requests_per_minute
        self.tokens = self.burst_size
        self.last_update = time.time()

        # Track for abuse detection
        self.request_times = deque(maxlen=1000)

    async def acquire(self, requester_id: str = "system"):
        """Acquire token with abuse detection"""
        # Record request
        self.request_times.append(datetime.utcnow())

        # Check for abuse (>500 requests in 1 minute)
        one_min_ago = datetime.utcnow() - timedelta(minutes=1)
        recent = sum(1 for t in self.request_times if t > one_min_ago)

        if recent > 500:
            logger.warning(
                "rate_limit_abuse_detected",
                requester_id=requester_id,
                requests_per_minute=recent
            )
            # Consider blocking or alerting

        # Token bucket algorithm
        while True:
            now = time.time()
            elapsed = now - self.last_update

            # Refill bucket
            self.tokens = min(
                self.burst_size,
                self.tokens + elapsed * self.rate
            )
            self.last_update = now

            if self.tokens >= 1:
                self.tokens -= 1
                return

            # Wait for next token
            wait_time = (1 - self.tokens) / self.rate
            logger.debug(
                "rate_limit_waiting",
                requester_id=requester_id,
                wait_seconds=wait_time
            )
            await asyncio.sleep(wait_time)
```

### 5. Secrets in Version Control ⚠️ CRITICAL

**Requirements:**
- **NEVER** commit .env files
- **ALWAYS** use .env.template with placeholder values
- **ALWAYS** add .env to .gitignore
- **ALWAYS** scan for secrets before commits

```bash
# .gitignore (REQUIRED)
.env
.env.local
.env.*.local
*.key
*.pem
*.p12
credentials.json
secrets.yaml
```

```bash
# .env.template (committed to repo)
# Copy this to .env and fill in real values
SEMANTIC_SCHOLAR_API_KEY=your_key_here
LLM_API_KEY=your_key_here
```

**Pre-commit Hook:**
```bash
#!/bin/bash
# .git/hooks/pre-commit

# Check for secrets
if git diff --cached --name-only | xargs grep -l "sk-" "api-key" "secret"; then
    echo "ERROR: Potential secret found in staged files!"
    echo "Please remove secrets before committing."
    exit 1
fi

# Check for .env files
if git diff --cached --name-only | grep -q "\.env$"; then
    echo "ERROR: .env file should not be committed!"
    exit 1
fi
```

### 6. Dependency Security ⚠️ REQUIRED

**Requirements:**
- **ALWAYS** pin dependency versions
- **ALWAYS** scan dependencies for vulnerabilities
- **REGULARLY** update dependencies

```bash
# Check for vulnerabilities
pip-audit

# Update safely
pip install --upgrade pip
pip list --outdated
```

```yaml
# .github/workflows/dependency-scan.yml
name: Dependency Security Scan
on:
  schedule:
    - cron: '0 0 * * 1'  # Weekly
  push:
    paths:
      - 'requirements.txt'
jobs:
  scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: pypa/gh-action-pip-audit@v1.0.0
```

### 7. Logging Security Events ⚠️ REQUIRED

**Requirements:**
- **ALWAYS** log security-relevant events
- **NEVER** log secrets or credentials
- **ALWAYS** include context for investigation

```python
# Security event logging
logger.warning(
    "authentication_failed",
    requester_ip=request.ip,
    attempted_user=username,  # Log attempt, not password!
    timestamp=datetime.utcnow()
)

logger.error(
    "authorization_denied",
    user_id=user.id,
    requested_resource=resource,
    required_permission=permission
)

logger.info(
    "sensitive_operation",
    operation="credential_rotation",
    user_id=user.id,
    success=True
)

# ❌ WRONG: Logging secrets
logger.info(f"API key loaded: {api_key}")  # NEVER DO THIS!

# ✅ CORRECT: Log that operation happened
logger.info("api_key_loaded", key_type="semantic_scholar")
```

### Security Checklist (Required for Every Phase)

Before completing any phase, ALL items must be checked:

#### Phase Completion Security Gate
- [ ] No hardcoded credentials in source code
- [ ] All secrets loaded from environment variables
- [ ] .env file in .gitignore
- [ ] .env.template provided with placeholders
- [ ] All user inputs validated with Pydantic
- [ ] No command injection vulnerabilities
- [ ] No SQL injection vulnerabilities (if using DB)
- [ ] All file paths sanitized
- [ ] No directory traversal vulnerabilities
- [ ] Rate limiting implemented for all external APIs
- [ ] Rate limiting implemented for user actions (if applicable)
- [ ] Dependencies scanned for vulnerabilities
- [ ] No vulnerable dependencies (or documented exceptions)
- [ ] Security events logged appropriately
- [ ] No secrets in logs
- [ ] Pre-commit hooks installed
- [ ] Secret scanning configured
- [ ] Security review completed
- [ ] Penetration testing performed (Phases 3-4)

### Security Incident Response

If a security issue is discovered:

1. **Immediately** stop the affected service
2. **Rotate** all potentially compromised credentials
3. **Investigate** the scope of the breach
4. **Document** the incident
5. **Fix** the vulnerability
6. **Test** the fix
7. **Deploy** the fix
8. **Audit** for similar issues
9. **Post-mortem** to prevent recurrence

### Community Sharing Guidelines

When sharing this tool publicly:

1. **Remove** all .env files before sharing
2. **Verify** .gitignore includes all secret paths
3. **Scan** entire repository for secrets
4. **Document** required credentials in README
5. **Provide** .env.template with clear instructions
6. **Test** setup process in clean environment
7. **Review** logs to ensure no secrets leaked

---

## Autonomous Operation Architecture

### Intelligent Stopping Criteria

The system autonomously determines when research for a topic is complete using multiple strategies:

#### 1. Quantity-Based Stopping
```python
if papers_found >= stopping_criteria.max_papers:
    logger.info(
        "stopping_quantity_met",
        papers_found=papers_found,
        max_papers=stopping_criteria.max_papers
    )
    return StopReason.MAX_PAPERS_REACHED
```

#### 2. Convergence-Based Stopping
```python
class ConvergenceDetector:
    """Detects when no new quality papers are being found"""

    def should_stop(
        self,
        topic_catalog: TopicCatalogEntry,
        stopping_criteria: StoppingCriteria
    ) -> tuple[bool, str]:
        """Check if research has converged

        Convergence means: No new high-quality papers found
        in the last N runs within the convergence window.

        Returns:
            (should_stop, reason)
        """
        # Get recent runs within convergence window
        cutoff_date = datetime.utcnow() - timedelta(
            days=stopping_criteria.convergence_window
        )
        recent_runs = [
            r for r in topic_catalog.runs
            if r.date >= cutoff_date
        ]

        if len(recent_runs) < stopping_criteria.max_runs_without_new:
            return False, "Not enough recent runs to detect convergence"

        # Check last N runs for new quality papers
        runs_without_new = 0
        for run in reversed(recent_runs):
            new_quality_papers = self._count_new_quality_papers(
                run,
                topic_catalog,
                stopping_criteria.min_quality_score
            )

            if new_quality_papers == 0:
                runs_without_new += 1
            else:
                runs_without_new = 0  # Reset counter

            if runs_without_new >= stopping_criteria.max_runs_without_new:
                logger.info(
                    "convergence_detected",
                    topic=topic_catalog.topic_slug,
                    runs_without_new=runs_without_new,
                    window_days=stopping_criteria.convergence_window
                )
                return True, f"No new quality papers in {runs_without_new} runs"

        return False, f"Still finding new quality papers"

    def _count_new_quality_papers(
        self,
        run: CatalogRun,
        topic_catalog: TopicCatalogEntry,
        min_quality: float
    ) -> int:
        """Count new papers above quality threshold in this run"""
        # Get papers from this run
        run_papers = self._get_run_papers(run)

        # Filter by quality score
        quality_papers = [
            p for p in run_papers
            if p.relevance_score >= min_quality
        ]

        # Count how many are truly new (not seen in previous runs)
        previous_papers = self._get_previous_papers(topic_catalog, run.date)
        new_papers = [
            p for p in quality_papers
            if not self._is_duplicate(p, previous_papers)
        ]

        return len(new_papers)
```

#### 3. Incremental Search Strategy
```python
class IncrementalSearchService:
    """Search only for papers newer than last run"""

    async def incremental_search(
        self,
        topic: ResearchTopic,
        catalog_entry: TopicCatalogEntry
    ) -> List[PaperMetadata]:
        """Search for papers published since last run

        This prevents re-processing known papers and focuses
        on discovering truly new research.
        """
        # Get last run date
        if catalog_entry.runs:
            last_run = max(catalog_entry.runs, key=lambda r: r.date)
            since_date = last_run.date
        else:
            # First run - use topic's configured timeframe
            since_date = self._calculate_initial_date(topic.timeframe)

        # Build incremental query
        params = {
            "query": topic.query,
            "publicationDate": f"{since_date.isoformat()}:",  # Open-ended
            "limit": topic.max_papers
        }

        # Execute search
        papers = await self.discovery_service.search(params)

        logger.info(
            "incremental_search_complete",
            topic=topic.query,
            since_date=since_date,
            papers_found=len(papers)
        )

        return papers
```

### Autonomous Workflow

```
┌─────────────────────────────────────────────────┐
│         Autonomous Research Loop                │
└─────────────────────────────────────────────────┘
                    │
                    ▼
        ┌──────────────────────┐
        │ Load Configuration   │
        │ Check Stopping       │
        │ Criteria             │
        └──────────┬───────────┘
                   │
                   ▼
           ┌───────────────┐
           │ Should Stop?  │
           └───┬───────┬───┘
               │       │
           Yes │       │ No
               │       │
               ▼       ▼
         ┌─────────┐  ┌──────────────────┐
         │  Stop   │  │ Incremental      │
         │ Archive │  │ Search for       │
         │ Topic   │  │ New Papers       │
         └─────────┘  └────────┬─────────┘
                               │
                               ▼
                    ┌──────────────────┐
                    │ Filter by        │
                    │ Quality          │
                    └────────┬─────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ Check for            │
                  │ Duplicates           │
                  └────────┬─────────────┘
                           │
                           ▼
                ┌──────────────────────────┐
                │ Process New Papers       │
                │ (PDF + LLM)              │
                └────────┬─────────────────┘
                         │
                         ▼
              ┌──────────────────────────┐
              │ Update Catalog           │
              │ Update Quality Metrics   │
              └────────┬─────────────────┘
                       │
                       ▼
            ┌──────────────────────────┐
            │ Check Convergence        │
            └────────┬─────────────────┘
                     │
                     ▼
              ┌──────────────┐
              │ Sleep Until  │
              │ Next Run     │
              └──────────────┘
```

### Quality Assessment

```python
class QualityAssessor:
    """Assess research paper quality"""

    def calculate_quality_score(
        self,
        paper: PaperMetadata,
        topic: ResearchTopic
    ) -> float:
        """Calculate paper quality score (0.0 - 1.0)

        Factors:
        - Citation count (weighted by age)
        - Venue prestige
        - Relevance to query
        - Author reputation (future)
        - Recency
        """
        scores = []
        weights = []

        # Citation score (40% weight)
        citation_score = self._citation_score(paper)
        scores.append(citation_score)
        weights.append(0.4)

        # Venue score (20% weight)
        venue_score = self._venue_score(paper)
        scores.append(venue_score)
        weights.append(0.2)

        # Relevance score (30% weight)
        relevance_score = self._relevance_score(paper, topic.query)
        scores.append(relevance_score)
        weights.append(0.3)

        # Recency score (10% weight)
        recency_score = self._recency_score(paper)
        scores.append(recency_score)
        weights.append(0.1)

        # Weighted average
        total_score = sum(s * w for s, w in zip(scores, weights))

        logger.debug(
            "quality_score_calculated",
            paper_id=paper.paper_id,
            citation_score=citation_score,
            venue_score=venue_score,
            relevance_score=relevance_score,
            recency_score=recency_score,
            total_score=total_score
        )

        return total_score

    def _citation_score(self, paper: PaperMetadata) -> float:
        """Score based on citations (age-adjusted)"""
        import math

        # Age adjustment
        if paper.year:
            age_years = datetime.now().year - paper.year
            age_factor = math.sqrt(max(1, age_years))
        else:
            age_factor = 1.0

        # Normalize citations
        adjusted_citations = paper.citation_count / age_factor

        # Logarithmic scale (diminishing returns)
        score = min(1.0, math.log10(adjusted_citations + 1) / 3.0)

        return score
```

### Autonomous Operation Configuration

```yaml
# config/research_config.yaml
research_topics:
  - query: "large language models AND reasoning"
    timeframe:
      type: "recent"
      value: "7d"
    max_papers: 50

    # Autonomous operation settings
    autonomous:
      enabled: true
      search_frequency_hours: 24  # Run daily

      stopping_criteria:
        max_papers: 50              # Stop after 50 quality papers
        max_runs_without_new: 3     # Stop after 3 runs with no new papers
        min_quality_score: 0.7      # Quality threshold for "new quality paper"
        convergence_window: 14      # Check last 14 days for convergence
        enable_auto_stop: true

      incremental_search: true      # Only search for new papers

    filters:
      min_citation_count: 10
      min_year: 2020
```

## Deployment Architecture

### Standalone Deployment

```
┌──────────────────────────────────────────────┐
│           Single Host (VM/Container)         │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │         ARISP Application              │ │
│  │  - Python process                      │ │
│  │  - APScheduler (cron jobs)             │ │
│  │  - Local disk storage                  │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │    Prometheus + Grafana (optional)     │ │
│  │  - Metrics collection                  │ │
│  │  - Dashboards                          │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  Disk:                                       │
│  - /opt/arisp/output/                        │
│  - /opt/arisp/cache/                         │
│  - /opt/arisp/checkpoints/                   │
└──────────────────────────────────────────────┘
        │
        ▼
   Internet
   (APIs)
```

### Cloud Deployment (Future)

```
┌─────────────────────────────────────────────────┐
│              AWS/GCP/Azure                      │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │        Container (ECS/Cloud Run/AKS)      │ │
│  │  - ARISP application                      │ │
│  │  - Health check endpoint                  │ │
│  └───────────────────────────────────────────┘ │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │     Managed Storage (S3/GCS/Blob)         │ │
│  │  - Research outputs                       │ │
│  │  - PDF archives                           │ │
│  └───────────────────────────────────────────┘ │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │    Scheduler (EventBridge/Cloud Scheduler)│ │
│  │  - Daily cron triggers                    │ │
│  └───────────────────────────────────────────┘ │
│                                                 │
│  ┌───────────────────────────────────────────┐ │
│  │    Monitoring (CloudWatch/Stackdriver)    │ │
│  │  - Logs aggregation                       │ │
│  │  - Metrics collection                     │ │
│  │  - Alerting                               │ │
│  └───────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

---

## Gap Resolution Matrix

This table shows how each identified architectural gap is addressed:

| Gap ID | Gap Description | Resolution | Phase | Component |
|--------|----------------|------------|-------|-----------|
| **1** | Data Models & Type Safety | Pydantic models for all data structures | Phase 1 | `src/models/` |
| **2** | No Concurrency Model | AsyncIO producer-consumer with semaphores | Phase 3 | `ConcurrentPipeline` |
| **3** | No Resilience Strategy | Retry (tenacity), circuit breaker, checkpoints | Phase 2-3 | `infrastructure/` |
| **4** | Hardcoded Extraction Targets | Configurable `ExtractionTarget` per topic | Phase 2 | `ExtractionTarget` model |
| **5** | No Observability | Structlog + Prometheus + correlation IDs | Phase 4 | `observability/` |
| **6** | Missing Storage Strategy | Retention policy, compression, quotas | Phase 3 | `StorageManager` |
| **7** | No Cost Controls | `CostLimits` model + tracking + alerts | Phase 2 | `LLMService` |
| **8** | Insufficient Error Handling | Error taxonomy, custom exceptions | Phase 1-2 | `exceptions.py` |
| **9** | No Incremental Processing | Checkpoint service + catalog tracking | Phase 3 | `CheckpointService` |
| **10** | Missing Paper Quality Filters | `PaperFilter` model + filter service | Phase 3 | `FilterService` |
| **11** | No Scheduling System | APScheduler integration | Phase 4 | `scheduler.py` |
| **12** | Missing CLI Framework | Typer with type safety | Phase 1 | `cli.py` |
| **13** | No Testing Strategy | Pytest + coverage target 99%+ | All Phases | `tests/` |
| **14** | Security Considerations | Input validation, path sanitization, rate limiting | Phase 1-4 | Multiple |
| **15** | No Semantic Search | (Future) Vector embeddings | Post-Phase 4 | N/A |
| **16** | Missing Metadata Enrichment | (Future) Extended metadata capture | Post-Phase 4 | N/A |

---

## References

### External Documentation
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [Semantic Scholar API](https://api.semanticscholar.org/)
- [marker-pdf Documentation](https://github.com/VikParuchuri/marker)
- [Anthropic API](https://docs.anthropic.com/)
- [Google AI API](https://ai.google.dev/)

### Internal Documentation
- [Architecture Review](./ARCHITECTURE_REVIEW.md) - Gap analysis
- [Phased Delivery Plan](./PHASED_DELIVERY_PLAN.md) - Implementation roadmap
- [Phase 1 Specification](./specs/PHASE_1_SPEC.md)
- [Phase 2 Specification](./specs/PHASE_2_SPEC.md)
- [Phase 3 Specification](./specs/PHASE_3_SPEC.md)
- [Phase 4 Specification](./specs/PHASE_4_SPEC.md)

---

**Document Control**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-23 | Principal Engineering Team | Initial architecture design |

