# Phase 3.2: Semantic Scholar Activation - Quick Reference

**Full Spec:** [PHASE_3.2_SPEC.md](./PHASE_3.2_SPEC.md)

---

## 🎯 What Is This Phase?

**Activate Semantic Scholar provider and add multi-provider intelligence.**

The Semantic Scholar provider code already exists (from Phase 1.5) but has never been tested in production due to lack of API key. This phase:
- ✅ Production-hardens Semantic Scholar with comprehensive testing
- ✅ Adds intelligent provider selection logic
- ✅ Implements automatic fallback strategies
- ✅ Enables provider comparison and benchmarking

---

## 📊 Key Metrics

| Metric | Value |
|--------|-------|
| **Timeline** | 1 week (5 days) |
| **Effort** | 26 hours |
| **Test Coverage Target** | 100% on new modules, ≥95% overall |
| **Lines of Code** | ~800 new/modified |
| **New Tests** | ~40 unit tests, 8 integration tests |

---

## 🚀 What Gets Built

### 1. Provider Selection Intelligence
**File:** `src/utils/provider_selector.py`

Automatically selects optimal provider based on:
- Query content (AI terms → ArXiv, cross-disciplinary → Semantic Scholar)
- Requirements (min_citations → must use Semantic Scholar)
- User preferences (explicit provider override)

### 2. Multi-Provider Discovery Service
**File:** `src/services/discovery_service.py` (updated)

New capabilities:
- Automatic fallback if primary provider fails
- Benchmark mode (query all providers, compare results)
- Performance metrics logging
- Concurrent provider queries

### 3. Comprehensive Testing
**Files:** Multiple test files

- 15 new Semantic Scholar tests (pagination, citation filtering, error handling)
- 10 provider selection tests (all selection criteria)
- 12 multi-provider discovery tests (fallback, benchmarking)
- 8 live integration tests (real API calls)

---

## 📋 Prerequisites

### Required
- [x] Phase 1.5 Complete (provider abstraction exists)
- [x] Phase 2.5 Complete (PDF extraction working)
- [x] Semantic Scholar API key obtained
- [ ] API key added to `.env` file

### Setup
```bash
# Add to .env
SEMANTIC_SCHOLAR_API_KEY=your_key_here

# Verify setup
python -c "import os; print('✅ API key loaded' if os.getenv('SEMANTIC_SCHOLAR_API_KEY') else '❌ API key missing')"
```

---

## ⚡ Quick Start (After Implementation)

### Basic Usage

```yaml
# research_config.yaml

research_topics:
  # Auto-select provider (ArXiv for AI topics)
  - query: "attention mechanism transformers"
    # provider field optional - will auto-select ArXiv

  # Force Semantic Scholar (cross-disciplinary)
  - query: "neuroscience AND deep learning"
    provider: "semantic_scholar"

  # Require citations (auto-selects Semantic Scholar)
  - query: "reinforcement learning robotics"
    min_citations: 10  # Only papers with 10+ citations

  # Benchmark mode (try all providers)
  - query: "graph neural networks"
    benchmark: true  # Queries both providers, compares results
```

### Provider Comparison

```bash
# Run with benchmark mode enabled
python -m src.cli run --config research_config.yaml

# Check logs for comparison report:
# - ArXiv: 15 results, 234ms
# - Semantic Scholar: 127 results, 891ms
# - Overlap: 12 papers found by both
# - Unique to ArXiv: 3 papers
# - Unique to Semantic Scholar: 115 papers
```

---

## 🎓 When to Use Which Provider

### Use ArXiv When:
- ✅ Researching AI, machine learning, deep learning
- ✅ Need 100% PDF access guarantee
- ✅ Speed is priority (2-5s queries)
- ✅ Focused on recent pre-prints

### Use Semantic Scholar When:
- ✅ Cross-disciplinary research
- ✅ Need citation data for filtering
- ✅ Broader coverage needed (200M vs 2.4M papers)
- ✅ Historical research (all years, all fields)

