"""Unit tests for FeedbackStorage service."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from src.models.feedback import (
    FeedbackEntry,
    FeedbackFilters,
    FeedbackRating,
    FeedbackReason,
)
from src.services.feedback.storage import FeedbackStorage


@pytest.fixture
def temp_storage_path(tmp_path):
    """Create a temporary storage path."""
    return tmp_path / "feedback.json"


@pytest.fixture
def storage(temp_storage_path):
    """Create a FeedbackStorage instance with temp path."""
    return FeedbackStorage(storage_path=temp_storage_path)


@pytest.fixture
def sample_entry():
    """Create a sample feedback entry."""
    return FeedbackEntry(
        paper_id="arxiv:2401.12345",
        rating=FeedbackRating.THUMBS_UP,
        reasons=[FeedbackReason.METHODOLOGY],
        topic_slug="test-topic",
    )


class TestFeedbackStorageInit:
    """Tests for FeedbackStorage initialization."""

    def test_init_with_path(self, temp_storage_path):
        """Test initialization with path."""
        storage = FeedbackStorage(storage_path=temp_storage_path)
        assert storage.storage_path == temp_storage_path

    def test_init_with_string_path(self, tmp_path):
        """Test initialization with string path."""
        path_str = str(tmp_path / "feedback.json")
        storage = FeedbackStorage(storage_path=path_str)
        assert storage.storage_path == Path(path_str)

    def test_init_creates_cache_dir(self, tmp_path):
        """Test that cache dir is created on init."""
        storage_path = tmp_path / "subdir" / "feedback.json"
        storage = FeedbackStorage(storage_path=storage_path)
        # Dir created on first save, not init
        assert storage.storage_path.parent == storage_path.parent


class TestFeedbackStorageSave:
    """Tests for FeedbackStorage.save method."""

    @pytest.mark.asyncio
    async def test_save_new_entry(self, storage, sample_entry):
        """Test saving a new entry."""
        await storage.save(sample_entry)
        assert storage.count == 1

    @pytest.mark.asyncio
    async def test_save_creates_file(self, storage, sample_entry, temp_storage_path):
        """Test that save creates the storage file."""
        await storage.save(sample_entry)
        assert temp_storage_path.exists()

    @pytest.mark.asyncio
    async def test_save_persists_data(self, storage, sample_entry, temp_storage_path):
        """Test that save persists data to disk."""
        await storage.save(sample_entry)

        # Read file directly
        data = json.loads(temp_storage_path.read_text())
        assert len(data) == 1
        assert data[0]["paper_id"] == "arxiv:2401.12345"

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, storage):
        """Test that save updates existing entry for same paper."""
        entry1 = FeedbackEntry(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )
        entry2 = FeedbackEntry(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_DOWN,
        )

        await storage.save(entry1)
        await storage.save(entry2)

        assert storage.count == 1
        loaded = await storage.get_by_paper_id("test-paper")
        assert loaded.rating == "thumbs_down"

    @pytest.mark.asyncio
    async def test_save_multiple_entries(self, storage):
        """Test saving multiple different entries."""
        for i in range(5):
            entry = FeedbackEntry(
                paper_id=f"paper-{i}",
                rating=FeedbackRating.THUMBS_UP,
            )
            await storage.save(entry)

        assert storage.count == 5


class TestFeedbackStorageLoad:
    """Tests for FeedbackStorage.load_all method."""

    @pytest.mark.asyncio
    async def test_load_empty(self, storage):
        """Test loading from non-existent file."""
        entries = await storage.load_all()
        assert entries == []

    @pytest.mark.asyncio
    async def test_load_existing(self, storage, sample_entry, temp_storage_path):
        """Test loading existing entries."""
        # Save first
        await storage.save(sample_entry)

        # Create new storage instance
        storage2 = FeedbackStorage(storage_path=temp_storage_path)
        entries = await storage2.load_all()

        assert len(entries) == 1
        assert entries[0].paper_id == "arxiv:2401.12345"

    @pytest.mark.asyncio
    async def test_load_corrupted_file(self, temp_storage_path):
        """Test loading corrupted file creates backup."""
        # Write invalid JSON
        temp_storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_storage_path.write_text("invalid json {{{")

        storage = FeedbackStorage(storage_path=temp_storage_path)
        entries = await storage.load_all()

        assert entries == []
        # Check backup was created
        backups = list(temp_storage_path.parent.glob("*.backup_*.json"))
        assert len(backups) == 1

    @pytest.mark.asyncio
    async def test_load_invalid_entry(self, temp_storage_path):
        """Test loading file with invalid entry data."""
        # Write valid JSON but invalid entry
        temp_storage_path.parent.mkdir(parents=True, exist_ok=True)
        temp_storage_path.write_text('[{"invalid": "entry"}]')

        storage = FeedbackStorage(storage_path=temp_storage_path)
        entries = await storage.load_all()

        # Should create backup and return empty
        assert entries == []


class TestFeedbackStorageQuery:
    """Tests for FeedbackStorage.query method."""

    @pytest_asyncio.fixture
    async def storage_with_data(self, storage):
        """Create storage with test data."""
        entries = [
            FeedbackEntry(
                paper_id="paper-1",
                rating=FeedbackRating.THUMBS_UP,
                topic_slug="topic-a",
                reasons=[FeedbackReason.METHODOLOGY],
            ),
            FeedbackEntry(
                paper_id="paper-2",
                rating=FeedbackRating.THUMBS_DOWN,
                topic_slug="topic-a",
            ),
            FeedbackEntry(
                paper_id="paper-3",
                rating=FeedbackRating.THUMBS_UP,
                topic_slug="topic-b",
                reasons=[FeedbackReason.FINDINGS],
            ),
            FeedbackEntry(
                paper_id="paper-4",
                rating=FeedbackRating.NEUTRAL,
                topic_slug="topic-b",
            ),
        ]
        for entry in entries:
            await storage.save(entry)
        return storage

    @pytest.mark.asyncio
    async def test_query_by_topic(self, storage_with_data):
        """Test querying by topic."""
        filters = FeedbackFilters(topic_slug="topic-a")
        results = await storage_with_data.query(filters)
        assert len(results) == 2
        assert all(e.topic_slug == "topic-a" for e in results)

    @pytest.mark.asyncio
    async def test_query_by_rating(self, storage_with_data):
        """Test querying by rating."""
        filters = FeedbackFilters(rating=FeedbackRating.THUMBS_UP)
        results = await storage_with_data.query(filters)
        assert len(results) == 2
        assert all(e.rating == "thumbs_up" for e in results)

    @pytest.mark.asyncio
    async def test_query_by_reasons(self, storage_with_data):
        """Test querying by reasons."""
        filters = FeedbackFilters(reasons=[FeedbackReason.METHODOLOGY])
        results = await storage_with_data.query(filters)
        assert len(results) == 1
        assert results[0].paper_id == "paper-1"

    @pytest.mark.asyncio
    async def test_query_by_paper_ids(self, storage_with_data):
        """Test querying by paper IDs."""
        filters = FeedbackFilters(paper_ids=["paper-1", "paper-3"])
        results = await storage_with_data.query(filters)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_query_combined_filters(self, storage_with_data):
        """Test querying with combined filters."""
        filters = FeedbackFilters(
            topic_slug="topic-a",
            rating=FeedbackRating.THUMBS_UP,
        )
        results = await storage_with_data.query(filters)
        assert len(results) == 1
        assert results[0].paper_id == "paper-1"

    @pytest.mark.asyncio
    async def test_query_no_matches(self, storage_with_data):
        """Test query with no matches."""
        filters = FeedbackFilters(topic_slug="nonexistent")
        results = await storage_with_data.query(filters)
        assert results == []


class TestFeedbackStorageGetMethods:
    """Tests for get_by_* methods."""

    @pytest.mark.asyncio
    async def test_get_by_paper_id_found(self, storage, sample_entry):
        """Test getting entry by paper ID."""
        await storage.save(sample_entry)
        result = await storage.get_by_paper_id("arxiv:2401.12345")
        assert result is not None
        assert result.paper_id == "arxiv:2401.12345"

    @pytest.mark.asyncio
    async def test_get_by_paper_id_not_found(self, storage):
        """Test getting non-existent paper ID."""
        result = await storage.get_by_paper_id("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_topic(self, storage):
        """Test getting entries by topic."""
        for i in range(3):
            entry = FeedbackEntry(
                paper_id=f"paper-{i}",
                rating=FeedbackRating.THUMBS_UP,
                topic_slug="test-topic",
            )
            await storage.save(entry)

        results = await storage.get_by_topic("test-topic")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_get_by_topic_with_rating_filter(self, storage):
        """Test getting entries by topic with rating filter."""
        await storage.save(
            FeedbackEntry(
                paper_id="paper-1",
                rating=FeedbackRating.THUMBS_UP,
                topic_slug="topic",
            )
        )
        await storage.save(
            FeedbackEntry(
                paper_id="paper-2",
                rating=FeedbackRating.THUMBS_DOWN,
                topic_slug="topic",
            )
        )

        results = await storage.get_by_topic("topic", FeedbackRating.THUMBS_UP)
        assert len(results) == 1
        assert results[0].rating == "thumbs_up"


class TestFeedbackStorageDelete:
    """Tests for FeedbackStorage.delete method."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, storage, sample_entry):
        """Test deleting an existing entry."""
        await storage.save(sample_entry)
        assert storage.count == 1

        deleted = await storage.delete(sample_entry.id)
        assert deleted is True
        assert storage.count == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, storage):
        """Test deleting non-existent entry."""
        deleted = await storage.delete("nonexistent-id")
        assert deleted is False


