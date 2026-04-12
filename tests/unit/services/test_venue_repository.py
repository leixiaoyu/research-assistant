"""Unit tests for VenueRepository.

Tests venue score loading, normalization, matching, and error handling.
Target: ≥99% coverage
"""

from pathlib import Path

import pytest
import yaml

from src.services.venue_repository import YamlVenueRepository


class TestYamlVenueRepositoryInit:
    """Test repository initialization."""

    def test_init_default_path(self) -> None:
        """Test initialization with default path."""
        repo = YamlVenueRepository()

        # Should use project's venue_scores.yaml
        assert repo._yaml_path.name == "venue_scores.yaml"
        assert repo._yaml_path.exists()
        assert repo._default_score == 0.5

    def test_init_custom_path(self, tmp_path: Path) -> None:
        """Test initialization with custom path."""
        custom_path = tmp_path / "custom_venues.yaml"
        custom_path.write_text("venues:\n  test: 20\n")

        repo = YamlVenueRepository(yaml_path=custom_path)

        assert repo._yaml_path == custom_path.resolve()
        assert repo._default_score == 0.5

    def test_init_custom_default_score(self) -> None:
        """Test initialization with custom default score."""
        repo = YamlVenueRepository(default_score=0.7)

        assert repo._default_score == 0.7

    def test_init_invalid_default_score_too_low(self) -> None:
        """Test initialization rejects default score < 0."""
        with pytest.raises(ValueError, match="default_score must be in"):
            YamlVenueRepository(default_score=-0.1)

    def test_init_invalid_default_score_too_high(self) -> None:
        """Test initialization rejects default score > 1."""
        with pytest.raises(ValueError, match="default_score must be in"):
            YamlVenueRepository(default_score=1.1)

    def test_init_lazy_loading(self, tmp_path: Path) -> None:
        """Test venues are not loaded on init (lazy loading)."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues:\n  test: 20\n")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Should not load until first access
        assert repo._venues is None


class TestYamlVenueRepositoryGetScore:
    """Test get_score method."""

    def test_get_score_exact_match(self, tmp_path: Path) -> None:
        """Test exact match on normalized venue name."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "default_score": 15,
            "venues": {
                "neurips": 30,
                "acl": 30,
            },
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Exact match (case-insensitive)
        assert repo.get_score("neurips") == 1.0
        assert repo.get_score("NeurIPS") == 1.0
        assert repo.get_score("NEURIPS") == 1.0

    def test_get_score_substring_match(self, tmp_path: Path) -> None:
        """Test substring matching for complex venue names."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "venues": {
                "acl": 30,
                "neurips": 30,
                "neural information processing systems": 30,  # Add full name
            }
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Substring matches
        assert repo.get_score("ACL 2024") == 1.0
        assert repo.get_score("Proceedings of ACL") == 1.0
        assert repo.get_score("NeurIPS 2023") == 1.0
        assert (
            repo.get_score("Conference on Neural Information Processing Systems") == 1.0
        )

    def test_get_score_normalization_removes_digits(self, tmp_path: Path) -> None:
        """Test normalization removes digits."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"acl": 30}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Should match despite digits
        assert repo.get_score("ACL 2024") == 1.0
        assert repo.get_score("ACL2024") == 1.0

    def test_get_score_normalization_removes_special_chars(
        self, tmp_path: Path
    ) -> None:
        """Test normalization removes special characters."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"acl": 30}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Should match despite special chars
        assert repo.get_score("ACL: 2024") == 1.0
        assert repo.get_score("ACL (Annual Conference)") == 1.0

    def test_get_score_normalization_removes_common_words(self, tmp_path: Path) -> None:
        """Test normalization removes common words."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"acl": 30}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Should match despite common words
        assert repo.get_score("Proceedings of the ACL Conference") == 1.0
        assert repo.get_score("International Conference on ACL") == 1.0
        assert repo.get_score("Journal of ACL") == 1.0

    def test_get_score_prefers_longest_substring_match(self, tmp_path: Path) -> None:
        """Test substring matching prefers longest match."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "venues": {
                "computer vision": 20,
                "computer vision pattern recognition": 28,
            }
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Should match longer key
        score = repo.get_score("Conference on Computer Vision and Pattern Recognition")
        # Normalized: "computer vision pattern recognition" -> 28/30 = 0.9333...
        assert abs(score - (28 / 30)) < 0.01

    def test_get_score_substring_match_logging(self, tmp_path: Path) -> None:
        """Test substring matching with logging (covers lines 157-169)."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "venues": {
                "machine learning": 25,
                "ai": 20,
            }
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Query that won't match exactly but will match via substring
        # "international conference machine learning systems" normalizes to
        # "machine learning systems" which contains "machine learning"
        score = repo.get_score("International Conference on Machine Learning Systems")
        # Should substring match "machine learning" -> 25/30
        assert abs(score - (25 / 30)) < 0.01

    def test_get_score_unknown_venue_returns_default(self, tmp_path: Path) -> None:
        """Test unknown venue returns default score."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"neurips": 30}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path, default_score=0.6)

        assert repo.get_score("unknown venue") == 0.6

    def test_get_score_empty_string_returns_default(self, tmp_path: Path) -> None:
        """Test empty venue name returns default."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"neurips": 30}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path, default_score=0.5)

        assert repo.get_score("") == 0.5

    def test_get_score_normalizes_to_0_1_scale(self, tmp_path: Path) -> None:
        """Test scores are normalized from 0-30 to 0-1."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "venues": {
                "top_venue": 30,
                "good_venue": 25,
                "medium_venue": 20,
                "default_venue": 15,
                "low_venue": 10,
                "zero_venue": 0,
            }
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        assert repo.get_score("top_venue") == 1.0
        assert abs(repo.get_score("good_venue") - (25 / 30)) < 0.01
        assert abs(repo.get_score("medium_venue") - (20 / 30)) < 0.01
        assert repo.get_score("default_venue") == 0.5
        assert abs(repo.get_score("low_venue") - (10 / 30)) < 0.01
        assert repo.get_score("zero_venue") == 0.0

    def test_get_score_arxiv_updated_to_15(self) -> None:
        """Test ArXiv score is 15 (0.5 normalized) in production YAML."""
        repo = YamlVenueRepository()

        arxiv_score = repo.get_score("arxiv")
        expected_score = 15 / 30  # 0.5

        assert abs(arxiv_score - expected_score) < 0.01

    def test_get_score_caches_loaded_venues(self, tmp_path: Path) -> None:
        """Test venues are cached after first load."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"test": 20}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # First call loads
        assert repo._venues is None
        repo.get_score("test")
        assert repo._venues is not None

        # Second call uses cache
        cached_venues = repo._venues
        repo.get_score("test")
        assert repo._venues is cached_venues  # Same object


