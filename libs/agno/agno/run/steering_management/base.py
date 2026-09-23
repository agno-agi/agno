from abc import ABC, abstractmethod
from typing import List

from agno.models.message import Message


class BaseRunSteeringManager(ABC):
    """Holds user input sent to a run while it is executing ("steering").

    A run's model loop opens an inbox when it starts, takes pending input before
    each model request, and releases the inbox when it stops. Input is accepted
    only while the inbox is open, and accepted input is never dropped silently:
    it is delivered to the run's model before its next request, even when that
    request happens in a later leg of the same run (a continuation after a
    human-in-the-loop pause, or a fallback model after a provider error).

    Subclass it to share steering state across processes, and install the
    subclass with set_steering_manager(). The async methods default to the sync
    ones; override them when the backend does I/O.
    """

    @abstractmethod
    def open_run(self, run_id: str) -> None:
        """Start accepting input for a run, keeping input a previous leg left undelivered."""

    @abstractmethod
    def steer(self, run_id: str, messages: List[Message]) -> bool:
        """Queue messages for a run.

        Returns:
            bool: True if the run's inbox is open and the messages were queued,
            False if the run is not accepting input (not started, paused,
            finishing, or finished).
        """

    @abstractmethod
    def take(self, run_id: str) -> List[Message]:
        """Remove and return all pending messages for a run, in the order they were queued."""

    @abstractmethod
    def take_or_close(self, run_id: str) -> List[Message]:
        """Take pending messages, or close the inbox if there are none, as one atomic step.

        The model loop calls this when it is about to finish. If input is
        pending it is returned and the inbox stays open, because the loop will
        make another model request. If nothing is pending the inbox is closed,
        so any later steer() is rejected rather than accepted and never read.
        """

    @abstractmethod
    def release_run(self, run_id: str) -> None:
        """Stop accepting input for a run that stopped without finishing.

        Pending messages are kept for the next leg of the run. An inbox with
        nothing pending is removed.
        """

    async def aopen_run(self, run_id: str) -> None:
        """Async version of open_run."""
        self.open_run(run_id)

    async def asteer(self, run_id: str, messages: List[Message]) -> bool:
        """Async version of steer."""
        return self.steer(run_id, messages)

    async def atake(self, run_id: str) -> List[Message]:
        """Async version of take."""
        return self.take(run_id)

    async def atake_or_close(self, run_id: str) -> List[Message]:
        """Async version of take_or_close."""
        return self.take_or_close(run_id)

    async def arelease_run(self, run_id: str) -> None:
        """Async version of release_run."""
        self.release_run(run_id)
