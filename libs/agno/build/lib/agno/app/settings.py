from __future__ import annotations

from pydantic_settings import BaseSettings


class APIAppSettings(BaseSettings):
    """App settings for API-based apps that can be set using environment variables.

    Reference: https://pydantic-docs.helpmanual.io/usage/settings/
    """

    title: str = "agno-app"

    # Set to False to disable docs server at /docs and /redoc
    docs_enabled: bool = True
