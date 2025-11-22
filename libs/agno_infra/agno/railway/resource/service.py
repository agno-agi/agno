"""Railway Service resource."""

from typing import Any, Optional

from agno.railway.api_client import RailwayApiClient
from agno.railway.resource.base import RailwayResource
from agno.utilities.logging import logger


class RailwayService(RailwayResource):
    """Railway Service resource.

    A service represents an application deployment on Railway.
    It can be deployed from a Docker image or GitHub repository.
    """

    resource_type: str = "RailwayService"

    # Required fields
    project_id: str
    environment_id: str

    # Deployment source - Docker image
    source_image: Optional[str] = None  # e.g., "docker.io/nginx:alpine"

    # Deployment source - GitHub repository (Phase 3)
    source_repo: Optional[str] = None  # e.g., "username/repository"
    source_branch: Optional[str] = "main"
    dockerfile_path: Optional[str] = None
    root_directory: Optional[str] = None

    # Service configuration
    icon: Optional[str] = None

    def _read(self, railway_client: RailwayApiClient) -> Any:
        """Read service from Railway."""
        if self.railway_id is None:
            # Try to find service by name in the project
            try:
                query = """
                query project($id: String!) {
                  project(id: $id) {
                    id
                    services {
                      edges {
                        node {
                          id
                          name
                          icon
                        }
                      }
                    }
                  }
                }
                """
                result = railway_client.execute_query(query, {"id": self.project_id})
                project = result.get("project", {})
                services = project.get("services", {}).get("edges", [])

                for edge in services:
                    service = edge.get("node", {})
                    if service.get("name") == self.name:
                        self.railway_id = service.get("id")
                        logger.debug(f"Found service: {self.name} (ID: {self.railway_id})")
                        return service

                logger.debug(f"Service {self.name} not found in project")
                return None
            except Exception as e:
                logger.debug(f"Error finding service: {e}")
                return None

        # If railway_id is set, fetch full service details
        try:
            service = railway_client.get_service(self.railway_id)
            if service:
                logger.debug(f"Found service: {service.get('name')}")
                return service
            return None
        except Exception as e:
            logger.debug(f"Service not found: {e}")
            return None

    def _create(self, railway_client: RailwayApiClient) -> bool:
        """Create service in Railway."""
        mutation = """
        mutation serviceCreate($input: ServiceCreateInput!) {
          serviceCreate(input: $input) {
            id
            name
            icon
            projectId
            createdAt
            updatedAt
          }
        }
        """

        # Build service input
        service_input: dict[str, Any] = {
            "projectId": self.project_id,
            "name": self.name,
        }

        # Add source (Docker image or GitHub repo)
        if self.source_image:
            service_input["source"] = {"image": self.source_image}
        elif self.source_repo:
            service_input["source"] = {"repo": self.source_repo}
            if self.source_branch:
                service_input["branch"] = self.source_branch

        if self.icon:
            service_input["icon"] = self.icon

        variables = {"input": service_input}

        try:
            result = railway_client.execute_mutation(mutation, variables)
            service = result.get("serviceCreate", {})

            if service and "id" in service:
                self.railway_id = service["id"]
                logger.info(f"Created service: {self.name} (ID: {self.railway_id})")

                # Trigger deployment for this environment
                self._trigger_deployment(railway_client)

                return True
            return False
        except Exception as e:
            logger.error(f"Failed to create service {self.name}: {e}")
            return False

    def _trigger_deployment(self, railway_client: RailwayApiClient) -> bool:
        """Trigger a deployment for this service in the specified environment."""
        if self.railway_id is None:
            logger.warning("Service ID not set, cannot trigger deployment")
            return False

        mutation = """
        mutation serviceInstanceDeploy(
          $serviceId: String!
          $environmentId: String!
        ) {
          serviceInstanceDeploy(
            serviceId: $serviceId
            environmentId: $environmentId
          )
        }
        """

        variables = {
            "serviceId": self.railway_id,
            "environmentId": self.environment_id,
        }

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Triggered deployment for service: {self.name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to trigger deployment: {e}")
            return False

    def _update(self, railway_client: RailwayApiClient) -> bool:
        """Update service in Railway."""
        if self.railway_id is None:
            logger.warning("Service ID not set, cannot update")
            return False

        mutation = """
        mutation serviceUpdate($serviceId: String!, $input: ServiceUpdateInput!) {
          serviceUpdate(serviceId: $serviceId, input: $input) {
            id
            name
            icon
          }
        }
        """

        update_input: dict[str, Any] = {}
        if self.name:
            update_input["name"] = self.name
        if self.icon:
            update_input["icon"] = self.icon

        if not update_input:
            logger.debug("No updates to apply")
            return True

        variables = {
            "serviceId": self.railway_id,
            "input": update_input,
        }

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Updated service: {self.name}")

            # Re-trigger deployment after update
            self._trigger_deployment(railway_client)

            return True
        except Exception as e:
            logger.error(f"Failed to update service: {e}")
            return False

    def _delete(self, railway_client: RailwayApiClient) -> bool:
        """Delete service from Railway."""
        if self.railway_id is None:
            logger.warning("Service ID not set, cannot delete")
            return False

        mutation = """
        mutation serviceDelete($id: String!) {
          serviceDelete(id: $id)
        }
        """

        variables = {"id": self.railway_id}

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Deleted service: {self.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete service: {e}")
            return False
