"""Agno Workspace Cli

This is the entrypoint for the `agno ws` application.
"""

from pathlib import Path
from typing import List, Optional, cast

import typer

from agno.cli.console import (
    log_active_workspace_not_available,
    log_config_not_available_msg,
    print_available_workspaces,
    print_info,
)
from agno.utils.log import logger, set_log_level_to_debug

ws_cli = typer.Typer(
    name="ws",
    short_help="Manage workspaces",
    help="""\b
Use `ag ws [COMMAND]` to create, setup, start or stop your workspace.
Run `ag ws [COMMAND] --help` for more info.
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="",
    subcommand_metavar="[COMMAND] [OPTIONS]",
)


@ws_cli.command(short_help="Create a new workspace in the current directory.")
def create(
    name: Optional[str] = typer.Option(
        None,
        "-n",
        "--name",
        help="Name of the new workspace.",
        show_default=False,
    ),
    template: Optional[str] = typer.Option(
        None,
        "-t",
        "--template",
        help="Starter template for the workspace.",
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
    Create a new workspace in the current directory using a starter template or url
    \b
    Examples:
    > ag ws create -t ai-app                -> Create an `ai-app` in the current directory
    > ag ws create -t ai-app -n my-ai-app   -> Create an `ai-app` named `my-ai-app` in the current directory
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.workspace.operator import create_workspace

    create_workspace(name=name, template=template, url=url)


@ws_cli.command(short_help="Setup workspace from the current directory")
def setup(
    path: Optional[str] = typer.Argument(
        None,
        help="Path to workspace [default: current directory]",
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
    Setup a workspace. This command can be run from the workspace directory OR using the workspace path.
    \b
    Examples:
    > `ag ws setup`           -> Setup the current directory as a workspace
    > `ag ws setup ai-app`    -> Setup the `ai-app` folder as a workspace
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.workspace.operator import setup_workspace

    # By default, we assume this command is run from the workspace directory
    ws_root_path: Path = Path(".").resolve()

    # If the user provides a path, use that to setup the workspace
    if path is not None:
        ws_root_path = Path(".").joinpath(path).resolve()
    setup_workspace(ws_root_path=ws_root_path)


@ws_cli.command(short_help="Create resources for the active workspace")
def up(
    resource_filter: Optional[str] = typer.Argument(
        None,
        help="Resource filter. Format - ENV:INFRA:GROUP:NAME:TYPE",
    ),
    env_filter: Optional[str] = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to deploy."),
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
        help="Skip confirmation before deploying resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: Optional[bool] = typer.Option(
        None,
        "-f",
        "--force",
        help="Force create resources where applicable.",
    ),
    pull: Optional[bool] = typer.Option(
        None,
        "-p",
        "--pull",
        help="Pull images where applicable.",
    ),
):
    """\b
    Create resources for the active workspace
    Options can be used to limit the resources to create.
      --env     : Env (dev, stg, prd)
      --infra   : Infra type (docker, aws)
      --group   : Group name
      --name    : Resource name
      --type    : Resource type
    \b
    Options can also be provided as a RESOURCE_FILTER in the format: ENV:INFRA:GROUP:NAME:TYPE
    \b
    Examples:
    > `ag ws up`            -> Deploy all resources
    > `ag ws up dev`        -> Deploy all dev resources
    > `ag ws up prd`        -> Deploy all prd resources
    > `ag ws up prd:aws`    -> Deploy all prd aws resources
    > `ag ws up prd:::s3`   -> Deploy prd resources matching name s3
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno
    from agno.utils.resource_filter import parse_resource_filter
    from agno.workspace.config import WorkspaceConfig
    from agno.workspace.helpers import get_workspace_dir_path
    from agno.workspace.operator import setup_workspace, start_workspace

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
        if not agno_config:
            log_config_not_available_msg()
            return
    agno_config = cast(AgnoCliConfig, agno_config)

    # Workspace to start
    ws_to_start: Optional[WorkspaceConfig] = None

    # If there is an existing workspace at current path, use that workspace
    current_path: Path = Path(".").resolve()
    ws_at_current_path: Optional[WorkspaceConfig] = agno_config.get_ws_config_by_path(current_path)
    if ws_at_current_path is not None:
        logger.debug(f"Found workspace at: {ws_at_current_path.ws_root_path}")
        if str(ws_at_current_path.ws_root_path) != agno_config.active_ws_dir:
            logger.debug(f"Updating active workspace to {ws_at_current_path.ws_root_path}")
            agno_config.set_active_ws_dir(ws_at_current_path.ws_root_path)
        ws_to_start = ws_at_current_path

    # If there's no existing workspace at current path, check if there's a `workspace` dir in the current path
    # In that case setup the workspace
    if ws_to_start is None:
        workspace_ws_dir_path = get_workspace_dir_path(current_path)
        if workspace_ws_dir_path is not None:
            logger.debug(f"Found workspace directory: {workspace_ws_dir_path}")
            logger.debug(f"Setting up a workspace at: {current_path}")
            ws_to_start = setup_workspace(ws_root_path=current_path)
            print_info("")

    # If there's no workspace at current path, check if an active workspace exists
    if ws_to_start is None:
        active_ws_config: Optional[WorkspaceConfig] = agno_config.get_active_ws_config()
        # If there's an active workspace, use that workspace
        if active_ws_config is not None:
            ws_to_start = active_ws_config

    # If there's no workspace to start, raise an error showing available workspaces
    if ws_to_start is None:
        log_active_workspace_not_available()
        avl_ws = agno_config.available_ws
        if avl_ws:
            print_available_workspaces(avl_ws)
        return

    target_env: Optional[str] = None
    target_infra: Optional[str] = None
    target_group: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None

    # derive env:infra:name:type:group from ws_filter
    if resource_filter is not None:
        if not isinstance(resource_filter, str):
            raise TypeError(f"Invalid resource_filter. Expected: str, Received: {type(resource_filter)}")
        (
            target_env,
            target_infra,
            target_group,
            target_name,
            target_type,
        ) = parse_resource_filter(resource_filter)

    # derive env:infra:name:type:group from command options
    if target_env is None and env_filter is not None and isinstance(env_filter, str):
        target_env = env_filter
    if target_infra is None and infra_filter is not None and isinstance(infra_filter, str):
        target_infra = infra_filter
    if target_group is None and group_filter is not None and isinstance(group_filter, str):
        target_group = group_filter
    if target_name is None and name_filter is not None and isinstance(name_filter, str):
        target_name = name_filter
    if target_type is None and type_filter is not None and isinstance(type_filter, str):
        target_type = type_filter

    # derive env:infra:name:type:group from defaults
    if target_env is None:
        target_env = ws_to_start.workspace_settings.default_env if ws_to_start.workspace_settings else None
    if target_infra is None:
        target_infra = ws_to_start.workspace_settings.default_infra if ws_to_start.workspace_settings else None

    start_workspace(
        agno_config=agno_config,
        ws_config=ws_to_start,
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


@ws_cli.command(short_help="Delete resources for active workspace")
def down(
    resource_filter: Optional[str] = typer.Argument(
        None,
        help="Resource filter. Format - ENV:INFRA:GROUP:NAME:TYPE",
    ),
    env_filter: str = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to shut down."),
    infra_filter: Optional[str] = typer.Option(
        None, "-i", "--infra", metavar="", help="Filter the infra to shut down."
    ),
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
        help="Skip the confirmation before deleting resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: bool = typer.Option(
        None,
        "-f",
        "--force",
        help="Force",
    ),
):
    """\b
    Delete resources for the active workspace.
    Options can be used to limit the resources to delete.
      --env     : Env (dev, stg, prd)
      --infra   : Infra type (docker, aws)
      --group   : Group name
      --name    : Resource name
      --type    : Resource type
    \b
    Options can also be provided as a RESOURCE_FILTER in the format: ENV:INFRA:GROUP:NAME:TYPE
    \b
    Examples:
    > `ag ws down`            -> Delete all resources
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno
    from agno.utils.resource_filter import parse_resource_filter
    from agno.workspace.config import WorkspaceConfig
    from agno.workspace.helpers import get_workspace_dir_path
    from agno.workspace.operator import setup_workspace, stop_workspace

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
        if not agno_config:
            log_config_not_available_msg()
            return

    # Workspace to stop
    ws_to_stop: Optional[WorkspaceConfig] = None

    # If there is an existing workspace at current path, use that workspace
    current_path: Path = Path(".").resolve()
    ws_at_current_path: Optional[WorkspaceConfig] = agno_config.get_ws_config_by_path(current_path)
    if ws_at_current_path is not None:
        logger.debug(f"Found workspace at: {ws_at_current_path.ws_root_path}")
        if str(ws_at_current_path.ws_root_path) != agno_config.active_ws_dir:
            logger.debug(f"Updating active workspace to {ws_at_current_path.ws_root_path}")
            agno_config.set_active_ws_dir(ws_at_current_path.ws_root_path)
        ws_to_stop = ws_at_current_path

    # If there's no existing workspace at current path, check if there's a `workspace` dir in the current path
    # In that case setup the workspace
    if ws_to_stop is None:
        workspace_ws_dir_path = get_workspace_dir_path(current_path)
        if workspace_ws_dir_path is not None:
            logger.debug(f"Found workspace directory: {workspace_ws_dir_path}")
            logger.debug(f"Setting up a workspace at: {current_path}")
            ws_to_stop = setup_workspace(ws_root_path=current_path)
            print_info("")

    # If there's no workspace at current path, check if an active workspace exists
    if ws_to_stop is None:
        active_ws_config: Optional[WorkspaceConfig] = agno_config.get_active_ws_config()
        # If there's an active workspace, use that workspace
        if active_ws_config is not None:
            ws_to_stop = active_ws_config

    # If there's no workspace to stop, raise an error showing available workspaces
    if ws_to_stop is None:
        log_active_workspace_not_available()
        avl_ws = agno_config.available_ws
        if avl_ws:
            print_available_workspaces(avl_ws)
        return

    target_env: Optional[str] = None
    target_infra: Optional[str] = None
    target_group: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None

    # derive env:infra:name:type:group from ws_filter
    if resource_filter is not None:
        if not isinstance(resource_filter, str):
            raise TypeError(f"Invalid resource_filter. Expected: str, Received: {type(resource_filter)}")
        (
            target_env,
            target_infra,
            target_group,
            target_name,
            target_type,
        ) = parse_resource_filter(resource_filter)

    # derive env:infra:name:type:group from command options
    if target_env is None and env_filter is not None and isinstance(env_filter, str):
        target_env = env_filter
    if target_infra is None and infra_filter is not None and isinstance(infra_filter, str):
        target_infra = infra_filter
    if target_group is None and group_filter is not None and isinstance(group_filter, str):
        target_group = group_filter
    if target_name is None and name_filter is not None and isinstance(name_filter, str):
        target_name = name_filter
    if target_type is None and type_filter is not None and isinstance(type_filter, str):
        target_type = type_filter

    # derive env:infra:name:type:group from defaults
    if target_env is None:
        target_env = ws_to_stop.workspace_settings.default_env if ws_to_stop.workspace_settings else None
    if target_infra is None:
        target_infra = ws_to_stop.workspace_settings.default_infra if ws_to_stop.workspace_settings else None

    stop_workspace(
        agno_config=agno_config,
        ws_config=ws_to_stop,
        target_env=target_env,
        target_infra=target_infra,
        target_group=target_group,
        target_name=target_name,
        target_type=target_type,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        force=force,
    )


@ws_cli.command(short_help="Update resources for active workspace")
def patch(
    resource_filter: Optional[str] = typer.Argument(
        None,
        help="Resource filter. Format - ENV:INFRA:GROUP:NAME:TYPE",
    ),
    env_filter: str = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to patch."),
    infra_filter: Optional[str] = typer.Option(None, "-i", "--infra", metavar="", help="Filter the infra to patch."),
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
        help="Skip the confirmation before patching resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: bool = typer.Option(
        None,
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
    Update resources for the active workspace.
    Options can be used to limit the resources to update.
      --env     : Env (dev, stg, prd)
      --infra   : Infra type (docker, aws)
      --group   : Group name
      --name    : Resource name
      --type    : Resource type
    \b
    Options can also be provided as a RESOURCE_FILTER in the format: ENV:INFRA:GROUP:NAME:TYPE
    Examples:
    \b
    > `ag ws patch`           -> Patch all resources
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno
    from agno.utils.resource_filter import parse_resource_filter
    from agno.workspace.config import WorkspaceConfig
    from agno.workspace.helpers import get_workspace_dir_path
    from agno.workspace.operator import setup_workspace, update_workspace

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
        if not agno_config:
            log_config_not_available_msg()
            return

    # Workspace to patch
    ws_to_patch: Optional[WorkspaceConfig] = None

    # If there is an existing workspace at current path, use that workspace
    current_path: Path = Path(".").resolve()
    ws_at_current_path: Optional[WorkspaceConfig] = agno_config.get_ws_config_by_path(current_path)
    if ws_at_current_path is not None:
        logger.debug(f"Found workspace at: {ws_at_current_path.ws_root_path}")
        if str(ws_at_current_path.ws_root_path) != agno_config.active_ws_dir:
            logger.debug(f"Updating active workspace to {ws_at_current_path.ws_root_path}")
            agno_config.set_active_ws_dir(ws_at_current_path.ws_root_path)
        ws_to_patch = ws_at_current_path

    # If there's no existing workspace at current path, check if there's a `workspace` dir in the current path
    # In that case setup the workspace
    if ws_to_patch is None:
        workspace_ws_dir_path = get_workspace_dir_path(current_path)
        if workspace_ws_dir_path is not None:
            logger.debug(f"Found workspace directory: {workspace_ws_dir_path}")
            logger.debug(f"Setting up a workspace at: {current_path}")
            ws_to_patch = setup_workspace(ws_root_path=current_path)
            print_info("")

    # If there's no workspace at current path, check if an active workspace exists
    if ws_to_patch is None:
        active_ws_config: Optional[WorkspaceConfig] = agno_config.get_active_ws_config()
        # If there's an active workspace, use that workspace
        if active_ws_config is not None:
            ws_to_patch = active_ws_config

    # If there's no workspace to patch, raise an error showing available workspaces
    if ws_to_patch is None:
        log_active_workspace_not_available()
        avl_ws = agno_config.available_ws
        if avl_ws:
            print_available_workspaces(avl_ws)
        return

    target_env: Optional[str] = None
    target_infra: Optional[str] = None
    target_group: Optional[str] = None
    target_name: Optional[str] = None
    target_type: Optional[str] = None

    # derive env:infra:name:type:group from ws_filter
    if resource_filter is not None:
        if not isinstance(resource_filter, str):
            raise TypeError(f"Invalid resource_filter. Expected: str, Received: {type(resource_filter)}")
        (
            target_env,
            target_infra,
            target_group,
            target_name,
            target_type,
        ) = parse_resource_filter(resource_filter)

    # derive env:infra:name:type:group from command options
    if target_env is None and env_filter is not None and isinstance(env_filter, str):
        target_env = env_filter
    if target_infra is None and infra_filter is not None and isinstance(infra_filter, str):
        target_infra = infra_filter
    if target_group is None and group_filter is not None and isinstance(group_filter, str):
        target_group = group_filter
    if target_name is None and name_filter is not None and isinstance(name_filter, str):
        target_name = name_filter
    if target_type is None and type_filter is not None and isinstance(type_filter, str):
        target_type = type_filter

    # derive env:infra:name:type:group from defaults
    if target_env is None:
        target_env = ws_to_patch.workspace_settings.default_env if ws_to_patch.workspace_settings else None
    if target_infra is None:
        target_infra = ws_to_patch.workspace_settings.default_infra if ws_to_patch.workspace_settings else None

    update_workspace(
        agno_config=agno_config,
        ws_config=ws_to_patch,
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


@ws_cli.command(short_help="Restart resources for active workspace")
def restart(
    resource_filter: Optional[str] = typer.Argument(
        None,
        help="Resource filter. Format - ENV:INFRA:GROUP:NAME:TYPE",
    ),
    env_filter: str = typer.Option(None, "-e", "--env", metavar="", help="Filter the environment to restart."),
    infra_filter: Optional[str] = typer.Option(None, "-i", "--infra", metavar="", help="Filter the infra to restart."),
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
        help="Skip the confirmation before restarting resources.",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
    force: bool = typer.Option(
        None,
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
    Restarts the active workspace. i.e. runs `ag ws down` and then `ag ws up`.

    \b
    Examples:
    > `ag ws restart`
    """
    if print_debug_log:
        set_log_level_to_debug()

    from time import sleep

    down(
        resource_filter=resource_filter,
        env_filter=env_filter,
        group_filter=group_filter,
        infra_filter=infra_filter,
        name_filter=name_filter,
        type_filter=type_filter,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        print_debug_log=print_debug_log,
        force=force,
    )
    print_info("Sleeping for 2 seconds..")
    sleep(2)
    up(
        resource_filter=resource_filter,
        env_filter=env_filter,
        infra_filter=infra_filter,
        group_filter=group_filter,
        name_filter=name_filter,
        type_filter=type_filter,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        print_debug_log=print_debug_log,
        force=force,
        pull=pull,
    )


@ws_cli.command(short_help="Prints active workspace config")
def config(
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Prints the active workspace config

    \b
    Examples:
    $ `ag ws config`         -> Print the active workspace config
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno
    from agno.utils.load_env import load_env
    from agno.workspace.config import WorkspaceConfig

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
        if not agno_config:
            log_config_not_available_msg()
            return

    active_ws_config: Optional[WorkspaceConfig] = agno_config.get_active_ws_config()
    if active_ws_config is None:
        log_active_workspace_not_available()
        avl_ws = agno_config.available_ws
        if avl_ws:
            print_available_workspaces(avl_ws)
        return

    # Load environment from .env
    load_env(
        dotenv_dir=active_ws_config.ws_root_path,
    )
    print_info(active_ws_config.model_dump_json(include={"ws_name", "ws_root_path"}, indent=2))


@ws_cli.command(short_help="Delete workspace record")
def delete(
    ws_name: Optional[str] = typer.Option(None, "-ws", help="Name of the workspace to delete"),
    all_workspaces: bool = typer.Option(
        False,
        "-a",
        "--all",
        help="Delete all workspaces from Agno",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Deletes the workspace record from agno.
    NOTE: Does not delete any physical files.

    \b
    Examples:
    $ `ag ws delete`         -> Delete the active workspace from Agno
    $ `ag ws delete -a`      -> Delete all workspaces from Agno
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno
    from agno.workspace.operator import delete_workspace

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno()
        if not agno_config:
            log_config_not_available_msg()
            return

    ws_to_delete: List[Path] = []
    # Delete workspace by name if provided
    if ws_name is not None:
        ws_config = agno_config.get_ws_config_by_dir_name(ws_name)
        if ws_config is None:
            logger.error(f"Workspace {ws_name} not found")
            return
        ws_to_delete.append(ws_config.ws_root_path)
    else:
        # Delete all workspaces if flag is set
        if all_workspaces:
            ws_to_delete = [ws.ws_root_path for ws in agno_config.available_ws if ws.ws_root_path is not None]
        else:
            # By default, we assume this command is run for the active workspace
            if agno_config.active_ws_dir is not None:
                ws_to_delete.append(Path(agno_config.active_ws_dir))

    delete_workspace(agno_config, ws_to_delete)
