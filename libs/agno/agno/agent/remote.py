import json
from functools import cached_property
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Union, overload

from pydantic import BaseModel

from agno.db.base import AsyncBaseDb, BaseDb
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.remote.base import BaseRemote
from agno.run.agent import RunOutput, RunOutputEvent, run_output_event_from_dict

from httpx import AsyncClient, ConnectError, ConnectTimeout, TimeoutException
from agno.models.base import Model
from agno.exceptions import RemoteServerUnavailableError


class RemoteAgent(BaseRemote):
    def __init__(
        self,
        base_url: str,
        agent_id: str,
        timeout: float = 60.0,
    ):
        """Initialize AgentOSRunner for local or remote execution.

        For remote execution, provide base_url and agent_id.

        Args:
            base_url: Base URL for remote AgentOS instance (e.g., "http://localhost:7777")
            agent_id: ID of remote agent
            timeout: Request timeout in seconds (default: 60)
        """
        super().__init__(base_url, timeout)
        self.agent_id = agent_id

    @property
    def id(self) -> str:
        return self.agent_id

    @cached_property
    def _agent_config(self) -> "AgentResponse":
        """Get the agent config from remote, cached after first access."""
        from agno.os.routers.agents.schema import AgentResponse
        config: AgentResponse = self.client.get_agent(self.agent_id)
        return config

    @cached_property
    def name(self) -> str:
        if self._agent_config is not None:
            return self._agent_config.name
        return self.agent_id

    @cached_property
    def description(self) -> str:
        if self._agent_config is not None:
            return self._agent_config.description
        return ""

    @cached_property
    def db_id(self) -> Optional[str]:
        return self._agent_config.db_id if self._agent_config else None
    
    @cached_property
    def model(self) -> Model:
        model_response = self._agent_config.model
        return Model(id=model_response.id, provider=model_response.provider)
        

    def _get_runs_endpoint(self) -> str:
        """Get the API endpoint for the configured resource."""
        return f"{self.base_url}/agents/{self.agent_id}/runs"

    def _get_continue_run_endpoint(self, run_id: str) -> str:
        """Get the API endpoint for the configured resource."""
        return f"{self.base_url}/agents/{self.agent_id}/runs/{run_id}/continue"

    def _get_cancel_run_endpoint(self, run_id: str) -> str:
        """Get the API endpoint for the configured resource."""
        return f"{self.base_url}/agents/{self.agent_id}/runs/{run_id}/cancel"

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
    ) -> RunOutput:
        """Execute remote agent/team/workflow via HTTP API."""
        headers = self._get_headers()

        async with AsyncClient(timeout=self.timeout) as client:
            # Handle non-streaming response - use data for URL-encoded form
            response = await client.post(endpoint, data=body, headers=headers)
            response.raise_for_status()
            data = response.json()
            return RunOutput.from_dict(data)

    async def _stream_remote_arun(
        self,
        endpoint: str,
        body: Dict[str, Any],
    ) -> AsyncIterator[RunOutputEvent]:
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
                            yield run_output_event_from_dict(data)  # type: ignore
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
    ) -> RunOutput: ...

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
    ) -> AsyncIterator[RunOutputEvent]: ...

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
        AsyncIterator[RunOutputEvent],
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
    ) -> RunOutput: ...

    @overload
    def acontinue_run(
        self,
        run_id: str,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[RunOutputEvent]: ...

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
        AsyncIterator[RunOutputEvent],
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
