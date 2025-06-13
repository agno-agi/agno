from typing import Union

from agno.db.session.agent import AgentSession
from agno.db.session.team import TeamSession
from agno.db.session.workflow import WorkflowSession

Session = Union[AgentSession, TeamSession, WorkflowSession]

__all__ = [
    "AgentSession",
    "TeamSession",
    "WorkflowSession",
    "Session",
]
