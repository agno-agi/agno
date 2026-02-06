from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Union

if TYPE_CHECKING:
    from agno.run.agent import RunOutput, RunOutputEvent


class RunPhase(str, Enum):
    RESOLVE_OPTIONS = "resolve_options"
    BUILD_MESSAGES = "build_messages"
    MODEL_CALL = "model_call"
    TOOL_LOOP = "tool_loop"
    POSTPROCESS = "postprocess"
    PERSIST = "persist"
    EMIT = "emit"


@dataclass
class PhaseTransition:
    phase: RunPhase
    timestamp: float = field(default_factory=time)

    def to_dict(self) -> Dict[str, Any]:
        return {"phase": self.phase.value, "timestamp": self.timestamp}


class RunEngine:
    """Internal orchestration wrapper for run execution phases."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.phase: Optional[RunPhase] = None
        self.transitions: List[PhaseTransition] = []

    def set_phase(self, phase: RunPhase) -> None:
        if self.phase == phase:
            return
        self.phase = phase
        self.transitions.append(PhaseTransition(phase=phase))

    def snapshot(self) -> Dict[str, Any]:
        return {
            "current_phase": self.phase.value if self.phase is not None else None,
            "transitions": [transition.to_dict() for transition in self.transitions],
        }

    def execute_sync(self, execute: Callable[[], RunOutput]) -> RunOutput:
        self.set_phase(RunPhase.RESOLVE_OPTIONS)
        try:
            return execute()
        finally:
            self.set_phase(RunPhase.EMIT)

    def execute_sync_stream(
        self, execute: Callable[[], Iterator[Union[RunOutputEvent, RunOutput]]]
    ) -> Iterator[Union[RunOutputEvent, RunOutput]]:
        self.set_phase(RunPhase.RESOLVE_OPTIONS)
        try:
            for item in execute():
                yield item
        finally:
            self.set_phase(RunPhase.EMIT)

    async def execute_async(self, execute: Callable[[], Any]) -> RunOutput:
        self.set_phase(RunPhase.RESOLVE_OPTIONS)
        try:
            return await execute()
        finally:
            self.set_phase(RunPhase.EMIT)

    async def execute_async_stream(
        self, execute: Callable[[], AsyncIterator[Union[RunOutputEvent, RunOutput]]]
    ) -> AsyncIterator[Union[RunOutputEvent, RunOutput]]:
        self.set_phase(RunPhase.RESOLVE_OPTIONS)
        try:
            async for item in execute():
                yield item
        finally:
            self.set_phase(RunPhase.EMIT)
