# GEMINI.md

This file provides guidance to Gemini CLI when working with code in this repository.

---

## Development Philosophy

**⚠️ NON-NEGOTIABLE BLOCKING REQUIREMENTS**

The following requirements are **absolute** and **block all commits and pushes** without exception:

1. **🔒 Security:** All security checklist items must pass
2. **🧪 Test Coverage:** ≥95% coverage for all modules (target 100%)
3. **✅ Tests Passing:** 100% pass rate (0 failures)
4. **📋 Completeness:** All feature requirements fully implemented
5. **🔏 Branch Protection:** No direct pushes to `main`. All changes via PR only.

**If ANY of these fail, you MUST stop and fix before committing or pushing. No exceptions.**

---

## Workflow & Branch Protection (Strict)

**Direct pushes to `main` are disabled and strictly forbidden.**

### PR Requirements (Non-Negotiable)
Before a Pull Request can be merged into `main`:
1. **CI Status:** The "test (3.10)" workflow must pass with **100% success rate**.
2. **Linting & Types:** **Flake8**, **Black** (formatting), and **Mypy** (static analysis) must pass with zero issues.
3. **Coverage:** The "test (3.10)" workflow must verify **≥95% test coverage per module**.
4. **Approval:** At least **one approving review** from a human teammate is required.
5. **Admin Enforcement:** These rules apply to **all users**, including administrators. No bypasses.

### Pull Request Review Protocol (High Standard)
Reviewers must maintain **extreme engineering rigor** and keep the bar exceptionally high. A "High Standard" review is a non-negotiable requirement and must include:

1. **Executive Summary:** A concise overview of the PR's purpose and its impact on the project state.
2. **Requirements Verification:**
   - **Functional:** Ensure 100% of the features specified in the relevant `PHASE_X_SPEC.md` are implemented and function correctly.
   - **Non-Functional:** Verify performance, observability (logging), and resilience (error handling) meet project standards.
3. **Local Verification:** Reviewers SHOULD fetch the branch and verify results locally:
   - Confirm **100% Pass Rate** for automated tests.
   - Verify **≥95% Coverage** per module. **Test coverage is non-negotiable.**
   - Run **Flake8**, **Black**, and **Mypy** to ensure zero regressions.
   - Check alignment with `ci.yml` enforcement rules.
4. **Technical Assessment & Rigor:**
   - **Engineering Best Practices:** Adherence to SOLID, DRY, and KISS principles is mandatory.
   - **API Implementation:** Verify protocol security (HTTPS), parameter accuracy, and graceful error handling.
   - **Type Safety & Validation:** Ensure robust Pydantic usage and centralized validation.
   - **Architecture Alignment:** Check for proper delegation patterns and adherence to layered design.
5. **Security & Path Safety (Non-Negotiable):**
   - **Security First:** Verify all security checklist items are met. No compromises.
   - **Secrets Management:** Ensure no real keys are committed.
   - **Path Security:** Audit `.gitignore` and path sanitization logic.
6. **Final Assessment:** A clear "Status" (APPROVED or CHANGES REQUESTED) with a recommendation for action.

---

### 🔒 Security First (Non-Negotiable)

**Security is the #1 priority and cannot be compromised under any circumstances.**

Before writing ANY code, you must:
1. **Never hardcode secrets** - All credentials via environment variables
2. **Validate all inputs** - Use Pydantic models for runtime validation
3. **Sanitize all paths** - Prevent directory traversal attacks
4. **Log security events** - But never log secrets or credentials
5. **Scan for secrets** - Check before committing

**Security Checklist (Required for Every Change):**
- [ ] No hardcoded credentials in code
- [ ] All user inputs validated with Pydantic
- [ ] No command injection vulnerabilities
- [ ] No SQL injection vulnerabilities
- [ ] All file paths sanitized
- [ ] No directory traversal vulnerabilities
- [ ] Rate limiting implemented where needed
- [ ] Security events logged appropriately
- [ ] No secrets in logs or commits

