"""Tests for tool-result accumulation of interleaved content streams.

The bug: when a generator tool fans out to several agents and yields their
content deltas interleaved (Team(delegate_to_all_members=True, stream=True) via
delegate_task_to_members), Model.arun_function_calls accumulated the deltas in
arrival order. The tool result handed back to the leader interleaved the
members' sentences mid-word, making broadcast delegation unusable.

Fix: content-event deltas are grouped per run_id so each stream stays
contiguous, and the per-stream blocks are joined in first-arrival order.
"""

from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.models.base import Model
from agno.run.agent import RunContentEvent
from agno.tools.function import Function, FunctionCall


class _ConcreteModel(Model):
    """Minimal concrete Model: arun_function_calls never invokes a provider."""

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
        raise NotImplementedError

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotImplementedError
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def _parse_provider_response_delta(self, response: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def _content_event(run_id: str, agent_name: str, content: str) -> RunContentEvent:
    return RunContentEvent(run_id=run_id, agent_name=agent_name, content=content, content_type="str")


async def broadcast_tool() -> AsyncIterator[RunContentEvent]:
    """Two member streams yielding deltas interleaved by arrival, as the merged
    event queue in delegate_task_to_members does for delegate_to_all_members."""
    member_a = ["Alpha part one ", "and part two."]
    member_b = ["Beta part one ", "and part two."]
    for a_delta, b_delta in zip(member_a, member_b):
        yield _content_event("run-member-a", "Member A", a_delta)
        yield _content_event("run-member-b", "Member B", b_delta)


async def single_stream_tool() -> AsyncIterator[RunContentEvent]:
    """A single stream must accumulate exactly as before the fix."""
    for delta in ["Hello ", "world."]:
        yield _content_event("run-single", "Solo", delta)


async def _run_tool(tool) -> str:
    func = Function.from_callable(tool)
    func.process_entrypoint()
    fc = FunctionCall(function=func, arguments={})
    function_call_results: List[Any] = []
    model = _ConcreteModel(id="test-model")
    async for _event in model.arun_function_calls([fc], function_call_results):
        pass
    tool_messages = [m for m in function_call_results if getattr(m, "role", None) == "tool"]
    assert tool_messages, f"expected a tool result message, got {function_call_results}"
    return tool_messages[0].content


@pytest.mark.asyncio
async def test_interleaved_member_streams_stay_contiguous_in_tool_result():
    result = await _run_tool(broadcast_tool)

    assert "Alpha part one and part two." in result, f"member A garbled in: {result!r}"
    assert "Beta part one and part two." in result, f"member B garbled in: {result!r}"
    assert "part one Beta" not in result, f"members still interleaved in: {result!r}"


@pytest.mark.asyncio
async def test_single_stream_tool_result_is_unchanged():
    result = await _run_tool(single_stream_tool)
    assert result == "Hello world."
