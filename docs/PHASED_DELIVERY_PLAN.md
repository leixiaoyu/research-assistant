# ARISP Phased Delivery Plan
**Automated Research Ingestion & Synthesis Pipeline**

**Version:** 1.1
**Date:** 2026-01-24
**Status:** Phase 1.5 Complete, Phase 2 Ready

---

## Executive Summary

This document outlines a 4-phase, 7-week delivery plan to build the Automated Research Ingestion & Synthesis Pipeline (ARISP) from concept to production-grade service.

### Timeline Overview
```
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ Phase 1  │Phase 1.5 │ Phase 2  │ Phase 3  │ Phase 4  │
│✅Complete│✅Complete│(2 weeks) │(2 weeks) │ (1 week) │
│          │          │          │          │          │
│Foundation│ Provider │Extraction│Optimize  │ Harden   │
└──────────┴──────────┴──────────┴──────────┴──────────┘
    MVP       Unblock    Full      Production  Ops Ready
  Working     Phase 2   Features     Grade     Deployment
  End-to-End  ArXiv                Performance
```

### Investment & Returns

| Metric | Value |
|--------|-------|
| **Development Time** | 5 weeks remaining |
| **Team Size** | 2-3 engineers |
| **Infrastructure Cost** | ~$100/month (LLM + hosting) |
| **Expected Savings** | 10+ hours/week of manual research |
| **ROI Timeframe** | 2-3 months |

---

## Phase Breakdown

### Phase 1: Foundation & Core Pipeline (MVP)
**Status:** ✅ **COMPLETED** (Jan 23, 2026)
**Duration:** 2 weeks (Actual: 1 day)
**Goal:** End-to-end pipeline working for single topic

#### Key Deliverables
✅ Type-safe data models (Pydantic)
✅ Configuration management with YAML validation
✅ Semantic Scholar API integration
✅ Intelligent catalog system with deduplication
✅ Obsidian-compatible markdown output
✅ Modern CLI (typer)

#### Success Metrics
- Can search and retrieve papers from Semantic Scholar
- Handles all timeframe types (recent, since_year, date_range)
- Detects duplicate topics with 90%+ accuracy
- Generates valid output markdown

#### Security Requirements (MANDATORY) 🔒
- [x] All API keys loaded from environment variables
- [x] No hardcoded secrets in source code
- [x] .env added to .gitignore
- [x] .env.template provided with placeholders
- [x] All configuration inputs validated with Pydantic
- [x] Query input validated to prevent injection
- [x] File paths sanitized to prevent traversal
- [x] Rate limiting implemented for Semantic Scholar API
- [x] Security events logged appropriately
- [x] No secrets in logs
- [x] Pre-commit hooks configured
- [x] Secret scanning enabled

#### Verification Requirements (MANDATORY) ✅
- [x] Unit test coverage >80% (Actual: 95%)
- [x] Integration tests pass
- [x] All security checklist items verified
- [x] Manual verification report generated
- [x] Feature specification 100% met
- [x] No known security vulnerabilities

**Phase 1 cannot proceed to Phase 2 until ALL security and verification requirements are met.**

#### Risk Level: **LOW**
All technologies are proven and well-documented.

---

### Phase 1.5: Discovery Provider Abstraction
**Duration:** 3-5 days (Actual: 1 day)
**Status:** ✅ **COMPLETED** (Jan 24, 2026)
**Dependencies:** Phase 1 Complete
**Goal:** Unblock Phase 2 by implementing ArXiv as default discovery provider

#### Problem Statement
- Semantic Scholar API key is pending approval (timeline unknown)
- Cannot proceed with Phase 2 PDF processing without discovering real papers
- Phase 1 was verified with mocked data only

#### Solution: Provider Pattern
- Implement Discovery Provider abstraction (Strategy Pattern)
- Add ArXiv as default provider (no API key required)
- Preserve Semantic Scholar as optional provider
- Enable real testing with 100% PDF-accessible papers

#### Key Deliverables
✅ `DiscoveryProvider` abstract interface
✅ `ArxivProvider` with rate limiting (3s minimum delay)
✅ `SemanticScholarProvider` refactored to provider pattern
✅ Provider selection from config (`provider: "arxiv"` or `"semantic_scholar"`)
✅ Backward compatibility (existing configs default to ArXiv)
✅ Security requirements (SR-1.5-1 through SR-1.5-5)

