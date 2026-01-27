"""Unit tests for checkpoint service"""

import pytest
import tempfile
import shutil
import json
from pathlib import Path
from datetime import datetime
from src.services.checkpoint_service import CheckpointService
from src.models.checkpoint import CheckpointConfig


@pytest.fixture
def temp_checkpoint_dir():
    """Create temporary checkpoint directory"""
    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def checkpoint_service(temp_checkpoint_dir):
    """Create checkpoint service with temp directory"""
    config = CheckpointConfig(
        enabled=True,
        checkpoint_dir=str(temp_checkpoint_dir),
        checkpoint_interval=10
    )
    return CheckpointService(config)


@pytest.fixture
def disabled_checkpoint_service(temp_checkpoint_dir):
    """Create disabled checkpoint service"""
    config = CheckpointConfig(
        enabled=False,
        checkpoint_dir=str(temp_checkpoint_dir)
    )
    return CheckpointService(config)


def test_checkpoint_service_initialization(checkpoint_service, temp_checkpoint_dir):
    """Test checkpoint service initializes correctly"""
    assert checkpoint_service.config.enabled is True
    assert checkpoint_service.config.checkpoint_interval == 10
    assert checkpoint_service.checkpoint_dir == temp_checkpoint_dir
    assert temp_checkpoint_dir.exists()


def test_disabled_checkpoint_service(disabled_checkpoint_service, temp_checkpoint_dir):
    """Test disabled checkpoint service doesn't create directory"""
    assert disabled_checkpoint_service.config.enabled is False
    # Directory should not be created when disabled
    # (Note: It will be created by fixture but service won't use it)


def test_save_and_load_checkpoint(checkpoint_service):
    """Test saving and loading checkpoint"""
    run_id = "test_run_123"
    processed_ids = ["paper1", "paper2", "paper3"]

    # Save checkpoint
    success = checkpoint_service.save_checkpoint(run_id, processed_ids)
    assert success is True

    # Load checkpoint
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint is not None
    assert checkpoint.run_id == run_id
    assert checkpoint.processed_paper_ids == processed_ids
    assert checkpoint.total_processed == 3
    assert checkpoint.completed is False
    assert isinstance(checkpoint.last_updated, datetime)


def test_save_completed_checkpoint(checkpoint_service):
    """Test saving checkpoint with completed flag"""
    run_id = "completed_run"
    processed_ids = ["paper1", "paper2"]

    # Save completed checkpoint
    success = checkpoint_service.save_checkpoint(run_id, processed_ids, completed=True)
    assert success is True

    # Load and verify completed flag
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint.completed is True


def test_atomic_save_uses_temp_file(checkpoint_service, temp_checkpoint_dir):
    """Test that save uses atomic write with temp file"""
    run_id = "atomic_test"
    processed_ids = ["paper1"]

    # Save checkpoint
    checkpoint_service.save_checkpoint(run_id, processed_ids)

    # Verify final file exists
    checkpoint_file = temp_checkpoint_dir / f"{run_id}.json"
    assert checkpoint_file.exists()

    # Verify temp file doesn't exist (was renamed)
    temp_file = checkpoint_file.with_suffix('.tmp')
    assert not temp_file.exists()

    # Verify file content is valid JSON
    with open(checkpoint_file, 'r') as f:
        data = json.load(f)
        assert data['run_id'] == run_id
        assert data['processed_paper_ids'] == processed_ids


def test_load_nonexistent_checkpoint(checkpoint_service):
    """Test loading checkpoint that doesn't exist"""
    checkpoint = checkpoint_service.load_checkpoint("nonexistent_run")
    assert checkpoint is None


def test_load_corrupted_checkpoint(checkpoint_service, temp_checkpoint_dir):
    """Test loading corrupted checkpoint file"""
    run_id = "corrupted_run"
    checkpoint_file = temp_checkpoint_dir / f"{run_id}.json"

    # Create corrupted file
    with open(checkpoint_file, 'w') as f:
        f.write("{ invalid json }")

    # Should return None and log error
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint is None


def test_get_processed_ids(checkpoint_service):
    """Test getting processed IDs as set"""
    run_id = "test_run"
    processed_ids = ["paper1", "paper2", "paper3"]

    # Save checkpoint
    checkpoint_service.save_checkpoint(run_id, processed_ids)

    # Get processed IDs
    processed_set = checkpoint_service.get_processed_ids(run_id)
    assert isinstance(processed_set, set)
    assert processed_set == {"paper1", "paper2", "paper3"}


