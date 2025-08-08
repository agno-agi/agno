from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.os.settings import OSSettings


@dataclass
class InfraBase:
    """Base class for all InfraResource, InfraApp and InfraResources objects."""

    # Name of the infrastructure resource
    name: Optional[str] = None
    # Group for the infrastructure resource
    # Used for filtering infrastructure resources by group
    group: Optional[str] = None
    # Environment filter for this resource
    env: Optional[str] = None
    # Infrastructure filter for this resource
    infra: Optional[str] = None
    # Whether this resource is enabled
    enabled: bool = True

    # Resource Control
    skip_create: bool = False
    skip_read: bool = False
    skip_update: bool = False
    skip_delete: bool = False
    recreate_on_update: bool = False

    # Skip create if resource with the same name is active
    use_cache: bool = True

    # Force create/update/delete even if a resource with the same name is active
    force: Optional[bool] = None

    # Wait for resource to be created, updated or deleted
    wait_for_create: bool = True
    wait_for_update: bool = True
    wait_for_delete: bool = True
    waiter_delay: int = 30
    waiter_max_attempts: int = 50

    # Environment Variables for the resource (if applicable)
    # Add env variables to resource where applicable
    env_vars: Optional[Dict[str, Any]] = None
    # Read env from a file in yaml format
    env_file: Optional[Path] = None

    # Add secret variables to resource where applicable
    # secrets_dict: Optional[Dict[str, Any]] = None
    # Read secrets from a file in yaml format
    secrets_file: Optional[Path] = None

    # Debug Mode
    debug_mode: bool = False

    # Store resource to output directory
    # If True, save resource output to json files
    save_output: bool = False

    # The directory for the input files in the infra directory
    input_dir: Optional[str] = None
    # The directory for the output files in the infra directory
    output_dir: Optional[str] = None

    # Dependencies for the resource
    depends_on: Optional[List[Any]] = None

    # OS Settings
    os_settings: Optional[OSSettings] = None

    # Cached Data
    cached_os_dir: Optional[Path] = None
    cached_env_file_data: Optional[Dict[str, Any]] = None
    cached_secret_file_data: Optional[Dict[str, Any]] = None

    def get_group_name(self) -> Optional[str]:
        return self.group or self.name

    @property
    def os_root(self) -> Optional[Path]:
        return self.os_settings.os_root if self.os_settings is not None else None

    @property
    def os_name(self) -> Optional[str]:
        return self.os_settings.os_name if self.os_settings is not None else None

    @property
    def os_dir(self) -> Optional[Path]:
        if self.cached_os_dir is not None:
            return self.cached_os_dir

        if self.os_root is not None:
            from agno.os.helpers import get_os_infra_dir_path

            os_dir = get_os_infra_dir_path(self.os_root)
            if os_dir is not None:
                self.cached_os_dir = os_dir
                return os_dir
        return None

    def set_os_settings(self, os_settings: Optional[OSSettings] = None) -> None:
        if os_settings is not None:
            self.os_settings = os_settings

    def get_env_file_data(self) -> Optional[Dict[str, Any]]:
        if self.cached_env_file_data is None:
            from agno.utils.yaml_io import read_yaml_file

            self.cached_env_file_data = read_yaml_file(file_path=self.env_file)
        return self.cached_env_file_data

    def get_secret_file_data(self) -> Optional[Dict[str, Any]]:
        if self.cached_secret_file_data is None:
            from agno.utils.yaml_io import read_yaml_file

            self.cached_secret_file_data = read_yaml_file(file_path=self.secrets_file)
        return self.cached_secret_file_data

    def get_secret_from_file(self, secret_name: str) -> Optional[str]:
        secret_file_data = self.get_secret_file_data()
        if secret_file_data is not None:
            return secret_file_data.get(secret_name)
        return None

    def get_os_resources(self) -> Optional[Any]:
        """This method returns an InfraResources object for this resource"""
        raise NotImplementedError("get_os_resources method not implemented")
