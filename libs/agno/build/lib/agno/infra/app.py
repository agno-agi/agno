from typing import Any, Dict, List, Optional, Union

from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from agno.infra.base import InfraBase
from agno.infra.context import ContainerContext
from agno.infra.resource import InfraResource
from agno.utils.log import logger


class InfraApp(InfraBase):
    """Base class for Infrastructure Apps."""

    # -*- App Name (required)
    name: str

    # -*- Image Configuration
    # Image can be provided as a DockerImage object
    image: Optional[Any] = None
    # OR as image_name:image_tag str
    image_str: Optional[str] = None
    # OR as image_name and image_tag
    image_name: Optional[str] = None
    image_tag: Optional[str] = None
    # Entrypoint for the container
    entrypoint: Optional[Union[str, List[str]]] = None
    # Command for the container
    command: Optional[Union[str, List[str]]] = None

    # -*- Python Configuration
    # Install python dependencies using a requirements.txt file
    install_requirements: bool = False
    # Path to the requirements.txt file relative to the workspace_root
    requirements_file: str = "requirements.txt"
    # Set the PYTHONPATH env var
    set_python_path: bool = True
    # Manually provide the PYTHONPATH.
    # If None, PYTHONPATH is set to workspace_root
    python_path: Optional[str] = None
    # Add paths to the PYTHONPATH env var
    # If python_path is provided, this value is ignored
    add_python_paths: Optional[List[str]] = None

    # -*- App Ports
    # Open a container port if open_port=True
    open_port: bool = False
    # If open_port=True, port_number is used to set the
    # container_port if container_port is None and host_port if host_port is None
    port_number: int = 80
    # Port number on the Container to open
    # Preferred over port_number if both are set
    container_port: Optional[int] = Field(None, validate_default=True)
    # Port name for the opened port
    container_port_name: str = "http"
    # Port number on the Host to map to the Container port
    # Preferred over port_number if both are set
    host_port: Optional[int] = Field(None, validate_default=True)

    # -*- Extra Resources created "before" the App resources
    resources: Optional[List[InfraResource]] = None

    #  -*- Other args
    print_env_on_load: bool = False

    # -*- App specific args. Not to be set by the user.
    # Container Environment that can be set by subclasses
    # which is used as a starting point for building the container_env
    # Any variables set in container_env will be overridden by values
    # in the env_vars dict or env_file
    container_env: Optional[Dict[str, Any]] = None
    # Variable used to cache the container context
    container_context: Optional[ContainerContext] = None

    # -*- Cached Data
    cached_resources: Optional[List[Any]] = None

    @field_validator("container_port", mode="before")
    def set_container_port(cls, v, info: ValidationInfo):
        port_number = info.data.get("port_number")
        if v is None and port_number is not None:
            v = port_number
        return v

    @field_validator("host_port", mode="before")
    def set_host_port(cls, v, info: ValidationInfo):
        port_number = info.data.get("port_number")
        if v is None and port_number is not None:
            v = port_number
        return v

    def get_app_name(self) -> str:
        return self.name

    def get_image_str(self) -> str:
        if self.image:
            return f"{self.image.name}:{self.image.tag}"
        elif self.image_str:
            return self.image_str
        elif self.image_name and self.image_tag:
            return f"{self.image_name}:{self.image_tag}"
        elif self.image_name:
            return f"{self.image_name}:latest"
        else:
            return ""

    def build_resources(self, build_context: Any) -> Optional[Any]:
        logger.debug(f"@build_resource_group not defined for {self.get_app_name()}")
        return None

    def get_dependencies(self) -> Optional[List[InfraResource]]:
        return (
            [dep for dep in self.depends_on if isinstance(dep, InfraResource)] if self.depends_on is not None else None
        )

    def add_app_properties_to_resources(self, resources: List[InfraResource]) -> List[InfraResource]:
        updated_resources = []
        app_properties = self.model_dump(exclude_defaults=True)
        app_group = self.get_group_name()
        app_output_dir = self.get_app_name()

        app_skip_create = app_properties.get("skip_create")
        app_skip_read = app_properties.get("skip_read")
        app_skip_update = app_properties.get("skip_update")
        app_skip_delete = app_properties.get("skip_delete")
        app_recreate_on_update = app_properties.get("recreate_on_update")
        app_use_cache = app_properties.get("use_cache")
        app_force = app_properties.get("force")
        app_debug_mode = app_properties.get("debug_mode")
        app_wait_for_create = app_properties.get("wait_for_create")
        app_wait_for_update = app_properties.get("wait_for_update")
        app_wait_for_delete = app_properties.get("wait_for_delete")
        app_save_output = app_properties.get("save_output")

        for resource in resources:
            resource_properties = resource.model_dump(exclude_defaults=True)
            resource_skip_create = resource_properties.get("skip_create")
            resource_skip_read = resource_properties.get("skip_read")
            resource_skip_update = resource_properties.get("skip_update")
            resource_skip_delete = resource_properties.get("skip_delete")
            resource_recreate_on_update = resource_properties.get("recreate_on_update")
            resource_use_cache = resource_properties.get("use_cache")
            resource_force = resource_properties.get("force")
            resource_debug_mode = resource_properties.get("debug_mode")
            resource_wait_for_create = resource_properties.get("wait_for_create")
            resource_wait_for_update = resource_properties.get("wait_for_update")
            resource_wait_for_delete = resource_properties.get("wait_for_delete")
            resource_save_output = resource_properties.get("save_output")

            # If skip_create on resource is not set, use app level skip_create (if set on app)
            if resource_skip_create is None and app_skip_create is not None:
                resource.skip_create = app_skip_create
            # If skip_read on resource is not set, use app level skip_read (if set on app)
            if resource_skip_read is None and app_skip_read is not None:
                resource.skip_read = app_skip_read
            # If skip_update on resource is not set, use app level skip_update (if set on app)
            if resource_skip_update is None and app_skip_update is not None:
                resource.skip_update = app_skip_update
            # If skip_delete on resource is not set, use app level skip_delete (if set on app)
            if resource_skip_delete is None and app_skip_delete is not None:
                resource.skip_delete = app_skip_delete
            # If recreate_on_update on resource is not set, use app level recreate_on_update (if set on app)
            if resource_recreate_on_update is None and app_recreate_on_update is not None:
                resource.recreate_on_update = app_recreate_on_update
            # If use_cache on resource is not set, use app level use_cache (if set on app)
            if resource_use_cache is None and app_use_cache is not None:
                resource.use_cache = app_use_cache
            # If force on resource is not set, use app level force (if set on app)
            if resource_force is None and app_force is not None:
                resource.force = app_force
            # If debug_mode on resource is not set, use app level debug_mode (if set on app)
            if resource_debug_mode is None and app_debug_mode is not None:
                resource.debug_mode = app_debug_mode
            # If wait_for_create on resource is not set, use app level wait_for_create (if set on app)
            if resource_wait_for_create is None and app_wait_for_create is not None:
                resource.wait_for_create = app_wait_for_create
            # If wait_for_update on resource is not set, use app level wait_for_update (if set on app)
            if resource_wait_for_update is None and app_wait_for_update is not None:
                resource.wait_for_update = app_wait_for_update
            # If wait_for_delete on resource is not set, use app level wait_for_delete (if set on app)
            if resource_wait_for_delete is None and app_wait_for_delete is not None:
                resource.wait_for_delete = app_wait_for_delete
            # If save_output on resource is not set, use app level save_output (if set on app)
            if resource_save_output is None and app_save_output is not None:
                resource.save_output = app_save_output
            # If workspace_settings on resource is not set, use app level workspace_settings (if set on app)
            if resource.workspace_settings is None and self.workspace_settings is not None:
                resource.set_workspace_settings(self.workspace_settings)
            # If group on resource is not set, use app level group (if set on app)
            if resource.group is None and app_group is not None:
                resource.group = app_group

            # Always set output_dir on resource to app level output_dir
            resource.output_dir = app_output_dir

            app_dependencies = self.get_dependencies()
            if app_dependencies is not None:
                if resource.depends_on is None:
                    resource.depends_on = app_dependencies
                else:
                    resource.depends_on.extend(app_dependencies)

            updated_resources.append(resource)
        return updated_resources

    def get_resources(self, build_context: Any) -> List[InfraResource]:
        if self.cached_resources is not None and len(self.cached_resources) > 0:
            return self.cached_resources

        base_resources = self.resources or []
        app_resources = self.build_resources(build_context)
        if app_resources is not None:
            base_resources.extend(app_resources)

        self.cached_resources = self.add_app_properties_to_resources(base_resources)
        # logger.debug(f"Resources: {self.cached_resources}")
        return self.cached_resources

    def matches_filters(self, group_filter: Optional[str] = None) -> bool:
        if group_filter is not None:
            group_name = self.get_group_name()
            logger.debug(f"{self.get_app_name()}: Checking {group_filter} in {group_name}")
            if group_name is None or group_filter not in group_name:
                return False
        return True

    def should_create(self, group_filter: Optional[str] = None) -> bool:
        if not self.enabled or self.skip_create:
            return False
        return self.matches_filters(group_filter)

    def should_delete(self, group_filter: Optional[str] = None) -> bool:
        if not self.enabled or self.skip_delete:
            return False
        return self.matches_filters(group_filter)

    def should_update(self, group_filter: Optional[str] = None) -> bool:
        if not self.enabled or self.skip_update:
            return False
        return self.matches_filters(group_filter)
