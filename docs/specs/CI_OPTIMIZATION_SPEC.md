# CI Pipeline Optimization Specification
**Version:** 1.1
**Status:** 📋 Planning
**Timeline:** 1-2 days implementation
**Last Updated:** 2026-03-15
**Dependencies:**
- GitHub Actions infrastructure
- Python 3.14 compatibility
- pytest ecosystem

---

## Architecture Reference

This specification defines optimizations to the CI/CD pipeline to reduce build times while maintaining comprehensive quality checks as defined in [CLAUDE.md](../../CLAUDE.md).

**Current Pain Points:**
- ❌ Sequential job execution (~4.5 min total)
- ❌ Slow dependency installation (2+ min)
- ❌ No fail-fast for quick checks
- ❌ Single-threaded test execution
- ❌ Suboptimal caching strategy

**Expected Outcomes:**
- ✅ 60-70% faster overall CI time
- ✅ 90%+ faster feedback on common errors
- ✅ Maintained 99%+ test coverage
- ✅ All existing checks preserved

**Coverage Targets:**
- All existing checks maintained
- Zero regression in code quality
- 99%+ test coverage enforced

**Execution Environment Matrix:**

| Check | Local (Pre-push) | GitHub Actions | Release Gate |
| ----- | ---------------- | -------------- | ------------ |
| Pre-commit hooks | ✅ Gitleaks, Black | ❌ | ❌ |
| Format/Lint/Type | ✅ `./verify.sh` | ✅ Automatic | ❌ |
| Tests + Coverage | ✅ `./verify.sh` | ✅ Automatic | ❌ |
| Secret Detection | ✅ Gitleaks | ✅ TruffleHog | ❌ |
| SAST (Bandit) | ⚠️ Optional | ✅ Warning | ❌ |
| Dependency Scan | ⚠️ Optional | ✅ Warning | ❌ |
| Doc Drift | ⚠️ Optional | ✅ Warning | ❌ |
| **Security Review Agent** | ✅ Required | ❌ Cannot run | ✅ **Enforced** |

**Legend:** ✅ = Runs here | ⚠️ = Optional | ❌ = Does not run here

---

## 1. Executive Summary

The CI pipeline has grown slower as additional verification steps were added (documentation validation, phase spec checking, etc.). This specification defines optimizations to reduce total CI time from ~5 minutes to ~1.5-2 minutes while maintaining all quality checks.

