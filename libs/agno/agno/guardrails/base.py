from abc import ABC, abstractmethod
from typing import Union

from agno.run.agent import RunInput
from agno.run.team import TeamRunInput


class BaseGuardrail(ABC):
    """Abstract base class for all guardrail implementations."""

    @abstractmethod
    def check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Perform synchronous guardrail check."""
        pass

    @abstractmethod
    async def async_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Perform asynchronous guardrail check."""
        pass
