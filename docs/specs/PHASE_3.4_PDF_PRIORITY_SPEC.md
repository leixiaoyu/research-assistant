# Phase 3.4: PDF Priority Search - Open Access First Strategy
**Version:** 1.0
**Status:** Draft - Pending Review
**Timeline:** 3-5 days
**Dependencies:**
- Phase 3.2 Complete (Semantic Scholar Provider Activation)
- Semantic Scholar API key available

---

## Architecture Reference

This phase enhances the Semantic Scholar discovery provider to prioritize papers with open access PDFs, as defined in [SYSTEM_ARCHITECTURE.md §5.2 Discovery Service](../SYSTEM_ARCHITECTURE.md#core-components).

**Architectural Gaps Addressed:**
- Gap: Low PDF availability rate (~5%) from Semantic Scholar
- Gap: No prioritization of papers with accessible PDFs

**Components Modified:**
- Discovery Layer: `SemanticScholarProvider` (see [Architecture §5.2](../SYSTEM_ARCHITECTURE.md#2-discovery-service))
- Configuration: New `pdf_priority` option in research topics

**Coverage Targets:**
- PDF priority logic: 100%
- Hybrid search implementation: 100%
- Configuration validation: 100%

---

## 1. Executive Summary

Phase 3.4 implements a **hybrid PDF priority search strategy** for the Semantic Scholar provider. The goal is to maximize the number of papers with downloadable PDFs by first querying for papers with open access PDFs, then filling remaining slots with all papers.

**Key Achievement:** Increase PDF availability from ~5% to 60-80%+ by prioritizing open access papers.

**What This Phase Is:**
- Implementing hybrid search strategy (open access first, then all papers)
- Adding `pdf_priority` configuration option
- Enhancing deduplication for multi-query results
- Adding metrics for PDF availability tracking

**What This Phase Is NOT:**
- Changing the provider abstraction architecture
- Implementing PDF download logic (already exists in Phase 2)
- Adding new providers

---

## 2. Problem Statement

### 2.1 Current State

**Working:**
- Semantic Scholar provider functional with proper query execution
- PDF download and conversion pipeline operational
- Open access PDF URLs returned in API responses

**Observed Issue (2025-02-07 Daily Run):**
- Daily automation found 0 papers with downloadable PDFs
- Root cause: Only ~5% of recent Semantic Scholar papers have open access PDFs
- Current search does not filter or prioritize papers with available PDFs

### 2.2 Analysis

**API Investigation Results:**
```python
# Standard query - ~5% have open access PDFs
GET /paper/search?query=machine+translation&limit=20
# Result: 20 papers, ~1 with openAccessPdf

# With openAccessPdf filter - 100% have PDFs
GET /paper/search?query=machine+translation&limit=20&openAccessPdf=
# Result: 20 papers, all with openAccessPdf
```

**Key Finding:** The Semantic Scholar API supports an `openAccessPdf` parameter that filters results to only return papers with available PDFs. This gives 100% PDF availability but may return fewer total papers.

### 2.3 Business Impact

**Without PDF Priority:**
- Daily research briefs have minimal or no extracted content
- LLM extraction pipeline runs with nothing to process
- Research output value significantly reduced
- Wasted API calls and processing time

**With PDF Priority:**
- 60-80%+ of papers have downloadable PDFs
- Rich LLM extractions for each paper
- Higher value research briefs
- Efficient resource utilization

---

## 3. Solution Design

### 3.1 Hybrid Search Strategy

The hybrid approach executes two API calls:

```
Step 1: Open Access Search
├── Query with openAccessPdf filter
├── Request max_papers results
└── Get papers with guaranteed PDF availability

Step 2: Fill Remaining (if needed)
├── Query without filter
├── Request enough to fill remaining slots
├── Deduplicate against Step 1 results
└── Prioritize papers with PDFs in final sort
```

### 3.2 Configuration Options

```yaml
research_topics:
  - query: "machine translation"
    max_papers: 20
    pdf_priority: "open_access_first"  # NEW OPTION
    # Options:
    # - "open_access_first" (default): Prioritize papers with PDFs
    # - "open_access_only": Only return papers with PDFs
    # - "disabled": Standard search without PDF prioritization
```

### 3.3 Deduplication Logic

Papers from both queries are merged with deduplication:
1. Create set of paper IDs from open access query
2. Filter second query results to exclude duplicates
3. Combine: [all open access papers] + [non-duplicate papers with PDFs] + [others]

---

## 4. Requirements

### REQ-3.4.1: Hybrid Search Implementation
The Semantic Scholar provider SHALL support hybrid search that prioritizes open access papers.

#### Scenario: Open Access First Search
**Given** a research topic with `pdf_priority: "open_access_first"`
**When** the provider executes a search
**Then** it SHALL:
- First query with `openAccessPdf` parameter to get papers with PDFs
- Then query without filter if more papers needed
- Deduplicate results by paper ID
- Return combined results with PDF papers first
- Log the number of papers from each query phase

#### Scenario: Open Access Only Search
**Given** a research topic with `pdf_priority: "open_access_only"`
**When** the provider executes a search
**Then** it SHALL:
- Query only with `openAccessPdf` parameter
- Return only papers with available PDFs
- Log warning if fewer than requested papers found

#### Scenario: Disabled PDF Priority
**Given** a research topic with `pdf_priority: "disabled"`
**When** the provider executes a search
**Then** it SHALL:
- Execute standard search without PDF filtering
- Maintain backward compatibility with existing behavior

### REQ-3.4.2: Configuration Validation
The configuration system SHALL validate PDF priority settings.

#### Scenario: Valid PDF Priority Value
**Given** a config with `pdf_priority` set to a valid value
**When** the config is loaded
**Then** it SHALL:
- Accept values: "open_access_first", "open_access_only", "disabled"
- Default to "open_access_first" if not specified

#### Scenario: Invalid PDF Priority Value
**Given** a config with `pdf_priority` set to an invalid value
**When** the config is loaded
**Then** it SHALL:
- Raise `ValidationError` with clear message
- List valid options in error message

### REQ-3.4.3: Rate Limit Compliance
The hybrid search SHALL respect API rate limits.

#### Scenario: Double API Call Rate Limiting
**Given** a hybrid search requires two API calls
**When** both calls are executed
**Then** it SHALL:
- Acquire rate limiter before each call
- Not exceed 100 requests/minute total
- Log rate limit status if approaching threshold

### REQ-3.4.4: Metrics and Logging
The provider SHALL log PDF availability metrics.

#### Scenario: PDF Availability Metrics
**Given** a hybrid search completes
**When** results are returned
**Then** it SHALL log:
- Total papers found
- Papers with open access PDF
- Papers without PDF
- PDF availability percentage
- Query phases executed

---

## 5. Technical Design

### 5.1 Model Changes

#### New Enum: PDFPriority

```python
# src/models/config.py

class PDFPriority(str, Enum):
    """PDF priority strategy for paper discovery."""
    OPEN_ACCESS_FIRST = "open_access_first"  # Default: prioritize, then fill
    OPEN_ACCESS_ONLY = "open_access_only"    # Only papers with PDFs
    DISABLED = "disabled"                     # Standard search
```

#### Updated ResearchTopic Model

```python
# src/models/config.py

class ResearchTopic(BaseModel):
    query: str
    timeframe: Union[TimeframeRecent, TimeframeSinceYear, TimeframeDateRange]
    max_papers: int = 20
    provider: ProviderType = ProviderType.ARXIV
    pdf_priority: PDFPriority = PDFPriority.OPEN_ACCESS_FIRST  # NEW
    # ... existing fields
```

### 5.2 Provider Changes

#### SemanticScholarProvider.search() - Hybrid Implementation

```python
# src/services/providers/semantic_scholar.py

async def search(self, topic: ResearchTopic) -> List[PaperMetadata]:
    """Search with PDF priority strategy."""

    if topic.pdf_priority == PDFPriority.DISABLED:
        return await self._search_standard(topic)

    if topic.pdf_priority == PDFPriority.OPEN_ACCESS_ONLY:
        return await self._search_open_access_only(topic)

    # Default: OPEN_ACCESS_FIRST
    return await self._search_hybrid(topic)

async def _search_hybrid(self, topic: ResearchTopic) -> List[PaperMetadata]:
    """Hybrid search: open access first, then fill with others."""

    # Phase 1: Get papers with open access PDFs
    open_access_papers = await self._execute_search(
        topic,
        open_access_only=True,
        limit=topic.max_papers
    )

    found_count = len(open_access_papers)
    remaining_slots = topic.max_papers - found_count

    logger.info(
        "hybrid_search_phase_1_complete",
        open_access_count=found_count,
        remaining_slots=remaining_slots,
    )

    if remaining_slots <= 0:
        return open_access_papers[:topic.max_papers]

    # Phase 2: Fill remaining slots
    seen_ids = {p.paper_id for p in open_access_papers}

    all_papers = await self._execute_search(
        topic,
        open_access_only=False,
        limit=topic.max_papers + 10  # Request extra for dedup buffer
    )

    # Filter duplicates and prioritize papers with PDFs
    additional = []
    for paper in all_papers:
        if paper.paper_id not in seen_ids:
            seen_ids.add(paper.paper_id)
            additional.append(paper)
            if len(additional) >= remaining_slots:
                break

    # Sort additional: papers with PDFs first
    additional.sort(key=lambda p: (0 if p.open_access_pdf else 1))

    combined = open_access_papers + additional

    # Calculate and log metrics
    pdf_count = sum(1 for p in combined if p.open_access_pdf)

    logger.info(
        "hybrid_search_complete",
        total_papers=len(combined),
        with_pdf=pdf_count,
        without_pdf=len(combined) - pdf_count,
        pdf_rate=f"{(pdf_count/len(combined)*100):.1f}%" if combined else "N/A",
    )

    return combined[:topic.max_papers]
```

#### Helper Method: _execute_search()

```python
async def _execute_search(
    self,
    topic: ResearchTopic,
    open_access_only: bool,
    limit: int
) -> List[PaperMetadata]:
    """Execute a single search with optional open access filter."""

    safe_query = self.validate_query(topic.query)
    params = self._build_query_params(topic, safe_query, limit=limit)

    if open_access_only:
        params["openAccessPdf"] = ""  # Empty string enables filter

    await self.rate_limiter.acquire()

    # ... existing HTTP request logic ...

    return self._parse_response(data)
```

### 5.3 Backward Compatibility

- Default `pdf_priority` is "open_access_first" for new behavior
- Existing configs without `pdf_priority` get the new default
- Set `pdf_priority: "disabled"` for exact old behavior

---

## 6. Implementation Tasks

### Task 1: Add PDFPriority Enum and Update ResearchTopic Model
**File:** `src/models/config.py`
**Effort:** 1 hour

```python
# Add:
class PDFPriority(str, Enum):
    OPEN_ACCESS_FIRST = "open_access_first"
    OPEN_ACCESS_ONLY = "open_access_only"
    DISABLED = "disabled"

# Update ResearchTopic:
pdf_priority: PDFPriority = PDFPriority.OPEN_ACCESS_FIRST
```

**Tests Required:**
- Test enum value validation
- Test default value assignment
- Test config loading with all priority values

### Task 2: Refactor SemanticScholarProvider.search() for Strategy Pattern
**File:** `src/services/providers/semantic_scholar.py`
**Effort:** 2 hours

- Extract current search logic to `_search_standard()`
- Add `_execute_search()` helper for single API call
- Route to appropriate strategy based on `pdf_priority`

**Tests Required:**
- Test strategy routing
- Test `_execute_search()` with both filter states
- Mock API responses for unit tests

### Task 3: Implement Hybrid Search Logic
**File:** `src/services/providers/semantic_scholar.py`
**Effort:** 2 hours

- Implement `_search_hybrid()` with two-phase search
- Implement `_search_open_access_only()`
- Add deduplication logic
- Add comprehensive logging

**Tests Required:**
- Test hybrid search with various result counts
- Test deduplication logic
- Test edge cases (0 open access, all open access)
- Test logging output

### Task 4: Update _build_query_params() for Open Access Filter
**File:** `src/services/providers/semantic_scholar.py`
**Effort:** 30 minutes

- Add `open_access_only` parameter
- Add `openAccessPdf` param when filter enabled

**Tests Required:**
- Test params with filter enabled/disabled
- Verify correct API parameter format

### Task 5: Integration Tests with Mocked API
**File:** `tests/integration/test_semantic_scholar_pdf_priority.py`
**Effort:** 2 hours

- Test full hybrid flow with mocked responses
- Test rate limiting with double API calls
- Test error handling in each phase

### Task 6: Update Configuration Examples
**Files:** `config/daily_german_mt.yaml`, `config/research_config.yaml`
**Effort:** 30 minutes

- Add `pdf_priority` to example configs
- Update documentation comments

---

## 7. Test Strategy

### 7.1 Unit Tests

| Test Case | Description | Coverage Target |
|-----------|-------------|-----------------|
| `test_pdf_priority_enum_values` | Verify all enum values | PDFPriority |
| `test_research_topic_default_priority` | Default is OPEN_ACCESS_FIRST | ResearchTopic |
| `test_search_routes_to_standard` | DISABLED routes correctly | search() |
| `test_search_routes_to_open_access_only` | OPEN_ACCESS_ONLY routes correctly | search() |
| `test_search_routes_to_hybrid` | OPEN_ACCESS_FIRST routes correctly | search() |
| `test_hybrid_phase1_fills_all` | When open access fills quota | _search_hybrid() |
| `test_hybrid_phase2_needed` | When fill phase required | _search_hybrid() |
| `test_dedup_removes_duplicates` | No duplicate paper IDs | _search_hybrid() |
| `test_additional_sorted_by_pdf` | PDF papers first | _search_hybrid() |
| `test_rate_limiter_called_twice` | Two acquires for hybrid | rate limiting |

### 7.2 Integration Tests

| Test Case | Description |
|-----------|-------------|
| `test_hybrid_search_end_to_end` | Full flow with mocked API |
| `test_open_access_only_end_to_end` | Full flow, filter only |
| `test_config_loading_with_priority` | Config file parsing |

### 7.3 Edge Case Tests

| Test Case | Description |
|-----------|-------------|
| `test_hybrid_zero_open_access` | No papers match open access filter |
| `test_hybrid_all_open_access` | All papers have PDFs |
| `test_hybrid_api_error_phase1` | Error in first phase |
| `test_hybrid_api_error_phase2` | Error in second phase |
| `test_empty_query_result` | Query returns no papers |

---

## 8. Acceptance Criteria

### Functional Criteria
- [ ] Hybrid search returns papers with PDFs prioritized
- [ ] Open access only mode filters to PDF-only papers
- [ ] Disabled mode preserves backward compatibility
- [ ] Deduplication works correctly across phases
- [ ] Logging includes PDF availability metrics

### Non-Functional Criteria
- [ ] Rate limiting respected for double API calls
- [ ] Performance: <5s for typical hybrid search
- [ ] Error handling: Pipeline continues on partial failure

### Quality Criteria
- [ ] Test coverage >= 95% for all new code
- [ ] All tests pass (100% pass rate)
- [ ] Mypy: Zero type errors
- [ ] Black/Flake8: Zero issues
- [ ] `./verify.sh` passes

---

## 9. Rollout Plan

### Phase 1: Implementation (Days 1-3)
1. Implement model changes (Task 1)
2. Implement provider changes (Tasks 2-4)
3. Write comprehensive tests (Task 5)
4. Update configs (Task 6)

### Phase 2: Verification (Day 4)
1. Run `./verify.sh` - all checks pass
2. Manual testing with real Semantic Scholar API
3. Verify PDF availability improvement

### Phase 3: Deployment (Day 5)
1. Create PR with verification report
2. Team review
3. Merge to main
4. Update daily automation config

---

## 10. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Open access filter returns too few papers | Medium | Low | Fill with non-filtered results |
| Double API calls hit rate limit | High | Low | Careful rate limiter management |
| Semantic Scholar changes API | High | Very Low | Monitor API responses, add alerts |

---

## 11. Future Considerations

- **PDF Source Fallback:** If open access URL fails, try unpaywall.org or other sources
- **PDF Quality Scoring:** Rank PDFs by quality/completeness
- **Provider-Agnostic:** Abstract PDF priority to work with other providers
- **Caching:** Cache open access status to avoid repeated API calls

---

## Appendix A: API Reference

### Semantic Scholar Paper Search API

**Endpoint:** `GET https://api.semanticscholar.org/graph/v1/paper/search`

**Relevant Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string | Search query |
| `limit` | int | Max results (1-100) |
| `fields` | string | Comma-separated fields to return |
| `openAccessPdf` | empty string | Filter to papers with open access PDFs |
| `publicationDateOrYear` | string | Date range filter |

**Example Request (with filter):**
```bash
curl -H "x-api-key: $API_KEY" \
  "https://api.semanticscholar.org/graph/v1/paper/search\
?query=machine+translation&limit=20&fields=title,openAccessPdf&openAccessPdf="
```

---

## Appendix B: Logging Examples

### Hybrid Search Logging Output

```json
{"event": "hybrid_search_phase_1_complete", "open_access_count": 12, "remaining_slots": 8}
{"event": "hybrid_search_complete", "total_papers": 20, "with_pdf": 15, "without_pdf": 5, "pdf_rate": "75.0%"}
```

### Metrics Dashboard Query

```sql
SELECT
  date,
  COUNT(*) as total_papers,
  SUM(CASE WHEN has_pdf THEN 1 ELSE 0 END) as with_pdf,
  ROUND(SUM(CASE WHEN has_pdf THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as pdf_rate
FROM paper_discoveries
WHERE provider = 'semantic_scholar'
GROUP BY date
ORDER BY date DESC;
```
