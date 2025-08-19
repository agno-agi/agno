"""Agno cli

This is the entrypoint for the `agno` cli application.
"""

from typing import Optional

import typer

from agno.cli.infra_cli import infra_cli as infra_subcommands
from agno.utilities.logging import set_log_level_to_debug

agno_cli = typer.Typer(
    help="""\b
Agno is a lightweight framework for building Agent Systems.
\b
Usage:
1. Run `ag init` to create a new /infra directory
2. Run `ag infra create` to create a new Agno infrastructure from template
3. Run `ag infra up` to start the infrastructure
4. Run `ag infra down` to stop the infrastructure
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="\b",
    subcommand_metavar="[COMMAND] [OPTIONS]",
    pretty_exceptions_show_locals=False,
)


@agno_cli.command(short_help="Initialize Agno, use -r to reset")
def init(
    reset: bool = typer.Option(False, "--reset", "-r", help="Reset Agno", show_default=True),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """
    \b
    Initialize Agno, use -r to reset

    \b
    Examples:
    * `ag init`    -> Initializing Agno
    * `ag init -r` -> Reset Agno
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.operator import initialize_agno_cli

    initialize_agno_cli(reset=reset)


@agno_cli.command(short_help="Reset Agno installation")
def reset(
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """
    \b
    Reset the existing Agno configuration
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.operator import initialize_agno_cli

    initialize_agno_cli(reset=True)


@agno_cli.command(short_help="Print Agno config")
def config(
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """Print your current Agno config"""
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.console import log_config_not_available_msg
    from agno.cli.operator import initialize_agno_cli

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return
    agno_config.print_to_cli(show_all=True)


agno_cli.add_typer(infra_subcommands)
