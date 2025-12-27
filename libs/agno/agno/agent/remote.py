import json
import time
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

    def __init__(
        self,
        base_url: str,
        agent_id: str,
        timeout: float = 60.0,
        config_ttl: float = 300.0,
    ):
        """Initialize AgentOSRunner for local or remote execution.

        For remote execution, provide base_url and agent_id.

        Args:
            base_url: Base URL for remote AgentOS instance (e.g., "http://localhost:7777")
            agent_id: ID of remote agent
            timeout: Request timeout in seconds (default: 60)
            config_ttl: Time-to-live for cached config in seconds (default: 300)
        """
        super().__init__(base_url, timeout, config_ttl)
        self.agent_id = agent_id
        self._cached_agent_config = None

    @property
    def id(self) -> str:
        return self.agent_id

    async def get_agent_config(self) -> "AgentResponse":
        """Get the agent config from remote (always fetches fresh)."""
        return await self.client.aget_agent(self.agent_id)

    @property
    def _agent_config(self) -> "AgentResponse":
        """Get the agent config from remote, cached with TTL."""
        from agno.os.routers.agents.schema import AgentResponse

        current_time = time.time()

        # Check if cache is valid
        if self._cached_agent_config is not None:
            config, cached_at = self._cached_agent_config
            if current_time - cached_at < self.config_ttl:
                return config

        # Fetch fresh config
        config: AgentResponse = self.client.get_agent(self.agent_id)  # type: ignore
        self._cached_agent_config = (config, current_time)
        return config

    def refresh_config(self) -> "AgentResponse":
        """Force refresh the cached agent config."""
        from agno.os.routers.agents.schema import AgentResponse

        config: AgentResponse = self.client.get_agent(self.agent_id)
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

    @property
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
        if self._agent_config is not None and self._agent_config.db_id is not None:
            return RemoteDb.from_config(
                db_id=self._agent_config.db_id,
                client=self.client,
                config=self._config,
            )
        return None

    @property
    def knowledge(self) -> Optional[RemoteKnowledge]:
        """Whether the agent has knowledge enabled."""
        if self._agent_config is not None and self._agent_config.knowledge is not None:
            return RemoteKnowledge(
                client=self.client,
                contents_db=RemoteDb(
                    id=self._agent_config.knowledge.get("db_id"),  # type: ignore
                    client=self.client,
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
        if self._agent_config.tools is not None:
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

        if stream:
            # Handle streaming response
            return self.get_client().run_agent_stream(
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
            return self.get_client().run_agent(  # type: ignore
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

        if stream:
            # Handle streaming response
            return self.get_client().continue_agent_run_stream(  # type: ignore
                agent_id=self.agent_id,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                tools=updated_tools,
                headers=headers,
                **kwargs,
            )
        else:
            return self.get_client().continue_agent_run(  # type: ignore
                agent_id=self.agent_id,
                run_id=run_id,
                tools=updated_tools,
                user_id=user_id,
                session_id=session_id,
                headers=headers,
                **kwargs,
            )

    async def cancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running agent execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was successfully cancelled, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        try:
            await self.get_client().cancel_agent_run(
                agent_id=self.agent_id,
                run_id=run_id,
                headers=headers,
            )
            return True
        except Exception:
            return False
