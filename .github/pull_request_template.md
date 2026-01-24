## Summary
<!-- Concise overview of the PR's purpose and impact -->

## Changes
- [ ] Feature 1
- [ ] Feature 2

## Security Checklist (Mandatory)
<!-- All items must be checked before merging -->
- [ ] No hardcoded credentials in code
- [ ] All user inputs validated with Pydantic/InputValidation
- [ ] No command injection vulnerabilities
- [ ] All file paths sanitized with PathSanitizer
- [ ] Security events logged appropriately (no secrets in logs)
- [ ] Secret scanning passed

## Verification Results
<!-- Attach evidence of local verification -->
- **Test Pass Rate**: 100% (X/X tests)
- **Overall Coverage**: X% (MUST be >= 95%)
- **Module Coverage**: All modules >= 95%
- **Linting (Ruff)**: PASSED
- **Static Analysis (Mypy)**: PASSED

## Functional Requirements Verification
- [ ] Requirement 1 (from PHASE_X_SPEC.md)
- [ ] Requirement 2

## Non-Functional Requirements Verification
- [ ] Observability (Logging)
- [ ] Resilience (Error Handling)
- [ ] Performance
