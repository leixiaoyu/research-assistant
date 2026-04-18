"""Deep Research Agent CLI commands.

Provides interactive research sessions using the DRA.

Usage:
    python -m src.cli research "What are the key techniques in ToT?"
    python -m src.cli research --question-file questions.txt
"""

from pathlib import Path
from typing import Optional

import structlog
import typer

from src.cli.utils import (
    display_error,
    display_info,
    display_success,
    display_warning,
    handle_errors,
    load_config,
)

logger = structlog.get_logger()

# Truncation limits for verbose output
REASONING_TRUNCATE_LIMIT = 500
OBSERVATION_TRUNCATE_LIMIT = 300

# Create research sub-application
research_app = typer.Typer(help="Deep Research Agent commands")


@research_app.callback(invoke_without_command=True)
@handle_errors
def research_command(
    ctx: typer.Context,
    question: Optional[str] = typer.Argument(
        None,
        help="Research question to investigate",
    ),
    question_file: Optional[Path] = typer.Option(
        None,
        "--question-file",
        "-f",
        help="File containing questions (one per line)",
    ),
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    max_turns: int = typer.Option(
        50,
        "--max-turns",
        "-t",
        help="Maximum turns per research session",
    ),
    output_file: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file for results (default: stdout)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed progress during research",
    ),
) -> None:
    """Execute a deep research session.

    Asks questions to the DRA which searches the offline corpus,
    reasons about findings, and synthesizes answers with citations.

    Examples:
        arisp research "What techniques improve LLM reasoning?"
        arisp research -f questions.txt -o results.md
    """
    # If a subcommand was invoked, skip the default behavior
    if ctx.invoked_subcommand is not None:
        return

    # Validate inputs
    if question is None and question_file is None:
        display_error("Either provide a question or use --question-file")
        raise typer.Exit(code=1)

    if question is not None and question_file is not None:
        display_error("Cannot use both question argument and --question-file")
        raise typer.Exit(code=1)

    # Load questions
    questions: list[str] = []
    if question:
        questions = [question]
    elif question_file:
        if not question_file.exists():
            display_error(f"Question file not found: {question_file}")
            raise typer.Exit(code=1)
        questions = [
            line.strip()
            for line in question_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not questions:
            display_error("No questions found in file")
            raise typer.Exit(code=1)
        display_info(f"Loaded {len(questions)} questions from {question_file}")

    # Load config
    config = load_config(config_path)

    # Initialize DRA components
    display_info("Initializing Deep Research Agent...")

    try:
        from src.models.dra import AgentLimits
        from src.services.dra.agent import DeepResearchAgent
        from src.services.dra.browser import ResearchBrowser
        from src.services.dra.corpus_manager import CorpusManager
        from src.services.llm.service import LLMService
    except ImportError as e:
        display_error(f"Failed to import DRA modules: {e}")
        display_warning("Ensure all DRA dependencies are installed")
        raise typer.Exit(code=1)

    # Get corpus directory from config or use default
    corpus_dir = Path(
        getattr(
            getattr(config.settings, "dra_settings", None),
            "corpus_dir",
            "./data/dra/corpus",
        )
        or "./data/dra/corpus"
    )

    # Initialize corpus manager
    try:
        from src.models.dra import CorpusConfig

        corpus_config = CorpusConfig(corpus_dir=str(corpus_dir))
        corpus_manager = CorpusManager(config=corpus_config)
        if corpus_manager.paper_count == 0:
            display_warning("Corpus is empty. Run corpus ingestion first.")
            display_info("Use: arisp corpus ingest")
            raise typer.Exit(code=1)
        display_success(f"✓ Corpus loaded: {corpus_manager.paper_count} papers")
    except Exception as e:
        display_error(f"Failed to load corpus: {e}")
        raise typer.Exit(code=1)

    # Initialize browser
    browser = ResearchBrowser(corpus_manager=corpus_manager)
    display_success("✓ Research browser initialized")

    # Initialize LLM service
    try:
        llm_settings = config.settings.llm_settings
        if llm_settings is None:
            display_error("LLM settings not configured")
            display_info("Add llm_settings to your config file")
            raise typer.Exit(code=1)

        # Convert LLMSettings to LLMConfig for LLMService
        from src.models.llm import CostLimits, LLMConfig

        llm_config = LLMConfig(
            provider=llm_settings.provider,
            model=llm_settings.model,
            api_key=llm_settings.api_key or "",
            max_tokens=llm_settings.max_tokens,
            temperature=llm_settings.temperature,
            timeout=llm_settings.timeout,
        )
        llm_service = LLMService(
            config=llm_config,
            cost_limits=CostLimits(),
        )
        display_success(f"✓ LLM service initialized ({llm_settings.provider})")
    except Exception as e:
        display_error(f"Failed to initialize LLM service: {e}")
        raise typer.Exit(code=1)

    # Create agent with limits
    limits = AgentLimits(max_turns=max_turns)
    agent = DeepResearchAgent(
        browser=browser,
        llm_service=llm_service,
        limits=limits,
    )
    display_success("✓ Deep Research Agent ready")

    # Process questions
    results: list[str] = []
    for i, q in enumerate(questions, 1):
        if len(questions) > 1:
            display_info(f"\n[{i}/{len(questions)}] Processing: {q[:80]}...")
        else:
            display_info(f"\nResearching: {q}")

        # Execute research
        try:
            if verbose:
                display_info("Starting ReAct loop...")

            result = agent.research(q)

            # Format result
            formatted = _format_result(result, verbose=verbose)
            results.append(formatted)

            # Display summary
            if result.answer:
                display_success(f"✓ Answer produced in {result.total_turns} turns")
                if result.papers_consulted:
                    display_info(
                        f"  Papers consulted: {', '.join(result.papers_consulted[:5])}"
                        + ("..." if len(result.papers_consulted) > 5 else "")
                    )
            else:
                display_warning(
                    f"✗ No answer produced (exhausted={result.exhausted}, "
                    f"turns={result.total_turns})"
                )

        except Exception as e:
            logger.exception("research_failed", question=q[:100])
            display_error(f"Research failed: {e}")
            results.append(f"# Question: {q}\n\n**Error:** {e}\n")

    # Output results
    output_content = "\n\n---\n\n".join(results)

    if output_file:
        output_file.write_text(output_content)
        display_success(f"\nResults saved to {output_file}")
    else:
        typer.echo("\n" + "=" * 60)
        typer.echo(output_content)
        typer.echo("=" * 60)


def _format_result(result, verbose: bool = False) -> str:
    """Format a research result as markdown.

    Args:
        result: ResearchResult from agent
        verbose: Include trajectory details

    Returns:
        Formatted markdown string
    """
    from src.models.dra import ResearchResult

    if not isinstance(result, ResearchResult):
        return str(result)

    lines = [
        f"# Question: {result.question}",
        "",
    ]

    if result.answer:
        lines.extend(
            [
                "## Answer",
                "",
                result.answer,
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Status",
                "",
                "No answer produced.",
                "",
            ]
        )

    # Add metadata
    lines.extend(
        [
            "## Session Metadata",
            "",
            f"- **Turns:** {result.total_turns}",
            f"- **Papers consulted:** {len(result.papers_consulted)}",
            f"- **Exhausted:** {result.exhausted}",
            f"- **Duration:** {result.duration_seconds:.1f}s",
            f"- **Tokens used:** {result.total_tokens:,}",
            "",
        ]
    )

    # Add citations if papers were consulted
    if result.papers_consulted:
        lines.extend(
            [
                "## Papers Consulted",
                "",
            ]
        )
        for paper_id in result.papers_consulted:
            lines.append(f"- `{paper_id}`")
        lines.append("")

    # Add trajectory if verbose
    if verbose and result.trajectory:
        lines.extend(
            [
                "## Trajectory",
                "",
            ]
        )
        for turn in result.trajectory:
            lines.extend(
                [
                    f"### Turn {turn.turn_number}",
                    "",
                    (
                        f"**Reasoning:** {turn.reasoning[:REASONING_TRUNCATE_LIMIT]}..."
                        if len(turn.reasoning) > REASONING_TRUNCATE_LIMIT
                        else f"**Reasoning:** {turn.reasoning}"
                    ),
                    "",
                    f"**Action:** `{turn.action.tool.value}`({turn.action.arguments})",
                    "",
                    (
                        (
                            f"**Observation:** "
                            f"{turn.observation[:OBSERVATION_TRUNCATE_LIMIT]}..."
                        )
                        if len(turn.observation) > OBSERVATION_TRUNCATE_LIMIT
                        else f"**Observation:** {turn.observation}"
                    ),
                    "",
                ]
            )

    return "\n".join(lines)


@research_app.command("status")
@handle_errors
def status_command(
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
) -> None:
    """Show DRA status and corpus statistics."""
    from src.services.dra.corpus_manager import CorpusManager

    config = load_config(config_path)

    # Get corpus directory
    corpus_dir = Path(
        getattr(
            getattr(config.settings, "dra_settings", None),
            "corpus_dir",
            "./data/dra/corpus",
        )
        or "./data/dra/corpus"
    )

    display_info("Deep Research Agent Status")
    display_info("=" * 40)

    # Check corpus
    if not corpus_dir.exists():
        display_warning(f"Corpus directory not found: {corpus_dir}")
        display_info("Run corpus ingestion to create it")
        return

    try:
        from src.models.dra import CorpusConfig

        corpus_config = CorpusConfig(corpus_dir=str(corpus_dir))
        corpus_manager = CorpusManager(config=corpus_config)
        stats = corpus_manager.stats

        display_success(f"✓ Corpus directory: {corpus_dir}")
        display_info(f"  Papers: {stats.total_papers}")
        display_info(f"  Chunks: {stats.total_chunks}")
        display_info(f"  Tokens: {stats.total_tokens:,}")

        if stats.last_updated:
            display_info(f"  Last updated: {stats.last_updated}")

    except Exception as e:
        display_error(f"Failed to read corpus: {e}")


# Standalone command for direct registration
@handle_errors
def research_single_command(
    question: str = typer.Argument(..., help="Research question to investigate"),
    config_path: Path = typer.Option(
        "config/research_config.yaml",
        "--config",
        "-c",
        help="Path to research config YAML",
    ),
    max_turns: int = typer.Option(
        50,
        "--max-turns",
        "-t",
        help="Maximum turns per research session",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed progress",
    ),
) -> None:
    """Execute a single research question (convenience wrapper)."""
    # Create a mock context and delegate.
    # Note: Type ignore needed because @handle_errors decorator changes
    # the function type, but this works at runtime for Typer delegation.
    ctx = typer.Context(research_command)  # type: ignore[arg-type]
    research_command(
        ctx=ctx,
        question=question,
        question_file=None,
        config_path=config_path,
        max_turns=max_turns,
        output_file=None,
        verbose=verbose,
    )
