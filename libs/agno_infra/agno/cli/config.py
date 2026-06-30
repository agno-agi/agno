from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

from agno.cli.console import print_heading, print_info
from agno.cli.settings import agno_cli_settings
from agno.infra.config import InfraConfig
from agno.utilities.json_io import read_json_file, write_json_file
from agno.utilities.logging import logger


class AgnoCliConfig:
    """The AgnoCliConfig class manages user data for the agno cli"""

    def __init__(
        self,
        active_infra_dir: Optional[str] = None,
        infra_config_map: Optional[Dict[str, InfraConfig]] = None,
    ) -> None:
        # Active infra dir - used as the default for `ag` commands
        # To add an active infra, use the active_infra_dir setter
        self._active_infra_dir: Optional[str] = active_infra_dir

        # Mapping from infra_root_path to infra_config
        self.infra_config_map: Dict[str, InfraConfig] = infra_config_map or OrderedDict()

    ######################################################
    ## Infra functions
    ######################################################

    @property
    def active_infra_dir(self) -> Optional[str]:
        return self._active_infra_dir

    def set_active_infra_dir(self, infra_root_path: Optional[Path]) -> None:
        if infra_root_path is not None:
            logger.debug(f"Setting active infra to: {str(infra_root_path)}")
            self._active_infra_dir = str(infra_root_path)
            self.save_config()

    @property
    def available_infra(self) -> List[InfraConfig]:
        return list(self.infra_config_map.values())

    def _add_or_update_infra_config(
        self,
        infra_root_path: Path,
    ) -> Optional[InfraConfig]:
        """The main function to create, update or refresh a InfraConfig.

        This function does not call self.save_config(). Remember to save_config() after calling this function.
        """

        # Validate infra_root_path
        if infra_root_path is None or not isinstance(infra_root_path, Path):
            raise ValueError(f"Invalid infra_root: {infra_root_path}")
        infra_root_str = str(infra_root_path)

        ######################################################
        # Create new infra_config if one does not exist
        ######################################################
        if infra_root_str not in self.infra_config_map:
            logger.debug(f"Creating infra at: {infra_root_str}")
            new_infra_config = InfraConfig(
                infra_root_path=infra_root_path,
            )
            self.infra_config_map[infra_root_str] = new_infra_config
            logger.debug(f"Infra created at: {infra_root_str}")

            # Return the new_infra_config
            return new_infra_config

        ######################################################
        # Update infra_config
        ######################################################
        logger.debug(f"Updating infra at: {infra_root_str}")
        # By this point there should be a InfraConfig object for this infra_name
        existing_infra_config: Optional[InfraConfig] = self.infra_config_map.get(infra_root_str, None)
        if existing_infra_config is None:
            logger.error(f"Could not find infra at: {infra_root_str}, please run `ag infra setup`")
            return None

        # Swap the existing infra_config with the updated one
        self.infra_config_map[infra_root_str] = existing_infra_config

        # Return the updated_infra_config
        return existing_infra_config

    def add_new_infra_to_config(self, infra_root_path: Path) -> Optional[InfraConfig]:
        """Adds a newly created workspace to the AgnoCliConfig"""

        infra_config = self._add_or_update_infra_config(infra_root_path=infra_root_path)
        self.save_config()
        return infra_config

    def create_or_update_infra_config(
        self,
        infra_root_path: Path,
        set_as_active: bool = True,
    ) -> Optional[InfraConfig]:
        """Creates or updates a WorkspaceConfig and returns the WorkspaceConfig"""

        infra_config = self._add_or_update_infra_config(infra_root_path=infra_root_path)
        if set_as_active:
            self._active_infra_dir = str(infra_root_path)
        self.save_config()
        return infra_config

    def delete_infra(self, infra_root_path: Path) -> None:
        """Handles Deleting a infra from the AgnoCliConfig and api"""

        infra_root_str = str(infra_root_path)
        print_heading(f"Deleting record for infra: {infra_root_str}")

        infra_config: Optional[InfraConfig] = self.infra_config_map.pop(infra_root_str, None)
        if infra_config is None:
            logger.warning(f"No record of infra at {infra_root_str}")
            return

        # Check if we're deleting the active infra, if yes, unset the active infra
        if self._active_infra_dir is not None and self._active_infra_dir == infra_root_str:
            print_info(f"Removing {infra_root_str} as the active infra")
            self._active_infra_dir = None
        self.save_config()
        print_info("Infra record deleted")

    def get_infra_config_by_dir_name(self, infra_dir_name: str) -> Optional[InfraConfig]:
        infra_root_str: Optional[str] = None
        for k, v in self.infra_config_map.items():
            if v.infra_root_path.stem == infra_dir_name:
                infra_root_str = k
                break

        if infra_root_str is None or infra_root_str not in self.infra_config_map:
            return None

        return self.infra_config_map[infra_root_str]

    def get_infra_config_by_path(self, infra_root_path: Path) -> Optional[InfraConfig]:
        return self.infra_config_map[str(infra_root_path)] if str(infra_root_path) in self.infra_config_map else None

    def get_active_infra_config(self) -> Optional[InfraConfig]:
        if self.active_infra_dir is not None and self.active_infra_dir in self.infra_config_map:
            return self.infra_config_map[self.active_infra_dir]
        return None

    ######################################################
    ## Save AgnoCliConfig
    ######################################################

    def save_config(self):
        config_data = {
            "active_infra_dir": self.active_infra_dir,
            "infra_config_map": {k: v.to_dict() for k, v in self.infra_config_map.items()},
        }
        write_json_file(file_path=agno_cli_settings.config_file_path, data=config_data)

    @classmethod
    def from_saved_config(cls) -> Optional["AgnoCliConfig"]:
        try:
            config_data = read_json_file(file_path=agno_cli_settings.config_file_path)
            if config_data is None or not isinstance(config_data, dict):
                logger.debug("No config found")
                return None

            active_infra_dir = config_data.get("active_infra_dir")

            # Create a new config
            new_config = cls(active_infra_dir)

            # Add all the workspaces
            for k, v in config_data.get("infra_config_map", {}).items():
                _infra_config = InfraConfig(**v)
                if _infra_config is not None:
                    new_config.infra_config_map[k] = _infra_config
            return new_config
        except Exception as e:
            logger.warning(e)
            logger.warning("Please setup the infra using `ag infra setup`")
            return None

    ######################################################
    ## Print AgnoCliConfig
    ######################################################

    def print_to_cli(self, show_all: bool = False):
        if self.active_infra_dir:
            print_heading(f"Active infra directory: {self.active_infra_dir}\n")
        else:
            print_info("No active infra found.")
            print_info(
                "Please create a infra using `ag infra create` or setup an existing infra using `ag infra setup`"
            )

        if show_all and len(self.infra_config_map) > 0:
            print_heading("Available infra:\n")
            c = 1
            for k, _ in self.infra_config_map.items():
                print_info(f"  {c}. Path: {k}")
                c += 1
