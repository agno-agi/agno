import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Tuple, Union, overload

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.remote.base import BaseRemote, RemoteDb, RemoteKnowledge
from agno.run.agent import RunOutput, RunOutputEvent
from agno.utils.agent import validate_input
from agno.utils.log import log_warning
from agno.utils.remote import serialize_input

if TYPE_CHECKING:
    from agno.os.routers.agents.schema import AgentResponse


@dataclass
class RemoteAgent(BaseRemote):
    # Private cache for agent config with TTL: (config, timestamp)
    _cached_agent_config: Optional[Tuple["AgentResponse", float]] = field(default=None, init=False, repr=False)

    knowledge_filters: Optional[Dict[str, Any]] = None
    enable_agentic_knowledge_filters: Optional[bool] = False
    output_schema: Optional[Any] = None
    store_media: bool = True
    store_tool_messages: bool = True
    store_history_messages: bool = False
    send_media_to_model: bool = True
    add_history_to_context: bool = False
    num_history_runs: Optional[int] = None
    num_history_messages: Optional[int] = None
    debug_mode: bool = False
    debug_level: Literal[1, 2] = 1

    def __init__(
        self,
        base_url: str,
        agent_id: str,
        timeout: float = 60.0,
        protocol: Literal["agentos", "a2a"] = "agentos",
        a2a_protocol: Literal["json-rpc", "rest"] = "rest",
        config_ttl: float = 300.0,
    ):
        """Initialize RemoteAgent for remote execution.

        Supports two protocols:
        - "agentos": Agno's proprietary AgentOS REST API (default)
        - "a2a": A2A (Agent-to-Agent) protocol for cross-framework communication

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            agent_id: ID of remote agent on the remote server
            timeout: Request timeout in seconds (default: 60)
            protocol: Communication protocol - "agentos" (default) or "a2a"
            a2a_protocol: For A2A protocol only - Whether to use JSON-RPC or REST protocol.
            config_ttl: Time-to-live for cached config in seconds (default: 300)
        """
        super().__init__(base_url, timeout, protocol, a2a_protocol, config_ttl)
        self.agent_id = agent_id
        self._cached_agent_config = None

    @property
    def id(self) -> str:
        return self.agent_id

    async def get_agent_config(self) -> "AgentResponse":
        """
        Get the agent config from remote.

        For A2A protocol, returns a minimal AgentResponse since A2A servers
        don't expose the same config endpoints as AgentOS. For AgentOS, always fetches fresh config.
        """
        from agno.os.routers.agents.schema import AgentResponse

        if self.a2a_client:
            from agno.client.a2a.schemas import AgentCard

            agent_card: Optional[AgentCard] = await self.a2a_client.aget_agent_card()

            return AgentResponse(
                id=self.agent_id,
                name=agent_card.name if agent_card else self.agent_id,
                description=agent_card.description if agent_card else f"A2A agent: {self.agent_id}",
            )

        return await self.agentos_client.aget_agent(self.agent_id)  # type: ignore

    @property
    def _agent_config(self) -> Optional["AgentResponse"]:
        """
        Get the agent config from remote, cached with TTL.
        Returns None for A2A protocol since A2A servers don't expose agent config endpoints.
        """
        import time

        from agno.os.routers.agents.schema import AgentResponse

        if self.a2a_client:
            from agno.client.a2a.schemas import AgentCard

            agent_card: Optional[AgentCard] = self.a2a_client.get_agent_card()

            return AgentResponse(
                id=self.agent_id,
                name=agent_card.name if agent_card else self.agent_id,
                description=agent_card.description if agent_card else f"A2A agent: {self.agent_id}",
            )

        current_time = time.time()

        # Check if cache is valid
        if self._cached_agent_config is not None:
            config, cached_at = self._cached_agent_config
            if current_time - cached_at < self.config_ttl:
                return config

        # Fetch fresh config
        config: AgentResponse = self.agentos_client.get_agent(self.agent_id)  # type: ignore
        self._cached_agent_config = (config, current_time)
        return config

    async def refresh_config(self) -> Optional["AgentResponse"]:
        """
        Force refresh the cached agent config.
        Returns None for A2A protocol.
        """
        import time

        from agno.os.routers.agents.schema import AgentResponse

        if self.a2a_client:
            self._cached_agent_config = None
            return None

        config: AgentResponse = await self.agentos_client.aget_agent(self.agent_id)  # type: ignore
        self._cached_agent_config = (config, time.time())
        return config

    @property
    def name(self) -> Optional[str]:
        if self._agent_config is not None:
            return self._agent_config.name
        return self.agent_id

    @property
    def description(self) -> Optional[str]:
        if self._agent_config is not None:
            return self._agent_config.description
        return ""

    def role(self) -> Optional[str]:
        if self._agent_config is not None:
            return self._agent_config.role
        return None

    @property
    def tools(self) -> Optional[List[Dict[str, Any]]]:
        if self._agent_config is not None:
            try:
                return json.loads(self._agent_config.tools["tools"]) if self._agent_config.tools else None
            except Exception as e:
                log_warning(f"Failed to load tools for agent {self.agent_id}: {e}")
                return None
        return None

    @property
    def db(self) -> Optional[RemoteDb]:
        if (
            self.agentos_client
            and self._config
            and self._agent_config is not None
            and self._agent_config.db_id is not None
        ):
            return RemoteDb.from_config(
                db_id=self._agent_config.db_id,
                client=self.agentos_client,
                config=self._config,
            )
        return None

    @property
    def knowledge(self) -> Optional[RemoteKnowledge]:
        if self.agentos_client and self._agent_config is not None and self._agent_config.knowledge is not None:
            return RemoteKnowledge(
                client=self.agentos_client,
                contents_db=RemoteDb(
                    id=self._agent_config.knowledge.get("db_id"),  # type: ignore
                    client=self.agentos_client,
                    knowledge_table_name=self._agent_config.knowledge.get("knowledge_table"),
                )
                if self._agent_config.knowledge.get("db_id") is not None
                else None,
            )
        return None

    @property
    def model(self) -> Optional[Model]:
        # We don't expose the remote agent's models, since they can't be used by other services in AgentOS.
        return None

    async def aget_tools(self, **kwargs: Any) -> List[Dict]:
        if self._agent_config is not None and self._agent_config.tools is not None:
            return json.loads(self._agent_config.tools["tools"])
        return []

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
        auth_token: Optional[str] = None,
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
        auth_token: Optional[str] = None,
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
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> Union[
        RunOutput,
        AsyncIterator[RunOutputEvent],
    ]:
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
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                headers=headers,
            )

        # AgentOS protocol path (default)
        if self.agentos_client:
            if stream:
                # Handle streaming response
                return self.agentos_client.run_agent_stream(
                    agent_id=self.agent_id,
                    message=serialized_input,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    session_state=session_state,
                    stream_events=stream_events,
                    retries=retries,
                    knowledge_filters=knowledge_filters,
                    add_history_to_context=add_history_to_context,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    dependencies=dependencies,
                    metadata=metadata,
                    headers=headers,
                    **kwargs,
                )
            else:
                return self.agentos_client.run_agent(  # type: ignore
                    agent_id=self.agent_id,
                    message=serialized_input,
                    session_id=session_id,
                    user_id=user_id,
                    audio=audio,
                    images=images,
                    videos=videos,
                    files=files,
                    session_state=session_state,
                    stream_events=stream_events,
                    retries=retries,
                    knowledge_filters=knowledge_filters,
                    add_history_to_context=add_history_to_context,
                    add_dependencies_to_context=add_dependencies_to_context,
                    add_session_state_to_context=add_session_state_to_context,
                    dependencies=dependencies,
                    metadata=metadata,
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
        audio: Optional[Sequence[Audio]],
        images: Optional[Sequence[Image]],
        videos: Optional[Sequence[Video]],
        files: Optional[Sequence[File]],
        headers: Optional[Dict[str, str]],
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]:
        """Execute via A2A protocol.

        Args:
            message: Serialized message string
            stream: Whether to stream the response
            user_id: User identifier
            context_id: Session/context ID (maps to session_id)
            audio: Audio files to include
            images: Images to include
            videos: Videos to include
            files: Files to include
            headers: HTTP headers to include in the request (optional)

        Returns:
            RunOutput for non-streaming, AsyncIterator[RunOutputEvent] for streaming
        """
        if not self.a2a_client:
            raise ValueError("A2A client not available")
        from agno.client.a2a.utils import map_stream_events_to_run_events

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
            return map_stream_events_to_run_events(event_stream, agent_id=self.agent_id)
        else:
            # Return coroutine for non-streaming
            return self._arun_a2a_send(  # type: ignore[return-value]
                message=message,
                user_id=user_id,
                context_id=context_id,
                audio=audio,
                images=images,
                videos=videos,
                files=files,
                headers=headers,
            )

    async def _arun_a2a_send(
        self,
        message: str,
        user_id: Optional[str],
        context_id: Optional[str],
        audio: Optional[Sequence[Audio]],
        images: Optional[Sequence[Image]],
        videos: Optional[Sequence[Video]],
        files: Optional[Sequence[File]],
        headers: Optional[Dict[str, str]],
    ) -> RunOutput:
        """Send a non-streaming A2A message and convert response to RunOutput."""
        if not self.a2a_client:
            raise ValueError("A2A client not available")
        from agno.client.a2a.utils import map_task_result_to_run_output

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
        return map_task_result_to_run_output(task_result, agent_id=self.agent_id, user_id=user_id)

    @overload
    async def acontinue_run(
        self,
        run_id: str,
        updated_tools: List[ToolExecution],
        stream: Literal[False] = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> RunOutput: ...

    @overload
    def acontinue_run(
        self,
        run_id: str,
        updated_tools: List[ToolExecution],
        stream: Literal[True] = True,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]: ...

    def acontinue_run(  # type: ignore
        self,
        run_id: str,  # type: ignore
        updated_tools: List[ToolExecution],
        stream: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> Union[
        RunOutput,
        AsyncIterator[RunOutputEvent],
    ]:
        headers = self._get_auth_headers(auth_token)

        if self.agentos_client:
            if stream:
                # Handle streaming response
                return self.agentos_client.continue_agent_run_stream(  # type: ignore
                    agent_id=self.agent_id,
                    run_id=run_id,
                    user_id=user_id,
                    session_id=session_id,
                    tools=updated_tools,
                    headers=headers,
                    **kwargs,
                )
            else:
                return self.agentos_client.continue_agent_run(  # type: ignore
                    agent_id=self.agent_id,
                    run_id=run_id,
                    tools=updated_tools,
                    user_id=user_id,
                    session_id=session_id,
                    headers=headers,
                    **kwargs,
                )

        else:
            raise ValueError("No client available")

    async def acancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running agent execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was successfully cancelled, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        if not self.agentos_client:
            raise ValueError("AgentOS client not available")
        try:
            await self.agentos_client.cancel_agent_run(
                agent_id=self.agent_id,
                run_id=run_id,
                headers=headers,
            )
            return True
        except Exception:
            return False
