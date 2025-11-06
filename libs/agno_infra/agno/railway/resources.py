"""Railway Resources orchestrator."""

from typing import List, Optional, Tuple

from pydantic import Field, PrivateAttr

from agno.base.resources import InfraResources
from agno.railway.api_client import RailwayApiClient
from agno.railway.app.base import RailwayApp
from agno.railway.context import RailwayBuildContext
from agno.railway.resource.base import RailwayResource
from agno.utilities.logging import logger


class RailwayResources(InfraResources):
    """Railway Resources orchestrator.

    Manages the lifecycle of Railway resources and applications.
    Provides create, update, and delete operations with dependency resolution.
    """

    infra: str = Field(default="railway", init=False)

    apps: Optional[List[RailwayApp]] = None
    resources: Optional[List[RailwayResource]] = None

    # Railway API token
    api_token: Optional[str] = None

    # Railway Workspace/Team ID
    workspace_id: Optional[str] = None

    # -*- Cached Data
    _api_client: Optional[RailwayApiClient] = PrivateAttr(default=None)

    def get_api_token(self) -> Optional[str]:
        """Get Railway API token with fallback priority."""
        # Priority 1: Use api_token from ResourceGroup (or cached value)
        if self.api_token:
            return self.api_token

        # Priority 2: Get api_token from infra settings
        if self.infra_settings is not None and hasattr(self.infra_settings, "railway_api_token"):
            if self.infra_settings.railway_api_token is not None:
                self.api_token = self.infra_settings.railway_api_token
                return self.api_token

        # Priority 3: Get api_token from env
        from os import getenv

        railway_api_token_env = getenv("RAILWAY_API_TOKEN")
        if railway_api_token_env is not None:
            logger.debug("Using RAILWAY_API_TOKEN from environment")
            self.api_token = railway_api_token_env
        return self.api_token

    def get_workspace_id(self) -> Optional[str]:
        """Get Railway workspace ID with fallback priority."""
        # Priority 1: Use workspace_id from ResourceGroup (or cached value)
        if self.workspace_id:
            return self.workspace_id

        # Priority 2: Get workspace_id from infra settings
        if self.infra_settings is not None and hasattr(self.infra_settings, "railway_workspace_id"):
            if self.infra_settings.railway_workspace_id is not None:
                self.workspace_id = self.infra_settings.railway_workspace_id
                return self.workspace_id

        # Priority 3: Get workspace_id from env
        from os import getenv

        workspace_env = getenv("RAILWAY_WORKSPACE_ID")
        if workspace_env is not None:
            logger.debug("Using RAILWAY_WORKSPACE_ID from environment")
            self.workspace_id = workspace_env
            return self.workspace_id

        # Priority 4: Auto-detect from user's workspaces
        try:
            workspaces = self.railway_client.get_user_workspaces()
            if workspaces and len(workspaces) > 0:
                # Use first workspace (usually personal workspace)
                self.workspace_id = workspaces[0]["id"]
                logger.info(f"Auto-detected workspace: {workspaces[0]['name']} (ID: {self.workspace_id})")
                return self.workspace_id
        except Exception as e:
            logger.warning(f"Failed to auto-detect workspace: {e}")

        return None

    @property
    def railway_client(self) -> RailwayApiClient:
        """Get or create Railway API client."""
        if self._api_client is None:
            self._api_client = RailwayApiClient(api_token=self.get_api_token())
        return self._api_client

    def create_resources(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
        dry_run: Optional[bool] = False,
        auto_confirm: Optional[bool] = False,
        force: Optional[bool] = None,
        pull: Optional[bool] = None,
    ) -> Tuple[int, int]:
        """Create Railway resources.

        Args:
            group_filter: Filter resources by group
            name_filter: Filter resources by name
            type_filter: Filter resources by type
            dry_run: If True, only print what would be created
            auto_confirm: If True, skip confirmation prompt
            force: If True, force recreation of existing resources
            pull: Not used for Railway

        Returns:
            Tuple of (number_created, total_number)
        """
        from agno.cli.console import confirm_yes_no, print_heading, print_info
        from agno.railway.resource.types import RailwayResourceInstallOrder

        logger.debug("-*- Creating RailwayResources")

        # Build a list of RailwayResources to create
        resources_to_create: List[RailwayResource] = []

        # Add resources to resources_to_create
        if self.resources is not None:
            for r in self.resources:
                r.set_infra_settings(infra_settings=self.infra_settings)
                if r.group is None and self.name is not None:
                    r.group = self.name
                if r.should_create(
                    group_filter=group_filter,
                    name_filter=name_filter,
                    type_filter=type_filter,
                ):
                    r.set_infra_settings(infra_settings=self.infra_settings)
                    resources_to_create.append(r)

        # Build a list of RailwayApps to create
        apps_to_create: List[RailwayApp] = []
        if self.apps is not None:
            for app in self.apps:
                if app.group is None and self.name is not None:
                    app.group = self.name
                if app.should_create(group_filter=group_filter):
                    apps_to_create.append(app)

        # Get the list of RailwayResources from the RailwayApps
        if len(apps_to_create) > 0:
            logger.debug(f"Found {len(apps_to_create)} apps to create")
            for app in apps_to_create:
                app.set_infra_settings(infra_settings=self.infra_settings)
                app_resources = app.get_resources(
                    build_context=RailwayBuildContext(
                        api_token=self.get_api_token(),
                        workspace_id=self.get_workspace_id(),
                    )
                )
                if len(app_resources) > 0:
                    # If the app has dependencies, add the resources from the
                    # dependencies first to the list of resources to create
                    if app.depends_on is not None:
                        for dep in app.depends_on:
                            if isinstance(dep, RailwayApp):
                                dep.set_infra_settings(infra_settings=self.infra_settings)
                                dep_resources = dep.get_resources(
                                    build_context=RailwayBuildContext(
                        api_token=self.get_api_token(),
                        workspace_id=self.get_workspace_id(),
                    )
                                )
                                if len(dep_resources) > 0:
                                    for dep_resource in dep_resources:
                                        if isinstance(dep_resource, RailwayResource):
                                            resources_to_create.append(dep_resource)
                    # Add the resources from the app to the list of resources to create
                    for app_resource in app_resources:
                        if isinstance(app_resource, RailwayResource) and app_resource.should_create(
                            group_filter=group_filter, name_filter=name_filter, type_filter=type_filter
                        ):
                            resources_to_create.append(app_resource)

        # Sort the RailwayResources in install order
        resources_to_create.sort(key=lambda x: RailwayResourceInstallOrder.get(x.__class__.__name__, 5000))

        # Deduplicate RailwayResources
        deduped_resources_to_create: List[RailwayResource] = []
        for r in resources_to_create:
            if r not in deduped_resources_to_create:
                deduped_resources_to_create.append(r)

        # Implement dependency sorting
        final_railway_resources: List[RailwayResource] = []
        logger.debug("-*- Building RailwayResources dependency graph")
        for railway_resource in deduped_resources_to_create:
            # Logic to follow if resource has dependencies
            if railway_resource.depends_on is not None and len(railway_resource.depends_on) > 0:
                # Add the dependencies before the resource itself
                for dep in railway_resource.depends_on:
                    if isinstance(dep, RailwayResource):
                        if dep not in final_railway_resources:
                            logger.debug(f"-*- Adding {dep.name}, dependency of {railway_resource.name}")
                            final_railway_resources.append(dep)

                # Add the resource to be created after its dependencies
                if railway_resource not in final_railway_resources:
                    logger.debug(f"-*- Adding {railway_resource.name}")
                    final_railway_resources.append(railway_resource)
            else:
                # Add the resource to be created if it has no dependencies
                if railway_resource not in final_railway_resources:
                    logger.debug(f"-*- Adding {railway_resource.name}")
                    final_railway_resources.append(railway_resource)

        # Track the total number of RailwayResources to create for validation
        num_resources_to_create: int = len(final_railway_resources)
        num_resources_created: int = 0
        if num_resources_to_create == 0:
            return 0, 0

        if dry_run:
            print_heading("--**- Railway resources to create:")
            for resource in final_railway_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            print_info(f"Total {num_resources_to_create} resources")
            return 0, 0

        # Validate resources to be created
        if not auto_confirm:
            print_heading("\n--**-- Confirm resources to create:")
            for resource in final_railway_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            print_info(f"Total {num_resources_to_create} resources")
            confirm = confirm_yes_no("\nConfirm deploy")
            if not confirm:
                print_info("-*-")
                print_info("-*- Skipping create")
                print_info("-*-")
                return 0, 0

        # Track last project creation time for rate limiting
        import time
        from agno.railway.resource.project import RailwayProject
        from agno.railway.resource.environment import RailwayEnvironment
        from agno.railway.resource.service import RailwayService
        from agno.railway.resource.variable import RailwayVariable

        last_project_creation = None
        created_project_ids = {}  # Map project names to IDs
        created_environment_ids = {}  # Map environment names to IDs

        for resource in final_railway_resources:
            print_info(f"\n-==+==- {resource.get_resource_type()}: {resource.get_resource_name()}")

            # Rate limiting: Railway allows only 1 project creation per 30 seconds
            if isinstance(resource, RailwayProject):
                if last_project_creation is not None:
                    elapsed = time.time() - last_project_creation
                    if elapsed < 30:
                        wait_time = 30 - elapsed
                        logger.info(f"Railway rate limit: waiting {wait_time:.0f}s before creating project...")
                        time.sleep(wait_time)
                last_project_creation = time.time()

            if force is True:
                resource.force = True
            try:
                _resource_created = resource.create(railway_client=self.railway_client)
                if _resource_created:
                    num_resources_created += 1

                    # Track created resource IDs and update dependent resources
                    if isinstance(resource, RailwayProject) and resource.railway_id:
                        project_name = resource.name
                        project_id = resource.railway_id
                        created_project_ids[project_name] = project_id
                        logger.debug(f"Tracked project ID: {project_name} -> {project_id}")

                        # Update all subsequent resources that reference this project
                        for subsequent_resource in final_railway_resources[final_railway_resources.index(resource) + 1 :]:
                            if hasattr(subsequent_resource, "project_id") and subsequent_resource.project_id in [
                                f"{{{{project.railway_id}}}}",
                                f"{{{{{project_name}.railway_id}}}}",
                            ]:
                                subsequent_resource.project_id = project_id
                                logger.debug(
                                    f"Updated {subsequent_resource.get_resource_name()}.project_id = {project_id}"
                                )

                    elif isinstance(resource, RailwayEnvironment) and resource.railway_id:
                        env_name = resource.name
                        env_id = resource.railway_id
                        created_environment_ids[env_name] = env_id
                        logger.debug(f"Tracked environment ID: {env_name} -> {env_id}")

                        # Update all subsequent resources that reference this environment
                        for subsequent_resource in final_railway_resources[final_railway_resources.index(resource) + 1 :]:
                            if hasattr(subsequent_resource, "environment_id") and subsequent_resource.environment_id in [
                                f"{{{{environment.railway_id}}}}",
                                f"{{{{{env_name}.railway_id}}}}",
                            ]:
                                subsequent_resource.environment_id = env_id
                                logger.debug(
                                    f"Updated {subsequent_resource.get_resource_name()}.environment_id = {env_id}"
                                )
                else:
                    if self.infra_settings is not None and not self.infra_settings.continue_on_create_failure:
                        return num_resources_created, num_resources_to_create
            except Exception as e:
                logger.error(f"Failed to create {resource.get_resource_type()}: {resource.get_resource_name()}")
                logger.error(e)
                logger.error("Please fix and try again...")

        print_heading(f"\n--**-- Resources created: {num_resources_created}/{num_resources_to_create}")
        if num_resources_to_create != num_resources_created:
            logger.error(
                f"Resources created: {num_resources_created} do not match resources required: {num_resources_to_create}"
            )
        return num_resources_created, num_resources_to_create

    def delete_resources(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
        dry_run: Optional[bool] = False,
        auto_confirm: Optional[bool] = False,
        force: Optional[bool] = None,
    ) -> Tuple[int, int]:
        """Delete Railway resources.

        Args:
            group_filter: Filter resources by group
            name_filter: Filter resources by name
            type_filter: Filter resources by type
            dry_run: If True, only print what would be deleted
            auto_confirm: If True, skip confirmation prompt
            force: If True, force deletion

        Returns:
            Tuple of (number_deleted, total_number)
        """
        from agno.cli.console import confirm_yes_no, print_heading, print_info
        from agno.railway.resource.types import RailwayResourceInstallOrder

        logger.debug("-*- Deleting RailwayResources")

        # Build a list of RailwayResources to delete
        resources_to_delete: List[RailwayResource] = []

        # Add resources to resources_to_delete
        if self.resources is not None:
            for r in self.resources:
                r.set_infra_settings(infra_settings=self.infra_settings)
                if r.group is None and self.name is not None:
                    r.group = self.name
                if r.should_delete(
                    group_filter=group_filter,
                    name_filter=name_filter,
                    type_filter=type_filter,
                ):
                    r.set_infra_settings(infra_settings=self.infra_settings)
                    resources_to_delete.append(r)

        # Build a list of RailwayApps to delete
        apps_to_delete: List[RailwayApp] = []
        if self.apps is not None:
            for app in self.apps:
                if app.group is None and self.name is not None:
                    app.group = self.name
                if app.should_delete(group_filter=group_filter):
                    apps_to_delete.append(app)

        # Get the list of RailwayResources from the RailwayApps
        if len(apps_to_delete) > 0:
            logger.debug(f"Found {len(apps_to_delete)} apps to delete")
            for app in apps_to_delete:
                app.set_infra_settings(infra_settings=self.infra_settings)
                app_resources = app.get_resources(
                    build_context=RailwayBuildContext(
                        api_token=self.get_api_token(),
                        workspace_id=self.get_workspace_id(),
                    )
                )
                if len(app_resources) > 0:
                    for app_resource in app_resources:
                        if isinstance(app_resource, RailwayResource) and app_resource.should_delete(
                            group_filter=group_filter, name_filter=name_filter, type_filter=type_filter
                        ):
                            resources_to_delete.append(app_resource)

        # Sort the RailwayResources in REVERSE install order for deletion
        resources_to_delete.sort(key=lambda x: RailwayResourceInstallOrder.get(x.__class__.__name__, 5000), reverse=True)

        # Deduplicate RailwayResources
        deduped_resources_to_delete: List[RailwayResource] = []
        for r in resources_to_delete:
            if r not in deduped_resources_to_delete:
                deduped_resources_to_delete.append(r)

        # Track the total number of RailwayResources to delete for validation
        num_resources_to_delete: int = len(deduped_resources_to_delete)
        num_resources_deleted: int = 0
        if num_resources_to_delete == 0:
            return 0, 0

        if dry_run:
            print_heading("--**- Railway resources to delete:")
            for resource in deduped_resources_to_delete:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            print_info(f"Total {num_resources_to_delete} resources")
            return 0, 0

        # Validate resources to be deleted
        if not auto_confirm:
            print_heading("\n--**-- Confirm resources to delete:")
            for resource in deduped_resources_to_delete:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            print_info(f"Total {num_resources_to_delete} resources")
            confirm = confirm_yes_no("\nConfirm delete")
            if not confirm:
                print_info("-*-")
                print_info("-*- Skipping delete")
                print_info("-*-")
                return 0, 0

        for resource in deduped_resources_to_delete:
            print_info(f"\n-==+==- {resource.get_resource_type()}: {resource.get_resource_name()}")
            if force is True:
                resource.force = True
            try:
                _resource_deleted = resource.delete(railway_client=self.railway_client)
                if _resource_deleted:
                    num_resources_deleted += 1
                else:
                    if self.infra_settings is not None and not self.infra_settings.continue_on_delete_failure:
                        return num_resources_deleted, num_resources_to_delete
            except Exception as e:
                logger.error(f"Failed to delete {resource.get_resource_type()}: {resource.get_resource_name()}")
                logger.error(e)
                logger.error("Please fix and try again...")

        print_heading(f"\n--**-- Resources deleted: {num_resources_deleted}/{num_resources_to_delete}")
        if num_resources_to_delete != num_resources_deleted:
            logger.error(
                f"Resources deleted: {num_resources_deleted} do not match resources required: {num_resources_to_delete}"
            )
        return num_resources_deleted, num_resources_to_delete

    def update_resources(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
        dry_run: Optional[bool] = False,
        auto_confirm: Optional[bool] = False,
        force: Optional[bool] = None,
        pull: Optional[bool] = None,
    ) -> Tuple[int, int]:
        """Update Railway resources.

        Note: For Railway, update is typically implemented as recreate.
        Railway handles many updates automatically through its API.

        Args:
            group_filter: Filter resources by group
            name_filter: Filter resources by name
            type_filter: Filter resources by type
            dry_run: If True, only print what would be updated
            auto_confirm: If True, skip confirmation prompt
            force: If True, force update
            pull: Not used for Railway

        Returns:
            Tuple of (number_updated, total_number)
        """
        from agno.cli.console import print_heading, print_info

        logger.debug("-*- Updating RailwayResources")
        print_heading("--**- Railway resource updates:")
        print_info("For Railway, updates are typically handled through redeployment.")
        print_info("Use create_resources() with force=True to recreate resources.")
        return 0, 0

    def save_resources(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> Tuple[int, int]:
        """Save Railway resources to output files.

        Args:
            group_filter: Filter resources by group
            name_filter: Filter resources by name
            type_filter: Filter resources by type

        Returns:
            Tuple of (number_saved, total_number)
        """
        logger.debug("-*- Saving RailwayResources")
        # Build a list of RailwayResources to save
        resources_to_save: List[RailwayResource] = []

        # Add resources to resources_to_save
        if self.resources is not None:
            for r in self.resources:
                r.set_infra_settings(infra_settings=self.infra_settings)
                if r.matches_filters(
                    group_filter=group_filter,
                    name_filter=name_filter,
                    type_filter=type_filter,
                ):
                    resources_to_save.append(r)

        # Get the list of RailwayResources from the RailwayApps
        if self.apps is not None:
            for app in self.apps:
                app.set_infra_settings(infra_settings=self.infra_settings)
                app_resources = app.get_resources(
                    build_context=RailwayBuildContext(
                        api_token=self.get_api_token(),
                        workspace_id=self.get_workspace_id(),
                    )
                )
                if len(app_resources) > 0:
                    for app_resource in app_resources:
                        if isinstance(app_resource, RailwayResource) and app_resource.matches_filters(
                            group_filter=group_filter, name_filter=name_filter, type_filter=type_filter
                        ):
                            resources_to_save.append(app_resource)

        # Track the total number of RailwayResources to save
        num_resources_to_save: int = len(resources_to_save)
        num_resources_saved: int = 0
        if num_resources_to_save == 0:
            return 0, 0

        for resource in resources_to_save:
            try:
                if resource.save_output_file():
                    num_resources_saved += 1
            except Exception as e:
                logger.error(f"Failed to save {resource.get_resource_type()}: {resource.get_resource_name()}")
                logger.error(e)

        logger.info(f"Resources saved: {num_resources_saved}/{num_resources_to_save}")
        return num_resources_saved, num_resources_to_save
