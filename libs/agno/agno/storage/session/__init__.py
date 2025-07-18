from typing import Union

from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.v2.workflow import WorkflowSession as WorkflowSessionV2
from agno.storage.session.workflow import WorkflowSession

Session = Union[AgentSession, TeamSession, WorkflowSession, WorkflowSessionV2]

__all__ = [
    "AgentSession",
    "TeamSession",
    "WorkflowSession",
    "WorkflowSessionV2",
    "Session",
]
