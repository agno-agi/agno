from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from agno.infra.settings import InfraSettings


class InfraBase(BaseModel):
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

    # Infra Settings
    infra_settings: Optional[InfraSettings] = None

    # Cached Data
    cached_infra_dir: Optional[Path] = None
    cached_env_file_data: Optional[Dict[str, Any]] = None
    cached_secret_file_data: Optional[Dict[str, Any]] = None

    def get_group_name(self) -> Optional[str]:
        return self.group or self.name

    @property
    def infra_root(self) -> Optional[Path]:
        return self.infra_settings.infra_root if self.infra_settings is not None else None

    @property
    def infra_name(self) -> Optional[str]:
        return self.infra_settings.infra_name if self.infra_settings is not None else None

    @property
    def infra_dir(self) -> Optional[Path]:
        if self.cached_infra_dir is not None:
            return self.cached_infra_dir

        if self.infra_root is not None:
            from agno.infra.helpers import get_infra_dir_path

            infra_dir = get_infra_dir_path(self.infra_root)
            if infra_dir is not None:
                self.cached_infra_dir = infra_dir
                return infra_dir
        return None

    def set_infra_settings(self, infra_settings: Optional[InfraSettings] = None) -> None:
        if infra_settings is not None:
            self.infra_settings = infra_settings

    def get_env_file_data(self) -> Optional[Dict[str, Any]]:
        if self.cached_env_file_data is None:
            from agno.utilities.yaml_io import read_yaml_file

            self.cached_env_file_data = read_yaml_file(file_path=self.env_file)
        return self.cached_env_file_data

    def get_secret_file_data(self) -> Optional[Dict[str, Any]]:
        if self.cached_secret_file_data is None:
            from agno.utilities.yaml_io import read_yaml_file

            self.cached_secret_file_data = read_yaml_file(file_path=self.secrets_file)
        return self.cached_secret_file_data

    def get_secret_from_file(self, secret_name: str) -> Optional[str]:
        secret_file_data = self.get_secret_file_data()
        if secret_file_data is not None:
            return secret_file_data.get(secret_name)
        return None

    def get_infra_resources(self) -> Optional[Any]:
        """This method returns an InfraResources object for this resource"""
        raise NotImplementedError("get_infra_resources method not implemented")
