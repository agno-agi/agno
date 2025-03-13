from typing import Union

from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession

Session = Union[AgentSession, TeamSession, WorkflowSession]
