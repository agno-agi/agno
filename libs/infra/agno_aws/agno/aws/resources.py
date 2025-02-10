from typing import List, Optional, Tuple

from agno.aws.api_client import AwsApiClient
from agno.aws.app.base import AwsApp
from agno.aws.context import AwsBuildContext
from agno.aws.resource.base import AwsResource
from agno.infra.resources import InfraResources
from agno.utils.log import logger


class AwsResources(InfraResources):
    infra: str = "aws"

    apps: Optional[List[AwsApp]] = None
    resources: Optional[List[AwsResource]] = None

    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None

    # -*- Cached Data
    _api_client: Optional[AwsApiClient] = None

    def get_aws_region(self) -> Optional[str]:
        # Priority 1: Use aws_region from ResourceGroup (or cached value)
        if self.aws_region:
            return self.aws_region

        # Priority 2: Get aws_region from workspace settings
        if self.workspace_settings is not None and self.workspace_settings.aws_region is not None:
            self.aws_region = self.workspace_settings.aws_region
            return self.aws_region

        # Priority 3: Get aws_region from env
        from os import getenv

        from agno.constants import AWS_REGION_ENV_VAR

        aws_region_env = getenv(AWS_REGION_ENV_VAR)
        if aws_region_env is not None:
            logger.debug(f"{AWS_REGION_ENV_VAR}: {aws_region_env}")
            self.aws_region = aws_region_env
        return self.aws_region

    def get_aws_profile(self) -> Optional[str]:
        # Priority 1: Use aws_region from ResourceGroup (or cached value)
        if self.aws_profile:
            return self.aws_profile

        # Priority 2: Get aws_profile from workspace settings
        if self.workspace_settings is not None and self.workspace_settings.aws_profile is not None:
            self.aws_profile = self.workspace_settings.aws_profile
            return self.aws_profile

        # Priority 3: Get aws_profile from env
        from os import getenv

        from agno.constants import AWS_PROFILE_ENV_VAR

        aws_profile_env = getenv(AWS_PROFILE_ENV_VAR)
        if aws_profile_env is not None:
            logger.debug(f"{AWS_PROFILE_ENV_VAR}: {aws_profile_env}")
            self.aws_profile = aws_profile_env
        return self.aws_profile

    @property
    def aws_client(self) -> AwsApiClient:
        if self._api_client is None:
            self._api_client = AwsApiClient(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
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
        from agno.aws.resource.types import AwsResourceInstallOrder
        from agno.cli.console import confirm_yes_no, print_heading, print_info

        logger.debug("-*- Creating AwsResources")
        # Build a list of AwsResources to create
        resources_to_create: List[AwsResource] = []

        # Add resources to resources_to_create
        if self.resources is not None:
            for r in self.resources:
                r.set_workspace_settings(workspace_settings=self.workspace_settings)
                if r.group is None and self.name is not None:
                    r.group = self.name
                if r.should_create(
                    group_filter=group_filter,
                    name_filter=name_filter,
                    type_filter=type_filter,
                ):
                    r.set_workspace_settings(workspace_settings=self.workspace_settings)
                    resources_to_create.append(r)

        # Build a list of AwsApps to create
        apps_to_create: List[AwsApp] = []
        if self.apps is not None:
            for app in self.apps:
                if app.group is None and self.name is not None:
                    app.group = self.name
                if app.should_create(group_filter=group_filter):
                    apps_to_create.append(app)

        # Get the list of AwsResources from the AwsApps
        if len(apps_to_create) > 0:
            logger.debug(f"Found {len(apps_to_create)} apps to create")
            for app in apps_to_create:
                app.set_workspace_settings(workspace_settings=self.workspace_settings)
                app_resources = app.get_resources(
                    build_context=AwsBuildContext(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
                )
                if len(app_resources) > 0:
                    # If the app has dependencies, add the resources from the
                    # dependencies first to the list of resources to create
                    if app.depends_on is not None:
                        for dep in app.depends_on:
                            if isinstance(dep, AwsApp):
                                dep.set_workspace_settings(workspace_settings=self.workspace_settings)
                                dep_resources = dep.get_resources(
                                    build_context=AwsBuildContext(
                                        aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile()
                                    )
                                )
                                if len(dep_resources) > 0:
                                    for dep_resource in dep_resources:
                                        if isinstance(dep_resource, AwsResource):
                                            resources_to_create.append(dep_resource)
                    # Add the resources from the app to the list of resources to create
                    for app_resource in app_resources:
                        if isinstance(app_resource, AwsResource) and app_resource.should_create(
                            group_filter=group_filter, name_filter=name_filter, type_filter=type_filter
                        ):
                            resources_to_create.append(app_resource)

        # Sort the AwsResources in install order
        resources_to_create.sort(key=lambda x: AwsResourceInstallOrder.get(x.__class__.__name__, 5000))

        # Deduplicate AwsResources
        deduped_resources_to_create: List[AwsResource] = []
        for r in resources_to_create:
            if r not in deduped_resources_to_create:
                deduped_resources_to_create.append(r)

        # Implement dependency sorting
        final_aws_resources: List[AwsResource] = []
        logger.debug("-*- Building AwsResources dependency graph")
        for aws_resource in deduped_resources_to_create:
            # Logic to follow if resource has dependencies
            if aws_resource.depends_on is not None and len(aws_resource.depends_on) > 0:
                # Add the dependencies before the resource itself
                for dep in aws_resource.depends_on:
                    if isinstance(dep, AwsResource):
                        if dep not in final_aws_resources:
                            logger.debug(f"-*- Adding {dep.name}, dependency of {aws_resource.name}")
                            final_aws_resources.append(dep)

                # Add the resource to be created after its dependencies
                if aws_resource not in final_aws_resources:
                    logger.debug(f"-*- Adding {aws_resource.name}")
                    final_aws_resources.append(aws_resource)
            else:
                # Add the resource to be created if it has no dependencies
                if aws_resource not in final_aws_resources:
                    logger.debug(f"-*- Adding {aws_resource.name}")
                    final_aws_resources.append(aws_resource)

        # Track the total number of AwsResources to create for validation
        num_resources_to_create: int = len(final_aws_resources)
        num_resources_created: int = 0
        if num_resources_to_create == 0:
            return 0, 0

        if dry_run:
            print_heading("--**- AWS resources to create:")
            for resource in final_aws_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            if self.get_aws_region():
                print_info(f"Region: {self.get_aws_region()}")
            if self.get_aws_profile():
                print_info(f"Profile: {self.get_aws_profile()}")
            print_info(f"Total {num_resources_to_create} resources")
            return 0, 0

        # Validate resources to be created
        if not auto_confirm:
            print_heading("\n--**-- Confirm resources to create:")
            for resource in final_aws_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            if self.get_aws_region():
                print_info(f"Region: {self.get_aws_region()}")
            if self.get_aws_profile():
                print_info(f"Profile: {self.get_aws_profile()}")
            print_info(f"Total {num_resources_to_create} resources")
            confirm = confirm_yes_no("\nConfirm deploy")
            if not confirm:
                print_info("-*-")
                print_info("-*- Skipping create")
                print_info("-*-")
                return 0, 0

        for resource in final_aws_resources:
            print_info(f"\n-==+==- {resource.get_resource_type()}: {resource.get_resource_name()}")
            if force is True:
                resource.force = True
            # logger.debug(resource)
            try:
                _resource_created = resource.create(aws_client=self.aws_client)
                if _resource_created:
                    num_resources_created += 1
                else:
                    if self.workspace_settings is not None and not self.workspace_settings.continue_on_create_failure:
                        return num_resources_created, num_resources_to_create
            except Exception as e:
                logger.error(f"Failed to create {resource.get_resource_type()}: {resource.get_resource_name()}")
                logger.error(e)
                logger.error("Please fix and try again...")

        print_heading(f"\n--**-- Resources created: {num_resources_created}/{num_resources_to_create}")
        if num_resources_to_create != num_resources_created:
            logger.error(
                f"Resources created: {num_resources_created} do not match resources required: {num_resources_to_create}"
            )  # noqa: E501
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
        from agno.aws.resource.types import AwsResourceInstallOrder
        from agno.cli.console import confirm_yes_no, print_heading, print_info

        logger.debug("-*- Deleting AwsResources")
        # Build a list of AwsResources to delete
        resources_to_delete: List[AwsResource] = []

        # Add resources to resources_to_delete
        if self.resources is not None:
            for r in self.resources:
                r.set_workspace_settings(workspace_settings=self.workspace_settings)
                if r.group is None and self.name is not None:
                    r.group = self.name
                if r.should_delete(
                    group_filter=group_filter,
                    name_filter=name_filter,
                    type_filter=type_filter,
                ):
                    r.set_workspace_settings(workspace_settings=self.workspace_settings)
                    resources_to_delete.append(r)

        # Build a list of AwsApps to delete
        apps_to_delete: List[AwsApp] = []
        if self.apps is not None:
            for app in self.apps:
                if app.group is None and self.name is not None:
                    app.group = self.name
                if app.should_delete(group_filter=group_filter):
                    apps_to_delete.append(app)

        # Get the list of AwsResources from the AwsApps
        if len(apps_to_delete) > 0:
            logger.debug(f"Found {len(apps_to_delete)} apps to delete")
            for app in apps_to_delete:
                app.set_workspace_settings(workspace_settings=self.workspace_settings)
                app_resources = app.get_resources(
                    build_context=AwsBuildContext(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
                )
                if len(app_resources) > 0:
                    for app_resource in app_resources:
                        if isinstance(app_resource, AwsResource) and app_resource.should_delete(
                            group_filter=group_filter, name_filter=name_filter, type_filter=type_filter
                        ):
                            resources_to_delete.append(app_resource)

        # Sort the AwsResources in install order
        resources_to_delete.sort(key=lambda x: AwsResourceInstallOrder.get(x.__class__.__name__, 5000), reverse=True)

        # Deduplicate AwsResources
        deduped_resources_to_delete: List[AwsResource] = []
        for r in resources_to_delete:
            if r not in deduped_resources_to_delete:
                deduped_resources_to_delete.append(r)

        # Implement dependency sorting
        final_aws_resources: List[AwsResource] = []
        logger.debug("-*- Building AwsResources dependency graph")
        for aws_resource in deduped_resources_to_delete:
            # Logic to follow if resource has dependencies
            if aws_resource.depends_on is not None and len(aws_resource.depends_on) > 0:
                # 1. Reverse the order of dependencies
                aws_resource.depends_on.reverse()

                # 2. Remove the dependencies if they are already added to the final_aws_resources
                for dep in aws_resource.depends_on:
                    if dep in final_aws_resources:
                        logger.debug(f"-*- Removing {dep.name}, dependency of {aws_resource.name}")
                        final_aws_resources.remove(dep)

                # 3. Add the resource to be deleted before its dependencies
                if aws_resource not in final_aws_resources:
                    logger.debug(f"-*- Adding {aws_resource.name}")
                    final_aws_resources.append(aws_resource)

                # 4. Add the dependencies back in reverse order
                for dep in aws_resource.depends_on:
                    if isinstance(dep, AwsResource):
                        if dep not in final_aws_resources:
                            logger.debug(f"-*- Adding {dep.name}, dependency of {aws_resource.name}")
                            final_aws_resources.append(dep)
            else:
                # Add the resource to be deleted if it has no dependencies
                if aws_resource not in final_aws_resources:
                    logger.debug(f"-*- Adding {aws_resource.name}")
                    final_aws_resources.append(aws_resource)

        # Track the total number of AwsResources to delete for validation
        num_resources_to_delete: int = len(final_aws_resources)
        num_resources_deleted: int = 0
        if num_resources_to_delete == 0:
            return 0, 0

        if dry_run:
            print_heading("--**- AWS resources to delete:")
            for resource in final_aws_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            if self.get_aws_region():
                print_info(f"Region: {self.get_aws_region()}")
            if self.get_aws_profile():
                print_info(f"Profile: {self.get_aws_profile()}")
            print_info(f"Total {num_resources_to_delete} resources")
            return 0, 0

        # Validate resources to be deleted
        if not auto_confirm:
            print_heading("\n--**-- Confirm resources to delete:")
            for resource in final_aws_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            if self.get_aws_region():
                print_info(f"Region: {self.get_aws_region()}")
            if self.get_aws_profile():
                print_info(f"Profile: {self.get_aws_profile()}")
            print_info(f"Total {num_resources_to_delete} resources")
            confirm = confirm_yes_no("\nConfirm delete")
            if not confirm:
                print_info("-*-")
                print_info("-*- Skipping delete")
                print_info("-*-")
                return 0, 0

        for resource in final_aws_resources:
            print_info(f"\n-==+==- {resource.get_resource_type()}: {resource.get_resource_name()}")
            if force is True:
                resource.force = True
            # logger.debug(resource)
            try:
                _resource_deleted = resource.delete(aws_client=self.aws_client)
                if _resource_deleted:
                    num_resources_deleted += 1
                else:
                    if self.workspace_settings is not None and not self.workspace_settings.continue_on_delete_failure:
                        return num_resources_deleted, num_resources_to_delete
            except Exception as e:
                logger.error(f"Failed to delete {resource.get_resource_type()}: {resource.get_resource_name()}")
                logger.error(e)
                logger.error("Please fix and try again...")

        print_heading(f"\n--**-- Resources deleted: {num_resources_deleted}/{num_resources_to_delete}")
        if num_resources_to_delete != num_resources_deleted:
            logger.error(
                f"Resources deleted: {num_resources_deleted} do not match resources required: {num_resources_to_delete}"
            )  # noqa: E501
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
        from agno.aws.resource.types import AwsResourceInstallOrder
        from agno.cli.console import confirm_yes_no, print_heading, print_info

        logger.debug("-*- Updating AwsResources")

        # Build a list of AwsResources to update
        resources_to_update: List[AwsResource] = []

        # Add resources to resources_to_update
        if self.resources is not None:
            for r in self.resources:
                r.set_workspace_settings(workspace_settings=self.workspace_settings)
                if r.group is None and self.name is not None:
                    r.group = self.name
                if r.should_update(
                    group_filter=group_filter,
                    name_filter=name_filter,
                    type_filter=type_filter,
                ):
                    r.set_workspace_settings(workspace_settings=self.workspace_settings)
                    resources_to_update.append(r)

        # Build a list of AwsApps to update
        apps_to_update: List[AwsApp] = []
        if self.apps is not None:
            for app in self.apps:
                if app.group is None and self.name is not None:
                    app.group = self.name
                if app.should_update(group_filter=group_filter):
                    apps_to_update.append(app)

        # Get the list of AwsResources from the AwsApps
        if len(apps_to_update) > 0:
            logger.debug(f"Found {len(apps_to_update)} apps to update")
            for app in apps_to_update:
                app.set_workspace_settings(workspace_settings=self.workspace_settings)
                app_resources = app.get_resources(
                    build_context=AwsBuildContext(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
                )
                if len(app_resources) > 0:
                    for app_resource in app_resources:
                        if isinstance(app_resource, AwsResource) and app_resource.should_update(
                            group_filter=group_filter, name_filter=name_filter, type_filter=type_filter
                        ):
                            resources_to_update.append(app_resource)

        # Sort the AwsResources in install order
        resources_to_update.sort(key=lambda x: AwsResourceInstallOrder.get(x.__class__.__name__, 5000))

        # Deduplicate AwsResources
        deduped_resources_to_update: List[AwsResource] = []
        for r in resources_to_update:
            if r not in deduped_resources_to_update:
                deduped_resources_to_update.append(r)

        # Implement dependency sorting
        final_aws_resources: List[AwsResource] = []
        logger.debug("-*- Building AwsResources dependency graph")
        for aws_resource in deduped_resources_to_update:
            # Logic to follow if resource has dependencies
            if aws_resource.depends_on is not None and len(aws_resource.depends_on) > 0:
                # Add the dependencies before the resource itself
                for dep in aws_resource.depends_on:
                    if isinstance(dep, AwsResource):
                        if dep not in final_aws_resources:
                            logger.debug(f"-*- Adding {dep.name}, dependency of {aws_resource.name}")
                            final_aws_resources.append(dep)

                # Add the resource to be created after its dependencies
                if aws_resource not in final_aws_resources:
                    logger.debug(f"-*- Adding {aws_resource.name}")
                    final_aws_resources.append(aws_resource)
            else:
                # Add the resource to be created if it has no dependencies
                if aws_resource not in final_aws_resources:
                    logger.debug(f"-*- Adding {aws_resource.name}")
                    final_aws_resources.append(aws_resource)

        # Track the total number of AwsResources to update for validation
        num_resources_to_update: int = len(final_aws_resources)
        num_resources_updated: int = 0
        if num_resources_to_update == 0:
            return 0, 0

        if dry_run:
            print_heading("--**- AWS resources to update:")
            for resource in final_aws_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            if self.get_aws_region():
                print_info(f"Region: {self.get_aws_region()}")
            if self.get_aws_profile():
                print_info(f"Profile: {self.get_aws_profile()}")
            print_info(f"Total {num_resources_to_update} resources")
            return 0, 0

        # Validate resources to be updated
        if not auto_confirm:
            print_heading("\n--**-- Confirm resources to update:")
            for resource in final_aws_resources:
                print_info(f"  -+-> {resource.get_resource_type()}: {resource.get_resource_name()}")
            print_info("")
            if self.get_aws_region():
                print_info(f"Region: {self.get_aws_region()}")
            if self.get_aws_profile():
                print_info(f"Profile: {self.get_aws_profile()}")
            print_info(f"Total {num_resources_to_update} resources")
            confirm = confirm_yes_no("\nConfirm patch")
            if not confirm:
                print_info("-*-")
                print_info("-*- Skipping patch")
                print_info("-*-")
                return 0, 0

        for resource in final_aws_resources:
            print_info(f"\n-==+==- {resource.get_resource_type()}: {resource.get_resource_name()}")
            if force is True:
                resource.force = True
            # logger.debug(resource)
            try:
                _resource_updated = resource.update(aws_client=self.aws_client)
                if _resource_updated:
                    num_resources_updated += 1
                else:
                    if self.workspace_settings is not None and not self.workspace_settings.continue_on_patch_failure:
                        return num_resources_updated, num_resources_to_update
            except Exception as e:
                logger.error(f"Failed to update {resource.get_resource_type()}: {resource.get_resource_name()}")
                logger.error(e)
                logger.error("Please fix and try again...")

        print_heading(f"\n--**-- Resources updated: {num_resources_updated}/{num_resources_to_update}")
        if num_resources_to_update != num_resources_updated:
            logger.error(
                f"Resources updated: {num_resources_updated} do not match resources required: {num_resources_to_update}"
            )  # noqa: E501
        return num_resources_updated, num_resources_to_update

    def save_resources(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> Tuple[int, int]:
        raise NotImplementedError
