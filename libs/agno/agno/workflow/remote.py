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
        config_ttl: float = 300.0,
    ):
        """Initialize AgentOSRunner for local or remote execution.

        For remote execution, provide base_url and workflow_id.

        Args:
            base_url: Base URL for remote AgentOS instance (e.g., "http://localhost:7777")
            workflow_id: ID of remote workflow
            timeout: Request timeout in seconds (default: 300)
            config_ttl: Time-to-live for cached config in seconds (default: 300)
        """
        super().__init__(base_url, timeout, config_ttl)
        self.workflow_id = workflow_id
        self._cached_workflow_config = None

    @property
    def id(self) -> str:
        return self.workflow_id

    async def get_workflow_config(self) -> "WorkflowResponse":
        """Get the workflow config from remote (always fetches fresh)."""
        return await self.client.aget_workflow(self.workflow_id)

    @property
    def _workflow_config(self) -> "WorkflowResponse":
        """Get the workflow config from remote, cached with TTL."""
        from agno.os.routers.workflows.schema import WorkflowResponse

        current_time = time.time()

        # Check if cache is valid
        if self._cached_workflow_config is not None:
            config, cached_at = self._cached_workflow_config
            if current_time - cached_at < self.config_ttl:
                return config

        # Fetch fresh config
        config: WorkflowResponse = self.client.get_workflow(self.workflow_id)  # type: ignore
        self._cached_workflow_config = (config, current_time)
        return config

    def refresh_config(self) -> "WorkflowResponse":
        """Force refresh the cached workflow config."""
        from agno.os.routers.workflows.schema import WorkflowResponse

        config: WorkflowResponse = self.client.get_workflow(self.workflow_id)
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
        if self._workflow_config is not None and self._workflow_config.db_id is not None:
            return RemoteDb.from_config(
                db_id=self._workflow_config.db_id,
                client=self.client,
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

        if stream:
            # Handle streaming response
            return self.get_client().run_workflow_stream(
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
            return self.get_client().run_workflow(  # type: ignore
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

    async def cancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running workflow execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        try:
            await self.get_client().cancel_workflow_run(
                workflow_id=self.workflow_id,
                run_id=run_id,
                headers=headers,
            )
            return True
        except Exception:
            return False
