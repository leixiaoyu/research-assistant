# GEMINI.md

This file provides guidance to Gemini CLI when working with code in this repository.

---

## Development Philosophy

**⚠️ NON-NEGOTIABLE BLOCKING REQUIREMENTS**

The following requirements are **absolute** and **block all commits and pushes** without exception:

1. **🔒 Security:** All security checklist items must pass
2. **🧪 Test Coverage:** ≥99% coverage for all modules (target 100%)
3. **✅ Tests Passing:** 100% pass rate (0 failures)
4. **📋 Completeness:** All feature requirements fully implemented
5. **🔏 Branch Protection:** No direct pushes to `main`. All changes via PR only.

**If ANY of these fail, you MUST stop and fix before committing or pushing. No exceptions.**

---

## Workflow & Branch Protection (Strict)

**Direct pushes to `main` are disabled and strictly forbidden.**

### 🌳 Git Worktree Protocol (Mandatory)

**All development work MUST be performed in isolated git worktrees.**

This ensures:
- Clean separation between concurrent tasks
- No accidental pollution of the main working directory
- Safe experimentation without affecting other work in progress
- Easy cleanup when work is complete

**Worktree Rules:**

1. **Always Create a Worktree for New Work:**
   ```bash
   # Standard location: ../.zcf/{project-name}/{feature-name}
   git worktree add -b feature/my-feature ../.zcf/research-assist/my-feature main
   ```

2. **Check Existing Worktrees Before Any Worktree Operation:**
   ```bash
   git worktree list
   ```

3. **Never Force-Remove Worktrees:**
   - Other processes may be using them
   - Always verify with `git worktree list` first
   - Ask user for confirmation before any removal

4. **Cleanup After PR Merge:**
   ```bash
   git worktree remove <path>  # Safe removal (will fail if dirty)
   git branch -d <branch>       # Delete merged branch
   ```

### ⚠️ Dangerous Operations - User Confirmation Required

**NEVER execute the following commands without EXPLICIT user confirmation:**

| Command | Risk | Confirmation Required |
|---------|------|----------------------|
| `git worktree remove --force` | May destroy uncommitted work | ✅ ALWAYS |
| `git reset --hard` | Destroys uncommitted changes | ✅ ALWAYS |
| `git clean -f` / `git clean -fd` | Deletes untracked files | ✅ ALWAYS |
| `git checkout -- .` | Discards all changes | ✅ ALWAYS |
| `git branch -D` (uppercase D) | Force deletes branch | ✅ ALWAYS |
| `git push --force` | Rewrites remote history | ✅ ALWAYS |
| `git stash drop` | Permanently deletes stash | ✅ ALWAYS |
| `rm -rf` on any git directory | Destroys repository data | ✅ ALWAYS |

**Before ANY destructive operation:**
1. List what will be affected (`git status`, `git worktree list`, `git stash list`)
2. Explain the impact to the user
3. Wait for explicit "yes", "confirm", or "proceed" response
4. Never assume silence or ambiguous responses as confirmation

**Safe Alternatives:**
- Use `git wt-remove` alias for worktree removal - enforces validation (see Worktree Protection Protocol below)
- Use `git branch -d` (lowercase d) - fails safely if branch is not merged
- Use `git stash` instead of discarding changes
- Use `git checkout -b backup/branch` before destructive operations

### 🔐 Git Worktree Protection Protocol (Non-Negotiable)

**Worktrees are PROTECTED WORKSPACES. Removal requires MANDATORY validation and EXPLICIT user confirmation.**

This protocol exists because worktrees may contain:
- Uncommitted changes (lost forever if removed)
- Untracked files (not recoverable)
- Work-in-progress not yet pushed (lost forever)
- Local experiments and notes (not in git)

#### Pre-Removal Validation Steps (MANDATORY)

**Before removing ANY worktree, you MUST complete ALL of these steps:**

1. **List all worktrees:**
   ```bash
   git worktree list
   ```

