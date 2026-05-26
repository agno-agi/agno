"""
Compatibility stubs for V1 → V2 migration.

Re-exports and wrapper classes for agno framework classes that changed location
or were removed in V2.6.5.

Note: Some stubs (Knowledge) are lazy-loaded to handle optional dependencies.
"""

from agno_custom.stubs.metrics import SessionMetrics
from agno_custom.stubs.memory_agent import AgentMemory, AgentRun
from agno_custom.stubs.memory_team import TeamMemory, TeamRun
from agno_custom.stubs.run_base import BaseRunResponseEvent, RunResponseExtraData
from agno_custom.stubs.run_messages import RunMessages

# Knowledge is lazy-loaded due to optional dependencies in agno.knowledge module
def __getattr__(name):
    if name == "Knowledge":
        from agno_custom.stubs.knowledge import Knowledge
        return Knowledge
    elif name == "AgentKnowledge":
        from agno_custom.stubs.knowledge import AgentKnowledge
        return AgentKnowledge
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "SessionMetrics",
    "AgentMemory",
    "AgentRun",
    "TeamMemory",
    "TeamRun",
    "BaseRunResponseEvent",
    "RunResponseExtraData",
    "RunMessages",
    "Knowledge",
    "AgentKnowledge",
]