class TestYamlVenueRepositoryGetDefaultScore:
    """Test get_default_score method."""

    def test_get_default_score_returns_configured_value(self) -> None:
        """Test returns the configured default score."""
        repo = YamlVenueRepository(default_score=0.7)
        assert repo.get_default_score() == 0.7

    def test_get_default_score_default_is_0_5(self) -> None:
        """Test default score is 0.5 when not specified."""
        repo = YamlVenueRepository()
        assert repo.get_default_score() == 0.5


class TestYamlVenueRepositoryReload:
    """Test reload method."""

    def test_reload_clears_cache_and_reloads(self, tmp_path: Path) -> None:
        """Test reload clears cache and loads fresh data."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"test": 20}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Load initial data
        repo.get_score("test")
        old_venues = repo._venues

        # Modify YAML
        yaml_content["venues"]["test"] = 25
        yaml_path.write_text(yaml.dump(yaml_content))

        # Reload
        repo.reload()

        # Should have new data
        assert repo._venues is not old_venues
        assert abs(repo.get_score("test") - (25 / 30)) < 0.01

    def test_reload_on_empty_repo(self, tmp_path: Path) -> None:
        """Test reload works when cache is already empty."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": {"test": 20}}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Reload without prior access
        assert repo._venues is None
        repo.reload()
        assert repo._venues is not None


