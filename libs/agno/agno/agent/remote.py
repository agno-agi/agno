import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Tuple, Union, overload

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.remote.base import BaseRemote, RemoteDb, RemoteKnowledge
from agno.remote.http import (
    aget_json,
    apost_form,
    astream_form_events,
    build_continue_form_data,
    build_run_form_data,
    get_json,
)
from agno.run.agent import RunOutput, RunOutputEvent, run_output_event_from_dict
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
        config_ttl: float = 300.0,
        api_prefix: str = "/remote",
    ):
        """Initialize RemoteAgent for remote execution.

        Executes the agent on a remote AgentOS instance through its RemoteAccess interface.
        The remote AgentOS must mount the RemoteAccess interface (agno.os.interfaces.remote_access.RemoteAccess)
        and pass this agent to it; agents not exposed through the interface are not
        remotely callable.

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            agent_id: ID of remote agent on the remote server
            timeout: Request timeout in seconds (default: 60)
            config_ttl: Time-to-live for cached config in seconds (default: 300)
            api_prefix: Path prefix where the RemoteAccess interface is mounted on the remote
                AgentOS (default: "/remote")
        """
        super().__init__(base_url, timeout, config_ttl, api_prefix)
        self.agent_id = agent_id
        self._cached_agent_config = None

    @property
    def id(self) -> str:
        return self.agent_id

    async def get_agent_config(self) -> "AgentResponse":
        """Get the agent config from the RemoteAccess interface. Always fetches fresh config."""
        from agno.os.routers.agents.schema import AgentResponse

        data = await aget_json(self.base_url, f"{self.api_prefix}/agents/{self.agent_id}", timeout=self.timeout)
        return AgentResponse.model_validate(data)

    @property
    def _agent_config(self) -> Optional["AgentResponse"]:
        """Get the agent config from the RemoteAccess interface, cached with TTL."""
        import time

        from agno.os.routers.agents.schema import AgentResponse

        current_time = time.time()

        # Check if cache is valid
        if self._cached_agent_config is not None:
            cached_config, cached_at = self._cached_agent_config
            if current_time - cached_at < self.config_ttl:
                return cached_config

        # Fetch fresh config
        config: AgentResponse = AgentResponse.model_validate(
            get_json(self.base_url, f"{self.api_prefix}/agents/{self.agent_id}", timeout=self.timeout)
        )
        self._cached_agent_config = (config, current_time)
        return config

    async def refresh_config(self) -> Optional["AgentResponse"]:
        """Force refresh the cached agent config."""
        import time

        from agno.os.routers.agents.schema import AgentResponse

        config: AgentResponse = AgentResponse.model_validate(
            await aget_json(self.base_url, f"{self.api_prefix}/agents/{self.agent_id}", timeout=self.timeout)
        )
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
                log_warning(f"Failed to load tools for agent {self.agent_id}: {str(e)}")
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

        path = f"{self.api_prefix}/agents/{self.agent_id}/runs"
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
                run_output_event_from_dict,
                timeout=self.timeout,
                headers=headers,
            )
        return self._arun_send(path, form_data, headers)  # type: ignore[return-value]

    async def _arun_send(
        self,
        path: str,
        form_data: Dict[str, Any],
        headers: Optional[Dict[str, str]],
    ) -> RunOutput:
        """Send a non-streaming run request to the RemoteAccess interface."""
        response_data = await apost_form(self.base_url, path, form_data, timeout=self.timeout, headers=headers)
        return RunOutput.from_dict(response_data)

    @overload
    async def acontinue_run(
        self,
        run_id: str,
        updated_tools: Optional[List[ToolExecution]] = None,
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
        updated_tools: Optional[List[ToolExecution]] = None,
        stream: Literal[True] = True,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        auth_token: Optional[str] = None,
        **kwargs: Any,
    ) -> AsyncIterator[RunOutputEvent]: ...

    def acontinue_run(  # type: ignore
        self,
        run_id: str,  # type: ignore
        updated_tools: Optional[List[ToolExecution]] = None,
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

        path = f"{self.api_prefix}/agents/{self.agent_id}/runs/{run_id}/continue"
        form_data = build_continue_form_data(
            stream=bool(stream),
            tools_field="tools",
            tools=updated_tools or [],
            session_id=session_id,
            user_id=user_id,
            **kwargs,
        )

        if stream:
            return astream_form_events(
                self.base_url,
                path,
                form_data,
                run_output_event_from_dict,
                timeout=self.timeout,
                headers=headers,
            )
        return self._arun_send(path, form_data, headers)  # type: ignore[return-value]

    async def acancel_run(self, run_id: str, auth_token: Optional[str] = None) -> bool:
        """Cancel a running agent execution.

        Args:
            run_id (str): The run_id to cancel.
            auth_token: Optional JWT token for authentication.

        Returns:
            bool: True if the run was successfully cancelled, False otherwise.
        """
        headers = self._get_auth_headers(auth_token)
        try:
            await apost_form(
                self.base_url,
                f"{self.api_prefix}/agents/{self.agent_id}/runs/{run_id}/cancel",
                timeout=self.timeout,
                headers=headers,
            )
            return True
        except Exception:
            return False
