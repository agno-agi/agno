"""A stand-in for a stored external agent that cannot be rebuilt in this process."""

from typing import Any, AsyncIterator, ClassVar

from agno.agents._config import agent_dataclass
from agno.agents.base import BaseExternalAgent
from agno.run.agent import RunOutputEvent


@agent_dataclass
class UnavailableExternalAgent(BaseExternalAgent):
    """Keeps a stored external agent visible in listings when its config cannot be rebuilt.

    It carries the stored id, name, description and sdk, and every run fails with the
    reason the rebuild failed, so the component can be found and repaired.
    """

    stored_sdk: str = "external"
    reason: str = "The stored config could not be rebuilt"

    _sdk_name: ClassVar[str] = "external"

    @property
    def sdk(self) -> str:
        return self.stored_sdk

    async def _arun_adapter(self, input: Any, **kwargs: Any) -> str:
        raise RuntimeError(self.reason)

    async def _arun_adapter_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[RunOutputEvent]:
        raise RuntimeError(self.reason)
        yield  # pragma: no cover - makes this an async generator
