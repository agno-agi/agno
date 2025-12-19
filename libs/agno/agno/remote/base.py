from abc import abstractmethod
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Literal, Optional, Sequence, Union

from pydantic import BaseModel

from agno.db.base import SessionType
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutput, WorkflowRunOutputEvent

if TYPE_CHECKING:
    from fastapi import UploadFile

    from agno.a2a import A2AClient
    from agno.a2a.schemas import AgentCard
    from agno.client import AgentOSClient
    from agno.os.routers.evals.schemas import EvalSchema
    from agno.os.routers.knowledge.schemas import (
        ConfigResponseSchema,
        ContentResponseSchema,
        ContentStatusResponse,
        VectorSearchResult,
    )
    from agno.os.routers.memory.schemas import OptimizeMemoriesResponse, UserMemorySchema, UserStatsSchema
    from agno.os.routers.metrics.schemas import DayAggregatedMetrics, MetricsResponse
    from agno.os.routers.traces.schemas import TraceDetail, TraceNode, TraceSessionStats, TraceSummary
    from agno.os.schema import (
        AgentSessionDetailSchema,
        ConfigResponse,
        PaginatedResponse,
        RunSchema,
        SessionSchema,
        TeamRunSchema,
        TeamSessionDetailSchema,
        WorkflowRunSchema,
        WorkflowSessionDetailSchema,
    )


