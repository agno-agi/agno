import json
from os import getenv
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Union, overload

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput, RunOutputEvent, run_output_event_from_dict
from agno.run.team import TeamRunOutput, TeamRunOutputEvent, team_run_output_event_from_dict
from agno.run.workflow import WorkflowRunOutput, WorkflowRunOutputEvent, workflow_run_output_event_from_dict
from agno.runner.base import BaseRunner

try:
    from httpx import AsyncClient
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


class AgentOSRunner(BaseRunner):
    def __init__(
        self,
        base_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 300.0,
    ):
        """Initialize AgentOSRunner for local or remote execution.

        For local execution, provide agent/team/workflow instances.
        For remote execution, provide base_url and agent_id/team_id/workflow_id.

        Args:
            base_url: Base URL for remote AgentOS instance (e.g., "http://localhost:7777")
            agent_id: ID of remote agent
            team_id: ID of remote team
            workflow_id: ID of remote workflow
            api_key: API key for authentication. Will default to AGNO_API_KEY environment variable if not provided.
            timeout: Request timeout in seconds (default: 300)
        """
        super().__init__(base_url, agent_id, team_id, workflow_id)

        self.api_key: Optional[str] = api_key or getenv("AGNO_API_KEY")
        self.timeout: float = timeout

    def get_client(self) -> "AgentOSClient":
        """Get an AgentOSClient for fetching remote configuration.

        This is used internally by AgentOS to fetch configuration from remote
        AgentOS instances when this runner represents a remote resource.

        Returns:
            AgentOSClient: Client configured for this remote resource's base URL
        """
        from agno.os.client import AgentOSClient

        return AgentOSClient(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=30.0,
        )


    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for remote requests."""
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_runs_endpoint(self) -> str:
        """Get the API endpoint for the configured resource."""
        if self.agent_id:
            return f"{self.base_url}/agents/{self.agent_id}/runs"
        elif self.team_id:
            return f"{self.base_url}/teams/{self.team_id}/runs"
        elif self.workflow_id:
            return f"{self.base_url}/workflows/{self.workflow_id}/runs"
        else:
            raise ValueError("No remote resource ID configured")

    def _get_continue_run_endpoint(self, run_id: str) -> str:
        """Get the API endpoint for the configured resource."""
        if self.agent_id:
            return f"{self.base_url}/agents/{self.agent_id}/runs/{run_id}/continue"
        elif self.team_id:
            return f"{self.base_url}/teams/{self.team_id}/runs/{run_id}/continue"
        elif self.workflow_id:
            return f"{self.base_url}/workflows/{self.workflow_id}/runs/{run_id}/continue"
        else:
            raise ValueError("No remote resource ID configured")

    def _get_cancel_run_endpoint(self, run_id: str) -> str:
        """Get the API endpoint for the configured resource."""
        if self.agent_id:
            return f"{self.base_url}/agents/{self.agent_id}/runs/{run_id}/cancel"
        elif self.team_id:
            return f"{self.base_url}/teams/{self.team_id}/runs/{run_id}/cancel"
        elif self.workflow_id:
            return f"{self.base_url}/workflows/{self.workflow_id}/runs/{run_id}/cancel"
        else:
            raise ValueError("No remote resource ID configured")

    def _prepare_runs_request_body(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        stream: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        retries: Optional[int] = None,
        knowledge_filters: Optional[Dict[str, Any]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Prepare request body for remote API call as URL-encoded form data."""

        body: Dict[str, Any] = {}

        # Handle input - convert to string
        if isinstance(input, str):
            body["message"] = input
        elif isinstance(input, Message):
            # Convert Message to JSON string for form data
            body["message"] = json.dumps(input.model_dump())
        elif isinstance(input, BaseModel):
            body["message"] = json.dumps(input.model_dump())
        elif isinstance(input, (list, dict)):
            # Convert complex types to JSON string
            body["message"] = json.dumps(input)
        else:
            body["message"] = str(input)

        # Add optional parameters
        # Booleans and strings can be passed directly
        if stream is not None:
            body["stream"] = str(stream).lower()
        if user_id is not None:
            body["user_id"] = user_id
        if session_id is not None:
            body["session_id"] = session_id

        # JSON parameters must be serialized to strings for form data
        if session_state is not None:
            body["session_state"] = json.dumps(session_state)
        if stream_events is not None:
            body["stream_events"] = str(stream_events).lower()
        if retries is not None:
            body["retries"] = str(retries)
        if knowledge_filters is not None:
            body["knowledge_filters"] = json.dumps(knowledge_filters)
        if add_history_to_context is not None:
            body["add_history_to_context"] = str(add_history_to_context).lower()
        if add_dependencies_to_context is not None:
            body["add_dependencies_to_context"] = str(add_dependencies_to_context).lower()
        if add_session_state_to_context is not None:
            body["add_session_state_to_context"] = str(add_session_state_to_context).lower()
        if dependencies is not None:
            body["dependencies"] = json.dumps(dependencies)
        if metadata is not None:
            body["metadata"] = json.dumps(metadata)

        # Add any additional kwargs, converting complex types to JSON strings
        for key, value in kwargs.items():
            if isinstance(value, (dict, list)):
                body[key] = json.dumps(value)
            elif isinstance(value, bool):
                body[key] = str(value).lower()
            elif value is not None:
                body[key] = str(value)

        return body

    def _prepare_continue_runs_request_body(
        self,
        run_id: Optional[str] = None,  # type: ignore
        updated_tools: Optional[List[ToolExecution]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        stream: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Prepare request body for remote API call as URL-encoded form data."""

        body: Dict[str, Any] = {}

        if run_id is not None:
            body["run_id"] = run_id
        if updated_tools is not None:
            body["tools"] = json.dumps([tool.to_dict() for tool in updated_tools])
        if session_id is not None:
            body["session_id"] = session_id
        if user_id is not None:
            body["user_id"] = user_id
        if stream is not None:
            body["stream"] = str(stream).lower()
        return body

    async def _remote_arun(
        self,
        endpoint: str,
        body: Dict[str, Any],
    ) -> Union[RunOutput, TeamRunOutput, WorkflowRunOutput]:
        """Execute remote agent/team/workflow via HTTP API."""
        headers = self._get_headers()

        async with AsyncClient(timeout=self.timeout) as client:
            # Handle non-streaming response - use data for URL-encoded form
            response = await client.post(endpoint, data=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            if self.agent_id:
                return RunOutput.from_dict(data)
            elif self.team_id:
                return TeamRunOutput.from_dict(data)
            elif self.workflow_id:
                return WorkflowRunOutput.from_dict(data)
            else:
                raise ValueError("No remote resource ID configured")

    async def _stream_remote_arun(
        self,
        endpoint: str,
        body: Dict[str, Any],
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]]:
        """Stream response from remote API."""
        headers = self._get_headers()

        async with AsyncClient(timeout=self.timeout) as client:
            # Use data instead of json for URL-encoded form data
            async with client.stream("POST", endpoint, data=body, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        # Parse SSE format if used
                        if line.startswith("data: "):
                            line = line[6:]
                        try:
                            data = json.loads(line)
                            if self.agent_id:
                                yield run_output_event_from_dict(data)  # type: ignore
                            elif self.team_id:
                                yield team_run_output_event_from_dict(data)  # type: ignore
                            elif self.workflow_id:
                                yield workflow_run_output_event_from_dict(data)  # type: ignore
                        except Exception:
                            # Skip unparseable lines
                            continue

    @overload
    async def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[False] = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        retries: Optional[int] = None,
        knowledge_filters: Optional[Dict[str, Any]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, TeamRunOutput, WorkflowRunOutput]: ...

    @overload
    def arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Literal[True] = True,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        retries: Optional[int] = None,
        knowledge_filters: Optional[Dict[str, Any]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]]: ...

    def arun(  # type: ignore
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        retries: Optional[int] = None,
        knowledge_filters: Optional[Dict[str, Any]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Union[
        RunOutput,
        TeamRunOutput,
        WorkflowRunOutput,
        AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]],
    ]:
        endpoint = self._get_runs_endpoint()
        body = self._prepare_runs_request_body(
            input,
            stream=stream,
            user_id=user_id,
            session_id=session_id,
            session_state=session_state,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream_events=stream_events,
            retries=retries,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            dependencies=dependencies,
            metadata=metadata,
            **kwargs,
        )

        if stream:
            # Handle streaming response
            return self._stream_remote_arun(
                endpoint=endpoint,
                body=body,
            )
        else:
            return self._remote_arun(  # type: ignore
                endpoint=endpoint,
                body=body,
            )

    @overload
    async def acontinue_run(
        self,
        run_id: str,
        stream: Literal[False] = False,
        stream_events: Optional[bool] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Union[RunOutput, TeamRunOutput, WorkflowRunOutput]: ...

    @overload
    def acontinue_run(
        self,
        run_id: str,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]]: ...

    def acontinue_run(  # type: ignore
        self,
        run_id: str,  # type: ignore
        stream: Optional[bool] = None,
        stream_events: Optional[bool] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Union[
        RunOutput,
        TeamRunOutput,
        WorkflowRunOutput,
        AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]],
    ]:
        endpoint = self._get_continue_run_endpoint(run_id)
        body = self._prepare_continue_runs_request_body(run_id, updated_tools, session_id, user_id, stream)

        if stream:
            # Handle streaming response
            return self._stream_remote_arun(
                endpoint=endpoint,
                body=body,
            )
        else:
            return self._remote_arun(  # type: ignore
                endpoint=endpoint,
                body=body,
            )

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a running agent execution.

        Args:
            run_id (str): The run_id to cancel.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        endpoint = self._get_cancel_run_endpoint(run_id)
        headers = self._get_headers()
        async with AsyncClient(timeout=self.timeout) as client:
            # Use data instead of json for URL-encoded form data
            async with client.stream("POST", endpoint, headers=headers) as response:
                response.raise_for_status()
                return True
