"""Railway Project resource."""

from typing import Any, Optional

from agno.railway.api_client import RailwayApiClient
from agno.railway.resource.base import RailwayResource
from agno.utilities.logging import logger


class RailwayProject(RailwayResource):
    """Railway Project resource.

    A project is the top-level container for Railway resources.
    It contains environments, services, plugins, and volumes.
    """

    resource_type: str = "RailwayProject"

    # Project configuration
    description: Optional[str] = None
    workspace_id: Optional[str] = None  # Required: Workspace/Team ID

    def _read(self, railway_client: RailwayApiClient) -> Any:
        """Read project from Railway."""
        if self.railway_id is None:
            logger.debug(f"Project ID not set for {self.name}, cannot read")
            return None

        try:
            project = railway_client.get_project(self.railway_id)
            if project:
                logger.debug(f"Found project: {project.get('name')}")
                return project
            return None
        except Exception as e:
            logger.debug(f"Project {self.name} not found: {e}")
            return None

    def _create(self, railway_client: RailwayApiClient) -> bool:
        """Create project in Railway."""
        # Workspace ID is required for project creation
        if not self.workspace_id:
            logger.error(f"Workspace ID is required to create project {self.name}")
            logger.error("Set workspace_id or RAILWAY_WORKSPACE_ID environment variable")
            return False

        mutation = """
        mutation projectCreate($input: ProjectCreateInput!) {
          projectCreate(input: $input) {
            id
            name
            description
            createdAt
            updatedAt
            baseEnvironmentId
          }
        }
        """

        variables = {
            "input": {
                "name": self.name,
                "workspaceId": self.workspace_id,  # Required field
            }
        }
        if self.description:
            variables["input"]["description"] = self.description

        try:
            result = railway_client.execute_mutation(mutation, variables)
            project = result.get("projectCreate", {})

            if project and "id" in project:
                self.railway_id = project["id"]
                logger.info(f"Created project: {self.name} (ID: {self.railway_id})")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to create project {self.name}: {e}")
            return False

    def _update(self, railway_client: RailwayApiClient) -> bool:
        """Update project in Railway.

        Note: Railway projects have limited update capabilities.
        Most updates are done through environment and service resources.
        """
        logger.debug(f"Update not implemented for project {self.name}")
        return True

    def _delete(self, railway_client: RailwayApiClient) -> bool:
        """Delete project from Railway."""
        if self.railway_id is None:
            logger.warning(f"Project ID not set for {self.name}, cannot delete")
            return False

        mutation = """
        mutation projectDelete($id: String!) {
          projectDelete(id: $id)
        }
        """

        variables = {"id": self.railway_id}

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Deleted project: {self.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete project {self.name}: {e}")
            return False
