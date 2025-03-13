from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

from agno.api.schemas.user import TeamSchema, UserSchema
from agno.api.schemas.workspace import WorkspaceSchema
from agno.cli.console import print_heading, print_info
from agno.cli.settings import agno_cli_settings
from agno.utils.json_io import read_json_file, write_json_file
from agno.utils.log import logger
from agno.workspace.config import WorkspaceConfig


class AgnoCliConfig:
    """The AgnoCliConfig class manages user data for the agno cli"""

    def __init__(
        self,
        user: Optional[UserSchema] = None,
        active_ws_dir: Optional[str] = None,
        ws_config_map: Optional[Dict[str, WorkspaceConfig]] = None,
    ) -> None:
        # Current user, populated after authenticating with the api
        # To add a user, use the user setter
        self._user: Optional[UserSchema] = user

        # Active ws dir - used as the default for `ag` commands
        # To add an active workspace, use the active_ws_dir setter
        self._active_ws_dir: Optional[str] = active_ws_dir

        # Mapping from ws_root_path to ws_config
        self.ws_config_map: Dict[str, WorkspaceConfig] = ws_config_map or OrderedDict()

    ######################################################
    ## User functions
    ######################################################

    @property
    def user(self) -> Optional[UserSchema]:
        return self._user

    @user.setter
    def user(self, user: Optional[UserSchema]) -> None:
        """Sets the user"""
        if user is not None:
            logger.debug(f"Setting user to: {user.email}")
            clear_user_cache = (
                self._user is not None  # previous user is not None
                and self._user.email != "anon"  # previous user is not anon
                and (user.email != self._user.email or user.id_user != self._user.id_user)  # new user is different
            )
            self._user = user
            if clear_user_cache:
                self.clear_user_cache()
            self.save_config()

    def clear_user_cache(self) -> None:
        """Clears the user cache"""
        logger.debug("Clearing user cache")
        self.ws_config_map.clear()
        self._active_ws_dir = None
        agno_cli_settings.ai_conversations_path.unlink(missing_ok=True)
        logger.info("Workspaces cleared, please setup again using `ag ws setup`")

    ######################################################
    ## Workspace functions
    ######################################################

    @property
    def active_ws_dir(self) -> Optional[str]:
        return self._active_ws_dir

    def set_active_ws_dir(self, ws_root_path: Optional[Path]) -> None:
        if ws_root_path is not None:
            logger.debug(f"Setting active workspace to: {str(ws_root_path)}")
            self._active_ws_dir = str(ws_root_path)
            self.save_config()

    @property
    def available_ws(self) -> List[WorkspaceConfig]:
        return list(self.ws_config_map.values())

    def _add_or_update_ws_config(
        self,
        ws_root_path: Path,
        ws_schema: Optional[WorkspaceSchema] = None,
        ws_team: Optional[TeamSchema] = None,
        ws_api_key: Optional[str] = None,
    ) -> Optional[WorkspaceConfig]:
        """The main function to create, update or refresh a WorkspaceConfig.

        This function does not call self.save_config(). Remember to save_config() after calling this function.
        """

        # Validate ws_root_path
        if ws_root_path is None or not isinstance(ws_root_path, Path):
            raise ValueError(f"Invalid ws_root: {ws_root_path}")
        ws_root_str = str(ws_root_path)

        ######################################################
        # Create new ws_config if one does not exist
        ######################################################
        if ws_root_str not in self.ws_config_map:
            logger.debug(f"Creating workspace at: {ws_root_str}")
            new_workspace_config = WorkspaceConfig(
                ws_root_path=ws_root_path,
                ws_schema=ws_schema,
                ws_team=ws_team,
                ws_api_key=ws_api_key,
            )
            self.ws_config_map[ws_root_str] = new_workspace_config
            logger.debug(f"Workspace created at: {ws_root_str}")

            # Return the new_workspace_config
            return new_workspace_config

        ######################################################
        # Update ws_config
        ######################################################
        logger.debug(f"Updating workspace at: {ws_root_str}")
        # By this point there should be a WorkspaceConfig object for this ws_name
        existing_ws_config: Optional[WorkspaceConfig] = self.ws_config_map.get(ws_root_str, None)
        if existing_ws_config is None:
            logger.error(f"Could not find workspace at: {ws_root_str}, please run `ag ws setup`")
            return None

        # Update the ws_schema if it's not None and different from the existing one
        if ws_schema is not None and existing_ws_config.ws_schema != ws_schema:
            existing_ws_config.ws_schema = ws_schema

        # Update the ws_team if it's not None and different from the existing one
        if ws_team is not None and existing_ws_config.ws_team != ws_team:
            existing_ws_config.ws_team = ws_team

        # Update the ws_api_key if it's not None and different from the existing one
        if ws_api_key is not None and existing_ws_config.ws_api_key != ws_api_key:
            existing_ws_config.ws_api_key = ws_api_key

        # Swap the existing ws_config with the updated one
        self.ws_config_map[ws_root_str] = existing_ws_config

        # Return the updated_ws_config
        return existing_ws_config

    def add_new_ws_to_config(
        self, ws_root_path: Path, ws_team: Optional[TeamSchema] = None
    ) -> Optional[WorkspaceConfig]:
        """Adds a newly created workspace to the AgnoCliConfig"""

        ws_config = self._add_or_update_ws_config(ws_root_path=ws_root_path, ws_team=ws_team)
        self.save_config()
        return ws_config

    def create_or_update_ws_config(
        self,
        ws_root_path: Path,
        ws_schema: Optional[WorkspaceSchema] = None,
        ws_team: Optional[TeamSchema] = None,
        set_as_active: bool = True,
    ) -> Optional[WorkspaceConfig]:
        """Creates or updates a WorkspaceConfig and returns the WorkspaceConfig"""

        ws_config = self._add_or_update_ws_config(
            ws_root_path=ws_root_path,
            ws_schema=ws_schema,
            ws_team=ws_team,
        )
        if set_as_active:
            self._active_ws_dir = str(ws_root_path)
        self.save_config()
        return ws_config

    def delete_ws(self, ws_root_path: Path) -> None:
        """Handles Deleting a workspace from the AgnoCliConfig and api"""

        ws_root_str = str(ws_root_path)
        print_heading(f"Deleting record for workspace: {ws_root_str}")

        ws_config: Optional[WorkspaceConfig] = self.ws_config_map.pop(ws_root_str, None)
        if ws_config is None:
            logger.warning(f"No record of workspace at {ws_root_str}")
            return

        # Check if we're deleting the active workspace, if yes, unset the active ws
        if self._active_ws_dir is not None and self._active_ws_dir == ws_root_str:
            print_info(f"Removing {ws_root_str} as the active workspace")
            self._active_ws_dir = None
        self.save_config()
        print_info("Workspace record deleted")
        print_info("Note: this does not delete any data locally or from agno.com, please delete them manually\n")

    def get_ws_config_by_dir_name(self, ws_dir_name: str) -> Optional[WorkspaceConfig]:
        ws_root_str: Optional[str] = None
        for k, v in self.ws_config_map.items():
            if v.ws_root_path.stem == ws_dir_name:
                ws_root_str = k
                break

        if ws_root_str is None or ws_root_str not in self.ws_config_map:
            return None

        return self.ws_config_map[ws_root_str]

    def get_ws_config_by_path(self, ws_root_path: Path) -> Optional[WorkspaceConfig]:
        return self.ws_config_map[str(ws_root_path)] if str(ws_root_path) in self.ws_config_map else None

    def get_active_ws_config(self) -> Optional[WorkspaceConfig]:
        if self.active_ws_dir is not None and self.active_ws_dir in self.ws_config_map:
            return self.ws_config_map[self.active_ws_dir]
        return None

    ######################################################
    ## Save AgnoCliConfig
    ######################################################

    def save_config(self):
        config_data = {
            "user": self.user.model_dump() if self.user else None,
            "active_ws_dir": self.active_ws_dir,
            "ws_config_map": {k: v.to_dict() for k, v in self.ws_config_map.items()},
        }
        write_json_file(file_path=agno_cli_settings.config_file_path, data=config_data)

    @classmethod
    def from_saved_config(cls) -> Optional["AgnoCliConfig"]:
        try:
            config_data = read_json_file(file_path=agno_cli_settings.config_file_path)
            if config_data is None or not isinstance(config_data, dict):
                logger.debug("No config found")
                return None

            user_dict = config_data.get("user")
            user_schema = UserSchema.model_validate(user_dict) if user_dict else None
            active_ws_dir = config_data.get("active_ws_dir")

            # Create a new config
            new_config = cls(user_schema, active_ws_dir)

            # Add all the workspaces
            for k, v in config_data.get("ws_config_map", {}).items():
                _ws_config = WorkspaceConfig.model_validate(v)
                if _ws_config is not None:
                    new_config.ws_config_map[k] = _ws_config
            return new_config
        except Exception as e:
            logger.warning(e)
            logger.warning("Please setup the workspace using `ag ws setup`")
            return None

    ######################################################
    ## Print AgnoCliConfig
    ######################################################

    def print_to_cli(self, show_all: bool = False):
        if self.user:
            print_heading(f"User: {self.user.email}\n")
        if self.active_ws_dir:
            print_heading(f"Active workspace directory: {self.active_ws_dir}\n")
        else:
            print_info("No active workspace found.")
            print_info(
                "Please create a workspace using `ag ws create` or setup an existing workspace using `ag ws setup`"
            )

        if show_all and len(self.ws_config_map) > 0:
            print_heading("Available workspaces:\n")
            c = 1
            for k, v in self.ws_config_map.items():
                print_info(f"  {c}. Path: {k}")
                if v.ws_schema and v.ws_schema.ws_name:
                    print_info(f"     Name: {v.ws_schema.ws_name}")
                if v.ws_team and v.ws_team.name:
                    print_info(f"     Team: {v.ws_team.name}")
                c += 1
