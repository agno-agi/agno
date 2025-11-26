"""AgentOS Client for programmatic access to AgentOS API endpoints.

This module provides a full-featured client for interacting with remote AgentOS instances,
including discovery, configuration inspection, and execution operations.
"""

from os import getenv
from typing import Any, AsyncIterator, Dict, List, Optional, Union

from agno.os.schema import (
    AgentResponse,
    AgentSummaryResponse,
    ConfigResponse,
    Model,
    TeamResponse,
    TeamSummaryResponse,
    WorkflowResponse,
    WorkflowSummaryResponse,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.runner.os import AgentOSRunner

try:
    from httpx import AsyncClient, HTTPStatusError
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


class AgentOSClient:
    """Client for interacting with AgentOS API endpoints.

    Use AgentOSClient when you need management and discovery operations.
    Use AgentOSRunner directly when you only need execution operations.
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
        self._http_client: Optional[AsyncClient] = None

        # Cached runner instances for reuse
        self._agent_runners: Dict[str, AgentOSRunner] = {}
        self._team_runners: Dict[str, AgentOSRunner] = {}
        self._workflow_runners: Dict[str, AgentOSRunner] = {}

    async def __aenter__(self) -> "AgentOSClient":
        """Enter async context manager."""
        self._http_client = AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and cleanup resources."""
        await self.close()

    async def close(self) -> None:
        """Close HTTP client connections."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for requests."""
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _get(self, endpoint: str) -> Any:
        """Execute GET request.

        Args:
            endpoint: API endpoint path (without base URL)

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._http_client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _post(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Any:
        """Execute POST request.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Request body data

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._http_client.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()

    # Discovery & Configuration Operations

    async def get_config(self) -> ConfigResponse:
        """Get AgentOS configuration and metadata.

        Returns comprehensive OS configuration including:
        - OS metadata (id, description, version)
        - List of available agents
        - List of available teams
        - List of available workflows
        - Interface configurations
        - Knowledge, evals, and metrics settings

        Returns:
            ConfigResponse: Complete OS configuration

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._get("/config")
        return ConfigResponse(**data)

    async def get_models(self) -> List[Model]:
        """Get list of all models used by agents and teams.

        Returns:
            List[Model]: List of model configurations

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._get("/models")
        return [Model(**item) for item in data]

    # Agent Operations

    async def list_agents(self) -> List[AgentSummaryResponse]:
        """List all agents configured in the AgentOS instance.

        Returns summary information for each agent including:
        - Agent ID, name, description
        - Model configuration
        - Basic settings

        Returns:
            List[AgentSummaryResponse]: List of agent summaries

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._get("/agents")
        return [AgentSummaryResponse(**item) for item in data]

    async def get_agent(self, agent_id: str) -> AgentResponse:
        """Get detailed configuration for a specific agent.

        Args:
            agent_id: ID of the agent to retrieve

        Returns:
            AgentResponse: Detailed agent configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if agent not found)
        """
        data = await self._get(f"/agents/{agent_id}")
        return AgentResponse(**data)

    def agent(self, agent_id: str) -> AgentOSRunner:
        """Get or create an AgentOSRunner for the specified agent.

        Returns a cached runner instance if one exists, otherwise creates a new one.
        This is useful for reusing runners across multiple executions.

        Args:
            agent_id: ID of the agent

        Returns:
            AgentOSRunner: Runner instance for executing the agent
        """
        if agent_id not in self._agent_runners:
            self._agent_runners[agent_id] = AgentOSRunner(
                base_url=self.base_url,
                agent_id=agent_id,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._agent_runners[agent_id]

    async def run_agent(
        self,
        agent_id: str,
        input: Any,
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator]:
        """Execute an agent (convenience wrapper).

        This is a convenience method that creates a runner and executes it.
        For multiple executions of the same agent, prefer using agent() to get
        a runner instance and reuse it.

        Args:
            agent_id: ID of the agent to run
            input: Input message or data
            **kwargs: Additional arguments passed to AgentOSRunner.arun()

        Returns:
            RunOutput or AsyncIterator: Agent execution result

        Raises:
            HTTPStatusError: On HTTP errors
        """
        runner = self.agent(agent_id)
        return await runner.arun(input, **kwargs)

    # Team Operations

    async def list_teams(self) -> List[TeamSummaryResponse]:
        """List all teams configured in the AgentOS instance.

        Returns summary information for each team including:
        - Team ID, name, description
        - Model configuration
        - Member information

        Returns:
            List[TeamSummaryResponse]: List of team summaries

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._get("/teams")
        return [TeamSummaryResponse(**item) for item in data]

    async def get_team(self, team_id: str) -> TeamResponse:
        """Get detailed configuration for a specific team.

        Args:
            team_id: ID of the team to retrieve

        Returns:
            TeamResponse: Detailed team configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if team not found)
        """
        data = await self._get(f"/teams/{team_id}")
        return TeamResponse(**data)

    def team(self, team_id: str) -> AgentOSRunner:
        """Get or create an AgentOSRunner for the specified team.

        Returns a cached runner instance if one exists, otherwise creates a new one.

        Args:
            team_id: ID of the team

        Returns:
            AgentOSRunner: Runner instance for executing the team
        """
        if team_id not in self._team_runners:
            self._team_runners[team_id] = AgentOSRunner(
                base_url=self.base_url,
                team_id=team_id,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._team_runners[team_id]

    async def run_team(
        self,
        team_id: str,
        input: Any,
        **kwargs: Any,
    ) -> Union[TeamRunOutput, AsyncIterator]:
        """Execute a team (convenience wrapper).

        Args:
            team_id: ID of the team to run
            input: Input message or data
            **kwargs: Additional arguments passed to AgentOSRunner.arun()

        Returns:
            TeamRunOutput or AsyncIterator: Team execution result

        Raises:
            HTTPStatusError: On HTTP errors
        """
        runner = self.team(team_id)
        return await runner.arun(input, **kwargs)

    # Workflow Operations

    async def list_workflows(self) -> List[WorkflowSummaryResponse]:
        """List all workflows configured in the AgentOS instance.

        Returns summary information for each workflow including:
        - Workflow ID, name, description
        - Step information

        Returns:
            List[WorkflowSummaryResponse]: List of workflow summaries

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._get("/workflows")
        return [WorkflowSummaryResponse(**item) for item in data]

    async def get_workflow(self, workflow_id: str) -> WorkflowResponse:
        """Get detailed configuration for a specific workflow.

        Args:
            workflow_id: ID of the workflow to retrieve

        Returns:
            WorkflowResponse: Detailed workflow configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if workflow not found)
        """
        data = await self._get(f"/workflows/{workflow_id}")
        return WorkflowResponse(**data)

    def workflow(self, workflow_id: str) -> AgentOSRunner:
        """Get or create an AgentOSRunner for the specified workflow.

        Returns a cached runner instance if one exists, otherwise creates a new one.

        Args:
            workflow_id: ID of the workflow

        Returns:
            AgentOSRunner: Runner instance for executing the workflow
        """
        if workflow_id not in self._workflow_runners:
            self._workflow_runners[workflow_id] = AgentOSRunner(
                base_url=self.base_url,
                workflow_id=workflow_id,
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._workflow_runners[workflow_id]

    async def run_workflow(
        self,
        workflow_id: str,
        input: Any,
        **kwargs: Any,
    ) -> Union[WorkflowRunOutput, AsyncIterator]:
        """Execute a workflow (convenience wrapper).

        Args:
            workflow_id: ID of the workflow to run
            input: Input message or data
            **kwargs: Additional arguments passed to AgentOSRunner.arun()

        Returns:
            WorkflowRunOutput or AsyncIterator: Workflow execution result

        Raises:
            HTTPStatusError: On HTTP errors
        """
        runner = self.workflow(workflow_id)
        return await runner.arun(input, **kwargs)