See [SYSTEM_ARCHITECTURE.md §9 Security](docs/SYSTEM_ARCHITECTURE.md#security) for complete security requirements.

### 🧪 Test Coverage (Non-Negotiable)

**Test coverage is a BLOCKING requirement for all commits and pushes to remote.**

**Coverage Requirements:**
- **Target:** 100% test coverage for all new code
- **Minimum Acceptable:** 95% coverage per module
- **Overall Project:** Must maintain ≥95% coverage at all times

**If coverage falls below 95%, you MUST NOT commit or push. No exceptions.**

**Pragmatic Approach:**
- Aim for 100%, accept 95%+ with clear justification
- Every uncovered line must be documented with reason (e.g., "unreachable defensive code", "external library limitation")
- Coverage gaps must be tracked as technical debt and resolved within 1 sprint

**Coverage Verification Checklist:**
- [ ] Unit tests cover 100% of new functions/methods
- [ ] Integration tests cover all service interactions
- [ ] Edge cases have dedicated tests
- [ ] Error paths are fully tested
- [ ] `pytest --cov=src --cov-report=term-missing` shows ≥95%
- [ ] Any uncovered lines documented in verification report

### 🧪 Test-Driven Development (Required)

**No code should be pushed to remote without complete verification.**

Every feature must have:
1. **Automated Tests** (required):
   - Unit tests for all functions
   - Integration tests for service interactions
   - End-to-end tests for critical workflows
   - **Test coverage ≥95% (see Test Coverage section above)**
   - **100% pass rate required for all CI pipelines**

2. **Manual Verification** (when automated tests insufficient):
   - Step-by-step manual testing by Gemini CLI
   - Detailed logging of each test step
   - Screenshots/outputs captured as evidence
   - Results documented in verification report

**Verification Report Format:**
```markdown
## Feature Verification Report

**Feature:** [Feature name]
**Date:** [Date]
**Tested By:** Gemini CLI
**Status:** [PASS/FAIL]

### Test Cases
1. [Test case 1]
   - Steps: [...]
   - Expected: [...]
   - Actual: [...]
   - Status: PASS ✅

2. [Test case 2]
   - Steps: [...]
   - Expected: [...]
   - Actual: [...]
   - Status: PASS ✅

### Coverage
- **Overall Coverage:** X% (MUST be ≥95%)
- Unit Tests: X%
- Integration Tests: Y%
- Manual Tests: Z test cases

### Uncovered Lines (if any)
- `file.py:123` - Reason: [Defensive code for impossible state]
- `file.py:456` - Reason: [External library error handling]

**Coverage Status:** [PASS ✅ if ≥95%, FAIL ❌ if <95%]

### Security Verification
- [ ] All security checklist items verified
- [ ] No vulnerabilities detected
- [ ] Secret scanning passed

### Conclusion
[Summary of verification results]
```

### 📋 Feature Completeness (Required)

Every feature must function **100% of the time** according to its specification before being pushed.

**Definition of Complete:**
- All specified functionality implemented
- All edge cases handled
- All error cases handled gracefully
- All inputs validated
- All security requirements met
- **All tests passing (100% pass rate)**
- **Test coverage ≥95% for all modified modules**
- All documentation updated
- Verification report generated with coverage proof

**If ANY requirement is not met, the feature is INCOMPLETE and must not be pushed.**

---

## Project Overview, Tech Stack, and Development Setup

Refer to `CLAUDE.md` and `README.md` for project details, tech stack, and development setup instructions. Gemini should follow the same architectural patterns and development workflows as outlined for Claude.

## Coding Standards

Adhere strictly to the coding standards, security standards, and testing standards defined in `CLAUDE.md`.

## Key Implementation Details

Refer to `CLAUDE.md` for key implementation details regarding Configuration Management, APIs, PDF Conversion, LLM Extraction, and Output Format.