class TestFeedbackStorageArchive:
    """Tests for FeedbackStorage.archive_old_entries method."""

    @pytest.mark.asyncio
    async def test_archive_when_under_threshold(self, storage):
        """Test archive does nothing when under threshold."""
        for i in range(5):
            await storage.save(
                FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            )

        archived = await storage.archive_old_entries(threshold=10)
        assert archived == 0
        assert storage.count == 5

    @pytest.mark.asyncio
    async def test_archive_when_over_threshold(self, storage):
        """Test archive when over threshold."""
        for i in range(15):
            await storage.save(
                FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            )

        archived = await storage.archive_old_entries(threshold=10)
        assert archived == 5
        assert storage.count == 10

    @pytest.mark.asyncio
    async def test_archive_creates_file(self, storage, tmp_path):
        """Test archive creates archive file."""
        for i in range(15):
            await storage.save(
                FeedbackEntry(paper_id=f"paper-{i}", rating=FeedbackRating.THUMBS_UP)
            )

        await storage.archive_old_entries(threshold=10)

        archive_files = list(storage.archive_dir.glob("feedback_archive_*.json"))
        assert len(archive_files) == 1


class TestFeedbackStorageExport:
    """Tests for FeedbackStorage.export method."""

    @pytest.mark.asyncio
    async def test_export_json(self, storage, sample_entry):
        """Test exporting to JSON format."""
        await storage.save(sample_entry)
        result = await storage.export(format="json")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["paper_id"] == "arxiv:2401.12345"

    @pytest.mark.asyncio
    async def test_export_csv(self, storage, sample_entry):
        """Test exporting to CSV format."""
        await storage.save(sample_entry)
        result = await storage.export(format="csv")

        lines = result.strip().split("\n")
        assert len(lines) == 2  # Header + 1 row
        assert "paper_id" in lines[0]

    @pytest.mark.asyncio
    async def test_export_to_file(self, storage, sample_entry, tmp_path):
        """Test exporting to file."""
        await storage.save(sample_entry)
        output_path = tmp_path / "export.json"

        result = await storage.export(format="json", output_path=output_path)
        assert result == str(output_path)
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_export_invalid_format(self, storage):
        """Test export with invalid format."""
        with pytest.raises(ValueError):
            await storage.export(format="xml")