### Use Benchmark Mode When:
- ✅ Exploratory research (find everything)
- ✅ Validating provider selection accuracy
- ✅ Comparing provider performance
- ✅ Maximizing paper discovery

---

## 📊 Implementation Plan (5 Days)

| Day | Tasks | Deliverables |
|-----|-------|--------------|
| **1** | Provider selection logic | `provider_selector.py`, 10 unit tests |
| **2** | Discovery service updates | Fallback & benchmark mode, 12 tests |
| **3** | Semantic Scholar hardening | 15 unit tests, 8 integration tests |
| **4** | Configuration & docs | Updated configs, provider guide |
| **5** | Testing & verification | Full test suite, verification report |

---

## ✅ Acceptance Criteria

### Functional
- [ ] Semantic Scholar searches work with real API
- [ ] Provider auto-selection chooses correctly
- [ ] Fallback activates on primary provider failure
- [ ] Benchmark mode compares all providers
- [ ] Citation filtering works (min_citations)
- [ ] Pagination retrieves all results (>100 papers)

### Quality
- [ ] Test coverage ≥95% overall
- [ ] 100% coverage on provider_selector.py
- [ ] 100% coverage on semantic_scholar.py additions
- [ ] verify.sh passes 100%
- [ ] All tests pass (0 failures)

### Security
- [ ] API key never logged in plaintext
- [ ] Query validation prevents injection
- [ ] Rate limiting enforced (100/minute)
- [ ] No secrets in commits

---

## 🔧 Development Commands

```bash
# Run provider selection tests
pytest tests/unit/test_utils/test_provider_selector.py -v

# Run Semantic Scholar tests (unit)
pytest tests/unit/test_providers/test_semantic_scholar_extended.py -v

# Run Semantic Scholar tests (integration - requires API key)
pytest tests/integration/test_semantic_scholar_live.py -v

# Run all Phase 3.2 tests
pytest tests/ -k "provider_selector or semantic_scholar_extended" -v

# Check coverage
pytest --cov=src/utils/provider_selector --cov=src/services/providers/semantic_scholar --cov-report=term-missing

# Full verification
./verify.sh
```

---

## 📚 Documentation

### New Documentation
- `docs/guides/PROVIDER_SELECTION.md` - When to use which provider
- `docs/verification/PHASE_3.2_VERIFICATION.md` - Verification report

### Updated Documentation
- `README.md` - Semantic Scholar setup instructions
- `SYSTEM_ARCHITECTURE.md` - Provider selection logic
- `.env.template` - SEMANTIC_SCHOLAR_API_KEY placeholder

---

## 🚨 Common Issues & Solutions

### Issue: "semantic_scholar_disabled: no_api_key"
**Solution:** Add `SEMANTIC_SCHOLAR_API_KEY` to `.env` file

### Issue: "Rate limit exceeded (429)"
**Solution:** Wait 60 seconds or enable fallback to ArXiv

### Issue: "min_citations requires Semantic Scholar provider"
**Solution:** Ensure `SEMANTIC_SCHOLAR_API_KEY` is set

### Issue: Integration tests skipped
**Solution:** Expected if no API key - unit tests still verify logic

---

## 📈 Success Metrics

**Immediate (End of Phase):**
- Semantic Scholar activated and tested
- 100% test coverage on new code
- Zero security vulnerabilities

**Short-Term (1 month):**
- 50% of queries use Semantic Scholar
- 80% provider selection accuracy
- <1% fallback activation rate

**Long-Term (3 months):**
- 200M papers accessible
- Cross-disciplinary workflows enabled
- User satisfaction with auto-selection

---

## 🔗 Related Documentation

- [Full Specification](./PHASE_3.2_SPEC.md)
- [Phase 1.5 Spec](./PHASE_1_5_SPEC.md) - Provider abstraction
- [Proposal 001](../proposals/001_DISCOVERY_PROVIDER_STRATEGY.md) - Discovery strategy
- [Semantic Scholar API Docs](https://api.semanticscholar.org/api-docs/graph)

---

**Ready to Start?** Review the [full specification](./PHASE_3.2_SPEC.md) and begin with Day 1 tasks!
