import json
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from httpx import AsyncClient, ConnectError, ConnectTimeout, TimeoutException

from agno.db.base import SessionType
from agno.db.schemas.evals import EvalFilterType, EvalType
from agno.exceptions import RemoteServerUnavailableError
from agno.media import Audio, Image, Video
from agno.media import File as MediaFile
from agno.models.response import ToolExecution
from agno.os.routers.agents.schema import AgentResponse
from agno.os.routers.evals.schemas import EvalSchema
from agno.os.routers.knowledge.schemas import (
    ConfigResponseSchema as KnowledgeConfigResponse,
)
from agno.os.routers.knowledge.schemas import (
    ContentResponseSchema,
    ContentStatusResponse,
    VectorSearchResult,
)
from agno.os.routers.memory.schemas import (
    UserMemorySchema,
    UserStatsSchema,
)
from agno.os.routers.teams.schema import TeamResponse
from agno.os.routers.workflows.schema import WorkflowResponse
from agno.os.schema import (
    AgentSessionDetailSchema,
    AgentSummaryResponse,
    ConfigResponse,
    Model,
    PaginatedResponse,
    PaginationInfo,
    RunSchema,
    SessionSchema,
    TeamRunSchema,
    TeamSessionDetailSchema,
    TeamSummaryResponse,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
    WorkflowSummaryResponse,
)
from agno.run.agent import RunOutput, RunOutputEvent, run_output_event_from_dict
from agno.run.team import TeamRunOutput, TeamRunOutputEvent, team_run_output_event_from_dict
from agno.run.workflow import WorkflowRunOutputEvent, workflow_run_output_event_from_dict
from agno.utils.http import get_default_async_client, get_default_sync_client


