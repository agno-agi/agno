"""Agno cli

This is the entrypoint for the `agno` cli application.
"""

import typer

from agno.cli.infra_cli import infra_cli as infra_subcommands

agno_cli = typer.Typer(
    help="""\b
Agno is a lightweight framework for building Agent Systems.
\b
Usage:
1. Run `ag infra create` to create a new Agentics Infrastructure project from a template
2. Run `ag infra up` to start the infrastructure
3. Run `ag infra down` to stop the infrastructure
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="\b",
    subcommand_metavar="[COMMAND] [OPTIONS]",
    pretty_exceptions_show_locals=False,
)


agno_cli.add_typer(infra_subcommands)
