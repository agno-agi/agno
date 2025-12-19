from functools import cached_property
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Union, overload

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.remote.base import BaseRemote, RemoteDb, RemoteKnowledge
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.utils.agent import validate_input
from agno.utils.remote import serialize_input

if TYPE_CHECKING:
    from agno.os.routers.teams.schema import TeamResponse


class RemoteTeam(BaseRemote):
    def __init__(
        self,
        base_url: str,
        team_id: str,
        timeout: float = 300.0,
    ):
        """Initialize AgentOSRunner for local or remote execution.

        For remote execution, provide base_url and team_id.

        Args:
            base_url: Base URL for remote AgentOS instance (e.g., "http://localhost:7777")
            team_id: ID of remote team
            timeout: Request timeout in seconds (default: 300)
        """
        super().__init__(base_url, timeout)
        self.team_id = team_id

    @property
    def id(self) -> str:
        return self.team_id

    async def get_team_config(self) -> "TeamResponse":
        """Get the agent config from remote, cached after first access."""
        return await self.client.aget_team(self.team_id)

    @cached_property
    def _team_config(self) -> Optional[Any]:
        """Get the agent config from remote, cached after first access."""
        from agno.os.routers.teams.schema import TeamResponse

        config: TeamResponse = self.client.get_team(self.team_id)
        return config

    @cached_property
    def name(self) -> str:
        if self._team_config is not None:
            return self._team_config.name
        return self.team_id

    @cached_property
    def description(self) -> str:
        if self._team_config is not None:
            return self._team_config.description
        return ""

    @cached_property
    def role(self) -> Optional[str]:
        if self._team_config is not None:
            return self._team_config.role
        return None

    @cached_property
    def tools(self) -> Optional[List[Dict[str, Any]]]:
        if self._team_config is not None:
            return self._team_config.tools
        return None

    @cached_property
    def db(self) -> Optional[RemoteDb]:
        if self._team_config is not None and self._team_config.db_id is not None:
            config = self._config
            db_id = self._team_config.db_id
            session_table_name = None
            knowledge_table_name = None
            memory_table_name = None
            metrics_table_name = None
            eval_table_name = None
            traces_table_name = None
            if config and config.session and config.session.dbs is not None:
                session_dbs = [db for db in config.session.dbs if db.db_id == db_id]
                session_table_name = session_dbs[0].tables[0] if session_dbs and session_dbs[0].tables else None
            if config and config.knowledge and config.knowledge.dbs is not None:
                knowledge_dbs = [db for db in config.knowledge.dbs if db.db_id == db_id]
                knowledge_table_name = knowledge_dbs[0].tables[0] if knowledge_dbs and knowledge_dbs[0].tables else None
            if config and config.memory and config.memory.dbs is not None:
                memory_dbs = [db for db in config.memory.dbs if db.db_id == db_id]
                memory_table_name = memory_dbs[0].tables[0] if memory_dbs and memory_dbs[0].tables else None
            if config and config.metrics and config.metrics.dbs is not None:
                metrics_dbs = [db for db in config.metrics.dbs if db.db_id == db_id]
                metrics_table_name = metrics_dbs[0].tables[0] if metrics_dbs and metrics_dbs[0].tables else None
            if config and config.evals and config.evals.dbs is not None:
                eval_dbs = [db for db in config.evals.dbs if db.db_id == db_id]
                eval_table_name = eval_dbs[0].tables[0] if eval_dbs and eval_dbs[0].tables else None
            if config and config.traces and config.traces.dbs is not None:
                traces_dbs = [db for db in config.traces.dbs if db.db_id == db_id]
                traces_table_name = traces_dbs[0].tables[0] if traces_dbs and traces_dbs[0].tables else None
            return RemoteDb(
                id=db_id,
                client=self.client,
                session_table_name=session_table_name,
                knowledge_table_name=knowledge_table_name,
                memory_table_name=memory_table_name,
                metrics_table_name=metrics_table_name,
                eval_table_name=eval_table_name,
                traces_table_name=traces_table_name,
            )
        return None

    @cached_property
    def knowledge(self) -> Optional[RemoteKnowledge]:
        """Whether the agent has knowledge enabled."""
        if self._team_config is not None and self._team_config.knowledge is not None:
            return RemoteKnowledge(
                client=self.client,
                contents_db=RemoteDb(
                    id=self._team_config.knowledge.get("db_id"),  # type: ignore
                    client=self.client,
                    knowledge_table_name=self._team_config.knowledge.get("knowledge_table"),
                )
                if self._team_config.knowledge.get("db_id") is not None
                else None,
            )
        return None

    @cached_property
    def model(self) -> Optional[Model]:
        # We don't expose the remote team's models, since they can't be used by other services in AgentOS.
        return None

    @cached_property
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

    async def cancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running team execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        await self.get_client().cancel_team_run(
            team_id=self.team_id,
            run_id=run_id,
            headers=headers,
        )
        return True
