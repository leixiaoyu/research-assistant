"""Unit tests for Phase 8 DRA CLI trajectories commands."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from src.cli import app
from src.cli.trajectories import (
    trajectories_app,
    _export_jsonl,
    _export_json,
    _export_csv,
    _get_storage_dir,
)

runner = CliRunner()


class TestTrajectoriesAppRegistration:
    """Tests for trajectories sub-application registration."""

    def test_trajectories_app_registered(self):
        """Test trajectories_app is registered with main app."""
        result = runner.invoke(app, ["trajectories", "--help"])
        assert result.exit_code == 0
        assert "Trajectory management" in result.stdout

    def test_trajectories_list_command_exists(self):
        """Test list subcommand exists."""
        result = runner.invoke(app, ["trajectories", "list", "--help"])
        assert result.exit_code == 0
        assert "List all recorded trajectories" in result.stdout

    def test_trajectories_analyze_command_exists(self):
        """Test analyze subcommand exists."""
        result = runner.invoke(app, ["trajectories", "analyze", "--help"])
        assert result.exit_code == 0
        assert "Analyze trajectory patterns" in result.stdout

    def test_trajectories_export_command_exists(self):
        """Test export subcommand exists."""
        result = runner.invoke(app, ["trajectories", "export", "--help"])
        assert result.exit_code == 0
        assert "Export trajectories" in result.stdout

    def test_trajectories_stats_command_exists(self):
        """Test stats subcommand exists."""
        result = runner.invoke(app, ["trajectories", "stats", "--help"])
        assert result.exit_code == 0
        assert "Show trajectory storage statistics" in result.stdout

    def test_trajectories_clear_command_exists(self):
        """Test clear subcommand exists."""
        result = runner.invoke(app, ["trajectories", "clear", "--help"])
        assert result.exit_code == 0
        assert "Clear recorded trajectories" in result.stdout


class TestGetStorageDir:
    """Tests for _get_storage_dir helper."""

    @patch("src.cli.trajectories.load_config")
    def test_uses_default_when_no_config(self, mock_load_config):
        """Test default storage directory when config missing."""
        mock_config = MagicMock()
        mock_config.settings = MagicMock()
        mock_config.settings.dra_settings = None
        mock_load_config.return_value = mock_config

        storage_dir = _get_storage_dir(Path("config.yaml"))

        assert storage_dir == Path("./data/dra/trajectories")

    @patch("src.cli.trajectories.load_config")
    def test_uses_config_value(self, mock_load_config):
        """Test uses storage directory from config."""
        mock_config = MagicMock()
        mock_config.settings.dra_settings.trajectory_dir = "/custom/path"
        mock_load_config.return_value = mock_config

        storage_dir = _get_storage_dir(Path("config.yaml"))

        assert storage_dir == Path("/custom/path")


class TestListCommand:
    """Tests for trajectories list command."""

    @patch("src.cli.trajectories.load_config")
    def test_list_no_storage_dir(self, mock_load_config, tmp_path):
        """Test list command with missing storage directory."""
        mock_config = MagicMock()
        mock_config.settings.dra_settings = None
        mock_load_config.return_value = mock_config

        # Use a non-existent path
        with patch(
            "src.cli.trajectories._get_storage_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = runner.invoke(trajectories_app, ["list"])

        assert result.exit_code == 0
        assert "Trajectory storage not found" in result.stdout

    def test_list_empty_trajectories(self, tmp_path):
        """Test list command with no trajectories."""
        # Create empty storage dir
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = []

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["list"])

        assert result.exit_code == 0
        assert "No trajectories found" in result.stdout

    def test_list_with_trajectories(self, tmp_path):
        """Test list command displays trajectories."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        # Create mock trajectory
        mock_traj = MagicMock()
        mock_traj.trajectory_id = "test_trajectory_123"
        mock_traj.question = "How does attention work?"
        mock_traj.answer = "Attention uses Q, K, V matrices."
        mock_traj.quality_score = 0.85
        mock_traj.turns = [MagicMock()] * 5
        mock_traj.papers_opened = 3
        mock_traj.unique_searches = 2
        mock_traj.find_operations = 1
        mock_traj.context_length_tokens = 5000
        mock_traj.created_at = datetime.now(UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["list"])

        assert result.exit_code == 0
        assert "test_trajectory_123" in result.stdout
        assert "How does attention" in result.stdout
        assert "0.85" in result.stdout

    def test_list_with_details_flag(self, tmp_path):
        """Test list command with --details flag."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()
        mock_traj.trajectory_id = "traj_1"
        mock_traj.question = "Test question"
        mock_traj.answer = "Test answer"
        mock_traj.quality_score = 0.8
        mock_traj.turns = [MagicMock()] * 3
        mock_traj.papers_opened = 2
        mock_traj.unique_searches = 4
        mock_traj.find_operations = 2
        mock_traj.context_length_tokens = 8000
        mock_traj.created_at = datetime.now(UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["list", "--details"])

        assert result.exit_code == 0
        assert "Unique searches: 4" in result.stdout
        assert "Find operations: 2" in result.stdout
        assert "Context tokens: 8,000" in result.stdout


class TestAnalyzeCommand:
    """Tests for trajectories analyze command."""

    @patch("src.cli.trajectories.load_config")
    def test_analyze_no_storage_dir(self, mock_load_config, tmp_path):
        """Test analyze command with missing storage directory."""
        mock_config = MagicMock()
        mock_config.settings.dra_settings = None
        mock_load_config.return_value = mock_config

        with patch(
            "src.cli.trajectories._get_storage_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = runner.invoke(trajectories_app, ["analyze"])

        assert result.exit_code == 0
        assert "Trajectory storage not found" in result.stdout

    def test_analyze_no_quality_trajectories(self, tmp_path):
        """Test analyze command with no quality trajectories."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = []

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["analyze"])

        assert result.exit_code == 0
        assert "No quality trajectories found" in result.stdout

    def test_analyze_with_insights(self, tmp_path):
        """Test analyze command generates insights."""
        from src.models.dra import ContextualTip, TrajectoryInsights

        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()

        mock_insights = TrajectoryInsights(
            effective_query_patterns=["attention", "transformer", "bert"],
            successful_sequences=["search -> open -> find"],
            average_turns_to_success=8.5,
            paper_consultation_patterns={"methods": 10, "results": 8},
        )

        mock_tips = [
            ContextualTip(
                context="When searching",
                strategy="Use specific terms",
                confidence=0.85,
            )
        ]

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]
        mock_collector.analyze_patterns.return_value = mock_insights
        mock_collector.generate_contextual_tips.return_value = mock_tips

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["analyze"])

        assert result.exit_code == 0
        assert "Trajectory Analysis Results" in result.stdout
        assert "Effective Query Patterns" in result.stdout
        assert "attention" in result.stdout
        assert "8.5" in result.stdout
        assert "Learning Tips Generated" in result.stdout

    def test_analyze_output_to_file(self, tmp_path):
        """Test analyze command outputs to file."""
        from src.models.dra import TrajectoryInsights

        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()

        mock_insights = TrajectoryInsights(
            effective_query_patterns=["test"],
            average_turns_to_success=5.0,
        )

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]
        mock_collector.analyze_patterns.return_value = mock_insights
        mock_collector.generate_contextual_tips.return_value = []

        output_file = tmp_path / "analysis.json"

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(
                    trajectories_app, ["analyze", "--output", str(output_file)]
                )

        assert result.exit_code == 0
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "insights" in data
        assert "analyzed_at" in data


