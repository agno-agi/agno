"""V1 run response compatibility stubs."""

from agno.run.base import BaseRunOutputEvent

# V1 Compatibility: RunResponseEvent is an alias for BaseRunOutputEvent
RunResponseEvent = BaseRunOutputEvent

__all__ = ["RunResponseEvent"]
