"""Base class for Railway applications."""

from typing import Dict, List, Optional

from agno.base.app import InfraApp
from agno.base.context import ContainerContext
from agno.base.resource import InfraResource
from agno.railway.context import RailwayBuildContext
from agno.railway.resource.environment import RailwayEnvironment
from agno.railway.resource.project import RailwayProject
from agno.railway.resource.service import RailwayService
from agno.railway.resource.variable import RailwayVariable
from agno.utilities.logging import logger


class RailwayApp(InfraApp):
    """Base class for Railway applications.

    Railway apps are deployed as services on Railway's platform.
    This base class provides common functionality for all Railway apps.
    """

    # Railway-specific configuration
    railway_project_id: Optional[str] = None
    railway_environment: str = "production"

    # Service icon (emoji or URL)
    service_icon: Optional[str] = None

    def get_container_env(self, container_context: ContainerContext) -> Dict[str, str]:
        """Get environment variables for the container.

        This method builds the environment variable dictionary from:
        1. Base container_env (if set by subclass)
        2. User-provided env_vars
        3. Railway-specific variables (PORT, etc.)

        Args:
            container_context: Container context with infra paths

        Returns:
            Dictionary of environment variables
        """
        # Start with base container_env if set
        container_env: Dict[str, str] = self.container_env.copy() if self.container_env else {}

        # Add user-provided env_vars
        if self.env_vars:
            container_env.update(self.env_vars)

        # Railway uses PORT env var for the exposed port
        if self.open_port and self.port_number:
            container_env["PORT"] = str(self.port_number)

        # Add Python-specific env vars if needed
        if self.set_python_path:
            if self.python_path:
                container_env["PYTHONPATH"] = self.python_path
            elif self.add_python_paths:
                container_env["PYTHONPATH"] = ":".join(self.add_python_paths)

        return container_env

    def build_resources(self, build_context: RailwayBuildContext) -> List[InfraResource]:
        """Build Railway resource graph for this app.

        Creates the necessary Railway resources:
        1. Project (if not provided)
        2. Environment (if not exists)
        3. Service (the actual application)
        4. Variables (environment variables)

        Args:
            build_context: Railway build context

        Returns:
            List of Railway resources to create
        """
        resources: List[InfraResource] = []

        # Determine project ID
        project_id = self.railway_project_id or build_context.project_id

        # 1. Create project if needed
        if project_id is None:
            project = RailwayProject(
                name=f"{self.name}-project",
                description=f"Railway project for {self.name}",
                workspace_id=build_context.workspace_id,
            )
            resources.append(project)
            # Reference will be resolved later
            project_id = "{{project.railway_id}}"

        # 2. Create or reference environment
        environment = RailwayEnvironment(
            name=f"{self.name}-env",
            project_id=project_id,
            environment_name=self.railway_environment,
        )
        resources.append(environment)
        environment_id = "{{environment.railway_id}}"

        # 3. Create service
        service = RailwayService(
            name=self.name,
            project_id=project_id,
            environment_id=environment_id,
            source_image=self.get_image_str() if self.get_image_str() else None,
            icon=self.service_icon,
        )
        resources.append(service)

        # 4. Create environment variables
        # Get container context for env var building
        container_context = ContainerContext(
            infra_name=self.name,
            infra_root="/app",  # Railway default
            infra_parent="/",
            requirements_file=self.requirements_file if self.install_requirements else None,
        )
        container_env = self.get_container_env(container_context)

        for key, value in container_env.items():
            var = RailwayVariable(
                name=f"{self.name}-{key.lower()}",
                project_id=project_id,
                environment_id=environment_id,
                variable_name=key,
                variable_value=str(value),
            )
            resources.append(var)

        logger.debug(f"Built {len(resources)} Railway resources for {self.name}")
        return resources
