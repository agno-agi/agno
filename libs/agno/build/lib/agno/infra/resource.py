from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.infra.base import InfraBase
from agno.utils.log import logger


class InfraResource(InfraBase):
    """Base class for Infrastructure Resources."""

    # Resource name (required)
    name: str
    # Resource type
    resource_type: Optional[str] = None
    # List of resource types to match for filtering
    resource_type_list: Optional[List[str]] = None

    # -*- Cached Data
    active_resource: Optional[Any] = None
    resource_created: bool = False
    resource_updated: bool = False
    resource_deleted: bool = False

    def read(self, client: Any) -> bool:
        raise NotImplementedError

    def is_active(self, client: Any) -> bool:
        raise NotImplementedError

    def create(self, client: Any) -> bool:
        raise NotImplementedError

    def update(self, client: Any) -> bool:
        raise NotImplementedError

    def delete(self, client: Any) -> bool:
        raise NotImplementedError

    def get_resource_name(self) -> str:
        return self.name or self.__class__.__name__

    def get_resource_type(self) -> str:
        if self.resource_type is None:
            return self.__class__.__name__
        return self.resource_type

    def get_resource_type_list(self) -> List[str]:
        if self.resource_type_list is None:
            return [self.get_resource_type().lower()]

        type_list: List[str] = [resource_type.lower() for resource_type in self.resource_type_list]
        if self.get_resource_type() not in type_list:
            type_list.append(self.get_resource_type().lower())
        return type_list

    def get_input_file_path(self) -> Optional[Path]:
        workspace_dir: Optional[Path] = self.workspace_dir
        if workspace_dir is None:
            from agno.workspace.helpers import get_workspace_dir_from_env

            workspace_dir = get_workspace_dir_from_env()
        if workspace_dir is not None:
            resource_name: str = self.get_resource_name()
            if resource_name is not None:
                input_file_name = f"{resource_name}.yaml"
                input_dir_path = workspace_dir
                if self.input_dir is not None:
                    input_dir_path = input_dir_path.joinpath(self.input_dir)
                else:
                    input_dir_path = input_dir_path.joinpath("input")
                    if self.env is not None:
                        input_dir_path = input_dir_path.joinpath(self.env)
                    if self.group is not None:
                        input_dir_path = input_dir_path.joinpath(self.group)
                    if self.get_resource_type() is not None:
                        input_dir_path = input_dir_path.joinpath(self.get_resource_type().lower())
                return input_dir_path.joinpath(input_file_name)
        return None

    def get_output_file_path(self) -> Optional[Path]:
        workspace_dir: Optional[Path] = self.workspace_dir
        if workspace_dir is None:
            from agno.workspace.helpers import get_workspace_dir_from_env

            workspace_dir = get_workspace_dir_from_env()
        if workspace_dir is not None:
            resource_name: str = self.get_resource_name()
            if resource_name is not None:
                output_file_name = f"{resource_name}.yaml"
                output_dir_path = workspace_dir
                output_dir_path = output_dir_path.joinpath("output")
                if self.env is not None:
                    output_dir_path = output_dir_path.joinpath(self.env)
                if self.output_dir is not None:
                    output_dir_path = output_dir_path.joinpath(self.output_dir)
                elif self.get_resource_type() is not None:
                    output_dir_path = output_dir_path.joinpath(self.get_resource_type().lower())
                return output_dir_path.joinpath(output_file_name)
        return None

    def save_output_file(self) -> bool:
        output_file_path: Optional[Path] = self.get_output_file_path()
        if output_file_path is not None:
            try:
                from agno.utils.yaml_io import write_yaml_file

                if not output_file_path.exists():
                    output_file_path.parent.mkdir(parents=True, exist_ok=True)
                    output_file_path.touch(exist_ok=True)
                write_yaml_file(output_file_path, self.active_resource)
                logger.info(f"Resource saved to: {str(output_file_path)}")
                return True
            except Exception as e:
                logger.error(f"Could not write {self.get_resource_name()} to file: {e}")
        return False

    def read_resource_from_file(self) -> Optional[Dict[str, Any]]:
        output_file_path: Optional[Path] = self.get_output_file_path()
        if output_file_path is not None:
            try:
                from agno.utils.yaml_io import read_yaml_file

                if output_file_path.exists() and output_file_path.is_file():
                    data_from_file = read_yaml_file(output_file_path)
                    if data_from_file is not None and isinstance(data_from_file, dict):
                        return data_from_file
                    else:
                        logger.warning(f"Could not read {self.get_resource_name()} from {output_file_path}")
            except Exception as e:
                logger.error(f"Could not read {self.get_resource_name()} from file: {e}")
        return None

    def delete_output_file(self) -> bool:
        output_file_path: Optional[Path] = self.get_output_file_path()
        if output_file_path is not None:
            try:
                if output_file_path.exists() and output_file_path.is_file():
                    output_file_path.unlink()
                    logger.debug(f"Output file deleted: {str(output_file_path)}")
                    return True
            except Exception as e:
                logger.error(f"Could not delete output file: {e}")
        return False

    def matches_filters(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> bool:
        if group_filter is not None:
            group_name = self.get_group_name()
            logger.debug(f"{self.get_resource_name()}: Checking {group_filter} in {group_name}")
            if group_name is None or group_filter not in group_name:
                return False
        if name_filter is not None:
            resource_name = self.get_resource_name()
            logger.debug(f"{self.get_resource_name()}: Checking {name_filter} in {resource_name}")
            if resource_name is None or name_filter not in resource_name:
                return False
        if type_filter is not None:
            resource_type_list = self.get_resource_type_list()
            logger.debug(f"{self.get_resource_name()}: Checking {type_filter.lower()} in {resource_type_list}")
            if resource_type_list is None or type_filter.lower() not in resource_type_list:
                return False
        return True

    def should_create(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> bool:
        if not self.enabled or self.skip_create:
            return False
        return self.matches_filters(group_filter, name_filter, type_filter)

    def should_delete(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> bool:
        if not self.enabled or self.skip_delete:
            return False
        return self.matches_filters(group_filter, name_filter, type_filter)

    def should_update(
        self,
        group_filter: Optional[str] = None,
        name_filter: Optional[str] = None,
        type_filter: Optional[str] = None,
    ) -> bool:
        if not self.enabled or self.skip_update:
            return False
        return self.matches_filters(group_filter, name_filter, type_filter)

    def __hash__(self):
        return hash(f"{self.get_resource_type()}:{self.get_resource_name()}")

    def __eq__(self, other):
        if isinstance(other, InfraResource):
            if other.get_resource_type() == self.get_resource_type():
                return self.get_resource_name() == other.get_resource_name()
        return False
