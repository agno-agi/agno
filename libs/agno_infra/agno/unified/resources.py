"""
Unified multi-cloud resource group for managing resources across cloud providers.

This module provides UnifiedResources class that enables CLI-based management
of multi-cloud infrastructure using unified resource interfaces.
"""

from typing import Dict, List, Optional, Tuple

from agno.base.resources import InfraResources
from agno.base.resource import InfraResource
from agno.utilities.logging import logger


class UnifiedResources(InfraResources):
    """
    Resource group for managing unified multi-cloud resources.

    This class enables CLI-based deployment and management of resources
    across multiple cloud providers (AWS, GCP, Azure, DigitalOcean, etc.)
    using a unified interface.

    Example:
        # In infra/dev.py
        from agno.unified.resources import UnifiedResources
        from agno.unified.resource.compute import UnifiedInstance

        dev_resources = UnifiedResources(
            env="dev",
            resources=[
                UnifiedInstance(
                    name="web-server",
                    provider="digitalocean",
                    size="small",
                    image="ubuntu-22.04"
                )
            ]
        )
    """

    infra: str = "unified"

    # List of unified resources to manage
    resources: Optional[List[InfraResource]] = None

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
        """
        Create unified resources across cloud providers.

        Args:
            group_filter: Filter by resource group
            name_filter: Filter by resource name
            type_filter: Filter by resource type
            dry_run: Print resources without creating them
            auto_confirm: Skip confirmation prompts
            force: Force resource creation
            pull: Pull latest images (not applicable for unified)

        Returns:
            Tuple of (successful_count, failed_count)
        """
        from agno.cli.console import confirm_yes_no, print_heading, print_info

        logger.debug("-*- Creating UnifiedResources")

        # Build list of resources to create
        resources_to_create: List[InfraResource] = []

        if self.resources is not None:
            for resource in self.resources:
                # Apply filters
                if group_filter is not None and resource.group != group_filter:
                    continue

                if name_filter is not None and resource.name != name_filter:
                    continue

                if type_filter is not None:
                    resource_type_list = resource.get_resource_type_list()
                    if type_filter.lower() not in resource_type_list:
                        continue

                resources_to_create.append(resource)

        # Return early if no resources to create
        if len(resources_to_create) == 0:
            return 0, 0

        # Print resources to create
        print_heading(f"\nResources to create ({len(resources_to_create)}):")
        for resource in resources_to_create:
            provider = getattr(resource, 'provider', 'unknown')
            print_info(f"  - {resource.get_resource_type()}: {resource.name} (provider: {provider})")

        # Confirm before creating
        if not dry_run and not auto_confirm:
            confirm = confirm_yes_no("\nConfirm resources creation?")
            if not confirm:
                print_info("Skipping resource creation")
                return 0, 0

        if dry_run:
            print_info("Dry run - skipping resource creation")
            return 0, 0

        # Group resources by provider for efficient operations
        resources_by_provider: Dict[str, List[InfraResource]] = {}
        for resource in resources_to_create:
            provider = getattr(resource, 'provider', 'unknown')
            if provider not in resources_by_provider:
                resources_by_provider[provider] = []
            resources_by_provider[provider].append(resource)

        # Create resources
        num_success = 0
        num_failed = 0

        print_info("\n")
        for provider, provider_resources in resources_by_provider.items():
            print_heading(f"Creating resources on {provider.upper()}")

            for resource in provider_resources:
                try:
                    logger.info(f"Creating {resource.get_resource_type()}: {resource.name}")

                    # Set force flag if provided
                    if force is not None:
                        resource.force = force

                    # Create the resource
                    success = resource.create()

                    if success:
                        num_success += 1
                        print_info(f"✅ Created {resource.get_resource_type()}: {resource.name}")
                    else:
                        num_failed += 1
                        print_info(f"❌ Failed to create {resource.get_resource_type()}: {resource.name}")

                except Exception as e:
                    num_failed += 1
                    logger.error(f"Error creating {resource.name}: {e}")
                    print_info(f"❌ Error creating {resource.get_resource_type()}: {resource.name} - {e}")

        print_info(f"\n✅ Successfully created {num_success} resources")
        if num_failed > 0:
            print_info(f"❌ Failed to create {num_failed} resources")

        return num_success, num_failed

    def delete_resources(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
        dry_run: Optional[bool] = False,
        auto_confirm: Optional[bool] = False,
        force: Optional[bool] = None,
    ) -> Tuple[int, int]:
        """
        Delete unified resources across cloud providers.

        Args:
            group_filter: Filter by resource group
            name_filter: Filter by resource name
            type_filter: Filter by resource type
            dry_run: Print resources without deleting them
            auto_confirm: Skip confirmation prompts
            force: Force resource deletion

        Returns:
            Tuple of (successful_count, failed_count)
        """
        from agno.cli.console import confirm_yes_no, print_heading, print_info

        logger.debug("-*- Deleting UnifiedResources")

        # Build list of resources to delete
        resources_to_delete: List[InfraResource] = []

        if self.resources is not None:
            # Delete in reverse order
            for resource in reversed(self.resources):
                # Apply filters
                if group_filter is not None and resource.group != group_filter:
                    continue

                if name_filter is not None and resource.name != name_filter:
                    continue

                if type_filter is not None:
                    resource_type_list = resource.get_resource_type_list()
                    if type_filter.lower() not in resource_type_list:
                        continue

                resources_to_delete.append(resource)

        # Return early if no resources to delete
        if len(resources_to_delete) == 0:
            print_info("No resources to delete")
            return 0, 0

        # Print resources to delete
        print_heading(f"\nResources to delete ({len(resources_to_delete)}):")
        for resource in resources_to_delete:
            provider = getattr(resource, 'provider', 'unknown')
            print_info(f"  - {resource.get_resource_type()}: {resource.name} (provider: {provider})")

        # Confirm before deleting
        if not dry_run and not auto_confirm:
            confirm = confirm_yes_no("\nConfirm resource deletion?")
            if not confirm:
                print_info("Skipping resource deletion")
                return 0, 0

        if dry_run:
            print_info("Dry run - skipping resource deletion")
            return 0, 0

        # Delete resources
        num_success = 0
        num_failed = 0

        print_info("\n")
        for resource in resources_to_delete:
            try:
                provider = getattr(resource, 'provider', 'unknown')
                logger.info(f"Deleting {resource.get_resource_type()}: {resource.name} (provider: {provider})")

                # Set force flag if provided
                if force is not None:
                    resource.force = force

                # Delete the resource
                success = resource.delete()

                if success:
                    num_success += 1
                    print_info(f"✅ Deleted {resource.get_resource_type()}: {resource.name}")
                else:
                    num_failed += 1
                    print_info(f"❌ Failed to delete {resource.get_resource_type()}: {resource.name}")

            except Exception as e:
                num_failed += 1
                logger.error(f"Error deleting {resource.name}: {e}")
                print_info(f"❌ Error deleting {resource.get_resource_type()}: {resource.name} - {e}")

        print_info(f"\n✅ Successfully deleted {num_success} resources")
        if num_failed > 0:
            print_info(f"❌ Failed to delete {num_failed} resources")

        return num_success, num_failed

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
        """
        Update unified resources across cloud providers.

        Args:
            group_filter: Filter by resource group
            name_filter: Filter by resource name
            type_filter: Filter by resource type
            dry_run: Print resources without updating them
            auto_confirm: Skip confirmation prompts
            force: Force resource update
            pull: Pull latest images (not applicable for unified)

        Returns:
            Tuple of (successful_count, failed_count)
        """
        from agno.cli.console import print_info

        logger.debug("-*- Updating UnifiedResources")
        print_info("Update operation: deleting and recreating resources")

        # For unified resources, update = delete + create
        del_success, del_failed = self.delete_resources(
            group_filter=group_filter,
            name_filter=name_filter,
            type_filter=type_filter,
            dry_run=dry_run,
            auto_confirm=auto_confirm,
            force=force,
        )

        if not dry_run:
            create_success, create_failed = self.create_resources(
                group_filter=group_filter,
                name_filter=name_filter,
                type_filter=type_filter,
                dry_run=dry_run,
                auto_confirm=True,  # Already confirmed during delete
                force=force,
                pull=pull,
            )

            return create_success, create_failed + del_failed

        return del_success, del_failed
