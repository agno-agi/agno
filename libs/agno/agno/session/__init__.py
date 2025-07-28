from typing import Union

from agno.session.agent import AgentSession
from agno.session.summary import SessionSummaryManager
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

Session = Union[AgentSession, TeamSession, WorkflowSession, SessionSummaryManager]

__all__ = [
    "AgentSession",
    "TeamSession",
    "WorkflowSession",
    "Session",
]
