from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

AGNO_CLI_CONFIG_DIR: Path = Path.home().resolve().joinpath(".config").joinpath("ag")


class AgnoCliSettings(BaseSettings):
    config_file_path: Path = AGNO_CLI_CONFIG_DIR.joinpath("config.json")

    model_config = SettingsConfigDict(env_prefix="AGNO_")


agno_cli_settings = AgnoCliSettings()
