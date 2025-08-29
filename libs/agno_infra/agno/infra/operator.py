from pathlib import Path
from typing import Dict, List, Optional, cast

from rich.prompt import Prompt

from agno.base.resources import InfraResources
from agno.cli.config import AgnoCliConfig
from agno.cli.console import (
    console,
    log_config_not_available_msg,
    print_heading,
    print_info,
    print_subheading,
)
from agno.infra.config import InfraConfig
from agno.infra.enums import InfraStarterTemplate
from agno.utilities.logging import log_warning, logger
from agno.utils.log import log_info

TEMPLATE_TO_NAME_MAP: Dict[InfraStarterTemplate, str] = {
    InfraStarterTemplate.agent_infra_docker: "agent-infra-docker",
}
TEMPLATE_TO_REPO_MAP: Dict[InfraStarterTemplate, str] = {
    InfraStarterTemplate.agent_infra_docker: "https://github.com/agno-agi/agent-infra-docker",
}


def create_infra_from_template(
    name: Optional[str] = None, template: Optional[str] = None, url: Optional[str] = None
) -> Optional[InfraConfig]:
    """Creates a new infra from a template and returns the InfraConfig.

    This function clones a template or url on the users machine at the path:
        cwd/name
    """
    from shutil import copytree

    import git

    from agno.cli.operator import initialize_agno_cli
    from agno.infra.helpers import get_infra_dir_path
    from agno.utilities.filesystem import rmdir_recursive
    from agno.utilities.git import GitCloneProgress

    current_dir: Path = Path("").resolve()

    # Initialize Agno before creating a Infra
    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return None
    agno_config = cast(AgnoCliConfig, agno_config)

    infra_dir_name: Optional[str] = name
    repo_to_clone: Optional[str] = url
    infra_template = InfraStarterTemplate.agent_infra_docker
    templates = list(InfraStarterTemplate.__members__.values())

    if repo_to_clone is None:
        # Get repo_to_clone from template
        if template is None:
            # Get starter template from the user if template is not provided
            # Display available starter templates and ask user to select one
            print_info("Select starter template or press Enter for default (agent-infra-docker)")
            for template_id, template_name in enumerate(templates, start=1):
                print_info("  [b][{}][/b] {}".format(template_id, InfraStarterTemplate(template_name).value))

            # Get starter template from the user
            template_choices = [str(idx) for idx, _ in enumerate(templates, start=1)]
            template_inp_raw = Prompt.ask("Chosen Template", choices=template_choices, default="1", show_choices=False)
            # Convert input to int
            template_inp = int(template_inp_raw) if template_inp_raw is not None else None

            if template_inp is not None:
                template_inp_idx = template_inp - 1
                infra_template = InfraStarterTemplate(templates[template_inp_idx])
        elif template.lower() in InfraStarterTemplate.__members__.values():
            infra_template = InfraStarterTemplate(template)
        else:
            raise Exception(f"{template} is not a supported template, please choose from: {templates}")

        logger.debug(f"Selected Template: {infra_template.value}")
        repo_to_clone = TEMPLATE_TO_REPO_MAP.get(infra_template)

    if infra_dir_name is None:
        default_infra_name = "agent-infra-docker"
        if url is not None:
            # Get default_infra_name from url
            default_infra_name = url.split("/")[-1].split(".")[0]
        else:
            # Get default_infra_name from template
            default_infra_name = TEMPLATE_TO_NAME_MAP.get(infra_template, "agent-infra-docker")
        logger.debug(f"Asking for infra name with default: {default_infra_name}")
        # Ask user for infra name if not provided
        infra_dir_name = Prompt.ask("Infra Project Directory", default=default_infra_name, console=console)

    if repo_to_clone is None:
        logger.error("URL or Template is required")
        return None

    # Check if we can create the infra in the current dir
    infra_root_path: Path = current_dir.joinpath(infra_dir_name)
    if infra_root_path.exists():
        logger.error(f"Directory {infra_root_path} exists, please delete directory or choose another name for infra")
        return None

    print_info(f"Creating {str(infra_root_path)}")
    logger.debug("Cloning: {}".format(repo_to_clone))
    try:
        git.Repo.clone_from(
            repo_to_clone,
            str(infra_root_path),
            progress=GitCloneProgress(),  # type: ignore
        )
    except Exception as e:
        logger.error(e)
        return None

    # Remove existing .git folder
    _dot_git_folder = infra_root_path.joinpath(".git")
    _dot_git_exists = _dot_git_folder.exists()
    if _dot_git_exists:
        logger.debug(f"Deleting {_dot_git_folder}")
        try:
            _dot_git_exists = not rmdir_recursive(_dot_git_folder)
        except Exception as e:
            log_warning(f"Failed to delete {_dot_git_folder}: {e}")
            log_info("Please delete the .git folder manually")
            pass

    agno_config.add_new_infra_to_config(infra_root_path=infra_root_path)

    try:
        # infra_dir_path is the path to the infra_root/infra dir
        infra_dir_path: Path = get_infra_dir_path(infra_root_path)
        infra_secrets_dir = infra_dir_path.joinpath("secrets").resolve()
        infra_example_secrets_dir = infra_dir_path.joinpath("example_secrets").resolve()

        print_info(f"Creating {str(infra_secrets_dir)}")
        copytree(
            str(infra_example_secrets_dir),
            str(infra_secrets_dir),
        )
    except Exception as e:
        log_warning(f"Could not create infra/secrets: {e}")
        log_warning("Please manually copy infra/example_secrets to infra/secrets")

    print_info(f"Your new infra is available at {str(infra_root_path)}\n")
    return setup_infra(infra_root_path=infra_root_path)


