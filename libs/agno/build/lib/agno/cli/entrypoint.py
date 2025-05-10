"""Agno cli

This is the entrypoint for the `agno` cli application.
"""

from typing import Optional

import typer

from agno.cli.ws.ws_cli import ws_cli
from agno.utils.log import set_log_level_to_debug

agno_cli = typer.Typer(
    help="""\b
Agno is a model-agnostic framework for building AI Agents.
\b
Usage:
1. Run `ag ws create` to create a new workspace
2. Run `ag ws up` to start the workspace
3. Run `ag ws down` to stop the workspace
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="\b",
    subcommand_metavar="[COMMAND] [OPTIONS]",
    pretty_exceptions_show_locals=False,
)


@agno_cli.command(short_help="Setup your account")
def setup(
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """
    \b
    Setup Agno on your machine
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.operator import initialize_agno

    initialize_agno(login=True)


@agno_cli.command(short_help="Initialize Agno, use -r to reset")
def init(
    reset: bool = typer.Option(False, "--reset", "-r", help="Reset Agno", show_default=True),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    login: bool = typer.Option(False, "--login", "-l", help="Login with agno.com", show_default=True),
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

    from agno.cli.operator import initialize_agno

    initialize_agno(reset=reset, login=login)


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

    from agno.cli.operator import initialize_agno

    initialize_agno(reset=True)


@agno_cli.command(short_help="Ping Agno servers")
def ping(
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """Ping the Agno servers and check if you are authenticated"""
    if print_debug_log:
        set_log_level_to_debug()

    from agno.api.user import user_ping
    from agno.cli.console import print_info

    ping_success = user_ping()
    if ping_success:
        print_info("Ping successful")
    else:
        print_info("Could not ping Agno servers")


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
    from agno.cli.operator import initialize_agno

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
        if not agno_config:
            log_config_not_available_msg()
            return
    agno_config.print_to_cli(show_all=True)


@agno_cli.command(short_help="Set current directory as active workspace")
def set(
    ws_name: str = typer.Option(None, "-ws", help="Active workspace name"),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """
    \b
    Set the current directory as the active workspace.
    This command can be run from within the workspace directory
        OR with a -ws flag to set another workspace as primary.

    \b
    Examples:
    $ `ag ws set`           -> Set the current directory as the active Agno workspace
    $ `ag ws set -ws idata` -> Set the workspace named idata as the active Agno workspace
    """
    from agno.workspace.operator import set_workspace_as_active

    if print_debug_log:
        set_log_level_to_debug()

    set_workspace_as_active(ws_dir_name=ws_name)


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
    > `ag ws start`                -> Start resources defined in a resources.py file
    > `ag ws start workspace.py`   -> Start resources defined in a workspace.py file
    """
    if print_debug_log:
        set_log_level_to_debug()

    from pathlib import Path

    from agno.cli.config import AgnoCliConfig
    from agno.cli.console import log_config_not_available_msg
    from agno.cli.operator import initialize_agno, start_resources

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
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

    resources_file_path: Path = Path(".").resolve().joinpath(resources_file)
    start_resources(
        agno_config=agno_config,
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
    > `ag ws stop`                -> Stop resources defined in a resources.py file
    > `ag ws stop workspace.py`   -> Stop resources defined in a workspace.py file
    """
    if print_debug_log:
        set_log_level_to_debug()

    from pathlib import Path

    from agno.cli.config import AgnoCliConfig
    from agno.cli.console import log_config_not_available_msg
    from agno.cli.operator import initialize_agno, stop_resources

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
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

    resources_file_path: Path = Path(".").resolve().joinpath(resources_file)
    stop_resources(
        agno_config=agno_config,
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
    config_filter: Optional[str] = typer.Option(None, "-c", "--config", metavar="", help="Filter the config to deploy"),
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
    > `ag ws patch`                -> Update resources defined in a resources.py file
    > `ag ws patch workspace.py`   -> Update resources defined in a workspace.py file
    """
    if print_debug_log:
        set_log_level_to_debug()

    from pathlib import Path

    from agno.cli.config import AgnoCliConfig
    from agno.cli.console import log_config_not_available_msg
    from agno.cli.operator import initialize_agno, patch_resources

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
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

    resources_file_path: Path = Path(".").resolve().joinpath(resources_file)
    patch_resources(
        agno_config=agno_config,
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
    > `ag ws restart`                -> Start resources defined in a resources.py file
    > `ag ws restart workspace.py`   -> Start resources defined in a workspace.py file
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


agno_cli.add_typer(ws_cli)
