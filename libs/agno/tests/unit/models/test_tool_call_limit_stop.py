"""Regression tests for the tool_call_limit no-progress stop guard.

Covers the bug in #8304: when every tool call in a batch is refused because
``tool_call_limit`` is exhausted, the model loop used to feed those refusals
back to the model, which re-proposed the same tools, looping until timeout.

The stop predicate must key off ``tool_call_limit_reached`` and not
``tool_call_error``: the latter is also set for ordinary runtime tool
failures (``create_function_call_result`` sets ``tool_call_error=not
success``), which the model should still see and be able to recover from.

These tests drive the real ``Model`` code with a local echo model, so they
need no API keys and no network.
"""

import json
from typing import Any, AsyncIterator, Iterator, List, Optional

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.tools.function import Function, FunctionCall


class _EchoModel(Model):
    """Minimal concrete Model. Only the tool-result plumbing is exercised."""

    def __init__(self):
        super().__init__(id="echo", name="Echo", provider="test")

    # The abstract request methods are never reached by these tests.
    def invoke(self, *args, **kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError

    async def ainvoke(self, *args, **kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError

    def invoke_stream(self, *args, **kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError

    async def ainvoke_stream(self, *args, **kwargs):  # pragma: no cover - not exercised
        raise NotImplementedError

    def _parse_provider_response(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def _parse_provider_response_delta(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError


class _RepeatedToolCallModel(Model):
    """Offline model that asks for the same tool after the limit is exhausted."""

    def __init__(self, tool_name: str):
        super().__init__(id="repeated-tool-call", name="Repeated tool call", provider="test")
        self.tool_name = tool_name
        self.invocations = 0
        self.requested_tools: List[Any] = []
        self.requested_tool_choices: List[Any] = []

    def _next_response(self, **kwargs: Any) -> ModelResponse:
        self.invocations += 1
        self.requested_tools.append(kwargs.get("tools"))
        self.requested_tool_choices.append(kwargs.get("tool_choice"))
        if self.invocations <= 2:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "id": f"call_{self.invocations}",
                        "type": "function",
                        "function": {"name": self.tool_name, "arguments": json.dumps({"query": "Agno"})},
                    }
                ],
                response_usage=MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2),
            )
        return ModelResponse(
            role="assistant",
            content="fallback answer",
            response_usage=MessageMetrics(input_tokens=1, output_tokens=1, total_tokens=2),
        )

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response(**kwargs)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self._next_response(**kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        yield self._next_response(**kwargs)

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        yield self._next_response(**kwargs)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _search_knowledge(query: str) -> str:
    return f"result for {query}"


def _make_call(name: str, fn) -> FunctionCall:
    function = Function(name=name, entrypoint=fn)
    function.process_entrypoint()
    return FunctionCall(function=function, arguments={}, call_id=f"call_{name}")


def _ok_tool() -> str:
    return "ok"


def _boom_tool() -> str:
    raise RuntimeError("upstream API is down")


def _drain(model: Model, calls: List[FunctionCall], limit: Optional[int], count: int = 0) -> List[Message]:
    results: List[Message] = []
    for _ in model.run_function_calls(
        function_calls=calls,
        function_call_results=results,
        current_function_call_count=count,
        function_call_limit=limit,
    ):
        pass
    return results


# --- marker semantics -------------------------------------------------------


def test_limit_refusal_is_marked_and_ordinary_success_is_not():
    """A call refused by the limit carries the marker; an executed call does not."""
    model = _EchoModel()
    calls = [_make_call("first", _ok_tool), _make_call("second", _ok_tool)]

    results = _drain(model, calls, limit=1)

    assert len(results) == 2
    # First call is inside the budget and runs normally.
    assert results[0].tool_call_limit_reached is None
    assert not results[0].tool_call_error
    # Second call is refused by the limit.
    assert results[1].tool_call_limit_reached is True
    assert results[1].tool_call_error is True


def test_ordinary_tool_failure_is_not_marked_as_limit_reached():
    """The core of the bug: a runtime failure sets tool_call_error but not the marker.

    Stopping on ``all(tool_call_error)`` would end the run here and deny the
    model any chance to recover from a transient tool failure.
    """
    model = _EchoModel()

    results = _drain(model, [_make_call("boom", _boom_tool)], limit=None)

    assert len(results) == 1
    assert results[0].tool_call_error is True
    assert results[0].tool_call_limit_reached is None


# --- stop predicate ---------------------------------------------------------
#
# The guard applied in each of the four response loops is:
#     all(m.tool_call_limit_reached for m in function_call_results)


def _should_stop(results: List[Message]) -> bool:
    return bool(results) and all(m.tool_call_limit_reached for m in results)


def test_all_blocked_by_limit_stops():
    model = _EchoModel()
    calls = [_make_call("a", _ok_tool), _make_call("b", _ok_tool)]

    # Budget already spent, so every call in the batch is refused.
    results = _drain(model, calls, limit=1, count=1)

    assert [m.tool_call_limit_reached for m in results] == [True, True]
    assert _should_stop(results) is True


def test_all_ordinary_errors_do_not_stop():
    model = _EchoModel()
    calls = [_make_call("boom1", _boom_tool), _make_call("boom2", _boom_tool)]

    results = _drain(model, calls, limit=None)

    assert all(m.tool_call_error for m in results)
    assert _should_stop(results) is False


def test_mixed_batch_does_not_stop():
    """One call succeeded, so progress was made; the model gets to use it."""
    model = _EchoModel()
    calls = [_make_call("a", _ok_tool), _make_call("b", _ok_tool)]

    results = _drain(model, calls, limit=1)

    assert results[1].tool_call_limit_reached is True
    assert _should_stop(results) is False


def test_budget_carries_across_turns_so_the_run_terminates():
    """The termination guarantee for #8304, across consecutive turns.

    A mixed batch does not stop the run, so this asserts the thing that makes
    that safe: the response loops keep a single running ``function_call_count``
    across ``while`` iterations (initialised once before the loop, incremented
    by ``_limit_charge_for`` after each batch). The turn after the budget runs
    out is therefore refused in full, and the guard fires.
    """
    model = _EchoModel()
    budget = 1

    # Turn 1: budget runs out mid-batch -> mixed, keep going.
    turn1 = _drain(model, [_make_call("a", _ok_tool), _make_call("b", _ok_tool)], limit=budget, count=0)
    assert _should_stop(turn1) is False

    # The loop charges the batch against the running total exactly as the
    # response loops do.
    count = model._limit_charge_for(turn1, None)
    assert count == 2

    # Turn 2: the model re-proposes, every call is now refused, the run ends.
    turn2 = _drain(model, [_make_call("a", _ok_tool), _make_call("b", _ok_tool)], limit=budget, count=count)
    assert [m.tool_call_limit_reached for m in turn2] == [True, True]
    assert _should_stop(turn2) is True


def test_no_limit_configured_never_stops():
    model = _EchoModel()
    calls = [_make_call("a", _ok_tool), _make_call("b", _ok_tool)]

    results = _drain(model, calls, limit=None)

    assert not any(m.tool_call_limit_reached for m in results)
    assert _should_stop(results) is False


# --- async parity -----------------------------------------------------------


@pytest.mark.asyncio
async def test_async_limit_refusal_is_marked():
    model = _EchoModel()
    calls = [_make_call("a", _ok_tool), _make_call("b", _ok_tool)]
    results: List[Message] = []

    async for _ in model.arun_function_calls(
        function_calls=calls,
        function_call_results=results,
        current_function_call_count=1,
        function_call_limit=1,
    ):
        pass

    assert [m.tool_call_limit_reached for m in results] == [True, True]
    assert _should_stop(results) is True


@pytest.mark.asyncio
async def test_async_ordinary_failure_is_not_marked():
    model = _EchoModel()
    results: List[Message] = []

    async for _ in model.arun_function_calls(
        function_calls=[_make_call("boom", _boom_tool)],
        function_call_results=results,
        function_call_limit=None,
    ):
        pass

    assert results[0].tool_call_error is True
    assert results[0].tool_call_limit_reached is None
    assert _should_stop(results) is False


# --- response loop behavior -------------------------------------------------


def test_response_stream_allows_one_tool_free_final_answer_after_limit_refusal():
    """The refused request is followed by one tool-free synthesis turn.

    The second request is refused because the only tool slot was used by the
    first request. The model must still get one final chance to answer from
    the first tool result, without being offered tools again.
    """
    model = _RepeatedToolCallModel("search")

    events = list(
        model.response_stream(
            messages=[Message(role="user", content="Find Agno")],
            tools=[Function.from_callable(_search_knowledge, name="search")],
            tool_call_limit=1,
        )
    )

    assert model.invocations == 3
    assert model.requested_tools[2] == []
    assert model.requested_tool_choices[2] == "none"
    assert any(getattr(event, "content", None) == "fallback answer" for event in events)


@pytest.mark.asyncio
async def test_aresponse_stream_allows_one_tool_free_final_answer_after_limit_refusal():
    """Async streaming also preserves a final answer after the limit refusal."""
    model = _RepeatedToolCallModel("search")

    events = [
        event
        async for event in model.aresponse_stream(
            messages=[Message(role="user", content="Find Agno")],
            tools=[Function.from_callable(_search_knowledge, name="search")],
            tool_call_limit=1,
        )
    ]

    assert model.invocations == 3
    assert model.requested_tools[2] == []
    assert model.requested_tool_choices[2] == "none"
    assert any(getattr(event, "content", None) == "fallback answer" for event in events)


def test_response_allows_one_tool_free_final_answer_after_limit_refusal():
    """Non-streaming response also synthesizes after the limit is exhausted."""
    model = _RepeatedToolCallModel("search")

    response = model.response(
        messages=[Message(role="user", content="Find Agno")],
        tools=[Function.from_callable(_search_knowledge, name="search")],
        tool_call_limit=1,
    )

    assert model.invocations == 3
    assert model.requested_tools[2] == []
    assert model.requested_tool_choices[2] == "none"
    assert response.content == "fallback answer"


@pytest.mark.asyncio
async def test_aresponse_allows_one_tool_free_final_answer_after_limit_refusal():
    """Async non-streaming response also synthesizes after the limit is exhausted."""
    model = _RepeatedToolCallModel("search")

    response = await model.aresponse(
        messages=[Message(role="user", content="Find Agno")],
        tools=[Function.from_callable(_search_knowledge, name="search")],
        tool_call_limit=1,
    )

    assert model.invocations == 3
    assert model.requested_tools[2] == []
    assert model.requested_tool_choices[2] == "none"
    assert response.content == "fallback answer"


def test_agentic_rag_synthesizes_after_search_knowledge_exhausts_tool_budget():
    """Agentic-RAG preserves its final answer when another search is refused.

    This exercises Agent's ``search_knowledge=True`` tool registration and
    execution path rather than supplying the search function as a model tool.
    The final, tool-free model turn can synthesize from the successful search.
    """
    retrieved_queries: List[str] = []

    def retrieve(query: str, num_documents: Optional[int] = None) -> List[dict]:
        retrieved_queries.append(query)
        return [{"content": "Agno is an agent framework."}]

    model = _RepeatedToolCallModel("search_knowledge_base")
    agent = Agent(
        model=model,
        search_knowledge=True,
        knowledge_retriever=retrieve,
        tool_call_limit=1,
    )

    result = agent.run("What is Agno?")

    assert retrieved_queries == ["Agno"]
    assert model.invocations == 3
    assert model.requested_tools[2] == []
    assert model.requested_tool_choices[2] == "none"
    assert result.content == "fallback answer"


# --- the guard is present in every response loop ----------------------------


def test_guard_present_in_all_four_response_loops():
    """Sync, async, streaming and async-streaming loops must all carry the guard."""
    import inspect

    import agno.models.base as base

    for fn in (
        base.Model.response,
        base.Model.aresponse,
        base.Model.response_stream,
        base.Model.aresponse_stream,
    ):
        source = inspect.getsource(fn)
        assert "all(m.tool_call_limit_reached for m in function_call_results)" in source, (
            f"{fn.__name__} is missing the tool_call_limit stop guard"
        )