#### Success Metrics
- ✅ ArXiv provider successfully searches and returns papers
- ✅ All ArXiv papers have accessible PDF links
- ✅ 3-second rate limiting enforced (runtime verified)
- ✅ Test coverage ~97% (exceeds >85% requirement)
- ✅ All Phase 1 tests still pass (backward compatible)

#### Security Requirements (MANDATORY) 🔒
- [x] SR-1.5-1: ArXiv rate limiting (3s minimum) ⚠️ **CRITICAL** - Runtime verified
- [x] SR-1.5-2: Provider-specific input validation
- [x] SR-1.5-3: PDF URL validation (ArXiv pattern matching, HTTPS enforcement)
- [x] SR-1.5-4: Provider selection validation (enum enforced)
- [x] SR-1.5-5: API response validation (status codes, malformed data)

#### Verification Requirements (MANDATORY) ✅
- [x] Unit test coverage **97%** (exceeds >85% requirement)
- [x] All Phase 1 tests still pass (100% backward compatibility)
- [x] Real ArXiv search successful (manual verification)
- [x] PDF links accessible (manual verification)
- [x] Rate limiting verified (runtime test + log analysis)
- [x] All security requirements tested
- [x] Comprehensive verification report generated

**Phase 1.5 Status:** ✅ **ALL requirements met - Ready for Phase 2**

#### What Phase 1.5 Unblocks
✅ **Phase 2 PDF Processing:** Real papers with guaranteed PDF access
✅ **Real Testing:** No longer dependent on mocked data
✅ **Immediate Progress:** No waiting for Semantic Scholar API key
✅ **User Onboarding:** No API key required for users

#### Risk Level: **LOW**
- ArXiv API is stable and well-documented
- No API key dependency
- Backward compatible with Phase 1 configs
- Clear implementation path

---

### Phase 2: PDF Processing & LLM Extraction
**Duration:** 2 weeks
**Dependencies:** Phase 1.5 Complete (Discovery Provider Abstraction)
**Goal:** Full extraction pipeline with intelligent content analysis

#### Key Deliverables
✅ PDF download with retry logic
✅ marker-pdf integration for MD conversion
✅ LLM integration (Claude 3.5 Sonnet / Gemini 1.5 Pro)
✅ Configurable extraction targets
✅ Enhanced output with extractions
✅ Cost tracking and budget controls

#### Success Metrics
- Successfully extracts prompts, code, and insights
- Handles papers without PDFs gracefully
- Enforces cost limits ($50/day default)
- 95%+ successful extraction rate

#### Security Requirements (MANDATORY) 🔒
- [ ] LLM API keys loaded from environment variables
- [ ] LLM responses sanitized before use
- [ ] PDF downloads validated (magic bytes check)
- [ ] PDF file size limits enforced
- [ ] Temporary files cleaned up securely
- [ ] Downloaded files isolated to safe directories
- [ ] No execution of code from PDFs
- [ ] Circuit breaker for failed LLM calls
- [ ] Cost limits enforced before API calls
- [ ] All Phase 1 security requirements maintained

#### Verification Requirements (MANDATORY) ✅
- [ ] Unit test coverage >80% (including new code)
- [ ] Integration tests for PDF pipeline
- [ ] Integration tests for LLM extraction
- [ ] Cost limit enforcement tested
- [ ] Fallback behavior tested (no PDF, LLM failure)
- [ ] Security vulnerability scan passed
- [ ] Manual verification report generated
- [ ] Feature specification 100% met

**Phase 2 cannot proceed to Phase 3 until ALL security and verification requirements are met.**

#### Risk Level: **MEDIUM**
LLM costs and PDF parsing failures are key risks, mitigated by:
- Strict cost limits and monitoring
- Fallback to abstract-only processing
- Retry logic with exponential backoff

---

### Phase 3: Intelligence & Optimization
**Duration:** 2 weeks
**Dependencies:** Phase 1 & 2 (with security gates passed)
**Goal:** Production-grade performance and efficiency

#### Key Deliverables
✅ Concurrent processing (asyncio)
✅ Multi-level caching (API, PDF, extractions)
✅ Enhanced paper deduplication
✅ Quality filtering and ranking
✅ Checkpoint/resume capability
✅ Autonomous operation with intelligent stopping
✅ Resource optimization

#### Success Metrics
- Process 50 papers in < 30 minutes (vs 2+ hours)
- Cache hit rate > 60%
- Detect 95%+ duplicate papers
- Reduce LLM costs by 40% through filtering
- Resume from interruption without data loss
- Autonomous stopping works correctly (quality convergence detected)