def setup_infra(infra_root_path: Path) -> Optional[InfraConfig]:
    """Setup an Agno Infra project at `infra_root_path` and return the InfraConfig

    1. Steps
    1.1 Check if infra_root_path exists and is a directory
    1.2 Create AgnoCliConfig if needed
    1.3 Create a InfraConfig if needed
    1.4 Get the Infra name
    1.5 Create or update InfraConfig
    """
    from agno.cli.operator import initialize_agno_cli
    from agno.infra.helpers import get_infra_dir_path
    from agno.utilities.git import get_remote_origin_for_dir

    print_heading("Setting up infra\n")

    ######################################################
    ## 1. Steps
    ######################################################
    # 1.1 Check infra_root_path exists and is a directory
    infra_is_valid: bool = infra_root_path is not None and infra_root_path.exists() and infra_root_path.is_dir()
    if not infra_is_valid:
        logger.error("Invalid directory: {}".format(infra_root_path))
        return None

    # 1.2 Create AgnoCliConfig if needed
    agno_config: Optional[AgnoCliConfig] = AgnoCliConfig.from_saved_config()
    if not agno_config:
        agno_config = initialize_agno_cli()
        if not agno_config:
            log_config_not_available_msg()
            return None

    # 1.3 Create a InfraConfig if needed
    logger.debug(f"Checking for a infra at {infra_root_path}")
    infra_config: Optional[InfraConfig] = agno_config.get_infra_config_by_path(infra_root_path)
    if infra_config is None:
        # There's no record of this infra, reasons:
        # - The user is setting up a new infra
        # - The user ran `ag init -r` which erased existing infra
        logger.debug(f"Could not find a infra at: {infra_root_path}")

        # Check if the infra contains a `infra` dir
        infra_dir_path = get_infra_dir_path(infra_root_path)
        logger.debug(f"Found the `infra` configuration at: {infra_dir_path}")
        infra_config = agno_config.create_or_update_infra_config(infra_root_path=infra_root_path, set_as_active=True)
        if infra_config is None:
            logger.error(f"Failed to create InfraConfig for {infra_root_path}")
            return None
    else:
        logger.debug(f"Found infra at {infra_root_path}")

    # 1.4 Get the infra name
    infra_name = infra_root_path.stem.replace(" ", "-").replace("_", "-").lower()
    logger.debug(f"Infra name: {infra_name}")

    # 1.5 Get the git remote origin url
    git_remote_origin_url: Optional[str] = get_remote_origin_for_dir(infra_root_path)
    logger.debug("Git origin: {}".format(git_remote_origin_url))

    # 1.6 Create or update InfraConfig
    infra_config = agno_config.create_or_update_infra_config(infra_root_path=infra_root_path, set_as_active=True)

    if infra_config is not None:
        print_subheading("Setup complete! Next steps:")
        print_info("1. Start Infra:")
        print_info("\tag infra up")
        print_info("2. Stop Infra:")
        print_info("\tag infra down")

        return infra_config
    else:
        print_info("Infra setup unsuccessful. Please try again.")
    return None

    ######################################################
    ## End Infra setup
    ######################################################


