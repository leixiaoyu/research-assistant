# Phase 1: Foundation & Core Pipeline (MVP)
**Version:** 2.2
**Status:** Approved - OpenSpec Compliant
**Timeline:** 2 weeks

---

## 1. Executive Summary

Phase 1 establishes the secure, production-grade foundation for the **Automated Research Ingestion & Synthesis Pipeline (ARISP)**. This phase delivers a working end-to-end pipeline capable of discovering research papers from Semantic Scholar, organizing them intelligently, and generating structured markdown output—all with security as the #1 priority.

---

## 2. Requirements

### Requirement: Configurable Research Topics
The system SHALL allow users to define multiple research topics via a YAML configuration file to enable flexible research queries without code changes.

#### Scenario: Load Valid Configuration
**Given** a `research_config.yaml` file with a valid list of topics
**When** the pipeline is initialized
**Then** the system SHALL parse all topics, including query strings, timeframes, and max paper limits.

#### Scenario: Reject Invalid Configuration
**Given** a `research_config.yaml` file with missing required fields (e.g., empty query)
**When** the pipeline attempts to load the config
**Then** the system SHALL raise a validation error and terminate with a descriptive message.

### Requirement: Flexible Time Horizons
The system SHALL support filtering research papers by various time horizons to allow both current awareness and historical analysis.

#### Scenario: Recent Timeframe
**Given** a topic configured with `timeframe: type: recent, value: 48h`
**When** the discovery service queries the API
**Then** it SHALL request papers published within the last 48 hours.

#### Scenario: Since Year Timeframe
**Given** a topic configured with `timeframe: type: since_year, value: 2023`
**When** the discovery service queries the API
**Then** it SHALL request papers published in or after 2023.

#### Scenario: Date Range Timeframe
**Given** a topic configured with a specific start and end date
**When** the discovery service queries the API
**Then** it SHALL request papers published strictly within that range.

### Requirement: Intelligent Topic Organization
The system SHALL organize research outputs by topic and detect duplicate queries to prevent redundant work.

#### Scenario: Detect Duplicate Topic
**Given** a new topic query that matches an existing topic (case-insensitive, normalized)
**When** the catalog service processes the topic
**Then** it SHALL identify the existing topic folder and reuse it instead of creating a new one.

#### Scenario: Create New Topic Folder
**Given** a unique topic query "Deep Learning"
**When** the catalog service processes the topic
**Then** it SHALL generate a filesystem-safe slug (e.g., `deep-learning`) and create a corresponding output directory.

### Requirement: Secure Credential Management
The system SHALL manage sensitive credentials securely, preventing any exposure in source code or logs.

#### Scenario: Load API Key from Env
**Given** a `.env` file containing `SEMANTIC_SCHOLAR_API_KEY`
**When** the configuration manager loads
**Then** it SHALL read the key into memory.

#### Scenario: Missing API Key
**Given** no API key is present in environment variables
**When** the system starts
**Then** it SHALL terminate immediately with a security error message.

---

## 3. Technical Specifications

### 3.1 Directory Structure
```
src/
├── __init__.py
├── cli.py                     # CLI Entry point
├── config/
│   ├── __init__.py
│   └── settings.py            # Global constant settings
├── models/                    # Pydantic Data Models
│   ├── __init__.py
│   ├── config.py              # ResearchConfig, Timeframe
│   ├── paper.py               # PaperMetadata, Author
│   └── catalog.py             # Catalog, TopicCatalogEntry
├── services/                  # Business Logic Services
│   ├── __init__.py
│   ├── config_manager.py      # Infrastructure: Config loading
│   ├── discovery_service.py   # Service: Semantic Scholar API
│   └── catalog_service.py     # Service: Deduplication & Org
├── output/
│   ├── __init__.py
│   └── markdown_generator.py  # Presentation logic
└── utils/
    ├── __init__.py
    ├── logging.py             # Structlog setup
    ├── security.py            # PathSanitizer, InputValidation
    └── validators.py
```

### 3.2 Data Models

#### Configuration (`models/config.py`)
```python
from enum import Enum
from pydantic import BaseModel, Field, validator
from typing import Literal, Union, List
from datetime import date

class TimeframeType(str, Enum):
    RECENT = "recent"
    SINCE_YEAR = "since_year"
    DATE_RANGE = "date_range"

class TimeframeRecent(BaseModel):
    type: Literal[TimeframeType.RECENT] = TimeframeType.RECENT
    value: str = Field(..., pattern=r'^\d+[hd])

class TimeframeSinceYear(BaseModel):
    type: Literal[TimeframeType.SINCE_YEAR] = TimeframeType.SINCE_YEAR
    value: int = Field(..., ge=1900, le=2100)

class TimeframeDateRange(BaseModel):
    type: Literal[TimeframeType.DATE_RANGE] = TimeframeType.DATE_RANGE
    start_date: date
    end_date: date

Timeframe = Union[TimeframeRecent, TimeframeSinceYear, TimeframeDateRange]

class ResearchTopic(BaseModel):
    query: str = Field(..., min_length=1)
    timeframe: Timeframe
    max_papers: int = Field(50, ge=1)
```

#### Paper Metadata (`models/paper.py`)
```python
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime

class Author(BaseModel):
    name: str
    author_id: Optional[str] = None

class PaperMetadata(BaseModel):
    paper_id: str
    title: str
    abstract: Optional[str]
    url: HttpUrl
    publication_date: Optional[datetime]
    authors: List[Author] = []
    open_access_pdf: Optional[HttpUrl]
    relevance_score: float = 0.0
```

### 3.3 Security Mandates
- **Credential Management:** `DiscoveryService` SHALL load API keys strictly from environment variables.
- **Input Validation:** All Pydantic models SHALL use strict validators.
- **Path Sanitization:** `ConfigManager` and `CatalogService` SHALL use `PathSanitizer` to prevent directory traversal.

---

## 4. Verification Plan

1.  **Automated Tests:**
    - Unit tests for all Models (validation logic).
    - Unit tests for `DiscoveryService` (mocked API).
    - Unit tests for `CatalogService` (deduplication logic).
    - **Coverage:** Must exceed 80%.

2.  **Manual Verification:**
    - Verify "Happy Path": Config load -> Search -> Catalog Update -> Markdown Gen.
    - Verify "Security Path": Injection attempts in config, missing API keys.