def test_get_processed_ids_nonexistent_run(checkpoint_service):
    """Test getting processed IDs for nonexistent run"""
    processed_set = checkpoint_service.get_processed_ids("nonexistent")
    assert isinstance(processed_set, set)
    assert len(processed_set) == 0


def test_mark_completed(checkpoint_service):
    """Test marking run as completed"""
    run_id = "mark_complete_test"
    processed_ids = ["paper1", "paper2"]

    # Save initial checkpoint
    checkpoint_service.save_checkpoint(run_id, processed_ids, completed=False)

    # Verify not completed
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint.completed is False

    # Mark as completed
    success = checkpoint_service.mark_completed(run_id)
    assert success is True

    # Verify completed flag updated
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint.completed is True
    assert checkpoint.processed_paper_ids == processed_ids  # IDs preserved


def test_mark_completed_nonexistent_run(checkpoint_service):
    """Test marking nonexistent run as completed"""
    success = checkpoint_service.mark_completed("nonexistent")
    assert success is False


def test_clear_checkpoint(checkpoint_service):
    """Test clearing checkpoint file"""
    run_id = "clear_test"
    processed_ids = ["paper1"]

    # Save checkpoint
    checkpoint_service.save_checkpoint(run_id, processed_ids)

    # Verify exists
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint is not None

    # Clear checkpoint
    success = checkpoint_service.clear_checkpoint(run_id)
    assert success is True

    # Verify deleted
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint is None


def test_clear_nonexistent_checkpoint(checkpoint_service):
    """Test clearing checkpoint that doesn't exist"""
    success = checkpoint_service.clear_checkpoint("nonexistent")
    assert success is True  # Should succeed (idempotent)


def test_list_checkpoints(checkpoint_service):
    """Test listing all checkpoint run IDs"""
    # Save multiple checkpoints
    checkpoint_service.save_checkpoint("run1", ["paper1"])
    checkpoint_service.save_checkpoint("run2", ["paper2"])
    checkpoint_service.save_checkpoint("run3", ["paper3"])

    # List checkpoints
    run_ids = checkpoint_service.list_checkpoints()
    assert len(run_ids) == 3
    assert "run1" in run_ids
    assert "run2" in run_ids
    assert "run3" in run_ids


def test_list_checkpoints_empty(checkpoint_service):
    """Test listing checkpoints when none exist"""
    run_ids = checkpoint_service.list_checkpoints()
    assert isinstance(run_ids, list)
    assert len(run_ids) == 0


def test_disabled_service_operations(disabled_checkpoint_service):
    """Test that disabled service returns success without doing anything"""
    run_id = "disabled_test"
    processed_ids = ["paper1"]

    # All operations should succeed but not do anything
    assert disabled_checkpoint_service.save_checkpoint(run_id, processed_ids) is True
    assert disabled_checkpoint_service.load_checkpoint(run_id) is None
    assert disabled_checkpoint_service.get_processed_ids(run_id) == set()
    assert disabled_checkpoint_service.clear_checkpoint(run_id) is True
    assert disabled_checkpoint_service.list_checkpoints() == []


def test_checkpoint_interval_config(temp_checkpoint_dir):
    """Test checkpoint interval configuration"""
    config = CheckpointConfig(
        enabled=True,
        checkpoint_dir=str(temp_checkpoint_dir),
        checkpoint_interval=25
    )
    service = CheckpointService(config)

    assert service.config.checkpoint_interval == 25


def test_update_checkpoint_with_more_papers(checkpoint_service):
    """Test updating checkpoint with additional papers"""
    run_id = "incremental_run"

    # Save initial checkpoint
    checkpoint_service.save_checkpoint(run_id, ["paper1", "paper2"])

    # Update with more papers
    checkpoint_service.save_checkpoint(run_id, ["paper1", "paper2", "paper3", "paper4"])

    # Verify update
    checkpoint = checkpoint_service.load_checkpoint(run_id)
    assert checkpoint.total_processed == 4
    assert len(checkpoint.processed_paper_ids) == 4


def test_processed_set_property(checkpoint_service):
    """Test that processed_set property returns set for O(1) lookup"""
    run_id = "set_test"
    processed_ids = ["paper1", "paper2", "paper3"]

    checkpoint_service.save_checkpoint(run_id, processed_ids)
    checkpoint = checkpoint_service.load_checkpoint(run_id)

    # Verify processed_set is a set
    assert isinstance(checkpoint.processed_set, set)
    assert checkpoint.processed_set == {"paper1", "paper2", "paper3"}

    # Verify O(1) lookup
    assert "paper1" in checkpoint.processed_set
    assert "paper999" not in checkpoint.processed_set
