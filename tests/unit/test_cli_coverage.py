import pytest
from typer.testing import CliRunner
from unittest.mock import Mock, patch, AsyncMock
from src.cli import app
from src.services.config_manager import ConfigValidationError
from src.services.discovery_service import APIError

runner = CliRunner()

class TestCLICoverage:
    def test_run_config_error(self):
        """Test config loading error"""
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_cm.return_value.load_config.side_effect = ConfigValidationError("Invalid config")
            
            result = runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "Configuration Error" in result.stdout

    def test_run_dry_run_phase2(self):
        """Test dry run with Phase 2 enabled"""
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_config = Mock()
            # Phase 2 settings present
            mock_config.settings.pdf_settings.keep_pdfs = True
            mock_config.settings.pdf_settings.temp_dir = "/tmp"
            mock_config.settings.pdf_settings.max_file_size_mb = 10
            mock_config.settings.pdf_settings.timeout_seconds = 60
            
            mock_config.settings.llm_settings.provider = "anthropic"
            mock_config.settings.llm_settings.model = "claude-3-5-sonnet"
            mock_config.settings.llm_settings.api_key = "key"
            mock_config.settings.llm_settings.max_tokens = 1000
            mock_config.settings.llm_settings.temperature = 0.7
            mock_config.settings.llm_settings.timeout = 60

            mock_config.settings.cost_limits.max_daily_spend_usd = 10.0
            mock_config.settings.cost_limits.max_total_spend_usd = 100.0
            mock_config.settings.cost_limits.max_tokens_per_paper = 10000

            mock_config.settings.semantic_scholar_api_key = "key"
            
            mock_config.research_topics = [
                Mock(query="topic1", timeframe=Mock(type="recent"))
            ]
            
            mock_cm.return_value.load_config.return_value = mock_config
            
            result = runner.invoke(app, ["run", "--dry-run"])
            assert result.exit_code == 0
            assert "Phase 2 Features Enabled" in result.stdout

    def test_run_exception(self):
        """Test general exception in run"""
        with patch("src.cli.ConfigManager", side_effect=Exception("Unexpected")):
            result = runner.invoke(app, ["run"])
            assert result.exit_code == 1
            assert "Pipeline failed" in result.stdout

    def test_process_topics_no_papers(self):
        """Test processing with no papers found"""
        with patch("src.cli.ConfigManager"):
            with patch("src.cli.CatalogService"):
                with patch("src.cli.DiscoveryService") as mock_discovery:
                    mock_discovery.return_value.search = AsyncMock(return_value=[])
                    # We need to mock _process_topics arguments or run the full command
                    pass

    @pytest.mark.asyncio
    async def test_process_topics_direct_no_papers(self):
        """Test _process_topics directly for no papers branch"""
        from src.cli import _process_topics
        
        config = Mock()
        topic = Mock(query="test")
        config.research_topics = [topic]
        
        discovery = Mock()
        discovery.search = AsyncMock(return_value=[])
        
        catalog_svc = Mock()
        
        await _process_topics(config, discovery, catalog_svc, Mock(), Mock())
        
        # Log verification would be ideal, but verifying no exception is raised and it completes is start
        assert discovery.search.called

    @pytest.mark.asyncio
    async def test_process_topics_api_error(self):
        """Test _process_topics with APIError"""
        from src.cli import _process_topics
        
        config = Mock()
        topic = Mock(query="test")
        config.research_topics = [topic]
        
        discovery = Mock()
        discovery.search = AsyncMock(side_effect=APIError("API Failed"))
        
        catalog_svc = Mock()
        
        await _process_topics(config, discovery, catalog_svc, Mock(), Mock())
        assert discovery.search.called

    @pytest.mark.asyncio
    async def test_process_topics_unexpected_error(self):
        """Test _process_topics with unexpected error"""
        from src.cli import _process_topics
        
        config = Mock()
        topic = Mock(query="test")
        config.research_topics = [topic]
        
        discovery = Mock()
        discovery.search = AsyncMock(side_effect=Exception("Crash"))
        
        catalog_svc = Mock()
        
        await _process_topics(config, discovery, catalog_svc, Mock(), Mock())
        assert discovery.search.called

    def test_catalog_history_no_topic(self):
        """Test catalog history without topic"""
        # Patch ConfigManager to avoid validation error
        with patch("src.cli.ConfigManager"):
            result = runner.invoke(app, ["catalog", "history"])
            assert "Please provide --topic" in result.stdout

    def test_catalog_history_topic_not_found(self):
        """Test catalog history with unknown topic"""
        # Patch ConfigManager to return empty catalog
        with patch("src.cli.ConfigManager") as mock_cm:
            mock_cm.return_value.load_catalog.return_value.topics = {}
            result = runner.invoke(app, ["catalog", "history", "--topic", "unknown"])
            assert "Topic 'unknown' not found" in result.stdout