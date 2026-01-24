import typer
import asyncio
import structlog
from pathlib import Path
from datetime import datetime
from typing import Optional

from src.services.config_manager import ConfigManager, ConfigValidationError
from src.services.discovery_service import DiscoveryService, APIError
from src.services.catalog_service import CatalogService
from src.output.markdown_generator import MarkdownGenerator
from src.models.catalog import CatalogRun
from src.utils.logging import configure_logging

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

        if dry_run:
            typer.secho("Dry run: Configuration valid.", fg=typer.colors.GREEN)
            typer.echo(f"Found {len(config.research_topics)} topics:")
            for t in config.research_topics:  # pragma: no cover
                typer.echo(f" - {t.query} ({t.timeframe.type})")
            return  # pragma: no cover

        # 2. Initialize Services
        discovery_service = DiscoveryService(
            api_key=config.settings.semantic_scholar_api_key or ""
        )
        catalog_service = CatalogService(config_manager)
        md_generator = MarkdownGenerator()

        # Load catalog once
        catalog_service.load()

        # 3. Process Topics
        asyncio.run(
            _process_topics(
                config, discovery_service, catalog_service, md_generator, config_manager
            )
        )

    except Exception as e:
        logger.exception("pipeline_failed")
        typer.secho(f"Pipeline failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


async def _process_topics(config, discovery, catalog_svc, md_gen, config_mgr):
    """Async processing of topics"""
    for topic in config.research_topics:
        try:
            run_id = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            logger.info("processing_topic", topic=topic.query, run_id=run_id)

            # A. Get/Create Topic in Catalog
            catalog_topic = catalog_svc.get_or_create_topic(topic.query)

            # B. Discovery
            papers = await discovery.search(topic)

            if not papers:
                logger.warning("no_papers_found", topic=topic.query)
                continue

            # C. Generate Output
            # Get output path from config manager
            output_dir = config_mgr.get_output_path(catalog_topic.topic_slug)
            filename = f"{datetime.utcnow().strftime('%Y-%m-%d')}_Research.md"
            output_file = output_dir / filename

            content = md_gen.generate(papers, topic, run_id)

            with open(output_file, "w") as f:
                f.write(content)

            logger.info("report_generated", path=str(output_file))

            # D. Update Catalog
            run = CatalogRun(
                run_id=run_id,
                date=datetime.utcnow(),
                papers_found=len(papers),
                papers_processed=len(papers),
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
