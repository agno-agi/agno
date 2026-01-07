import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Tuple, Union, overload

from fastapi import WebSocket
from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.remote.base import BaseRemote, RemoteDb
from agno.run.workflow import WorkflowRunOutput, WorkflowRunOutputEvent
from agno.utils.agent import validate_input
from agno.utils.remote import serialize_input

if TYPE_CHECKING:
    from agno.os.routers.workflows.schema import WorkflowResponse


class RemoteWorkflow(BaseRemote):
    # Private cache for workflow config with TTL: (config, timestamp)
    _cached_workflow_config: Optional[Tuple["WorkflowResponse", float]] = None

    def __init__(
        self,
        base_url: str,
        workflow_id: str,
        timeout: float = 300.0,
        protocol: Literal["agentos", "a2a"] = "agentos",
        a2a_protocol: Literal["json-rpc", "rest"] = "rest",
        config_ttl: float = 300.0,
    ):
        """Initialize RemoteWorkflow for remote execution.

        Supports two protocols:
        - "agentos": Agno's proprietary AgentOS REST API (default)
        - "a2a": A2A (Agent-to-Agent) protocol for cross-framework communication

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            workflow_id: ID of remote workflow on the remote server
            timeout: Request timeout in seconds (default: 300)
            protocol: Communication protocol - "agentos" (default) or "a2a"
            a2a_protocol: For A2A protocol only - Whether to use JSON-RPC or REST protocol.
            config_ttl: Time-to-live for cached config in seconds (default: 300)
        """
        super().__init__(base_url, timeout, protocol, a2a_protocol, config_ttl)
        self.workflow_id = workflow_id
        self._cached_workflow_config = None
        self._config_ttl = config_ttl

    @property
    def id(self) -> str:
        return self.workflow_id

    async def get_workflow_config(self) -> "WorkflowResponse":
        """Get the workflow config from remote (always fetches fresh)."""
        from agno.os.routers.workflows.schema import WorkflowResponse

        if self.protocol == "a2a":
            from agno.client.a2a.schemas import AgentCard

            agent_card: Optional[AgentCard] = await self.a2a_client.aget_agent_card()  # type: ignore

            return WorkflowResponse(
                id=self.workflow_id,
                name=agent_card.name if agent_card else self.workflow_id,
                description=agent_card.description if agent_card else f"A2A workflow: {self.workflow_id}",
            )

        # AgentOS protocol: fetch fresh config from remote
        return await self.agentos_client.aget_workflow(self.workflow_id)  # type: ignore

    @property
    def _workflow_config(self) -> "WorkflowResponse":
        """Get the workflow config from remote, cached with TTL."""
        from agno.os.routers.workflows.schema import WorkflowResponse

        if self.protocol == "a2a":
            from agno.client.a2a.schemas import AgentCard

            agent_card: Optional[AgentCard] = self.a2a_client.get_agent_card()  # type: ignore

            return WorkflowResponse(
                id=self.workflow_id,
                name=agent_card.name if agent_card else self.workflow_id,
                description=agent_card.description if agent_card else f"A2A workflow: {self.workflow_id}",
            )

        current_time = time.time()

        # Check if cache is valid
        if self._cached_workflow_config is not None:
            config, cached_at = self._cached_workflow_config
            if current_time - cached_at < self.config_ttl:
                return config

        # Fetch fresh config
        config: WorkflowResponse = self.agentos_client.get_workflow(self.workflow_id)  # type: ignore
        self._cached_workflow_config = (config, current_time)
        return config

    async def refresh_config(self) -> "WorkflowResponse":
        """Force refresh the cached workflow config."""
        from agno.os.routers.workflows.schema import WorkflowResponse

        config: WorkflowResponse = await self.agentos_client.aget_workflow(self.workflow_id)  # type: ignore
        self._cached_workflow_config = (config, time.time())
        return config

    @property
    def name(self) -> Optional[str]:
        if self._workflow_config is not None:
            return self._workflow_config.name
        return None

    @property
    def description(self) -> Optional[str]:
        if self._workflow_config is not None:
            return self._workflow_config.description
        return None

    @property
    def db(self) -> Optional[RemoteDb]:
        if (
            self.agentos_client
            and self._config
            and self._workflow_config is not None
            and self._workflow_config.db_id is not None
        ):
            return RemoteDb.from_config(
                db_id=self._workflow_config.db_id,
                client=self.agentos_client,
                config=self._config,
            )
        return None

    @overload
    async def arun(
        self,
        input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        stream: Literal[False] = False,
        stream_events: Optional[bool] = None,
        stream_intermediate_steps: Optional[bool] = None,
        background: Optional[bool] = False,
        websocket: Optional[WebSocket] = None,
        background_tasks: Optional[Any] = None,
        auth_token: Optional[str] = None,
    ) -> WorkflowRunOutput: ...

    @overload
    def arun(
        self,
        input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]]] = None,
        additional_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        stream: Literal[True] = True,
        stream_events: Optional[bool] = None,
        stream_intermediate_steps: Optional[bool] = None,
        background: Optional[bool] = False,
        websocket: Optional[WebSocket] = None,
        background_tasks: Optional[Any] = None,
        auth_token: Optional[str] = None,
    ) -> AsyncIterator[WorkflowRunOutputEvent]: ...

    def arun(  # type: ignore
        self,
        input: Union[str, Dict[str, Any], List[Any], BaseModel, List[Message]],
        additional_data: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        session_id: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        audio: Optional[List[Audio]] = None,
        images: Optional[List[Image]] = None,
        videos: Optional[List[Video]] = None,
        files: Optional[List[File]] = None,
        stream: bool = False,
        stream_events: Optional[bool] = None,
        background: Optional[bool] = False,
        websocket: Optional[WebSocket] = None,
        background_tasks: Optional[Any] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> Union[WorkflowRunOutput, AsyncIterator[WorkflowRunOutputEvent]]:
        # TODO: Deal with background
        validated_input = validate_input(input)
        serialized_input = serialize_input(validated_input)
        headers = self._get_auth_headers(auth_token)

        # A2A protocol path
        if self.a2a_client:
            return self._arun_a2a(  # type: ignore[return-value]
                message=serialized_input,
                stream=stream or False,
                user_id=user_id,
                context_id=session_id,  # Map session_id → context_id for A2A
                images=images,
                videos=videos,
                audio=audio,
                files=files,
                headers=headers,
            )

        # AgentOS protocol path (default)
        if self.agentos_client:
            if stream:
                # Handle streaming response
                return self.agentos_client.run_workflow_stream(
                    workflow_id=self.workflow_id,
                    message=serialized_input,
                    additional_data=additional_data,
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    session_state=session_state,
                    stream_events=stream_events,
                    headers=headers,
                    **kwargs,
                )
            else:
                return self.agentos_client.run_workflow(  # type: ignore
                    workflow_id=self.workflow_id,
                    message=serialized_input,
                    additional_data=additional_data,
                    run_id=run_id,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    session_state=session_state,
                    headers=headers,
                    **kwargs,
                )
        else:
            raise ValueError("No client available")

    def _arun_a2a(
        self,
        message: str,
        stream: bool,
        user_id: Optional[str],
        context_id: Optional[str],
        images: Optional[List[Image]],
        videos: Optional[List[Video]],
        audio: Optional[List[Audio]],
        files: Optional[List[File]],
        headers: Optional[Dict[str, str]],
    ) -> Union[WorkflowRunOutput, AsyncIterator[WorkflowRunOutputEvent]]:
        """Execute via A2A protocol.

        Args:
            message: Serialized message string
            stream: Whether to stream the response
            user_id: User identifier
            context_id: Session/context ID (maps to session_id)
            images: Images to include
            videos: Videos to include
            audio: Audio files to include
            files: Files to include
            headers: HTTP headers to include in the request (optional)
        Returns:
            WorkflowRunOutput for non-streaming, AsyncIterator[WorkflowRunOutputEvent] for streaming
        """
        if not self.a2a_client:
            raise ValueError("A2A client not available")
        from agno.client.a2a.utils import map_stream_events_to_workflow_run_events

        if stream:
            # Return async generator for streaming
            event_stream = self.a2a_client.stream_message(
                message=message,
                context_id=context_id,
                user_id=user_id,
                images=list(images) if images else None,
                audio=list(audio) if audio else None,
                videos=list(videos) if videos else None,
                files=list(files) if files else None,
                headers=headers,
            )
            return map_stream_events_to_workflow_run_events(event_stream, workflow_id=self.workflow_id)  # type: ignore
        else:
            # Return coroutine for non-streaming
            return self._arun_a2a_send(  # type: ignore[return-value]
                message=message,
                user_id=user_id,
                context_id=context_id,
                images=images,
                audio=audio,
                videos=videos,
                files=files,
                headers=headers,
            )

    async def _arun_a2a_send(
        self,
        message: str,
        user_id: Optional[str],
        context_id: Optional[str],
        images: Optional[List[Image]],
        videos: Optional[List[Video]],
        audio: Optional[List[Audio]],
        files: Optional[List[File]],
        headers: Optional[Dict[str, str]],
    ) -> WorkflowRunOutput:
        """Send a non-streaming A2A message and convert response to WorkflowRunOutput."""
        if not self.a2a_client:
            raise ValueError("A2A client not available")
        from agno.client.a2a.utils import map_task_result_to_workflow_run_output

        task_result = await self.a2a_client.send_message(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=list(images) if images else None,
            audio=list(audio) if audio else None,
            videos=list(videos) if videos else None,
            files=list(files) if files else None,
            headers=headers,
        )
        return map_task_result_to_workflow_run_output(task_result, workflow_id=self.workflow_id, user_id=user_id)

    async def acancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running workflow execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        try:
            await self.get_os_client().cancel_workflow_run(
                workflow_id=self.workflow_id,
                run_id=run_id,
                headers=headers,
            )
            return True
        except Exception:
            return False
