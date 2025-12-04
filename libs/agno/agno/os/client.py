"""
AgentOS Client for programmatic access to AgentOS API endpoints.

AgentOSClient provides a comprehensive async client for interacting with
remote AgentOS instances. It supports all major operations including:

- **Discovery**: Get configuration, list agents/teams/workflows
- **Runs**: Execute agent/team/workflow runs with streaming support
- **Sessions**: Manage conversation sessions and history
- **Memory**: Create, read, update, delete user memories
- **Knowledge**: Search and manage knowledge base content
- **Evals**: Run and manage evaluations

Example:
    ```python
    import asyncio
    from agno.os.client import AgentOSClient

    async def main():
        async with AgentOSClient(base_url="http://localhost:7777") as client:
            # Discover available agents
            config = await client.get_config()
            print(f"Agents: {[a.id for a in config.agents]}")

            # Run an agent
            result = await client.run_agent(
                agent_id="assistant",
                message="Hello!",
            )
            print(f"Response: {result.content}")

    asyncio.run(main())
    ```
"""

from os import getenv
from typing import Any, AsyncIterator, Dict, List, Optional, Union

__all__ = ["AgentOSClient"]

from agno.db.base import SessionType
from agno.db.schemas.evals import EvalFilterType, EvalType
from agno.os.routers.evals.schemas import EvalSchema
from agno.os.routers.knowledge.schemas import (
    ConfigResponseSchema as KnowledgeConfigResponse,
    ContentResponseSchema,
    ContentStatusResponse,
    VectorSearchResult,
)
from agno.os.routers.memory.schemas import (
    UserMemoryCreateSchema,
    UserMemorySchema,
    UserStatsSchema,
)
from agno.os.schema import (
    AgentResponse,
    AgentSessionDetailSchema,
    AgentSummaryResponse,
    ConfigResponse,
    CreateSessionRequest,
    DeleteSessionRequest,
    Model,
    PaginatedResponse,
    RunSchema,
    SessionSchema,
    TeamResponse,
    TeamRunSchema,
    TeamSessionDetailSchema,
    TeamSummaryResponse,
    UpdateSessionRequest,
    WorkflowResponse,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
    WorkflowSummaryResponse,
)
try:
    from httpx import AsyncClient, HTTPStatusError
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


