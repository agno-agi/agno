"""AgentOS Client for programmatic access to AgentOS API endpoints.

This module provides a client with both sync and async methods for interacting with
remote AgentOS instances, including discovery, configuration inspection, and execution operations.
"""

from os import getenv
from typing import Any, Dict, List, Optional

from agno.schema.os.os import (
    AgentResponse,
    AgentSummaryResponse,
    ConfigResponse,
    Model,
    TeamResponse,
    TeamSummaryResponse,
    WorkflowResponse,
    WorkflowSummaryResponse,
)

try:
    from httpx import AsyncClient, Client
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


class AgentOSClient:
    """Client for interacting with AgentOS API endpoints.

    Supports both sync and async usage patterns.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 300.0,
    ):
        """Initialize AgentOSClient.

        Args:
            base_url: Base URL of the AgentOS instance (e.g., "http://localhost:7777")
            api_key: API key for authentication. Defaults to AGNO_API_KEY environment variable
            timeout: Request timeout in seconds (default: 300)
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or getenv("AGNO_API_KEY")
        self.timeout = timeout
        self._sync_client: Optional[Client] = None
        self._async_client: Optional[AsyncClient] = None

    # Sync context manager
    def __enter__(self) -> "AgentOSClient":
        """Enter sync context manager."""
        self._sync_client = Client(timeout=self.timeout)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit sync context manager and cleanup resources."""
        self.close()

    # Async context manager
    async def __aenter__(self) -> "AgentOSClient":
        """Enter async context manager."""
        self._async_client = AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and cleanup resources."""
        await self.aclose()

    def close(self) -> None:
        """Close sync HTTP client connections."""
        if self._sync_client:
            self._sync_client.close()
            self._sync_client = None

    async def aclose(self) -> None:
        """Close async HTTP client connections."""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for requests."""
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # Sync HTTP methods
    def _get(self, endpoint: str) -> Any:
        """Execute sync GET request.

        Args:
            endpoint: API endpoint path (without base URL)

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._sync_client:
            self._sync_client = Client(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = self._sync_client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    def _post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Any:
        """Execute sync POST request.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Request body data

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._sync_client:
            self._sync_client = Client(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = self._sync_client.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()

    # Async HTTP methods
    async def _aget(self, endpoint: str) -> Any:
        """Execute async GET request.

        Args:
            endpoint: API endpoint path (without base URL)

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._async_client:
            self._async_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._async_client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _apost(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Any:
        """Execute async POST request.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Request body data

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._async_client:
            self._async_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._async_client.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()

    # =========================================================================
    # Sync API Methods
    # =========================================================================

    def get_config(self) -> ConfigResponse:
        """Get AgentOS configuration and metadata (sync).

        Returns:
            ConfigResponse: Complete OS configuration
        """
        data = self._get("/config")
        return ConfigResponse(**data)

    def get_models(self) -> List[Model]:
        """Get list of all models used by agents and teams (sync).

        Returns:
            List[Model]: List of model configurations
        """
        data = self._get("/models")
        return [Model(**item) for item in data]

    async def list_agents(self) -> List[AgentSummaryResponse]:
        """List all agents configured in the AgentOS instance (sync).

        Returns:
            List[AgentSummaryResponse]: List of agent summaries
        """
        data = await self._aget("/agents")
        return [AgentSummaryResponse(**item) for item in data]

    async def get_agent(self, agent_id: str) -> AgentResponse:
        """Get detailed configuration for a specific agent (sync).

        Args:
            agent_id: ID of the agent to retrieve

        Returns:
            AgentResponse: Detailed agent configuration
        """
        data = await self._aget(f"/agents/{agent_id}")
        return AgentResponse(**data)

    async def list_teams(self) -> List[TeamSummaryResponse]:
        """List all teams configured in the AgentOS instance (sync).

        Returns:
            List[TeamSummaryResponse]: List of team summaries
        """
        data = await self._aget("/teams")
        return [TeamSummaryResponse(**item) for item in data]

    async def get_team(self, team_id: str) -> TeamResponse:
        """Get detailed configuration for a specific team (sync).

        Args:
            team_id: ID of the team to retrieve

        Returns:
            TeamResponse: Detailed team configuration
        """
        data = await self._aget(f"/teams/{team_id}")
        return TeamResponse(**data)

    async def list_workflows(self) -> List[WorkflowSummaryResponse]:
        """List all workflows configured in the AgentOS instance (sync).

        Returns:
            List[WorkflowSummaryResponse]: List of workflow summaries
        """
        data = await self._aget("/workflows")
        return [WorkflowSummaryResponse(**item) for item in data]

    async def get_workflow(self, workflow_id: str) -> WorkflowResponse:
        """Get detailed configuration for a specific workflow (sync).

        Args:
            workflow_id: ID of the workflow to retrieve

        Returns:
            WorkflowResponse: Detailed workflow configuration
        """
        data = await self._aget(f"/workflows/{workflow_id}")
        return WorkflowResponse(**data)