class TestYamlVenueRepositoryNormalization:
    """Test _normalize_venue method."""

    def test_normalize_venue_lowercase(self, tmp_path: Path) -> None:
        """Test normalization converts to lowercase."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues: {}")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        assert repo._normalize_venue("NEURIPS") == "neurips"
        assert repo._normalize_venue("NeurIPS") == "neurips"

    def test_normalize_venue_removes_digits(self, tmp_path: Path) -> None:
        """Test normalization removes digits."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues: {}")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        assert repo._normalize_venue("ACL 2024") == "acl"
        assert repo._normalize_venue("NeurIPS2023") == "neurips"

    def test_normalize_venue_removes_special_chars(self, tmp_path: Path) -> None:
        """Test normalization removes special characters."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues: {}")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        assert repo._normalize_venue("ACL: 2024") == "acl"
        assert repo._normalize_venue("NeurIPS (2023)") == "neurips"
        assert repo._normalize_venue("ACL/EMNLP") == "acl emnlp"

    def test_normalize_venue_removes_common_words(self, tmp_path: Path) -> None:
        """Test normalization removes common words."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues: {}")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        assert repo._normalize_venue("Proceedings of ACL") == "acl"
        assert repo._normalize_venue("International Conference on ACL") == "acl"
        assert (
            repo._normalize_venue("Journal of Machine Learning") == "machine learning"
        )
        assert repo._normalize_venue("Workshop on NLP") == "nlp"

    def test_normalize_venue_strips_whitespace(self, tmp_path: Path) -> None:
        """Test normalization strips and collapses whitespace."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues: {}")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        assert repo._normalize_venue("  ACL  ") == "acl"
        assert repo._normalize_venue("ACL   2024") == "acl"

    def test_normalize_venue_complex_example(self, tmp_path: Path) -> None:
        """Test normalization on complex venue name."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues: {}")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        result = repo._normalize_venue(
            "Proceedings of the 2024 International Conference on "
            "Neural Information Processing Systems"
        )
        assert result == "neural information processing systems"


class TestYamlVenueRepositoryLoadVenues:
    """Test _load_venues method."""

    def test_load_venues_generic_exception(self, tmp_path: Path, monkeypatch) -> None:
        """Test graceful handling of generic exceptions during load."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues:\n  test: 20\n")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Mock open() to raise a generic exception
        def mock_open_error(*args, **kwargs):
            raise RuntimeError("Simulated file system error")

        monkeypatch.setattr("builtins.open", mock_open_error)

        venues = repo._load_venues()
        assert venues == {}

    def test_load_venues_valid_yaml(self, tmp_path: Path) -> None:
        """Test loading valid YAML."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "default_score": 15,
            "venues": {
                "neurips": 30,
                "acl": 28,
            },
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert len(venues) == 2
        assert venues["neurips"] == 1.0
        assert abs(venues["acl"] - (28 / 30)) < 0.01

    def test_load_venues_file_not_found(self, tmp_path: Path) -> None:
        """Test graceful handling when file not found."""
        yaml_path = tmp_path / "nonexistent.yaml"

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert venues == {}

    def test_load_venues_not_a_file(self, tmp_path: Path) -> None:
        """Test graceful handling when path is a directory."""
        yaml_path = tmp_path / "venues_dir"
        yaml_path.mkdir()

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert venues == {}

    def test_load_venues_invalid_yaml(self, tmp_path: Path) -> None:
        """Test graceful handling of invalid YAML."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("invalid: yaml: content: [")

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert venues == {}

    def test_load_venues_yaml_not_dict(self, tmp_path: Path) -> None:
        """Test graceful handling when YAML root is not dict."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("- item1\n- item2\n")

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert venues == {}

    def test_load_venues_missing_venues_key(self, tmp_path: Path) -> None:
        """Test graceful handling when 'venues' key missing."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"default_score": 15}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert venues == {}

    def test_load_venues_invalid_venues_value(self, tmp_path: Path) -> None:
        """Test graceful handling when 'venues' is not dict."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {"venues": "not a dict"}
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert venues == {}

    def test_load_venues_invalid_score_type(self, tmp_path: Path) -> None:
        """Test graceful handling of non-numeric scores."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "venues": {
                "valid": 30,
                "invalid": "not a number",
                "also_valid": 20,
            }
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        # Should skip invalid entries
        assert len(venues) == 2
        assert "valid" in venues
        assert "also_valid" in venues  # Underscore normalized from "also_valid"
        assert "invalid" not in venues

    def test_load_venues_clamps_scores_to_0_1(self, tmp_path: Path) -> None:
        """Test scores are clamped to [0, 1] range."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "venues": {
                "negative": -10,
                "too_high": 100,
                "normal": 15,
            }
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        assert venues["negative"] == 0.0
        assert venues["too_high"] == 1.0  # Underscore normalized from "too_high"
        assert venues["normal"] == 0.5

    def test_load_venues_normalizes_venue_names(self, tmp_path: Path) -> None:
        """Test venue names are normalized during load."""
        yaml_path = tmp_path / "venues.yaml"
        yaml_content = {
            "venues": {
                "NeurIPS 2024": 30,
                "ACL Conference": 28,
            }
        }
        yaml_path.write_text(yaml.dump(yaml_content))

        repo = YamlVenueRepository(yaml_path=yaml_path)
        venues = repo._load_venues()

        # Keys should be normalized
        assert "neurips" in venues
        assert "acl" in venues