class TestExportCommand:
    """Tests for trajectories export command."""

    @patch("src.cli.trajectories.load_config")
    def test_export_no_storage_dir(self, mock_load_config, tmp_path):
        """Test export command with missing storage directory."""
        mock_config = MagicMock()
        mock_config.settings.dra_settings = None
        mock_load_config.return_value = mock_config

        output_file = tmp_path / "export.jsonl"

        with patch(
            "src.cli.trajectories._get_storage_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = runner.invoke(
                trajectories_app, ["export", "--output", str(output_file)]
            )

        assert result.exit_code == 0
        assert "Trajectory storage not found" in result.stdout

    def test_export_invalid_format(self, tmp_path):
        """Test export command with invalid format."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        output_file = tmp_path / "export.txt"

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            result = runner.invoke(
                trajectories_app,
                ["export", "--output", str(output_file), "--format", "invalid"],
            )

        assert result.exit_code == 1
        assert "Invalid format" in result.stdout


class TestExportHelpers:
    """Tests for export helper functions."""

    def test_export_jsonl(self, tmp_path):
        """Test JSONL export format."""
        from src.models.dra import ToolCall, ToolCallType, Turn, TrajectoryRecord

        traj = TrajectoryRecord(
            trajectory_id="test_001",
            question="Test question?",
            answer="Test answer.",
            turns=[
                Turn(
                    turn_number=1,
                    reasoning="Searching for papers",
                    action=ToolCall(
                        tool=ToolCallType.SEARCH,
                        arguments={"query": "test"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Found 5 results",
                    observation_tokens=100,
                )
            ],
            quality_score=0.8,
            papers_opened=2,
            unique_searches=1,
            find_operations=0,
            context_length_tokens=500,
            created_at=datetime.now(UTC),
        )

        output_file = tmp_path / "export.jsonl"
        _export_jsonl([traj], output_file)

        assert output_file.exists()
        content = output_file.read_text()
        data = json.loads(content.strip())

        assert data["id"] == "test_001"
        assert data["quality_score"] == 0.8
        assert len(data["conversations"]) == 3  # system, human, gpt

    def test_export_json(self, tmp_path):
        """Test JSON export format."""
        from src.models.dra import ToolCall, ToolCallType, Turn, TrajectoryRecord

        traj = TrajectoryRecord(
            trajectory_id="test_002",
            question="Another question?",
            answer="Another answer.",
            turns=[
                Turn(
                    turn_number=1,
                    reasoning="Opening paper",
                    action=ToolCall(
                        tool=ToolCallType.OPEN,
                        arguments={"paper_id": "paper1"},
                        timestamp=datetime.now(UTC),
                    ),
                    observation="Paper content...",
                    observation_tokens=200,
                )
            ],
            quality_score=0.9,
            papers_opened=1,
            unique_searches=0,
            find_operations=0,
            context_length_tokens=300,
            created_at=datetime.now(UTC),
        )

        output_file = tmp_path / "export.json"
        _export_json([traj], output_file)

        assert output_file.exists()
        data = json.loads(output_file.read_text())

        assert len(data) == 1
        assert data[0]["trajectory_id"] == "test_002"
        assert data[0]["quality_score"] == 0.9
        assert len(data[0]["turns"]) == 1

    def test_export_csv(self, tmp_path):
        """Test CSV export format."""
        from src.models.dra import TrajectoryRecord

        traj = TrajectoryRecord(
            trajectory_id="test_003",
            question="CSV question?",
            answer="CSV answer.",
            turns=[],
            quality_score=0.75,
            papers_opened=5,
            unique_searches=3,
            find_operations=2,
            context_length_tokens=1000,
            created_at=datetime.now(UTC),
        )

        output_file = tmp_path / "export.csv"
        _export_csv([traj], output_file)

        assert output_file.exists()
        content = output_file.read_text()
        lines = content.strip().split("\n")

        assert len(lines) == 2  # header + 1 data row
        assert "trajectory_id" in lines[0]
        assert "test_003" in lines[1]
        assert "0.750" in lines[1]


class TestStatsCommand:
    """Tests for trajectories stats command."""

    @patch("src.cli.trajectories.load_config")
    def test_stats_no_storage_dir(self, mock_load_config, tmp_path):
        """Test stats command with missing storage directory."""
        mock_config = MagicMock()
        mock_config.settings.dra_settings = None
        mock_load_config.return_value = mock_config

        with patch(
            "src.cli.trajectories._get_storage_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = runner.invoke(trajectories_app, ["stats"])

        assert result.exit_code == 0
        assert "Trajectory storage not found" in result.stdout

    def test_stats_empty_storage(self, tmp_path):
        """Test stats command with empty storage."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = []

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["stats"])

        assert result.exit_code == 0
        assert "No trajectories found" in result.stdout

    def test_stats_with_data(self, tmp_path):
        """Test stats command displays statistics."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        # Create mock files
        (storage_dir / "traj1.json").write_text("{}")
        (storage_dir / "traj2.json").write_text("{}")

        # Create mock trajectories
        mock_traj1 = MagicMock()
        mock_traj1.answer = "Answer 1"
        mock_traj1.quality_score = 0.8
        mock_traj1.turns = [MagicMock()] * 5
        mock_traj1.context_length_tokens = 1000
        mock_traj1.created_at = datetime(2024, 1, 1, tzinfo=UTC)

        mock_traj2 = MagicMock()
        mock_traj2.answer = None
        mock_traj2.quality_score = 0.3
        mock_traj2.turns = [MagicMock()] * 10
        mock_traj2.context_length_tokens = 2000
        mock_traj2.created_at = datetime(2024, 1, 15, tzinfo=UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj1, mock_traj2]

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["stats"])

        assert result.exit_code == 0
        assert "Trajectory Storage Statistics" in result.stdout
        assert "Total trajectories: 2" in result.stdout
        assert "With answers: 1" in result.stdout


class TestClearCommand:
    """Tests for trajectories clear command."""

    @patch("src.cli.trajectories.load_config")
    def test_clear_no_storage_dir(self, mock_load_config, tmp_path):
        """Test clear command with missing storage directory."""
        mock_config = MagicMock()
        mock_config.settings.dra_settings = None
        mock_load_config.return_value = mock_config

        with patch(
            "src.cli.trajectories._get_storage_dir",
            return_value=tmp_path / "nonexistent",
        ):
            result = runner.invoke(trajectories_app, ["clear"])

        assert result.exit_code == 0
        assert "No trajectory storage found" in result.stdout

    def test_clear_empty_storage(self, tmp_path):
        """Test clear command with empty storage."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            result = runner.invoke(trajectories_app, ["clear"])

        assert result.exit_code == 0
        assert "No trajectory files to clear" in result.stdout

    def test_clear_with_force(self, tmp_path):
        """Test clear command with --force flag."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()
        (storage_dir / "traj1.json").write_text("{}")
        (storage_dir / "traj2.json").write_text("{}")

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            result = runner.invoke(trajectories_app, ["clear", "--force"])

        assert result.exit_code == 0
        assert "Cleared 2 trajectory file(s)" in result.stdout
        assert not (storage_dir / "traj1.json").exists()
        assert not (storage_dir / "traj2.json").exists()

    def test_clear_aborted(self, tmp_path):
        """Test clear command aborted when not confirmed."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()
        (storage_dir / "traj1.json").write_text("{}")

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            result = runner.invoke(trajectories_app, ["clear"], input="n\n")

        assert result.exit_code == 0
        assert "Aborted" in result.stdout
        # File should still exist
        assert (storage_dir / "traj1.json").exists()

    def test_clear_older_than(self, tmp_path):
        """Test clear command with --older-than filter."""
        import os
        import time

        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        # Create old file (modify mtime to be 40 days ago)
        old_file = storage_dir / "old_traj.json"
        old_file.write_text("{}")
        old_time = time.time() - (40 * 24 * 60 * 60)  # 40 days ago
        os.utime(old_file, (old_time, old_time))

        # Create new file
        new_file = storage_dir / "new_traj.json"
        new_file.write_text("{}")

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            result = runner.invoke(
                trajectories_app, ["clear", "--force", "--older-than", "30"]
            )

        assert result.exit_code == 0
        assert "Cleared 1 trajectory file(s)" in result.stdout
        assert not old_file.exists()
        assert new_file.exists()


