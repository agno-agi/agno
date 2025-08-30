from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agno.base.base import InfraBase
from agno.base.resources import InfraResources
from agno.infra.settings import InfraSettings
from agno.utilities.logging import logger

# List of directories to ignore when loading the Infra
ignored_dirs = ["ignore", "test", "tests", "config"]


class InfraConfig(BaseModel):
    """The InfraConfig holds the configuration for an Agno Infrastructure."""

    # Root directory of the infrastructure.
    infra_root_path: Path

    # Path to the "infra" directory inside the infrastructure root
    internal_infra_dir_path: Optional[Path] = None
    # InfraSettings
    internal_infra_settings: Optional[InfraSettings] = None

    def to_dict(self) -> dict:
        return {
            "infra_root_path": self.infra_root_path,
        }

    @property
    def infra_dir_path(self) -> Optional[Path]:
        if self.internal_infra_dir_path is None:
            if self.infra_root_path is not None:
                from agno.infra.helpers import get_infra_dir_path

                self.internal_infra_dir_path = get_infra_dir_path(self.infra_root_path)
        return self.internal_infra_dir_path

    def validate_infra_settings(self, obj: Any) -> bool:
        if not isinstance(obj, InfraSettings):
            raise Exception("InfraSettings must be of type InfraSettings")

        if self.infra_root_path is not None and obj.infra_root is not None:
            if obj.infra_root != self.infra_root_path:
                raise Exception(f"InfraSettings.infra_root ({obj.infra_root}) must match {self.infra_root_path}")
        return True

    @property
    def infra_settings(self) -> Optional[InfraSettings]:
        if self.internal_infra_settings is not None:
            return self.internal_infra_settings

        infra_settings_file: Optional[Path] = None
        if self.infra_dir_path is not None:
            _infra_settings_file_path = self.infra_dir_path.joinpath("settings.py")
            if _infra_settings_file_path.exists() and _infra_settings_file_path.is_file():
                infra_settings_file = _infra_settings_file_path
        if infra_settings_file is None:
            logger.debug("infra_settings file not found")
            return None

        logger.debug(f"Loading infra_settings from {infra_settings_file}")
        try:
            from agno.utilities.py_io import get_python_objects_from_module

            python_objects = get_python_objects_from_module(infra_settings_file)
            for obj_name, obj in python_objects.items():
                if isinstance(obj, InfraSettings):
                    if self.validate_infra_settings(obj):
                        self.internal_infra_settings = obj
        except Exception:
            logger.warning(f"Error in {infra_settings_file}")
            raise
        return self.internal_infra_settings

    def set_local_env(self) -> None:
        from os import environ

        from agno.constants import (
            AGNO_INFRA_DIR,
            AGNO_INFRA_NAME,
            AGNO_INFRA_ROOT,
            AWS_REGION_ENV_VAR,
        )

        if self.infra_root_path is not None:
            environ[AGNO_INFRA_ROOT] = str(self.infra_root_path)

            infra_dir_path: Optional[Path] = self.infra_dir_path
            if infra_dir_path is not None:
                environ[AGNO_INFRA_DIR] = str(infra_dir_path)

            if self.infra_settings is not None:
                environ[AGNO_INFRA_NAME] = str(self.infra_settings.infra_name)

        if (
            environ.get(AWS_REGION_ENV_VAR) is None
            and self.infra_settings is not None
            and self.infra_settings.aws_region is not None
        ):
            environ[AWS_REGION_ENV_VAR] = self.infra_settings.aws_region

    def get_resources(
        self,
        env: Optional[str] = None,
        infra: Optional[str] = None,
        order: str = "create",
    ) -> List[InfraResources]:
        if self.infra_root_path is None:
            logger.warning("InfraConfig.infra_root_path is None")
            return []

        from sys import path as sys_path

        from agno.utilities.load_env import load_env
        from agno.utilities.py_io import get_python_objects_from_module

        logger.debug("**--> Loading InfraConfig")
        logger.debug(f"Loading .env from {self.infra_root_path}")
        load_env(dotenv_dir=self.infra_root_path)

        # NOTE: When loading a Infra, relative imports or package imports do not work.
        # This is a known problem in python
        #     eg: https://stackoverflow.com/questions/6323860/sibling-package-imports/50193944#50193944
        # To make them work, we add infra_root to sys.path so is treated as a module
        logger.debug(f"Adding {self.infra_root_path} to path")
        sys_path.insert(0, str(self.infra_root_path))

        infra_dir_path: Optional[Path] = self.infra_dir_path
        if infra_dir_path is not None:
            logger.debug(f"--^^-- Loading Infra from: {infra_dir_path}")
            # Create a dict of objects in the Infra directory
            infra_objects: Dict[str, InfraResources] = {}
            resource_files = infra_dir_path.rglob("*.py")
            for resource_file in resource_files:
                if resource_file.name == "__init__.py":
                    continue

                resource_file_parts = resource_file.parts
                infra_dir_path_parts = infra_dir_path.parts
                resource_file_parts_after_ws = resource_file_parts[len(infra_dir_path_parts) :]
                # Check if file in ignored directory
                if any([ignored_dir in resource_file_parts_after_ws for ignored_dir in ignored_dirs]):
                    logger.debug(f"Skipping file in ignored directory: {resource_file}")
                    continue
                logger.debug(f"Reading file: {resource_file}")
                try:
                    python_objects = get_python_objects_from_module(resource_file)
                    # logger.debug(f"python_objects: {python_objects}")
                    for obj_name, obj in python_objects.items():
                        if isinstance(obj, InfraSettings):
                            logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                            if self.validate_infra_settings(obj):
                                self.internal_infra_settings = obj
                        elif isinstance(obj, InfraResources):
                            logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                            if not obj.enabled:
                                logger.debug(f"Skipping {obj_name}: disabled")
                                continue
                            infra_objects[obj_name] = obj
                except Exception:
                    logger.warning(f"Error in {resource_file}")
                    raise
            logger.debug(f"infra_objects: {infra_objects}")
        logger.debug("**--> InfraConfig loaded")
        logger.debug(f"Removing {self.infra_root_path} from path")
        sys_path.remove(str(self.infra_root_path))

        # Filter resources by infra
        filtered_infra_objects_by_infra_type: Dict[str, InfraResources] = {}
        logger.debug(f"Filtering resources for env: {env} | infra: {infra} | order: {order}")
        if infra is None:
            filtered_infra_objects_by_infra_type = infra_objects
        else:
            for resource_name, resource in infra_objects.items():
                if resource.infra == infra:
                    filtered_infra_objects_by_infra_type[resource_name] = resource

        # Filter resources by env
        filtered_infra_objects_by_env: Dict[str, InfraResources] = {}
        if env is None:
            filtered_infra_objects_by_env = filtered_infra_objects_by_infra_type
        else:
            for resource_name, resource in filtered_infra_objects_by_infra_type.items():
                if resource.env == env:
                    filtered_infra_objects_by_env[resource_name] = resource

        # Updated resources with the infra settings
        # Create a temporary infra settings object if it does not exist
        if self.infra_settings is None:
            self.internal_infra_settings = InfraSettings(
                infra_root=self.infra_root_path,
                infra_name=self.infra_root_path.stem,
            )
            logger.debug(f"Created InfraSettings: {self.infra_settings}")
        # Update the resources with the infra settings
        if self.infra_settings is not None:
            for resource_name, resource in filtered_infra_objects_by_env.items():
                logger.debug(f"Setting infra settings for {resource.__class__.__name__}")
                resource.set_infra_settings(self.infra_settings)

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

        from agno.utilities.load_env import load_env
        from agno.utilities.py_io import get_python_objects_from_module

        resource_file_parent_dir = resource_file.parent.resolve()
        logger.debug(f"Loading .env from {resource_file_parent_dir}")
        load_env(dotenv_dir=resource_file_parent_dir)

        temporary_infra_config = InfraConfig(infra_root_path=resource_file_parent_dir)

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
            # Filter out the objects that are subclasses of InfraSettings
            for obj_name, obj in python_objects.items():
                if isinstance(obj, InfraSettings):
                    logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                    infra_objects[obj_name] = obj  # type: ignore
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

        # Updated resources with the infra settings
        # Create a temporary infra settings object if it does not exist
        if temporary_infra_config.infra_settings is None:
            temporary_infra_config.internal_infra_settings = InfraSettings(
                infra_root=temporary_infra_config.infra_root_path,
                infra_name=temporary_infra_config.infra_root_path.stem,
            )
        # Update the resources with the infra settings
        if temporary_infra_config.infra_settings is not None:
            for resource_name, resource in filtered_infra_objects_by_env.items():
                logger.debug(f"Setting infra settings for {resource.__class__.__name__}")
                resource.set_infra_settings(temporary_infra_config.infra_settings)

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