#### Security Requirements (MANDATORY) 🔒
- [ ] Cache keys use secure hashing (no sensitive data in keys)
- [ ] Cache directory permissions restricted
- [ ] Checkpoint files atomic writes only
- [ ] Checkpoint files validated on load
- [ ] Concurrent access to shared resources protected
- [ ] No race conditions in credential access
- [ ] Worker pool limits enforced
- [ ] Memory limits enforced to prevent DoS
- [ ] All Phase 1 & 2 security requirements maintained

#### Verification Requirements (MANDATORY) ✅
- [ ] Unit test coverage >80% (including all new code)
- [ ] Concurrent processing tested under load
- [ ] Race condition testing performed
- [ ] Cache invalidation tested
- [ ] Checkpoint/resume tested (with interruption)
- [ ] Autonomous stopping tested (convergence detection)
- [ ] Performance benchmarks met
- [ ] Load testing performed (50+ papers)
- [ ] Security vulnerability scan passed
- [ ] Manual verification report generated
- [ ] Feature specification 100% met

**Phase 3 cannot proceed to Phase 4 until ALL security and verification requirements are met.**

#### Risk Level: **MEDIUM**
Concurrency bugs and race conditions mitigated by:
- Comprehensive async testing
- Atomic cache operations
- Checkpoint integrity validation

---

### Phase 4: Production Hardening
**Duration:** 1 week
**Dependencies:** Phase 1, 2, 3 (with security gates passed)
**Goal:** Observable, maintainable, production-ready service

#### Key Deliverables
✅ Structured logging (JSON + correlation IDs)
✅ Prometheus metrics
✅ Comprehensive test suite (>80% coverage)
✅ Automated scheduling
✅ Grafana dashboards
✅ Health checks and alerts
✅ Deployment configs (Docker, systemd, K8s)
✅ Operational runbook
✅ Security hardening guide

#### Success Metrics
- All errors traceable via correlation IDs
- Key metrics visualized in Grafana
- Test coverage > 80%
- Zero-downtime deployments
- Mean time to recovery < 15 minutes
- All security audits passed

#### Security Requirements (MANDATORY) 🔒
- [ ] Security monitoring enabled
- [ ] Failed authentication attempts logged
- [ ] Rate limit violations logged
- [ ] Anomaly detection configured
- [ ] Security audit trail complete
- [ ] Credentials rotatable without downtime
- [ ] Secrets encrypted at rest (if stored)
- [ ] Secure communication (HTTPS only for APIs)
- [ ] Security headers configured
- [ ] Penetration testing performed
- [ ] Security incident response plan documented
- [ ] All Phase 1, 2, 3 security requirements maintained

#### Verification Requirements (MANDATORY) ✅
- [ ] Final unit test coverage >80%
- [ ] All integration tests pass
- [ ] End-to-end tests pass
- [ ] Load testing passed (sustained operation)
- [ ] Chaos testing performed (resilience verification)
- [ ] Security penetration testing passed
- [ ] Monitoring and alerting tested
- [ ] Deployment tested in clean environment
- [ ] Rollback procedure tested
- [ ] Security vulnerability scan passed (FINAL)
- [ ] Complete verification report generated
- [ ] Production readiness checklist 100% complete

**Phase 4 cannot be deployed to production until ALL security and verification requirements are met.**

#### Risk Level: **LOW**
Standard DevOps practices, well-understood tooling.

---

## Technology Stack

### Core Technologies
| Category | Technology | Rationale |
|----------|-----------|-----------|
| Language | Python 3.10+ | Rich ecosystem, async support |
| Data Models | Pydantic | Runtime validation, type safety |
| API Client | aiohttp | Async HTTP for performance |
| PDF Parser | marker-pdf | Code-preserving conversion |
| LLM | Claude 3.5 Sonnet / Gemini 1.5 Pro | 1M+ context, high quality |
| CLI | typer | Modern, type-safe interface |
| Config | YAML + dotenv | User-friendly, standard |

### Infrastructure
| Component | Technology | Purpose |
|-----------|-----------|---------|
| Caching | diskcache | Fast local caching |
| Logging | structlog | Structured JSON logs |
| Metrics | Prometheus | Time-series metrics |
| Dashboards | Grafana | Visualization |
| Scheduling | APScheduler | In-process scheduling |
| Testing | pytest | Comprehensive testing |

---

## Critical Dependencies

