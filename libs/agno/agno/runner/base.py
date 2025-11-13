from abc import abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Union

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput, RunOutputEvent
from agno.run.team import TeamRunOutput, TeamRunOutputEvent
from agno.run.workflow import WorkflowRunOutput, WorkflowRunOutputEvent


class BaseRunner:
    def __init__(
        self,
        base_url: Optional[str] = None,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ):
        """Initialize BaseRunner for remote execution.

        For local execution, provide agent/team/workflow instances.
        For remote execution, provide base_url and agent_id/team_id/workflow_id.

        Args:
            base_url: Base URL for remote instance (e.g., "http://localhost:7777")
            agent_id: ID of remote agent
            team_id: ID of remote team
            workflow_id: ID of remote workflow
            timeout: Request timeout in seconds (default: 300)
        """
        self.base_url = base_url.rstrip("/") if base_url else None
        self.agent_id = agent_id
        self.team_id = team_id
        self.workflow_id = workflow_id

        if not self.agent_id and not self.team_id and not self.workflow_id:
            raise ValueError("No remote resource ID configured")

        # Ensure only one of agent_id, team_id, or workflow_id is set
        if (
            sum(
                [
                    bool(self.agent_id),
                    bool(self.team_id),
                    bool(self.workflow_id),
                ]
            )
            > 1
        ):
            raise ValueError("Only one of agent_id, team_id, or workflow_id can be configured at a time.")

    @property
    def id(self) -> Optional[str]:
        if self.agent_id:
            return self.agent_id
        elif self.team_id:
            return self.team_id
        elif self.workflow_id:
            return self.workflow_id
        else:
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
