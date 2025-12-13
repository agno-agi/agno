"""Railway FastAPI application."""

from typing import Dict, List, Optional, Union

from agno.base.context import ContainerContext
from agno.railway.app.base import RailwayApp
from agno.railway.context import RailwayBuildContext


class RailwayFastApi(RailwayApp):
    """Railway FastAPI application.

    This class provides a FastAPI application deployment for Railway.
    It extends RailwayApp with FastAPI-specific configuration.
    """

    # App name and image configuration
    name: str = "fastapi"
    image_name: str = "agnohq/fastapi"
    image_tag: str = "0.104"
    command: Optional[Union[str, List[str]]] = "uvicorn main:app --reload"

    # Port configuration
    open_port: bool = True
    port_number: int = 8000

    # Uvicorn Configuration
    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: Optional[int] = None
    uvicorn_reload: Optional[bool] = None
    uvicorn_log_level: Optional[str] = None
    web_concurrency: Optional[int] = None

    def get_container_env(self, container_context: ContainerContext) -> Dict[str, str]:
        """Get environment variables for the FastAPI container.

        This method builds the environment variable dictionary from:
        1. Base RailwayApp environment variables
        2. FastAPI/Uvicorn-specific variables

        Args:
            container_context: Container context with infra paths

        Returns:
            Dictionary of environment variables
        """
        # Get base container environment from RailwayApp
        container_env = super().get_container_env(container_context)

        # Add Uvicorn configuration
        if self.uvicorn_host is not None:
            container_env["UVICORN_HOST"] = self.uvicorn_host

        if self.uvicorn_port is not None:
            container_env["UVICORN_PORT"] = str(self.uvicorn_port)
        elif self.port_number is not None:
            # Use port_number as default if uvicorn_port not set
            container_env["UVICORN_PORT"] = str(self.port_number)

        if self.uvicorn_reload is not None:
            container_env["UVICORN_RELOAD"] = str(self.uvicorn_reload).lower()

        if self.uvicorn_log_level is not None:
            container_env["UVICORN_LOG_LEVEL"] = self.uvicorn_log_level

        if self.web_concurrency is not None:
            container_env["WEB_CONCURRENCY"] = str(self.web_concurrency)

        return container_env
