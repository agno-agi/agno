from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Union, overload

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.remote.base import BaseRemote, RemoteDb, RemoteKnowledge
from agno.run.agent import RunOutput, RunOutputEvent
from agno.utils.agent import validate_input

if TYPE_CHECKING:
    from agno.os.routers.agents.schema import AgentResponse


@dataclass
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

    async def get_agent_config(self) -> "AgentResponse":
        """Get the agent config from remote, cached after first access."""
        return await self.client.aget_agent(self.agent_id)

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
    def db(self) -> Optional[RemoteDb]:
        if self._agent_config is not None and self._agent_config.db_id is not None:
            config = self._config
            db_id = self._agent_config.db_id
            session_dbs = [db for db in config.session.dbs if db.db_id == db_id]
            session_table_name = session_dbs[0].tables[0] if session_dbs and session_dbs[0].tables else None
            knowledge_dbs = [db for db in config.knowledge.dbs if db.db_id == db_id]
            knowledge_table_name = knowledge_dbs[0].tables[0] if knowledge_dbs and knowledge_dbs[0].tables else None
            memory_dbs = [db for db in config.memory.dbs if db.db_id == db_id]
            memory_table_name = memory_dbs[0].tables[0] if memory_dbs and memory_dbs[0].tables else None
            metrics_dbs = [db for db in config.metrics.dbs if db.db_id == db_id]
            metrics_table_name = metrics_dbs[0].tables[0] if metrics_dbs and metrics_dbs[0].tables else None
            eval_dbs = [db for db in config.evals.dbs if db.db_id == db_id]
            eval_table_name = eval_dbs[0].tables[0] if eval_dbs and eval_dbs[0].tables else None
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

    @cached_property
    def knowledge(self) -> Optional[RemoteKnowledge]:
        """Whether the agent has knowledge enabled."""
        if self._agent_config is not None and self._agent_config.knowledge is not None:
            return self._agent_config.knowledge.get("enabled")
        return False

    @cached_property
    def model(self) -> Model:
        from agno.models.utils import get_model

        model_response = self._agent_config.model
        model_str = f"{model_response.provider}:{model_response.model}"
        return get_model(model_str)

    # @cached_property
    # def user_id(self) -> Optional[str]:
    #     return None

    # @cached_property
    # def additional_input(self) -> Optional[Dict[str, Any]]:
    #     if self._agent_config is not None and self._agent_config.extra_messages is not None:
    #         return self._agent_config.extra_messages.get("additional_input", None)
    #     return None

    # @cached_property
    # def input_schema(self) -> Optional[Dict[str, Any]]:
    #     if self._agent_config is not None and self._agent_config.input_schema is not None:
    #         return self._agent_config.input_schema
    #     return None

    # @cached_property
    # def tool_call_limit(self) -> Optional[int]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.tools.get("tool_call_limit")
    #     return None

    # @cached_property
    # def tool_choice(self) -> Optional[Union[str, Dict[str, Any]]]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.tools.get("tool_choice")
    #     return None

    # @cached_property
    # def add_history_to_context(self) -> Optional[bool]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.sessions.get("add_history_to_context")
    #     return None

    # @cached_property
    # def enable_session_summaries(self) -> Optional[bool]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.tools.get("enable_session_summaries")
    #     return None

    # @cached_property
    # def num_history_runs(self) -> Optional[int]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.sessions.get("num_history_runs")
    #     return None

    # @cached_property
    # def num_history_sessions(self) -> Optional[int]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.sessions.get("num_history_sessions")
    #     return None

    # @cached_property
    # def cache_session(self) -> Optional[bool]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.sessions.get("cache_session")
    #     return None

    # @cached_property
    # def search_session_history(self) -> Optional[bool]:
    #     if self._agent_config is not None and self._agent_config.tools is not None:
    #         return self._agent_config.sessions.get("search_session_history")
    #     return None

    # @cached_property
    # def knowledge_filters(self) -> Optional[Dict[str, Any]]:
    #     if self._agent_config is not None and self._agent_config.knowledge is not None:
    #         return self._agent_config.knowledge.get("knowledge_filters")
    #     return None

    # @cached_property
    # def references_format(self) -> Optional[str]:
    #     if self._agent_config is not None and self._agent_config.knowledge is not None:
    #         return self._agent_config.knowledge.get("references_format")
    #     return None

    # @cached_property
    # def enable_agentic_knowledge_filters(self) -> Optional[bool]:
    #     if self._agent_config is not None and self._agent_config.knowledge is not None:
    #         return self._agent_config.knowledge.get("enable_agentic_knowledge_filters")
    #     return None

    async def aget_tools(self, **kwargs: Any) -> List[Dict]:
        if self._agent_config.tools is not None:
            return self._agent_config.tools
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
        validated_input = validate_input(input)

        if stream:
            # Handle streaming response
            return self.get_client().run_agent_stream(
                agent_id=self.agent_id,
                message=validated_input,
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
                **kwargs,
            )
        else:
            return self.get_client().run_agent(
                agent_id=self.agent_id,
                message=validated_input,
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
                **kwargs,
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
        if stream:
            # Handle streaming response
            return self.get_client().continue_agent_run_stream(
                agent_id=self.agent_id,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                tools=updated_tools,
            )
        else:
            return self.get_client().continue_agent_run(
                agent_id=self.agent_id,
                run_id=run_id,
                tools=updated_tools,
                user_id=user_id,
                session_id=session_id,
            )

    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a running agent execution.

        Args:
            run_id (str): The run_id to cancel.

        Returns:
            bool: True if the run was found and marked for cancellation, False otherwise.
        """
        return await self.get_client().cancel_agent_run(
            agent_id=self.agent_id,
            run_id=run_id,
        )