class TestYamlVenueRepositoryIntegration:
    """Integration tests with real venue_scores.yaml."""

    def test_load_production_yaml(self) -> None:
        """Test loading production venue_scores.yaml."""
        repo = YamlVenueRepository()

        # Should load without errors
        score = repo.get_score("neurips")
        assert 0.0 <= score <= 1.0

    def test_production_yaml_top_venues(self) -> None:
        """Test production YAML has expected top venues."""
        repo = YamlVenueRepository()

        # Top ML venues should score high (30/30 = 1.0)
        assert repo.get_score("neurips") == 1.0
        assert repo.get_score("icml") == 1.0
        assert repo.get_score("acl") == 1.0
        assert repo.get_score("emnlp") == 1.0

    def test_production_yaml_journals(self) -> None:
        """Test production YAML has journals."""
        repo = YamlVenueRepository()

        # Top journals
        assert repo.get_score("nature") == 1.0
        assert repo.get_score("science") == 1.0

    def test_production_yaml_preprints(self) -> None:
        """Test production YAML has preprint servers."""
        repo = YamlVenueRepository()

        # ArXiv should be 15/30 = 0.5 (updated from 10)
        assert abs(repo.get_score("arxiv") - 0.5) < 0.01

    def test_production_yaml_substring_matching(self) -> None:
        """Test substring matching works with production data."""
        repo = YamlVenueRepository()

        # Should match via substring
        assert repo.get_score("NeurIPS 2024") == 1.0
        assert repo.get_score("Proceedings of ACL 2023") == 1.0
        assert repo.get_score("ICML Conference") == 1.0


class TestVenueRepositoryProtocol:
    """Test VenueRepository protocol compliance."""

    def test_yaml_repository_implements_protocol(self, tmp_path: Path) -> None:
        """Test YamlVenueRepository implements VenueRepository protocol."""
        from src.services.venue_repository import VenueRepository

        yaml_path = tmp_path / "venues.yaml"
        yaml_path.write_text("venues:\n  test: 20\n")

        repo = YamlVenueRepository(yaml_path=yaml_path)

        # Should have protocol methods
        assert hasattr(repo, "get_score")
        assert hasattr(repo, "get_default_score")
        assert hasattr(repo, "reload")

        # Should work as protocol
        def use_repo(repository: VenueRepository) -> float:
            return repository.get_score("test")

        result = use_repo(repo)
        assert abs(result - (20 / 30)) < 0.01
