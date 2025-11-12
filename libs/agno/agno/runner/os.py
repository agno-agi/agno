from typing import Any, AsyncIterator, Dict, Literal, Optional, Sequence, Union, overload, List
import httpx
from agno.agent import Agent

from agno.models.message import Message
from agno.team import Team
from agno.workflow import Workflow
from agno.run import RunContext
from agno.run.agent import RunOutput, RunOutputEvent
from agno.media import Audio, File, Image, Video

from pydantic import BaseModel




class AgentOSRunner:
    def __init__(
        self,
        base_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        timeout: float = 300.0,
    ):
        """Initialize AgentOSRunner for local or remote execution.
        
        For local execution, provide agent/team/workflow instances.
        For remote execution, provide base_url and agent_id/team_id/workflow_id.
        
        Args:
            agent: Local agent instance
            team: Local team instance
            workflow: Local workflow instance
            base_url: Base URL for remote AgentOS instance (e.g., "http://localhost:7777")
            agent_id: ID of remote agent
            team_id: ID of remote team
            workflow_id: ID of remote workflow
            api_key: Optional API key for authentication
            timeout: Request timeout in seconds (default: 300)
        """
        self.base_url = base_url.rstrip("/") if base_url else None
        self.agent_id = agent_id
        self.team_id = team_id
        self.workflow_id = workflow_id
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        """Get HTTP headers for remote requests."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_endpoint(self) -> str:
        """Get the API endpoint for the configured resource."""
        if self.agent_id:
            return f"{self.base_url}/v1/agents/{self.agent_id}/run"
        elif self.team_id:
            return f"{self.base_url}/v1/teams/{self.team_id}/run"
        elif self.workflow_id:
            return f"{self.base_url}/v1/workflows/{self.workflow_id}/run"
        else:
            raise ValueError("No remote resource ID configured")

    def _prepare_request_body(
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
        """Prepare request body for remote API call."""
        body: Dict[str, Any] = {}
        
        # Handle input - convert to string or dict
        if isinstance(input, str):
            body["message"] = input
        elif isinstance(input, Message):
            body["message"] = input.model_dump()
        elif isinstance(input, BaseModel):
            body["message"] = input.model_dump()
        elif isinstance(input, list):
            if input and isinstance(input[0], Message):
                body["messages"] = [msg.model_dump() for msg in input]
            else:
                body["messages"] = input
        else:
            body["message"] = input

        # Add optional parameters
        if stream is not None:
            body["stream"] = stream
        if user_id is not None:
            body["user_id"] = user_id
        if session_id is not None:
            body["session_id"] = session_id
        if session_state is not None:
            body["session_state"] = session_state
        if stream_events is not None:
            body["stream_events"] = stream_events
        if retries is not None:
            body["retries"] = retries
        if knowledge_filters is not None:
            body["knowledge_filters"] = knowledge_filters
        if add_history_to_context is not None:
            body["add_history_to_context"] = add_history_to_context
        if add_dependencies_to_context is not None:
            body["add_dependencies_to_context"] = add_dependencies_to_context
        if add_session_state_to_context is not None:
            body["add_session_state_to_context"] = add_session_state_to_context
        if dependencies is not None:
            body["dependencies"] = dependencies
        if metadata is not None:
            body["metadata"] = metadata
        
        # Add any additional kwargs
        body.update(kwargs)
        
        return body

    async def _remote_arun(
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        stream: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator[Union[RunOutputEvent, RunOutput]]]:
        """Execute remote agent/team/workflow via HTTP API."""
        endpoint = self._get_endpoint()
        headers = self._get_headers()
        body = self._prepare_request_body(input, stream=stream, **kwargs)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if stream:
                # Handle streaming response
                return self._stream_remote_response(client, endpoint, headers, body)
            else:
                # Handle non-streaming response
                response = await client.post(endpoint, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
                return RunOutput(**data)

    async def _stream_remote_response(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
        """Stream response from remote API."""
        async with client.stream("POST", endpoint, json=body, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    # Parse SSE format if used
                    if line.startswith("data: "):
                        line = line[6:]
                    try:
                        import json
                        data = json.loads(line)
                        # Try to parse as RunOutputEvent or RunOutput
                        if "event" in data:
                            yield RunOutputEvent(**data)
                        else:
                            yield RunOutput(**data)
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
        run_context: Optional[RunContext] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        stream_intermediate_steps: Optional[bool] = None,
        retries: Optional[int] = None,
        knowledge_filters: Optional[Dict[str, Any]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        debug_mode: Optional[bool] = None,
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
        run_context: Optional[RunContext] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        stream_intermediate_steps: Optional[bool] = None,
        retries: Optional[int] = None,
        knowledge_filters: Optional[Dict[str, Any]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        yield_run_response: Optional[bool] = None,  # To be deprecated: use yield_run_output instead
        yield_run_output: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]: ...

    def arun(  # type: ignore
        self,
        input: Union[str, List, Dict, Message, BaseModel, List[Message]],
        *,
        stream: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        run_context: Optional[RunContext] = None,
        audio: Optional[Sequence[Audio]] = None,
        images: Optional[Sequence[Image]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        stream_intermediate_steps: Optional[bool] = None,
        retries: Optional[int] = None,
        knowledge_filters: Optional[Dict[str, Any]] = None,
        add_history_to_context: Optional[bool] = None,
        add_dependencies_to_context: Optional[bool] = None,
        add_session_state_to_context: Optional[bool] = None,
        dependencies: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        yield_run_response: Optional[bool] = None,  # To be deprecated: use yield_run_output instead
        yield_run_output: Optional[bool] = None,
        debug_mode: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
        # Route to remote or local execution
        if self.is_remote:
            return self._remote_arun(
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
                **kwargs
            )
        
        # Local execution
        if self.agent:
            return self.agent.arun(input, stream=stream, user_id=user_id, session_id=session_id, session_state=session_state, run_context=run_context, audio=audio, images=images, videos=videos, files=files, stream_events=stream_events, stream_intermediate_steps=stream_intermediate_steps, retries=retries, knowledge_filters=knowledge_filters, add_history_to_context=add_history_to_context, add_dependencies_to_context=add_dependencies_to_context, add_session_state_to_context=add_session_state_to_context, dependencies=dependencies, metadata=metadata, yield_run_response=yield_run_response, yield_run_output=yield_run_output, debug_mode=debug_mode, **kwargs)
        elif self.team:
            return self.team.arun(input, stream=stream, user_id=user_id, session_id=session_id, session_state=session_state, run_context=run_context, audio=audio, images=images, videos=videos, files=files, stream_events=stream_events, stream_intermediate_steps=stream_intermediate_steps, retries=retries, knowledge_filters=knowledge_filters, add_history_to_context=add_history_to_context, add_dependencies_to_context=add_dependencies_to_context, add_session_state_to_context=add_session_state_to_context, dependencies=dependencies, metadata=metadata, yield_run_response=yield_run_response, yield_run_output=yield_run_output, debug_mode=debug_mode, **kwargs)
        elif self.workflow:
            return self.workflow.arun(input, stream=stream, user_id=user_id, session_id=session_id, session_state=session_state, run_context=run_context, audio=audio, images=images, videos=videos, files=files, stream_events=stream_events, stream_intermediate_steps=stream_intermediate_steps, retries=retries, knowledge_filters=knowledge_filters, add_history_to_context=add_history_to_context, add_dependencies_to_context=add_dependencies_to_context, add_session_state_to_context=add_session_state_to_context, dependencies=dependencies, metadata=metadata, yield_run_response=yield_run_response, yield_run_output=yield_run_output, debug_mode=debug_mode, **kwargs)
        else:
            raise ValueError("No agent, team, or workflow provided")