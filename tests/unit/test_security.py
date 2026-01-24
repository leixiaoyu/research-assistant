import pytest
from pathlib import Path
from src.utils.security import PathSanitizer, InputValidation, SecurityError

def test_path_sanitizer_valid(tmp_path):
    sanitizer = PathSanitizer(allowed_bases=[tmp_path])
    
    # Valid child
    child = tmp_path / "child.txt"
    safe = sanitizer.safe_path(tmp_path, "child.txt")
    assert safe == child.resolve()
    
    # Valid subdirectory
    subdir = tmp_path / "subdir" / "file.txt"
    safe = sanitizer.safe_path(tmp_path, "subdir/file.txt")
    assert safe == subdir.resolve()

def test_path_sanitizer_traversal(tmp_path):
    sanitizer = PathSanitizer(allowed_bases=[tmp_path])
    
    # Simple traversal
    with pytest.raises(SecurityError):
        sanitizer.safe_path(tmp_path, "../outside.txt")
        
    # Root traversal
    with pytest.raises(SecurityError):
        sanitizer.safe_path(tmp_path, "/etc/passwd")

def test_path_sanitizer_base_check(tmp_path):
    # Base not in allowed list
    other_path = Path("/tmp/other")
    sanitizer = PathSanitizer(allowed_bases=[tmp_path])
    
    with pytest.raises(SecurityError):
        sanitizer.safe_path(other_path, "file.txt")

def test_input_validation_query():
    # Valid
    assert InputValidation.validate_query("machine learning") == "machine learning"
    assert InputValidation.validate_query("AI AND Robotics") == "AI AND Robotics" 
    
    # Invalid character &
    with pytest.raises(ValueError):
        InputValidation.validate_query("AI & Robotics")

    # Command injection
    with pytest.raises(ValueError):
        InputValidation.validate_query("test; rm -rf /")

    with pytest.raises(ValueError):
        InputValidation.validate_query("$(whoami)")
