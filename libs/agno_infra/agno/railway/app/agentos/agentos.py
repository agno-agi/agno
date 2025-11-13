"""Railway AgentOS application."""

from typing import Dict, List, Optional, Union

from agno.base.context import ContainerContext
from agno.railway.app.base import RailwayApp


class RailwayAgentOS(RailwayApp):
    """Railway AgentOS application.

    This class provides an AgentOS application deployment for Railway.
    AgentOS is a production-ready FastAPI runtime that serves Agno agents,
    teams, and workflows as a web API.

    AgentOS requires a PostgreSQL database for session persistence, memory,
    and knowledge storage. Use the `database` parameter to reference a
    RailwayPostgres resource.
    """

    # App name and image configuration
    name: str = "agentos"
    image_name: str = "agnohq/agentos"  # Default AgentOS image
    image_tag: str = "latest"
    command: Optional[Union[str, List[str]]] = None  # AgentOS has default entrypoint

    # Port configuration
    open_port: bool = True
    port_number: int = 8000

    # Uvicorn Configuration (inherited from FastAPI)
    uvicorn_host: str = "0.0.0.0"
    uvicorn_port: Optional[int] = None
    uvicorn_reload: Optional[bool] = None
    uvicorn_log_level: Optional[str] = "info"
    web_concurrency: Optional[int] = 2

    # AgentOS Configuration
    agentos_ui_url: str = "https://os.agno.com"  # AgentOS UI URL
    enable_cors: bool = True  # Enable CORS for UI access

    def get_container_env(self, container_context: ContainerContext) -> Dict[str, str]:
        """Get environment variables for the AgentOS container.

        This method builds the environment variable dictionary from:
        1. Database connection (from referenced database)
        2. Base RailwayApp environment variables
        3. AgentOS-specific variables
        4. Uvicorn configuration

        Args:
            container_context: Container context with infra paths

        Returns:
            Dictionary of environment variables
        """
        # Get base container environment from RailwayApp (includes DATABASE_URL if database is set)
        container_env = super().get_container_env(container_context)

        # Add Uvicorn configuration (similar to FastAPI)
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

        # Add AgentOS-specific configuration
        if self.agentos_ui_url:
            container_env["AGENTOS_UI_URL"] = self.agentos_ui_url

        if self.enable_cors:
            container_env["ENABLE_CORS"] = "true"

        # Ensure DATABASE_URL is present (required for AgentOS)
        if "DATABASE_URL" not in container_env:
            # If no database reference was provided, warn the user
            # AgentOS requires a database connection
            container_env[
                "DATABASE_URL"
            ] = "postgresql://postgres:postgres@localhost:5432/railway"  # Default placeholder

        return container_env
