"""
Test that streamed tool content is grouped by the run it came from, and not interleaved.
"""

from dataclasses import dataclass
from itertools import zip_longest
from typing import Any, AsyncIterator, Iterator, List, Optional

import pytest

from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.agent import RunContentEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent
from agno.tools.function import Function, FunctionCall

# Two members answering a question. Each answer must be merged intact.
ANSWER_A = "The first member wrote this entire sentence."
ANSWER_B = "The second member wrote a different one."


@dataclass
class StubModel(Model):
    """Minimal concrete Model: only the tool-execution machinery is exercised."""

    id: str = "stub"
    name: Optional[str] = "StubModel"
    provider: Optional[str] = "Stub"

    def invoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        raise NotImplementedError

    def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        raise NotImplementedError

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        raise NotImplementedError


def deltas(text: str, run_id: str, agent_name: str = "", team_name: str = "") -> List[Any]:
    """Split text into word-level deltas the same way a model would stream them."""
    chunks = [word if i == 0 else " " + word for i, word in enumerate(text.split(" "))]
    if team_name:
        return [TeamRunContentEvent(run_id=run_id, team_name=team_name, content=chunk) for chunk in chunks]
    return [RunContentEvent(run_id=run_id, agent_name=agent_name, content=chunk) for chunk in chunks]


def interleave(first: List[Any], second: List[Any]) -> List[Any]:
    """Round-robin two event streams the same way a shared queue would."""
    return [event for pair in zip_longest(first, second) for event in pair if event is not None]


async def tool_result(events: List[Any]) -> Any:
    """Run `events` through a tool call and return the resulting tool result."""

    async def delegate_task_to_members(task: str) -> AsyncIterator[Any]:
        for event in events:
            yield event

    func = Function.from_callable(delegate_task_to_members)
    func.process_entrypoint()
    fc = FunctionCall(function=func, arguments={"task": "Answer the question."})

    results: List[Message] = []
    async for _ in StubModel().arun_function_calls([fc], results):
        pass

    assert len(results) == 1
    return results[0].content


@pytest.mark.asyncio
async def test_concurrent_runs_are_not_interleaved():
    """Two runs streaming into one tool call must each come out in one piece."""
    output = await tool_result(
        interleave(
            deltas(ANSWER_A, run_id="run-1", agent_name="A"),
            deltas(ANSWER_B, run_id="run-2", agent_name="B"),
        )
    )

    assert output == f"Agent A: {ANSWER_A}\n\nAgent B: {ANSWER_B}"


@pytest.mark.asyncio
async def test_single_run_output_is_unchanged():
    """One streaming run must act like a plain concatenation, with no labels."""
    output = await tool_result(deltas(ANSWER_A, run_id="run-1", agent_name="A"))

    assert output == ANSWER_A


@pytest.mark.asyncio
async def test_sub_team_members_are_labelled_by_team_name():
    """Team content events carry `team_name` rather than `agent_name`."""
    output = await tool_result(
        interleave(
            deltas("The first sub-team answered.", run_id="run-1", team_name="Team A"),
            deltas("The second sub-team answered.", run_id="run-2", team_name="Team B"),
        )
    )

    assert output == "Agent Team A: The first sub-team answered.\n\nAgent Team B: The second sub-team answered."


@pytest.mark.asyncio
async def test_plain_output_is_separated_from_labelled_blocks():
    """A paused member yields a plain string, it must not attach to the last block."""
    events = interleave(
        deltas(ANSWER_A, run_id="run-1", agent_name="A"),
        deltas(ANSWER_B, run_id="run-2", agent_name="B"),
    )
    events.append("Agent C: Requires human input before continuing.")

    output = await tool_result(events)

    assert output.endswith(f"{ANSWER_B}\n\nAgent C: Requires human input before continuing.")
