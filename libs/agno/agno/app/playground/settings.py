from __future__ import annotations

from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class PlaygroundSettings(BaseSettings):
    """Playground API settings that can be set using environment variables.

    Reference: https://pydantic-docs.helpmanual.io/usage/settings/
    """

    env: str = "dev"
    title: str = "agno-playground"

    # Set to False to disable docs server at /docs and /redoc
    docs_enabled: bool = True

    secret_key: Optional[str] = None

    # Cors origin list to allow requests from.
    # This list is set using the set_cors_origin_list validator
    cors_origin_list: Optional[List[str]] = Field(None, validate_default=True)

    @field_validator("env", mode="before")
    def validate_playground_env(cls, env):
        """Validate playground_env."""

        valid_runtime_envs = ["dev", "stg", "prd"]
        if env not in valid_runtime_envs:
            raise ValueError(f"Invalid Playground Env: {env}")
        return env

    @field_validator("cors_origin_list", mode="before")
    def set_cors_origin_list(cls, cors_origin_list):
        valid_cors = cors_origin_list or []

        # Add Agno domains to cors origin list
        valid_cors.extend(
            [
                "http://localhost:3000",
                "https://agno.com",
                "https://www.agno.com",
                "https://app.agno.com",
                "https://app-stg.agno.com",
            ]
        )

        return valid_cors
