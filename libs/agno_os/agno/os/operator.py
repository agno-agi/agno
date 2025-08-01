from pathlib import Path
from typing import Dict, List, Optional, cast

from rich.prompt import Prompt

from agno.cli.config import AgnoCliConfig
from agno.cli.console import (
    console,
    log_config_not_available_msg,
    print_heading,
    print_info,
    print_subheading,
)
from agno.constants import OSStarterTemplate
from agno.infra.resources import InfraResources
from agno.os.config import OSConfig
from agno.utils.logging import logger

TEMPLATE_TO_NAME_MAP: Dict[OSStarterTemplate, str] = {
    OSStarterTemplate.agent_api: "agent-api",
}
TEMPLATE_TO_REPO_MAP: Dict[OSStarterTemplate, str] = {
    OSStarterTemplate.agent_api: "https://github.com/agno-agi/agent-api-template",
}


def create_os_from_template(
    name: Optional[str] = None, template: Optional[str] = None, url: Optional[str] = None
) -> Optional[OSConfig]:
    """Creates a new os from a template and returns the OSConfig.

    This function clones a template or url on the users machine at the path:
        cwd/name
    """
    from shutil import copytree

    import git

    from agno.cli.operator import initialize_agno_cli
    from agno.os.helpers import get_os_infra_dir_path
    from agno.utils.filesystem import rmdir_recursive
    from agno.utils.git import GitCloneProgress

    current_dir: Path = Path("").resolve()

    # Initialize Agno before creating a OS
    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return None
    agno_config = cast(AgnoCliConfig, agno_config)

    os_dir_name: Optional[str] = name
    repo_to_clone: Optional[str] = url
    os_template = OSStarterTemplate.agent_api
    templates = list(OSStarterTemplate.__members__.values())

    if repo_to_clone is None:
        # Get repo_to_clone from template
        if template is None:
            # Get starter template from the user if template is not provided
            # Display available starter templates and ask user to select one
            print_info("Select starter template or press Enter for default (agent-app)")
            for template_id, template_name in enumerate(templates, start=1):
                print_info("  [b][{}][/b] {}".format(template_id, OSStarterTemplate(template_name).value))

            # Get starter template from the user
            template_choices = [str(idx) for idx, _ in enumerate(templates, start=1)]
            template_inp_raw = Prompt.ask("Template Number", choices=template_choices, default="1", show_choices=False)
            # Convert input to int
            template_inp = int(template_inp_raw) if template_inp_raw is not None else None

            if template_inp is not None:
                template_inp_idx = template_inp - 1
                os_template = OSStarterTemplate(templates[template_inp_idx])
        elif template.lower() in OSStarterTemplate.__members__.values():
            os_template = OSStarterTemplate(template)
        else:
            raise Exception(f"{template} is not a supported template, please choose from: {templates}")

        logger.debug(f"Selected Template: {os_template.value}")
        repo_to_clone = TEMPLATE_TO_REPO_MAP.get(os_template)

    if os_dir_name is None:
        default_os_name = "agent-api"
        if url is not None:
            # Get default_os_name from url
            default_os_name = url.split("/")[-1].split(".")[0]
        else:
            # Get default_os_name from template
            default_os_name = TEMPLATE_TO_NAME_MAP.get(os_template, "agent-api")
        logger.debug(f"Asking for os name with default: {default_os_name}")
        # Ask user for os name if not provided
        os_dir_name = Prompt.ask("OS Name", default=default_os_name, console=console)

    if repo_to_clone is None:
        logger.error("URL or Template is required")
        return None

    # Check if we can create the os in the current dir
    os_root_path: Path = current_dir.joinpath(os_dir_name)
    if os_root_path.exists():
        logger.error(f"Directory {os_root_path} exists, please delete directory or choose another name for os")
        return None

    print_info(f"Creating {str(os_root_path)}")
    logger.debug("Cloning: {}".format(repo_to_clone))
    try:
        git.Repo.clone_from(
            repo_to_clone,
            str(os_root_path),
            progress=GitCloneProgress(),  # type: ignore
        )
    except Exception as e:
        logger.error(e)
        return None

    # Remove existing .git folder
    _dot_git_folder = os_root_path.joinpath(".git")
    _dot_git_exists = _dot_git_folder.exists()
    if _dot_git_exists:
        logger.debug(f"Deleting {_dot_git_folder}")
        try:
            _dot_git_exists = not rmdir_recursive(_dot_git_folder)
        except Exception as e:
            logger.warning(f"Failed to delete {_dot_git_folder}: {e}")
            logger.info("Please delete the .git folder manually")
            pass

    agno_config.add_new_os_to_config(os_root_path=os_root_path)

    try:
        # os_dir_path is the path to the os_root/os dir
        os_dir_path: Path = get_os_infra_dir_path(os_root_path)
        os_secrets_dir = os_dir_path.joinpath("secrets").resolve()
        os_example_secrets_dir = os_dir_path.joinpath("example_secrets").resolve()

        print_info(f"Creating {str(os_secrets_dir)}")
        copytree(
            str(os_example_secrets_dir),
            str(os_secrets_dir),
        )
    except Exception as e:
        logger.warning(f"Could not create infra/secrets: {e}")
        logger.warning("Please manually copy infra/example_secrets to infra/secrets")

    print_info(f"Your new os is available at {str(os_root_path)}\n")
    return setup_os(os_root_path=os_root_path)


