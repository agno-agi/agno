"""Agno Infra Cli

This is the entrypoint for the `agno infra` application.
"""

from pathlib import Path
from typing import List, Optional, cast

import typer

from agno.cli.console import (
    log_active_infra_not_available,
    log_config_not_available_msg,
    print_available_infra,
    print_info,
)
from agno.infra.config import InfraConfig
from agno.utilities.logging import logger, set_log_level_to_debug

infra_cli = typer.Typer(
    name="infra",
    short_help="Manage Agent Infrastructure",
    help="""\b
Use `ag infra [COMMAND]` to create, setup, start or stop your infrastructure.
Run `ag infra [COMMAND] --help` for more info.
""",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
    options_metavar="",
    subcommand_metavar="[COMMAND] [OPTIONS]",
)


@infra_cli.command(short_help="Create a new AgentOS codebase in the current directory.")
def create(
    name: Optional[str] = typer.Option(
        None,
        "-n",
        "--name",
        help="Name of the new AgentOS codebase directory (e.g. `my-agentos-project`).",
        show_default=False,
    ),
    template: Optional[str] = typer.Option(
        None,
        "-t",
        "--template",
        help="Starter template for the Agno AgentOS codebase.",
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
    Create a new AgentOS Infrastructure project in the current directory using a starter template
    \b
    Examples:
    > ag infra create -t agentos-aws-template                        -> Create an `agentos-aws-template` in the current directory
    > ag infra create -t agentos-aws-template -n my-agentos-template     -> Create an `agentos-aws-template` named `my-agentos-template` in the current directory
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.infra.operator import create_infra_from_template

    create_infra_from_template(name=name, template=template, url=url)


@infra_cli.command(short_help="Start the resources for the active AgentOS codebase")
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
    Create resources for the active AgentOS codebase
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
    > `ag infra up`            -> Deploy all resources
    > `ag infra up dev`        -> Deploy all dev resources
    > `ag infra up prd`        -> Deploy all prd resources
    > `ag infra up prd:aws`    -> Deploy all prd aws resources
    > `ag infra up prd:::s3`   -> Deploy prd resources matching name s3
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.cli.utils import find_compose_files, run_docker_compose_up
    from agno.infra.helpers import get_infra_dir_path
    from agno.infra.operator import setup_infra_config_from_dir, start_infra
    from agno.utilities.resource_filter import parse_resource_filter

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return
    agno_config = cast(AgnoCliConfig, agno_config)

    # Workspace to start
    infra_to_start: Optional[InfraConfig] = None

    # If there is an existing infra project at current path, use that infra project
    current_path: Path = Path(".").resolve()
    infra_at_current_path: Optional[InfraConfig] = agno_config.get_infra_config_by_path(current_path)
    if infra_at_current_path is not None:
        logger.debug(f"Found Agno Infra project at: {infra_at_current_path.infra_root_path}")
        if str(infra_at_current_path.infra_root_path) != agno_config.active_infra_dir:
            logger.debug(f"Updating active Agno Infra project to {infra_at_current_path.infra_root_path}")
            agno_config.set_active_infra_dir(infra_at_current_path.infra_root_path)
        infra_to_start = infra_at_current_path

    # If there's no existing Infra at current path, check if there's a `infra` dir in the current path
    # In that case setup the Infra
    if infra_to_start is None:
        infra_infra_dir_path = get_infra_dir_path(current_path)
        if infra_infra_dir_path is not None:
            logger.debug(f"Found Infra directory: {infra_infra_dir_path}")
            logger.debug(f"Setting up a Infra at: {current_path}")
            infra_to_start = setup_infra_config_from_dir(infra_root_path=current_path)
            print_info("")

    # If there's no Infra at current path, check if an active Infra exists
    if infra_to_start is None:
        active_infra_config: Optional[InfraConfig] = agno_config.get_active_infra_config()
        # If there's an active Infra, use that Infra
        if active_infra_config is not None:
            infra_to_start = active_infra_config

    # If there's no Infra to start, raise an error showing available Infra
    if infra_to_start is None:
        log_active_infra_not_available()
        avl_infra = agno_config.available_infra
        if avl_infra:
            print_available_infra(avl_infra)

    # Check for docker compose files
    current_dir = Path.cwd()
    compose_files = find_compose_files(current_dir)
    if not compose_files and agno_config.active_infra_dir:
        compose_files = find_compose_files(Path(agno_config.active_infra_dir))
    if infra_to_start is None and not compose_files:
        return
    elif compose_files:
        from agno.cli.console import confirm_yes_no

        logger.info(f"Found Docker Compose files: {[f.name for f in compose_files]}")

        for compose_file in compose_files:
            if not dry_run:
                if not auto_confirm:
                    confirm = confirm_yes_no(f"Run docker compose up for {compose_file.name}?")
                    if not confirm:
                        continue

                # TODO: Use the -f flag logic to force build
                run_docker_compose_up(compose_file, build=True, detached=True)
            else:
                print(f"Would run: docker compose -f {compose_file} up -d --build")
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
    if target_env is None and infra_to_start and infra_to_start.infra_settings:
        target_env = infra_to_start.infra_settings.default_env if infra_to_start.infra_settings else None
    if target_infra is None and infra_to_start and infra_to_start.infra_settings:
        target_infra = infra_to_start.infra_settings.default_infra if infra_to_start.infra_settings else None

    start_infra(
        infra_config=infra_to_start,  # type: ignore
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


@infra_cli.command(short_help="Delete resources for active AgentOS codebase")
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
    Delete resources for the active AgentOS codebase.
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
    > `ag infra down`            -> Delete all resources
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.cli.utils import find_compose_files, run_docker_compose_down
    from agno.infra.helpers import get_infra_dir_path
    from agno.infra.operator import setup_infra_config_from_dir, stop_infra
    from agno.utilities.resource_filter import parse_resource_filter

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    # Infra to stop
    infra_to_stop: Optional[InfraConfig] = None

    # If there is an existing Infra at current path, use that Infra
    current_path: Path = Path(".").resolve()
    infra_at_current_path: Optional[InfraConfig] = agno_config.get_infra_config_by_path(current_path)
    if infra_at_current_path is not None:
        logger.debug(f"Found Infra at: {infra_at_current_path.infra_root_path}")
        if str(infra_at_current_path.infra_root_path) != agno_config.active_infra_dir:
            logger.debug(f"Updating active Infra to {infra_at_current_path.infra_root_path}")
            agno_config.set_active_infra_dir(infra_at_current_path.infra_root_path)
        infra_to_stop = infra_at_current_path

    # If there's no existing Infra at current path, check if there's a `infra` dir in the current path
    # In that case setup the Infra
    if infra_to_stop is None:
        infra_infra_dir_path = get_infra_dir_path(current_path)
        if infra_infra_dir_path is not None:
            logger.debug(f"Found infra directory: {infra_infra_dir_path}")
            logger.debug(f"Setting up a Infra at: {current_path}")
            infra_to_stop = setup_infra_config_from_dir(infra_root_path=current_path)
            print_info("")

    # If there's no Infra at current path, check if an active Infra exists
    if infra_to_stop is None:
        active_infra_config: Optional[InfraConfig] = agno_config.get_active_infra_config()
        # If there's an active Infra, use that Infra
        if active_infra_config is not None:
            infra_to_stop = active_infra_config

    # If there's no Infra to stop, raise an error showing available Infra
    if infra_to_stop is None:
        log_active_infra_not_available()
        avl_infra = agno_config.available_infra
        if avl_infra:
            print_available_infra(avl_infra)

    # Check for docker compose files
    current_dir = Path.cwd()
    compose_files = find_compose_files(current_dir)
    if not compose_files and agno_config.active_infra_dir:
        compose_files = find_compose_files(Path(agno_config.active_infra_dir))

    if infra_to_stop is None and not compose_files:
        return
    elif compose_files:
        from agno.cli.console import confirm_yes_no

        logger.info(f"Found Docker Compose files: {[f.name for f in compose_files]}")

        for compose_file in compose_files:
            if not dry_run:
                if not auto_confirm:
                    confirm = confirm_yes_no(f"Run docker compose down for {compose_file.name}?")
                    if not confirm:
                        continue

                run_docker_compose_down(compose_file, remove_volumes=False)
            else:
                print(f"Would run: docker compose -f {compose_file} down")
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
    if target_env is None and infra_to_stop and infra_to_stop.infra_settings:
        target_env = infra_to_stop.infra_settings.default_env if infra_to_stop.infra_settings else None
    if target_infra is None and infra_to_stop and infra_to_stop.infra_settings:
        target_infra = infra_to_stop.infra_settings.default_infra if infra_to_stop.infra_settings else None

    stop_infra(
        infra_config=infra_to_stop,  # type: ignore
        target_env=target_env,
        target_infra=target_infra,
        target_group=target_group,
        target_name=target_name,
        target_type=target_type,
        dry_run=dry_run,
        auto_confirm=auto_confirm,
        force=force,
    )


@infra_cli.command(short_help="Update resources for active AgentOS codebase")
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
    Update resources for the active AgentOS codebase.
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
    > `ag infra patch`           -> Patch all resources
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.infra.helpers import get_infra_dir_path
    from agno.infra.operator import setup_infra_config_from_dir, update_infra
    from agno.utilities.resource_filter import parse_resource_filter

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    # Infra to patch
    infra_to_patch: Optional[InfraConfig] = None

    # If there is an existing Infra at current path, use that Infra
    current_path: Path = Path(".").resolve()
    infra_at_current_path: Optional[InfraConfig] = agno_config.get_infra_config_by_path(current_path)
    if infra_at_current_path is not None:
        logger.debug(f"Found infra at: {infra_at_current_path.infra_root_path}")
        if str(infra_at_current_path.infra_root_path) != agno_config.active_infra_dir:
            logger.debug(f"Updating active infra to {infra_at_current_path.infra_root_path}")
            agno_config.set_active_infra_dir(infra_at_current_path.infra_root_path)
        infra_to_patch = infra_at_current_path

    # If there's no existing Infra at current path, check if there's a `infra` dir in the current path
    # In that case setup the Infra
    if infra_to_patch is None:
        infra_infra_dir_path = get_infra_dir_path(current_path)
        if infra_infra_dir_path is not None:
            logger.debug(f"Found infra directory: {infra_infra_dir_path}")
            logger.debug(f"Setting up a Infra at: {current_path}")
            infra_to_patch = setup_infra_config_from_dir(infra_root_path=current_path)
            print_info("")

    # If there's no Infra at current path, check if an active Infra exists
    if infra_to_patch is None:
        active_infra_config: Optional[InfraConfig] = agno_config.get_active_infra_config()
        # If there's an active Infra, use that Infra
        if active_infra_config is not None:
            infra_to_patch = active_infra_config

    # If there's no Infra to patch, raise an error showing available Infra
    if infra_to_patch is None:
        log_active_infra_not_available()
        avl_infra = agno_config.available_infra
        if avl_infra:
            print_available_infra(avl_infra)
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
        target_env = infra_to_patch.infra_settings.default_env if infra_to_patch.infra_settings else None
    if target_infra is None:
        target_infra = infra_to_patch.infra_settings.default_infra if infra_to_patch.infra_settings else None

    update_infra(
        infra_config=infra_to_patch,
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


@infra_cli.command(short_help="Restart resources for active AgentOS codebase")
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
    Restarts the active AgentOS codebase. i.e. runs `ag infra down` and then `ag infra up`.

    \b
    Examples:
    > `ag infra restart`
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


@infra_cli.command(short_help="Prints active AgentOS codebase config")
def config(
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Prints the active AgentOS codebase config

    \b
    Examples:
    $ `ag infra config`         -> Print the active Infra config
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.utilities.load_env import load_env

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    active_infra_config: Optional[InfraConfig] = agno_config.get_active_infra_config()
    if active_infra_config is None:
        log_active_infra_not_available()
        avl_infra = agno_config.available_infra
        if avl_infra:
            print_available_infra(avl_infra)
        return

    # Load environment from .env
    load_env(
        dotenv_dir=active_infra_config.infra_root_path,
    )
    print_info(active_infra_config.model_dump_json(include={"infra_name", "infra_root_path"}, indent=2))


@infra_cli.command(short_help="Delete AgentOS codebase infra record")
def delete(
    infra_name: Optional[str] = typer.Option(None, "-infra", help="Name of the AgentOS codebase to delete"),
    print_debug_log: bool = typer.Option(
        False,
        "-d",
        "--debug",
        help="Print debug logs.",
    ),
):
    """\b
    Deletes the AgentOS codebase record from agno_infra.
    NOTE: Does not delete any physical files.

    \b
    Examples:
    $ `ag infra delete`         -> Delete the active AgentOS codebase from Agno
    """
    if print_debug_log:
        set_log_level_to_debug()

    from agno.cli.config import AgnoCliConfig
    from agno.cli.operator import initialize_agno_cli
    from agno.infra.operator import delete_infra

    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    infra_to_delete: List[Path] = []
    # Delete Infra by name if provided
    if infra_name is not None:
        infra_config = agno_config.get_infra_config_by_dir_name(infra_name)
        if infra_config is None:
            logger.error(f"AgentOS codebase {infra_name} not found")
            return
        infra_to_delete.append(infra_config.infra_root_path)
    else:
        # By default, we assume this command is run for the active Infra
        if agno_config.active_infra_dir is not None:
            infra_to_delete.append(Path(agno_config.active_infra_dir))

    delete_infra(agno_config, infra_to_delete)