class AgentOSClient:
    """Client for interacting with AgentOS API endpoints.

    Attributes:
        base_url: Base URL of the AgentOS instance
        timeout: Request timeout in seconds
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
    ):
        """Initialize AgentOSClient.

        Args:
            base_url: Base URL of the AgentOS instance (e.g., "http://localhost:7777")
            timeout: Request timeout in seconds (default: 60.0)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        as_form: bool = False,
    ) -> Any:
        """Execute synchronous HTTP request.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint path (without base URL)
            data: Request body data (optional)
            params: Query parameters (optional)
            headers: HTTP headers to include in the request (optional)
            as_form: If True, send data as form data instead of JSON

        Returns:
            Parsed JSON response, or None for empty responses

        Raises:
            RemoteServerUnavailableError: When the remote server is unavailable
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        url = f"{self.base_url}{endpoint}"

        kwargs: Dict[str, Any] = {"headers": headers or {}}
        if data is not None:
            if as_form:
                kwargs["data"] = data
            else:
                kwargs["json"] = data
        if params is not None:
            kwargs["params"] = params

        sync_client = get_default_sync_client()

        try:
            with sync_client as client:
                response = client.request(method, url, **kwargs)
                response.raise_for_status()

                # Return None for empty responses (204 No Content, etc.)
                if not response.content:
                    return None
                return response.json()
        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to remote server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except TimeoutException as e:
            raise RemoteServerUnavailableError(
                message=f"Request to remote server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e

    async def _arequest(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        as_form: bool = False,
    ) -> Any:
        """Execute asynchronous HTTP request.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE)
            endpoint: API endpoint path (without base URL)
            data: Request body data (optional)
            params: Query parameters (optional)
            headers: HTTP headers to include in the request (optional)
            as_form: If True, send data as form data instead of JSON

        Returns:
            Parsed JSON response, or None for empty responses

        Raises:
            RemoteServerUnavailableError: When the remote server is unavailable
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        url = f"{self.base_url}{endpoint}"

        kwargs: Dict[str, Any] = {"headers": headers or {}}
        if data is not None:
            if as_form:
                kwargs["data"] = data
            else:
                kwargs["json"] = data
        if params is not None:
            kwargs["params"] = params

        async_client = get_default_async_client()
        async_client.timeout = self.timeout

        try:
            async with async_client as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()

                # Return None for empty responses (204 No Content, etc.)
                if not response.content:
                    return None
                return response.json()
        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to remote server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except TimeoutException as e:
            raise RemoteServerUnavailableError(
                message=f"Request to remote server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e

    def _get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute synchronous GET request.

        Args:
            endpoint: API endpoint path (without base URL)
            params: Query parameters (optional)
            headers: HTTP headers to include in the request (optional)

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        return self._request("GET", endpoint, params=params, headers=headers)

    async def _aget(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute asynchronous GET request.

        Args:
            endpoint: API endpoint path (without base URL)
            params: Query parameters (optional)
            headers: HTTP headers to include in the request (optional)

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        return await self._arequest("GET", endpoint, params=params, headers=headers)

    async def _apost(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        as_form: bool = False,
    ) -> Any:
        """Execute asynchronous POST request.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Request body data (optional)
            params: Query parameters (optional)
            headers: HTTP headers to include in the request (optional)
            as_form: If True, send data as form data instead of JSON

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        return await self._arequest("POST", endpoint, data=data, params=params, headers=headers, as_form=as_form)

    async def _apatch(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute asynchronous PATCH request.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Request body data
            params: Query parameters (optional)
            headers: HTTP headers to include in the request (optional)

        Returns:
            Parsed JSON response

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        return await self._arequest("PATCH", endpoint, data=data, params=params, headers=headers)

    async def _adelete(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Execute asynchronous DELETE request.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Optional request body data
            params: Query parameters (optional)
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        await self._arequest("DELETE", endpoint, data=data, params=params, headers=headers)

    async def _astream_post_form_data(
        self,
        endpoint: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> AsyncIterator[str]:
        """Stream POST request with form data.

        Args:
            endpoint: API endpoint path (without base URL)
            data: Form data dictionary
            headers: HTTP headers to include in the request (optional)

        Yields:
            str: Lines from the streaming response

        Raises:
            RemoteServerUnavailableError: When the remote server is unavailable
        """
        url = f"{self.base_url}{endpoint}"

        try:
            async with AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, data=data, headers=headers or {}) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        yield line
        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to remote server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except TimeoutException as e:
            raise RemoteServerUnavailableError(
                message=f"Request to remote server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e

    async def _parse_sse_events(
        self,
        raw_stream: AsyncIterator[str],
        event_parser: Callable[[dict], Any],
    ) -> AsyncIterator[Any]:
        """Parse SSE stream into typed event objects.

        Args:
            raw_stream: Raw SSE lines from streaming response
            event_parser: Function to parse event dict into typed object

        Yields:
            Parsed event objects
        """
        from agno.utils.log import logger

        async for line in raw_stream:
            # Skip empty lines and comments (SSE protocol)
            if not line or line.startswith(":"):
                continue

            # Parse SSE data lines
            if line.startswith("data: "):
                try:
                    # Extract and parse JSON payload
                    json_str = line[6:]  # Remove "data: " prefix
                    event_dict = json.loads(json_str)

                    # Parse into typed event using provided factory
                    event = event_parser(event_dict)
                    yield event

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse SSE JSON: {line[:100]}... | Error: {e}")
                    continue  # Skip bad events, continue stream

                except ValueError as e:
                    logger.error(f"Unknown event type: {line[:100]}... | Error: {e}")
                    continue  # Skip unknown events, continue stream

    # Discovery & Configuration Operations

    def get_config(self, headers: Optional[Dict[str, str]] = None) -> ConfigResponse:
        """Get AgentOS configuration and metadata.

        Returns comprehensive OS configuration including:
        - OS metadata (id, description, version)
        - List of available agents
        - List of available teams
        - List of available workflows
        - Interface configurations
        - Knowledge, evals, and metrics settings

        Args:
            headers: HTTP headers to include in the request (optional)

        Returns:
            ConfigResponse: Complete OS configuration

        We need this sync version so it can be used for other sync use-cases upstream
        """
        data = self._get("/config", headers=headers)
        return ConfigResponse.model_validate(data)

    async def aget_config(self, headers: Optional[Dict[str, str]] = None) -> ConfigResponse:
        """Get AgentOS configuration and metadata.

        Returns comprehensive OS configuration including:
        - OS metadata (id, description, version)
        - List of available agents
        - List of available teams
        - List of available workflows
        - Interface configurations
        - Knowledge, evals, and metrics settings

        Args:
            headers: HTTP headers to include in the request (optional)

        Returns:
            ConfigResponse: Complete OS configuration

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._aget("/config", headers=headers)
        return ConfigResponse.model_validate(data)

    async def get_models(self, headers: Optional[Dict[str, str]] = None) -> List[Model]:
        """Get list of all models used by agents and teams.

        Args:
            headers: HTTP headers to include in the request (optional)

        Returns:
            List[Model]: List of model configurations

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._aget("/models", headers=headers)
        return [Model.model_validate(item) for item in data]

    async def migrate_database(
        self, db_id: str, target_version: Optional[str] = None, headers: Optional[Dict[str, str]] = None
    ) -> None:
        """Migrate a database to a target version.

        Args:
            db_id: ID of the database to migrate
            target_version: Target version to migrate to
            headers: HTTP headers to include in the request (optional)
        """
        return await self._apost(
            f"/databases/{db_id}/migrate", data={"target_version": target_version}, headers=headers
        )

    async def list_agents(self, headers: Optional[Dict[str, str]] = None) -> List[AgentSummaryResponse]:
        """List all agents configured in the AgentOS instance.

        Returns summary information for each agent including:
        - Agent ID, name, description
        - Model configuration
        - Basic settings

        Args:
            headers: HTTP headers to include in the request (optional)

        Returns:
            List[AgentSummaryResponse]: List of agent summaries

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._aget("/agents", headers=headers)
        return [AgentSummaryResponse.model_validate(item) for item in data]

    def get_agent(self, agent_id: str, headers: Optional[Dict[str, str]] = None) -> AgentResponse:
        """Get detailed configuration for a specific agent.

        Args:
            agent_id: ID of the agent to retrieve
            headers: HTTP headers to include in the request (optional)

        Returns:
            AgentResponse: Detailed agent configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if agent not found)
        """
        data = self._get(f"/agents/{agent_id}", headers=headers)
        return AgentResponse.model_validate(data)

    async def aget_agent(self, agent_id: str, headers: Optional[Dict[str, str]] = None) -> AgentResponse:
        """Get detailed configuration for a specific agent.

        Args:
            agent_id: ID of the agent to retrieve
            headers: HTTP headers to include in the request (optional)

        Returns:
            AgentResponse: Detailed agent configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if agent not found)
        """
        data = await self._aget(f"/agents/{agent_id}", headers=headers)
        return AgentResponse.model_validate(data)

    async def run_agent(
        self,
        agent_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[MediaFile]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> RunOutput:
        """Execute an agent run.

        Args:
            agent_id: ID of the agent to run
            message: The message/prompt for the agent
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of Image objects
            audio: Optional list of Audio objects
            videos: Optional list of Video objects
            files: Optional list of MediaFile objects
            headers: HTTP headers to include in the request (optional)
            **kwargs: Additional parameters passed to the agent run, such as:
                - session_state: Dict for session state
                - dependencies: Dict for dependencies
                - metadata: Dict for metadata
                - knowledge_filters: Filters for knowledge search
                - output_schema: JSON schema for structured output

        Returns:
            RunOutput: The run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        endpoint = f"/agents/{agent_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": "false"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps([img.model_dump() for img in images])
        if audio:
            data["audio"] = json.dumps([a.model_dump() for a in audio])
        if videos:
            data["videos"] = json.dumps([v.model_dump() for v in videos])
        if files:
            data["files"] = json.dumps([f.model_dump() for f in files])

        # Add kwargs to data, serializing dicts as JSON
        for key, value in kwargs.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        data = {k: v for k, v in data.items() if v is not None}

        response_data = await self._apost(endpoint, data, headers=headers, as_form=True)
        return RunOutput.from_dict(response_data)

    async def run_agent_stream(
        self,
        agent_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[MediaFile]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]:
        """Stream an agent run response.

        Args:
            agent_id: ID of the agent to run
            message: The message/prompt for the agent
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of Image objects
            audio: Optional list of Audio objects
            videos: Optional list of Video objects
            files: Optional list of MediaFile objects
            headers: HTTP headers to include in the request (optional)
            **kwargs: Additional parameters (session_state, dependencies, metadata, etc.)

        Yields:
            RunOutputEvent: Typed event objects (RunStartedEvent, RunContentEvent, etc.)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        endpoint = f"/agents/{agent_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": "true"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id
        if images:
            data["images"] = json.dumps([img.model_dump() for img in images])
        if audio:
            data["audio"] = json.dumps([a.model_dump() for a in audio])
        if videos:
            data["videos"] = json.dumps([v.model_dump() for v in videos])
        if files:
            data["files"] = json.dumps([f.model_dump() for f in files])

        for key, value in kwargs.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        data = {k: v for k, v in data.items() if v is not None}

        # Get raw SSE stream and parse into typed events
        raw_stream = self._astream_post_form_data(endpoint, data, headers=headers)
        async for event in self._parse_sse_events(raw_stream, run_output_event_from_dict):
            yield event

    async def continue_agent_run(
        self,
        agent_id: str,
        run_id: str,
        tools: List[ToolExecution],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> RunOutput:
        """Continue a paused agent run with tool results.

        Args:
            agent_id: ID of the agent
            run_id: ID of the run to continue
            tools: List of ToolExecution objects with tool results
            stream: Whether to stream the response
            session_id: Optional session ID
            user_id: Optional user ID
            headers: HTTP headers to include in the request (optional)

        Returns:
            RunOutput: The continued run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        endpoint = f"/agents/{agent_id}/runs/{run_id}/continue"
        data: Dict[str, Any] = {"tools": json.dumps([tool.to_dict() for tool in tools]), "stream": "false"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id

        response_data = await self._apost(endpoint, data, headers=headers, as_form=True)
        return RunOutput.from_dict(response_data)

    async def continue_agent_run_stream(
        self,
        agent_id: str,
        run_id: str,
        tools: List[ToolExecution],
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> AsyncIterator[RunOutputEvent]:
        """Stream a continued agent run response.

        Args:
            agent_id: ID of the agent
            run_id: ID of the run to continue
            tools: List of ToolExecution objects with tool results
            session_id: Optional session ID
            user_id: Optional user ID
            headers: HTTP headers to include in the request (optional)

        Yields:
            RunOutputEvent: Typed event objects (RunStartedEvent, RunContentEvent, etc.)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        endpoint = f"/agents/{agent_id}/runs/{run_id}/continue"
        data: Dict[str, Any] = {"tools": json.dumps([tool.to_dict() for tool in tools]), "stream": "true"}
        if session_id:
            data["session_id"] = session_id
        if user_id:
            data["user_id"] = user_id

        raw_stream = self._astream_post_form_data(endpoint, data, headers=headers)
        async for event in self._parse_sse_events(raw_stream, run_output_event_from_dict):
            yield event

    async def cancel_agent_run(self, agent_id: str, run_id: str, headers: Optional[Dict[str, str]] = None) -> None:
        """Cancel an agent run.

        Args:
            agent_id: ID of the agent
            run_id: ID of the run to cancel
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        await self._apost(f"/agents/{agent_id}/runs/{run_id}/cancel", headers=headers)

    async def list_teams(self, headers: Optional[Dict[str, str]] = None) -> List[TeamSummaryResponse]:
        """List all teams configured in the AgentOS instance.

        Returns summary information for each team including:
        - Team ID, name, description
        - Model configuration
        - Member information

        Args:
            headers: HTTP headers to include in the request (optional)

        Returns:
            List[TeamSummaryResponse]: List of team summaries

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._aget("/teams", headers=headers)
        return [TeamSummaryResponse.model_validate(item) for item in data]

    def get_team(self, team_id: str, headers: Optional[Dict[str, str]] = None) -> TeamResponse:
        """Get detailed configuration for a specific team.

        Args:
            team_id: ID of the team to retrieve
            headers: HTTP headers to include in the request (optional)

        Returns:
            TeamResponse: Detailed team configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if team not found)
        """
        data = self._get(f"/teams/{team_id}", headers=headers)
        return TeamResponse.model_validate(data)

    async def aget_team(self, team_id: str, headers: Optional[Dict[str, str]] = None) -> TeamResponse:
        """Get detailed configuration for a specific team.

        Args:
            team_id: ID of the team to retrieve
            headers: HTTP headers to include in the request (optional)

        Returns:
            TeamResponse: Detailed team configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if team not found)
        """
        data = await self._aget(f"/teams/{team_id}", headers=headers)
        return TeamResponse.model_validate(data)

    async def run_team(
        self,
        team_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[MediaFile]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> TeamRunOutput:
        """Execute a team run.

        Args:
            team_id: ID of the team to run
            message: The message/prompt for the team
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            headers: HTTP headers to include in the request (optional)
            **kwargs: Additional parameters passed to the team run

        Returns:
            TeamRunOutput: The team run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        endpoint = f"/teams/{team_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": "false"}
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

        # Add kwargs to data, serializing dicts as JSON
        for key, value in kwargs.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        data = {k: v for k, v in data.items() if v is not None}

        response_data = await self._apost(endpoint, data, headers=headers, as_form=True)
        return TeamRunOutput.from_dict(response_data)

    async def run_team_stream(
        self,
        team_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[MediaFile]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[TeamRunOutputEvent]:
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
            headers: HTTP headers to include in the request (optional)
            **kwargs: Additional parameters passed to the team run

        Yields:
            TeamRunOutputEvent: Typed event objects (team and agent events)

        Raises:
            HTTPStatusError: On HTTP errors
        """
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

        # Add kwargs to data, serializing dicts as JSON
        for key, value in kwargs.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        data = {k: v for k, v in data.items() if v is not None}

        # Get raw SSE stream and parse into typed events
        raw_stream = self._astream_post_form_data(endpoint, data, headers=headers)
        async for event in self._parse_sse_events(raw_stream, team_run_output_event_from_dict):
            yield event

    async def cancel_team_run(self, team_id: str, run_id: str, headers: Optional[Dict[str, str]] = None) -> None:
        """Cancel a team run.

        Args:
            team_id: ID of the team
            run_id: ID of the run to cancel
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        await self._apost(f"/teams/{team_id}/runs/{run_id}/cancel", headers=headers)

    async def list_workflows(self, headers: Optional[Dict[str, str]] = None) -> List[WorkflowSummaryResponse]:
        """List all workflows configured in the AgentOS instance.

        Returns summary information for each workflow including:
        - Workflow ID, name, description
        - Step information

        Args:
            headers: HTTP headers to include in the request (optional)

        Returns:
            List[WorkflowSummaryResponse]: List of workflow summaries

        Raises:
            HTTPStatusError: On HTTP errors
        """
        data = await self._aget("/workflows", headers=headers)
        return [WorkflowSummaryResponse.model_validate(item) for item in data]

    def get_workflow(self, workflow_id: str, headers: Optional[Dict[str, str]] = None) -> WorkflowResponse:
        """Get detailed configuration for a specific workflow.

        Args:
            workflow_id: ID of the workflow to retrieve
            headers: HTTP headers to include in the request (optional)

        Returns:
            WorkflowResponse: Detailed workflow configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if workflow not found)
        """
        data = self._get(f"/workflows/{workflow_id}", headers=headers)
        return WorkflowResponse.model_validate(data)

    async def aget_workflow(self, workflow_id: str, headers: Optional[Dict[str, str]] = None) -> WorkflowResponse:
        """Get detailed configuration for a specific workflow.

        Args:
            workflow_id: ID of the workflow to retrieve
            headers: HTTP headers to include in the request (optional)

        Returns:
            WorkflowResponse: Detailed workflow configuration

        Raises:
            HTTPStatusError: On HTTP errors (404 if workflow not found)
        """
        data = await self._aget(f"/workflows/{workflow_id}", headers=headers)
        return WorkflowResponse.model_validate(data)

    async def run_workflow(
        self,
        workflow_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[MediaFile]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> WorkflowRunSchema:
        """Execute a workflow run.

        Args:
            workflow_id: ID of the workflow to run
            message: The message/prompt for the workflow
            session_id: Optional session ID for context
            user_id: Optional user ID
            images: Optional list of images
            audio: Optional audio data
            videos: Optional list of videos
            files: Optional list of files
            headers: HTTP headers to include in the request (optional)
            **kwargs: Additional parameters passed to the workflow run
        Returns:
            WorkflowRunSchema: The workflow run response

        Raises:
            HTTPStatusError: On HTTP errors
        """
        endpoint = f"/workflows/{workflow_id}/runs"
        data: Dict[str, Any] = {"message": message, "stream": "false"}
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

        # Add kwargs to data, serializing dicts as JSON
        for key, value in kwargs.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        data = {k: v for k, v in data.items() if v is not None}

        response_data = await self._apost(endpoint, data, headers=headers, as_form=True)
        return WorkflowRunSchema.model_validate(response_data)

    async def run_workflow_stream(
        self,
        workflow_id: str,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[List[Image]] = None,
        audio: Optional[List[Audio]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[MediaFile]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[WorkflowRunOutputEvent]:
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
            headers: HTTP headers to include in the request (optional)
            **kwargs: Additional parameters passed to the workflow run.

        Yields:
            WorkflowRunOutputEvent: Typed event objects (workflow, team, and agent events)

        Raises:
            HTTPStatusError: On HTTP errors
        """
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

        # Add kwargs to data, serializing dicts as JSON
        for key, value in kwargs.items():
            if isinstance(value, dict):
                data[key] = json.dumps(value)
            else:
                data[key] = value

        data = {k: v for k, v in data.items() if v is not None}

        # Get raw SSE stream and parse into typed events
        raw_stream = self._astream_post_form_data(endpoint, data, headers=headers)
        async for event in self._parse_sse_events(raw_stream, workflow_run_output_event_from_dict):
            yield event

    async def cancel_workflow_run(
        self, workflow_id: str, run_id: str, headers: Optional[Dict[str, str]] = None
    ) -> None:
        """Cancel a workflow run.

        Args:
            workflow_id: ID of the workflow
            run_id: ID of the run to cancel
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        await self._apost(f"/workflows/{workflow_id}/runs/{run_id}/cancel", headers=headers)

    async def create_memory(
        self,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> UserMemorySchema:
        """Create a new user memory.

        Args:
            memory: The memory content to store
            user_id: User ID to associate with the memory
            topics: Optional list of topics to categorize the memory
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

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

        payload: Dict[str, Any] = {"memory": memory, "user_id": user_id}
        if topics:
            payload["topics"] = topics

        data = await self._apost("/memories", payload, params=params, headers=headers)
        return UserMemorySchema.model_validate(data)

    async def get_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> UserMemorySchema:
        """Get a specific memory by ID.

        Args:
            memory_id: ID of the memory to retrieve
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

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

        data = await self._aget(f"/memories/{memory_id}", params=params, headers=headers)
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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

        Returns:
            PaginatedResponse[UserMemorySchema]: Paginated list of memories

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "page": page,
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
            params["topics"] = topics
        if search_content:
            params["search_content"] = search_content
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        data = await self._aget("/memories", params=params, headers=headers)
        return PaginatedResponse[UserMemorySchema].model_validate(data)

    async def update_memory(
        self,
        memory_id: str,
        memory: str,
        user_id: str,
        topics: Optional[List[str]] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> UserMemorySchema:
        """Update an existing memory.

        Args:
            memory_id: ID of the memory to update
            memory: New memory content
            user_id: User ID associated with the memory
            topics: Optional new list of topics
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

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

        payload: Dict[str, Any] = {"memory": memory, "user_id": user_id}
        if topics:
            payload["topics"] = topics

        data = await self._apatch(f"/memories/{memory_id}", payload, params=params, headers=headers)
        return UserMemorySchema.model_validate(data)

    async def delete_memory(
        self,
        memory_id: str,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Delete a specific memory.

        Args:
            memory_id: ID of the memory to delete
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

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

        await self._adelete(f"/memories/{memory_id}", params=params, headers=headers)

    async def delete_memories(
        self,
        memory_ids: List[str],
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Delete multiple memories.

        Args:
            memory_ids: List of memory IDs to delete
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        payload: Dict[str, Any] = {"memory_ids": memory_ids}
        if user_id:
            payload["user_id"] = user_id

        await self._adelete("/memories", payload, params=params, headers=headers)

    async def get_memory_topics(
        self,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """Get all unique memory topics.

        Args:
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

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

        return await self._aget("/memory_topics", params=params, headers=headers)

    async def get_user_memory_stats(
        self,
        limit: int = 20,
        page: int = 1,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> PaginatedResponse[UserStatsSchema]:
        """Get user memory statistics.

        Args:
            limit: Number of stats per page
            page: Page number
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            PaginatedResponse[UserStatsSchema]: Paginated user statistics

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, Any] = {"limit": limit, "page": page}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        data = await self._aget("/user_memory_stats", params=params, headers=headers)
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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

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
        data = await self._aget(endpoint, headers=headers)
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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

        Returns:
            AgentSessionDetailSchema, TeamSessionDetailSchema, or WorkflowSessionDetailSchema

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, Any] = {"type": session_type.value}
        if db_id:
            params["db_id"] = db_id

        payload: Dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "session_name": session_name,
            "session_state": session_state,
            "metadata": metadata,
            "agent_id": agent_id,
            "team_id": team_id,
            "workflow_id": workflow_id,
        }

        data = await self._apost("/sessions", payload, params=params, headers=headers)

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.model_validate(data)
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.model_validate(data)
        else:
            return WorkflowSessionDetailSchema.model_validate(data)

    async def get_sessions(
        self,
        session_type: Optional[SessionType] = None,
        component_id: Optional[str] = None,
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> PaginatedResponse[SessionSchema]:
        """Get a specific session by ID.

        Args:
            session_type: Type of session (agent, team, or workflow)
            component_id: Optional component ID filter
            user_id: Optional user ID filter
            session_name: Optional session name filter
            limit: Number of sessions per page
            page: Page number
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            PaginatedResponse[SessionSchema]
        """
        params: Dict[str, Any] = {
            "type": session_type.value,
            "limit": str(limit),
            "page": str(page),
            "sort_by": sort_by,
            "sort_order": sort_order,
            "db_id": db_id,
            "table": table,
            "user_id": user_id,
            "session_name": session_name,
            "component_id": component_id,
        }

        params = {k: v for k, v in params.items() if v is not None}

        response = await self._aget("/sessions", params=params, headers=headers)
        data = response.get("data", [])
        pagination_info = PaginationInfo.model_validate(response.get("meta", {}))
        return PaginatedResponse[SessionSchema](
            data=[SessionSchema.from_dict(session) for session in data],
            meta=pagination_info,
        )

    async def get_session(
        self,
        session_id: str,
        session_type: SessionType = SessionType.AGENT,
        user_id: Optional[str] = None,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        """Get a specific session by ID.

        Args:
            session_id: ID of the session to retrieve
            session_type: Type of session (agent, team, or workflow)
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            AgentSessionDetailSchema, TeamSessionDetailSchema, or WorkflowSessionDetailSchema

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params: Dict[str, Any] = {
            "type": session_type.value,
            "user_id": user_id,
            "db_id": db_id,
            "table": table,
        }
        params = {k: v for k, v in params.items() if v is not None}

        data = await self._aget(f"/sessions/{session_id}", params=params, headers=headers)

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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

        Returns:
            List of runs (RunSchema, TeamRunSchema, or WorkflowRunSchema)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, Any] = {
            "type": session_type.value,
            "user_id": user_id,
            "created_after": created_after,
            "created_before": created_before,
            "db_id": db_id,
            "table": table,
        }
        params = {k: v for k, v in params.items() if v is not None}

        data = await self._aget(f"/sessions/{session_id}/runs", params=params, headers=headers)

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
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Union[RunSchema, TeamRunSchema, WorkflowRunSchema]:
        """Get a specific run from a session.

        Args:
            session_id: ID of the session
            run_id: ID of the run to retrieve
            session_type: Type of session (agent, team, or workflow)
            user_id: Optional user ID filter
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            RunSchema, TeamRunSchema, or WorkflowRunSchema

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params: Dict[str, Any] = {
            "type": session_type.value,
            "user_id": user_id,
            "db_id": db_id,
            "table": table,
        }
        params = {k: v for k, v in params.items() if v is not None}

        data = await self._aget(f"/sessions/{session_id}/runs/{run_id}", params=params, headers=headers)

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
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Delete a specific session.

        Args:
            session_id: ID of the session to delete
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        await self._adelete(f"/sessions/{session_id}", params=params, headers=headers)

    async def delete_sessions(
        self,
        session_ids: List[str],
        session_types: List[SessionType],
        session_type: SessionType = SessionType.AGENT,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Delete multiple sessions.

        Args:
            session_ids: List of session IDs to delete
            session_types: List of session types corresponding to each session ID
            session_type: Default session type filter
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, Any] = {"type": session_type.value}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        payload = {
            "session_ids": session_ids,
            "session_types": [st.value for st in session_types],
        }

        await self._adelete("/sessions", payload, params=params, headers=headers)

    async def rename_session(
        self,
        session_id: str,
        session_name: str,
        session_type: SessionType = SessionType.AGENT,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        """Rename a session.

        Args:
            session_id: ID of the session to rename
            session_name: New name for the session
            session_type: Type of session (agent, team, or workflow)
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            AgentSessionDetailSchema, TeamSessionDetailSchema, or WorkflowSessionDetailSchema

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params: Dict[str, Any] = {"type": session_type.value}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        payload = {"session_name": session_name}
        data = await self._apost(f"/sessions/{session_id}/rename", payload, params=params, headers=headers)

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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

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

        payload: Dict[str, Any] = {}
        if session_name is not None:
            payload["session_name"] = session_name
        if session_state is not None:
            payload["session_state"] = session_state
        if metadata is not None:
            payload["metadata"] = metadata
        if summary is not None:
            payload["summary"] = summary

        data = await self._apatch(f"/sessions/{session_id}", payload, params=params, headers=headers)

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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

        Returns:
            PaginatedResponse[EvalSchema]: Paginated list of evaluation runs

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "page": page,
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

        data = await self._aget("/eval-runs", params=params, headers=headers)
        return PaginatedResponse[EvalSchema].model_validate(data)

    async def get_eval_run(
        self,
        eval_run_id: str,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> EvalSchema:
        """Get a specific evaluation run by ID.

        Args:
            eval_run_id: ID of the evaluation run to retrieve
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

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

        data = await self._aget(f"/eval-runs/{eval_run_id}", params=params, headers=headers)
        return EvalSchema.model_validate(data)

    async def delete_eval_runs(
        self,
        eval_run_ids: List[str],
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Delete multiple evaluation runs.

        Args:
            eval_run_ids: List of evaluation run IDs to delete
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id
        if table:
            params["table"] = table

        payload = {"eval_run_ids": eval_run_ids}
        await self._adelete("/eval-runs", payload, params=params, headers=headers)

    async def update_eval_run(
        self,
        eval_run_id: str,
        name: str,
        db_id: Optional[str] = None,
        table: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> EvalSchema:
        """Update an evaluation run (rename).

        Args:
            eval_run_id: ID of the evaluation run to update
            name: New name for the evaluation run
            db_id: Optional database ID to use
            table: Optional table name to use
            headers: HTTP headers to include in the request (optional)

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

        payload = {"name": name}
        data = await self._apatch(f"/eval-runs/{eval_run_id}", payload, params=params, headers=headers)
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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

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

        payload: Dict[str, Any] = {
            "eval_type": eval_type.value,
            "input": input_text,
            "agent_id": agent_id,
            "team_id": team_id,
            "model_id": model_id,
            "model_provider": model_provider,
            "expected_output": expected_output,
            "expected_tool_calls": expected_tool_calls,
            "num_iterations": num_iterations,
        }

        endpoint = "/evals"
        data = await self._apost(endpoint, payload, params=params, headers=headers)
        if data is None:
            return None
        return EvalSchema.model_validate(data)

    # Knowledge Operations

    async def _apost_multipart(
        self,
        endpoint: str,
        form_data: Dict[str, Any],
        files: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Execute asynchronous POST request with multipart form data and optional files.

        Args:
            endpoint: API endpoint path (without base URL)
            form_data: Form data dictionary
            files: Optional files dictionary for multipart upload
            headers: HTTP headers to include in the request (optional)

        Returns:
            Parsed JSON response

        Raises:
            RemoteServerUnavailableError: When the remote server is unavailable
            HTTPStatusError: On HTTP errors (4xx, 5xx)
        """
        url = f"{self.base_url}{endpoint}"

        try:
            async with AsyncClient(timeout=self.timeout) as client:
                if files:
                    response = await client.post(url, data=form_data, files=files, headers=headers or {})
                else:
                    response = await client.post(url, data=form_data, headers=headers or {})
                response.raise_for_status()
                return response.json()
        except (ConnectError, ConnectTimeout) as e:
            raise RemoteServerUnavailableError(
                message=f"Failed to connect to remote server at {self.base_url}",
                base_url=self.base_url,
                original_error=e,
            ) from e
        except TimeoutException as e:
            raise RemoteServerUnavailableError(
                message=f"Request to remote server at {self.base_url} timed out",
                base_url=self.base_url,
                original_error=e,
            ) from e

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
        headers: Optional[Dict[str, str]] = None,
    ) -> ContentResponseSchema:
        """Upload content to the knowledge base.

        Args:
            name: Content name (auto-generated from file/URL if not provided)
            description: Content description
            url: URL to fetch content from (can be a single URL string or a JSON-encoded array of URLs)
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
            headers: HTTP headers to include in the request (optional)

        Returns:
            ContentResponseSchema: The uploaded content info

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = "/knowledge/content"
        if params:
            endpoint += "?" + "&".join(f"{k}={v}" for k, v in params.items())

        # Build multipart form data
        form_data: Dict[str, Any] = {}
        files: Optional[Dict[str, Any]] = None

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
            files = {"file": (file_name or "upload", file_content, file_content_type or "application/octet-stream")}

        data = await self._apost_multipart(endpoint, form_data, files=files, headers=headers)
        return ContentResponseSchema.model_validate(data)

    async def update_content(
        self,
        content_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reader_id: Optional[str] = None,
        db_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> ContentResponseSchema:
        """Update content properties.

        Args:
            content_id: ID of the content to update
            name: New content name
            description: New content description
            metadata: New metadata dictionary
            reader_id: ID of the reader to use
            db_id: Optional database ID to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            ContentResponseSchema: The updated content

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/knowledge/content/{content_id}"

        form_data: Dict[str, Any] = {}
        if name:
            form_data["name"] = name
        if description:
            form_data["description"] = description
        if metadata:
            form_data["metadata"] = json.dumps(metadata)
        if reader_id:
            form_data["reader_id"] = reader_id

        data = await self._arequest("PATCH", endpoint, data=form_data, params=params, headers=headers, as_form=True)
        return ContentResponseSchema.model_validate(data)

    async def list_content(
        self,
        limit: int = 20,
        page: int = 1,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        db_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> PaginatedResponse[ContentResponseSchema]:
        """List all content in the knowledge base.

        Args:
            limit: Number of content entries per page
            page: Page number
            sort_by: Field to sort by
            sort_order: Sort order (asc or desc)
            db_id: Optional database ID to use
            headers: HTTP headers to include in the request (optional)

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
        data = await self._aget(endpoint, headers=headers)
        return PaginatedResponse[ContentResponseSchema].model_validate(data)

    async def get_content(
        self,
        content_id: str,
        db_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> ContentResponseSchema:
        """Get a specific content by ID.

        Args:
            content_id: ID of the content to retrieve
            db_id: Optional database ID to use
            headers: HTTP headers to include in the request (optional)

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

        data = await self._aget(endpoint, headers=headers)
        return ContentResponseSchema.model_validate(data)

    async def delete_content(
        self,
        content_id: str,
        db_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> ContentResponseSchema:
        """Delete a specific content.

        Args:
            content_id: ID of the content to delete
            db_id: Optional database ID to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            ContentResponseSchema: The deleted content info

        Raises:
            HTTPStatusError: On HTTP errors (404 if not found)
        """
        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = f"/knowledge/content/{content_id}"

        data = await self._arequest("DELETE", endpoint, params=params, headers=headers)
        return ContentResponseSchema.model_validate(data)

    async def delete_all_content(
        self,
        db_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Delete all content from the knowledge base.

        WARNING: This is a destructive operation that cannot be undone.

        Args:
            db_id: Optional database ID to use
            headers: HTTP headers to include in the request (optional)

        Returns:
            str: "success" if successful

        Raises:
            HTTPStatusError: On HTTP errors
        """
        params = {}
        if db_id:
            params["db_id"] = db_id

        endpoint = "/knowledge/content"

        return await self._arequest("DELETE", endpoint, params=params, headers=headers)

    async def get_content_status(
        self,
        content_id: str,
        db_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> ContentStatusResponse:
        """Get the processing status of a content item.

        Args:
            content_id: ID of the content
            db_id: Optional database ID to use
            headers: HTTP headers to include in the request (optional)

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

        data = await self._aget(endpoint, headers=headers)
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
        headers: Optional[Dict[str, str]] = None,
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
            headers: HTTP headers to include in the request (optional)

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

        data = await self._apost("/knowledge/search", payload, headers=headers)
        return PaginatedResponse[VectorSearchResult].model_validate(data)

    async def get_knowledge_config(
        self,
        db_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> KnowledgeConfigResponse:
        """Get knowledge base configuration.

        Returns available readers, chunkers, vector DBs, and filters.

        Args:
            db_id: Optional database ID to use
            headers: HTTP headers to include in the request (optional)

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

        data = await self._aget(endpoint, headers=headers)
        return KnowledgeConfigResponse.model_validate(data)
