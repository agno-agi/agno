"""V1 storage session compatibility — re-export V2 session types."""

from typing import Union

from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

Session = Union[AgentSession, TeamSession, WorkflowSession]

__all__ = [
    "AgentSession",
    "TeamSession",
    "WorkflowSession",
    "Session",
]
