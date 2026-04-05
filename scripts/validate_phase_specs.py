#!/usr/bin/env python3
"""Validate phase specification statuses match implementation indicators.

This script checks that phase spec documents have consistent status indicators.
It detects cases where:
- A spec shows "Planning" but has completion indicators (stale docs)
- A spec shows "Complete" but lacks completion indicators (premature status)

Usage:
    python scripts/validate_phase_specs.py [--strict]

Exit codes:
    0 - All validations passed (warnings may be present)
    1 - Errors found (strict mode) or script error

See docs/specs/DOC_AUTOMATION_SPEC.md for specification.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# Directory containing phase specifications
SPECS_DIR = Path("docs/specs")

# Patterns indicating a phase is complete
COMPLETION_PATTERNS: List[str] = [
    r"✅\s*(Complete|COMPLETED)",
    r"\*\*Status:\*\*\s*✅",
    r"Completed\s+\w+\s+\d+,?\s+\d{4}",
    r"##\s*\d+\.\s*File Size Results",
    r"##\s*\d+\.\s*Verification Results",
]

# Patterns indicating planning status
PLANNING_PATTERNS: List[str] = [
    r"📋\s*Planning",
    r"\*\*Status:\*\*\s*📋",
    r"Status:\s*Planning",
]


@dataclass
class ValidationIssue:
    """Represents a validation issue found in a spec file."""

    file: str
    severity: str  # "ERROR" or "WARN"
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: {self.file} - {self.message}"


def extract_status(content: str) -> str | None:
    """Extract the status line from spec content."""
    match = re.search(r"\*\*Status:\*\*\s*(.+?)(?:\n|$)", content)
    return match.group(1).strip() if match else None


def has_completion_indicators(content: str) -> bool:
    """Check if content has indicators of completion."""
    return any(re.search(pattern, content) for pattern in COMPLETION_PATTERNS)


def has_planning_indicators(content: str) -> bool:
    """Check if content has indicators of planning status."""
    return any(re.search(pattern, content) for pattern in PLANNING_PATTERNS)


def validate_spec_file(spec_file: Path) -> List[ValidationIssue]:
    """Validate a single spec file for status consistency."""
    issues: List[ValidationIssue] = []

    try:
        content = spec_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return [ValidationIssue(spec_file.name, "ERROR", f"Cannot read file: {e}")]

    status = extract_status(content)
    if not status:
        # No status line found, skip validation
        return []

    has_completion = has_completion_indicators(content)
    has_planning = has_planning_indicators(content)

    # Case 1: Shows "Planning" but has completion indicators
    if has_planning and has_completion:
        issues.append(
            ValidationIssue(
                spec_file.name,
                "WARN",
                "Shows 'Planning' status but has completion indicators. "
                "Consider updating status to 'Complete'.",
            )
        )

    # Case 2: Shows "Complete" but no completion indicators
    if "Complete" in status and "📋" not in status and not has_completion:
        issues.append(
            ValidationIssue(
                spec_file.name,
                "WARN",
                "Shows 'Complete' status but no completion indicators found. "
                "Verify the phase is actually complete.",
            )
        )

    return issues


def validate_all_specs() -> Tuple[List[ValidationIssue], int]:
    """Validate all phase spec files in the specs directory."""
    issues: List[ValidationIssue] = []
    files_checked = 0

    if not SPECS_DIR.exists():
        return [ValidationIssue("docs/specs", "ERROR", "Specs directory not found")], 0

    for spec_file in sorted(SPECS_DIR.glob("PHASE_*.md")):
        files_checked += 1
        issues.extend(validate_spec_file(spec_file))

    return issues, files_checked


def main() -> int:
    """Main entry point for the validation script."""
    parser = argparse.ArgumentParser(
        description="Validate phase specification statuses"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors (exit 1 on any issue)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only output errors, suppress warnings",
    )
    args = parser.parse_args()

    issues, files_checked = validate_all_specs()

    # Filter issues based on quiet mode
    if args.quiet:
        issues = [i for i in issues if i.severity == "ERROR"]

    # Print results
    if issues:
        print(f"Phase spec validation found {len(issues)} issue(s):\n")
        for issue in issues:
            print(f"  {issue}")
        print()
    else:
        print(f"✅ Phase spec validation passed ({files_checked} files checked)")

    # Determine exit code
    errors = [i for i in issues if i.severity == "ERROR"]
    warnings = [i for i in issues if i.severity == "WARN"]

    if errors:
        return 1
    if args.strict and warnings:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
