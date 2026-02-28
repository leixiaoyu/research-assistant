"""Health command for health server management.

Provides commands for starting the health server.
"""

import typer

from src.cli.utils import handle_errors, display_info


@handle_errors
def health_command(
    host: str = typer.Option("localhost", "--host", "-h", help="Health server host"),
    port: int = typer.Option(8000, "--port", "-p", help="Health server port"),
):
    """Start standalone health server.

    Starts the health server without the scheduler.
    Useful for testing or when running scheduler separately.
    """
    from src.health.server import run_health_server

    display_info(f"Starting health server at http://{host}:{port}")
    run_health_server(host=host, port=port)
