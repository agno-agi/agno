from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.infra.base import InfraBase
from agno.infra.resources import InfraResources
from agno.os.settings import OSSettings
from agno.utils.logging import logger

# List of directories to ignore when loading the OS
ignored_dirs = ["ignore", "test", "tests", "config"]


@dataclass
class OSConfig:
    """The OSConfig holds the configuration for an Agno OS."""

    # Root directory of the OS.
    os_root_path: Path

    # Path to the "infra" directory inside the OS root
    _os_infra_dir_path: Optional[Path] = field(default=None, init=False)
    # OSSettings
    _os_settings: Optional[OSSettings] = field(default=None, init=False)

    def to_dict(self) -> dict:
        return {
            "os_root_path": self.os_root_path,
        }

    @property
    def os_infra_dir_path(self) -> Optional[Path]:
        if self._os_infra_dir_path is None:
            if self.os_root_path is not None:
                from agno.os.helpers import get_os_infra_dir_path

                self._os_infra_dir_path = get_os_infra_dir_path(self.os_root_path)
        return self._os_infra_dir_path

    def validate_os_settings(self, obj: Any) -> bool:
        if not isinstance(obj, OSSettings):
            raise Exception("OSSettings must be of type OSSettings")

        if self.os_root_path is not None and obj.os_root is not None:
            if obj.os_root != self.os_root_path:
                raise Exception(f"OSSettings.os_root ({obj.os_root}) must match {self.os_root_path}")
        return True

    @property
    def os_settings(self) -> Optional[OSSettings]:
        if self._os_settings is not None:
            return self._os_settings

        os_settings_file: Optional[Path] = None
        if self.os_infra_dir_path is not None:
            _os_settings_file = self.os_infra_dir_path.joinpath("settings.py")
            if _os_settings_file.exists() and _os_settings_file.is_file():
                os_settings_file = _os_settings_file
        if os_settings_file is None:
            logger.debug("os_settings file not found")
            return None

        logger.debug(f"Loading os_settings from {os_settings_file}")
        try:
            from agno.utils.py_io import get_python_objects_from_module

            python_objects = get_python_objects_from_module(os_settings_file)
            for obj_name, obj in python_objects.items():
                if isinstance(obj, OSSettings):
                    if self.validate_os_settings(obj):
                        self._os_settings = obj
        except Exception:
            logger.warning(f"Error in {os_settings_file}")
            raise
        return self._os_settings

    def set_local_env(self) -> None:
        from os import environ

        from agno.constants import (
            AGNO_OS_INFRA_DIR,
            AGNO_OS_NAME,
            AGNO_OS_ROOT,
            AWS_REGION_ENV_VAR,
        )

        if self.os_root_path is not None:
            environ[AGNO_OS_ROOT] = str(self.os_root_path)

            os_infra_dir_path: Optional[Path] = self.os_infra_dir_path
            if os_infra_dir_path is not None:
                environ[AGNO_OS_INFRA_DIR] = str(os_infra_dir_path)

            if self.os_settings is not None:
                environ[AGNO_OS_NAME] = str(self.os_settings.os_name)

        if (
            environ.get(AWS_REGION_ENV_VAR) is None
            and self.os_settings is not None
            and self.os_settings.aws_region is not None
        ):
            environ[AWS_REGION_ENV_VAR] = self.os_settings.aws_region

    def get_resources(
        self,
        env: Optional[str] = None,
        infra: Optional[str] = None,
        order: str = "create",
    ) -> List[InfraResources]:
        if self.os_root_path is None:
            logger.warning("OSConfig.os_root_path is None")
            return []

        from sys import path as sys_path

        from agno.utils.load_env import load_env
        from agno.utils.py_io import get_python_objects_from_module

        logger.debug("**--> Loading OSConfig")
        logger.debug(f"Loading .env from {self.os_root_path}")
        load_env(dotenv_dir=self.os_root_path)

        # NOTE: When loading a OS, relative imports or package imports do not work.
        # This is a known problem in python
        #     eg: https://stackoverflow.com/questions/6323860/sibling-package-imports/50193944#50193944
        # To make them work, we add os_root to sys.path so is treated as a module
        logger.debug(f"Adding {self.os_root_path} to path")
        sys_path.insert(0, str(self.os_root_path))

        os_infra_dir_path: Optional[Path] = self.os_infra_dir_path
        if os_infra_dir_path is not None:
            logger.debug(f"--^^-- Loading OS from: {os_infra_dir_path}")
            # Create a dict of objects in the OS directory
            os_objects: Dict[str, InfraResources] = {}
            resource_files = os_infra_dir_path.rglob("*.py")
            for resource_file in resource_files:
                if resource_file.name == "__init__.py":
                    continue

                resource_file_parts = resource_file.parts
                os_infra_dir_path_parts = os_infra_dir_path.parts
                resource_file_parts_after_ws = resource_file_parts[len(os_infra_dir_path_parts) :]
                # Check if file in ignored directory
                if any([ignored_dir in resource_file_parts_after_ws for ignored_dir in ignored_dirs]):
                    logger.debug(f"Skipping file in ignored directory: {resource_file}")
                    continue
                logger.debug(f"Reading file: {resource_file}")
                try:
                    python_objects = get_python_objects_from_module(resource_file)
                    # logger.debug(f"python_objects: {python_objects}")
                    for obj_name, obj in python_objects.items():
                        if isinstance(obj, OSSettings):
                            logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                            if self.validate_os_settings(obj):
                                self._os_settings = obj
                        elif isinstance(obj, InfraResources):
                            logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                            if not obj.enabled:
                                logger.debug(f"Skipping {obj_name}: disabled")
                                continue
                            os_objects[obj_name] = obj
                except Exception:
                    logger.warning(f"Error in {resource_file}")
                    raise
            logger.debug(f"os_objects: {os_objects}")
        logger.debug("**--> OSConfig loaded")
        logger.debug(f"Removing {self.os_root_path} from path")
        sys_path.remove(str(self.os_root_path))

        # Filter resources by infra
        filtered_os_objects_by_infra_type: Dict[str, InfraResources] = {}
        logger.debug(f"Filtering resources for env: {env} | infra: {infra} | order: {order}")
        if infra is None:
            filtered_os_objects_by_infra_type = os_objects
        else:
            for resource_name, resource in os_objects.items():
                if resource.infra == infra:
                    filtered_os_objects_by_infra_type[resource_name] = resource

        # Filter resources by env
        filtered_infra_objects_by_env: Dict[str, InfraResources] = {}
        if env is None:
            filtered_infra_objects_by_env = filtered_os_objects_by_infra_type
        else:
            for resource_name, resource in filtered_os_objects_by_infra_type.items():
                if resource.env == env:
                    filtered_infra_objects_by_env[resource_name] = resource

        # Updated resources with the os settings
        # Create a temporary os settings object if it does not exist
        if self._os_settings is None:
            self._os_settings = OSSettings(
                os_root=self.os_root_path,
                os_name=self.os_root_path.stem,
            )
            logger.debug(f"Created OSSettings: {self._os_settings}")
        # Update the resources with the os settings
        if self._os_settings is not None:
            for resource_name, resource in filtered_infra_objects_by_env.items():
                logger.debug(f"Setting os settings for {resource.__class__.__name__}")
                resource.set_os_settings(self._os_settings)

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

        temporary_os_config = OSConfig(os_root_path=resource_file_parent_dir)

        # NOTE: When loading a directory, relative imports or package imports do not work.
        # This is a known problem in python
        #     eg: https://stackoverflow.com/questions/6323860/sibling-package-imports/50193944#50193944
        # To make them work, we add the resource_file_parent_dir to sys.path so it can be treated as a module
        logger.debug(f"Adding {resource_file_parent_dir} to path")
        sys_path.insert(0, str(resource_file_parent_dir))

        logger.debug(f"**--> Reading OS resources from {resource_file}")

        # Get all os resources from the file
        os_objects: Dict[str, InfraBase] = {}
        try:
            # Get all python objects from the file
            python_objects = get_python_objects_from_module(resource_file)
            # Filter out the objects that are subclasses of OSSettings
            for obj_name, obj in python_objects.items():
                if isinstance(obj, OSSettings):
                    logger.debug(f"Found: {obj.__class__.__module__}: {obj_name}")
                    if not obj.enabled:
                        logger.debug(f"Skipping {obj_name}: disabled")
                        continue
                    os_objects[obj_name] = obj
        except Exception:
            logger.error(f"Error reading: {resource_file}")
            raise

        # Filter resources by infra
        filtered_os_objects_by_infra_type: Dict[str, InfraBase] = {}
        logger.debug(f"Filtering resources for env: {env} | infra: {infra} | order: {order}")
        if infra is None:
            filtered_os_objects_by_infra_type = os_objects
        else:
            for resource_name, resource in os_objects.items():
                if resource.infra == infra:
                    filtered_os_objects_by_infra_type[resource_name] = resource

        # Filter resources by env
        filtered_os_objects_by_env: Dict[str, InfraBase] = {}
        if env is None:
            filtered_os_objects_by_env = filtered_os_objects_by_infra_type
        else:
            for resource_name, resource in filtered_os_objects_by_infra_type.items():
                if resource.env == env:
                    filtered_os_objects_by_env[resource_name] = resource

        # Updated resources with the os settings
        # Create a temporary os settings object if it does not exist
        if temporary_os_config._os_settings is None:
            temporary_os_config._os_settings = OSSettings(
                os_root=temporary_os_config.os_root_path,
                os_name=temporary_os_config.os_root_path.stem,
            )
        # Update the resources with the os settings
        if temporary_os_config._os_settings is not None:
            for resource_name, resource in filtered_os_objects_by_env.items():
                logger.debug(f"Setting os settings for {resource.__class__.__name__}")
                resource.set_os_settings(temporary_os_config._os_settings)

        # Create a list of InfraResources from the filtered resources
        os_resources_list: List[InfraResources] = []
        for resource_name, resource in filtered_os_objects_by_env.items():
            # If the resource is an InfraResources object, add it to the list
            if isinstance(resource, InfraResources):
                os_resources_list.append(resource)
            # Otherwise, get the InfraResources object from the resource
            else:
                _os_resources = resource.get_os_resources()
                if _os_resources is not None and isinstance(_os_resources, InfraResources):
                    os_resources_list.append(_os_resources)

        return os_resources_list