def setup_os(os_root_path: Path) -> Optional[OSConfig]:
    """Setup an Agno OS project at `os_root_path` and return the OSConfig

    1. Steps
    1.1 Check if os_root_path exists and is a directory
    1.2 Create AgnoCliConfig if needed
    1.3 Create a OSConfig if needed
    1.4 Get the OS name
    1.5 Create or update OSConfig
    """
    from agno.cli.operator import initialize_agno_cli
    from agno.os.helpers import get_os_infra_dir_path
    from agno.utils.git import get_remote_origin_for_dir

    print_heading("Setting up os\n")

    ######################################################
    ## 1. Steps
    ######################################################
    # 1.1 Check os_root_path exists and is a directory
    os_is_valid: bool = os_root_path is not None and os_root_path.exists() and os_root_path.is_dir()
    if not os_is_valid:
        logger.error("Invalid directory: {}".format(os_root_path))
        return None

    # 1.2 Create AgnoCliConfig if needed
    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return None

    # 1.3 Create a OSConfig if needed
    logger.debug(f"Checking for a os at {os_root_path}")
    os_config: Optional[OSConfig] = agno_config.get_os_config_by_path(os_root_path)
    if os_config is None:
        # There's no record of this os, reasons:
        # - The user is setting up a new os
        # - The user ran `ag init -r` which erased existing os
        logger.debug(f"Could not find a os at: {os_root_path}")

        # Check if the os contains a `os` dir
        os_os_dir_path = get_os_infra_dir_path(os_root_path)
        logger.debug(f"Found the `os` configuration at: {os_os_dir_path}")
        os_config = agno_config.create_or_update_os_config(os_root_path=os_root_path, set_as_active=True)
        if os_config is None:
            logger.error(f"Failed to create OSConfig for {os_root_path}")
            return None
    else:
        logger.debug(f"Found os at {os_root_path}")

    # 1.4 Get the os name
    os_name = os_root_path.stem.replace(" ", "-").replace("_", "-").lower()
    logger.debug(f"OS name: {os_name}")

    # 1.5 Get the git remote origin url
    git_remote_origin_url: Optional[str] = get_remote_origin_for_dir(os_root_path)
    logger.debug("Git origin: {}".format(git_remote_origin_url))

    # 1.6 Create or update OSConfig
    os_config = agno_config.create_or_update_os_config(os_root_path=os_root_path, set_as_active=True)

    if os_config is not None:
        print_subheading("Setup complete! Next steps:")
        print_info("1. Start OS:")
        print_info("\tag os up")
        print_info("2. Stop OS:")
        print_info("\tag os down")

        return os_config
    else:
        print_info("OS setup unsuccessful. Please try again.")
    return None

    ######################################################
    ## End OS setup
    ######################################################


