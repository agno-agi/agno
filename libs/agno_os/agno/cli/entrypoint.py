"""Agno cli

This is the entrypoint for the `agno` cli application.
"""

from typing import Optional

import typer

from agno.utils.logging import set_log_level_to_debug
from agno.cli import os_cli

agno_cli = typer.Typer(
    help="""\b
Agno is a model-agnostic framework for building AI Agents.
\b
Usage:
1. Run `ag os create` to create a new OS
2. Run `ag os up` to start the OS
3. Run `ag os down` to stop the OS
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="\b",
    subcommand_metavar="[COMMAND] [OPTIONS]",
    pretty_exceptions_show_locals=False,
)


@agno_cli.command(short_help="Create a new OS in the current directory.")
def create(
    name: Optional[str] = typer.Option(
        None,
        "-n",
        "--name",
        help="Name of the new OS.",
        show_default=False,
    ),
    template: Optional[str] = typer.Option(
        None,
        "-t",
        "--template",
        help="Starter template for the OS.",
        show_default=False,
    ),
    url: Optional[str] = typer.Option(
        None,
        "-u",
        "--url",
        help="URL of the starter template.",
        show_default=False,
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Create a new OS in the current directory using a starter template or url
    \b
    Examples:
    > ag os create -t agent-os-docker                -> Create an `agent-os-docker` in the current directory
    > ag os create -t agent-os-docker -n my-agent-os   -> Create an `agent-os-docker` named `my-agent-os` in the current directory
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.os.operator import create_os_from_template

    create_os_from_template(name=name, template=template, url=url)

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


@agno_cli.command(short_help="Set current directory as active workspace")
def set(
    os_name: str = typer.Option(None, "-os", help="Active OS name"),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """
    \b
    Set the current directory as the active OS.
    This command can be run from within the OS directory
        OR with a -os flag to set another OS as primary.

    \b
    Examples:
    $ `ag os set`           -> Set the current directory as the active Agno OS
    $ `ag os set -os idata` -> Set the OS named "idata" as the active Agno OS
    """
    from agno.os.operator import set_os_as_active

    if print_debug_log:
        set_log_level_to_debug()

    set_os_as_active(os_dir_name=os_name)


@agno_cli.command(short_help="Start resources defined in a resources.py file")
def start(
    resources_file: str = typer.Argument(
        "resources.py",
        help="Path to workspace file.",
        show_default=False,
    ),
    env_filter: Optional[str] = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to deploy"),
    infra_filter: Optional[str] = typer.Option(None, "-i", "--infra", metavar="", help="Filter the infra to deploy."),
    group_filter: Optional[str] = typer.Option(
        None, "-g", "--group", metavar="", help="Filter resources using group name."
    ),
    name_filter: Optional[str] = typer.Option(None, "-n", "--name", metavar="", help="Filter resource using name."),
    type_filter: Optional[str] = typer.Option(
        None,
        "-t",
        "--type",
        metavar="",
        help="Filter resource using type",
    ),
    dry_run: bool = typer.Option(
        False,
        "-dr",
        "--dry-run",
        help="Print resources and exit.",
    ),
    auto_confirm: bool = typer.Option(
        False,
        "-y",
        "--yes",
        help="Skip the confirmation before deploying resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: bool = typer.Option(
        False,
        "-f",
        "--force",
        help="Force",
    ),
    pull: Optional[bool] = typer.Option(
        None,
        "-p",
        "--pull",
        help="Pull images where applicable.",
    ),
):
    """\b
    Start resources defined in a resources.py file
    \b
    Examples:
    > `ag os start`                -> Start resources defined in a resources.py file
    > `ag os start resources.py`   -> Start resources defined in a resources.py file
    """
    if print_debug_log:
        set_log_level_to_debug()

    from pathlib import Path

    from agno.cli.config import AgnoCliConfig
    from agno.cli.console import log_config_not_available_msg
    from agno.cli.operator import initialize_agno_cli, start_resources

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    target_env: Optional[str] = None
    target_infra: Optional[str] = None
    target_group: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None

    if env_filter is not None and isinstance(env_filter, str):
        target_env = env_filter
    if infra_filter is not None and isinstance(infra_filter, str):
        target_infra = infra_filter
    if group_filter is not None and isinstance(group_filter, str):
        target_group = group_filter
    if name_filter is not None and isinstance(name_filter, str):
        target_name = name_filter
    if type_filter is not None and isinstance(type_filter, str):
        target_type = type_filter

    resources_file_path: Path = Path("").resolve().joinpath(resources_file)
    start_resources(
        resources_file_path=resources_file_path,
        target_env=target_env,
        target_infra=target_infra,
        target_group=target_group,
        target_name=target_name,
        target_type=target_type,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        force=force,
        pull=pull,
    )


@agno_cli.command(short_help="Stop resources defined in a resources.py file")
def stop(
    resources_file: str = typer.Argument(
        "resources.py",
        help="Path to workspace file.",
        show_default=False,
    ),
    env_filter: Optional[str] = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to deploy"),
    infra_filter: Optional[str] = typer.Option(None, "-i", "--infra", metavar="", help="Filter the infra to deploy."),
    group_filter: Optional[str] = typer.Option(
        None, "-g", "--group", metavar="", help="Filter resources using group name."
    ),
    name_filter: Optional[str] = typer.Option(None, "-n", "--name", metavar="", help="Filter using resource name"),
    type_filter: Optional[str] = typer.Option(
        None,
        "-t",
        "--type",
        metavar="",
        help="Filter using resource type",
    ),
    dry_run: bool = typer.Option(
        False,
        "-dr",
        "--dry-run",
        help="Print resources and exit.",
    ),
    auto_confirm: bool = typer.Option(
        False,
        "-y",
        "--yes",
        help="Skip the confirmation before deploying resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: bool = typer.Option(
        False,
        "-f",
        "--force",
        help="Force",
    ),
):
    """\b
    Stop resources defined in a resources.py file
    \b
    Examples:
    > `ag os stop`                -> Stop resources defined in a resources.py file
    > `ag os stop resources.py`   -> Stop resources defined in a resources.py file
    """
    if print_debug_log:
        set_log_level_to_debug()

    from pathlib import Path

    from agno.cli.config import AgnoCliConfig
    from agno.cli.console import log_config_not_available_msg
    from agno.cli.operator import initialize_agno_cli, stop_resources

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    target_env: Optional[str] = None
    target_infra: Optional[str] = None
    target_group: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None

    if env_filter is not None and isinstance(env_filter, str):
        target_env = env_filter
    if infra_filter is not None and isinstance(infra_filter, str):
        target_infra = infra_filter
    if group_filter is not None and isinstance(group_filter, str):
        target_group = group_filter
    if name_filter is not None and isinstance(name_filter, str):
        target_name = name_filter
    if type_filter is not None and isinstance(type_filter, str):
        target_type = type_filter

    resources_file_path: Path = Path("").resolve().joinpath(resources_file)
    stop_resources(
        resources_file_path=resources_file_path,
        target_env=target_env,
        target_infra=target_infra,
        target_group=target_group,
        target_name=target_name,
        target_type=target_type,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        force=force,
    )


@agno_cli.command(short_help="Update resources defined in a resources.py file")
def patch(
    resources_file: str = typer.Argument(
        "resources.py",
        help="Path to workspace file.",
        show_default=False,
    ),
    env_filter: Optional[str] = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to deploy"),
    infra_filter: Optional[str] = typer.Option(None, "-i", "--infra", metavar="", help="Filter the infra to deploy."),
    group_filter: Optional[str] = typer.Option(
        None, "-g", "--group", metavar="", help="Filter resources using group name."
    ),
    name_filter: Optional[str] = typer.Option(None, "-n", "--name", metavar="", help="Filter using resource name"),
    type_filter: Optional[str] = typer.Option(
        None,
        "-t",
        "--type",
        metavar="",
        help="Filter using resource type",
    ),
    dry_run: bool = typer.Option(
        False,
        "-dr",
        "--dry-run",
        help="Print which resources will be deployed and exit.",
    ),
    auto_confirm: bool = typer.Option(
        False,
        "-y",
        "--yes",
        help="Skip the confirmation before deploying resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: bool = typer.Option(
        False,
        "-f",
        "--force",
        help="Force",
    ),
):
    """\b
    Update resources defined in a resources.py file
    \b
    Examples:
    > `ag os patch`                -> Update resources defined in a resources.py file
    """
    if print_debug_log:
        set_log_level_to_debug()

    from pathlib import Path

    from agno.cli.config import AgnoCliConfig
    from agno.cli.console import log_config_not_available_msg
    from agno.cli.operator import initialize_agno_cli, patch_resources

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    target_env: Optional[str] = None
    target_infra: Optional[str] = None
    target_group: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None

    if env_filter is not None and isinstance(env_filter, str):
        target_env = env_filter
    if infra_filter is not None and isinstance(infra_filter, str):
        target_infra = infra_filter
    if group_filter is not None and isinstance(group_filter, str):
        target_group = group_filter
    if name_filter is not None and isinstance(name_filter, str):
        target_name = name_filter
    if type_filter is not None and isinstance(type_filter, str):
        target_type = type_filter

    resources_file_path: Path = Path("").resolve().joinpath(resources_file)
    patch_resources(
        resources_file_path=resources_file_path,
        target_env=target_env,
        target_infra=target_infra,
        target_group=target_group,
        target_name=target_name,
        target_type=target_type,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        force=force,
    )


@agno_cli.command(short_help="Restart resources defined in a resources.py file")
def restart(
    resources_file: str = typer.Argument(
        "resources.py",
        help="Path to workspace file.",
        show_default=False,
    ),
    env_filter: Optional[str] = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to deploy"),
    infra_filter: Optional[str] = typer.Option(None, "-i", "--infra", metavar="", help="Filter the infra to deploy."),
    group_filter: Optional[str] = typer.Option(
        None, "-g", "--group", metavar="", help="Filter resources using group name."
    ),
    name_filter: Optional[str] = typer.Option(None, "-n", "--name", metavar="", help="Filter using resource name"),
    type_filter: Optional[str] = typer.Option(
        None,
        "-t",
        "--type",
        metavar="",
        help="Filter using resource type",
    ),
    dry_run: bool = typer.Option(
        False,
        "-dr",
        "--dry-run",
        help="Print which resources will be deployed and exit.",
    ),
    auto_confirm: bool = typer.Option(
        False,
        "-y",
        "--yes",
        help="Skip the confirmation before deploying resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: bool = typer.Option(
        False,
        "-f",
        "--force",
        help="Force",
    ),
):
    """\b
    Restart resources defined in a resources.py file
    \b
    Examples:
    > `ag os restart`                -> Start resources defined in a resources.py file
    """
    from time import sleep

    from agno.cli.console import print_info

    stop(
        resources_file=resources_file,
        env_filter=env_filter,
        infra_filter=infra_filter,
        group_filter=group_filter,
        name_filter=name_filter,
        type_filter=type_filter,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        print_debug_log=print_debug_log,
        force=force,
    )
    print_info("Sleeping for 2 seconds..")
    sleep(2)
    start(
        resources_file=resources_file,
        env_filter=env_filter,
        infra_filter=infra_filter,
        group_filter=group_filter,
        name_filter=name_filter,
        type_filter=type_filter,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        print_debug_log=print_debug_log,
        force=force,
    )

agno_cli.add_typer(os_cli)