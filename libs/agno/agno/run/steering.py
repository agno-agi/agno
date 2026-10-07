"""Run steering: deliver user input to a run while it is executing.

A caller steers a run with ``Agent.steer(run_id, input)``. The input is queued
and the run's model loop appends it to the conversation as a user message
before its next model request: after the tool batch in flight finishes, or
instead of finishing when the model has just produced its final answer. Text
input is framed as a message the user sent mid-run (STEERING_MESSAGE_TEMPLATE);
a Message is used verbatim.
"""

from typing import List, Optional, Union

from agno.models.message import Message
from agno.run.steering_management.base import BaseRunSteeringManager
from agno.run.steering_management.in_memory_steering_manager import InMemoryRunSteeringManager
from agno.utils.log import logger

SteeringInput = Union[str, Message]

# How text steered into a run reads to the model. A bare user message placed mid-run only tells
# the model who is speaking; the framing also says the user wrote it while the model was working
# (possibly before seeing its latest output) and that the work in progress continues.
STEERING_MESSAGE_TEMPLATE = "The user sent this message while you were working. Address it as you continue:\n\n{input}"

# Global steering manager instance
_steering_manager: BaseRunSteeringManager = InMemoryRunSteeringManager()


def set_steering_manager(manager: BaseRunSteeringManager) -> None:
    """Replace the global steering manager, e.g. with one shared across processes."""
    global _steering_manager
    _steering_manager = manager
    logger.info(f"Steering manager set to {type(manager).__name__}")


def get_steering_manager() -> BaseRunSteeringManager:
    """Get the current steering manager instance."""
    return _steering_manager


def steering_message(text: str) -> Message:
    """Build the user message that text steered into a run becomes, framed as mid-run input.

    ``steer(run_id, text)`` sends exactly this. Build it yourself to keep its ``id``, which the
    run's ``RunSteered`` event reports. Pass any other ``Message`` to steer() to use it verbatim.
    """
    if not text.strip():
        raise ValueError("Steering input must not be empty")
    return Message(role="user", content=STEERING_MESSAGE_TEMPLATE.format(input=text))


def _to_messages(input: SteeringInput) -> List[Message]:
    if isinstance(input, Message):
        return [input]
    if isinstance(input, str):
        return [steering_message(input)]
    raise TypeError(f"Steering input must be a str or Message, got {type(input).__name__}")


def steer_run(run_id: str, input: SteeringInput) -> bool:
    """Send input to a running run.

    Returns:
        bool: True if the run accepted the input; it will reach the run's model
        before its next request. False if the run is not accepting input (not
        started, paused for human input, finishing, or finished); start a new
        run, or continue the paused one, instead.
    """
    return _steering_manager.steer(run_id, _to_messages(input))


async def asteer_run(run_id: str, input: SteeringInput) -> bool:
    """Send input to a running run (async version). See steer_run."""
    return await _steering_manager.asteer(run_id, _to_messages(input))


class RunSteering:
    """A model loop's handle on one run's steering inbox.

    Backend failures are logged and treated as "no input": steering must never
    break the run it is steering.
    """

    def __init__(self, run_id: str, manager: Optional[BaseRunSteeringManager] = None):
        self.run_id = run_id
        self.manager = manager if manager is not None else _steering_manager

    def open(self) -> None:
        try:
            self.manager.open_run(self.run_id)
        except Exception as e:
            logger.warning(f"Could not open steering for run {self.run_id}: {e}")

    async def aopen(self) -> None:
        try:
            await self.manager.aopen_run(self.run_id)
        except Exception as e:
            logger.warning(f"Could not open steering for run {self.run_id}: {e}")

    def take(self) -> List[Message]:
        try:
            return self.manager.take(self.run_id)
        except Exception as e:
            logger.warning(f"Could not read steering for run {self.run_id}: {e}")
            return []

    async def atake(self) -> List[Message]:
        try:
            return await self.manager.atake(self.run_id)
        except Exception as e:
            logger.warning(f"Could not read steering for run {self.run_id}: {e}")
            return []

    def take_or_close(self) -> List[Message]:
        try:
            return self.manager.take_or_close(self.run_id)
        except Exception as e:
            logger.warning(f"Could not read steering for run {self.run_id}: {e}")
            return []

    async def atake_or_close(self) -> List[Message]:
        try:
            return await self.manager.atake_or_close(self.run_id)
        except Exception as e:
            logger.warning(f"Could not read steering for run {self.run_id}: {e}")
            return []

    def release(self) -> None:
        try:
            self.manager.release_run(self.run_id)
        except Exception as e:
            logger.warning(f"Could not release steering for run {self.run_id}: {e}")

    async def arelease(self) -> None:
        try:
            await self.manager.arelease_run(self.run_id)
        except Exception as e:
            logger.warning(f"Could not release steering for run {self.run_id}: {e}")


def steering_for(run_id: Optional[str]) -> Optional[RunSteering]:
    """The steering handle for a run, or None when the run has no id to steer by."""
    return RunSteering(run_id) if run_id else None