class AgentOSClient:
    """Async client for interacting with AgentOS API endpoints.

    AgentOSClient provides programmatic access to all AgentOS operations,
    including agent execution, session management, memory operations,
    knowledge search, and evaluations.

    The client uses httpx for async HTTP operations and supports both
    context manager and manual connection management patterns.

    Attributes:
        base_url: Base URL of the AgentOS instance
        api_key: API key for authentication (optional)
        timeout: Request timeout in seconds

    Example:
        Using context manager (recommended):

        ```python
        async with AgentOSClient(base_url="http://localhost:7777") as client:
            result = await client.run_agent(agent_id="assistant", message="Hello")
        ```

        Manual connection management:

        ```python
        client = AgentOSClient(base_url="http://localhost:7777")
        await client.connect()
        try:
            result = await client.run_agent(agent_id="assistant", message="Hello")
        finally:
            await client.close()
        ```
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

    async def __aenter__(self) -> "AgentOSClient":
        """Enter async context manager."""
        self._http_client = AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit async context manager and cleanup resources."""
        await self.close()

    async def connect(self) -> "AgentOSClient":
        """Explicitly create HTTP client connection.
        
        Use this when you need to manage the client lifecycle manually
        without using the async context manager.
        
        Returns:
            AgentOSClient: self for method chaining
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)
        return self

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

    async def _post_form_data(self, endpoint: str, data: Dict[str, Any]) -> Any:
        """Execute POST request with form data (for runs endpoints).

        Args:
            endpoint: API endpoint path (without base URL)
            data: Form data dictionary

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._http_client.post(url, data=data, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _stream_post_form_data(
        self, endpoint: str, data: Dict[str, Any]
    ) -> AsyncIterator[str]:
        """Stream POST request with form data.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Form data dictionary

        Yields:
            str: Lines from the streaming response
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        async with self._http_client.stream("POST", url, data=data, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                yield line

    async def _post_empty(self, endpoint: str) -> bool:
        """Execute POST request with no body (for cancel endpoints).

        Args:
            endpoint: API endpoint path (without base URL)

        Returns:
            bool: True if successful
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        async with self._http_client.stream("POST", url, headers=headers) as response:
            response.raise_for_status()
            return True

    async def _patch(self, endpoint: str, data: Optional[Dict[str, Any]] = None) -> Any:
        """Execute PATCH request.

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

        response = await self._http_client.patch(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _delete(self, endpoint: str) -> None:
        """Execute DELETE request.

        Args:
            endpoint: API endpoint path (without base URL)

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._http_client.delete(url, headers=headers)
        response.raise_for_status()

    async def _delete_with_body(self, endpoint: str, data: Dict[str, Any]) -> None:
        """Execute DELETE request with JSON body.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Request body data

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._http_client.request("DELETE", url, json=data, headers=headers)
        response.raise_for_status()

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
        return ConfigResponse.model_validate(data)

    async def get_models(self) -> List[Model]:
        """Get list of all models used by agents and teams.

        Returns:
            List[Model]: List of model configurations

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._get("/models")
        return [Model.model_validate(item) for item in data]

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
        return [AgentSummaryResponse.model_validate(item) for item in data]

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
        return AgentResponse.model_validate(data)

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
        return [TeamSummaryResponse.model_validate(item) for item in data]

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
        return TeamResponse.model_validate(data)

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
        return [WorkflowSummaryResponse.model_validate(item) for item in data]

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
        return WorkflowResponse.model_validate(data)

    # Memory Operations

    async def create_memory(
        self,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> UserMemorySchema:
        """Create a new user memory.

        Args:
            memory: The memory content to store
            user_id: User ID to associate with the memory
            topics: Optional list of topics to categorize the memory
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            UserMemorySchema: The created memory

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/memories"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload: Dict[str, Any] = {"memory": memory, "user_id": user_id}
        if topics:
            payload["topics"] = topics

        data = await self._post(endpoint, payload)
        return UserMemorySchema.model_validate(data)

    async def get_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> UserMemorySchema:
        """Get a specific memory by ID.

        Args:
            memory_id: ID of the memory to retrieve
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            UserMemorySchema: The requested memory

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params = {}
        if user_id:
            params["user_id"] = user_id
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/memories/{memory_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)
        return UserMemorySchema.model_validate(data)

    async def list_memories(
        self,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> PaginatedResponse[UserMemorySchema]:
        """List user memories with filtering and pagination.

        Args:
            user_id: Filter by user ID
            agent_id: Filter by agent ID
            team_id: Filter by team ID
            topics: Filter by topics
            search_content: Search within memory content
            limit: Number of memories per page
            page: Page number
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            PaginatedResponse[UserMemorySchema]: Paginated list of memories

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {
            "limit": str(limit),
            "page": str(page),
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if user_id:
            params["user_id"] = user_id
        if agent_id:
            params["agent_id"] = agent_id
        if team_id:
            params["team_id"] = team_id
        if topics:
            params["topics"] = ",".join(topics)
        if search_content:
            params["search_content"] = search_content
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/memories?" + "&".join(f"{k}={v}" for k, v in params.items())
        data = await self._get(endpoint)
        return PaginatedResponse[UserMemorySchema].model_validate(data)

    async def update_memory(
        self,
        memory_id: str,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> UserMemorySchema:
        """Update an existing memory.

        Args:
            memory_id: ID of the memory to update
            memory: New memory content
            user_id: User ID associated with the memory
            topics: Optional new list of topics
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            UserMemorySchema: The updated memory

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/memories/{memory_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload: Dict[str, Any] = {"memory": memory, "user_id": user_id}
        if topics:
            payload["topics"] = topics

        data = await self._patch(endpoint, payload)
        return UserMemorySchema.model_validate(data)

    async def delete_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> None:
        """Delete a specific memory.

        Args:
            memory_id: ID of the memory to delete
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if user_id:
            params["user_id"] = user_id
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/memories/{memory_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        await self._delete(endpoint)

    async def delete_memories(
        self,
        memory_ids: List[str],
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> None:
        """Delete multiple memories.

        Args:
            memory_ids: List of memory IDs to delete
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/memories"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload: Dict[str, Any] = {"memory_ids": memory_ids}
        if user_id:
            payload["user_id"] = user_id

        await self._delete_with_body(endpoint, payload)

    async def get_memory_topics(
        self,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> List[str]:
        """Get all unique memory topics.

        Args:
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            List[str]: List of unique topic names

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/memory_topics"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        return await self._get(endpoint)

    async def get_user_memory_stats(
        self,
        limit: int = 20,
        page: int = 1,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> PaginatedResponse[UserStatsSchema]:
        """Get user memory statistics.

        Args:
            limit: Number of stats per page
            page: Page number
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            PaginatedResponse[UserStatsSchema]: Paginated user statistics

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {"limit": str(limit), "page": str(page)}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/user_memory_stats?" + "&".join(f"{k}={v}" for k, v in params.items())
        data = await self._get(endpoint)
        return PaginatedResponse[UserStatsSchema].model_validate(data)

    # Session Operations

    async def list_sessions(
        self,
        session_type: SessionType = SessionType.AGENT,
        component_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> PaginatedResponse[SessionSchema]:
        """List sessions with filtering and pagination.

        Args:
            session_type: Type of sessions to retrieve (agent, team, or workflow)
            component_id: Filter by component ID (agent/team/workflow ID)
            user_id: Filter by user ID
            session_name: Filter by session name (partial match)
            limit: Number of sessions per page
            page: Page number
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            PaginatedResponse[SessionSchema]: Paginated list of sessions

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {
            "type": session_type.value,
            "limit": str(limit),
            "page": str(page),
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if component_id:
            params["component_id"] = component_id
        if user_id:
            params["user_id"] = user_id
        if session_name:
            params["session_name"] = session_name
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/sessions?" + "&".join(f"{k}={v}" for k, v in params.items())
        data = await self._get(endpoint)
        return PaginatedResponse[SessionSchema].model_validate(data)

    async def create_session(
        self,
        session_type: SessionType = SessionType.AGENT,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        """Create a new session.

        Args:
            session_type: Type of session to create (agent, team, or workflow)
            session_id: Optional session ID (auto-generated if not provided)
            user_id: User ID to associate with the session
            session_name: Optional session name
            session_state: Optional initial session state
            metadata: Optional session metadata
            agent_id: Agent ID (for agent sessions)
            team_id: Team ID (for team sessions)
            workflow_id: Workflow ID (for workflow sessions)
            db_id: Optional database ID to use

        Returns:
            AgentSessionDetailSchema, TeamSessionDetailSchema, or WorkflowSessionDetailSchema

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {"type": session_type.value}
        if db_id:
            params["db_id"] = db_id

        endpoint = "/sessions"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload: Dict[str, Any] = {}
        if session_id:
            payload["session_id"] = session_id
        if user_id:
            payload["user_id"] = user_id
        if session_name:
            payload["session_name"] = session_name
        if session_state:
            payload["session_state"] = session_state
        if metadata:
            payload["metadata"] = metadata
        if agent_id:
            payload["agent_id"] = agent_id
        if team_id:
            payload["team_id"] = team_id
        if workflow_id:
            payload["workflow_id"] = workflow_id

        data = await self._post(endpoint, payload)

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.model_validate(data)
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.model_validate(data)
        else:
            return WorkflowSessionDetailSchema.model_validate(data)

    async def get_session(
        self,
        session_id: str,
        session_type: SessionType = SessionType.AGENT,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        """Get a specific session by ID.

        Args:
            session_id: ID of the session to retrieve
            session_type: Type of session (agent, team, or workflow)
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            AgentSessionDetailSchema, TeamSessionDetailSchema, or WorkflowSessionDetailSchema

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params: Dict[str, str] = {"type": session_type.value}
        if user_id:
            params["user_id"] = user_id
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/sessions/{session_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.model_validate(data)
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.model_validate(data)
        else:
            return WorkflowSessionDetailSchema.model_validate(data)

    async def get_session_runs(
        self,
        session_id: str,
        session_type: SessionType = SessionType.AGENT,
        user_id: Optional[str] = None,
        created_after: Optional[int] = None,
        created_before: Optional[int] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> List[Union[RunSchema, TeamRunSchema, WorkflowRunSchema]]:
        """Get all runs for a specific session.

        Args:
            session_id: ID of the session
            session_type: Type of session (agent, team, or workflow)
            user_id: Optional user ID filter
            created_after: Filter runs created after this Unix timestamp
            created_before: Filter runs created before this Unix timestamp
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            List of runs (RunSchema, TeamRunSchema, or WorkflowRunSchema)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {"type": session_type.value}
        if user_id:
            params["user_id"] = user_id
        if created_after:
            params["created_after"] = str(created_after)
        if created_before:
            params["created_before"] = str(created_before)
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/sessions/{session_id}/runs"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)

        # Parse runs based on session type and run content
        runs: List[Union[RunSchema, TeamRunSchema, WorkflowRunSchema]] = []
        for run in data:
            if run.get("workflow_id") is not None:
                runs.append(WorkflowRunSchema.model_validate(run))
            elif run.get("team_id") is not None:
                runs.append(TeamRunSchema.model_validate(run))
            else:
                runs.append(RunSchema.model_validate(run))
        return runs

    async def get_session_run(
        self,
        session_id: str,
        run_id: str,
        session_type: SessionType = SessionType.AGENT,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> Union[RunSchema, TeamRunSchema, WorkflowRunSchema]:
        """Get a specific run from a session.

        Args:
            session_id: ID of the session
            run_id: ID of the run to retrieve
            session_type: Type of session (agent, team, or workflow)
            user_id: Optional user ID filter
            db_id: Optional database ID to use

        Returns:
            RunSchema, TeamRunSchema, or WorkflowRunSchema

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params: Dict[str, str] = {"type": session_type.value}
        if user_id:
            params["user_id"] = user_id
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/sessions/{session_id}/runs/{run_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)

        # Return appropriate schema based on run type
        if data.get("workflow_id") is not None:
            return WorkflowRunSchema.model_validate(data)
        elif data.get("team_id") is not None:
            return TeamRunSchema.model_validate(data)
        else:
            return RunSchema.model_validate(data)

    async def delete_session(
        self,
        session_id: str,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> None:
        """Delete a specific session.

        Args:
            session_id: ID of the session to delete
            db_id: Optional database ID to use
            table: Optional table name to use

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/sessions/{session_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        await self._delete(endpoint)

    async def delete_sessions(
        self,
        session_ids: List[str],
        session_types: List[SessionType],
        session_type: SessionType = SessionType.AGENT,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> None:
        """Delete multiple sessions.

        Args:
            session_ids: List of session IDs to delete
            session_types: List of session types corresponding to each session ID
            session_type: Default session type filter
            db_id: Optional database ID to use
            table: Optional table name to use

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {"type": session_type.value}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/sessions"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload = {
            "session_ids": session_ids,
            "session_types": [st.value for st in session_types],
        }

        await self._delete_with_body(endpoint, payload)

    async def rename_session(
        self,
        session_id: str,
        session_name: str,
        session_type: SessionType = SessionType.AGENT,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        """Rename a session.

        Args:
            session_id: ID of the session to rename
            session_name: New name for the session
            session_type: Type of session (agent, team, or workflow)
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            AgentSessionDetailSchema, TeamSessionDetailSchema, or WorkflowSessionDetailSchema

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params: Dict[str, str] = {"type": session_type.value}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/sessions/{session_id}/rename"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload = {"session_name": session_name}
        data = await self._post(endpoint, payload)

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.model_validate(data)
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.model_validate(data)
        else:
            return WorkflowSessionDetailSchema.model_validate(data)

    async def update_session(
        self,
        session_id: str,
        session_type: SessionType = SessionType.AGENT,
        session_name: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        summary: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        """Update session properties.

        Args:
            session_id: ID of the session to update
            session_type: Type of session (agent, team, or workflow)
            session_name: Optional new session name
            session_state: Optional new session state
            metadata: Optional new metadata
            summary: Optional new summary
            user_id: Optional user ID
            db_id: Optional database ID to use

        Returns:
            AgentSessionDetailSchema, TeamSessionDetailSchema, or WorkflowSessionDetailSchema

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params: Dict[str, str] = {"type": session_type.value}
        if user_id:
            params["user_id"] = user_id
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/sessions/{session_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload: Dict[str, Any] = {}
        if session_name is not None:
            payload["session_name"] = session_name
        if session_state is not None:
            payload["session_state"] = session_state
        if metadata is not None:
            payload["metadata"] = metadata
        if summary is not None:
            payload["summary"] = summary

        data = await self._patch(endpoint, payload)

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.model_validate(data)
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.model_validate(data)
        else:
            return WorkflowSessionDetailSchema.model_validate(data)

    # Eval Operations

    async def list_eval_runs(
        self,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        model_id: Optional[str] = None,
        filter_type: Optional[EvalFilterType] = None,
        eval_types: Optional[List[EvalType]] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> PaginatedResponse[EvalSchema]:
        """List evaluation runs with filtering and pagination.

        Args:
            agent_id: Filter by agent ID
            team_id: Filter by team ID
            workflow_id: Filter by workflow ID
            model_id: Filter by model ID
            filter_type: Filter type (agent, team, workflow)
            eval_types: List of eval types to filter by (accuracy, performance, reliability)
            limit: Number of eval runs per page
            page: Page number
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            PaginatedResponse[EvalSchema]: Paginated list of evaluation runs

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {
            "limit": str(limit),
            "page": str(page),
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if agent_id:
            params["agent_id"] = agent_id
        if team_id:
            params["team_id"] = team_id
        if workflow_id:
            params["workflow_id"] = workflow_id
        if model_id:
            params["model_id"] = model_id
        if filter_type:
            params["type"] = filter_type.value
        if eval_types:
            params["eval_types"] = ",".join(et.value for et in eval_types)
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/eval-runs?" + "&".join(f"{k}={v}" for k, v in params.items())
        data = await self._get(endpoint)
        return PaginatedResponse[EvalSchema].model_validate(data)

    async def get_eval_run(
        self,
        eval_run_id: str,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> EvalSchema:
        """Get a specific evaluation run by ID.

        Args:
            eval_run_id: ID of the evaluation run to retrieve
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            EvalSchema: The evaluation run details

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/eval-runs/{eval_run_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)
        return EvalSchema.model_validate(data)

    async def delete_eval_runs(
        self,
        eval_run_ids: List[str],
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> None:
        """Delete multiple evaluation runs.

        Args:
            eval_run_ids: List of evaluation run IDs to delete
            db_id: Optional database ID to use
            table: Optional table name to use

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/eval-runs"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload = {"eval_run_ids": eval_run_ids}
        await self._delete_with_body(endpoint, payload)

    async def update_eval_run(
        self,
        eval_run_id: str,
        name: str,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> EvalSchema:
        """Update an evaluation run (rename).

        Args:
            eval_run_id: ID of the evaluation run to update
            name: New name for the evaluation run
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            EvalSchema: The updated evaluation run

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = f"/eval-runs/{eval_run_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload = {"name": name}
        data = await self._patch(endpoint, payload)
        return EvalSchema.model_validate(data)

    async def run_eval(
        self,
        eval_type: EvalType,
        input_text: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        model_id: Optional[str] = None,
        model_provider: Optional[str] = None,
        expected_output: Optional[str] = None,
        expected_tool_calls: Optional[List[str]] = None,
        num_iterations: int = 1,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
    ) -> Optional[EvalSchema]:
        """Execute an evaluation on an agent or team.

        Args:
            eval_type: Type of evaluation (accuracy, performance, reliability)
            input_text: Input text for the evaluation
            agent_id: Agent ID to evaluate (mutually exclusive with team_id)
            team_id: Team ID to evaluate (mutually exclusive with agent_id)
            model_id: Optional model ID to use (overrides agent/team default)
            model_provider: Optional model provider to use
            expected_output: Expected output for accuracy evaluations
            expected_tool_calls: Expected tool calls for reliability evaluations
            num_iterations: Number of iterations for performance evaluations
            db_id: Optional database ID to use
            table: Optional table name to use

        Returns:
            EvalSchema: The evaluation result, or None if evaluation against remote agents

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        endpoint = "/eval-runs"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        payload: Dict[str, Any] = {
            "eval_type": eval_type.value,
            "input": input_text,
        }
        if agent_id:
            payload["agent_id"] = agent_id
        if team_id:
            payload["team_id"] = team_id
        if model_id:
            payload["model_id"] = model_id
        if model_provider:
            payload["model_provider"] = model_provider
        if expected_output:
            payload["expected_output"] = expected_output
        if expected_tool_calls:
            payload["expected_tool_calls"] = expected_tool_calls
        if num_iterations != 1:
            payload["num_iterations"] = num_iterations

        data = await self._post(endpoint, payload)
        if data is None:
            return None
        return EvalSchema.model_validate(data)

    # Knowledge Operations

    async def upload_content(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        file_content: Optional[bytes] = None,
        file_name: Optional[str] = None,
        file_content_type: Optional[str] = None,
        text_content: Optional[str] = None,
        reader_id: Optional[str] = None,
        chunker: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        db_id: Optional[str] = None,
    ) -> ContentResponseSchema:
        """Upload content to the knowledge base.

        Args:
            name: Content name (auto-generated from file/URL if not provided)
            description: Content description
            url: URL to fetch content from (can be JSON array or single URL)
            metadata: Metadata dictionary for the content
            file_content: Raw file bytes to upload
            file_name: Filename for the uploaded content
            file_content_type: MIME type of the file
            text_content: Raw text content to process
            reader_id: ID of the reader to use for processing
            chunker: Chunking strategy to apply
            chunk_size: Chunk size for processing
            chunk_overlap: Chunk overlap for processing
            db_id: Optional database ID to use

        Returns:
            ContentResponseSchema: The uploaded content info

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = "/knowledge/content"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        url_full = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        # Build multipart form data
        form_data: Dict[str, Any] = {}
        files: Dict[str, Any] = {}

        if name:
            form_data["name"] = name
        if description:
            form_data["description"] = description
        if url:
            form_data["url"] = url
        if metadata:
            form_data["metadata"] = json.dumps(metadata)
        if text_content:
            form_data["text_content"] = text_content
        if reader_id:
            form_data["reader_id"] = reader_id
        if chunker:
            form_data["chunker"] = chunker
        if chunk_size:
            form_data["chunk_size"] = str(chunk_size)
        if chunk_overlap:
            form_data["chunk_overlap"] = str(chunk_overlap)

        if file_content:
            files["file"] = (file_name or "upload", file_content, file_content_type or "application/octet-stream")

        if files:
            response = await self._http_client.post(url_full, data=form_data, files=files, headers=headers)
        else:
            response = await self._http_client.post(url_full, data=form_data, headers=headers)

        response.raise_for_status()
        return ContentResponseSchema.model_validate(response.json())

    async def update_content(
        self,
        content_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reader_id: Optional[str] = None,
        db_id: Optional[str] = None,
    ) -> ContentResponseSchema:
        """Update content properties.

        Args:
            content_id: ID of the content to update
            name: New content name
            description: New content description
            metadata: New metadata dictionary
            reader_id: ID of the reader to use
            db_id: Optional database ID to use

        Returns:
            ContentResponseSchema: The updated content

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        import json

        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/knowledge/content/{content_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        url_str = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        form_data: Dict[str, Any] = {}
        if name:
            form_data["name"] = name
        if description:
            form_data["description"] = description
        if metadata:
            form_data["metadata"] = json.dumps(metadata)
        if reader_id:
            form_data["reader_id"] = reader_id

        response = await self._http_client.patch(url_str, data=form_data, headers=headers)
        response.raise_for_status()
        return ContentResponseSchema.model_validate(response.json())

    async def list_content(
        self,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        db_id: Optional[str] = None,
    ) -> PaginatedResponse[ContentResponseSchema]:
        """List all content in the knowledge base.

        Args:
            limit: Number of content entries per page
            page: Page number
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
            db_id: Optional database ID to use

        Returns:
            PaginatedResponse[ContentResponseSchema]: Paginated list of content

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, str] = {
            "limit": str(limit),
            "page": str(page),
            "sort_by": sort_by,
            "sort_order": sort_order,
        }
        if db_id:
            params["db_id"] = db_id

        endpoint = "/knowledge/content?" + "&".join(f"{k}={v}" for k, v in params.items())
        data = await self._get(endpoint)
        return PaginatedResponse[ContentResponseSchema].model_validate(data)

    async def get_content(
        self,
        content_id: str,
        db_id: Optional[str] = None,
    ) -> ContentResponseSchema:
        """Get a specific content by ID.

        Args:
            content_id: ID of the content to retrieve
            db_id: Optional database ID to use

        Returns:
            ContentResponseSchema: The content details

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/knowledge/content/{content_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)
        return ContentResponseSchema.model_validate(data)

    async def delete_content(
        self,
        content_id: str,
        db_id: Optional[str] = None,
    ) -> ContentResponseSchema:
        """Delete a specific content.

        Args:
            content_id: ID of the content to delete
            db_id: Optional database ID to use

        Returns:
            ContentResponseSchema: The deleted content info

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/knowledge/content/{content_id}"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        url_str = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._http_client.delete(url_str, headers=headers)
        response.raise_for_status()
        return ContentResponseSchema.model_validate(response.json())

    async def delete_all_content(
        self,
        db_id: Optional[str] = None,
    ) -> str:
        """Delete all content from the knowledge base.

        WARNING: This is a destructive operation that cannot be undone.

        Args:
            db_id: Optional database ID to use

        Returns:
            str: "success" if successful

        Raises:
            HTTPStatusError: On HTTP errors
        """
        if not self._http_client:
            self._http_client = AsyncClient(timeout=self.timeout)

        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = "/knowledge/content"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        url_str = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        response = await self._http_client.delete(url_str, headers=headers)
        response.raise_for_status()
        return response.json()

    async def get_content_status(
        self,
        content_id: str,
        db_id: Optional[str] = None,
    ) -> ContentStatusResponse:
        """Get the processing status of a content item.

        Args:
            content_id: ID of the content
            db_id: Optional database ID to use

        Returns:
            ContentStatusResponse: The content processing status

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/knowledge/content/{content_id}/status"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)
        return ContentStatusResponse.model_validate(data)

    async def search_knowledge(
        self,
        query: str,
        max_results: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        search_type: Optional[str] = None,
        vector_db_ids: Optional[List[str]] = None,
        limit: int = 20,
        page: int = 1,
        db_id: Optional[str] = None,
    ) -> PaginatedResponse[VectorSearchResult]:
        """Search the knowledge base.

        Args:
            query: Search query string
            max_results: Maximum number of results to return from search
            filters: Optional filters to apply
            search_type: Type of search (vector, keyword, hybrid)
            vector_db_ids: Optional list of vector DB IDs to search
            limit: Number of results per page
            page: Page number
            db_id: Optional database ID to use

        Returns:
            PaginatedResponse[VectorSearchResult]: Paginated search results

        Raises:
            HTTPStatusError: On HTTP errors
        """
        payload: Dict[str, Any] = {"query": query}
        if max_results:
            payload["max_results"] = max_results
        if filters:
            payload["filters"] = filters
        if search_type:
            payload["search_type"] = search_type
        if vector_db_ids:
            payload["vector_db_ids"] = vector_db_ids
        payload["meta"] = {"limit": limit, "page": page}
        if db_id:
            payload["db_id"] = db_id

        data = await self._post("/knowledge/search", payload)
        return PaginatedResponse[VectorSearchResult].model_validate(data)

    async def get_knowledge_config(
        self,
        db_id: Optional[str] = None,
    ) -> KnowledgeConfigResponse:
        """Get knowledge base configuration.

        Returns available readers, chunkers, vector DBs, and filters.

        Args:
            db_id: Optional database ID to use

        Returns:
            KnowledgeConfigResponse: Knowledge configuration

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = "/knowledge/config"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        data = await self._get(endpoint)
        return KnowledgeConfigResponse.model_validate(data)

    async def run_agent(
        self,
        agent_id: str,
        message: str,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        audio: Optional[Dict[str, Any]] = None,
        videos: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunSchema:
        """Execute an agent run.

        Args:
            agent_id: ID of the agent to run
            message: The message/prompt for the agent
            stream: Whether to stream the response (for non-streaming, use this; for streaming use stream_agent_run)
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            context: Optional context dictionary

        Returns:
            RunSchema: The run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/agents/{agent_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": str(stream).lower()}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps(images)
        if audio:
            data["audio"] = json.dumps(audio)
        if videos:
            data["videos"] = json.dumps(videos)
        if files:
            data["files"] = json.dumps(files)
        if context:
            data["context"] = json.dumps(context)

        response_data = await self._post_form_data(endpoint, data)
        return RunSchema.model_validate(response_data)

    async def stream_agent_run(
        self,
        agent_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        audio: Optional[Dict[str, Any]] = None,
        videos: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """Stream an agent run response.

        Args:
            agent_id: ID of the agent to run
            message: The message/prompt for the agent
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            context: Optional context dictionary

        Yields:
            str: Server-sent event lines

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/agents/{agent_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": "true"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps(images)
        if audio:
            data["audio"] = json.dumps(audio)
        if videos:
            data["videos"] = json.dumps(videos)
        if files:
            data["files"] = json.dumps(files)
        if context:
            data["context"] = json.dumps(context)

        async for line in self._stream_post_form_data(endpoint, data):
            yield line

    async def continue_agent_run(
        self,
        agent_id: str,
        run_id: str,
        tools: List[Dict[str, Any]],
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RunSchema:
        """Continue a paused agent run with tool results.

        Args:
            agent_id: ID of the agent
            run_id: ID of the run to continue
            tools: List of tool results to provide
            stream: Whether to stream the response
            session_id: Optional session ID
            user_id: Optional user ID

        Returns:
            RunSchema: The continued run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/agents/{agent_id}/runs/{run_id}/continue"
        data: Dict[str, Any] = {"tools": json.dumps(tools), "stream": str(stream).lower()}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id

        response_data = await self._post_form_data(endpoint, data)
        return RunSchema.model_validate(response_data)

    async def stream_continue_agent_run(
        self,
        agent_id: str,
        run_id: str,
        tools: List[Dict[str, Any]],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Stream a continued agent run response.

        Args:
            agent_id: ID of the agent
            run_id: ID of the run to continue
            tools: List of tool results to provide
            session_id: Optional session ID
            user_id: Optional user ID

        Yields:
            str: Server-sent event lines

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/agents/{agent_id}/runs/{run_id}/continue"
        data: Dict[str, Any] = {"tools": json.dumps(tools), "stream": "true"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id

        async for line in self._stream_post_form_data(endpoint, data):
            yield line

    async def cancel_agent_run(self, agent_id: str, run_id: str) -> None:
        """Cancel an agent run.

        Args:
            agent_id: ID of the agent
            run_id: ID of the run to cancel

        Raises:
            HTTPStatusError: On HTTP errors
        """
        await self._post_empty(f"/agents/{agent_id}/runs/{run_id}/cancel")

    # Team Run Operations

    async def run_team(
        self,
        team_id: str,
        message: str,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        audio: Optional[Dict[str, Any]] = None,
        videos: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> TeamRunSchema:
        """Execute a team run.

        Args:
            team_id: ID of the team to run
            message: The message/prompt for the team
            stream: Whether to stream the response
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            context: Optional context dictionary

        Returns:
            TeamRunSchema: The team run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/teams/{team_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": str(stream).lower()}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps(images)
        if audio:
            data["audio"] = json.dumps(audio)
        if videos:
            data["videos"] = json.dumps(videos)
        if files:
            data["files"] = json.dumps(files)
        if context:
            data["context"] = json.dumps(context)

        response_data = await self._post_form_data(endpoint, data)
        return TeamRunSchema.model_validate(response_data)

    async def stream_team_run(
        self,
        team_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        audio: Optional[Dict[str, Any]] = None,
        videos: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """Stream a team run response.

        Args:
            team_id: ID of the team to run
            message: The message/prompt for the team
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            context: Optional context dictionary

        Yields:
            str: Server-sent event lines

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/teams/{team_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": "true"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps(images)
        if audio:
            data["audio"] = json.dumps(audio)
        if videos:
            data["videos"] = json.dumps(videos)
        if files:
            data["files"] = json.dumps(files)
        if context:
            data["context"] = json.dumps(context)

        async for line in self._stream_post_form_data(endpoint, data):
            yield line

    async def cancel_team_run(self, team_id: str, run_id: str) -> None:
        """Cancel a team run.

        Args:
            team_id: ID of the team
            run_id: ID of the run to cancel

        Raises:
            HTTPStatusError: On HTTP errors
        """
        await self._post_empty(f"/teams/{team_id}/runs/{run_id}/cancel")

    async def run_workflow(
        self,
        workflow_id: str,
        message: str,
        stream: bool = False,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        audio: Optional[Dict[str, Any]] = None,
        videos: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> WorkflowRunSchema:
        """Execute a workflow run.

        Args:
            workflow_id: ID of the workflow to run
            message: The message/prompt for the workflow
            stream: Whether to stream the response
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            context: Optional context dictionary

        Returns:
            WorkflowRunSchema: The workflow run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/workflows/{workflow_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": str(stream).lower()}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps(images)
        if audio:
            data["audio"] = json.dumps(audio)
        if videos:
            data["videos"] = json.dumps(videos)
        if files:
            data["files"] = json.dumps(files)
        if context:
            data["context"] = json.dumps(context)

        response_data = await self._post_form_data(endpoint, data)
        return WorkflowRunSchema.model_validate(response_data)

    async def stream_workflow_run(
        self,
        workflow_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Any]] = None,
        audio: Optional[Dict[str, Any]] = None,
        videos: Optional[List[Any]] = None,
        files: Optional[List[Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[str]:
        """Stream a workflow run response.

        Args:
            workflow_id: ID of the workflow to run
            message: The message/prompt for the workflow
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            context: Optional context dictionary

        Yields:
            str: Server-sent event lines

        Raises:
            HTTPStatusError: On HTTP errors
        """
        import json

        endpoint = f"/workflows/{workflow_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": "true"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps(images)
        if audio:
            data["audio"] = json.dumps(audio)
        if videos:
            data["videos"] = json.dumps(videos)
        if files:
            data["files"] = json.dumps(files)
        if context:
            data["context"] = json.dumps(context)

        async for line in self._stream_post_form_data(endpoint, data):
            yield line

    async def cancel_workflow_run(self, workflow_id: str, run_id: str) -> None:
        """Cancel a workflow run.

        Args:
            workflow_id: ID of the workflow
            run_id: ID of the run to cancel

        Raises:
            HTTPStatusError: On HTTP errors
        """
        await self._post_empty(f"/workflows/{workflow_id}/runs/{run_id}/cancel")
