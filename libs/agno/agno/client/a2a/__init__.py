"""DEPRECATED: use the `A2AClient` toolkit from `agno.tools.a2a` instead.

This hand-rolled A2A client predates A2A 1.0. It remains only as the internal
transport of RemoteAgent/RemoteTeam/RemoteWorkflow; direct use emits a
DeprecationWarning.
"""

from agno.client.a2a.client import A2AClient
from agno.client.a2a.schemas import AgentCard, Artifact, StreamEvent, TaskResult

__all__ = [
    "A2AClient",
    "AgentCard",
    "Artifact",
    "StreamEvent",
    "TaskResult",
]