### External APIs
1. **Semantic Scholar API**
   - Rate limit: 100 requests/5 minutes
   - Required for paper discovery
   - Fallback: Manual paper list upload

2. **LLM APIs (Anthropic or Google)**
   - Cost: ~$3-15 per million tokens
   - Required for extraction
   - Fallback: None (core feature)

3. **marker-pdf**
   - Open source PDF converter
   - Required for PDF processing
   - Fallback: Abstract-only mode

### Infrastructure Requirements
- **Compute:** 2 CPU, 4GB RAM minimum
- **Storage:** 50GB for cache and outputs
- **Network:** Stable internet for API calls

---

## Cost Analysis

### Development Costs
| Phase | Engineering Weeks | Cost (@ $150/hr) |
|-------|-------------------|------------------|
| Phase 1 | 2 weeks × 2 eng | $24,000 |
| Phase 2 | 2 weeks × 2 eng | $24,000 |
| Phase 3 | 2 weeks × 2 eng | $24,000 |
| Phase 4 | 1 week × 2 eng | $12,000 |
| **Total** | **7 weeks** | **$84,000** |

### Operational Costs (Monthly)
| Item | Cost |
|------|------|
| LLM API (50 papers/day) | $50-150 |
| Hosting (VM or cloud) | $20-50 |
| Storage (S3/equivalent) | $10-20 |
| Monitoring (Grafana Cloud) | $0-50 |
| **Total/month** | **$80-270** |

### ROI Calculation
**Assumptions:**
- Manual research: 10 hours/week @ $100/hr = $1,000/week
- System savings: 80% automation = $800/week
- Monthly savings: $3,200
- **Payback period: 2-3 months**

---

## Risk Assessment

### High-Impact Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| LLM cost overruns | Medium | High | Strict budgets, alerts, filtering |
| API rate limits | Medium | Medium | Caching, backoff, queue management |
| PDF parsing failures | High | Medium | Fallback to abstracts |
| Concurrent bugs | Low | High | Comprehensive async testing |

### Risk Mitigation Strategy
1. **Phase 1:** Build solid foundation, minimize technical debt
2. **Phase 2:** Implement cost controls early
3. **Phase 3:** Extensive testing of concurrent code
4. **Phase 4:** Observability prevents production issues

---

## Success Criteria

### Functional Requirements
- [ ] Process 50 papers in < 30 minutes
- [ ] Extract structured information with >90% accuracy
- [ ] Detect duplicate topics with >95% accuracy
- [ ] Generate Obsidian-compatible output
- [ ] Automated daily runs without intervention

### Non-Functional Requirements
- [ ] 99% uptime
- [ ] Mean time to recovery < 15 minutes
- [ ] LLM costs < $150/month
- [ ] Test coverage > 80%
- [ ] Zero security vulnerabilities

### Business Requirements
- [ ] Reduce manual research time by 80%
- [ ] Enable engineering teams to stay current
- [ ] ROI positive within 3 months
- [ ] Scalable to 100+ papers/day

---

## Team Structure

### Recommended Team
- **1× Technical Lead** (70% time)
  - Architecture decisions
  - Code reviews
  - Risk management

- **2× Senior Engineers** (100% time)
  - Feature implementation
  - Testing
  - Documentation

- **1× DevOps Engineer** (20% time, Phase 4 only)
  - Deployment setup
  - Monitoring configuration

### Skills Required
- Python async programming
- LLM integration experience
- PDF processing knowledge
- Testing best practices
- DevOps / monitoring

---

## Dependencies & Prerequisites

### Before Phase 1
- [ ] Semantic Scholar API key obtained
- [ ] LLM API key (Anthropic or Google)
- [ ] Development environment setup
- [ ] Repository initialized
- [ ] Team onboarded

### Before Phase 2
- [ ] Phase 1 acceptance tests pass
- [ ] marker-pdf installation tested
- [ ] LLM budget approved
- [ ] Cost monitoring setup

### Before Phase 3
- [ ] Phase 2 performance baseline established
- [ ] Concurrency testing plan approved

### Before Phase 4
- [ ] Production infrastructure provisioned
- [ ] Monitoring stack deployed
- [ ] Operations team trained

---

## Go/No-Go Decision Points

### After Phase 1 (Week 2)
**Evaluate:**
- Core pipeline working end-to-end?
- Configuration system flexible enough?
- Team velocity on track?

**Decision:** Proceed to Phase 2 or adjust scope

