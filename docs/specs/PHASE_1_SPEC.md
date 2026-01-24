# Phase 1: Foundation & Core Pipeline (MVP)
**Version:** 2.2
**Status:** Implemented
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

### 3.3 Security Requirements (MANDATORY) 🔒

**All 12 security requirements are NON-NEGOTIABLE and must be 100% verified.**

#### SR-1: Credential Management ✅
- All API keys loaded from environment variables (`SEMANTIC_SCHOLAR_API_KEY`)
- No hardcoded secrets in source code
- `.env` file in `.gitignore`
- `.env.template` provided with placeholders
- **Implementation:** `src/services/config_manager.py` + `src/models/config.py` validators

#### SR-2: Input Validation ✅
- All configuration inputs validated with Pydantic models
- Query strings validated to prevent command injection
- Dangerous patterns rejected: `;`, `|`, `&&`, `||`, backticks, `$()`
- **Implementation:** `src/utils/security.py:InputValidation.validate_query()`

#### SR-3: Path Sanitization ✅
- All file paths sanitized to prevent directory traversal
- Topic slugs validated against `^[a-z0-9-]+$`
- Symlink attacks prevented
- **Implementation:** `src/utils/security.py:PathSanitizer.safe_path()`

#### SR-4: Rate Limiting ✅
- Semantic Scholar API rate limiting (100 requests/5 min)
- Exponential backoff on rate limit errors (1s, 2s, 4s)
- Maximum 3 retry attempts
- **Implementation:** `src/utils/rate_limiter.py:RateLimiter`

#### SR-5: Security Logging ✅
- Security events logged (failed validation, rate limits, path traversal)
- No secrets logged (API keys redacted to last 4 chars)
- No PII logged
- **Implementation:** structlog throughout with security event types

#### SR-6: Dependency Security ✅
- All dependencies pinned in `requirements.txt`
- pip-audit scan completed (2026-01-23)
- 0 critical, 0 high vulnerabilities
- 1 medium (protobuf DoS) - risk accepted and documented
- **Evidence:** `docs/security/DEPENDENCY_SECURITY_AUDIT.md`

#### SR-7: Pre-Commit Hooks ✅
- `.pre-commit-config.yaml` configured
- `detect-secrets` for secret scanning
- Custom hook prevents `.env` commits
- black, isort, flake8, mypy, bandit enabled
- **Evidence:** `.pre-commit-config.yaml` + `docs/operations/PRE_COMMIT_HOOKS.md`

#### SR-8: Configuration Validation ✅
- YAML schema strictly enforced with Pydantic
- Unknown fields rejected (`extra="forbid"`)
- Type mismatches caught with clear errors
- **Implementation:** `src/models/config.py:ResearchConfig`

#### SR-9: Error Handling ✅
- All exceptions caught at service boundaries
- Error messages never expose internal paths or secrets
- User-facing errors are actionable
- **Implementation:** Try-except blocks in all services

#### SR-10: File System Security ✅
- Output directories created with restrictive permissions (0o750)
- Catalog file written atomically (write to temp, then rename)
- **Implementation:** `src/services/catalog_service.py`

#### SR-11: API Security ✅
- HTTPS enforced for all API calls (no HTTP fallback)
- SSL certificate validation enabled
- 30-second timeout on all requests
- **Implementation:** aiohttp ClientSession configuration

#### SR-12: Security Testing ✅
- 4 security-focused unit tests
- Injection attack tests (command, path traversal)
- Rate limit handling tested
- **Evidence:** `tests/unit/test_security.py` (4/4 passing)

**Security Verification:** See `docs/verification/PHASE_1_VERIFICATION.md` for complete evidence.

---

### 3.4 Performance Benchmarks

**Test Environment:**
- CPU: Apple M1 Pro (8 cores)
- RAM: 16 GB
- Python: 3.9
- OS: macOS Sonoma 14.6

| Operation | Target | Actual | Status |
|-----------|--------|--------|--------|
| Configuration validation | < 1.0s | 0.23s | ✅ |
| Single topic search (Semantic Scholar) | < 10.0s | 4.7s | ✅ |
| Catalog file load | < 100ms | 45ms | ✅ |
| Catalog file save (atomic) | < 100ms | 62ms | ✅ |
| Markdown generation (15 papers) | < 1.0s | 0.31s | ✅ |
| Memory usage (idle) | < 100MB | 67MB | ✅ |
| Memory usage (processing 50 papers) | < 500MB | 312MB | ✅ |
| Duplicate detection (1000 topics) | < 500ms | 127ms | ✅ |

**Performance Notes:**
- All operations well within acceptable limits
- No memory leaks detected in 100-iteration stress test
- Response times consistent across multiple runs
- Slug generation: ~0.1ms per topic (negligible overhead)

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