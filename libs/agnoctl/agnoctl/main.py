from typing import List, Optional, Tuple

import typer
from rich.table import Table
from rich.text import Text

from agnoctl import __version__
from agnoctl.commands.connect import connect
from agnoctl.commands.create import create
from agnoctl.commands.disconnect import disconnect
from agnoctl.commands.lifecycle import down, restart, up
from agnoctl.commands.status import status
from agnoctl.commands.tokens import tokens_app
from agnoctl.console import console, print_info

app = typer.Typer(
    name="agno",
    help="The CLI for AgentOS, built for humans and coding agents.",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)

app.command(name="connect")(connect)
app.command(name="disconnect")(disconnect)
app.command(name="create")(create)
app.command(name="status")(status)
app.add_typer(tokens_app, name="tokens")
app.command(name="up")(up)
app.command(name="down")(down)
app.command(name="restart")(restart)


ORANGE = "color(208)"

_BANNER = r""" █████╗  ██████╗ ███╗   ██╗ ██████╗
██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗
███████║██║  ███╗██╔██╗ ██║██║   ██║
██╔══██║██║   ██║██║╚██╗██║██║   ██║
██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝
╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝"""

# The home screen's command catalog. Keep in sync with the commands registered above.
_GROUPS: List[Tuple[str, List[Tuple[str, str]]]] = [
    (
        "Get started",
        [
            ("agno create <name>", "Create a new AgentOS"),
            ("agno connect", "Connect your AI apps to your AgentOS using MCP"),
            ("agno disconnect", "Disconnect your AI apps from your AgentOS"),
        ],
    ),
    (
        "Operate",
        [
            ("agno up / down / restart", "Run your AgentOS"),
            ("agno status", "Show the AgentOS and which agents are connected"),
        ],
    ),
    (
        "Tokens",
        [
            ("agno tokens", "Mint, list, and revoke service-account tokens"),
        ],
    ),
]


def render_home() -> None:
    """Print the branded home screen shown for a bare `agno` invocation."""
    console.print()
    console.print(Text(_BANNER, style=f"bold {ORANGE}"))
    console.print()
    console.print(Text("The CLI for AgentOS, built for humans and agents", style="dim"))
    console.print()

    grid = Table.grid(padding=(0, 3))
    grid.add_column(style=ORANGE, no_wrap=True)
    grid.add_column(style="grey74")
    for i, (heading, rows) in enumerate(_GROUPS):
        if i:
            grid.add_row("", "")
        grid.add_row(Text(heading, style="bold default"), "")
        for cmd, desc in rows:
            grid.add_row("  " + cmd, desc)
    console.print(grid)
    console.print()
    console.print(Text(f"Run agno COMMAND --help  for details · v{__version__}", style="dim"))
    console.print()


def _version_callback(value: bool) -> None:
    if value:
        print_info("agnoctl " + __version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True, help="Print the CLI version and exit."
    ),
) -> None:
    if ctx.invoked_subcommand is None:
        render_home()


if __name__ == "__main__":
    app()
