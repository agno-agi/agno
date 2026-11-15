from typing import TYPE_CHECKING, Any

from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager

if TYPE_CHECKING:
    from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager

__all__ = [
    "BaseRunCancellationManager",
    "InMemoryRunCancellationManager",
    "RedisRunCancellationManager",
]


def __getattr__(name: str) -> Any:
    # The Redis manager imports the redis client, and with it opentelemetry and
    # psutil. Nothing that does not ask for it should pay that at import time.
    if name == "RedisRunCancellationManager":
        from agno.run.cancellation_management.redis_cancellation_manager import RedisRunCancellationManager

        return RedisRunCancellationManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