class TestMinQualityFilter:
    """Tests for --min-quality filter across commands."""

    def test_list_min_quality_filter(self, tmp_path):
        """Test list respects min-quality filter."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = []

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                runner.invoke(trajectories_app, ["list", "--min-quality", "0.8"])

        # Verify filter_quality was called with correct min_quality
        mock_collector.filter_quality.assert_called_once()
        call_kwargs = mock_collector.filter_quality.call_args[1]
        assert call_kwargs["min_quality_score"] == 0.8


class TestExportWithTrajectories:
    """Tests for export command with actual trajectory data."""

    def test_export_jsonl_format(self, tmp_path):
        """Test export command with JSONL format."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()
        mock_traj.trajectory_id = "export_test_1"
        mock_traj.question = "Test export question?"
        mock_traj.answer = "Test export answer."
        mock_traj.quality_score = 0.85
        mock_traj.turns = []
        mock_traj.papers_opened = 2
        mock_traj.unique_searches = 1
        mock_traj.find_operations = 0
        mock_traj.context_length_tokens = 1000
        mock_traj.created_at = datetime.now(UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]

        output_file = tmp_path / "export.jsonl"

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(
                    trajectories_app,
                    ["export", "--output", str(output_file), "--format", "jsonl"],
                )

        assert result.exit_code == 0
        assert "Exported 1 trajectories" in result.stdout

    def test_export_json_format(self, tmp_path):
        """Test export command with JSON format."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()
        mock_traj.trajectory_id = "export_test_2"
        mock_traj.question = "Test JSON export?"
        mock_traj.answer = "JSON answer."
        mock_traj.quality_score = 0.9
        mock_traj.turns = []
        mock_traj.papers_opened = 3
        mock_traj.unique_searches = 2
        mock_traj.find_operations = 1
        mock_traj.context_length_tokens = 2000
        mock_traj.created_at = datetime.now(UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]

        output_file = tmp_path / "export.json"

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(
                    trajectories_app,
                    ["export", "--output", str(output_file), "--format", "json"],
                )

        assert result.exit_code == 0
        assert "Exported 1 trajectories" in result.stdout

    def test_export_csv_format(self, tmp_path):
        """Test export command with CSV format."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()
        mock_traj.trajectory_id = "export_test_3"
        mock_traj.question = "Test CSV export?"
        mock_traj.answer = "CSV answer."
        mock_traj.quality_score = 0.75
        mock_traj.turns = []
        mock_traj.papers_opened = 1
        mock_traj.unique_searches = 1
        mock_traj.find_operations = 0
        mock_traj.context_length_tokens = 500
        mock_traj.created_at = datetime.now(UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]

        output_file = tmp_path / "export.csv"

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(
                    trajectories_app,
                    ["export", "--output", str(output_file), "--format", "csv"],
                )

        assert result.exit_code == 0
        assert "Exported 1 trajectories" in result.stdout

    def test_export_no_matching_trajectories(self, tmp_path):
        """Test export with no matching trajectories."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = []

        output_file = tmp_path / "export.jsonl"

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(
                    trajectories_app, ["export", "--output", str(output_file)]
                )

        assert result.exit_code == 0
        assert "No trajectories found" in result.stdout


class TestExceptionHandling:
    """Tests for exception handling paths."""

    def test_list_exception_handling(self, tmp_path):
        """Test list command exception handling."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                side_effect=Exception("Test error"),
            ):
                result = runner.invoke(trajectories_app, ["list"])

        assert result.exit_code == 1
        assert "Failed to list trajectories" in result.stdout

    def test_analyze_exception_handling(self, tmp_path):
        """Test analyze command exception handling."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                side_effect=Exception("Analysis error"),
            ):
                result = runner.invoke(trajectories_app, ["analyze"])

        assert result.exit_code == 1
        assert "Failed to analyze trajectories" in result.stdout

    def test_export_exception_handling(self, tmp_path):
        """Test export command exception handling."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        output_file = tmp_path / "export.jsonl"

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                side_effect=Exception("Export error"),
            ):
                result = runner.invoke(
                    trajectories_app, ["export", "--output", str(output_file)]
                )

        assert result.exit_code == 1
        assert "Failed to export trajectories" in result.stdout

    def test_stats_exception_handling(self, tmp_path):
        """Test stats command exception handling."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                side_effect=Exception("Stats error"),
            ):
                result = runner.invoke(trajectories_app, ["stats"])

        assert result.exit_code == 1
        assert "Failed to get trajectory stats" in result.stdout


class TestListDetailedOutput:
    """Tests for list command detailed output paths."""

    def test_list_with_long_answer(self, tmp_path):
        """Test list command truncates long answers in details."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()
        mock_traj.trajectory_id = "long_answer_traj"
        mock_traj.question = "Question with long answer?"
        mock_traj.answer = "A" * 150  # Long answer > 100 chars
        mock_traj.quality_score = 0.8
        mock_traj.turns = [MagicMock()] * 5
        mock_traj.papers_opened = 2
        mock_traj.unique_searches = 3
        mock_traj.find_operations = 1
        mock_traj.context_length_tokens = 5000
        mock_traj.created_at = datetime.now(UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["list", "--details"])

        assert result.exit_code == 0
        assert "..." in result.stdout  # Truncated answer

    def test_list_with_short_answer(self, tmp_path):
        """Test list command shows full short answers."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        mock_traj = MagicMock()
        mock_traj.trajectory_id = "short_answer_traj"
        mock_traj.question = "Short question?"
        mock_traj.answer = "Short answer"  # < 100 chars
        mock_traj.quality_score = 0.9
        mock_traj.turns = [MagicMock()] * 3
        mock_traj.papers_opened = 1
        mock_traj.unique_searches = 1
        mock_traj.find_operations = 0
        mock_traj.context_length_tokens = 2000
        mock_traj.created_at = datetime.now(UTC)

        mock_collector = MagicMock()
        mock_collector.filter_quality.return_value = [mock_traj]

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch(
                "src.cli.trajectories.TrajectoryCollector",
                return_value=mock_collector,
            ):
                result = runner.invoke(trajectories_app, ["list", "--details"])

        assert result.exit_code == 0
        assert "Short answer" in result.stdout


class TestClearEdgeCases:
    """Tests for clear command edge cases."""

    def test_clear_no_old_files_with_older_than(self, tmp_path):
        """Test clear with older-than but no old files."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()

        # Create only new files
        new_file = storage_dir / "new_traj.json"
        new_file.write_text("{}")

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            result = runner.invoke(
                trajectories_app, ["clear", "--force", "--older-than", "30"]
            )

        assert result.exit_code == 0
        assert "No trajectories older than" in result.stdout
        assert new_file.exists()

    def test_clear_file_deletion_error(self, tmp_path):
        """Test clear handles file deletion errors gracefully."""
        storage_dir = tmp_path / "trajectories"
        storage_dir.mkdir()
        test_file = storage_dir / "test.json"
        test_file.write_text("{}")

        with patch("src.cli.trajectories._get_storage_dir", return_value=storage_dir):
            with patch("pathlib.Path.unlink", side_effect=PermissionError("No access")):
                result = runner.invoke(trajectories_app, ["clear", "--force"])

        assert result.exit_code == 0
        assert "Failed to delete" in result.stdout
