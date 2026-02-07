# Phase 3.4: Quality-First Paper Discovery with PDF Availability Tracking
**Version:** 2.1
**Status:** Approved - Ready for Implementation
**Timeline:** 3-5 days
**Dependencies:**
- Phase 3.2 Complete (Semantic Scholar Provider Activation)
- Semantic Scholar API key available

---

## Architecture Reference

This phase enhances the discovery pipeline to prioritize paper quality while tracking PDF availability, as defined in [SYSTEM_ARCHITECTURE.md §5.2 Discovery Service](../SYSTEM_ARCHITECTURE.md#core-components).

**Architectural Gaps Addressed:**
- Gap: No quality-based ranking of discovered papers
- Gap: No visibility into PDF availability before processing
- Gap: Low actionable paper rate in research briefs

**Components Modified:**
- Discovery Layer: `SemanticScholarProvider`, `ArxivProvider`
- Models: `PaperMetadata` (add quality score fields)
- Filter Service: Quality ranking integration

**Coverage Targets:**
- Quality scoring logic: 100%
- PDF availability tracking: 100%
- Provider enhancements: 100%

---

## 1. Executive Summary

Phase 3.4 implements a **Quality-First Discovery Strategy** that ranks papers by academic quality metrics first, then provides PDF availability as metadata for downstream processing decisions.

**Key Insight:** Filtering for open access PDFs can bias toward lower-quality papers (preprints, unfunded research). Instead, we discover the BEST papers first, then let the user/pipeline decide how to handle papers without PDFs.

**What This Phase Is:**
- Quality-based paper ranking (citations, venue, recency)
- PDF availability tracking and reporting
- Clear separation of quality discovery vs PDF processing
- Enhanced metrics and visibility

**What This Phase Is NOT:**
- Filtering out high-quality papers due to PDF unavailability
- Changing the fundamental discovery approach
- Compromising research quality for PDF convenience

---

## 2. Problem Statement

### 2.1 Original Problem
Daily automation found 0 papers with downloadable PDFs from Semantic Scholar.

### 2.2 Naive Solution (Rejected)
Filter for open access PDFs first → **Biases toward lower-quality papers**

### 2.3 Quality Concerns with PDF-First Approach

| Bias Risk | Impact |
|-----------|--------|
| **Preprint bias** | ArXiv papers not peer-reviewed, may contain errors |
| **Recency bias** | Newer papers more likely OA, but less validated by community |
| **Venue exclusion** | ACL, EMNLP, NeurIPS papers often paywalled 6-12 months |
| **Citation blindness** | Seminal highly-cited papers often behind paywalls |
| **Funding bias** | Well-funded institutions pay OA fees; smaller labs can't |

### 2.4 Revised Approach: Quality First, PDF Optional

**Strategy:** Discover the highest-quality papers first, then track and report PDF availability as metadata. Let the pipeline make informed decisions about what to process.

**Benefits:**
- No quality degradation in discovery
- Full visibility into PDF availability
- Informed processing decisions
- Ability to generate "quality briefs" even without full PDF extraction

---

## 3. Solution Design

### 3.1 Quality-First Discovery Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    DISCOVERY PHASE                               │
│  1. Query provider for papers (no PDF filter)                   │
│  2. Retrieve quality metadata (citations, venue, date)          │
│  3. Score papers by quality metrics                             │
│  4. Return top N papers ranked by quality                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AVAILABILITY CHECK                            │
│  1. For each paper, check open_access_pdf field                 │
│  2. Categorize: has_pdf, no_pdf, unknown                        │
│  3. Log PDF availability statistics                             │
│  4. Add pdf_available flag to PaperMetadata                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PROCESSING DECISION                           │
│  Papers WITH PDF: Full extraction pipeline                      │
│  Papers WITHOUT PDF:                                            │
│    Option A: Skip (current behavior)                            │
│    Option B: Generate abstract-only brief                       │
│    Option C: Try alternate PDF sources (future)                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Quality Scoring Algorithm

```python
def calculate_quality_score(paper: PaperMetadata) -> float:
    """
    Calculate composite quality score (0-100).

    Weights:
    - Citation impact: 40%
    - Venue reputation: 30%
    - Recency boost: 20%
    - Completeness: 10%
    """
    score = 0.0

    # Citation impact (40 points max)
    # Log scale: 1 citation = 5pts, 10 = 15pts, 100 = 25pts, 1000 = 35pts, 10000 = 40pts
    if paper.citation_count > 0:
        citation_score = min(40, 5 * math.log10(paper.citation_count + 1) * 2)
        score += citation_score

    # Influential citations bonus (within citation score)
    if paper.influential_citation_count > 0:
        score += min(5, paper.influential_citation_count * 0.5)

    # Venue reputation (30 points max)
    venue_scores = {
        "ACL": 30, "EMNLP": 30, "NAACL": 28,
        "NeurIPS": 30, "ICML": 30, "ICLR": 28,
        "CVPR": 28, "ICCV": 28,
        "Nature": 30, "Science": 30,
        "TACL": 25, "CL": 25,
        "ArXiv": 10,  # Preprint - lower score
    }
    venue = paper.venue or ""
    for v, pts in venue_scores.items():
        if v.lower() in venue.lower():
            score += pts
            break
    else:
        score += 15  # Unknown venue default

    # Recency boost (20 points max)
    # Papers < 1 year: 20pts, < 2 years: 15pts, < 5 years: 10pts, older: 5pts
    if paper.publication_date:
        age_days = (datetime.utcnow() - paper.publication_date).days
        if age_days < 365:
            score += 20
        elif age_days < 730:
            score += 15
        elif age_days < 1825:
            score += 10
        else:
            score += 5
    else:
        score += 10  # Unknown date default

    # Completeness (10 points max)
    if paper.abstract:
        score += 5
    if paper.authors:
        score += 3
    if paper.doi:
        score += 2

    return min(100, score)
```

### 3.3 Provider Comparison: ArXiv vs Semantic Scholar

| Aspect | ArXiv | Semantic Scholar |
|--------|-------|------------------|
| **PDF Availability** | ~100% | ~5% (recent papers) |
| **Peer Review Status** | None (preprints) | Mixed (includes published) |
| **Citation Data** | None | Yes (key quality signal) |
| **Venue Information** | "ArXiv" only | Yes (conferences, journals) |
| **Coverage** | 2.4M papers (CS/Physics/Math) | 200M+ papers (all fields) |
| **Quality Ranking** | By date only | By citations possible |
| **Best For** | Latest preprints with PDFs | Quality-ranked published research |

### 3.4 Configuration Options

```yaml
research_topics:
  - query: "large language model translation"
    max_papers: 20
    provider: "semantic_scholar"

    # NEW: Quality-first settings
    quality_ranking: true           # Enable quality scoring (default: true)
    min_quality_score: 0            # Minimum score threshold (0-100)

    # PDF handling strategy
    pdf_strategy: "quality_first"   # NEW OPTION
    # Options:
    # - "quality_first" (default): Rank by quality, track PDF availability
    # - "pdf_required": Only include papers with PDFs (may reduce quality)
    # - "arxiv_supplement": Add ArXiv results to fill PDF gaps

    # ArXiv supplement threshold (when pdf_strategy: "arxiv_supplement")
    arxiv_supplement_threshold: 0.5  # Trigger ArXiv if PDF rate below 50%

    # What to do with papers without PDFs
    no_pdf_action: "include_metadata"  # NEW OPTION
    # Options:
    # - "include_metadata" (default): Include in brief with abstract only
    # - "skip": Exclude from brief entirely
    # - "flag_for_manual": Mark for manual PDF acquisition
```

---

## 4. Requirements

### REQ-3.4.1: Quality Scoring Implementation
The discovery service SHALL score papers by academic quality metrics.

#### Scenario: Quality Score Calculation
**Given** a paper with citation count, venue, and publication date
**When** the quality score is calculated
**Then** it SHALL:
- Apply weighted scoring (citations 40%, venue 30%, recency 20%, completeness 10%)
- Return a score between 0 and 100
- Handle missing fields gracefully with defaults
- Log scoring breakdown at DEBUG level

#### Scenario: Quality-Based Ranking
**Given** a search returns multiple papers
**When** results are processed
**Then** it SHALL:
- Calculate quality score for each paper
- Sort results by quality score (highest first)
- Store quality_score in PaperMetadata
- Return top N papers by quality

### REQ-3.4.2: PDF Availability Tracking
The discovery service SHALL track and report PDF availability separately from quality.

#### Scenario: PDF Availability Check
**Given** papers returned from Semantic Scholar
**When** results are processed
**Then** it SHALL:
- Check `openAccessPdf` field for each paper
- Set `pdf_available: bool` in PaperMetadata
- NOT filter out papers missing PDFs (unless explicitly configured)
- Log PDF availability statistics

#### Scenario: PDF Availability Reporting
**Given** a search completes with N papers
**When** results are logged
**Then** it SHALL report:
- Total papers found
- Papers with PDF available
- Papers without PDF
- PDF availability percentage
- Average quality score of papers with/without PDFs

### REQ-3.4.3: Configurable PDF Strategy
The system SHALL support multiple PDF handling strategies.

#### Scenario: Quality First Strategy (Default)
**Given** `pdf_strategy: "quality_first"`
**When** search executes
**Then** it SHALL:
- Search without PDF filter
- Rank by quality
- Include all papers regardless of PDF availability
- Track PDF availability as metadata

#### Scenario: PDF Required Strategy
**Given** `pdf_strategy: "pdf_required"`
**When** search executes
**Then** it SHALL:
- Search with PDF filter (Semantic Scholar: `openAccessPdf` param)
- Warn that quality may be reduced
- Return only papers with PDFs

#### Scenario: ArXiv Supplement Strategy
**Given** `pdf_strategy: "arxiv_supplement"`
**When** search executes
**Then** it SHALL:
- First query Semantic Scholar for quality papers
- If PDF availability < `arxiv_supplement_threshold` (default 0.5), supplement with ArXiv results
- Merge and deduplicate results
- Prefer Semantic Scholar metadata when duplicate found
- Log threshold and actual PDF rate for observability

### REQ-3.4.4: No-PDF Paper Handling
The system SHALL handle papers without PDFs according to configuration.

#### Scenario: Include Metadata (Default)
**Given** `no_pdf_action: "include_metadata"`
**When** generating research brief
**Then** it SHALL:
- Include paper in brief with title, abstract, authors, venue
- Mark as "Abstract Only - Full PDF Unavailable"
- Skip LLM extraction step
- Include in paper count statistics

#### Scenario: Skip Papers Without PDF
**Given** `no_pdf_action: "skip"`
**When** generating research brief
**Then** it SHALL:
- Exclude papers without PDFs from brief
- Log skipped papers with reasons
- Report "X papers skipped (no PDF)"

#### Scenario: Flag for Manual Acquisition
**Given** `no_pdf_action: "flag_for_manual"`
**When** generating research brief
**Then** it SHALL:
- Include paper in brief with metadata
- Add "ACTION REQUIRED: PDF needs manual acquisition" flag
- Generate a separate list of papers needing PDFs
- Include DOI/URL for manual lookup

---

## 5. Technical Design

### 5.1 Model Changes

#### New Enum: PDFStrategy

```python
# src/models/config.py

class PDFStrategy(str, Enum):
    """Strategy for handling PDF availability in discovery."""
    QUALITY_FIRST = "quality_first"      # Default: rank by quality, track PDF
    PDF_REQUIRED = "pdf_required"        # Only papers with PDFs
    ARXIV_SUPPLEMENT = "arxiv_supplement"  # Fill PDF gaps with ArXiv

class NoPDFAction(str, Enum):
    """What to do with papers that don't have PDFs."""
    INCLUDE_METADATA = "include_metadata"  # Include with abstract only
    SKIP = "skip"                          # Exclude from brief
    FLAG_FOR_MANUAL = "flag_for_manual"    # Mark for manual acquisition
```

#### Updated PaperMetadata Model

```python
# src/models/paper.py

class PaperMetadata(BaseModel):
    # ... existing fields ...

    # NEW: Quality and availability tracking
    quality_score: float = 0.0           # Calculated quality score (0-100)
    pdf_available: bool = False          # Whether PDF is available
    pdf_source: Optional[str] = None     # Source of PDF (open_access, arxiv, etc.)
```

#### Updated ResearchTopic Model

```python
# src/models/config.py

class ResearchTopic(BaseModel):
    # ... existing fields ...

    # NEW: Quality-first settings
    quality_ranking: bool = True
    min_quality_score: float = 0.0
    pdf_strategy: PDFStrategy = PDFStrategy.QUALITY_FIRST
    no_pdf_action: NoPDFAction = NoPDFAction.INCLUDE_METADATA

    # ArXiv supplement settings (for ARXIV_SUPPLEMENT strategy)
    arxiv_supplement_threshold: float = 0.5  # Trigger ArXiv if PDF rate below this
```

### 5.2 Externalized Venue Scores (Per Review Feedback)

Venue scores are externalized to a YAML file for domain flexibility. Researchers in different fields (Biology, Physics, Medicine) can customize without code changes.

```yaml
# src/data/venue_scores.yaml

# Default venue reputation scores (0-30 scale)
# Higher = more prestigious venue
default_score: 15

venues:
  # Top NLP venues
  acl: 30
  emnlp: 30
  naacl: 28
  eacl: 25
  tacl: 25
  computational linguistics: 25

  # Top ML venues
  neurips: 30
  icml: 30
  iclr: 28

  # Top CV venues
  cvpr: 28
  iccv: 28
  eccv: 26

  # Top journals
  nature: 30
  science: 30
  cell: 30
  jmlr: 25
  pami: 25

  # Preprints (lower quality signal - not peer-reviewed)
  arxiv: 10
  biorxiv: 10
  medrxiv: 10

  # Biology/Medicine (example extension)
  # lancet: 30
  # nejm: 30
  # plos one: 20
```

### 5.3 Quality Scorer Service

```python
# src/services/quality_scorer.py

import math
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import structlog
import yaml

from src.models.paper import PaperMetadata

logger = structlog.get_logger()

# Default path for venue scores
DEFAULT_VENUE_SCORES_PATH = Path(__file__).parent.parent / "data" / "venue_scores.yaml"


def load_venue_scores(path: Optional[Path] = None) -> tuple[Dict[str, int], int]:
    """Load venue scores from YAML file.

    Args:
        path: Path to venue scores YAML. Uses default if None.

    Returns:
        Tuple of (venue_scores dict, default_score)
    """
    scores_path = path or DEFAULT_VENUE_SCORES_PATH

    if not scores_path.exists():
        logger.warning("venue_scores_file_not_found", path=str(scores_path))
        return {}, 15  # Fallback defaults

    with open(scores_path) as f:
        data = yaml.safe_load(f)

    venues = {k.lower(): v for k, v in data.get("venues", {}).items()}
    default = data.get("default_score", 15)

    logger.info("venue_scores_loaded", count=len(venues), default=default)
    return venues, default


class QualityScorer:
    """Calculate quality scores for papers."""

    def __init__(
        self,
        citation_weight: float = 0.40,
        venue_weight: float = 0.30,
        recency_weight: float = 0.20,
        completeness_weight: float = 0.10,
        venue_scores_path: Optional[Path] = None,
    ):
        self.citation_weight = citation_weight
        self.venue_weight = venue_weight
        self.recency_weight = recency_weight
        self.completeness_weight = completeness_weight

        # Load externalized venue scores
        self.venue_scores, self.default_venue_score = load_venue_scores(venue_scores_path)

    def score(self, paper: PaperMetadata) -> float:
        """Calculate composite quality score (0-100)."""
        scores = {
            "citation": self._citation_score(paper),
            "venue": self._venue_score(paper),
            "recency": self._recency_score(paper),
            "completeness": self._completeness_score(paper),
        }

        total = (
            scores["citation"] * self.citation_weight +
            scores["venue"] * self.venue_weight +
            scores["recency"] * self.recency_weight +
            scores["completeness"] * self.completeness_weight
        )

        # Normalize to 0-100
        final_score = min(100, total * 100)

        logger.debug(
            "quality_score_calculated",
            paper_id=paper.paper_id,
            scores=scores,
            final=final_score,
        )

        return final_score

    def _citation_score(self, paper: PaperMetadata) -> float:
        """Citation impact score (0-1)."""
        if paper.citation_count <= 0:
            return 0.0

        # Log scale: 1=0.17, 10=0.50, 100=0.83, 1000=1.0
        score = math.log10(paper.citation_count + 1) / 3

        # Influential citation bonus
        if paper.influential_citation_count > 0:
            score += min(0.1, paper.influential_citation_count * 0.01)

        return min(1.0, score)

    def _venue_score(self, paper: PaperMetadata) -> float:
        """Venue reputation score (0-1)."""
        venue = (paper.venue or "").lower()

        # Case-insensitive partial matching (per review feedback)
        for v, pts in self.venue_scores.items():
            if v in venue:
                return pts / 30  # Normalize to 0-1

        return self.default_venue_score / 30

    def _recency_score(self, paper: PaperMetadata) -> float:
        """Recency score (0-1)."""
        if not paper.publication_date:
            return 0.5  # Unknown date default

        age_days = (datetime.utcnow() - paper.publication_date).days

        if age_days < 365:      # < 1 year
            return 1.0
        elif age_days < 730:    # < 2 years
            return 0.75
        elif age_days < 1825:   # < 5 years
            return 0.50
        else:
            return 0.25

    def _completeness_score(self, paper: PaperMetadata) -> float:
        """Metadata completeness score (0-1)."""
        score = 0.0

        if paper.abstract:
            score += 0.5
        if paper.authors:
            score += 0.3
        if paper.doi:
            score += 0.2

        return score

    def rank_papers(
        self,
        papers: List[PaperMetadata],
        min_score: float = 0.0,
    ) -> List[PaperMetadata]:
        """Score and rank papers by quality."""
        scored = []

        for paper in papers:
            paper.quality_score = self.score(paper)
            if paper.quality_score >= min_score:
                scored.append(paper)

        # Sort by quality (highest first)
        scored.sort(key=lambda p: p.quality_score, reverse=True)

        logger.info(
            "papers_ranked_by_quality",
            total=len(papers),
            above_threshold=len(scored),
            min_score=min_score,
        )

        return scored
```

### 5.3 Updated SemanticScholarProvider

```python
# src/services/providers/semantic_scholar.py (search method update)

async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
    """Search with quality-first strategy."""

    # Execute search based on PDF strategy
    if topic.pdf_strategy == PDFStrategy.PDF_REQUIRED:
        papers = await self._search_with_pdf_filter(topic)
    else:
        papers = await self._search_standard(topic)

    # Track PDF availability
    for paper in papers:
        paper.pdf_available = bool(paper.open_access_pdf)
        if paper.pdf_available:
            paper.pdf_source = "open_access"

    # Log PDF availability metrics
    pdf_count = sum(1 for p in papers if p.pdf_available)
    logger.info(
        "pdf_availability_check",
        total_papers=len(papers),
        with_pdf=pdf_count,
        without_pdf=len(papers) - pdf_count,
        pdf_rate=f"{(pdf_count/len(papers)*100):.1f}%" if papers else "N/A",
        provider="semantic_scholar",
    )

    return papers

async def _search_with_pdf_filter(self, topic: ResearchTopic) -> List[PaperMetadata]:
    """Search with openAccessPdf filter (for PDF_REQUIRED strategy)."""
    params = self._build_query_params(topic, topic.query)
    params["openAccessPdf"] = ""  # Enable filter

    logger.warning(
        "pdf_required_mode_active",
        note="Quality may be reduced - only papers with open access PDFs returned",
    )

    # ... execute search with filter ...
```

### 5.4 Enhanced Markdown Generator

```python
# src/output/enhanced_generator.py (addition)

def _format_paper_entry(self, paper: PaperMetadata, has_extraction: bool) -> str:
    """Format a single paper entry with quality and PDF status."""

    lines = []
    lines.append(f"### {paper.title}")
    lines.append("")

    # Quality badge
    quality_badge = self._quality_badge(paper.quality_score)
    pdf_badge = "📄 PDF Available" if paper.pdf_available else "📋 Abstract Only"

    lines.append(f"**Quality:** {quality_badge} | **Status:** {pdf_badge}")
    lines.append("")

    # Metadata
    if paper.authors:
        authors_str = ", ".join(a.name for a in paper.authors[:5])
        if len(paper.authors) > 5:
            authors_str += f" (+{len(paper.authors) - 5} more)"
        lines.append(f"**Authors:** {authors_str}")

    if paper.venue:
        lines.append(f"**Venue:** {paper.venue}")

    if paper.citation_count:
        lines.append(f"**Citations:** {paper.citation_count}")

    lines.append(f"**Link:** [{paper.url}]({paper.url})")
    lines.append("")

    # Abstract
    if paper.abstract:
        lines.append("**Abstract:**")
        lines.append(f"> {paper.abstract[:500]}...")
        lines.append("")

    # PDF status message
    if not paper.pdf_available:
        lines.append("> ⚠️ **Note:** Full PDF not available via open access.")
        lines.append(f"> DOI: {paper.doi}" if paper.doi else "> Manual lookup may be required.")
        lines.append("")

    return "\n".join(lines)

def _quality_badge(self, score: float) -> str:
    """Generate quality badge based on score."""
    if score >= 80:
        return f"⭐⭐⭐ Excellent ({score:.0f})"
    elif score >= 60:
        return f"⭐⭐ Good ({score:.0f})"
    elif score >= 40:
        return f"⭐ Fair ({score:.0f})"
    else:
        return f"○ Low ({score:.0f})"
```

---

## 6. Implementation Tasks

### Task 1: Create Externalized Venue Scores File (Per Review)
**File:** `src/data/venue_scores.yaml`
**Effort:** 30 minutes

- Create `src/data/` directory
- Create `venue_scores.yaml` with default CS/AI venues
- Include comments for extensibility (Biology, Medicine examples)
- Document score scale (0-30)

**Tests Required:**
- Test YAML loading
- Test fallback when file missing
- Test case-insensitive matching

### Task 2: Create QualityScorer Service
**File:** `src/services/quality_scorer.py`
**Effort:** 2 hours

- Implement `QualityScorer` class with weighted scoring
- Load venue scores from YAML file (externalized)
- Implement `rank_papers()` method
- Add comprehensive logging

**Tests Required:**
- Test scoring with various citation counts
- Test venue recognition (case-insensitive partial match)
- Test recency scoring
- Test edge cases (missing fields)

### Task 3: Add New Config Enums and Model Fields
**Files:** `src/models/config.py`, `src/models/paper.py`
**Effort:** 1 hour

- Add `PDFStrategy` and `NoPDFAction` enums
- Add `quality_score`, `pdf_available`, `pdf_source` to PaperMetadata
- Add config fields to ResearchTopic
- Update validation

**Tests Required:**
- Test enum validation
- Test default values
- Test config loading

### Task 4: Update SemanticScholarProvider for PDF Tracking
**File:** `src/services/providers/semantic_scholar.py`
**Effort:** 1.5 hours

- Add PDF availability tracking
- Implement `_search_with_pdf_filter()` for PDF_REQUIRED strategy
- Add PDF availability logging
- Maintain backward compatibility

**Tests Required:**
- Test PDF tracking
- Test PDF filter mode
- Test logging output

### Task 5: Integrate Quality Scoring into Discovery Service
**File:** `src/services/discovery_service.py`
**Effort:** 1.5 hours

- Integrate QualityScorer after search
- Apply quality ranking when enabled
- Filter by min_quality_score
- Log quality statistics

**Tests Required:**
- Test quality ranking integration
- Test min_score filtering
- Test disabled quality ranking

### Task 6: Update Enhanced Generator for Quality Display
**File:** `src/output/enhanced_generator.py`
**Effort:** 1 hour

- Add quality badges to paper entries
- Add PDF availability indicators
- Handle no-PDF papers according to config
- Generate PDF availability summary

**Tests Required:**
- Test quality badge generation
- Test PDF status display
- Test abstract-only entries

### Task 7: Update Configuration Examples and Documentation
**Files:** `config/*.yaml`, `docs/CLAUDE.md`
**Effort:** 30 minutes

- Add new config options to examples
- Document quality scoring algorithm
- Document PDF handling strategies

---

## 7. Test Strategy

### 7.1 Unit Tests

| Test Case | Description | Coverage Target |
|-----------|-------------|-----------------|
| `test_quality_score_citation_scaling` | Log scale citation scoring | QualityScorer |
| `test_quality_score_venue_recognition` | Known venues scored correctly | QualityScorer |
| `test_quality_score_unknown_venue` | Default score for unknown | QualityScorer |
| `test_quality_score_recency_tiers` | Age-based scoring | QualityScorer |
| `test_quality_score_completeness` | Metadata completeness | QualityScorer |
| `test_rank_papers_sorts_by_quality` | Highest quality first | rank_papers() |
| `test_rank_papers_filters_by_min` | Min score threshold | rank_papers() |
| `test_pdf_available_tracking` | PDF flag set correctly | Provider |
| `test_pdf_strategy_quality_first` | No filter applied | search() |
| `test_pdf_strategy_pdf_required` | Filter applied | search() |

### 7.2 Integration Tests

| Test Case | Description |
|-----------|-------------|
| `test_full_pipeline_quality_first` | Discovery → Scoring → Output |
| `test_config_loading_new_options` | YAML parsing with new fields |
| `test_markdown_output_with_quality` | Brief includes quality info |

### 7.3 Edge Cases

| Test Case | Description |
|-----------|-------------|
| `test_zero_citations_paper` | Paper with no citations |
| `test_missing_publication_date` | Unknown date handling |
| `test_all_papers_have_pdf` | 100% PDF availability |
| `test_no_papers_have_pdf` | 0% PDF availability |
| `test_empty_search_results` | No papers found |

---

## 8. Acceptance Criteria

### Functional Criteria
- [ ] Papers ranked by quality score (citations, venue, recency)
- [ ] PDF availability tracked without filtering quality papers
- [ ] Quality badges displayed in research briefs
- [ ] Papers without PDFs handled according to config
- [ ] ArXiv supplement mode fills PDF gaps when enabled

### Non-Functional Criteria
- [ ] Quality scoring adds <100ms to pipeline
- [ ] Clear logging of quality and PDF metrics
- [ ] Backward compatible with existing configs

### Quality Criteria
- [ ] Test coverage >= 95% for all new code
- [ ] All tests pass (100% pass rate)
- [ ] Mypy: Zero type errors
- [ ] Black/Flake8: Zero issues
- [ ] `./verify.sh` passes

---

## 9. Comparison: Old vs New Approach

| Aspect | PDF-First (v1, Rejected) | Quality-First (v2, Approved) |
|--------|--------------------------|------------------------------|
| **Search Filter** | `openAccessPdf` enabled | No PDF filter |
| **Ranking** | By PDF availability | By quality score |
| **Quality Bias** | May miss top papers | Preserves paper quality |
| **PDF Visibility** | Only papers with PDFs | All papers with PDF status |
| **User Choice** | PDF or nothing | Quality + informed PDF decision |
| **Output Value** | Limited but extractable | Comprehensive but mixed extraction |

---

## 10. Future Considerations

- **PDF Source Expansion:** Try Unpaywall, CORE, or institutional repos for missing PDFs
- **Quality Model Training:** Learn quality weights from user feedback
- **Venue Database:** Maintain comprehensive venue reputation scores
- **Abstract-Based Extraction:** LLM extraction from abstracts when PDF unavailable
- **Citation Network Analysis:** Quality boost for papers citing/cited by known good papers

---

## Appendix A: Quality Score Examples

| Paper | Citations | Venue | Age | Score |
|-------|-----------|-------|-----|-------|
| Attention Is All You Need | 100,000+ | NeurIPS | 7 years | 92 |
| Recent ArXiv preprint | 0 | ArXiv | 1 week | 35 |
| EMNLP 2023 paper | 50 | EMNLP | 1.5 years | 68 |
| Unknown venue, 500 cites | 500 | Unknown | 3 years | 55 |

---

## Appendix B: Configuration Migration Guide

**Existing configs work unchanged.** New options are optional with sensible defaults.

```yaml
# Before (still works):
research_topics:
  - query: "machine translation"
    max_papers: 20

# After (with new options):
research_topics:
  - query: "machine translation"
    max_papers: 20
    quality_ranking: true           # NEW (default: true)
    pdf_strategy: "quality_first"   # NEW (default)
    no_pdf_action: "include_metadata"  # NEW (default)
```
