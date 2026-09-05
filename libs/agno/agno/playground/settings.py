from __future__ import annotations

from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class PlaygroundSettings(BaseSettings):
    """Backward-compatible settings for the legacy Playground API."""

    env: str = "dev"
    title: str = "agno-playground"
    docs_enabled: bool = True
    secret_key: Optional[str] = None
    cors_origin_list: Optional[List[str]] = Field(default=None, validate_default=True)

    @field_validator("env", mode="before")
    def validate_playground_env(cls, env):
        valid_runtime_envs = ["dev", "stg", "prd"]
        if env not in valid_runtime_envs:
            raise ValueError(f"Invalid Playground Env: {env}")
        return env

    @field_validator("cors_origin_list", mode="before")
    def set_cors_origin_list(cls, cors_origin_list):
        valid_cors = cors_origin_list or []
        valid_cors.extend(
            [
                "http://localhost:3000",
                "https://agno.com",
                "https://www.agno.com",
                "https://app.agno.com",
                "https://os-stg.agno.com",
                "https://os.agno.com",
            ]
        )
        return valid_cors


__all__ = ["PlaygroundSettings"]
