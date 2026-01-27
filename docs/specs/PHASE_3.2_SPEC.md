# Phase 3.2: Semantic Scholar Provider Activation & Multi-Provider Intelligence
**Version:** 1.0
**Status:** 🎯 Ready for Implementation
**Timeline:** 1 week
**Dependencies:**
- Phase 1.5 Complete (Provider abstraction layer)
- Phase 2.5 Complete (PDF extraction reliability)
- Semantic Scholar API key available

---

## Architecture Reference

This phase activates and hardens the Semantic Scholar discovery provider as defined in [SYSTEM_ARCHITECTURE.md §5.2 Discovery Service](../SYSTEM_ARCHITECTURE.md#core-components).

**Architectural Gaps Addressed:**
- ✅ Gap #5: Multi-Provider Intelligence (provider selection, comparison, fallback)

**Components Activated:**
- Discovery Layer: Semantic Scholar Provider (see [Architecture §5.2](../SYSTEM_ARCHITECTURE.md#2-discovery-service))
- Provider selection and benchmarking

**Coverage Targets:**
- Provider selection logic: 100%
- Semantic Scholar integration: 100%
- Multi-provider scenarios: 100%

---

## 1. Executive Summary

Phase 3.2 **activates** the already-implemented Semantic Scholar provider and adds **multi-provider intelligence** to automatically select the optimal provider based on research needs. While the `SemanticScholarProvider` class exists from Phase 1.5, it has never been production-tested due to API key unavailability.

**Key Achievement:** Transform from single-provider system (ArXiv-only) to intelligent multi-provider system with automatic selection and fallback.

**What This Phase Is:**
- ✅ Production-hardening Semantic Scholar provider (comprehensive testing)
- ✅ Intelligent provider selection logic
- ✅ Multi-provider comparison and benchmarking
- ✅ Automatic fallback strategies

**What This Phase Is NOT:**
- ❌ Implementing Semantic Scholar from scratch (already exists)
- ❌ Changing the provider abstraction (Phase 1.5 architecture is solid)

---

## 2. Problem Statement

### 2.1 Current State

**Working:**
- ArXiv provider fully functional and production-tested
- Provider abstraction layer established
- Semantic Scholar provider implemented but untested

**Limitations:**
- Single provider dependency (ArXiv-only in production)
- No intelligent provider selection
- Semantic Scholar code untested (0% real-world verification)
- No provider comparison metrics
- No automatic fallback if provider fails

### 2.2 Business Impact

**Without Semantic Scholar:**
- Limited to ArXiv's domain (AI/CS/Physics pre-prints)
- Cannot search 200M+ papers across all disciplines
- Missing citation-based ranking capabilities
- No cross-disciplinary research possible

**With Multi-Provider Intelligence:**
- ✅ 200M+ papers accessible (vs 2.4M on ArXiv)
- ✅ Cross-disciplinary research enabled
- ✅ Citation-based quality filtering
- ✅ Automatic provider selection per topic
- ✅ Fallback resilience if one provider fails

---

## 3. Requirements

### Requirement: Semantic Scholar Production Readiness
The Semantic Scholar provider SHALL be production-hardened with comprehensive testing.

#### Scenario: API Key Configuration
**Given** a valid Semantic Scholar API key is available
**When** the system initializes
**Then** it SHALL:
- Load the API key from `SEMANTIC_SCHOLAR_API_KEY` environment variable
- Initialize the Semantic Scholar provider
- Log provider availability at INFO level
- Validate API key format (minimum 10 characters)

#### Scenario: Semantic Scholar Search Execution
**Given** a research topic configured with `provider: "semantic_scholar"`
**When** the discovery service executes a search
**Then** it SHALL:
- Use Semantic Scholar API v1 endpoints
- Enforce rate limiting (100 requests/minute)
- Return papers with `PaperMetadata` format
- Handle pagination for results > 100 papers
- Map Semantic Scholar fields correctly

#### Scenario: Semantic Scholar Error Handling
**Given** Semantic Scholar API returns an error
**When** the search is executed
**Then** it SHALL:
- Retry with exponential backoff (3 attempts)
- Log error details without exposing API key
- Return empty results on terminal failure
- Not crash the pipeline

### Requirement: Intelligent Provider Selection
The system SHALL automatically select the optimal provider based on research topic characteristics.

#### Scenario: ArXiv-Optimal Topic Detection
**Given** a research topic with query containing "arXiv", "AI", "machine learning", or "deep learning"
**When** no provider is explicitly specified
**Then** the system SHALL:
- Recommend ArXiv provider
- Log recommendation reasoning
- Allow user override via `provider` field

#### Scenario: Cross-Disciplinary Topic Detection
**Given** a research topic spanning multiple disciplines (e.g., "neuroscience AND machine learning")
**When** no provider is explicitly specified
**Then** the system SHALL:
- Recommend Semantic Scholar provider
- Log recommendation reasoning
- Allow user override

#### Scenario: Citation-Based Filtering Intent
**Given** a research topic config with `min_citations` field
**When** provider selection occurs
**Then** the system SHALL:
- Require Semantic Scholar provider (ArXiv doesn't provide citations)
- Log automatic selection reasoning

### Requirement: Multi-Provider Comparison
The system SHALL provide tools to compare providers for the same query.

#### Scenario: Provider Benchmark Mode
**Given** a research topic with `benchmark: true` in config
**When** the discovery service executes
**Then** it SHALL:
- Query ALL available providers for the same topic
- Log comparison metrics (count, overlap, unique papers)
- Return union of results with provider attribution
- Generate comparison report

#### Scenario: Provider Performance Metrics
**Given** any discovery search completes
**When** results are returned
**Then** the system SHALL log:
- Provider name
- Query time (milliseconds)
- Result count
- Rate limit remaining (if available)

### Requirement: Provider Fallback Strategy
The system SHALL automatically fall back to alternate providers on failure.

#### Scenario: Primary Provider Timeout
**Given** the primary provider times out after 30 seconds
**When** the search is retried
**Then** the system SHALL:
- Log timeout event
- Attempt search with secondary provider (if available)
- Return combined results
- Mark primary provider as degraded

#### Scenario: Provider Rate Limit Exhaustion
**Given** a provider returns 429 (rate limit exceeded)
**When** the search is attempted
**Then** the system SHALL:
- Wait for rate limit reset (if header provided)
- Fall back to alternate provider immediately
- Log rate limit event
- Continue pipeline without user intervention

### Requirement: Security & Compliance
All provider integrations SHALL meet Phase 1 security standards.

#### Scenario: API Key Protection
**Given** Semantic Scholar API key is configured
**When** any logging or error occurs
**Then** the system SHALL:
- Never log the API key value
- Redact API key in error messages
- Use masked format in logs (e.g., "sk_***7890")

#### Scenario: Query Injection Prevention
**Given** a user-provided Semantic Scholar query
**When** the query is validated
**Then** it SHALL:
- Reject control characters (except tab, newline, carriage return)
- Enforce maximum length (500 characters)
- Validate against Semantic Scholar query syntax
- Log rejected queries at WARN level

---

## 4. Technical Specifications

### 4.1 Module Structure

```
research-assist/
├── src/
│   ├── models/
│   │   └── config.py                  # UPDATE: Add provider selection config
│   ├── services/
│   │   ├── discovery_service.py       # UPDATE: Add provider selection logic
│   │   └── providers/
│   │       ├── base.py                # EXISTING: Provider interface
│   │       ├── arxiv.py               # EXISTING: ArXiv provider
│   │       └── semantic_scholar.py    # HARDEN: Add comprehensive tests
│   └── utils/
│       └── provider_selector.py       # NEW: Intelligent provider selection
└── tests/
    ├── unit/
    │   ├── test_providers/
    │   │   ├── test_semantic_scholar_extended.py  # NEW: Full coverage
    │   │   └── test_provider_selector.py          # NEW: Selection logic
    │   └── test_discovery_service_extended.py     # UPDATE: Multi-provider tests
    └── integration/
        ├── test_semantic_scholar_live.py          # NEW: Real API tests
        └── test_provider_comparison.py            # NEW: Benchmark tests
```

### 4.2 Data Models

#### Provider Selection Configuration

```python
# models/config.py

class ProviderSelectionConfig(BaseModel):
    """Provider selection configuration"""

    auto_select: bool = Field(
        default=True,
        description="Automatically select optimal provider based on query"
    )

    fallback_enabled: bool = Field(
        default=True,
        description="Enable automatic fallback to alternate providers"
    )

    benchmark_mode: bool = Field(
        default=False,
        description="Query all providers for comparison"
    )

    preference_order: List[ProviderType] = Field(
        default=[ProviderType.ARXIV, ProviderType.SEMANTIC_SCHOLAR],
        description="Provider preference order for auto-selection"
    )


class ResearchTopic(BaseModel):
    """Research topic configuration (UPDATED)"""

    query: str = Field(..., min_length=1, max_length=500)

    provider: Optional[ProviderType] = Field(
        default=None,
        description="Override automatic provider selection"
    )

    min_citations: Optional[int] = Field(
        default=None,
        description="Minimum citations (requires Semantic Scholar)"
    )

    benchmark: bool = Field(
        default=False,
        description="Enable provider comparison mode for this topic"
    )

    # ... existing fields ...
```

#### Provider Performance Metrics

```python
# models/provider.py (NEW)

class ProviderMetrics(BaseModel):
    """Performance metrics for a provider"""

    provider_name: str
    query_time_ms: int
    result_count: int
    rate_limit_remaining: Optional[int] = None
    cache_hit: bool = False
    error: Optional[str] = None


class ProviderComparison(BaseModel):
    """Comparison report for multiple providers"""

    query: str
    providers: List[ProviderMetrics]
    overlap_count: int  # Papers found by multiple providers
    unique_per_provider: Dict[str, int]  # Unique papers per provider
    total_unique: int
    recommendation: str  # Which provider performed best
```

### 4.3 Provider Selection Logic

```python
# utils/provider_selector.py (NEW)

class ProviderSelector:
    """Intelligent provider selection based on query characteristics"""

    # Provider capabilities matrix
    PROVIDER_CAPABILITIES = {
        ProviderType.ARXIV: {
            "domains": ["AI", "CS", "Physics", "Math", "Stats"],
            "citation_data": False,
            "pdf_access": 1.0,  # 100% guaranteed
            "coverage": 2_400_000,
            "cost": "free",
            "rate_limit": "3s/request"
        },
        ProviderType.SEMANTIC_SCHOLAR: {
            "domains": ["All"],
            "citation_data": True,
            "pdf_access": 0.6,  # ~60% have PDFs
            "coverage": 200_000_000,
            "cost": "free",
            "rate_limit": "100/minute"
        }
    }

    def select_provider(
        self,
        topic: ResearchTopic,
        available_providers: List[ProviderType]
    ) -> ProviderType:
        """Select optimal provider for topic

        Selection Logic:
        1. If topic.provider specified → use that (user override)
        2. If topic.min_citations specified → require Semantic Scholar
        3. If query contains ArXiv-specific terms → prefer ArXiv
        4. If cross-disciplinary query → prefer Semantic Scholar
        5. Default → first in preference_order

        Returns:
            Optimal provider for the topic
        """
        # User override
        if topic.provider:
            return topic.provider

        # Citation requirement
        if topic.min_citations is not None:
            if ProviderType.SEMANTIC_SCHOLAR not in available_providers:
                raise ValueError(
                    "min_citations requires Semantic Scholar provider"
                )
            return ProviderType.SEMANTIC_SCHOLAR

        # Query analysis
        query_lower = topic.query.lower()

        # ArXiv indicators
        arxiv_terms = ["arxiv", "preprint", "neural network", "deep learning",
                      "transformer", "attention mechanism", "machine learning"]
        if any(term in query_lower for term in arxiv_terms):
            if ProviderType.ARXIV in available_providers:
                logger.info(
                    "provider_selected_arxiv",
                    reason="query_domain_match",
                    query=topic.query[:50]
                )
                return ProviderType.ARXIV

        # Cross-disciplinary indicators
        if " AND " in topic.query or " OR " in topic.query:
            if ProviderType.SEMANTIC_SCHOLAR in available_providers:
                logger.info(
                    "provider_selected_semantic_scholar",
                    reason="cross_disciplinary_query",
                    query=topic.query[:50]
                )
                return ProviderType.SEMANTIC_SCHOLAR

        # Default to first available in preference order
        for provider in topic.preference_order:
            if provider in available_providers:
                logger.info(
                    "provider_selected_default",
                    provider=provider.value,
                    reason="preference_order"
                )
                return provider

        # Fallback to first available
        return available_providers[0]
```

### 4.4 Discovery Service Updates

```python
# services/discovery_service.py (UPDATE)

class DiscoveryService:
    """Discovery service with multi-provider intelligence"""

    def __init__(
        self,
        api_keys: Dict[str, str],
        config: ProviderSelectionConfig
    ):
        self.config = config
        self.selector = ProviderSelector()
        self.providers: Dict[ProviderType, DiscoveryProvider] = {}

        # Initialize ArXiv (always available)
        self.providers[ProviderType.ARXIV] = ArxivProvider()
        logger.info("arxiv_provider_initialized")

        # Initialize Semantic Scholar (if API key available)
        if "semantic_scholar" in api_keys:
            api_key = api_keys["semantic_scholar"]
            self.providers[ProviderType.SEMANTIC_SCHOLAR] = SemanticScholarProvider(
                api_key=api_key
            )
            logger.info("semantic_scholar_provider_initialized")
        else:
            logger.warning(
                "semantic_scholar_disabled",
                reason="no_api_key",
                hint="Set SEMANTIC_SCHOLAR_API_KEY to enable"
            )

    async def search(
        self,
        topic: ResearchTopic
    ) -> List[PaperMetadata]:
        """Search for papers with intelligent provider selection"""

        # Benchmark mode: query all providers
        if topic.benchmark or self.config.benchmark_mode:
            return await self._benchmark_search(topic)

        # Select optimal provider
        provider_type = self.selector.select_provider(
            topic,
            list(self.providers.keys())
        )

        provider = self.providers[provider_type]

        # Execute search with fallback
        try:
            results = await self._search_with_fallback(
                topic,
                provider,
                provider_type
            )
            return results

        except Exception as e:
            logger.error(
                "discovery_failed",
                provider=provider_type.value,
                error=str(e)
            )
            return []

    async def _search_with_fallback(
        self,
        topic: ResearchTopic,
        primary_provider: DiscoveryProvider,
        primary_type: ProviderType
    ) -> List[PaperMetadata]:
        """Execute search with automatic fallback"""

        start_time = datetime.now()

        try:
            results = await primary_provider.search(topic)

            # Log metrics
            query_time = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(
                "provider_search_success",
                provider=primary_type.value,
                result_count=len(results),
                query_time_ms=int(query_time)
            )

            return results

        except (APIError, RateLimitError, asyncio.TimeoutError) as e:
            logger.warning(
                "provider_search_failed",
                provider=primary_type.value,
                error=str(e),
                fallback_enabled=self.config.fallback_enabled
            )

            # Fallback if enabled
            if self.config.fallback_enabled:
                return await self._fallback_search(topic, primary_type)
            else:
                return []

    async def _fallback_search(
        self,
        topic: ResearchTopic,
        failed_provider: ProviderType
    ) -> List[PaperMetadata]:
        """Attempt search with alternate provider"""

        # Get alternate providers
        alternates = [
            p for p in self.providers.keys()
            if p != failed_provider
        ]

        if not alternates:
            logger.error("no_fallback_providers_available")
            return []

        # Try first alternate
        alternate_type = alternates[0]
        alternate_provider = self.providers[alternate_type]

        logger.info(
            "attempting_fallback",
            from_provider=failed_provider.value,
            to_provider=alternate_type.value
        )

        try:
            results = await alternate_provider.search(topic)
            logger.info(
                "fallback_search_success",
                provider=alternate_type.value,
                result_count=len(results)
            )
            return results
        except Exception as e:
            logger.error(
                "fallback_search_failed",
                provider=alternate_type.value,
                error=str(e)
            )
            return []

    async def _benchmark_search(
        self,
        topic: ResearchTopic
    ) -> List[PaperMetadata]:
        """Query all providers and compare results"""

        logger.info(
            "benchmark_mode_enabled",
            providers=list(self.providers.keys())
        )

        # Query all providers concurrently
        tasks = [
            self._benchmark_single_provider(topic, provider_type, provider)
            for provider_type, provider in self.providers.items()
        ]

        provider_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Build comparison report
        comparison = self._build_comparison_report(
            topic.query,
            provider_results
        )

        logger.info(
            "benchmark_comparison_complete",
            total_unique=comparison.total_unique,
            overlap=comparison.overlap_count,
            recommendation=comparison.recommendation
        )

        # Return union of all results
        all_papers = []
        for result in provider_results:
            if isinstance(result, list):
                all_papers.extend(result)

        # Deduplicate by paper_id
        unique_papers = {p.paper_id: p for p in all_papers}.values()
        return list(unique_papers)
```

---

## 5. Implementation Plan

### Day 1: Provider Selection Intelligence (6 hours)

**Task 1.1: Implement ProviderSelector** (2 hours)
- Create `utils/provider_selector.py`
- Implement capability matrix
- Implement selection logic with query analysis
- Add comprehensive logging

**Task 1.2: Add Selection Configuration** (2 hours)
- Update `models/config.py` with `ProviderSelectionConfig`
- Update `ResearchTopic` with `min_citations`, `benchmark`
- Add validation logic

**Task 1.3: Unit Tests** (2 hours)
- Test provider selection logic (10 test cases)
- Test all selection criteria
- Test edge cases (no providers available, etc.)
- Target: 100% coverage on `provider_selector.py`

### Day 2: Discovery Service Enhancement (6 hours)

**Task 2.1: Update DiscoveryService** (3 hours)
- Integrate `ProviderSelector`
- Implement `_search_with_fallback()`
- Implement `_fallback_search()`
- Add performance metrics logging

**Task 2.2: Benchmark Mode Implementation** (2 hours)
- Implement `_benchmark_search()`
- Implement `_build_comparison_report()`
- Add concurrent provider querying

**Task 2.3: Unit Tests** (1 hour)
- Test fallback scenarios (5 test cases)
- Test benchmark mode (3 test cases)
- Update existing discovery service tests

### Day 3: Semantic Scholar Hardening (6 hours)

**Task 3.1: Extended Unit Tests** (3 hours)
Create `tests/unit/test_providers/test_semantic_scholar_extended.py`:
- Test pagination handling
- Test all timeframe types (recent, since_year, date_range)
- Test citation filtering
- Test error scenarios (timeout, rate limit, 4xx, 5xx)
- Test retry logic with exponential backoff
- Target: 100% coverage

**Task 3.2: Integration Tests** (2 hours)
Create `tests/integration/test_semantic_scholar_live.py`:
- Test real API calls (with API key from env)
- Test rate limiting enforcement
- Test result mapping accuracy
- Skip if API key not available (`@pytest.mark.skipif`)

**Task 3.3: Performance Tests** (1 hour)
- Benchmark Semantic Scholar vs ArXiv for same query
- Measure query times, result counts
- Document findings

### Day 4: Configuration & Documentation (4 hours)

**Task 4.1: Update Configuration** (1 hour)
- Add `SEMANTIC_SCHOLAR_API_KEY` to `.env.template`
- Update `research_config.yaml` with examples
- Add provider selection examples

**Task 4.2: Update Documentation** (2 hours)
- Update README with Semantic Scholar setup
- Update SYSTEM_ARCHITECTURE with provider selection logic
- Add provider comparison guide

**Task 4.3: Create Provider Selection Guide** (1 hour)
Create `docs/guides/PROVIDER_SELECTION.md`:
- When to use ArXiv vs Semantic Scholar
- How to enable Semantic Scholar
- How to use benchmark mode
- Provider capabilities matrix

### Day 5: Testing & Verification (4 hours)

**Task 5.1: Run Full Test Suite** (1 hour)
```bash
pytest tests/ --cov=src --cov-report=term-missing
```
- Verify ≥95% coverage
- Fix any failing tests

**Task 5.2: Manual Integration Testing** (2 hours)
Test scenarios:
1. Query with ArXiv (should work)
2. Query with Semantic Scholar (should work with API key)
3. Query with invalid Semantic Scholar API key (should fallback to ArXiv)
4. Benchmark mode (should query both and compare)
5. Citation filtering (should auto-select Semantic Scholar)

**Task 5.3: Verification Report** (1 hour)
- Document all test results
- Create coverage report
- Verify all acceptance criteria met

---

## 6. Testing Strategy

### 6.1 Unit Tests (Target: 100% coverage)

**Provider Selection Tests** (10 tests):
- `test_select_arxiv_for_ai_query` - ArXiv domain matching
- `test_select_semantic_scholar_for_cross_disciplinary` - Cross-domain detection
- `test_select_semantic_scholar_for_citations` - Citation requirement
- `test_user_override_provider` - Explicit provider selection
- `test_fallback_to_default_provider` - Default behavior
- `test_no_providers_available` - Edge case handling
- `test_provider_not_in_preference_order` - Fallback logic
- `test_benchmark_mode_ignores_selection` - Benchmark override
- `test_selection_logging` - Logging verification
- `test_capability_matrix_lookup` - Matrix data validation

**Semantic Scholar Extended Tests** (15 tests):
- `test_search_with_recent_timeframe` - Recent papers
- `test_search_with_since_year_timeframe` - Historical papers
- `test_search_with_date_range_timeframe` - Custom range
- `test_search_with_pagination` - Multiple pages
- `test_search_with_min_citations` - Citation filtering
- `test_search_handles_timeout` - Timeout handling
- `test_search_handles_rate_limit` - 429 response
- `test_search_retry_logic` - Exponential backoff
- `test_search_handles_4xx_error` - Client errors
- `test_search_handles_5xx_error` - Server errors
- `test_validate_query_rejects_empty` - Input validation
- `test_validate_query_rejects_too_long` - Length limit
- `test_validate_query_rejects_control_chars` - Control char injection
- `test_api_key_redaction_in_logs` - Security check
- `test_result_mapping_accuracy` - Data mapping

**Discovery Service Multi-Provider Tests** (12 tests):
- `test_fallback_on_primary_timeout` - Timeout fallback
- `test_fallback_on_rate_limit` - Rate limit fallback
- `test_fallback_disabled` - No fallback mode
- `test_no_fallback_providers_available` - Edge case
- `test_benchmark_mode_queries_all_providers` - Benchmark execution
- `test_benchmark_comparison_report` - Report generation
- `test_provider_metrics_logging` - Performance tracking
- `test_semantic_scholar_initialization_with_key` - Initialization
- `test_semantic_scholar_disabled_without_key` - Disabled state
- `test_auto_selection_enabled` - Auto mode
- `test_auto_selection_disabled` - Manual mode
- `test_concurrent_provider_queries` - Concurrency

### 6.2 Integration Tests

**Semantic Scholar Live Tests** (5 tests):
```python
@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
    reason="Semantic Scholar API key not available"
)
class TestSemanticScholarLive:

    async def test_search_real_papers(self):
        """Test real search returns valid papers"""
        # Use a known query that should return results
        # Verify paper structure matches PaperMetadata

    async def test_rate_limiting_enforcement(self):
        """Test rate limiter prevents >100 requests/minute"""
        # Make rapid requests, verify delays enforced

    async def test_pagination_retrieves_all_results(self):
        """Test pagination correctly retrieves >100 results"""
        # Query with high result count
        # Verify all pages retrieved

    async def test_citation_filtering_accuracy(self):
        """Test min_citations correctly filters results"""
        # Query with min_citations=10
        # Verify all results have ≥10 citations

    async def test_timeframe_filtering_accuracy(self):
        """Test date range filtering works correctly"""
        # Query with specific date range
        # Verify all results within range
```

**Provider Comparison Tests** (3 tests):
- `test_arxiv_vs_semantic_scholar_overlap` - Measure overlap
- `test_arxiv_vs_semantic_scholar_performance` - Compare speed
- `test_provider_unique_papers` - Identify unique contributions

### 6.3 Coverage Requirements

| Module | Minimum Coverage | Target Coverage |
|--------|-----------------|-----------------|
| `provider_selector.py` | 95% | 100% |
| `semantic_scholar.py` | 95% | 100% |
| `discovery_service.py` (updated) | 95% | 100% |
| `config.py` (updated) | 95% | 100% |
| **Overall Phase 3.2** | **95%** | **100%** |

---

## 7. Acceptance Criteria

### Functional Requirements
- [ ] Semantic Scholar provider successfully queries real API
- [ ] Provider selection automatically chooses optimal provider
- [ ] Fallback strategy works when primary provider fails
- [ ] Benchmark mode queries all providers and generates comparison
- [ ] Citation filtering (min_citations) works correctly
- [ ] All timeframe types work with Semantic Scholar
- [ ] Rate limiting enforced (100 requests/minute)
- [ ] Pagination handles results > 100 papers

### Quality Requirements
- [ ] Test coverage ≥95% for all new/modified modules
- [ ] 100% coverage on provider_selector.py
- [ ] 100% coverage on semantic_scholar.py additions
- [ ] All unit tests pass (0 failures)
- [ ] All integration tests pass (or skip if API key unavailable)
- [ ] verify.sh passes 100%

### Security Requirements
- [ ] API key never logged in plaintext
- [ ] API key redacted in error messages
- [ ] Query validation prevents injection attacks
- [ ] No secrets in git commits
- [ ] Rate limiting prevents API abuse

### Documentation Requirements
- [ ] README updated with Semantic Scholar setup
- [ ] Provider selection guide created
- [ ] SYSTEM_ARCHITECTURE updated with multi-provider logic
- [ ] Configuration examples provided
- [ ] Verification report generated

---

## 8. Risks & Mitigation

### Risk: API Key Rate Limiting

**Risk Level:** Medium
**Impact:** Search failures during testing
**Probability:** High (if extensive testing without delays)

**Mitigation:**
- Implement strict rate limiter (100 requests/minute)
- Use cache during development to minimize API calls
- Mock Semantic Scholar in unit tests
- Reserve integration tests for final verification only

### Risk: Semantic Scholar API Changes

**Risk Level:** Low
**Impact:** Search failures, incorrect data mapping
**Probability:** Low (stable API)

**Mitigation:**
- Pin API version (v1) in code
- Add integration tests to detect breaking changes
- Monitor Semantic Scholar changelog
- Have ArXiv as automatic fallback

### Risk: Provider Selection Logic Complexity

**Risk Level:** Low
**Impact:** Suboptimal provider selection
**Probability:** Medium

**Mitigation:**
- Comprehensive unit tests for all selection criteria
- Allow explicit provider override in config
- Log all selection decisions with reasoning
- Benchmark mode to validate selection accuracy

---

## 9. Success Metrics

### Immediate Metrics (End of Phase 3.2)
- ✅ Semantic Scholar provider activated and tested
- ✅ 100% test coverage on new modules
- ✅ Provider selection logic verified with 10+ test cases
- ✅ Fallback strategy tested and working
- ✅ Zero security vulnerabilities

### Short-Term Metrics (1 month)
- 50% of research queries use Semantic Scholar
- 80% provider selection accuracy (user doesn't override)
- <1% fallback activation rate (providers stable)
- Zero API key leaks in logs

### Long-Term Metrics (3 months)
- 200M papers accessible (vs 2.4M ArXiv-only)
- Cross-disciplinary research workflows enabled
- User satisfaction with automatic provider selection
- Fallback resilience validated in production

---

## 10. Dependencies

### Prerequisites
- [x] Phase 1.5 Complete (Provider abstraction)
- [x] Phase 2.5 Complete (PDF extraction reliability)
- [x] Semantic Scholar API key obtained
- [ ] API key added to `.env` file

### External Dependencies
- Semantic Scholar API (v1)
  - Endpoint: `https://api.semanticscholar.org/graph/v1/paper/search`
  - Rate Limit: 100 requests/minute
  - Status Page: https://www.semanticscholar.org/product/api

### Environment Variables
```bash
# Required for Semantic Scholar
SEMANTIC_SCHOLAR_API_KEY=your_api_key_here

# Optional (for testing)
ENABLE_PROVIDER_BENCHMARKS=true
```

---

## 11. Rollout Plan

### Development Phase (Days 1-3)
- Implement provider selection logic
- Update discovery service
- Add comprehensive tests

### Testing Phase (Days 4-5)
- Run full test suite
- Manual integration testing
- Performance benchmarking

### Documentation Phase (Day 5)
- Update all documentation
- Create provider selection guide
- Generate verification report

### Deployment Phase
- Merge to main via PR
- Update production .env with API key
- Monitor provider usage metrics
- Validate fallback behavior in production

---

## 12. Future Enhancements (Out of Scope)

These enhancements are explicitly **NOT** part of Phase 3.2:

- **OpenAlex Provider**: Third provider integration
- **PubMed Provider**: Medical research integration
- **Machine Learning Provider Selection**: ML model instead of heuristics
- **Provider Cost Optimization**: Minimize API costs across providers
- **Provider Caching Layer**: Share cache across providers
- **Multi-Provider Deduplication**: Advanced duplicate detection across providers

These will be considered for future phases based on user demand.

---

## 13. References

- [Phase 1.5 Specification](./PHASE_1_5_SPEC.md) - Provider abstraction architecture
- [Semantic Scholar API Documentation](https://api.semanticscholar.org/api-docs/graph)
- [ArXiv API Documentation](https://info.arxiv.org/help/api/index.html)
- [SYSTEM_ARCHITECTURE.md](../SYSTEM_ARCHITECTURE.md) - Overall architecture
- [Proposal 001: Discovery Provider Strategy](../proposals/001_DISCOVERY_PROVIDER_STRATEGY.md)

---

**Prepared By:** Claude Code
**Review Status:** Ready for Team Review
**Estimated Effort:** 26 hours (1 week)
**Priority:** High (Unlocks cross-disciplinary research)