def start_infra(
    infra_config: InfraConfig,
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
    """Start an Agno Infra. This is called from `ag infra up`"""

    print_heading("Starting infra: {}".format(str(infra_config.infra_root_path.stem)))
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
    infra_config.set_local_env()

    # Get resource groups to deploy
    resource_groups_to_create: List[InfraResources] = infra_config.get_resources(
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


def stop_infra(
    infra_config: InfraConfig,
    target_env: Optional[str] = None,
    target_infra: Optional[str] = None,
    target_group: Optional[str] = None,
    target_name: Optional[str] = None,
    target_type: Optional[str] = None,
    dry_run: Optional[bool] = False,
    auto_confirm: Optional[bool] = False,
    force: Optional[bool] = None,
) -> None:
    """Stop an Agno Infra. This is called from `ag infra down`"""
    print_heading("Stopping infra: {}".format(str(infra_config.infra_root_path.stem)))
    logger.debug(f"\ttarget_env   : {target_env}")
    logger.debug(f"\ttarget_infra : {target_infra}")
    logger.debug(f"\ttarget_group : {target_group}")
    logger.debug(f"\ttarget_name  : {target_name}")
    logger.debug(f"\ttarget_type  : {target_type}")
    logger.debug(f"\tdry_run      : {dry_run}")
    logger.debug(f"\tauto_confirm : {auto_confirm}")
    logger.debug(f"\tforce        : {force}")

    # Set the local environment variables before processing configs
    infra_config.set_local_env()

    # Get resource groups to delete
    resource_groups_to_delete: List[InfraResources] = infra_config.get_resources(
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


def update_infra(
    infra_config: InfraConfig,
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
    """Update an Agno Infra. This is called from `ag infra patch`"""
    print_heading("Updating infra: {}".format(str(infra_config.infra_root_path.stem)))
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
    infra_config.set_local_env()

    # Get resource groups to update
    resource_groups_to_update: List[InfraResources] = infra_config.get_resources(
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


def delete_infra(agno_config: AgnoCliConfig, infra_to_delete: Optional[List[Path]]) -> None:
    if infra_to_delete is None or len(infra_to_delete) == 0:
        print_heading("No infra to delete")
        return

    for infra_root in infra_to_delete:
        agno_config.delete_infra(infra_root_path=infra_root)


def set_infra_as_active(infra_dir_name: Optional[str]) -> None:
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
    # 1.2 Check infra_root_path is valid
    ######################################################
    # By default, we assume this command is run from the infra directory
    if infra_dir_name is None:
        # If the user does not provide a infra_name, that implies `ag set` is ran from
        # the infra directory.
        infra_root_path = Path("").resolve()
    else:
        # If the user provides a infra name manually, we find the dir for that infra
        infra_config: Optional[InfraConfig] = agno_config.get_infra_config_by_dir_name(infra_dir_name)
        if infra_config is None:
            logger.error(f"Could not find infra {infra_dir_name}")
            return
        infra_root_path = infra_config.infra_root_path

    infra_dir_is_valid: bool = infra_root_path is not None and infra_root_path.exists() and infra_root_path.is_dir()
    if not infra_dir_is_valid:
        logger.error("Invalid infra directory: {}".format(infra_root_path))
        return

    ######################################################
    # 1.3 Validate InfraConfig is available i.e. a Infra is available at this directory
    ######################################################
    logger.debug(f"Checking for a infra at path: {infra_root_path}")
    active_infra_config: Optional[InfraConfig] = agno_config.get_infra_config_by_path(infra_root_path)
    if active_infra_config is None:
        # This happens when the infra is not yet setup
        print_info(f"Could not find a infra at path: {infra_root_path}")
        # TODO: setup automatically for the user
        print_info("If this infra has not been setup, please run `ag infra setup` from the infra directory")
        return

    ######################################################
    ## 2. Set Infra as active
    ######################################################
    print_heading(f"Setting infra {active_infra_config.infra_root_path.stem} as active")
    agno_config.set_active_infra_dir(active_infra_config.infra_root_path)
    print_info("Active infra updated")
    return
