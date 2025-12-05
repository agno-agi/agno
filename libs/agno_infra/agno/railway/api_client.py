"""Railway GraphQL API client."""

import os
import time
from typing import Any, Dict, List, Optional

import httpx

from agno.utils.log import logger


class RailwayApiClient:
    """Client for Railway GraphQL API.

    Provides methods to execute GraphQL queries and mutations against
    Railway's v2 GraphQL endpoint.
    """

    def __init__(
        self,
        api_token: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        """Initialize Railway API client.

        Args:
            api_token: Railway API token. If not provided, reads from RAILWAY_API_TOKEN env var.
            api_url: Railway API endpoint URL. Defaults to production endpoint.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts for failed requests.
        """
        self.api_token = api_token or os.getenv("RAILWAY_API_TOKEN")
        if not self.api_token:
            raise ValueError("Railway API token is required. Set RAILWAY_API_TOKEN environment variable.")

        self.api_url = api_url or "https://backboard.railway.com/graphql/v2"
        self.timeout = timeout
        self.max_retries = max_retries

        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def execute(
        self,
        query: str,
        variables: Optional[Dict[str, Any]] = None,
        operation_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a GraphQL query or mutation.

        Args:
            query: GraphQL query or mutation string.
            variables: Optional variables for the query.
            operation_name: Optional operation name for the query.

        Returns:
            GraphQL response data.

        Raises:
            Exception: If the request fails after all retries.
        """
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        if operation_name:
            payload["operationName"] = operation_name

        last_exception = None
        for attempt in range(self.max_retries):
            try:
                response = httpx.post(
                    self.api_url,
                    headers=self.headers,
                    json=payload,
                    timeout=self.timeout,
                )

                # Check HTTP status
                if response.status_code == 429:
                    # Rate limited - wait and retry
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Rate limited. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()

                # Parse response
                data = response.json()

                # Check for GraphQL errors
                if "errors" in data:
                    errors = data["errors"]
                    error_messages = [e.get("message", str(e)) for e in errors]
                    raise Exception(f"GraphQL errors: {', '.join(error_messages)}")

                return data.get("data", {})

            except httpx.HTTPStatusError as e:
                last_exception = e
                if e.response.status_code == 401:
                    raise Exception("Authentication failed. Check your Railway API token.")
                elif e.response.status_code == 403:
                    raise Exception("Permission denied. Check your Railway API token permissions.")
                elif e.response.status_code >= 500:
                    # Server error - retry
                    wait_time = 2 ** attempt
                    logger.warning(f"Server error ({e.response.status_code}). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise Exception(f"HTTP error {e.response.status_code}: {e.response.text}")

            except httpx.TimeoutException as e:
                last_exception = e
                wait_time = 2 ** attempt
                logger.warning(f"Request timeout. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

            except httpx.RequestError as e:
                last_exception = e
                wait_time = 2 ** attempt
                logger.warning(f"Request error: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue

        # All retries failed
        raise Exception(f"Request failed after {self.max_retries} attempts: {last_exception}")

    def execute_query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a GraphQL query.

        Args:
            query: GraphQL query string.
            variables: Optional variables for the query.

        Returns:
            Query response data.
        """
        return self.execute(query, variables)

    def execute_mutation(self, mutation: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a GraphQL mutation.

        Args:
            mutation: GraphQL mutation string.
            variables: Optional variables for the mutation.

        Returns:
            Mutation response data.
        """
        return self.execute(mutation, variables)

    # Convenience methods for common queries

    def get_me(self) -> Dict[str, Any]:
        """Get current authenticated user."""
        query = """
        query {
          me {
            id
            name
            email
            avatar
          }
        }
        """
        result = self.execute_query(query)
        return result.get("me", {})

    def get_user_workspaces(self) -> List[Dict[str, Any]]:
        """Get all workspaces (teams) the user has access to.

        Returns:
            List of workspaces with id and name
        """
        query = """
        query {
          me {
            teams {
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
        result = self.execute_query(query)
        me = result.get("me", {})
        teams = me.get("teams", {}).get("edges", [])

        workspaces = []
        for edge in teams:
            node = edge.get("node", {})
            if node.get("id") and node.get("name"):
                workspaces.append({
                    "id": node["id"],
                    "name": node["name"],
                })

        return workspaces

    def get_project(self, project_id: str) -> Dict[str, Any]:
        """Get project details."""
        query = """
        query project($id: String!) {
          project(id: $id) {
            id
            name
            description
            createdAt
            updatedAt
            baseEnvironmentId
          }
        }
        """
        result = self.execute_query(query, {"id": project_id})
        return result.get("project", {})

    def get_environment(self, environment_id: str) -> Dict[str, Any]:
        """Get environment details."""
        query = """
        query environment($id: String!) {
          environment(id: $id) {
            id
            name
            projectId
            createdAt
            updatedAt
          }
        }
        """
        result = self.execute_query(query, {"id": environment_id})
        return result.get("environment", {})

    def get_service(self, service_id: str) -> Dict[str, Any]:
        """Get service details."""
        query = """
        query service($id: String!) {
          service(id: $id) {
            id
            name
            icon
            projectId
            createdAt
            updatedAt
          }
        }
        """
        result = self.execute_query(query, {"id": service_id})
        return result.get("service", {})

    def get_deployment(self, deployment_id: str) -> Dict[str, Any]:
        """Get deployment details."""
        query = """
        query deployment($id: String!) {
          deployment(id: $id) {
            id
            status
            createdAt
            updatedAt
            url
            staticUrl
            canRedeploy
            canRollback
          }
        }
        """
        result = self.execute_query(query, {"id": deployment_id})
        return result.get("deployment", {})
