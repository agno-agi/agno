from typing import Union

from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession

Session = Union[AgentSession, WorkflowSession]
