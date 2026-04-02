"""Tests for src/cli/__main__.py entry point.

This module tests the CLI entry point module.
"""

import subprocess
import sys


class TestMainEntry:
    """Tests for the __main__.py entry point."""

    def test_module_imports_app(self):
        """Test that the module imports app correctly."""
        from src.cli import app

        assert app is not None

    def test_module_can_be_imported(self):
        """Test that __main__ module can be imported without executing."""
        # This import should not raise
        import src.cli.__main__  # noqa: F401

        # The app should be importable from __main__
        from src.cli.__main__ import app

        assert app is not None

    def test_main_block_execution(self):
        """Test the __main__ block by executing directly.

        The `if __name__ == "__main__":` block is tested by running
        the module as a subprocess with --help flag.
        """
        # Run python -m src.cli --help to test the entry point
        result = subprocess.run(
            [sys.executable, "-m", "src.cli", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should exit successfully with help output
        assert result.returncode == 0
        assert "Usage" in result.stdout or "usage" in result.stdout.lower()

    def test_app_is_typer_instance(self):
        """Test that app is a Typer instance."""
        import typer
        from src.cli import app

        assert isinstance(app, typer.Typer)
