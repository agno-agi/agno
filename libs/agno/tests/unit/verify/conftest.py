"""Shared fixtures: a recording stub Agent and a RunOutput factory."""

import asyncio
import uuid
from typing import Any, Dict, List, Optional

import pytest

from agno.metrics import RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


def make_output(
    status: RunStatus = RunStatus.completed,
    content: str = "done",
    run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RunOutput:
    return RunOutput(
        run_id=run_id or str(uuid.uuid4()),
        session_id="session-1",
        content=content,
        status=status,
        metrics=RunMetrics(),
        metadata=metadata,
    )


class StubAgent:
    """Records every run / continue_run call and hands back scripted RunOutputs.

    `outputs` is consumed in order: attempt 0 takes the first, each continuation the next.
    When the script runs out, completed outputs are minted. `on_run` lets a test change the
    world (create a file) as a side effect of an attempt.
    """

    def __init__(self, outputs: Optional[List[RunOutput]] = None, db: Any = None, on_run=None) -> None:
        self.outputs = list(outputs or [])
        self.db = db
        self.on_run = on_run
        self.run_calls: List[Dict[str, Any]] = []
        self.continue_calls: List[Dict[str, Any]] = []

    def _next(self) -> RunOutput:
        attempt_index = len(self.run_calls) + len(self.continue_calls) - 1
        if self.on_run is not None:
            self.on_run(attempt_index)
        if self.outputs:
            return self.outputs.pop(0)
        return make_output()

    def run(self, input: Any, **kwargs: Any) -> RunOutput:
        self.run_calls.append({"input": input, **kwargs})
        return self._next()

    def continue_run(self, run_response: Any = None, **kwargs: Any) -> RunOutput:
        self.continue_calls.append({"run_response": run_response, **kwargs})
        return self._next()

    async def arun(self, input: Any, **kwargs: Any) -> RunOutput:
        await asyncio.sleep(0)
        return self.run(input, **kwargs)

    async def acontinue_run(self, run_response: Any = None, **kwargs: Any) -> RunOutput:
        await asyncio.sleep(0)
        return self.continue_run(run_response=run_response, **kwargs)

    @property
    def attempts_made(self) -> int:
        return len(self.run_calls) + len(self.continue_calls)


@pytest.fixture
def stub_agent():
    return StubAgent


@pytest.fixture
def output():
    return make_output
