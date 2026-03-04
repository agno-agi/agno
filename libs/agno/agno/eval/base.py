from abc import ABC, abstractmethod
from typing import Union

from agno.run.agent import RunInput, RunOutput
from agno.run.team import TeamRunInput, TeamRunOutput


class BaseEval(ABC):
    """Abstract base class for all evaluations."""

    @abstractmethod
    def pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Perform sync pre-evals."""
        pass

    @abstractmethod
    async def async_pre_check(self, run_input: Union[RunInput, TeamRunInput]) -> None:
        """Perform async pre-evals."""
        pass

    @abstractmethod
    def post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Perform sync post-evals."""
        pass

    @abstractmethod
    async def async_post_check(self, run_output: Union[RunOutput, TeamRunOutput]) -> None:
        """Perform async post-evals."""
        pass