### After Phase 2 (Week 4)
**Evaluate:**
- LLM extraction quality acceptable?
- Costs within budget?
- PDF processing reliable?

**Decision:** Proceed to Phase 3 or optimize Phase 2

### After Phase 3 (Week 6)
**Evaluate:**
- Performance targets met?
- System stable under load?
- Resource usage acceptable?

**Decision:** Proceed to Phase 4 or performance tuning

### After Phase 4 (Week 7)
**Evaluate:**
- All acceptance criteria met?
- Operations team ready?
- Production checklist complete?

**Decision:** Deploy to production or extend hardening

---

## Documentation Deliverables

### Technical Documentation
- [x] Architecture review (ARCHITECTURE_REVIEW.md)
- [x] Phase 1 specification (PHASE_1_SPEC.md)
- [x] Phase 2 specification (PHASE_2_SPEC.md)
- [x] Phase 3 specification (PHASE_3_SPEC.md)
- [x] Phase 4 specification (PHASE_4_SPEC.md)
- [ ] API documentation
- [ ] Data model reference
- [ ] Configuration guide

### Operational Documentation
- [ ] Deployment guide
- [ ] Operational runbook
- [ ] Troubleshooting guide
- [ ] Monitoring guide
- [ ] Disaster recovery plan

### User Documentation
- [ ] User guide
- [ ] Configuration examples
- [ ] FAQ
- [ ] Best practices

---

## Next Steps

### Immediate Actions
1. **Stakeholder Review** (This week)
   - Review this phased delivery plan
   - Review architectural decisions
   - Approve budget and timeline

2. **Team Formation** (Week 1)
   - Assign technical lead
   - Staff engineering team
   - Set up communication channels

3. **Environment Setup** (Week 1)
   - Provision development environments
   - Obtain API keys
   - Initialize repository

4. **Phase 1 Kickoff** (Week 1)
   - Sprint planning
   - Task breakdown
   - Begin implementation

### Success Metrics Tracking
- Weekly progress reports
- Biweekly stakeholder demos
- Continuous cost monitoring
- Quality metrics dashboard

---

## Approval

### Required Approvals

- [ ] **Product Owner** - Business value and priorities
- [ ] **Technical Lead** - Architecture and feasibility
- [ ] **Finance** - Budget allocation
- [ ] **Operations** - Operational readiness
- [ ] **Security** - Security review

### Sign-off

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Product Owner | | | |
| Technical Lead | | | |
| Engineering Manager | | | |
| Finance | | | |
| Operations Lead | | | |

---

## Architecture Foundation

All phases implement components defined in the **[System Architecture](./SYSTEM_ARCHITECTURE.md)** document, which provides:

- Complete layered architecture design
- Detailed data models (Pydantic)
- Component interactions and data flows
- Concurrency and resilience patterns
- Storage and caching strategies
- Observability architecture
- Security implementation
- Deployment architecture

**Key Architecture Decisions:**
1. **Separation of Concerns**: Layered architecture (CLI → Orchestration → Services → Infrastructure)
2. **Type Safety**: All data structures use Pydantic models
3. **Async-First**: I/O-bound operations use asyncio for performance
4. **Fail-Safe**: Graceful degradation rather than complete failure
5. **Observable**: Structured logging and Prometheus metrics throughout

See [Gap Resolution Matrix](./SYSTEM_ARCHITECTURE.md#gap-resolution-matrix) for how each architectural gap is addressed.

## Appendix

### Related Documents

**Architecture:**
- [System Architecture](./SYSTEM_ARCHITECTURE.md) - **[Primary Reference]** Complete system architecture design
- [Architecture Review](./ARCHITECTURE_REVIEW.md) - Gap analysis and recommendations

**Phase Specifications:**
- [Phase 1 Specification](./specs/PHASE_1_SPEC.md) - Foundation & Core Pipeline
- [Phase 2 Specification](./specs/PHASE_2_SPEC.md) - PDF Processing & LLM Extraction
- [Phase 3 Specification](./specs/PHASE_3_SPEC.md) - Intelligence & Optimization
- [Phase 4 Specification](./specs/PHASE_4_SPEC.md) - Production Hardening

**Development:**
- [CLAUDE.md](../CLAUDE.md) - Development guide for Claude Code

### Contact
- **Technical Lead:** [TBD]
- **Product Owner:** [TBD]
- **Project Manager:** [TBD]

---

**Document Version History**

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-01-23 | Principal Engineer | Initial phased delivery plan |
