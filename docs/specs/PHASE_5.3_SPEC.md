# Phase 5.3: CLI Command Splitting
**Version:** 1.0
**Status:** 📋 Planning
**Timeline:** 2 days
**Dependencies:**
- Phase 5.1 Complete (LLMService Decomposition)
- Phase 5.2 Complete (ResearchPipeline Refactoring)
- All existing CLI tests passing

---

## Architecture Reference

This phase refactors the CLI layer as defined in [SYSTEM_ARCHITECTURE.md §2 CLI Layer](../SYSTEM_ARCHITECTURE.md#cli-layer).

**Architectural Gaps Addressed:**
- ❌ Gap: Single 716-line file contains all CLI commands
- ❌ Gap: Command logic mixed with orchestration code
- ❌ Gap: Difficult to test individual commands in isolation
- ❌ Gap: Legacy functions preserved alongside modern code

**Components Modified:**
- CLI: src/cli.py → New package structure

**Coverage Targets:**
- All new CLI modules: ≥99%
- Overall coverage: Maintain ≥99%

---

## 1. Executive Summary

Phase 5.3 splits the monolithic `cli.py` (716 lines) into a CLI package with dedicated modules for each command group. This improves maintainability, enables independent command testing, and allows for cleaner addition of new commands.

**What This Phase Is:**
- ✅ Extraction of CLI commands into dedicated modules.
- ✅ Creation of shared CLI utilities module.
- ✅ Removal of legacy compatibility code.
- ✅ Maintained backward compatibility for all command invocations.

**What This Phase Is NOT:**
- ❌ Adding new CLI commands.
- ❌ Changing command signatures or options.
- ❌ Modifying command behavior or output format.
- ❌ Altering notification integration logic.

**Key Achievement:** Transform 716-line CLI file into 6-7 focused modules, each <150 lines.

---

## 2. Problem Statement

### 2.1 The Monolithic CLI
`cli.py` currently contains:
1. `run` command - Full pipeline execution (~100 lines)
2. `validate` command - Configuration validation
3. `catalog` command group - Catalog management (show, stats)
4. `schedule` command group - Scheduler management
5. `health` command - Health checks
6. `synthesize` command - Manual synthesis trigger
7. `_send_notifications` helper - Notification handling (~80 lines)
8. `_process_topics` legacy function - Deprecated (~100 lines)

### 2.2 The Testing Challenge
Testing a single command requires importing the entire CLI module with all its dependencies.

### 2.3 The Legacy Burden
The `_process_topics` function is marked as legacy but remains in the codebase, adding maintenance burden.

---

## 3. Requirements

### 3.1 Command Extraction

#### REQ-5.3.1: Run Command Module
The `run` command SHALL be extracted to a dedicated module.

**Responsibilities:**
- Pipeline execution orchestration
- Progress display and result formatting
- Notification triggering

#### REQ-5.3.2: Catalog Command Module
Catalog commands SHALL be extracted to a dedicated module.

**Responsibilities:**
- `catalog show` - Display catalog contents
- `catalog stats` - Display catalog statistics
- Catalog formatting utilities

#### REQ-5.3.3: Schedule Command Module
Schedule commands SHALL be extracted to a dedicated module.

**Responsibilities:**
- `schedule start` - Start scheduler
- `schedule stop` - Stop scheduler
- `schedule status` - Check scheduler status

#### REQ-5.3.4: Health Command Module
The `health` command SHALL be extracted to a dedicated module.

**Responsibilities:**
- Service health checks
- Dependency status reporting
- Health output formatting

#### REQ-5.3.5: Synthesize Command Module
The `synthesize` command SHALL be extracted to a dedicated module.

**Responsibilities:**
- Manual synthesis triggering
- Synthesis result display

### 3.2 Shared Utilities

#### REQ-5.3.6: CLI Utilities Module
A shared utilities module SHALL provide common CLI functionality.

**Contents:**
- Configuration loading helper
- Output formatting utilities
- Error handling decorators
- Progress display utilities

### 3.3 Legacy Removal

#### REQ-5.3.7: Legacy Code Removal
The `_process_topics` function SHALL be removed.

**Rationale:**
- Marked as legacy with pragma exclusion
- ResearchPipeline provides the same functionality
- No callers in the codebase

### 3.4 Package Structure

#### REQ-5.3.8: Module Organization

```
src/cli/
├── __init__.py           # Main app, combines command groups
├── run.py                # run command
├── catalog.py            # catalog commands (show, stats)
├── schedule.py           # schedule commands
├── health.py             # health command
├── synthesize.py         # synthesize command
└── utils.py              # Shared CLI utilities
```

### 3.5 Backward Compatibility

#### REQ-5.3.9: Invocation Preservation
All existing CLI invocations SHALL continue to work unchanged.

```bash
# These MUST continue to work:
python -m src.cli run --config config/research.yaml
python -m src.cli catalog show
python -m src.cli health
```

---

## 4. Technical Design

### 4.1 Main CLI App

```python
# src/cli/__init__.py
import typer
from src.cli.run import run_command
from src.cli.catalog import catalog_app
from src.cli.schedule import schedule_app
from src.cli.health import health_command
from src.cli.synthesize import synthesize_command

app = typer.Typer(help="ARISP: Automated Research Ingestion & Synthesis Pipeline")

# Register commands
app.command(name="run")(run_command)
app.command(name="health")(health_command)
app.command(name="synthesize")(synthesize_command)

# Register sub-applications
app.add_typer(catalog_app, name="catalog")
app.add_typer(schedule_app, name="schedule")
```

### 4.2 Run Command Module

```python
# src/cli/run.py
import typer
import asyncio
from pathlib import Path

from src.cli.utils import load_config, handle_errors
from src.orchestration.research_pipeline import ResearchPipeline


@handle_errors
def run_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config", "-c",
        help="Path to research config YAML",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Validate and plan without executing",
    ),
    no_synthesis: bool = typer.Option(
        False, "--no-synthesis",
        help="Skip Knowledge Base synthesis",
    ),
):
    """Run the research pipeline based on configuration."""
    config = load_config(config_path)

    if dry_run:
        _display_dry_run(config)
        return

    pipeline = ResearchPipeline(
        config_path=config_path,
        enable_phase2=_is_phase2_enabled(config),
        enable_synthesis=not no_synthesis,
    )

    result = asyncio.run(pipeline.run())
    _display_results(result, config)
    asyncio.run(_send_notifications(result, config))
```

### 4.3 Shared Utilities

```python
# src/cli/utils.py
import typer
import functools
from pathlib import Path
from typing import Callable

from src.services.config_manager import ConfigManager, ConfigValidationError


def load_config(config_path: Path):
    """Load and validate configuration."""
    config_manager = ConfigManager(config_path=str(config_path))
    try:
        return config_manager.load_config()
    except (FileNotFoundError, ConfigValidationError) as e:
        typer.secho(f"Configuration Error: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


def handle_errors(func: Callable) -> Callable:
    """Decorator for consistent error handling."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except Exception as e:
            typer.secho(f"Error: {e}", fg=typer.colors.RED)
            raise typer.Exit(code=1)
    return wrapper


def display_success(message: str) -> None:
    """Display a success message."""
    typer.secho(message, fg=typer.colors.GREEN)


def display_warning(message: str) -> None:
    """Display a warning message."""
    typer.secho(message, fg=typer.colors.YELLOW)


def display_error(message: str) -> None:
    """Display an error message."""
    typer.secho(message, fg=typer.colors.RED)
```

---

## 5. Security Requirements (MANDATORY) 🔒

### SR-5.3.1: Input Validation
- [ ] All CLI inputs validated before use.
- [ ] Config paths sanitized with PathSanitizer.
- [ ] No command injection via CLI arguments.

### SR-5.3.2: Output Security
- [ ] No secrets displayed in CLI output.
- [ ] Error messages do not expose internal paths.
- [ ] Stack traces only in debug mode.

### SR-5.3.3: Module Security
- [ ] No credentials in CLI modules.
- [ ] All credential access via environment variables.
- [ ] No hardcoded paths or URLs.

---

## 6. Implementation Tasks

### Task 1: Create Package Structure (0.25 day)
**Files:** src/cli/__init__.py, src/cli/utils.py

1. Create directory structure.
2. Create utils module with shared helpers.
3. Set up main app file.

### Task 2: Extract Run Command (0.5 day)
**Files:** src/cli/run.py

1. Extract run command logic.
2. Extract notification helper.
3. Add comprehensive tests.

### Task 3: Extract Catalog Commands (0.25 day)
**Files:** src/cli/catalog.py

1. Extract catalog show command.
2. Extract catalog stats command.
3. Add comprehensive tests.

### Task 4: Extract Schedule Commands (0.25 day)
**Files:** src/cli/schedule.py

1. Extract schedule start/stop/status commands.
2. Add comprehensive tests.

### Task 5: Extract Health & Synthesize Commands (0.25 day)
**Files:** src/cli/health.py, src/cli/synthesize.py

1. Extract health command.
2. Extract synthesize command.
3. Add comprehensive tests.

### Task 6: Remove Legacy Code & Verify (0.5 day)
**Files:** src/cli/__init__.py, tests/

1. Remove `_process_topics` legacy function.
2. Update all imports.
3. Verify all existing tests pass.
4. Verify all CLI invocations work.

---

## 7. Verification Criteria

### 7.1 Unit Tests (New)
- `test_run_command_executes`: Run command invokes pipeline.
- `test_run_command_dry_run`: Dry run displays config without executing.
- `test_catalog_show_displays_entries`: Catalog show works.
- `test_schedule_commands_work`: Schedule start/stop/status work.
- `test_utils_load_config`: Config loading utility works.
- `test_utils_error_handling`: Error decorator works.

### 7.2 Regression Tests
- All existing CLI tests MUST pass.
- Coverage MUST remain ≥99%.

### 7.3 Integration Tests
- `test_cli_run_invocation`: `python -m src.cli run` works.
- `test_cli_catalog_invocation`: `python -m src.cli catalog show` works.
- `test_cli_help_displays`: `python -m src.cli --help` shows all commands.

---

## 8. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Breaking CLI invocations | High | Low | Comprehensive invocation tests |
| Import cycle issues | Medium | Low | Careful dependency ordering |
| Missing command options | Low | Low | Regression test all options |

---

## 9. File Size Targets

| File | Current | Target |
|------|---------|--------|
| cli.py | 716 lines | Deprecated (re-export only) |
| cli/__init__.py | N/A | <50 lines |
| cli/run.py | N/A | <150 lines |
| cli/catalog.py | N/A | <100 lines |
| cli/schedule.py | N/A | <100 lines |
| cli/health.py | N/A | <80 lines |
| cli/synthesize.py | N/A | <80 lines |
| cli/utils.py | N/A | <100 lines |