@dataclass
class RemoteDb:
    id: str
    client: "AgentOSClient"
    session_table_name: Optional[str] = None
    knowledge_table_name: Optional[str] = None
    memory_table_name: Optional[str] = None
    metrics_table_name: Optional[str] = None
    eval_table_name: Optional[str] = None
    traces_table_name: Optional[str] = None
    spans_table_name: Optional[str] = None
    culture_table_name: Optional[str] = None

    # TODO: Pass headers for auth

    # SESSIONS
    async def get_sessions(self, **kwargs: Any) -> "PaginatedResponse[SessionSchema]":
        return await self.client.get_sessions(**kwargs)

    async def get_session(
        self, session_id: str, **kwargs: Any
    ) -> Union["AgentSessionDetailSchema", "TeamSessionDetailSchema", "WorkflowSessionDetailSchema"]:
        return await self.client.get_session(session_id, **kwargs)

    async def get_session_runs(
        self, session_id: str, **kwargs: Any
    ) -> List[Union["RunSchema", "TeamRunSchema", "WorkflowRunSchema"]]:
        return await self.client.get_session_runs(session_id, **kwargs)

    async def create_session(
        self,
        session_id: Optional[str] = None,
        session_name: Optional[str] = None,
        session_state: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Union["AgentSessionDetailSchema", "TeamSessionDetailSchema", "WorkflowSessionDetailSchema"]:
        return await self.client.create_session(
            session_id=session_id,
            session_name=session_name,
            session_state=session_state,
            metadata=metadata,
            user_id=user_id,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            **kwargs,
        )

    async def get_session_run(
        self, session_id: str, run_id: str, **kwargs: Any
    ) -> Union["RunSchema", "TeamRunSchema", "WorkflowRunSchema"]:
        return await self.client.get_session_run(session_id, run_id, **kwargs)

    async def rename_session(
        self, session_id: str, session_name: str, **kwargs: Any
    ) -> Union["AgentSessionDetailSchema", "TeamSessionDetailSchema", "WorkflowSessionDetailSchema"]:
        return await self.client.rename_session(session_id, session_name, **kwargs)

    async def update_session(
        self, session_id: str, session_type: SessionType, **kwargs: Any
    ) -> Union["AgentSessionDetailSchema", "TeamSessionDetailSchema", "WorkflowSessionDetailSchema"]:
        return await self.client.update_session(session_id=session_id, session_type=session_type, **kwargs)

    async def delete_session(self, session_id: str, **kwargs: Any) -> None:
        return await self.client.delete_session(session_id, **kwargs)

    async def delete_sessions(self, session_ids: List[str], session_types: List[SessionType], **kwargs: Any) -> None:
        return await self.client.delete_sessions(session_ids, session_types, **kwargs)

    # MEMORIES
    async def create_memory(self, memory: str, topics: List[str], user_id: str, **kwargs: Any) -> "UserMemorySchema":
        return await self.client.create_memory(memory=memory, topics=topics, user_id=user_id, **kwargs)

    async def delete_memory(self, memory_id: str, **kwargs: Any) -> None:
        return await self.client.delete_memory(memory_id, **kwargs)

    async def delete_memories(self, memory_ids: List[str], **kwargs: Any) -> None:
        return await self.client.delete_memories(memory_ids, **kwargs)

    async def get_memory(self, memory_id: str, **kwargs: Any) -> "UserMemorySchema":
        return await self.client.get_memory(memory_id, **kwargs)

    async def get_memories(self, user_id: Optional[str] = None, **kwargs: Any) -> "PaginatedResponse[UserMemorySchema]":
        return await self.client.list_memories(user_id, **kwargs)

    async def update_memory(self, memory_id: str, **kwargs: Any) -> "UserMemorySchema":
        return await self.client.update_memory(memory_id, **kwargs)

    async def get_user_memory_stats(self, **kwargs: Any) -> "PaginatedResponse[UserStatsSchema]":
        return await self.client.get_user_memory_stats(**kwargs)

    async def optimize_memories(self, **kwargs: Any) -> "OptimizeMemoriesResponse":
        return await self.client.optimize_memories(**kwargs)

    async def get_memory_topics(self, **kwargs: Any) -> List[str]:
        return await self.client.get_memory_topics(**kwargs)

    # TRACES
    async def get_traces(self, **kwargs: Any) -> "PaginatedResponse[TraceSummary]":
        return await self.client.get_traces(**kwargs)

    async def get_trace(self, trace_id: str, **kwargs: Any) -> Union["TraceDetail", "TraceNode"]:
        return await self.client.get_trace(trace_id, **kwargs)

    async def get_trace_session_stats(self, **kwargs: Any) -> "PaginatedResponse[TraceSessionStats]":
        return await self.client.get_trace_session_stats(**kwargs)

    # EVALS
    async def get_eval_runs(self, **kwargs: Any) -> "PaginatedResponse[EvalSchema]":
        return await self.client.list_eval_runs(**kwargs)

    async def get_eval_run(self, eval_run_id: str, **kwargs: Any) -> "EvalSchema":
        return await self.client.get_eval_run(eval_run_id, **kwargs)

    async def delete_eval_runs(self, eval_run_ids: List[str], **kwargs: Any) -> None:
        return await self.client.delete_eval_runs(eval_run_ids, **kwargs)

    async def update_eval_run(self, eval_run_id: str, **kwargs: Any) -> "EvalSchema":
        return await self.client.update_eval_run(eval_run_id, **kwargs)

    async def create_eval_run(self, **kwargs: Any) -> Optional["EvalSchema"]:
        return await self.client.run_eval(**kwargs)

    # METRICS
    async def get_metrics(
        self, starting_date: Optional[date] = None, ending_date: Optional[date] = None, **kwargs: Any
    ) -> "MetricsResponse":
        return await self.client.get_metrics(starting_date=starting_date, ending_date=ending_date, **kwargs)

    async def refresh_metrics(self, **kwargs: Any) -> List["DayAggregatedMetrics"]:
        return await self.client.refresh_metrics(**kwargs)

    # OTHER
    async def migrate_database(self, target_version: Optional[str] = None) -> None:
        """Migrate the database to a target version.

        Args:
            target_version: Target version to migrate to
        """

        return await self.client.migrate_database(self.id, target_version)


@dataclass
class RemoteKnowledge:
    client: "AgentOSClient"
    contents_db: Optional[RemoteDb] = None

    async def get_config(self, headers: Optional[Dict[str, str]] = None) -> "ConfigResponseSchema":
        return await self.client.get_knowledge_config(
            db_id=self.contents_db.id if self.contents_db else None, headers=headers
        )

    async def search_knowledge(self, query: str, **kwargs: Any) -> "PaginatedResponse[VectorSearchResult]":
        return await self.client.search_knowledge(query, **kwargs)

    async def upload_content(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        url: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        file: Optional[Union[File, "UploadFile"]] = None,
        text_content: Optional[str] = None,
        reader_id: Optional[str] = None,
        chunker: Optional[str] = None,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        db_id: Optional[str] = None,
        **kwargs: Any,
    ) -> "ContentResponseSchema":
        return await self.client.upload_knowledge_content(
            name=name,
            description=description,
            url=url,
            metadata=metadata,
            file=file,
            text_content=text_content,
            reader_id=reader_id,
            chunker=chunker,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            db_id=db_id,
            **kwargs,
        )

    async def update_content(
        self,
        content_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        reader_id: Optional[str] = None,
        db_id: Optional[str] = None,
        **kwargs: Any,
    ) -> "ContentResponseSchema":
        return await self.client.update_knowledge_content(
            content_id=content_id,
            name=name,
            description=description,
            metadata=metadata,
            reader_id=reader_id,
            db_id=db_id,
            **kwargs,
        )

    async def get_content(
        self,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        db_id: Optional[str] = None,
        **kwargs: Any,
    ) -> "PaginatedResponse[ContentResponseSchema]":
        return await self.client.list_knowledge_content(
            limit=limit, page=page, sort_by=sort_by, sort_order=sort_order, db_id=db_id, **kwargs
        )

    async def get_content_by_id(
        self, content_id: str, db_id: Optional[str] = None, **kwargs: Any
    ) -> "ContentResponseSchema":
        return await self.client.get_knowledge_content(content_id=content_id, db_id=db_id, **kwargs)

    async def delete_content_by_id(self, content_id: str, db_id: Optional[str] = None, **kwargs: Any) -> None:
        await self.client.delete_knowledge_content(content_id=content_id, db_id=db_id, **kwargs)

    async def delete_all_content(self, db_id: Optional[str] = None, **kwargs: Any) -> None:
        await self.client.delete_all_knowledge_content(db_id=db_id, **kwargs)

    async def get_content_status(
        self, content_id: str, db_id: Optional[str] = None, **kwargs: Any
    ) -> "ContentStatusResponse":
        return await self.client.get_knowledge_content_status(content_id=content_id, db_id=db_id, **kwargs)


@dataclass
class BaseRemote:
    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
        protocol: Literal["agentos", "a2a"] = "agentos",
        json_rpc_endpoint: Optional[str] = None,
    ):
        """Initialize BaseRemote for remote execution.

        Supports two protocols:
        - "agentos": Agno's proprietary AgentOS REST API (default)
        - "a2a": A2A (Agent-to-Agent) protocol for cross-framework communication

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            timeout: Request timeout in seconds (default: 60)
            protocol: Communication protocol - "agentos" (default) or "a2a"
            json_rpc_endpoint: For A2A protocol only - endpoint for JSON-RPC calls.
                Use "/" for Google ADK servers. If None, uses REST-style endpoints.
        """
        self.base_url = base_url.rstrip("/")
        self.timeout: float = timeout
        self.protocol = protocol
        self.json_rpc_endpoint = json_rpc_endpoint

        self.client = self.get_client()
        self._a2a_client: Optional["A2AClient"] = None

    def get_client(self) -> "AgentOSClient":
        """Get an AgentOSClient for fetching remote configuration.

        This is used internally by AgentOS to fetch configuration from remote
        AgentOS instances when this runner represents a remote resource.

        Returns:
            AgentOSClient: Client configured for this remote resource's base URL
        """
        from agno.client import AgentOSClient

        return AgentOSClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

    def get_a2a_client(self) -> "A2AClient":
        """Get an A2AClient for A2A protocol communication.

        Returns cached client if available, otherwise creates a new one.
        This method provides lazy initialization of the A2A client.

        Returns:
            A2AClient: Client configured for A2A protocol communication
        """
        if self._a2a_client is None:
            from agno.a2a import A2AClient

            self._a2a_client = A2AClient(
                base_url=self.base_url,
                timeout=int(self.timeout),
                json_rpc_endpoint=self.json_rpc_endpoint,
            )
        return self._a2a_client

    @cached_property
    def _agent_card(self) -> Optional["AgentCard"]:
        """Get agent card for A2A protocol agents.

        Fetches the agent card from the standard /.well-known/agent.json endpoint
        to populate agent metadata (name, description, etc.) for A2A agents.

        Returns None for non-A2A protocols or if the server doesn't support agent cards.
        """
        if self.protocol != "a2a":
            return None

        import asyncio

        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self.get_a2a_client().get_agent_card())
        except Exception:
            return None

    @cached_property
    def _config(self) -> "ConfigResponse":
        """Get the agent config from remote, cached after first access."""
        from agno.os.schema import ConfigResponse

        config: ConfigResponse = self.client.get_config()
        return config

    def _get_headers(self, auth_token: Optional[str] = None) -> Dict[str, str]:
        """Get headers for HTTP requests.

        Args:
            auth_token: Optional JWT token for authentication

        Returns:
            Dict[str, str]: Headers including Content-Type and optional Authorization
        """
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        return headers

    def _get_auth_headers(self, auth_token: Optional[str] = None) -> Optional[Dict[str, str]]:
        """Get Authorization headers for HTTP requests.

        Args:
            auth_token: Optional JWT token for authentication

        Returns:
            Dict[str, str] with Authorization header if auth_token is provided, None otherwise
        """
        if auth_token:
            return {"Authorization": f"Bearer {auth_token}"}
        return None

    @abstractmethod
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
        TeamRunOutput,
        WorkflowRunOutput,
        AsyncIterator[Union[RunOutputEvent, TeamRunOutputEvent, WorkflowRunOutputEvent]],
    ]:
        raise NotImplementedError("arun method must be implemented by the subclass")

    @abstractmethod
    async def acontinue_run(  # type: ignore
        self,
        run_id: str,
        stream: Optional[bool] = None,
        updated_tools: Optional[List[ToolExecution]] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Union[RunOutput, TeamRunOutput, WorkflowRunOutput]:
        raise NotImplementedError("acontinue_run method must be implemented by the subclass")

    @abstractmethod
    async def cancel_run(self, run_id: str) -> bool:
        raise NotImplementedError("cancel_run method must be implemented by the subclass")
