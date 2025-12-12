from abc import abstractmethod
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutput, WorkflowRunOutputEvent

if TYPE_CHECKING:
    from agno.client import AgentOSClient
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

    async def get_session_run(
        self, session_id: str, run_id: str, **kwargs: Any
    ) -> Union["RunSchema", "TeamRunSchema", "WorkflowRunSchema"]:
        return await self.client.get_session_run(session_id, run_id, **kwargs)

    async def migrate_database(self, target_version: Optional[str] = None) -> None:
        """Migrate the database to a target version.

        Args:
            target_version: Target version to migrate to
        """

        return await self.client.migrate_database(self.id, target_version)


@dataclass
class RemoteKnowledge:
    id: str
    contents_db: Optional[RemoteDb] = None


@dataclass
class BaseRemote:
    def __init__(
        self,
        base_url: str,
        timeout: float = 60.0,
    ):
        """Initialize BaseRemote for remote execution.

        For local execution, provide agent/team/workflow instances.
        For remote execution, provide base_url.

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            timeout: Request timeout in seconds (default: 60)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout: float = timeout

        self.client = self.get_client()

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

    @cached_property
    def _config(self) -> "ConfigResponse":
        """Get the agent config from remote, cached after first access."""
        from agno.os.schema import ConfigResponse

        config: ConfigResponse = self.client.get_config()
        return config

    def _get_headers(self) -> Dict[str, str]:
        """Get default headers for HTTP requests.

        Returns:
            Dict[str, str]: Default headers including Content-Type
        """
        return {"Content-Type": "application/x-www-form-urlencoded"}

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