2. **Check for uncommitted changes in the target worktree:**
   ```bash
   git -C <worktree-path> status --porcelain
   ```
   - If output is NOT empty → **STOP, DO NOT REMOVE**

3. **Check for unpushed commits:**
   ```bash
   git -C <worktree-path> log @{u}..HEAD --oneline 2>/dev/null
   ```
   - If output is NOT empty → **STOP, DO NOT REMOVE**

4. **Check for untracked files:**
   ```bash
   git -C <worktree-path> status --porcelain | grep "^??"
   ```
   - If output is NOT empty → **WARN USER about untracked files**

5. **Request EXPLICIT user confirmation with full details:**
   ```
   ⚠️ WORKTREE REMOVAL REQUEST

   Path: <full-worktree-path>
   Branch: <branch-name>
   Uncommitted changes: [None detected / X files modified]
   Unpushed commits: [None / X commits ahead of remote]
   Untracked files: [None / X untracked files]

   This action is IRREVERSIBLE. All untracked files will be PERMANENTLY DELETED.

   Do you want to proceed with removal? [Requires explicit "yes" or "confirm"]
   ```

6. **Wait for explicit confirmation:**
   - Acceptable: "yes", "confirm", "proceed", "remove it"
   - NOT acceptable: silence, "ok", "sure", ambiguous responses

#### Required Method: Use `git wt-remove` Alias (MANDATORY)

**NEVER use `git worktree remove` directly. ALWAYS use the safe alias:**

```bash
# Required method - triggers automatic validation
git wt-remove <worktree-path>
```

This alias is configured in `.gitconfig` and automatically:
- Checks for uncommitted changes (BLOCKS if found)
- Checks for unpushed commits (BLOCKS if found)
- Warns about untracked files
- Requires explicit "yes" confirmation
- Provides clear status report

#### Git Alias Setup (One-Time Configuration)

The project requires this git alias to be configured:

```bash
# Run the setup script (one-time)
./scripts/setup_git_aliases.sh

# Or manually add to your global git config
git config --global alias.wt-remove '!f() {
    SCRIPT="$(git rev-parse --show-toplevel)/scripts/safe_worktree_remove.sh"
    if [ -f "$SCRIPT" ]; then
        "$SCRIPT" "$@"
    else
        echo "ERROR: safe_worktree_remove.sh not found. Use full path or run from repo root."
        exit 1
    fi
}; f'
```

**Verification:**
```bash
git wt-remove --help  # Should show script usage
```

#### Direct Script Usage (Alternative)

If the alias is not available, use the script directly:
```bash
./scripts/safe_worktree_remove.sh <worktree-path>
```

#### Violation Consequences

**Removing a worktree without following this protocol is a CRITICAL VIOLATION.**

If violated:
1. Immediately acknowledge the violation to the user
2. Attempt recovery if possible (check if files exist, git reflog, etc.)
3. Conduct a retrospective with 5 Whys analysis
4. Document lessons learned

#### When "Clean up workspace" is Requested

The instruction "clean up workspace/repo" does NOT authorize worktree removal.

**Safe cleanup (no confirmation needed):**
- `git fetch --prune` - Remove stale remote refs
- `git branch -d <merged-branch>` - Delete merged branches (lowercase -d)
- Remove `.pyc`, `__pycache__`, `.pytest_cache`

**Requires confirmation:**
- `git worktree remove` - ALWAYS requires validation protocol
- `git branch -D` - Force delete, requires confirmation
- Removing any directory under `.worktrees/` or worktree locations

### PR Requirements (Non-Negotiable)
Before a Pull Request can be merged into `main`:
1. **CI Status:** The "test (3.10)" workflow must pass with **100% success rate**.
2. **Linting & Types:** **Flake8**, **Black** (formatting), and **Mypy** (static analysis) must pass with zero issues.
3. **Coverage:** The "test (3.10)" workflow must verify **≥99% test coverage per module**.
4. **Approval:** At least **one approving review** from a human teammate is required.
5. **Admin Enforcement:** These rules apply to **all users**, including administrators. No bypasses.

