from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

from agno.cli.console import print_heading, print_info
from agno.cli.settings import agno_cli_settings
from agno.os.config import OSConfig
from agno.utils.json_io import read_json_file, write_json_file
from agno.utils.logging import logger


class AgnoCliConfig:
    """The AgnoCliConfig class manages user data for the agno cli"""

    def __init__(
        self,
        active_os_dir: Optional[str] = None,
        os_config_map: Optional[Dict[str, OSConfig]] = None,
    ) -> None:
        # Active os dir - used as the default for `ag` commands
        # To add an active os, use the active_os_dir setter
        self._active_os_dir: Optional[str] = active_os_dir

        # Mapping from os_root_path to os_config
        self.os_config_map: Dict[str, OSConfig] = os_config_map or OrderedDict()

    ######################################################
    ## OS functions
    ######################################################

    @property
    def active_os_dir(self) -> Optional[str]:
        return self._active_os_dir

    def set_active_os_dir(self, os_root_path: Optional[Path]) -> None:
        if os_root_path is not None:
            logger.debug(f"Setting active os to: {str(os_root_path)}")
            self._active_os_dir = str(os_root_path)
            self.save_config()

    @property
    def available_os(self) -> List[OSConfig]:
        return list(self.os_config_map.values())

    def _add_or_update_os_config(
        self,
        os_root_path: Path,
    ) -> Optional[OSConfig]:
        """The main function to create, update or refresh a OSConfig.

        This function does not call self.save_config(). Remember to save_config() after calling this function.
        """

        # Validate os_root_path
        if os_root_path is None or not isinstance(os_root_path, Path):
            raise ValueError(f"Invalid os_root: {os_root_path}")
        os_root_str = str(os_root_path)

        ######################################################
        # Create new os_config if one does not exist
        ######################################################
        if os_root_str not in self.os_config_map:
            logger.debug(f"Creating os at: {os_root_str}")
            new_os_config = OSConfig(
                os_root_path=os_root_path,
            )
            self.os_config_map[os_root_str] = new_os_config
            logger.debug(f"OS created at: {os_root_str}")

            # Return the new_os_config
            return new_os_config

        ######################################################
        # Update os_config
        ######################################################
        logger.debug(f"Updating os at: {os_root_str}")
        # By this point there should be a OSConfig object for this os_name
        existing_os_config: Optional[OSConfig] = self.os_config_map.get(os_root_str, None)
        if existing_os_config is None:
            logger.error(f"Could not find os at: {os_root_str}, please run `ag os setup`")
            return None

        # Swap the existing os_config with the updated one
        self.os_config_map[os_root_str] = existing_os_config

        # Return the updated_os_config
        return existing_os_config

    def add_new_os_to_config(self, os_root_path: Path) -> Optional[OSConfig]:
        """Adds a newly created workspace to the AgnoCliConfig"""

        ws_config = self._add_or_update_os_config(os_root_path=os_root_path)
        self.save_config()
        return ws_config

    def create_or_update_os_config(
        self,
        os_root_path: Path,
        set_as_active: bool = True,
    ) -> Optional[OSConfig]:
        """Creates or updates a WorkspaceConfig and returns the WorkspaceConfig"""

        os_config = self._add_or_update_os_config(os_root_path=os_root_path)
        if set_as_active:
            self._active_os_dir = str(os_root_path)
        self.save_config()
        return os_config

    def delete_os(self, os_root_path: Path) -> None:
        """Handles Deleting a os from the AgnoCliConfig and api"""

        os_root_str = str(os_root_path)
        print_heading(f"Deleting record for os: {os_root_str}")

        os_config: Optional[OSConfig] = self.os_config_map.pop(os_root_str, None)
        if os_config is None:
            logger.warning(f"No record of os at {os_root_str}")
            return

        # Check if we're deleting the active os, if yes, unset the active os
        if self._active_os_dir is not None and self._active_os_dir == os_root_str:
            print_info(f"Removing {os_root_str} as the active os")
            self._active_os_dir = None
        self.save_config()
        print_info("OS record deleted")

    def get_os_config_by_dir_name(self, os_dir_name: str) -> Optional[OSConfig]:
        os_root_str: Optional[str] = None
        for k, v in self.os_config_map.items():
            if v.os_root_path.stem == os_dir_name:
                os_root_str = k
                break

        if os_root_str is None or os_root_str not in self.os_config_map:
            return None

        return self.os_config_map[os_root_str]

    def get_os_config_by_path(self, os_root_path: Path) -> Optional[OSConfig]:
        return self.os_config_map[str(os_root_path)] if str(os_root_path) in self.os_config_map else None

    def get_active_os_config(self) -> Optional[OSConfig]:
        if self.active_os_dir is not None and self.active_os_dir in self.os_config_map:
            return self.os_config_map[self.active_os_dir]
        return None

    ######################################################
    ## Save AgnoCliConfig
    ######################################################

    def save_config(self):
        config_data = {
            "active_os_dir": self.active_os_dir,
            "os_config_map": {k: v.to_dict() for k, v in self.os_config_map.items()},
        }
        write_json_file(file_path=agno_cli_settings.config_file_path, data=config_data)

    @classmethod
    def from_saved_config(cls) -> Optional["AgnoCliConfig"]:
        try:
            config_data = read_json_file(file_path=agno_cli_settings.config_file_path)
            if config_data is None or not isinstance(config_data, dict):
                logger.debug("No config found")
                return None

            active_os_dir = config_data.get("active_os_dir")

            # Create a new config
            new_config = cls(active_os_dir)

            # Add all the workspaces
            for k, v in config_data.get("os_config_map", {}).items():
                _os_config = OSConfig(**v)
                if _os_config is not None:
                    new_config.os_config_map[k] = _os_config
            return new_config
        except Exception as e:
            logger.warning(e)
            logger.warning("Please setup the os using `ag os setup`")
            return None

    ######################################################
    ## Print AgnoCliConfig
    ######################################################

    def print_to_cli(self, show_all: bool = False):
        if self.active_os_dir:
            print_heading(f"Active os directory: {self.active_os_dir}\n")
        else:
            print_info("No active os found.")
            print_info("Please create a os using `ag os create` or setup an existing os using `ag os setup`")

        if show_all and len(self.os_config_map) > 0:
            print_heading("Available os:\n")
            c = 1
            for k, _ in self.os_config_map.items():
                print_info(f"  {c}. Path: {k}")
                c += 1
