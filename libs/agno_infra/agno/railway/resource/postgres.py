"""Railway PostgreSQL database resource."""

from typing import Any, Optional

from agno.railway.api_client import RailwayApiClient
from agno.railway.resource.base import RailwayResource
from agno.utilities.logging import logger


class RailwayPostgres(RailwayResource):
    """Railway PostgreSQL database service.

    Deploys a PostgreSQL database as a Railway service.
    The database will automatically create connection environment variables:
    - DATABASE_URL (full connection string)
    - PGHOST
    - PGPORT
    - PGUSER
    - PGPASSWORD
    - PGDATABASE
    """

    resource_type: str = "RailwayPostgres"

    # Required fields (set by RailwayResources orchestrator)
    project_id: Optional[str] = None
    environment_id: Optional[str] = None

    # PostgreSQL configuration
    postgres_version: str = "16"  # PostgreSQL version
    database_name: Optional[str] = None  # Database name (defaults to 'railway')
    postgres_user: Optional[str] = None  # Database user (defaults to 'postgres')
    postgres_password: Optional[str] = None  # Auto-generated if not provided

    # Service configuration
    icon: Optional[str] = "\U0001f418"  # 🐘 Elephant emoji for PostgreSQL

    def _read(self, railway_client: RailwayApiClient) -> Any:
        """Read PostgreSQL service from Railway."""
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
                        logger.debug(f"Found PostgreSQL service: {self.name} (ID: {self.railway_id})")
                        return service

                logger.debug(f"PostgreSQL service {self.name} not found in project")
                return None
            except Exception as e:
                logger.debug(f"Error finding PostgreSQL service: {e}")
                return None

        # If railway_id is set, fetch full service details
        try:
            service = railway_client.get_service(self.railway_id)
            if service:
                logger.debug(f"Found PostgreSQL service: {service.get('name')}")
                return service
            return None
        except Exception as e:
            logger.debug(f"PostgreSQL service not found: {e}")
            return None

    def _create(self, railway_client: RailwayApiClient) -> bool:
        """Create PostgreSQL service in Railway."""
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

        # Build service input with PostgreSQL Docker image
        service_input: dict[str, Any] = {
            "projectId": self.project_id,
            "name": self.name,
            "source": {
                "image": f"postgres:{self.postgres_version}"
            },
        }

        if self.icon:
            service_input["icon"] = self.icon

        variables = {"input": service_input}

        try:
            result = railway_client.execute_mutation(mutation, variables)
            service = result.get("serviceCreate", {})

            if service and "id" in service:
                self.railway_id = service["id"]
                logger.info(f"Created PostgreSQL service: {self.name} (ID: {self.railway_id})")

                # Set up PostgreSQL environment variables
                self._setup_postgres_variables(railway_client)

                # Trigger deployment
                self._trigger_deployment(railway_client)

                return True
            return False
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL service {self.name}: {e}")
            return False

    def _setup_postgres_variables(self, railway_client: RailwayApiClient) -> bool:
        """Set up PostgreSQL environment variables."""
        if self.railway_id is None:
            logger.warning("Service ID not set, cannot setup variables")
            return False

        mutation = """
        mutation variableUpsert($input: VariableUpsertInput!) {
          variableUpsert(input: $input)
        }
        """

        # Generate secure password if not provided
        if not self.postgres_password:
            import secrets
            import string
            # Generate 32-character random password
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
            self.postgres_password = "".join(secrets.choice(alphabet) for _ in range(32))
            logger.debug("Generated secure random password for PostgreSQL")

        # PostgreSQL default configuration
        variables_to_set = {
            "POSTGRES_DB": self.database_name or "railway",
            "POSTGRES_USER": self.postgres_user or "postgres",
            "POSTGRES_PASSWORD": self.postgres_password,  # Always required
        }

        # Create variables
        for key, value in variables_to_set.items():
            try:
                variable_input = {
                    "projectId": self.project_id,
                    "environmentId": self.environment_id,
                    "serviceId": self.railway_id,
                    "name": key,
                    "value": value,
                }
                railway_client.execute_mutation(mutation, {"input": variable_input})
                logger.debug(f"Set PostgreSQL variable: {key}")
            except Exception as e:
                logger.warning(f"Failed to set variable {key}: {e}")

        return True

    def _trigger_deployment(self, railway_client: RailwayApiClient) -> bool:
        """Trigger a deployment for the PostgreSQL service."""
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
            logger.info(f"Triggered deployment for PostgreSQL service: {self.name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to trigger PostgreSQL deployment: {e}")
            return False

    def _update(self, railway_client: RailwayApiClient) -> bool:
        """Update PostgreSQL service in Railway.

        Note: PostgreSQL version changes require redeployment.
        Variable updates are handled separately via RailwayVariable resources.
        """
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
            logger.debug("No updates to apply to PostgreSQL service")
            return True

        variables = {
            "serviceId": self.railway_id,
            "input": update_input,
        }

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Updated PostgreSQL service: {self.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to update PostgreSQL service: {e}")
            return False

    def _delete(self, railway_client: RailwayApiClient) -> bool:
        """Delete PostgreSQL service from Railway.

        WARNING: This will permanently delete the database and all its data.
        """
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
            logger.info(f"Deleted PostgreSQL service: {self.name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete PostgreSQL service: {e}")
            return False

    def get_connection_string_reference(self) -> str:
        """Get Railway variable reference for DATABASE_URL.

        Returns a Railway variable reference that can be used in other services:
        Example: "${{Postgres.DATABASE_URL}}"

        Note: Railway automatically creates DATABASE_URL for PostgreSQL services.
        """
        return f"${{{{{self.name}.DATABASE_URL}}}}"

    def get_connection_vars_reference(self) -> dict[str, str]:
        """Get Railway variable references for all PostgreSQL connection variables.

        Returns:
            Dictionary of environment variable names to Railway variable references
        """
        return {
            "DATABASE_URL": f"${{{{{self.name}.DATABASE_URL}}}}",
            "PGHOST": f"${{{{{self.name}.PGHOST}}}}",
            "PGPORT": f"${{{{{self.name}.PGPORT}}}}",
            "PGUSER": f"${{{{{self.name}.PGUSER}}}}",
            "PGPASSWORD": f"${{{{{self.name}.PGPASSWORD}}}}",
            "PGDATABASE": f"${{{{{self.name}.PGDATABASE}}}}",
        }
