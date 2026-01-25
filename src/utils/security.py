from pathlib import Path
import re
from typing import List
import structlog

logger = structlog.get_logger()


class SecurityError(Exception):
    """Base class for security-related errors."""

    pass


class PathSanitizer:
    """Secure path validation and sanitization"""

    def __init__(self, allowed_bases: List[Path]):
        """Initialize with allowed base directories"""
        self.allowed_bases = [p.resolve() for p in allowed_bases]

    def safe_path(
        self, base_dir: Path, user_input: str, must_exist: bool = False
    ) -> Path:
        """Get safe path within base directory

        Prevents:
        - Directory traversal (../)
        - Absolute path injection
        - Symlink attacks

        Raises:
            SecurityError: If path is outside base_dir
            FileNotFoundError: If must_exist=True and path doesn't exist
        """
        # Normalize base directory
        base_dir = base_dir.resolve()

        # Check base directory is allowed
        # (This ensures we are operating within one of the approved roots)
        is_allowed = False
        for allowed in self.allowed_bases:
            if base_dir == allowed or base_dir.is_relative_to(allowed):
                is_allowed = True
                break

        if not is_allowed:  # pragma: no cover
            raise SecurityError(f"Base directory not in allowed list: {base_dir}")

        # Remove dangerous characters (null byte)
        safe_input = user_input.replace("\0", "")

        # Build requested path
        requested = (base_dir / safe_input).resolve()

        # Ensure it's within base directory
        try:
            requested.relative_to(base_dir)
        except ValueError:  # pragma: no cover
            logger.warning(
                "path_traversal_blocked",
                base_dir=str(base_dir),
                user_input=user_input,
                resolved=str(requested),
            )
            raise SecurityError(f"Path traversal attempt detected: {user_input}")

        # Check if symlink points outside base (symlink attack)
        if requested.is_symlink():
            real_path = requested.resolve()
            try:
                real_path.relative_to(base_dir)
            except ValueError:  # pragma: no cover
                raise SecurityError(
                    f"Symlink points outside base directory: {requested}"
                )

        # Optionally check existence
        if must_exist and not requested.exists():
            raise FileNotFoundError(f"Path does not exist: {requested}")

        return requested


class InputValidation:
    """Security validation for user inputs"""

    @staticmethod
    def validate_query(query: str) -> str:
        """Validate search query for injection attacks"""
        v = query.strip()

        # Check for command injection patterns
        dangerous_patterns = [
            r";\s*\w+",  # Command chaining
            r"\|\s*\w+",  # Pipe to command
            r"&&",  # AND operator
            r"\|\|",  # OR operator
            r"`[^`]+`",  # Backticks
            r"\$\([^)]+\)",  # Command substitution
            r">\s*\w+",  # Output redirection
            r"<\s*\w+",  # Input redirection
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, v):
                logger.warning(
                    "input_validation_failed",
                    query=v,
                    pattern=pattern,
                    reason="Potential injection attack",
                )
                raise ValueError(
                    "Query contains forbidden pattern that could "
                    "be used for injection"
                )

        # Enforce whitelist of allowed characters
        allowed_chars = re.compile(r'^[a-zA-Z0-9\s\-_+.,"():]+$')
        if not allowed_chars.match(v):
            # Log the character that failed
            for char in v:  # pragma: no cover
                if not re.match(r'[a-zA-Z0-9\s\-_+.,"():]', char):
                    logger.warning("invalid_char_detected", char=char, query=v)

            raise ValueError(
                "Query contains characters outside allowed set: "
                'alphanumeric, spaces, hyphens, underscores, +.,():"'
            )

        return v
