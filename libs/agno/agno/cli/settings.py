from __future__ import annotations

from importlib import metadata
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

from agno.utils.log import logger

AGNO_CLI_CONFIG_DIR: Path = Path.home().resolve().joinpath(".config").joinpath("ag")


class AgnoCliSettings(BaseSettings):
    app_name: str = "agno"
    app_version: str = metadata.version("agno")

    tmp_token_path: Path = AGNO_CLI_CONFIG_DIR.joinpath("tmp_token")
    config_file_path: Path = AGNO_CLI_CONFIG_DIR.joinpath("config.json")
    credentials_path: Path = AGNO_CLI_CONFIG_DIR.joinpath("credentials.json")
    ai_conversations_path: Path = AGNO_CLI_CONFIG_DIR.joinpath("ai_conversations.json")
    auth_token_cookie: str = "__agno_session"
    auth_token_header: str = "X-AGNO-AUTH-TOKEN"

    api_runtime: str = "prd"
    api_enabled: bool = True
    alpha_features: bool = False
    api_url: str = Field("https://api.agno.com", validate_default=True)
    signin_url: str = Field("https://app.agno.com/login", validate_default=True)
    playground_url: str = Field("https://app.agno.com/playground", validate_default=True)

    model_config = SettingsConfigDict(env_prefix="AGNO_")

    @field_validator("api_runtime", mode="before")
    def validate_runtime_env(cls, v):
        """Validate api_runtime."""

        valid_api_runtimes = ["dev", "stg", "prd"]
        if v.lower() not in valid_api_runtimes:
            raise ValueError(f"Invalid api_runtime: {v}")

        return v.lower()

    @field_validator("signin_url", mode="before")
    def update_signin_url(cls, v, info: ValidationInfo):
        api_runtime = info.data["api_runtime"]
        if api_runtime == "dev":
            return "http://localhost:3000/login"
        elif api_runtime == "stg":
            return "https://app-stg.agno.com/login"
        else:
            return "https://app.agno.com/login"

    @field_validator("playground_url", mode="before")
    def update_playground_url(cls, v, info: ValidationInfo):
        api_runtime = info.data["api_runtime"]
        if api_runtime == "dev":
            return "http://localhost:3000/playground"
        elif api_runtime == "stg":
            return "https://app-stg.agno.com/playground"
        else:
            return "https://app.agno.com/playground"

    @field_validator("api_url", mode="before")
    def update_api_url(cls, v, info: ValidationInfo):
        api_runtime = info.data["api_runtime"]
        if api_runtime == "dev":
            from os import getenv

            if getenv("AGNO_RUNTIME") == "docker":
                return "http://host.docker.internal:7070"
            return "http://localhost:7070"
        elif api_runtime == "stg":
            return "https://api-stg.agno.com"
        else:
            return "https://api.agno.com"

    def gate_alpha_feature(self):
        if not self.alpha_features:
            logger.error("This is an Alpha feature not for general use.\nPlease message the Agno team for access.")
            exit(1)


agno_cli_settings = AgnoCliSettings()