def start_os(
    os_config: OSConfig,
    target_env: Optional[str] = None,
    target_infra: Optional[str] = None,
    target_group: Optional[str] = None,
    target_name: Optional[str] = None,
    target_type: Optional[str] = None,
    dry_run: Optional[bool] = False,
    auto_confirm: Optional[bool] = False,
    force: Optional[bool] = None,
    pull: Optional[bool] = False,
) -> None:
    """Start an Agno OS. This is called from `ag os up`"""

    print_heading("Starting os: {}".format(str(os_config.os_root_path.stem)))
    logger.debug(f"\ttarget_env   : {target_env}")
    logger.debug(f"\ttarget_infra : {target_infra}")
    logger.debug(f"\ttarget_group : {target_group}")
    logger.debug(f"\ttarget_name  : {target_name}")
    logger.debug(f"\ttarget_type  : {target_type}")
    logger.debug(f"\tdry_run      : {dry_run}")
    logger.debug(f"\tauto_confirm : {auto_confirm}")
    logger.debug(f"\tforce        : {force}")
    logger.debug(f"\tpull         : {pull}")

    # Set the local environment variables before processing configs
    os_config.set_local_env()

    # Get resource groups to deploy
    resource_groups_to_create: List[InfraResources] = os_config.get_resources(
        env=target_env,
        infra=target_infra,
        order="create",
    )

    # Track number of resource groups created
    num_rgs_created = 0
    num_rgs_to_create = len(resource_groups_to_create)
    # Track number of resources created
    num_resources_created = 0
    num_resources_to_create = 0

    if num_rgs_to_create == 0:
        print_info("No resources to create")
        return

    logger.debug(f"Deploying {num_rgs_to_create} resource groups")
    for rg in resource_groups_to_create:
        _num_resources_created, _num_resources_to_create = rg.create_resources(
            group_filter=target_group,
            name_filter=target_name,
            type_filter=target_type,
            dry_run=dry_run,
            auto_confirm=auto_confirm,
            force=force,
            pull=pull,
        )
        if _num_resources_created > 0:
            num_rgs_created += 1
        num_resources_created += _num_resources_created
        num_resources_to_create += _num_resources_to_create
        logger.debug(f"Deployed {num_resources_created} resources in {num_rgs_created} resource groups")

    if dry_run:
        return

    if num_resources_created == 0:
        return

    print_heading(f"\n--**-- ResourceGroups deployed: {num_rgs_created}/{num_rgs_to_create}\n")

    if num_resources_created != num_resources_to_create:
        logger.error("Some resources failed to create, please check logs")


def stop_os(
    os_config: OSConfig,
    target_env: Optional[str] = None,
    target_infra: Optional[str] = None,
    target_group: Optional[str] = None,
    target_name: Optional[str] = None,
    target_type: Optional[str] = None,
    dry_run: Optional[bool] = False,
    auto_confirm: Optional[bool] = False,
    force: Optional[bool] = None,
) -> None:
    """Stop an Agno OS. This is called from `ag os down`"""
    print_heading("Stopping os: {}".format(str(os_config.os_root_path.stem)))
    logger.debug(f"\ttarget_env   : {target_env}")
    logger.debug(f"\ttarget_infra : {target_infra}")
    logger.debug(f"\ttarget_group : {target_group}")
    logger.debug(f"\ttarget_name  : {target_name}")
    logger.debug(f"\ttarget_type  : {target_type}")
    logger.debug(f"\tdry_run      : {dry_run}")
    logger.debug(f"\tauto_confirm : {auto_confirm}")
    logger.debug(f"\tforce        : {force}")

    # Set the local environment variables before processing configs
    os_config.set_local_env()

    # Get resource groups to delete
    resource_groups_to_delete: List[InfraResources] = os_config.get_resources(
        env=target_env,
        infra=target_infra,
        order="delete",
    )

    # Track number of resource groups deleted
    num_rgs_deleted = 0
    num_rgs_to_delete = len(resource_groups_to_delete)
    # Track number of resources deleted
    num_resources_deleted = 0
    num_resources_to_delete = 0

    if num_rgs_to_delete == 0:
        print_info("No resources to delete")
        return

    logger.debug(f"Deleting {num_rgs_to_delete} resource groups")
    for rg in resource_groups_to_delete:
        _num_resources_deleted, _num_resources_to_delete = rg.delete_resources(
            group_filter=target_group,
            name_filter=target_name,
            type_filter=target_type,
            dry_run=dry_run,
            auto_confirm=auto_confirm,
            force=force,
        )
        if _num_resources_deleted > 0:
            num_rgs_deleted += 1
        num_resources_deleted += _num_resources_deleted
        num_resources_to_delete += _num_resources_to_delete
        logger.debug(f"Deleted {num_resources_deleted} resources in {num_rgs_deleted} resource groups")

    if dry_run:
        return

    if num_resources_deleted == 0:
        return

    print_heading(f"\n--**-- ResourceGroups deleted: {num_rgs_deleted}/{num_rgs_to_delete}\n")

    if num_resources_to_delete != num_resources_deleted:
        logger.error("Some resources failed to delete, please check logs")