### Pull Request Review Protocol (High Standard)
Reviewers must maintain **extreme engineering rigor** and keep the bar exceptionally high. A "High Standard" review is a non-negotiable requirement and must include:

1. **Executive Summary:** A concise overview of the PR's purpose and its impact on the project state.
2. **Requirements Verification:**
   - **Functional:** Ensure 100% of the features specified in the relevant `PHASE_X_SPEC.md` are implemented and function correctly.
   - **Non-Functional:** Verify performance, observability (logging), and resilience (error handling) meet project standards.
3. **Local Verification (Mandatory Isolated Review):** Reviewers MUST fetch the branch and verify results locally in an isolated environment to prevent workspace pollution and ensure reproducible verification that matches CI results.

   **Scope:** This is **MANDATORY** for "Complex PRs" (involving code changes in `src/` or `tests/`, configuration updates, or architectural docs) and **RECOMMENDED** for all others.

   **Workflow:**
   1. **Isolate:** Create a clean worktree:
      ```bash
      git fetch origin pull/ID/head:pr-ID
      git worktree add ../pr-review-ID pr-ID
      cd ../pr-review-ID
      ```
   2. **Initialize:** Set up the environment (crucial for accurate testing):
      ```bash
      python3.10 -m venv venv
      source venv/bin/activate
      pip install -r requirements.txt
      cp .env.template .env
      # Add dummy keys to .env if needed for non-integration tests
      ```
      *Note: This setup adds ~1-2 minutes per review but is essential to prevent false positives/negatives caused by dirty environments.*
   3. **Verify:** Run the verification suite:
      ```bash
      ./verify.sh
      ```
      - **100% Pass Rate** for automated tests.
      - **≥99% Coverage** per module.
      - **Zero Formatting/Linting/Type Issues.**
   4. **Cleanup:** Safely remove the worktree:
      ```bash
      cd ..
      git worktree remove pr-review-ID
      # Only if directory remains: rm -rf pr-review-ID
      ```

   **Environment Integrity Checks:**
   - [ ] No hardcoded paths (e.g., `/Users/username/...`)
   - [ ] No environment-specific imports (e.g., local-only packages)
   - [ ] No reliance on files outside repository (e.g., `~/config.yaml`)
   - [ ] All dependencies listed in `requirements.txt`
   - [ ] No OS-specific commands without cross-platform fallbacks
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
- **Minimum Acceptable:** 99% coverage per module
- **Overall Project:** Must maintain ≥99% coverage at all times

**If coverage falls below 95%, you MUST NOT commit or push. No exceptions.**

**Pragmatic Approach:**
- Aim for 100%, accept 99%+ with clear justification
- Every uncovered line must be documented with reason (e.g., "unreachable defensive code", "external library limitation")
- Coverage gaps must be tracked as technical debt and resolved within 1 sprint

**Coverage Verification Checklist:**
- [ ] Unit tests cover 100% of new functions/methods
- [ ] Integration tests cover all service interactions
- [ ] Edge cases have dedicated tests
- [ ] Error paths are fully tested
- [ ] `pytest --cov=src --cov-report=term-missing` shows ≥99%
- [ ] Any uncovered lines documented in verification report

### 🧪 Test-Driven Development (Required)

**No code should be pushed to remote without complete verification.**

Every feature must have:
1. **Automated Tests** (required):
   - Unit tests for all functions
   - Integration tests for service interactions
   - End-to-end tests for critical workflows
   - **Test coverage ≥99% (see Test Coverage section above)**
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
- **Overall Coverage:** X% (MUST be ≥99%)
- Unit Tests: X%
- Integration Tests: Y%
- Manual Tests: Z test cases

### Uncovered Lines (if any)
- `file.py:123` - Reason: [Defensive code for impossible state]
- `file.py:456` - Reason: [External library error handling]

**Coverage Status:** [PASS ✅ if ≥99%, FAIL ❌ if <99%]

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
- **Test coverage ≥99% for all modified modules**
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