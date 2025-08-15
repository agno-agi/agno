"""Agno OS Cli

This is the entrypoint for the `agno os` application.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional, cast

import typer

from agno.cli.console import (
    log_active_os_not_available,
    log_config_not_available_msg,
    print_available_os,
    print_info,
)
from agno.utils.logging import logger, set_log_level_to_debug

os_cli = typer.Typer(
    name="os",
    short_help="Manage OS",
    help="""\b
Use `ag os [COMMAND]` to create, setup, start or stop your os.
Run `ag os [COMMAND] --help` for more info.
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="",
    subcommand_metavar="[COMMAND] [OPTIONS]",
)


@os_cli.command(short_help="Create a new OS in the current directory.")
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
    > ag os create -t agent-api                -> Create an `agent-api` in the current directory
    > ag os create -t agent-api -n my-agent-api   -> Create an `agent-api` named `my-agent-api` in the current directory
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.os.operator import create_os_from_template

    create_os_from_template(name=name, template=template, url=url)


@os_cli.command(short_help="Setup OS from the current directory")
def setup(
    path: Optional[str] = typer.Argument(
        None,
        help="Path to OS [default: current directory]",
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
    Setup a OS. This command can be run from the OS directory OR using the OS path.
    \b
    Examples:
    > `ag os setup`           -> Setup the current directory as a OS
    > `ag os setup agent-api`    -> Setup the `agent-api` folder as a OS
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.os.operator import setup_os

    # By default, we assume this command is run from the OS directory
    os_root_path: Path = Path("").resolve()

    # If the user provides a path, use that to setup the OS
    if path is not None:
        os_root_path = Path("").joinpath(path).resolve()
    setup_os(os_root_path=os_root_path)


@os_cli.command(short_help="Create resources for the active OS")
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
    Create resources for the active OS
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
    > `ag os up`            -> Deploy all resources
    > `ag os up dev`        -> Deploy all dev resources
    > `ag os up prd`        -> Deploy all prd resources
    > `ag os up prd:aws`    -> Deploy all prd aws resources
    > `ag os up prd:::s3`   -> Deploy prd resources matching name s3
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.os.config import OSConfig
    from agno.os.helpers import get_os_infra_dir_path
    from agno.os.operator import setup_os, start_os
    from agno.utils.resource_filter import parse_resource_filter

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return
    agno_config = cast(AgnoCliConfig, agno_config)

    # OS to start
    os_to_start: Optional[OSConfig] = None

    # If there is an existing OS at current path, use that OS
    current_path: Path = Path("").resolve()
    os_at_current_path: Optional[OSConfig] = agno_config.get_os_config_by_path(current_path)
    if os_at_current_path is not None:
        logger.debug(f"Found OS at: {os_at_current_path.os_root_path}")
        if str(os_at_current_path.os_root_path) != agno_config.active_os_dir:
            logger.debug(f"Updating active OS to {os_at_current_path.os_root_path}")
            agno_config.set_active_os_dir(os_at_current_path.os_root_path)
        os_to_start = os_at_current_path

    # If there's no existing OS at current path, check if there's a `infra` dir in the current path
    # In that case setup the OS
    if os_to_start is None:
        os_os_dir_path = get_os_infra_dir_path(current_path)
        if os_os_dir_path is not None:
            logger.debug(f"Found OS directory: {os_os_dir_path}")
            logger.debug(f"Setting up a OS at: {current_path}")
            os_to_start = setup_os(os_root_path=current_path)
            print_info("")

    # If there's no OS at current path, check if an active OS exists
    if os_to_start is None:
        active_os_config: Optional[OSConfig] = agno_config.get_active_os_config()
        # If there's an active OS, use that OS
        if active_os_config is not None:
            os_to_start = active_os_config

    # If there's no OS to start, raise an error showing available OSs
    if os_to_start is None:
        log_active_os_not_available()
        avl_os = agno_config.available_os
        if avl_os:
            print_available_os(avl_os)
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
        target_env = os_to_start.os_settings.default_env if os_to_start.os_settings else None
    if target_infra is None:
        target_infra = os_to_start.os_settings.default_infra if os_to_start.os_settings else None

    start_os(
        agno_config=agno_config,
        os_config=os_to_start,
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


@os_cli.command(short_help="Delete resources for active OS")
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
    Delete resources for the active OS.
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
    > `ag os down`            -> Delete all resources
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.os.config import OSConfig
    from agno.os.helpers import get_os_infra_dir_path
    from agno.os.operator import setup_os, stop_os
    from agno.utils.resource_filter import parse_resource_filter

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    # OS to stop
    os_to_stop: Optional[OSConfig] = None

    # If there is an existing OS at current path, use that OS
    current_path: Path = Path("").resolve()
    os_at_current_path: Optional[OSConfig] = agno_config.get_os_config_by_path(current_path)
    if os_at_current_path is not None:
        logger.debug(f"Found OS at: {os_at_current_path.os_root_path}")
        if str(os_at_current_path.os_root_path) != agno_config.active_os_dir:
            logger.debug(f"Updating active OS to {os_at_current_path.os_root_path}")
            agno_config.set_active_os_dir(os_at_current_path.os_root_path)
        os_to_stop = os_at_current_path

    # If there's no existing OS at current path, check if there's a `infra` dir in the current path
    # In that case setup the OS
    if os_to_stop is None:
        os_os_dir_path = get_os_infra_dir_path(current_path)
        if os_os_dir_path is not None:
            logger.debug(f"Found OS directory: {os_os_dir_path}")
            logger.debug(f"Setting up a OS at: {current_path}")
            os_to_stop = setup_os(os_root_path=current_path)
            print_info("")

    # If there's no OS at current path, check if an active OS exists
    if os_to_stop is None:
        active_os_config: Optional[OSConfig] = agno_config.get_active_os_config()
        # If there's an active OS, use that OS
        if active_os_config is not None:
            os_to_stop = active_os_config

    # If there's no OS to stop, raise an error showing available OSs
    if os_to_stop is None:
        log_active_os_not_available()
        avl_os = agno_config.available_os
        if avl_os:
            print_available_os(avl_os)
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
        target_env = os_to_stop.os_settings.default_env if os_to_stop.os_settings else None
    if target_infra is None:
        target_infra = os_to_stop.os_settings.default_infra if os_to_stop.os_settings else None

    stop_os(
        agno_config=agno_config,
        os_config=os_to_stop,
        target_env=target_env,
        target_infra=target_infra,
        target_group=target_group,
        target_name=target_name,
        target_type=target_type,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        force=force,
    )


@os_cli.command(short_help="Update resources for active OS")
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
    Update resources for the active OS.
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
    > `ag os patch`           -> Patch all resources
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.os.config import OSConfig
    from agno.os.helpers import get_os_infra_dir_path
    from agno.os.operator import setup_os, update_os
    from agno.utils.resource_filter import parse_resource_filter

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    # OS to patch
    os_to_patch: Optional[OSConfig] = None

    # If there is an existing OS at current path, use that OS
    current_path: Path = Path("").resolve()
    os_at_current_path: Optional[OSConfig] = agno_config.get_os_config_by_path(current_path)
    if os_at_current_path is not None:
        logger.debug(f"Found OS at: {os_at_current_path.os_root_path}")
        if str(os_at_current_path.os_root_path) != agno_config.active_os_dir:
            logger.debug(f"Updating active OS to {os_at_current_path.os_root_path}")
            agno_config.set_active_os_dir(os_at_current_path.os_root_path)
        os_to_patch = os_at_current_path

    # If there's no existing OS at current path, check if there's a `infra` dir in the current path
    # In that case setup the OS
    if os_to_patch is None:
        os_os_dir_path = get_os_infra_dir_path(current_path)
        if os_os_dir_path is not None:
            logger.debug(f"Found OS directory: {os_os_dir_path}")
            logger.debug(f"Setting up a OS at: {current_path}")
            os_to_patch = setup_os(os_root_path=current_path)
            print_info("")

    # If there's no OS at current path, check if an active OS exists
    if os_to_patch is None:
        active_os_config: Optional[OSConfig] = agno_config.get_active_os_config()
        # If there's an active OS, use that OS
        if active_os_config is not None:
            os_to_patch = active_os_config

    # If there's no OS to patch, raise an error showing available OSs
    if os_to_patch is None:
        log_active_os_not_available()
        avl_os = agno_config.available_os
        if avl_os:
            print_available_os(avl_os)
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
        target_env = os_to_patch.os_settings.default_env if os_to_patch.os_settings else None
    if target_infra is None:
        target_infra = os_to_patch.os_settings.default_infra if os_to_patch.os_settings else None

    update_os(
        agno_config=agno_config,
        os_config=os_to_patch,
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


@os_cli.command(short_help="Restart resources for active OS")
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
    Restarts the active OS. i.e. runs `ag os down` and then `ag os up`.

    \b
    Examples:
    > `ag os restart`
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


@os_cli.command(short_help="Prints active OS config")
def config(
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Prints the active OS config

    \b
    Examples:
    $ `ag os config`         -> Print the active OS config
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.os.config import OSConfig
    from agno.utils.load_env import load_env

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    active_os_config: Optional[OSConfig] = agno_config.get_active_os_config()
    if active_os_config is None:
        log_active_os_not_available()
        avl_os = agno_config.available_os
        if avl_os:
            print_available_os(avl_os)
        return

    # Load environment from .env
    load_env(
        dotenv_dir=active_os_config.os_root_path,
    )
    active_os_config_dict = asdict(active_os_config)
    print_info(json.dumps(active_os_config_dict, indent=2))


@os_cli.command(short_help="Delete OS record")
def delete(
    os_name: Optional[str] = typer.Option(None, "-os", help="Name of the OS to delete"),
    all_os: bool = typer.Option(
        False,
        "-a",
        "--all",
        help="Delete all OSs from Agno",
    ),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Deletes the OS record from agno.
    NOTE: Does not delete any physical files.

    \b
    Examples:
    $ `ag os delete`         -> Delete the active OS from Agno
    $ `ag os delete -a`      -> Delete all OSs from Agno
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.os.operator import delete_os

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    os_to_delete: List[Path] = []
    # Delete OS by name if provided
    if os_name is not None:
        os_config = agno_config.get_os_config_by_dir_name(os_name)
        if os_config is None:
            logger.error(f"OS {os_name} not found")
            return
        os_to_delete.append(os_config.os_root_path)
    else:
        # Delete all OSs if flag is set
        if all_os:
            os_to_delete = [os.os_root_path for os in agno_config.available_os if os.os_root_path is not None]
        else:
            # By default, we assume this command is run for the active OS
            if agno_config.active_os_dir is not None:
                os_to_delete.append(Path(agno_config.active_os_dir))

    delete_os(agno_config, os_to_delete)
