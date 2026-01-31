import typer
import asyncio
import structlog
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Union

from src.services.config_manager import ConfigManager, ConfigValidationError
from src.services.discovery_service import DiscoveryService, APIError
from src.services.catalog_service import CatalogService
from src.output.markdown_generator import MarkdownGenerator
from src.output.enhanced_generator import EnhancedMarkdownGenerator
from src.models.catalog import CatalogRun
from src.utils.logging import configure_logging

# Phase 2 imports
from src.services.pdf_service import PDFService
from src.services.llm_service import LLMService
from src.services.extraction_service import ExtractionService
from src.services.pdf_extractors.fallback_service import FallbackPDFService
from src.models.llm import LLMConfig, CostLimits

# Phase 3 imports
from src.services.cache_service import CacheService
from src.services.dedup_service import DeduplicationService
from src.services.filter_service import FilterService
from src.services.checkpoint_service import CheckpointService
from src.models.cache import CacheConfig
from src.models.dedup import DedupConfig
from src.models.filters import FilterConfig
from src.models.checkpoint import CheckpointConfig

# Configure structured logging
configure_logging()
logger = structlog.get_logger()

app = typer.Typer(help="ARISP: Automated Research Ingestion & Synthesis Pipeline")


@app.command()
def run(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Validate and plan without executing"
    ),
):
    """Run the research pipeline based on configuration"""
    try:
        # 1. Load Config
        config_manager = ConfigManager(config_path=str(config_path))
        try:
            config = config_manager.load_config()
        except (FileNotFoundError, ConfigValidationError) as e:
            typer.secho(f"Configuration Error: {e}", fg=typer.colors.RED)
            raise typer.Exit(code=1)

        # Check if Phase 2 is enabled (based on config)
        phase2_enabled = (
            config.settings.pdf_settings is not None
            and config.settings.llm_settings is not None
            and config.settings.cost_limits is not None
        )

        if dry_run:
            typer.secho("Dry run: Configuration valid.", fg=typer.colors.GREEN)
            typer.echo(f"Found {len(config.research_topics)} topics:")
            for t in config.research_topics:  # pragma: no cover
                typer.echo(f" - {t.query} ({t.timeframe.type})")

            if phase2_enabled:
                # Type narrowing for Mypy
                assert config.settings.pdf_settings is not None
                assert config.settings.llm_settings is not None
                assert config.settings.cost_limits is not None

                typer.secho("\nPhase 2 Features Enabled:", fg=typer.colors.CYAN)
                pdf_status = (
                    "Keep PDFs"
                    if config.settings.pdf_settings.keep_pdfs
                    else "Delete after processing"
                )
                typer.echo(f" - PDF Processing: {pdf_status}")
                typer.echo(f" - LLM Provider: {config.settings.llm_settings.provider}")
                typer.echo(f" - LLM Model: {config.settings.llm_settings.model}")
                daily_limit = config.settings.cost_limits.max_daily_spend_usd
                total_limit = config.settings.cost_limits.max_total_spend_usd
                typer.echo(f" - Daily Cost Limit: ${daily_limit:.2f}")
                typer.echo(f" - Total Cost Limit: ${total_limit:.2f}")
            else:
                typer.secho(
                    "\nPhase 2 Features: Disabled (Phase 1 discovery only)",
                    fg=typer.colors.YELLOW,
                )

            return  # pragma: no cover

        # 2. Initialize Core Services (Phase 1)
        discovery_service = DiscoveryService(
            api_key=config.settings.semantic_scholar_api_key or ""
        )
        catalog_service = CatalogService(config_manager)

        # Load catalog once
        catalog_service.load()

        # 3. Initialize Phase 2 Services (if enabled)
        pdf_service = None
        llm_service = None
        extraction_service = None
        md_generator: Optional[Union[MarkdownGenerator, EnhancedMarkdownGenerator]] = (
            None
        )

        if phase2_enabled:
            # Type narrowing: these are guaranteed not None due to phase2_enabled check
            assert config.settings.pdf_settings is not None
            assert config.settings.llm_settings is not None
            assert config.settings.cost_limits is not None
            typer.secho("Initializing Phase 2 services...", fg=typer.colors.CYAN)

            # PDF Service
            pdf_service = PDFService(
                temp_dir=Path(config.settings.pdf_settings.temp_dir),
                max_size_mb=config.settings.pdf_settings.max_file_size_mb,
                timeout_seconds=config.settings.pdf_settings.timeout_seconds,
            )

            # LLM Service
            # Ensure api_key is a string (never None)
            api_key_value: str = (
                config.settings.llm_settings.api_key
                if config.settings.llm_settings.api_key is not None
                else os.getenv("LLM_API_KEY", "")
            )

            llm_config = LLMConfig(
                provider=config.settings.llm_settings.provider,
                model=config.settings.llm_settings.model,
                api_key=api_key_value,
                max_tokens=config.settings.llm_settings.max_tokens,
                temperature=config.settings.llm_settings.temperature,
                timeout=config.settings.llm_settings.timeout,
            )

            cost_limits = CostLimits(
                max_tokens_per_paper=config.settings.cost_limits.max_tokens_per_paper,
                max_daily_spend_usd=config.settings.cost_limits.max_daily_spend_usd,
                max_total_spend_usd=config.settings.cost_limits.max_total_spend_usd,
            )

            llm_service = LLMService(config=llm_config, cost_limits=cost_limits)

            # Fallback PDF Service (Phase 2.5)
            fallback_service = FallbackPDFService(config=config.settings.pdf_settings)

            # Phase 3 Services (concurrent processing support)
            # Note: Pydantic models have Field() defaults that Mypy doesn't recognize
            cache_service = CacheService(config=CacheConfig())  # type: ignore[call-arg]
            dedup_service = DeduplicationService(
                config=DedupConfig()  # type: ignore[call-arg]
            )
            filter_service = FilterService(
                config=FilterConfig()  # type: ignore[call-arg]
            )
            checkpoint_service = CheckpointService(
                config=CheckpointConfig()  # type: ignore[call-arg]
            )

            # Extraction Service with Phase 3 services for concurrent processing
            extraction_service = ExtractionService(
                pdf_service=pdf_service,
                llm_service=llm_service,
                fallback_service=fallback_service,
                keep_pdfs=config.settings.pdf_settings.keep_pdfs,
                # Phase 3 services for concurrent processing
                cache_service=cache_service,
                dedup_service=dedup_service,
                filter_service=filter_service,
                checkpoint_service=checkpoint_service,
                concurrency_config=config.settings.concurrency,
            )

            # Enhanced Markdown Generator
            md_generator = EnhancedMarkdownGenerator()

            typer.secho("✓ Phase 2 services initialized", fg=typer.colors.GREEN)
            typer.secho(
                "✓ Phase 3 concurrent processing enabled", fg=typer.colors.GREEN
            )
        else:
            # Phase 1 only - basic markdown generator
            md_generator = MarkdownGenerator()

        # 4. Process Topics
        asyncio.run(
            _process_topics(
                config=config,
                discovery=discovery_service,
                catalog_svc=catalog_service,
                md_gen=md_generator,
                config_mgr=config_manager,
                extraction_svc=extraction_service,
                phase2_enabled=phase2_enabled,
            )
        )

    except Exception as e:
        logger.exception("pipeline_failed")
        typer.secho(f"Pipeline failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


async def _process_topics(
    config,
    discovery,
    catalog_svc,
    md_gen,
    config_mgr,
    extraction_svc=None,
    phase2_enabled=False,
):
    """Async processing of topics

    Args:
        config: Research configuration
        discovery: Discovery service
        catalog_svc: Catalog service
        md_gen: Markdown generator (MarkdownGenerator or EnhancedMarkdownGenerator)
        config_mgr: Configuration manager
        extraction_svc: Extraction service (Phase 2, optional)
        phase2_enabled: Whether Phase 2 features are enabled
    """
    for topic in config.research_topics:
        try:
            run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            logger.info(
                "processing_topic",
                topic=topic.query,
                run_id=run_id,
                phase2=phase2_enabled,
            )

            # A. Get/Create Topic in Catalog
            catalog_topic = catalog_svc.get_or_create_topic(topic.query)

            # B. Discovery
            papers = await discovery.search(topic)

            if not papers:
                logger.warning("no_papers_found", topic=topic.query)
                continue

            # C. Phase 2: PDF Processing & LLM Extraction (if enabled)
            extracted_papers = None
            summary_stats = None

            if phase2_enabled and extraction_svc and topic.extraction_targets:
                logger.info(
                    "starting_phase2_extraction",
                    topic=topic.query,
                    papers_count=len(papers),
                    targets_count=len(topic.extraction_targets),
                )

                # Process papers through extraction pipeline
                # Phase 3.1: Use concurrent processing when available
                extracted_papers = await extraction_svc.process_papers_concurrent(
                    papers=papers,
                    targets=topic.extraction_targets,
                    run_id=run_id,
                    query=topic.query,
                )

                # Get summary statistics
                summary_stats = extraction_svc.get_extraction_summary(extracted_papers)

                logger.info(
                    "phase2_extraction_completed",
                    topic=topic.query,
                    papers_with_pdf=summary_stats["papers_with_pdf"],
                    papers_with_extraction=summary_stats["papers_with_extraction"],
                    total_tokens=summary_stats["total_tokens_used"],
                    total_cost_usd=summary_stats["total_cost_usd"],
                )

            # D. Generate Output
            # Get output path from config manager
            output_dir = config_mgr.get_output_path(catalog_topic.topic_slug)
            filename = f"{datetime.utcnow().strftime('%Y-%m-%d')}_Research.md"
            output_file = output_dir / filename

            # Generate markdown (Phase 1 or Phase 2 format)
            if phase2_enabled and extracted_papers is not None:
                # Phase 2: Enhanced markdown with extraction results
                content = md_gen.generate_enhanced(
                    extracted_papers=extracted_papers,
                    topic=topic,
                    run_id=run_id,
                    summary_stats=summary_stats,
                )
            else:
                # Phase 1: Basic markdown from paper metadata only
                content = md_gen.generate(papers, topic, run_id)

            with open(output_file, "w") as f:
                f.write(content)

            logger.info(
                "report_generated", path=str(output_file), phase2=phase2_enabled
            )

            # E. Update Catalog
            papers_processed = len(papers)
            if phase2_enabled and summary_stats:
                papers_processed = summary_stats["papers_with_extraction"]

            run = CatalogRun(
                run_id=run_id,
                date=datetime.utcnow(),
                papers_found=len(papers),
                papers_processed=papers_processed,
                timeframe=(
                    str(topic.timeframe.value)
                    if hasattr(topic.timeframe, "value")
                    else "custom"
                ),
                output_file=str(output_file),
            )
            catalog_svc.add_run(catalog_topic.topic_slug, run)

        except APIError as e:
            logger.error("topic_failed", topic=topic.query, error=str(e))
            continue
        except Exception:
            logger.exception("topic_unexpected_error", topic=topic.query)
            continue


@app.command()
def validate(config_path: Path = typer.Argument(..., help="Config file to validate")):
    """Validate configuration file syntax and semantics"""
    try:
        manager = ConfigManager(config_path=str(config_path))
        manager.load_config()
        typer.secho("Configuration is valid! ✅", fg=typer.colors.GREEN)
    except Exception as e:
        typer.secho(f"Validation failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command()
def catalog(
    action: str = typer.Argument(..., help="Action: show, history"),
    topic: Optional[str] = typer.Option(None, help="Filter by topic slug"),
):
    """Manage research catalog"""
    manager = ConfigManager()
    cat = manager.load_catalog()

    if action == "show":
        typer.echo(f"Catalog contains {len(cat.topics)} topics:")
        for slug, t in cat.topics.items():
            typer.echo(f" - {slug}: {t.query} ({len(t.runs)} runs)")

    elif action == "history":
        if not topic:
            typer.secho("Please provide --topic for history", fg=typer.colors.YELLOW)
            return

        if topic not in cat.topics:
            typer.secho(f"Topic '{topic}' not found", fg=typer.colors.RED)
            return

        t = cat.topics[topic]
        typer.echo(f"History for {t.query}:")
        for run in t.runs:
            typer.echo(
                f"  {run.date}: Found {run.papers_found} papers "
                f"-> {run.output_file}"
            )


if __name__ == "__main__":
    app()  # pragma: no cover