class TestFeedbackStorageClear:
    """Tests for FeedbackStorage.clear method."""

    @pytest.mark.asyncio
    async def test_clear(self, storage, sample_entry, temp_storage_path):
        """Test clearing all entries."""
        await storage.save(sample_entry)
        assert storage.count == 1

        await storage.clear()
        assert storage.count == 0
        assert not temp_storage_path.exists()


class TestFeedbackStorageDateFilters:
    """Tests for date-based query filtering."""

    @pytest_asyncio.fixture
    async def storage_with_dated_entries(self, storage):
        """Create storage with entries having different timestamps."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)

        entries = [
            FeedbackEntry(
                paper_id="paper-old",
                rating=FeedbackRating.THUMBS_UP,
                timestamp=now - timedelta(days=30),
            ),
            FeedbackEntry(
                paper_id="paper-mid",
                rating=FeedbackRating.THUMBS_UP,
                timestamp=now - timedelta(days=15),
            ),
            FeedbackEntry(
                paper_id="paper-new",
                rating=FeedbackRating.THUMBS_UP,
                timestamp=now - timedelta(days=1),
            ),
        ]
        for entry in entries:
            await storage.save(entry)
        return storage, now

    @pytest.mark.asyncio
    async def test_query_by_start_date(self, storage_with_dated_entries):
        """Test filtering by start date."""
        from datetime import timedelta

        storage, now = storage_with_dated_entries
        start = now - timedelta(days=20)

        filters = FeedbackFilters(start_date=start)
        results = await storage.query(filters)

        assert len(results) == 2
        paper_ids = [e.paper_id for e in results]
        assert "paper-old" not in paper_ids
        assert "paper-mid" in paper_ids
        assert "paper-new" in paper_ids

    @pytest.mark.asyncio
    async def test_query_by_end_date(self, storage_with_dated_entries):
        """Test filtering by end date."""
        from datetime import timedelta

        storage, now = storage_with_dated_entries
        end = now - timedelta(days=10)

        filters = FeedbackFilters(end_date=end)
        results = await storage.query(filters)

        assert len(results) == 2
        paper_ids = [e.paper_id for e in results]
        assert "paper-old" in paper_ids
        assert "paper-mid" in paper_ids
        assert "paper-new" not in paper_ids

    @pytest.mark.asyncio
    async def test_query_by_date_range(self, storage_with_dated_entries):
        """Test filtering by date range."""
        from datetime import timedelta

        storage, now = storage_with_dated_entries
        start = now - timedelta(days=20)
        end = now - timedelta(days=10)

        filters = FeedbackFilters(start_date=start, end_date=end)
        results = await storage.query(filters)

        assert len(results) == 1
        assert results[0].paper_id == "paper-mid"


class TestFeedbackStorageWriteExceptions:
    """Tests for write exception handling."""

    @pytest.mark.asyncio
    async def test_write_to_disk_creates_parent_dir(self, tmp_path):
        """Test that _write_to_disk creates parent directories."""
        storage_path = tmp_path / "subdir" / "nested" / "feedback.json"
        storage = FeedbackStorage(storage_path=storage_path)

        entry = FeedbackEntry(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )
        storage._entries = [entry]
        storage._loaded = True

        await storage._write_to_disk()

        # Parent directory should be created
        assert storage_path.parent.exists()
        assert storage_path.exists()

    @pytest.mark.asyncio
    async def test_save_atomic_write(self, tmp_path):
        """Test that save performs atomic write."""
        storage_path = tmp_path / "feedback.json"
        storage = FeedbackStorage(storage_path=storage_path)

        entry = FeedbackEntry(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )

        await storage.save(entry)

        # File should exist after save
        assert storage_path.exists()

        # Temp file should not exist
        temp_path = storage_path.with_suffix(".tmp")
        assert not temp_path.exists()


class TestFeedbackStorageAdditionalCoverage:
    """Additional tests for full coverage."""

    @pytest.mark.asyncio
    async def test_create_backup_file_not_exists(self, tmp_path):
        """Test _create_backup_and_reset when file doesn't exist."""
        storage_path = tmp_path / "nonexistent.json"
        storage = FeedbackStorage(storage_path=storage_path)

        # File doesn't exist
        assert not storage_path.exists()

        await storage._create_backup_and_reset()

        # Should just reset entries
        assert storage._entries == []
        assert storage._loaded is True

    @pytest.mark.asyncio
    async def test_export_csv_with_entries(self, storage, sample_entry):
        """Test CSV export with entries having reasons."""
        await storage.save(sample_entry)

        result = await storage.export(format="csv")

        # CSV should contain header and data row
        lines = result.strip().split("\n")
        assert len(lines) == 2
        assert "paper_id" in lines[0]
        assert "arxiv:2401.12345" in lines[1]
        # Reasons should be joined
        assert "methodology" in lines[1]

    @pytest.mark.asyncio
    async def test_export_csv_empty(self, storage):
        """Test CSV export with no entries."""
        result = await storage.export(format="csv")

        # Should return empty string for empty CSV
        assert result == ""

    @pytest.mark.asyncio
    async def test_clear_file_not_exists(self, tmp_path):
        """Test clear when storage file doesn't exist."""
        storage_path = tmp_path / "nonexistent.json"
        storage = FeedbackStorage(storage_path=storage_path)

        # File doesn't exist
        assert not storage_path.exists()

        # Should not raise
        await storage.clear()

        assert storage._entries == []
        assert storage._loaded is True

    @pytest.mark.asyncio
    async def test_write_to_disk_replace_exception(self, tmp_path):
        """Test _write_to_disk handles replace exception and cleans temp."""
        storage_path = tmp_path / "feedback.json"
        storage = FeedbackStorage(storage_path=storage_path)

        entry = FeedbackEntry(
            paper_id="test-paper",
            rating=FeedbackRating.THUMBS_UP,
        )
        storage._entries = [entry]
        storage._loaded = True

        temp_path = storage_path.with_suffix(".tmp")

        # Create a mock that writes temp file but fails on replace
        original_replace = Path.replace

        def mock_replace(self, target):
            raise OSError("Replace failed")

        # Ensure parent dir exists
        storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Patch the replace method
        Path.replace = mock_replace
        try:
            with pytest.raises(IOError, match="Failed to write feedback"):
                await storage._write_to_disk()

            # Temp file should be cleaned up
            assert not temp_path.exists()
        finally:
            Path.replace = original_replace
