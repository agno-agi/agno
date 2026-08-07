import json
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Tuple, Union, overload

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.remote.base import BaseRemote, RemoteDb, RemoteKnowledge
from agno.remote.http import (
    aget_json,
    apost_form,
    astream_form_events,
    build_continue_form_data,
    build_run_form_data,
    get_json,
)
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent, team_run_output_event_from_dict
from agno.utils.agent import validate_input
from agno.utils.log import log_error, log_warning
from agno.utils.remote import serialize_input

if TYPE_CHECKING:
    from agno.os.routers.teams.schema import TeamResponse


class RemoteTeam(BaseRemote):
    # Private cache for team config with TTL: (config, timestamp)
    _cached_team_config: Optional[Tuple["TeamResponse", float]] = None

    knowledge_filters: Optional[Dict[str, Any]] = None
    enable_agentic_knowledge_filters: Optional[bool] = False

    def __init__(
        self,
        base_url: str,
        team_id: str,
        timeout: float = 300.0,
        config_ttl: float = 300.0,
        api_prefix: str = "/remote",
    ):
        """Initialize RemoteTeam for remote execution.

        Executes the team on a remote AgentOS instance through its RemoteAccess interface.
        The remote AgentOS must mount the RemoteAccess interface (agno.os.interfaces.remote_access.RemoteAccess)
        and pass this team to it; teams not exposed through the interface are not
        remotely callable.

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            team_id: ID of remote team on the remote server
            timeout: Request timeout in seconds (default: 300)
            config_ttl: Time-to-live for cached config in seconds (default: 300)
            api_prefix: Path prefix where the RemoteAccess interface is mounted on the remote
                AgentOS (default: "/remote")
        """
        super().__init__(base_url, timeout, config_ttl, api_prefix)
        self.team_id = team_id
        self._cached_team_config = None

    @property
    def id(self) -> str:
        return self.team_id

    async def get_team_config(self) -> "TeamResponse":
        """Get the team config from the RemoteAccess interface. Always fetches fresh config.

        Returns a placeholder TeamResponse when the remote server is unreachable so
        listings and gateways can render the team instead of failing.
        """
        from agno.exceptions import RemoteServerUnavailableError
        from agno.os.routers.teams.schema import TeamResponse

        try:
            data = await aget_json(self.base_url, f"{self.api_prefix}/teams/{self.team_id}", timeout=self.timeout)
        except RemoteServerUnavailableError:
            log_error(f"RemoteTeam '{self.team_id}' at {self.base_url} is unreachable, likely offline")
            return TeamResponse(
                id=self.team_id,
                name=self.team_id,
                description="RemoteTeam is unreachable, likely offline",
            )
        return TeamResponse.model_validate(data)

    @property
    def _team_config(self) -> Optional["TeamResponse"]:
        """Get the team config from the RemoteAccess interface, cached with TTL.

        Returns None when the remote server is unreachable; failures are not cached,
        so the next access retries.
        """
        import time

        from agno.exceptions import RemoteServerUnavailableError
        from agno.os.routers.teams.schema import TeamResponse

        current_time = time.time()
        if self._cached_team_config is not None:
            cached_config, cached_at = self._cached_team_config
            if current_time - cached_at < self.config_ttl:
                return cached_config

        # Fetch fresh config and update cache
        try:
            config: TeamResponse = TeamResponse.model_validate(
                get_json(self.base_url, f"{self.api_prefix}/teams/{self.team_id}", timeout=self.timeout)
            )
        except RemoteServerUnavailableError:
            log_error(f"RemoteTeam '{self.team_id}' at {self.base_url} is unreachable, likely offline")
            return None
        self._cached_team_config = (config, current_time)
        return config

    async def refresh_config(self) -> Optional["TeamResponse"]:
        """Force refresh the cached team config from remote."""
        import time

        from agno.os.routers.teams.schema import TeamResponse

        config: TeamResponse = TeamResponse.model_validate(
            await aget_json(self.base_url, f"{self.api_prefix}/teams/{self.team_id}", timeout=self.timeout)
        )
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
                log_warning(f"Failed to load tools for team {self.team_id}: {str(e)}")
                return None
        return None

    @property
    def db(self) -> Optional[RemoteDb]:
        if (
            self.agentos_client
            and self._config
            and self._team_config is not None
            and self._team_config.db_id is not None
        ):
            return RemoteDb.from_config(
                db_id=self._team_config.db_id,
                client=self.agentos_client,
                config=self._config,
            )
        return None

    @property
    def knowledge(self) -> Optional[RemoteKnowledge]:
        """Whether the team has knowledge enabled."""
        if self.agentos_client and self._team_config is not None and self._team_config.knowledge is not None:
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

        path = f"{self.api_prefix}/teams/{self.team_id}/runs"
        form_data = build_run_form_data(
            message=serialized_input,
            stream=bool(stream),
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
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
            **kwargs,
        )

        if stream:
            return astream_form_events(
                self.base_url,
                path,
                form_data,
                team_run_output_event_from_dict,
                timeout=self.timeout,
                headers=headers,
            )
        return self._arun_send(path, form_data, headers)  # type: ignore[return-value]

    async def _arun_send(
        self,
        path: str,
        form_data: Dict[str, Any],
        headers: Optional[Dict[str, str]],
    ) -> TeamRunOutput:
        """Send a non-streaming run request to the RemoteAccess interface."""
        response_data = await apost_form(self.base_url, path, form_data, timeout=self.timeout, headers=headers)
        return TeamRunOutput.from_dict(response_data)

    async def acancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running team execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        try:
            await apost_form(
                self.base_url,
                f"{self.api_prefix}/teams/{self.team_id}/runs/{run_id}/cancel",
                timeout=self.timeout,
                headers=headers,
            )
            return True
        except Exception:
            return False

    @overload
    async def acontinue_run(
        self,
        run_id: str,
        requirements: List[Any],
        stream: Literal[False] = False,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> TeamRunOutput: ...

    @overload
    def acontinue_run(
        self,
        run_id: str,
        requirements: List[Any],
        stream: Literal[True] = True,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[TeamRunOutputEvent]: ...

    def acontinue_run(  # type: ignore
        self,
        run_id: str,
        requirements: List[Any],
        stream: Optional[bool] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> Union[
        TeamRunOutput,
        AsyncIterator[TeamRunOutputEvent],
    ]:
        """Continue a paused team run with requirements (e.g., tool approval results).

        Args:
            run_id: The run_id to continue.
            requirements: List of RunRequirement objects with tool execution results.
            stream: Whether to stream the response.
            user_id: Optional user ID.
            session_id: Optional session ID.
            auth_token: Optional JWT token for authentication.
            **kwargs: Additional parameters.

        Returns:
            TeamRunOutput for non-streaming, AsyncIterator[TeamRunOutputEvent] for streaming.
        """
        headers = self._get_auth_headers(auth_token)

        path = f"{self.api_prefix}/teams/{self.team_id}/runs/{run_id}/continue"
        form_data = build_continue_form_data(
            stream=bool(stream),
            tools_field="requirements",
            tools=requirements,
            session_id=session_id,
            user_id=user_id,
            **kwargs,
        )

        if stream:
            return astream_form_events(
                self.base_url,
                path,
                form_data,
                team_run_output_event_from_dict,
                timeout=self.timeout,
                headers=headers,
            )
        return self._arun_send(path, form_data, headers)  # type: ignore[return-value]
