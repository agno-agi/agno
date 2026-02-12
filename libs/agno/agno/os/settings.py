from __future__ import annotations

from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class AgnoAPISettings(BaseSettings):
    """App settings for API-based apps that can be set using environment variables.

    Reference: https://pydantic-docs.helpmanual.io/usage/settings/
    """

    env: str = "dev"

    # Set to False to disable docs server at /docs and /redoc
    docs_enabled: bool = True

    # Authentication settings
    os_security_key: Optional[str] = Field(default=None, description="Bearer token for API authentication")

    # Authorization flag - when True, JWT middleware handles auth and security key validation is skipped
    authorization_enabled: bool = Field(default=False, description="Whether JWT authorization is enabled")

    # Cors origin list to allow requests from.
    # This list is set using the set_cors_origin_list validator
    cors_origin_list: Optional[List[str]] = Field(default=None, validate_default=True)

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
                "https://os-stg.agno.com",
                "https://os.agno.com",
            ]
        )

        return valid_cors
