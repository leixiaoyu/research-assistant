# Pre-Commit Hooks Documentation

## Overview

ARISP uses pre-commit hooks to enforce code quality, security, and consistency **before** code is committed to the repository. This is a critical security control (SR-7) that prevents secrets from being committed and ensures code meets quality standards.

## Installation

### First-Time Setup

```bash
# Install pre-commit
pip install pre-commit

# Install the git hook scripts
pre-commit install

# (Optional) Run against all files to verify setup
pre-commit run --all-files
```

### Verification

After installation, test that hooks are working:

```bash
# This should succeed
echo "test content" > test_file.txt
git add test_file.txt
git commit -m "test commit"

# This should FAIL (attempting to commit .env)
cp .env.template .env
echo "SEMANTIC_SCHOLAR_API_KEY=sk-test-key" >> .env
git add .env
git commit -m "bad commit"
# Expected: ERROR: Attempted to commit .env file!
```

## Hooks Configured

### 1. Secret Detection (`detect-secrets`)
**Purpose:** Prevent hardcoded API keys, tokens, passwords from being committed

**What it checks:**
- AWS keys, Azure keys, GitHub tokens
- High-entropy strings (likely secrets)
- Private keys, JWTs, API keys
- Common secret patterns

**How to handle detections:**
```bash
# If secrets are detected:
# 1. Remove the secret from the file
# 2. Move it to .env (which is gitignored)
# 3. Update code to load from environment variables
# 4. Re-attempt commit
```

**Updating baseline:**
```bash
# If you have false positives, update the baseline:
detect-secrets scan --baseline .secrets.baseline

# Review the baseline file to ensure no real secrets are excluded
```

### 2. .env File Prevention (`prevent-env-commit`)
**Purpose:** Absolute prevention of .env file commits

**What it does:**
- Scans staged files for `.env`
- Immediately rejects commit if found
- No exceptions, no bypass

### 3. Code Formatting (`black`)
**Purpose:** Ensure consistent Python code style

**Auto-fix:** Yes
**Configuration:** Default black style, 100 char line length

```bash
# Run manually:
black src/ tests/
```

### 4. Import Sorting (`isort`)
**Purpose:** Consistent import order

**Auto-fix:** Yes
**Configuration:** black-compatible profile

```bash
# Run manually:
isort src/ tests/
```

### 5. Linting (`flake8`)
**Purpose:** Catch Python code quality issues

**Auto-fix:** No (requires manual fixes)
**Configuration:** Max line length 100, ignores E203/W503 (black conflicts)

**Common issues:**
- Unused imports
- Undefined variables
- Line too long
- Missing docstrings

### 6. Type Checking (`mypy`)
**Purpose:** Static type checking for Python

**Auto-fix:** No
**Configuration:** Strict mode with `--ignore-missing-imports`

**Common issues:**
- Missing type annotations
- Type mismatches
- Incompatible return types

### 7. Security Scanning (`bandit`)
**Purpose:** Identify common security issues in Python code

**What it checks:**
- Use of `assert` (can be optimized out)
- Hardcoded passwords/tokens
- SQL injection vulnerabilities
- Shell injection risks
- Insecure random number generation
- Unsafe YAML loading

**Excluded:** Tests directory (intentionally uses potentially unsafe patterns)

### 8. File Quality Checks
**Purpose:** General file hygiene

**Checks:**
- Trailing whitespace → Auto-removed
- End of file newlines → Auto-added
- YAML syntax → Validated
- JSON syntax → Validated
- Large files (>1MB) → Rejected
- Merge conflict markers → Detected
- Mixed line endings → Fixed to LF

## Bypassing Hooks (Emergency Only)

### When to Bypass
**NEVER** bypass hooks except in true emergencies:
- Production incident requiring immediate hotfix
- Critical security patch needed urgently

### How to Bypass
```bash
# Bypass all hooks (USE WITH EXTREME CAUTION)
git commit --no-verify -m "Emergency: [reason]"
```

**IMPORTANT:** Any commit made with `--no-verify` MUST be:
1. Documented in commit message with justification
2. Reviewed immediately after commit
3. Fixed to pass all hooks in next commit

## Continuous Integration

Pre-commit hooks also run in CI/CD pipelines to catch any commits made with `--no-verify`:

```yaml
# .github/workflows/ci.yml
- name: Run pre-commit
  run: pre-commit run --all-files
```

## Troubleshooting

### Hook Installation Failed
```bash
# Reinstall
pre-commit clean
pre-commit install
```

### Hooks Taking Too Long
```bash
# Run only on changed files (default)
pre-commit run

# Skip expensive checks locally (run in CI)
SKIP=mypy git commit -m "message"
```

### False Positive in Secret Detection
```bash
# Option 1: Rephrase code to avoid detection
# Option 2: Update baseline (review carefully!)
detect-secrets scan --baseline .secrets.baseline
git add .secrets.baseline
git commit -m "Update secrets baseline"
```

### Type Errors in External Libraries
```bash
# Add to mypy ignore list in pyproject.toml
[tool.mypy]
ignore_missing_imports = true
```

## Maintenance

### Updating Hook Versions
```bash
# Check for updates
pre-commit autoupdate

# Review .pre-commit-config.yaml for version changes
git diff .pre-commit-config.yaml

# Test with all files
pre-commit run --all-files

# Commit updates
git add .pre-commit-config.yaml
git commit -m "chore: Update pre-commit hook versions"
```

### Adding New Hooks
1. Edit `.pre-commit-config.yaml`
2. Test: `pre-commit run --all-files`
3. Document in this file
4. Commit changes

## Security Compliance

**Pre-commit hooks fulfill these mandatory security requirements:**
- ✅ **SR-7:** Secret scanning enabled
- ✅ **SR-7:** Pre-commit hooks configured
- ✅ **SR-7:** Hooks prevent secret commits
- ✅ **SR-9:** Code quality enforced (linting, type checking)
- ✅ **SR-12:** Security testing (bandit scanning)

**Verification:**
```bash
# Verify hooks are installed
pre-commit run --all-files

# Check hook status
ls -la .git/hooks/pre-commit
```

## Resources

- [Pre-commit Documentation](https://pre-commit.com/)
- [detect-secrets Documentation](https://github.com/Yelp/detect-secrets)
- [Bandit Documentation](https://bandit.readthedocs.io/)
- [Black Documentation](https://black.readthedocs.io/)
- [MyPy Documentation](https://mypy.readthedocs.io/)

---

**Last Updated:** 2026-01-23
**Maintainer:** ARISP Security Team