def update_os(
    os_config: OSConfig,
    target_env: Optional[str] = None,
    target_infra: Optional[str] = None,
    target_group: Optional[str] = None,
    target_name: Optional[str] = None,
    target_type: Optional[str] = None,
    dry_run: Optional[bool] = False,
    auto_confirm: Optional[bool] = False,
    force: Optional[bool] = None,
    pull: Optional[bool] = False,
) -> None:
    """Update an Agno OS. This is called from `ag os patch`"""
    print_heading("Updating os: {}".format(str(os_config.os_root_path.stem)))
    logger.debug(f"\ttarget_env   : {target_env}")
    logger.debug(f"\ttarget_infra : {target_infra}")
    logger.debug(f"\ttarget_group : {target_group}")
    logger.debug(f"\ttarget_name  : {target_name}")
    logger.debug(f"\ttarget_type  : {target_type}")
    logger.debug(f"\tdry_run      : {dry_run}")
    logger.debug(f"\tauto_confirm : {auto_confirm}")
    logger.debug(f"\tforce        : {force}")
    logger.debug(f"\tpull         : {pull}")

    # Set the local environment variables before processing configs
    os_config.set_local_env()

    # Get resource groups to update
    resource_groups_to_update: List[InfraResources] = os_config.get_resources(
        env=target_env,
        infra=target_infra,
        order="create",
    )
    # Track number of resource groups updated
    num_rgs_updated = 0
    num_rgs_to_update = len(resource_groups_to_update)
    # Track number of resources updated
    num_resources_updated = 0
    num_resources_to_update = 0

    if num_rgs_to_update == 0:
        print_info("No resources to update")
        return

    logger.debug(f"Updating {num_rgs_to_update} resource groups")
    for rg in resource_groups_to_update:
        _num_resources_updated, _num_resources_to_update = rg.update_resources(
            group_filter=target_group,
            name_filter=target_name,
            type_filter=target_type,
            dry_run=dry_run,
            auto_confirm=auto_confirm,
            force=force,
            pull=pull,
        )
        if _num_resources_updated > 0:
            num_rgs_updated += 1
        num_resources_updated += _num_resources_updated
        num_resources_to_update += _num_resources_to_update
        logger.debug(f"Updated {num_resources_updated} resources in {num_rgs_updated} resource groups")

    if dry_run:
        return

    if num_resources_updated == 0:
        return

    print_heading(f"\n--**-- ResourceGroups updated: {num_rgs_updated}/{num_rgs_to_update}\n")

    if num_resources_updated != num_resources_to_update:
        logger.error("Some resources failed to update, please check logs")


def delete_os(agno_config: AgnoCliConfig, os_to_delete: Optional[List[Path]]) -> None:
    if os_to_delete is None or len(os_to_delete) == 0:
        print_heading("No os to delete")
        return

    for os_root in os_to_delete:
        agno_config.delete_os(os_root_path=os_root)


def set_os_as_active(os_dir_name: Optional[str]) -> None:
    from agno.cli.operator import initialize_agno_cli

    ######################################################
    ## 1. Validate Pre-requisites
    ######################################################
    ######################################################
    # 1.1 Check AgnoCliConfig is valid
    ######################################################
    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return

    ######################################################
    # 1.2 Check os_root_path is valid
    ######################################################
    # By default, we assume this command is run from the infra directory
    if os_dir_name is None:
        # If the user does not provide a ws_name, that implies `ag set` is ran from
        # the infra directory.
        os_root_path = Path("").resolve()
    else:
        # If the user provides a os name manually, we find the dir for that os
        os_config: Optional[OSConfig] = agno_config.get_os_config_by_dir_name(os_dir_name)
        if os_config is None:
            logger.error(f"Could not find os {os_dir_name}")
            return
        os_root_path = os_config.os_root_path

    os_dir_is_valid: bool = os_root_path is not None and os_root_path.exists() and os_root_path.is_dir()
    if not os_dir_is_valid:
        logger.error("Invalid os directory: {}".format(os_root_path))
        return

    ######################################################
    # 1.3 Validate OSConfig is available i.e. a OS is available at this directory
    ######################################################
    logger.debug(f"Checking for a os at path: {os_root_path}")
    active_os_config: Optional[OSConfig] = agno_config.get_os_config_by_path(os_root_path)
    if active_os_config is None:
        # This happens when the os is not yet setup
        print_info(f"Could not find a os at path: {os_root_path}")
        # TODO: setup automatically for the user
        print_info("If this os has not been setup, please run `ag os setup` from the os directory")
        return

    ######################################################
    ## 2. Set OS as active
    ######################################################
    print_heading(f"Setting os {active_os_config.os_root_path.stem} as active")
    agno_config.set_active_os_dir(active_os_config.os_root_path)
    print_info("Active os updated")
    return
