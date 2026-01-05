import json
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Tuple, Union, overload

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.remote.base import BaseRemote, RemoteDb, RemoteKnowledge
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.utils.agent import validate_input
from agno.utils.log import log_warning
from agno.utils.remote import serialize_input

if TYPE_CHECKING:
    from agno.os.routers.teams.schema import TeamResponse


class RemoteTeam(BaseRemote):
    # Private cache for team config with TTL: (config, timestamp)
    _cached_team_config: Optional[Tuple["TeamResponse", float]] = None

    def __init__(
        self,
        base_url: str,
        team_id: str,
        timeout: float = 300.0,
        protocol: Literal["agentos", "a2a"] = "agentos",
        a2a_protocol: Literal["json-rpc", "rest"] = "json-rpc",
        config_ttl: float = 300.0,
    ):
        """Initialize RemoteTeam for remote execution.

        Supports two protocols:
        - "agentos": Agno's proprietary AgentOS REST API (default)
        - "a2a": A2A (Agent-to-Agent) protocol for cross-framework communication

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            team_id: ID of remote team on the remote server
            timeout: Request timeout in seconds (default: 300)
            protocol: Communication protocol - "agentos" (default) or "a2a"
            a2a_protocol: For A2A protocol only - Whether to use JSON-RPC or REST protocol.
            config_ttl: Time-to-live for cached config in seconds (default: 300)
        """
        super().__init__(base_url, timeout, protocol, a2a_protocol, config_ttl)
        self.team_id = team_id
        self._cached_team_config = None

    @property
    def id(self) -> str:
        return self.team_id

    async def get_team_config(self) -> "TeamResponse":
        """
        Get the team config from remote.

        - For AgentOS protocol, always fetches fresh config from the remote.
        - For A2A protocol, returns a minimal TeamResponse because A2A servers
          do not expose detailed config endpoints.

        Returns:
            TeamResponse: The remote team configuration.
        """
        from agno.os.routers.teams.schema import TeamResponse

        # TODO: Implement A2A _agent_card to get the team config
        if self.protocol == "a2a":
            # Return minimal config for A2A
            return TeamResponse(
                id=self.team_id,
                name=self.team_id,
                description="A2A team: {}".format(self.team_id),
            )

        # Fetch fresh config from remote for AgentOS
        return await self.agentos_client.aget_team(self.team_id)

    @property
    def _team_config(self) -> Optional["TeamResponse"]:
        """
        Get the team config from remote, cached with TTL.

        - Returns None for A2A protocol (no config available).
        - For AgentOS protocol, uses TTL caching for efficiency.
        """
        import time

        from agno.os.routers.teams.schema import TeamResponse

        # TODO: Implement A2A _agent_card to get the team config
        if self.protocol == "a2a":
            # Return minimal config for A2A
            return TeamResponse(
                id=self.team_id,
                name=self.team_id,
                description="A2A team: {}".format(self.team_id),
            )

        current_time = time.time()
        if self._cached_team_config is not None:
            config, cached_at = self._cached_team_config
            if current_time - cached_at < self.config_ttl:
                return config

        # Fetch fresh config and update cache
        config: TeamResponse = self.agentos_client.get_team(self.team_id)  # type: ignore
        self._cached_team_config = (config, current_time)
        return config

    def refresh_config(self) -> Optional["TeamResponse"]:
        """
        Force refresh the cached team config from remote.
        """
        import time

        from agno.os.routers.teams.schema import TeamResponse

        if self.protocol == "a2a":
            return None

        config: TeamResponse = self.agentos_client.get_team(self.team_id)
        self._cached_team_config = (config, time.time())
        return config

    @property
    def name(self) -> Optional[str]:
        config = self._team_config
        if config is not None:
            return config.name
        return self.team_id

    @property
    def description(self) -> Optional[str]:
        config = self._team_config
        if config is not None:
            return config.description
        return ""

    def role(self) -> Optional[str]:
        if self._team_config is not None:
            return self._team_config.role
        return None

    @property
    def tools(self) -> Optional[List[Dict[str, Any]]]:
        if self._team_config is not None:
            try:
                return json.loads(self._team_config.tools["tools"]) if self._team_config.tools else None
            except Exception as e:
                log_warning(f"Failed to load tools for team {self.team_id}: {e}")
                return None
        return None

    @property
    def db(self) -> Optional[RemoteDb]:
        if self._team_config is not None and self._team_config.db_id is not None:
            return RemoteDb.from_config(
                db_id=self._team_config.db_id,
                client=self.agentos_client,
                config=self._config,
            )
        return None

    @property
    def knowledge(self) -> Optional[RemoteKnowledge]:
        """Whether the team has knowledge enabled."""
        if self._team_config is not None and self._team_config.knowledge is not None:
            return RemoteKnowledge(
                client=self.agentos_client,
                contents_db=RemoteDb(
                    id=self._team_config.knowledge.get("db_id"),  # type: ignore
                    client=self.agentos_client,
                    knowledge_table_name=self._team_config.knowledge.get("knowledge_table"),
                )
                if self._team_config.knowledge.get("db_id") is not None
                else None,
            )
        return None

    @property
    def model(self) -> Optional[Model]:
        # We don't expose the remote team's models, since they can't be used by other services in AgentOS.
        return None

    @property
    def user_id(self) -> Optional[str]:
        return None

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
    ) -> TeamRunOutput: ...

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
    ) -> AsyncIterator[TeamRunOutputEvent]: ...

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
        TeamRunOutput,
        AsyncIterator[RunOutputEvent],
    ]:
        validated_input = validate_input(input)
        serialized_input = serialize_input(validated_input)
        headers = self._get_auth_headers(auth_token)

        # A2A protocol path
        if self.protocol == "a2a":
            return self._arun_a2a(  # type: ignore[return-value]
                message=serialized_input,
                stream=stream or False,
                user_id=user_id,
                context_id=session_id,  # Map session_id → context_id for A2A
                images=images,
                files=files,
            )

        # AgentOS protocol path (default)
        if stream:
            # Handle streaming response
            return self.get_client().run_team_stream(  # type: ignore
                team_id=self.team_id,
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
            return self.get_client().run_team(  # type: ignore
                team_id=self.team_id,
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

    def _arun_a2a(
        self,
        message: str,
        stream: bool,
        user_id: Optional[str],
        context_id: Optional[str],
        images: Optional[Sequence[Image]],
        files: Optional[Sequence[File]],
    ) -> Union[TeamRunOutput, AsyncIterator[TeamRunOutputEvent]]:
        """Execute via A2A protocol.

        Args:
            message: Serialized message string
            stream: Whether to stream the response
            user_id: User identifier
            context_id: Session/context ID (maps to session_id)
            images: Images to include
            files: Files to include

        Returns:
            TeamRunOutput for non-streaming, AsyncIterator[TeamRunOutputEvent] for streaming
        """
        from agno.client.a2a.utils import map_stream_events_to_team_run_events

        if stream:
            # Return async generator for streaming
            event_stream = self.a2a_client.stream_message(
                message=message,
                context_id=context_id,
                user_id=user_id,
                images=list(images) if images else None,
                files=list(files) if files else None,
            )
            return map_stream_events_to_team_run_events(event_stream, team_id=self.team_id)
        else:
            # Return coroutine for non-streaming
            return self._arun_a2a_send(  # type: ignore[return-value]
                message=message,
                user_id=user_id,
                context_id=context_id,
                images=images,
                files=files,
            )

    async def _arun_a2a_send(
        self,
        message: str,
        user_id: Optional[str],
        context_id: Optional[str],
        images: Optional[Sequence[Image]],
        files: Optional[Sequence[File]],
    ) -> TeamRunOutput:
        """Send a non-streaming A2A message and convert response to TeamRunOutput."""
        from agno.client.a2a.utils import map_task_result_to_team_run_output

        task_result = await self.a2a_client.send_message(
            message=message,
            context_id=context_id,
            user_id=user_id,
            images=list(images) if images else None,
            files=list(files) if files else None,
        )
        return map_task_result_to_team_run_output(task_result, team_id=self.team_id)

    async def cancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running team execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        try:
            await self.agentos_client.cancel_team_run(  # type: ignore
                team_id=self.team_id,
                run_id=run_id,
                headers=headers,
            )
            return True
        except Exception:
            return False
