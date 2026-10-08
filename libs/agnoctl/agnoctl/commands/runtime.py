"""Start the bound harness runtime inside a session sandbox."""

from importlib import import_module

import typer

runtime_app = typer.Typer(help="Run a session-bound harness executor.")


@runtime_app.command("serve")
def serve() -> None:
    """Serve the runtime configured by AGNO_RUNTIME_CONFIG and AGNO_RUNTIME_TOKEN."""
    try:
        runtime = import_module("agno.sandbox.runtime")
    except ModuleNotFoundError as error:
        raise typer.BadParameter("Install agno and its runtime dependencies to serve a sandbox") from error
    runtime.serve()
