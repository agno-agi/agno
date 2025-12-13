"""Railway Environment resource."""

from typing import Any, Optional

from agno.railway.api_client import RailwayApiClient
from agno.railway.resource.base import RailwayResource
from agno.utilities.logging import logger


class RailwayEnvironment(RailwayResource):
    """Railway Environment resource.

    Environments (production, staging, etc.) contain service instances and variables.
    Each project has a default "production" environment created automatically.
    """

    resource_type: str = "RailwayEnvironment"

    # Required: project ID
    project_id: str

    # Environment name (production, staging, dev, etc.)
    environment_name: str = "production"

    def _read(self, railway_client: RailwayApiClient) -> Any:
        """Read environment from Railway."""
        if self.railway_id is None:
            # Try to find environment by name in the project
            try:
                query = """
                query project($id: String!) {
                  project(id: $id) {
                    id
                    environments {
                      edges {
                        node {
                          id
                          name
                        }
                      }
                    }
                  }
                }
                """
                result = railway_client.execute_query(query, {"id": self.project_id})
                project = result.get("project", {})
                environments = project.get("environments", {}).get("edges", [])

                for edge in environments:
                    env = edge.get("node", {})
                    if env.get("name") == self.environment_name:
                        self.railway_id = env.get("id")
                        logger.debug(f"Found environment: {self.environment_name} (ID: {self.railway_id})")
                        return env

                logger.debug(f"Environment {self.environment_name} not found in project")
                return None
            except Exception as e:
                logger.debug(f"Error finding environment: {e}")
                return None

        # If railway_id is set, fetch full environment details
        try:
            environment = railway_client.get_environment(self.railway_id)
            if environment:
                logger.debug(f"Found environment: {environment.get('name')}")
                return environment
            return None
        except Exception as e:
            logger.debug(f"Environment not found: {e}")
            return None

    def _create(self, railway_client: RailwayApiClient) -> bool:
        """Create environment in Railway."""
        mutation = """
        mutation environmentCreate($input: EnvironmentCreateInput!) {
          environmentCreate(input: $input) {
            id
            name
            projectId
            createdAt
            updatedAt
          }
        }
        """

        variables = {
            "input": {
                "projectId": self.project_id,
                "name": self.environment_name,
            }
        }

        try:
            result = railway_client.execute_mutation(mutation, variables)
            environment = result.get("environmentCreate", {})

            if environment and "id" in environment:
                self.railway_id = environment["id"]
                logger.info(f"Created environment: {self.environment_name} (ID: {self.railway_id})")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to create environment {self.environment_name}: {e}")
            return False

    def _update(self, railway_client: RailwayApiClient) -> bool:
        """Update environment in Railway."""
        if self.railway_id is None:
            logger.warning(f"Environment ID not set, cannot update")
            return False

        # Railway supports renaming environments
        mutation = """
        mutation environmentRename($environmentId: String!, $name: String!) {
          environmentRename(environmentId: $environmentId, name: $name)
        }
        """

        variables = {
            "environmentId": self.railway_id,
            "name": self.environment_name,
        }

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Renamed environment to: {self.environment_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to update environment: {e}")
            return False

    def _delete(self, railway_client: RailwayApiClient) -> bool:
        """Delete environment from Railway."""
        if self.railway_id is None:
            logger.warning(f"Environment ID not set, cannot delete")
            return False

        mutation = """
        mutation environmentDelete($id: String!) {
          environmentDelete(id: $id)
        }
        """

        variables = {"id": self.railway_id}

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Deleted environment: {self.environment_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete environment: {e}")
            return False