**Key Strategies:**
1. **Parallel job execution** with fail-fast dependencies
2. **Fast package installation** using `uv` (Astral's Rust-based installer)
3. **Aggressive caching** (virtualenv, mypy cache)
4. **Parallel test execution** using pytest-xdist

**What This Specification Is:**
- ✅ CI workflow restructuring for parallelization
- ✅ Dependency installation optimization
- ✅ Test execution acceleration
- ✅ Caching strategy improvements

**What This Specification Is NOT:**
- ❌ Changes to test coverage requirements
- ❌ Removal of any existing checks
- ❌ Changes to documentation validation
- ❌ New quality gates or requirements

---

## 2. Current State Analysis

### 2.1 Current CI Workflow (`ci.yml`)

```yaml
# Current: Sequential execution in single job
jobs:
  test:
    steps:
      - Checkout                    # ~5s
      - Setup Python (pip cache)   # ~30s
      - Install system deps        # ~30s (apt-get for Pillow)
      - Install Python deps        # ~90s (pip install)
      - Debug file structure       # ~2s (unnecessary)
      - Flake8 linting            # ~15s
      - Black formatting          # ~10s
      - Mypy type checking        # ~45s
      - Pytest with coverage      # ~120s
      # Total: ~5 minutes
```

### 2.2 Current Documentation Validation (`docs-validation.yml`)

```yaml
# Already parallelized - no changes needed
jobs:
  lint-markdown:     # ~6s
  check-spelling:    # ~13s
  check-doc-drift:   # ~6s
  validate-phase-specs: # ~7s
  # Total: ~13s (parallel)
```

### 2.3 Identified Bottlenecks

| Bottleneck | Impact | Root Cause |
| ---------- | ------ | ---------- |
| Pip install | ~90 seconds | Sequential download/install |
| Sequential jobs | ~5 min total | All checks in one job |
| No fail-fast | Slow feedback | Format errors wait for tests |
| Single-threaded pytest | ~2 min | No parallelization |
| System deps install | ~30s | apt-get on every run |

---

## 3. Requirements

### 3.1 Performance Requirements

#### REQ-CI-1.1: Fast Feedback on Formatting Errors
Format/lint errors SHALL be detected within 30 seconds.

**Acceptance Criteria:**
- WHEN Black formatting fails THEN CI SHALL fail within 30 seconds
- WHEN Flake8 linting fails THEN CI SHALL fail within 45 seconds
- WHEN format/lint passes THEN type checking and tests SHALL begin

#### REQ-CI-1.2: Reduced Total CI Time
Full CI pipeline SHALL complete in under 2 minutes when all checks pass.

**Acceptance Criteria:**
- WHEN all checks pass THEN CI SHALL complete in ≤120 seconds
- WHEN tests pass THEN coverage SHALL be reported as usual
- WHEN any check fails THEN clear error message SHALL be displayed

#### REQ-CI-1.3: Dependency Installation Speed
Dependency installation SHALL complete in under 30 seconds.

**Acceptance Criteria:**
- WHEN cache hits THEN installation SHALL complete in ≤10 seconds
- WHEN cache misses THEN installation SHALL complete in ≤30 seconds
- WHEN installation completes THEN all dependencies SHALL be available

### 3.2 Quality Requirements

#### REQ-CI-2.1: Maintained Test Coverage
Test coverage requirements SHALL NOT be reduced.

**Acceptance Criteria:**
- WHEN tests run THEN ≥99% coverage SHALL be enforced
- WHEN coverage fails THEN CI SHALL fail with clear message
- WHEN coverage passes THEN report SHALL be generated

#### REQ-CI-2.2: All Checks Preserved
All existing quality checks SHALL be maintained.

**Acceptance Criteria:**
- WHEN CI runs THEN Black formatting SHALL be checked
- WHEN CI runs THEN Flake8 linting SHALL be checked
- WHEN CI runs THEN Mypy type checking SHALL be checked
- WHEN CI runs THEN Pytest SHALL run with coverage

### 3.3 Compatibility Requirements

#### REQ-CI-3.1: Python 3.14 Support
All optimizations SHALL support Python 3.14.

**Acceptance Criteria:**
- WHEN using uv THEN Python 3.14 SHALL be supported
- WHEN using pytest-xdist THEN Python 3.14 SHALL work
- WHEN caching THEN Python 3.14 artifacts SHALL be cached

---

## 4. Implementation Plan

### Phase 1: Workflow Restructuring (Fail-Fast Pattern)

**Objective:** Split sequential job into parallel jobs with dependencies.

**New Workflow Structure (Unified CI Pipeline):**
```
                    ┌─────────────┐
                    │   format    │  ← Tier 1: Fastest check (15s)
                    └──────┬──────┘
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
┌──────────┐         ┌──────────┐        ┌──────────┐
│   lint   │         │typecheck │        │ secrets  │  ← Tier 2: Parallel (20-45s)
└────┬─────┘         └────┬─────┘        └────┬─────┘
     │                    │                   │
     └────────────────────┼───────────────────┘
                          ▼
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
┌──────────┐        ┌──────────┐       ┌──────────┐
│   test   │        │  sast    │       │ dep-scan │  ← Tier 3: Full checks (60-90s)
└────┬─────┘        └────┬─────┘       └────┬─────┘
     │                   │                  │
     └───────────────────┼──────────────────┘
                         ▼
                  ┌──────────────┐
                  │  doc-drift   │  ← Tier 4: Documentation sync (10s)
                  └──────────────┘
```

**Key Integration Points:**
- **Security Scanning (Tier 2-3):** Secret detection, SAST (Bandit), dependency vulnerabilities
- **Documentation Validation (Tier 4):** Ensures docs stay synchronized with code changes
- **Fail-Fast:** Secrets detection blocks immediately; SAST/dep-scan are non-blocking warnings

**Implementation:**

```yaml
# .github/workflows/ci.yml (restructured)
name: CI

on:
  push:
    branches: [ "main" ]
  pull_request:
    branches: [ "main" ]

permissions:
  contents: read

env:
  PYTHON_VERSION: "3.14"

jobs:
  # TIER 1: Fastest check - fail immediately on formatting issues
  format:
    name: Check Formatting
    runs-on: ubuntu-latest
    timeout-minutes: 2
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Check formatting
        run: |
          uv pip install black --system
          black --check src/ tests/

  # TIER 2: Quick static analysis (parallel after format passes)
  lint:
    name: Lint Code
    needs: format
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Run linting
        run: |
          uv pip install flake8 --system
          flake8 src/ tests/

  typecheck:
    name: Type Check
    needs: format
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Cache mypy
        uses: actions/cache@v4
        with:
          path: .mypy_cache
          key: mypy-${{ runner.os }}-${{ env.PYTHON_VERSION }}-${{ hashFiles('src/**/*.py') }}
          restore-keys: |
            mypy-${{ runner.os }}-${{ env.PYTHON_VERSION }}-

      - name: Run type checking
        run: |
          uv pip install mypy types-requests types-PyYAML --system
          mypy src/

  # TIER 3: Full test suite (only run if all checks pass)
  test:
    name: Test Suite
    needs: [lint, typecheck]
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
          cache-dependency-glob: "requirements.txt"

      - name: Set up Python
        run: uv python install ${{ env.PYTHON_VERSION }}

      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y libjpeg-dev zlib1g-dev libpng-dev libfreetype6-dev

      - name: Install dependencies
        run: |
          uv venv
          source .venv/bin/activate
          uv pip install -r requirements.txt
          uv pip install pytest-xdist

      - name: Run tests with coverage
        env:
          SEMANTIC_SCHOLAR_API_KEY: "dummy_key_for_ci"
        run: |
          source .venv/bin/activate
          pytest -n auto --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=99 tests/

  # TIER 2: Security - Secret Detection (parallel with lint/typecheck)
  secrets:
    name: Secret Detection
    needs: format
    runs-on: ubuntu-latest
    timeout-minutes: 3
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: TruffleHog Secret Scan
        uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}
          head: HEAD
          extra_args: --results=verified,unknown --fail

  # TIER 3: Security - SAST Analysis (parallel with test)
  sast:
    name: Static Security Analysis
    needs: [lint, typecheck, secrets]
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Run Bandit SAST
        run: |
          pip install bandit
          bandit -r src/ -f json -o bandit-results.json || true
          bandit -r src/ -ll -ii  # Show high-severity issues

  # TIER 3: Security - Dependency Vulnerabilities (parallel with test)
  dep-scan:
    name: Dependency Vulnerabilities
    needs: [lint, typecheck, secrets]
    runs-on: ubuntu-latest
    timeout-minutes: 3
    continue-on-error: true  # Non-blocking - CVEs appear daily
    steps:
      - uses: actions/checkout@v4

      - name: pip-audit Scan
        uses: pypa/gh-action-pip-audit@v1.0.0
        with:
          inputs: requirements.txt
          vulnerability-service: osv

  # TIER 4: Documentation Sync Check
  doc-drift:
    name: Documentation Sync
    needs: [test, sast, dep-scan]
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    timeout-minutes: 2
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Check documentation drift
        run: |
          BASE_SHA="${{ github.event.pull_request.base.sha }}"
          HEAD_SHA="${{ github.event.pull_request.head.sha }}"
          CHANGED_SRC=$(git diff --name-only "${BASE_SHA}"..."${HEAD_SHA}" -- 'src/' || true)
          CHANGED_DOCS=$(git diff --name-only "${BASE_SHA}"..."${HEAD_SHA}" -- 'docs/' 'CLAUDE.md' || true)
          if [ -n "${CHANGED_SRC}" ] && [ -z "${CHANGED_DOCS}" ]; then
            echo "::warning::Source code changed but no documentation updated."
          fi
          echo "✅ Documentation sync check complete"
```

### Phase 2: Dependency Management (uv)

**Objective:** Replace pip with uv for 8-15x faster installation.

**Changes:**
1. Replace `actions/setup-python` pip cache with `astral-sh/setup-uv`
2. Use `uv pip install` instead of `pip install`
3. Configure uv caching with dependency hash

**Expected Impact:**
- Cold cache: 90s → 20-30s
- Warm cache: 90s → 5-10s

### Phase 2.5: Developer Onboarding Script (`scripts/init.sh`)

**Objective:** Enable new developers to set up their environment with a single command.

**Problem:** Currently, new developers must:
1. Manually create virtual environment
2. Install multiple requirement files
3. Install system tools (gitleaks)
4. Configure pre-commit hooks
5. Copy environment templates
6. Potentially miss steps and face issues later

**Solution:** One-command initialization script.

**Usage (from README.md):**
```bash
# Clone and setup in one flow
git clone <repo-url>
cd research-assist
./scripts/init.sh
```

**Script Specification (`scripts/init.sh`):**
```bash
#!/bin/bash
set -e

echo "🚀 ARISP Development Environment Setup"
echo "======================================="
echo ""

# Detect OS
OS="$(uname -s)"
echo "📍 Detected OS: $OS"

# Check Python version
echo ""
echo "🐍 Checking Python version..."
if command -v python3.14 &> /dev/null; then
    PYTHON_CMD="python3.14"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
    MAJOR=$(echo $VERSION | cut -d. -f1)
    MINOR=$(echo $VERSION | cut -d. -f2)
    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 14 ]); then
        echo "❌ Python 3.14+ required. Found: $VERSION"
        echo "   Install: https://www.python.org/downloads/"
        exit 1
    fi
else
    echo "❌ Python not found. Install Python 3.14+"
    exit 1
fi
echo "   ✓ Using $($PYTHON_CMD --version)"

# Create virtual environment
echo ""
echo "📦 Creating virtual environment..."
if [ -d "venv" ]; then
    echo "   ⚠ venv already exists, skipping creation"
else
    $PYTHON_CMD -m venv venv
    echo "   ✓ Virtual environment created"
fi

# Activate virtual environment
echo ""
echo "🔌 Activating virtual environment..."
source venv/bin/activate
echo "   ✓ Activated"

# Upgrade pip
echo ""
echo "⬆️  Upgrading pip..."
pip install --upgrade pip --quiet
echo "   ✓ pip upgraded"

# Install dependencies
echo ""
echo "📚 Installing dependencies..."
pip install -r requirements.txt --quiet
echo "   ✓ Runtime dependencies installed"

if [ -f "requirements-dev.txt" ]; then
    pip install -r requirements-dev.txt --quiet
    echo "   ✓ Development dependencies installed"
fi

# Install system-level security tools
echo ""
echo "🔒 Installing security tools..."

# Gitleaks
if ! command -v gitleaks &> /dev/null; then
    case "$OS" in
        Darwin)
            if command -v brew &> /dev/null; then
                echo "   Installing gitleaks via Homebrew..."
                brew install gitleaks --quiet
            else
                echo "   ⚠ Homebrew not found. Install gitleaks manually:"
                echo "     brew install gitleaks"
            fi
            ;;
        Linux)
            echo "   ⚠ Please install gitleaks manually:"
            echo "     https://github.com/gitleaks/gitleaks/releases"
            ;;
        *)
            echo "   ⚠ Please install gitleaks manually for your OS"
            ;;
    esac
else
    echo "   ✓ gitleaks already installed ($(gitleaks version 2>&1 | head -1))"
fi

# Setup pre-commit hooks
echo ""
echo "🪝 Setting up pre-commit hooks..."
if command -v pre-commit &> /dev/null; then
    pre-commit install --quiet
    echo "   ✓ Pre-commit hooks installed"
else
    pip install pre-commit --quiet
    pre-commit install --quiet
    echo "   ✓ Pre-commit installed and hooks configured"
fi

# Setup environment file
echo ""
echo "🔐 Setting up environment..."
if [ ! -f ".env" ]; then
    if [ -f ".env.template" ]; then
        cp .env.template .env
        echo "   ✓ Created .env from template"
        echo "   ⚠ Remember to add your API keys to .env"
    fi
else
    echo "   ✓ .env already exists"
fi

# Verify installation
echo ""
echo "✅ Verifying installation..."
echo ""

# Check all required tools
TOOLS_OK=true
echo "   Checking tools:"
for tool in black flake8 mypy pytest bandit pip-audit gitleaks; do
    if command -v $tool &> /dev/null; then
        echo "   ✓ $tool"
    else
        echo "   ❌ $tool (missing)"
        TOOLS_OK=false
    fi
done

echo ""
if [ "$TOOLS_OK" = true ]; then
    echo "🎉 Setup complete! You're ready to develop."
    echo ""
    echo "Next steps:"
    echo "  1. Add your API keys to .env"
    echo "  2. Run ./verify.sh to validate setup"
    echo "  3. Start coding!"
    echo ""
    echo "Useful commands:"
    echo "  source venv/bin/activate  # Activate environment"
    echo "  ./verify.sh               # Run all checks"
    echo "  pytest tests/             # Run tests"
else
    echo "⚠️  Setup incomplete. Some tools are missing."
    echo "   Please install missing tools and run init.sh again."
    exit 1
fi
```

**README.md Update:**
```markdown
## Quick Start

### New Developer Setup (One Command)

```bash
git clone https://github.com/your-org/research-assist.git
cd research-assist
./scripts/init.sh
```

This script will:
- ✅ Verify Python 3.14+ is installed
- ✅ Create and activate virtual environment
- ✅ Install all runtime dependencies
- ✅ Install development and security tools
- ✅ Configure pre-commit hooks
- ✅ Create .env from template
- ✅ Verify all tools are working

### Manual Setup (Alternative)

If you prefer manual setup, see the Development Setup section in CLAUDE.md.
```

**Expected Developer Experience:**
```text
$ git clone https://github.com/org/research-assist && cd research-assist && ./scripts/init.sh

ARISP Development Environment Setup
====================================

📍 Detected OS: Darwin
🐍 Checking Python version...
   ✓ Using Python 3.14.0
📦 Creating virtual environment...
   ✓ Virtual environment created
🔌 Activating virtual environment...
   ✓ Activated
⬆️  Upgrading pip...
   ✓ pip upgraded
📚 Installing dependencies...
   ✓ Runtime dependencies installed
   ✓ Development dependencies installed
🔒 Installing security tools...
   ✓ gitleaks already installed (v8.24.2)
🪝 Setting up pre-commit hooks...
   ✓ Pre-commit hooks installed
🔐 Setting up environment...
   ✓ Created .env from template
   ⚠ Remember to add your API keys to .env

✅ Verifying installation...

   Checking tools:
   ✓ black
   ✓ flake8
   ✓ mypy
   ✓ pytest
   ✓ bandit
   ✓ pip-audit
   ✓ gitleaks

🎉 Setup complete! You're ready to develop.
```

---

### Phase 2.6: verify.sh Security Integration

**Objective:** Update verify.sh to include security checks for local validation.

**Current verify.sh Structure:**
1. Python version check
2. Black formatting
3. Flake8 linting
4. Mypy type checking
5. Pragma audit
6. Documentation validation
7. Tests with coverage

**Updated verify.sh Structure:**
```bash
#!/bin/bash
set -e

# ... existing Python version check ...

echo "🔍 Running Black (formatting)..."
$PYTHON_CMD -m black --check src/ tests/

echo "🔍 Running Flake8 (linting)..."
$PYTHON_CMD -m flake8 src/ tests/

echo "🔍 Running Mypy (type checking)..."
$PYTHON_CMD -m mypy src/

echo "🔍 Running Pragma Audit..."
# ... existing pragma audit logic ...

# ═══════════════════════════════════════════════════════════════
# NEW: Security Checks
# ═══════════════════════════════════════════════════════════════

echo "🔒 Running Security Checks..."
SECURITY_FAILED=0

# Secret scanning with Gitleaks (if installed)
if command -v gitleaks &> /dev/null; then
    echo "   Running Gitleaks secret scan..."
    if gitleaks detect --source . --no-git 2>/dev/null; then
        echo "   ✓ No secrets detected"
    else
        echo "   ❌ Potential secrets detected!"
        SECURITY_FAILED=1
    fi
else
    echo "   ⊘ Gitleaks not installed, skipping (install: brew install gitleaks)"
fi

# Bandit SAST (if installed)
if command -v bandit &> /dev/null; then
    echo "   Running Bandit SAST..."
    # -ll = only medium and higher, -ii = only medium confidence and higher
    if bandit -r src/ -ll -ii -q 2>/dev/null; then
        echo "   ✓ No high/medium severity issues"
    else
        echo "   ⚠ Bandit found potential issues (review recommended)"
        # Non-blocking for regular verify, blocking for release
    fi
else
    echo "   ⊘ Bandit not installed, skipping (install: pip install bandit)"
fi

# Dependency vulnerability scan (if installed)
if command -v pip-audit &> /dev/null; then
    echo "   Running pip-audit dependency scan..."
    if pip-audit -r requirements.txt --progress-spinner off 2>/dev/null; then
        echo "   ✓ No known vulnerabilities in dependencies"
    else
        echo "   ⚠ Vulnerabilities found in dependencies (review recommended)"
        # Non-blocking - CVEs appear daily
    fi
else
    echo "   ⊘ pip-audit not installed, skipping (install: pip install pip-audit)"
fi

if [ "$SECURITY_FAILED" -eq 1 ]; then
    echo ""
    echo "❌ Security checks failed. Secrets must be removed before commit."
    exit 1
fi

echo "   ✓ Security checks passed"

# ═══════════════════════════════════════════════════════════════

echo "📝 Running Documentation Validation..."
# ... existing documentation validation ...

echo "🧪 Running Tests with Coverage (>=99% required)..."
$PYTHON_CMD -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=99 tests/

echo "✅ All checks passed!"
```

**Security Check Behavior:**

| Check | Blocking? | Rationale |
| ----- | --------- | --------- |
| Gitleaks (secrets) | ✅ BLOCKING | Secrets must never be committed |
| Bandit (SAST) | ⚠️ Warning | Review findings, may have false positives |
| pip-audit (deps) | ⚠️ Warning | CVEs appear daily, avoid flaky local checks |

**Mandatory Tool Installation:**

All security tools SHALL be installed as part of project setup. This is NOT optional.

**Updated requirements-dev.txt:**
```txt
# Development & Testing Dependencies
pytest>=8.0.0
pytest-cov>=4.1.0
pytest-asyncio>=0.23.0
pytest-xdist>=3.5.0

# Code Quality
black>=24.3.0
flake8>=7.0.0
mypy>=1.9.0

# Security Tools (REQUIRED)
bandit>=1.7.8
pip-audit>=2.7.0

# Documentation
codespell>=2.2.0
```

**System-level Tools (one-time setup):**
```bash
# macOS
brew install gitleaks

# Linux
# Download from https://github.com/gitleaks/gitleaks/releases

# Windows
scoop install gitleaks
# OR download from releases
```

**Updated Setup Instructions (CLAUDE.md):**
```bash
# Create virtual environment
python3.14 -m venv venv
source venv/bin/activate

# Install ALL dependencies including security tools
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install system-level security tools
brew install gitleaks  # macOS

# Verify installation
gitleaks version
bandit --version
pip-audit --version
```

**verify.sh Tool Check:**
```bash
# verify.sh will fail fast if required tools are missing
check_required_tools() {
    MISSING=""
    command -v gitleaks &> /dev/null || MISSING="$MISSING gitleaks"
    command -v bandit &> /dev/null || MISSING="$MISSING bandit"
    command -v pip-audit &> /dev/null || MISSING="$MISSING pip-audit"

    if [ -n "$MISSING" ]; then
        echo "❌ Missing required security tools:$MISSING"
        echo ""
        echo "Install with:"
        echo "  brew install gitleaks"
        echo "  pip install bandit pip-audit"
        exit 1
    fi
}
```

---

### verify.sh Timing Estimates

**Current verify.sh (~2.5 minutes):**

| Check | Time | Notes |
| ----- | ---- | ----- |
| Python version check | ~0s | Instant |
| Black formatting | ~5s | Fast check mode |
| Flake8 linting | ~8s | Full codebase |
| Mypy type checking | ~25s | With cache |
| Pragma audit | ~2s | grep operations |
| Documentation validation | ~10s | Optional tools |
| **Pytest with coverage** | **~120s** | Main bottleneck |
| **Total** | **~170s** | ~2.5 minutes |

**Updated verify.sh with Security (~3 minutes):**

| Check | Time | Notes |
| ----- | ---- | ----- |
| Python version check | ~0s | Instant |
| Black formatting | ~5s | Fast check mode |
| Flake8 linting | ~8s | Full codebase |
| Mypy type checking | ~25s | With cache |
| Pragma audit | ~2s | grep operations |
| **Gitleaks (secrets)** | **~3s** | Very fast regex scan |
| **Bandit (SAST)** | **~15s** | Python AST analysis |
| **pip-audit (deps)** | **~8s** | OSV database check |
| Documentation validation | ~10s | Optional tools |
| **Pytest with coverage** | **~90s** | With pytest-xdist (-n auto) |
| **Total** | **~166s** | **~2.8 minutes** |

**Net Impact:** Security adds ~26 seconds, but pytest-xdist saves ~30 seconds.
**Result:** Similar or slightly faster overall!

### Phase 3: Test Parallelization

**Objective:** Run tests in parallel using pytest-xdist.

**Changes:**
1. Add `pytest-xdist` to test dependencies
2. Update pytest command to use `-n auto`
3. Ensure coverage combines correctly from workers

**Configuration:**
```ini
# pytest.ini updates
[pytest]
addopts =
    -n auto
    --dist=worksteal
    --cov=src
    --cov-branch
    --cov-report=term-missing
    --cov-fail-under=99
```

**Expected Impact:**
- Test execution: 120s → 40-60s (on 4-core runner)

### Phase 4: Security Scanning Integration

**Objective:** Add comprehensive security scanning without blocking developer velocity.

**Tools Integrated:**
1. **TruffleHog** (Secret Detection) - Blocks on verified secrets
2. **Bandit** (SAST) - Python-specific security analysis
3. **pip-audit** (Dependency Scanning) - OSV vulnerability database

**Configuration:**
```yaml
# Pre-commit hook for local secret scanning
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.24.2
    hooks:
      - id: gitleaks
        args: ["protect", "--staged"]
```

**Blocking vs Non-Blocking:**

| Check | Behavior | Rationale |
| ----- | -------- | --------- |
| Secret detection | **BLOCKING** | Leaked secrets are critical |
| SAST (Bandit) | Warning | Review findings, not auto-block |
| Dependency CVEs | Warning | CVEs appear daily, avoid CI flakiness |

**Expected Impact:**
- Secret leaks detected before merge: 100%
- SAST coverage: All Python source files
- Dependency scanning: Real-time OSV database

### Phase 5: Documentation Validation Integration

**Objective:** Ensure documentation stays synchronized with code changes.

**Integration with Existing `docs-validation.yml`:**
The CI pipeline incorporates documentation drift detection from the existing workflow.

**Checks Performed:**
1. **Markdown linting** - Format consistency
2. **Spell checking** - Typo detection
3. **Doc drift detection** - Warns when code changes without doc updates
4. **Phase spec validation** - Verifies spec statuses match implementation

**Expected Impact:**
- Documentation drift warnings: Immediate feedback on PRs
- False positive rate: Minimal (test-only changes excluded)

### Phase 6: Security Review Agent Integration (Release Gate)

**Objective:** Enforce AI-powered security review before every release.

**⚠️ Problem:** Cannot rely on humans remembering to run security reviews.

**Solution:** Automated release script with mandatory security review gate.

**Execution Environment:**

| Check | Runs In | Enforcement |
| ----- | ------- | ----------- |
| Format, Lint, Type, Test | GitHub Actions | Automatic on PR |
| Secret Detection (TruffleHog) | GitHub Actions | Blocks PR merge |
| SAST (Bandit), Dep-scan | GitHub Actions | Warning (non-blocking) |
| **Security Review Agent** | **Local (pre-release)** | **Release script enforced** |

**Security Severity Policy (Non-Negotiable):**

| Severity | Action Required | Can Release? |
| -------- | --------------- | ------------ |
| **CRITICAL** | Must fix immediately | ❌ BLOCKED |
| **HIGH** | Must fix immediately | ❌ BLOCKED |
| **MEDIUM** | Must fix before release | ❌ BLOCKED |
| **LOW** | Must fix OR document justification | ⚠️ Conditional |

**LOW Severity Exception Process:**
- Each LOW finding must have documented justification
- Justification stored in `security-exceptions-{version}.md`
- Exceptions require explicit `--allow-low-exceptions` flag
- All exceptions tracked and reviewed in next release

**Release Script (`scripts/release.sh`):**
```bash
#!/bin/bash
set -e

VERSION=$1
ALLOW_LOW_EXCEPTIONS=false

# Parse flags
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --allow-low-exceptions) ALLOW_LOW_EXCEPTIONS=true ;;
        *) VERSION=$1 ;;
    esac
    shift
done

if [ -z "$VERSION" ]; then
    echo "Usage: ./scripts/release.sh <version> [--allow-low-exceptions]"
    exit 1
fi

echo "🔒 Running mandatory security review..."
REPORT_FILE="security-review-${VERSION}.md"
EXCEPTIONS_FILE="security-exceptions-${VERSION}.md"

# Run Claude Code security review (REQUIRED)
if ! command -v claude &> /dev/null; then
    echo "❌ Claude Code CLI not installed. Cannot proceed with release."
    echo "Install: https://claude.ai/code"
    exit 1
fi

claude "/oh-my-claudecode:security-review src/" > "$REPORT_FILE" 2>&1

# Check for CRITICAL/HIGH/MEDIUM findings (always block)
if grep -qE "CRITICAL|HIGH|MEDIUM" "$REPORT_FILE"; then
    echo "❌ Security review found issues that MUST be resolved:"
    grep -E "CRITICAL|HIGH|MEDIUM" "$REPORT_FILE"
    echo ""
    echo "All CRITICAL, HIGH, and MEDIUM issues must be fixed before release."
    echo "Review full report: $REPORT_FILE"
    exit 1
fi

# Check for LOW findings
if grep -q "LOW" "$REPORT_FILE"; then
    LOW_COUNT=$(grep -c "LOW" "$REPORT_FILE" || echo "0")
    echo "⚠️  Found $LOW_COUNT LOW severity findings."

    if [ "$ALLOW_LOW_EXCEPTIONS" = true ]; then
        if [ ! -f "$EXCEPTIONS_FILE" ]; then
            echo "❌ --allow-low-exceptions requires $EXCEPTIONS_FILE"
            echo ""
            echo "Create exceptions file with justification for each LOW finding:"
            echo "  ## LOW-001: [Finding title]"
            echo "  **Justification:** [Why this cannot be fixed now]"
            echo "  **Tracking:** [Issue/ticket number for future fix]"
            exit 1
        fi

        echo "✅ LOW exceptions documented in $EXCEPTIONS_FILE"
        echo "⚠️  These will be reviewed in the next release cycle."
    else
        echo "❌ LOW severity issues must be resolved OR use --allow-low-exceptions"
        echo ""
        echo "Options:"
        echo "  1. Fix all LOW issues (recommended)"
        echo "  2. Document justifications in $EXCEPTIONS_FILE and use:"
        echo "     ./scripts/release.sh $VERSION --allow-low-exceptions"
        exit 1
    fi
fi

echo "✅ Security review passed (no CRITICAL/HIGH/MEDIUM issues)"

# Run all CI checks locally
echo "🧪 Running full verification..."
./verify.sh || { echo "❌ Verification failed"; exit 1; }

# Create release artifacts
echo "📦 Creating release tag v${VERSION}..."

if [ -f "$EXCEPTIONS_FILE" ]; then
    git add "$EXCEPTIONS_FILE"
    git commit -m "docs: Add security exceptions for v${VERSION}"
fi

git tag -a "v${VERSION}" -m "Release v${VERSION}" \
    -m "Security review: $REPORT_FILE" \
    -m "Exceptions: ${EXCEPTIONS_FILE:-none}"

echo "✅ Release v${VERSION} ready. Push with: git push origin v${VERSION}"
```

**GitHub Actions Release Validation:**
```yaml
# .github/workflows/release-validation.yml
name: Release Validation

on:
  push:
    tags:
      - 'v*'

jobs:
  validate-release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Verify security review artifact
        run: |
          VERSION="${GITHUB_REF#refs/tags/v}"
          REPORT="security-review-${VERSION}.md"

          if [ ! -f "$REPORT" ]; then
            echo "::error::Security review report not found: $REPORT"
            echo "::error::Releases must be created via ./scripts/release.sh"
            exit 1
          fi

          echo "✅ Security review artifact verified"

      - name: Run final security checks
        run: |
          pip install bandit pip-audit
          bandit -r src/ -ll -ii
          pip-audit -r requirements.txt
```

**Pre-push Hook (`.git/hooks/pre-push`):**
```bash
#!/bin/bash
# Prevent direct tag pushes without release script

while read local_ref local_sha remote_ref remote_sha; do
    if [[ "$local_ref" == refs/tags/v* ]]; then
        VERSION="${local_ref#refs/tags/v}"
        REPORT="security-review-${VERSION}.md"

        if [ ! -f "$REPORT" ]; then
            echo "❌ Cannot push release tag without security review."
            echo "Use: ./scripts/release.sh ${VERSION}"
            exit 1
        fi
    fi
done
```

**Enforcement Summary:**
1. **Release script required** - Only way to create release tags
2. **Security review mandatory** - Script blocks if Claude Code unavailable
3. **Critical findings block** - HIGH/CRITICAL issues prevent release
4. **Pre-push hook** - Prevents bypassing release script
5. **GitHub validation** - Final check on tag push

---

## 5. Expected Outcomes

### 5.1 Time Improvements

| Scenario | Current | Optimized | Improvement |
| -------- | ------- | --------- | ----------- |
| Format fails | ~5 min | ~15 sec | **95% faster** |
| Lint fails | ~5 min | ~35 sec | **88% faster** |
| Type check fails | ~5 min | ~60 sec | **80% faster** |
| All pass | ~5 min | ~90-120 sec | **60-70% faster** |

### 5.2 Feedback Loop Improvements

| Error Type | Current Feedback | Optimized Feedback |
| ---------- | ---------------- | ------------------ |
| Formatting | Wait ~5 min | ~15 seconds |
| Linting | Wait ~5 min | ~35 seconds |
| Type errors | Wait ~5 min | ~60 seconds |
| Test failures | Wait ~5 min | ~90-120 seconds |

### 5.3 Resource Utilization

| Metric | Current | Optimized |
| ------ | ------- | --------- |
| Runner minutes/PR | ~5 min | ~3-4 min |
| Parallel jobs | 1 | 4 (format → lint+type → test) |
| Cache hit rate | ~60% | ~90%+ |

---

## 6. Security Requirements 🔒

### SR-CI-1: No Secrets in Workflows
- [ ] Workflow files SHALL NOT contain hardcoded API keys or credentials
- [ ] All secrets SHALL be accessed via `${{ secrets.* }}` syntax
- [ ] Dummy/mock keys used in CI SHALL be clearly labeled

### SR-CI-2: Safe Dependency Installation
- [ ] Dependencies SHALL be installed from trusted sources only (PyPI)
- [ ] `uv` SHALL use `--system` flag only for isolated CI runners
- [ ] No arbitrary code execution in workflow scripts

### SR-CI-3: Minimal Permissions
- [ ] Workflow SHALL use `permissions: contents: read` (least privilege)
- [ ] No write permissions unless explicitly required
- [ ] Actions SHALL be pinned to specific versions (`@v4`, not `@main`)

### SR-CI-4: Security Review Standards (Non-Negotiable)
- [ ] All CRITICAL severity findings SHALL block release
- [ ] All HIGH severity findings SHALL block release
- [ ] All MEDIUM severity findings SHALL block release
- [ ] LOW severity findings SHALL be fixed OR documented with justification
- [ ] Security exceptions SHALL be tracked and reviewed in subsequent releases
- [ ] No release SHALL proceed without passing security review

---

## 7. Risk Assessment

### 7.1 Low Risk Items
- **uv compatibility**: Well-tested with Python 3.14, active development
- **pytest-xdist**: Mature library, used by major projects
- **Caching**: Standard GitHub Actions feature

### 7.2 Medium Risk Items
- **Pillow compilation**: May require system deps in each job
  - Mitigation: Install system deps only in test job
- **Coverage combination**: pytest-xdist auto-combines, but verify
  - Mitigation: Test coverage output before merge

### 7.3 Rollback Strategy
If issues arise, revert to previous ci.yml:
```bash
git revert <commit-hash>
```

The previous workflow is fully functional and tested.

---

## 8. Testing Plan

### 8.1 Pre-Implementation Validation
1. Test uv installation locally with Python 3.14
2. Verify pytest-xdist works with current test suite
3. Confirm coverage combines correctly with parallel tests

### 8.2 Implementation Validation
1. Create PR with optimized workflow
2. Verify all checks pass
3. Compare timing metrics with baseline
4. Verify coverage report is complete

### 8.3 Post-Implementation Monitoring
1. Monitor CI times for first 10 PRs
2. Track cache hit rates
3. Verify no coverage regressions

---

## 9. Implementation Checklist

### Phase 1: Workflow Restructuring
- [ ] Split ci.yml into parallel jobs
- [ ] Add `needs:` dependencies for fail-fast
- [ ] Add timeout limits to each job
- [ ] Test on feature branch

### Phase 2: Dependency Optimization
- [ ] Replace setup-python with setup-uv
- [ ] Configure uv caching
- [ ] Update pip commands to uv pip
- [ ] Verify system deps installation

### Phase 3: Test Parallelization
- [ ] Add pytest-xdist to requirements
- [ ] Update pytest configuration
- [ ] Verify coverage combination
- [ ] Benchmark test execution time

### Phase 4: Caching Enhancement
- [ ] Add mypy cache configuration
- [ ] Configure virtualenv caching
- [ ] Set appropriate cache keys
- [ ] Test cache invalidation

### Phase 5: Developer Onboarding
- [ ] Create `scripts/init.sh` initialization script
- [ ] Create `requirements-dev.txt` with all dev dependencies
- [ ] Update README.md with Quick Start section
- [ ] Test init.sh on macOS, Linux, Windows (WSL)
- [ ] Verify all tools are installed correctly
- [ ] Add init.sh to repository root scripts/

### Phase 6: Security Scanning
- [ ] Add TruffleHog secret detection job
- [ ] Add Bandit SAST job
- [ ] Add pip-audit dependency scanning job
- [ ] Configure Gitleaks pre-commit hook
- [ ] Verify blocking vs non-blocking behavior
- [ ] Test SARIF output integration

### Phase 7: Documentation Validation Integration
- [ ] Integrate doc-drift check into unified CI
- [ ] Verify markdown linting still works
- [ ] Test spell checking integration
- [ ] Confirm phase spec validation runs

### Phase 8: Release Gate Enforcement (REQUIRED)
- [ ] Create `scripts/release.sh` with security review gate
- [ ] Create `.git/hooks/pre-push` to prevent tag bypass
- [ ] Create `.github/workflows/release-validation.yml`
- [ ] Document release process in CLAUDE.md
- [ ] Test release flow end-to-end
- [ ] Ensure Claude Code CLI is documented as release requirement

---

## 10. File Changes Summary

| File | Change Type | Description |
| ---- | ----------- | ----------- |
| `.github/workflows/ci.yml` | Major | Restructure into parallel jobs with security |
| `.github/workflows/release-validation.yml` | New | Release gate validation workflow |
| `.pre-commit-config.yaml` | Minor | Add Gitleaks secret scanning hook |
| `.git/hooks/pre-push` | New | Prevent release tag bypass |
| `scripts/release.sh` | New | Mandatory release script with security review |
| `scripts/init.sh` | New | One-command developer environment setup |
| `verify.sh` | Minor | Add security checks (Gitleaks, Bandit, pip-audit) |
| `requirements.txt` | Minor | Add pytest-xdist |
| `requirements-dev.txt` | New | Development dependencies including security tools |
| `README.md` | Minor | Add Quick Start section with init.sh instructions |
| `pytest.ini` | Minor | Add parallel execution config |
| `docs/specs/CI_OPTIMIZATION_SPEC.md` | New | This specification |
| `CLAUDE.md` | Minor | Document release process requirements |

---

## 11. References

### Research Sources
- [pytest-xdist documentation](https://pytest-xdist.readthedocs.io/)
- [uv - Fast Python Package Installer](https://docs.astral.sh/uv/)
- [GitHub Actions Caching Guide](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows)
- [Fail-Fast CI Patterns](https://costops.dev/guides/slow-failures-expensive-before-cheap)

### Security Scanning Sources
- [TruffleHog - Secret Detection](https://github.com/trufflesecurity/trufflehog)
- [Gitleaks - Pre-commit Secret Scanning](https://github.com/gitleaks/gitleaks)
- [Bandit - Python SAST](https://bandit.readthedocs.io/)
- [pip-audit - Dependency Vulnerabilities](https://pypi.org/project/pip-audit/)
- [OpenSSF Scorecard](https://scorecard.dev/)

### Industry Examples
- FastAPI CI/CD pipeline structure
- Django project CI patterns
- PyPI test suite optimization (81% faster with sys.monitoring)
- LinkedIn SAST pipeline (CodeQL + Semgrep)

---

## 12. Sign-off

### 12.1 Approval Checklist

- [ ] Specification reviewed by project maintainer
- [ ] CI workflow changes approved
- [ ] Security requirements verified (SR-CI-1, SR-CI-2, SR-CI-3)
- [ ] No regressions to existing checks
- [ ] Test coverage requirements maintained (≥99%)

### 12.2 Sign-off

| Role | Name | Date | Signature |
| ---- | ---- | ---- | --------- |
| Author | Claude Code Research Team | 2026-03-15 | ✅ |
| Reviewer | | | |
| Approver | | | |

---

## 13. Document Control

| Version | Date | Author | Changes |
| ------- | ---- | ------ | ------- |
| 1.0 | 2026-03-15 | Claude Code Research Team | Initial specification |
| 1.1 | 2026-03-15 | Claude Code Research Team | Added security scanning, documentation validation, security review agent reference |

---

## Appendix A: Current vs Proposed Workflow Comparison

### Current Workflow (Sequential)
```
checkout → setup-python → apt-get → pip install → flake8 → black → mypy → pytest
[5s]       [30s]          [30s]     [90s]         [15s]    [10s]   [45s]   [120s]
                                                                            = ~5.5 min
```

### Proposed Workflow (Parallel with Fail-Fast)
```
           ┌─ lint (20s) ─────┐
format ────┤                  ├── test (60-90s)
  (15s)    └─ typecheck (45s)─┘

Total: 15 + 45 + 90 = ~2.5 min (worst case)
Fast fail: 15 sec (format error)
```

---

## Appendix B: uv vs pip Benchmark Data

| Operation | pip | uv | Speedup |
| --------- | --- | -- | ------- |
| Cold install (30 deps) | 45s | 3s | 15x |
| Warm cache | 15s | 2s | 7.5x |
| requirements.txt | 90s | 20s | 4.5x |
| Single package | 5s | 0.5s | 10x |

*Source: Real Python benchmarks, Astral documentation*
