"""Railway Variable resource."""

from typing import Any, Optional

from agno.railway.api_client import RailwayApiClient
from agno.railway.resource.base import RailwayResource
from agno.utilities.logging import logger


class RailwayVariable(RailwayResource):
    """Railway Environment Variable resource.

    Variables are scoped to a project and environment.
    They are available to all services in that environment.
    """

    resource_type: str = "RailwayVariable"

    # Required fields
    project_id: str
    environment_id: str
    variable_name: str
    variable_value: str

    def _read(self, railway_client: RailwayApiClient) -> Any:
        """Read variable from Railway.

        Note: Railway returns all variables for an environment,
        so we query the environment and check for our variable.
        """
        try:
            query = """
            query environment($id: String!) {
              environment(id: $id) {
                id
                name
                variables
              }
            }
            """
            result = railway_client.execute_query(query, {"id": self.environment_id})
            environment = result.get("environment", {})
            variables = environment.get("variables", {})

            if self.variable_name in variables:
                logger.debug(f"Found variable: {self.variable_name}")
                return {
                    "name": self.variable_name,
                    "value": variables[self.variable_name],
                }
            else:
                logger.debug(f"Variable {self.variable_name} not found")
                return None
        except Exception as e:
            logger.debug(f"Error reading variable: {e}")
            return None

    def _create(self, railway_client: RailwayApiClient) -> bool:
        """Create or update variable in Railway.

        Railway uses upsert semantics - variableUpsert creates or updates.
        """
        mutation = """
        mutation variableUpsert($input: VariableUpsertInput!) {
          variableUpsert(input: $input)
        }
        """

        variables = {
            "input": {
                "projectId": self.project_id,
                "environmentId": self.environment_id,
                "name": self.variable_name,
                "value": self.variable_value,
            }
        }

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Set variable: {self.variable_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set variable {self.variable_name}: {e}")
            return False

    def _update(self, railway_client: RailwayApiClient) -> bool:
        """Update variable in Railway.

        Since Railway uses upsert, update is the same as create.
        """
        return self._create(railway_client)

    def _delete(self, railway_client: RailwayApiClient) -> bool:
        """Delete variable from Railway."""
        mutation = """
        mutation variableDelete($input: VariableDeleteInput!) {
          variableDelete(input: $input)
        }
        """

        variables = {
            "input": {
                "projectId": self.project_id,
                "environmentId": self.environment_id,
                "name": self.variable_name,
            }
        }

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Deleted variable: {self.variable_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete variable {self.variable_name}: {e}")
            return False


class RailwayVariableCollection(RailwayResource):
    """Railway Variable Collection for bulk operations.

    This resource allows setting multiple variables at once,
    which is more efficient than individual upserts.
    """

    resource_type: str = "RailwayVariableCollection"

    # Required fields
    project_id: str
    environment_id: str
    variables: dict[str, str]  # Dictionary of name: value pairs

    def _read(self, railway_client: RailwayApiClient) -> Any:
        """Read all variables for the environment."""
        try:
            query = """
            query environment($id: String!) {
              environment(id: $id) {
                id
                name
                variables
              }
            }
            """
            result = railway_client.execute_query(query, {"id": self.environment_id})
            environment = result.get("environment", {})
            return environment.get("variables", {})
        except Exception as e:
            logger.debug(f"Error reading variables: {e}")
            return None

    def _create(self, railway_client: RailwayApiClient) -> bool:
        """Create or update multiple variables in Railway."""
        mutation = """
        mutation variableCollectionUpsert($input: VariableCollectionUpsertInput!) {
          variableCollectionUpsert(input: $input)
        }
        """

        variables = {
            "input": {
                "projectId": self.project_id,
                "environmentId": self.environment_id,
                "variables": self.variables,
            }
        }

        try:
            railway_client.execute_mutation(mutation, variables)
            logger.info(f"Set {len(self.variables)} variables")
            return True
        except Exception as e:
            logger.error(f"Failed to set variables: {e}")
            return False

    def _update(self, railway_client: RailwayApiClient) -> bool:
        """Update multiple variables (same as create for upsert)."""
        return self._create(railway_client)

    def _delete(self, railway_client: RailwayApiClient) -> bool:
        """Delete multiple variables from Railway."""
        # Railway doesn't have bulk delete, so delete one by one
        success = True
        for variable_name in self.variables.keys():
            mutation = """
            mutation variableDelete($input: VariableDeleteInput!) {
              variableDelete(input: $input)
            }
            """

            variables = {
                "input": {
                    "projectId": self.project_id,
                    "environmentId": self.environment_id,
                    "name": variable_name,
                }
            }

            try:
                railway_client.execute_mutation(mutation, variables)
                logger.debug(f"Deleted variable: {variable_name}")
            except Exception as e:
                logger.error(f"Failed to delete variable {variable_name}: {e}")
                success = False

        if success:
            logger.info(f"Deleted {len(self.variables)} variables")
        return success
