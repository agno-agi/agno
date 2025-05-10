from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from agno.api.schemas.user import TeamSchema
from agno.api.schemas.workspace import WorkspaceSchema
from agno.infra.base import InfraBase
from agno.infra.resources import InfraResources
from agno.utils.log import logger
from agno.workspace.settings import WorkspaceSettings

# List of directories to ignore when loading the workspace
ignored_dirs = ["ignore", "test", "tests", "config"]


class WorkspaceConfig(BaseModel):
    """The WorkspaceConfig holds the configuration for an Agno workspace."""

    # Root directory of the workspace.
    ws_root_path: Path
    # WorkspaceSchema: This field indicates that the workspace is synced with the api
    ws_schema: Optional[WorkspaceSchema] = None
    # The Team for this workspace
    ws_team: Optional[TeamSchema] = None
    # The API key for this workspace
    ws_api_key: Optional[str] = None

    # Path to the "workspace" directory inside the workspace root
    _workspace_dir_path: Optional[Path] = None
    # WorkspaceSettings
    _workspace_settings: Optional[WorkspaceSettings] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_dict(self) -> dict:
        return self.model_dump(include={"ws_root_path", "ws_schema", "ws_team", "ws_api_key"})

    @property
    def workspace_dir_path(self) -> Optional[Path]:
        if self._workspace_dir_path is None:
            if self.ws_root_path is not None:
                from agno.workspace.helpers import get_workspace_dir_path

                self._workspace_dir_path = get_workspace_dir_path(self.ws_root_path)
        return self._workspace_dir_path

    def validate_workspace_settings(self, obj: Any) -> bool:
        if not isinstance(obj, WorkspaceSettings):
            raise Exception("WorkspaceSettings must be of type WorkspaceSettings")

        if self.ws_root_path is not None and obj.ws_root is not None:
            if obj.ws_root != self.ws_root_path:
                raise Exception(f"WorkspaceSettings.ws_root ({obj.ws_root}) must match {self.ws_root_path}")
        return True

    @property
    def workspace_settings(self) -> Optional[WorkspaceSettings]:
        if self._workspace_settings is not None:
            return self._workspace_settings

        ws_settings_file: Optional[Path] = None
        if self.workspace_dir_path is not None:
            _ws_settings_file = self.workspace_dir_path.joinpath("settings.py")
            if _ws_settings_file.exists() and _ws_settings_file.is_file():
                ws_settings_file = _ws_settings_file
        if ws_settings_file is None:
            logger.debug("workspace_settings file not found")
            return None

        logger.debug(f"Loading workspace_settings from {ws_settings_file}")
        try:
            from agno.utils.py_io import get_python_objects_from_module

            python_objects = get_python_objects_from_module(ws_settings_file)
            for obj_name, obj in python_objects.items():
                if isinstance(obj, WorkspaceSettings):
                    if self.validate_workspace_settings(obj):
                        self._workspace_settings = obj
                        if self.ws_schema is not None and self._workspace_settings is not None:
                            self._workspace_settings.ws_schema = self.ws_schema
                            logger.debug("Added WorkspaceSchema to WorkspaceSettings")
        except Exception:
            logger.warning(f"Error in {ws_settings_file}")
            raise
        return self._workspace_settings

    def set_local_env(self) -> None:
        from os import environ

        from agno.constants import (
            AWS_REGION_ENV_VAR,
            WORKSPACE_DIR_ENV_VAR,
            WORKSPACE_ID_ENV_VAR,
            WORKSPACE_NAME_ENV_VAR,
            WORKSPACE_ROOT_ENV_VAR,
        )

        if self.ws_root_path is not None:
            environ[WORKSPACE_ROOT_ENV_VAR] = str(self.ws_root_path)

            workspace_dir_path: Optional[Path] = self.workspace_dir_path
            if workspace_dir_path is not None:
                environ[WORKSPACE_DIR_ENV_VAR] = str(workspace_dir_path)

            if self.workspace_settings is not None:
                environ[WORKSPACE_NAME_ENV_VAR] = str(self.workspace_settings.ws_name)

        if self.ws_schema is not None and self.ws_schema.id_workspace is not None:
            environ[WORKSPACE_ID_ENV_VAR] = str(self.ws_schema.id_workspace)

        if (
            environ.get(AWS_REGION_ENV_VAR) is None
            and self.workspace_settings is not None
            and self.workspace_settings.aws_region is not None
        ):
            environ[AWS_REGION_ENV_VAR] = self.workspace_settings.aws_region

    def get_resources(
        self,
        env: Optional[str] = None,
        infra: Optional[str] = None,
        order: str = "create",
    ) -> List[InfraResources]:
        if self.ws_root_path is None:
            logger.warning("WorkspaceConfig.ws_root_path is None")
            return []

        from sys import path as sys_path

        from agno.utils.load_env import load_env
        from agno.utils.py_io import get_python_objects_from_module

        logger.debug("**--> Loading WorkspaceConfig")
        logger.debug(f"Loading .env from {self.ws_root_path}")
        load_env(dotenv_dir=self.ws_root_path)

        # NOTE: When loading a workspace, relative imports or package imports do not work.
        # This is a known problem in python
        #     eg: https://stackoverflow.com/questions/6323860/sibling-package-imports/50193944#50193944
        # To make them work, we add workspace_root to sys.path so is treated as a module
        logger.debug(f"Adding {self.ws_root_path} to path")
        sys_path.insert(0, str(self.ws_root_path))

        workspace_dir_path: Optional[Path] = self.workspace_dir_path
        if workspace_dir_path is not None:
            logger.debug(f"--^^-- Loading workspace from: {workspace_dir_path}")
            # Create a dict of objects in the workspace directory
            workspace_objects: Dict[str, InfraResources] = {}
            resource_files = workspace_dir_path.rglob("*.py")
            for resource_file in resource_files:
                if resource_file.name == "__init__.py":
                    continue

                resource_file_parts = resource_file.parts
                workspace_dir_path_parts = workspace_dir_path.parts
                resource_file_parts_after_ws = resource_file_parts[len(workspace_dir_path_parts) :]
                # Check if file in ignored directory
                if any([ignored_dir in resource_file_parts_after_ws for ignored_dir in ignored_dirs]):
                    logger.debug(f"Skipping file in ignored directory: {resource_file}")
                    continue
                logger.debug(f"Reading file: {resource_file}")
                try:
                    python_objects = get_python_objects_from_module(resource_file)
                    # logger.debug(f"python_objects: {python_objects}")
                    for obj_name, obj in python_objects.items():
                        if isinstance(obj, WorkspaceSettings):
                            logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                            if self.validate_workspace_settings(obj):
                                self._workspace_settings = obj
                                if self.ws_schema is not None and self._workspace_settings is not None:
                                    self._workspace_settings.ws_schema = self.ws_schema
                                    logger.debug("Added WorkspaceSchema to WorkspaceSettings")
                        elif isinstance(obj, InfraResources):
                            logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                            if not obj.enabled:
                                logger.debug(f"Skipping {obj_name}: disabled")
                                continue
                            workspace_objects[obj_name] = obj
                except Exception:
                    logger.warning(f"Error in {resource_file}")
                    raise
            logger.debug(f"workspace_objects: {workspace_objects}")
        logger.debug("**--> WorkspaceConfig loaded")
        logger.debug(f"Removing {self.ws_root_path} from path")
        sys_path.remove(str(self.ws_root_path))

        # Filter resources by infra
        filtered_ws_objects_by_infra_type: Dict[str, InfraResources] = {}
        logger.debug(f"Filtering resources for env: {env} | infra: {infra} | order: {order}")
        if infra is None:
            filtered_ws_objects_by_infra_type = workspace_objects
        else:
            for resource_name, resource in workspace_objects.items():
                if resource.infra == infra:
                    filtered_ws_objects_by_infra_type[resource_name] = resource

        # Filter resources by env
        filtered_infra_objects_by_env: Dict[str, InfraResources] = {}
        if env is None:
            filtered_infra_objects_by_env = filtered_ws_objects_by_infra_type
        else:
            for resource_name, resource in filtered_ws_objects_by_infra_type.items():
                if resource.env == env:
                    filtered_infra_objects_by_env[resource_name] = resource

        # Updated resources with the workspace settings
        # Create a temporary workspace settings object if it does not exist
        if self._workspace_settings is None:
            self._workspace_settings = WorkspaceSettings(
                ws_root=self.ws_root_path,
                ws_name=self.ws_root_path.stem,
            )
            logger.debug(f"Created WorkspaceSettings: {self._workspace_settings}")
        # Update the resources with the workspace settings
        if self._workspace_settings is not None:
            for resource_name, resource in filtered_infra_objects_by_env.items():
                logger.debug(f"Setting workspace settings for {resource.__class__.__name__}")
                resource.set_workspace_settings(self._workspace_settings)

        # Create a list of InfraResources from the filtered resources
        infra_resources_list: List[InfraResources] = []
        for resource_name, resource in filtered_infra_objects_by_env.items():
            # If the resource is an InfraResources object, add it to the list
            if isinstance(resource, InfraResources):
                infra_resources_list.append(resource)

        return infra_resources_list

    @staticmethod
    def get_resources_from_file(
        resource_file: Path,
        env: Optional[str] = None,
        infra: Optional[str] = None,
        order: str = "create",
    ) -> List[InfraResources]:
        if not resource_file.exists():
            raise FileNotFoundError(f"File {resource_file} does not exist")
        if not resource_file.is_file():
            raise ValueError(f"Path {resource_file} is not a file")
        if not resource_file.suffix == ".py":
            raise ValueError(f"File {resource_file} is not a python file")

        from sys import path as sys_path

        from agno.utils.load_env import load_env
        from agno.utils.py_io import get_python_objects_from_module

        resource_file_parent_dir = resource_file.parent.resolve()
        logger.debug(f"Loading .env from {resource_file_parent_dir}")
        load_env(dotenv_dir=resource_file_parent_dir)

        temporary_ws_config = WorkspaceConfig(ws_root_path=resource_file_parent_dir)

        # NOTE: When loading a directory, relative imports or package imports do not work.
        # This is a known problem in python
        #     eg: https://stackoverflow.com/questions/6323860/sibling-package-imports/50193944#50193944
        # To make them work, we add the resource_file_parent_dir to sys.path so it can be treated as a module
        logger.debug(f"Adding {resource_file_parent_dir} to path")
        sys_path.insert(0, str(resource_file_parent_dir))

        logger.debug(f"**--> Reading Infra resources from {resource_file}")

        # Get all infra resources from the file
        infra_objects: Dict[str, InfraBase] = {}
        try:
            # Get all python objects from the file
            python_objects = get_python_objects_from_module(resource_file)
            # Filter out the objects that are subclasses of InfraBase
            for obj_name, obj in python_objects.items():
                if isinstance(obj, InfraBase):
                    logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                    if not obj.enabled:
                        logger.debug(f"Skipping {obj_name}: disabled")
                        continue
                    infra_objects[obj_name] = obj
        except Exception:
            logger.error(f"Error reading: {resource_file}")
            raise

        # Filter resources by infra
        filtered_infra_objects_by_infra_type: Dict[str, InfraBase] = {}
        logger.debug(f"Filtering resources for env: {env} | infra: {infra} | order: {order}")
        if infra is None:
            filtered_infra_objects_by_infra_type = infra_objects
        else:
            for resource_name, resource in infra_objects.items():
                if resource.infra == infra:
                    filtered_infra_objects_by_infra_type[resource_name] = resource

        # Filter resources by env
        filtered_infra_objects_by_env: Dict[str, InfraBase] = {}
        if env is None:
            filtered_infra_objects_by_env = filtered_infra_objects_by_infra_type
        else:
            for resource_name, resource in filtered_infra_objects_by_infra_type.items():
                if resource.env == env:
                    filtered_infra_objects_by_env[resource_name] = resource

        # Updated resources with the workspace settings
        # Create a temporary workspace settings object if it does not exist
        if temporary_ws_config._workspace_settings is None:
            temporary_ws_config._workspace_settings = WorkspaceSettings(
                ws_root=temporary_ws_config.ws_root_path,
                ws_name=temporary_ws_config.ws_root_path.stem,
            )
        # Update the resources with the workspace settings
        if temporary_ws_config._workspace_settings is not None:
            for resource_name, resource in filtered_infra_objects_by_env.items():
                logger.debug(f"Setting workspace settings for {resource.__class__.__name__}")
                resource.set_workspace_settings(temporary_ws_config._workspace_settings)

        # Create a list of InfraResources from the filtered resources
        infra_resources_list: List[InfraResources] = []
        for resource_name, resource in filtered_infra_objects_by_env.items():
            # If the resource is an InfraResources object, add it to the list
            if isinstance(resource, InfraResources):
                infra_resources_list.append(resource)
            # Otherwise, get the InfraResources object from the resource
            else:
                _infra_resources = resource.get_infra_resources()
                if _infra_resources is not None and isinstance(_infra_resources, InfraResources):
                    infra_resources_list.append(_infra_resources)

        return infra_resources_list
