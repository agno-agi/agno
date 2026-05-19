"""Regression tests for tool_call_limit enforcement across HITL pause/resume.

Reproduces https://github.com/agno-agi/agno/issues/7962

The model loop in ``agno/models/base.py`` initialized ``function_call_count = 0``
at the start of *every* ``response`` / ``aresponse`` / ``response_stream`` /
``aresponse_stream`` invocation. When an agent pauses for HITL and resumes,
``continue_run`` invokes a fresh model loop, so the previously-executed tool
call (the one that triggered the pause) was no longer counted. With
``tool_call_limit=1`` the agent could therefore issue another tool call after
resume even though the cumulative limit had already been reached pre-pause.

These tests use a mock model (no network / API keys) that drives the *real*
``Model`` loop: it returns a tool call first (which pauses for confirmation),
then a second (hallucinated) tool call after resume. With the limit enforced
cumulatively the second tool call must be blocked.
"""

import json
from typing import Any, AsyncIterator, Iterator, List
from uuid import uuid4

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.tools.decorator import tool

executions: List[str] = []


@tool(requires_confirmation=True)
def get_the_weather(city: str) -> str:
    executions.append(city)
    return f"It is currently 70 degrees and cloudy in {city}"


def _tool_call(city: str) -> dict:
    return {
        "id": f"call_{uuid4().hex[:8]}",
        "type": "function",
        "function": {"name": "get_the_weather", "arguments": json.dumps({"city": city})},
    }


class _ScriptedModel(Model):
    """Mock model that keeps the real Model loop but scripts provider output.

    Every model invocation returns the next scripted ``ModelResponse``:
      1. a tool call (pauses for confirmation)
      2. another tool call after resume (should be blocked by the limit)
      3. plain content (so the run can finish)
    """

    def __init__(self) -> None:
        super().__init__(id="scripted-model", name="scripted-model", provider="test")
        self._step = 0

    def _next_response(self) -> ModelResponse:
        step = self._step
        self._step += 1
        if step == 0:
            return ModelResponse(
                role="assistant",
                tool_calls=[_tool_call("Tokyo")],
                response_usage=MessageMetrics(),
            )
        if step == 1:
            # After resume the model "hallucinates" another tool call.
            return ModelResponse(
                role="assistant",
                tool_calls=[_tool_call("Paris")],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(
            role="assistant",
            content="The weather in Tokyo is 70 degrees and cloudy.",
            response_usage=MessageMetrics(),
        )

    # --- non-streaming ---
    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next_response()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next_response()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    # --- streaming ---
    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next_response()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next_response()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response

    # Mock model has no real prompt construction
    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None


def _make_agent() -> Agent:
    return Agent(
        model=_ScriptedModel(),
        tools=[get_the_weather],
        tool_call_limit=1,
        db=InMemoryDb(),
        telemetry=False,
    )


def _assert_paused_with_one_tool(response) -> None:
    assert response is not None
    assert response.is_paused
    assert response.tools is not None
    assert len(response.tools) == 1
    assert response.tools[0].tool_name == "get_the_weather"
    assert response.tools[0].tool_args == {"city": "Tokyo"}


def _assert_limit_enforced_after_resume(response) -> None:
    # The run must complete instead of pausing again for the (hallucinated)
    # post-resume tool call.
    assert response is not None
    assert response.is_paused is False

    # Only the approved pre-pause tool actually executed.
    assert executions == ["Tokyo"]

    # Exactly one tool execution is recorded for the whole run: the post-resume
    # call was blocked and never became a ToolExecution.
    assert response.tools is not None
    assert len(response.tools) == 1
    assert response.tools[0].tool_args == {"city": "Tokyo"}
    assert response.tools[0].result == "It is currently 70 degrees and cloudy in Tokyo"

    # The blocked call surfaces as a tool_call_limit error message back to the
    # model, which proves the cumulative limit was enforced post-resume.
    limit_errors = [
        m
        for m in (response.messages or [])
        if m.tool_call_error and isinstance(m.content, str) and "Tool call limit reached" in m.content
    ]
    assert len(limit_errors) == 1, "Post-resume tool call should be blocked by cumulative tool_call_limit"


def test_tool_call_limit_enforced_across_hitl_resume_sync():
    executions.clear()
    agent = _make_agent()

    response = agent.run("What is the weather in Tokyo?")
    _assert_paused_with_one_tool(response)

    # Approve the paused tool and resume the run.
    response.tools[0].confirmed = True
    response = agent.continue_run(response)

    _assert_limit_enforced_after_resume(response)


@pytest.mark.asyncio
async def test_tool_call_limit_enforced_across_hitl_resume_async():
    executions.clear()
    agent = _make_agent()

    response = await agent.arun("What is the weather in Tokyo?")
    _assert_paused_with_one_tool(response)

    response.tools[0].confirmed = True
    response = await agent.acontinue_run(response)

    _assert_limit_enforced_after_resume(response)


def test_tool_call_limit_enforced_across_hitl_resume_sync_stream():
    executions.clear()
    agent = _make_agent()

    response = None
    for _ in agent.run("What is the weather in Tokyo?", stream=True, yield_run_output=True):
        response = _
    _assert_paused_with_one_tool(response)

    response.tools[0].confirmed = True
    final = None
    for _ in agent.continue_run(response, stream=True, yield_run_output=True):
        final = _
    _assert_limit_enforced_after_resume(final)


@pytest.mark.asyncio
async def test_tool_call_limit_enforced_across_hitl_resume_async_stream():
    executions.clear()
    agent = _make_agent()

    response = None
    async for _ in agent.arun("What is the weather in Tokyo?", stream=True, yield_run_output=True):
        response = _
    _assert_paused_with_one_tool(response)

    response.tools[0].confirmed = True
    final = None
    async for _ in agent.acontinue_run(response, stream=True, yield_run_output=True):
        final = _
    _assert_limit_enforced_after_resume(final)


class _ThreeCallScriptedModel(_ScriptedModel):
    """Scripts three confirmation tool calls then plain content.

    Reuses the base harness; only the response script is extended so the
    cumulative ``tool_call_limit`` boundary can be probed with a limit > 1:

      step 0 -> tool call "Tokyo"  (1st call, pauses for confirmation)
      step 1 -> tool call "Paris"  (2nd call, pauses for confirmation)
      step 2 -> tool call "Berlin" (3rd call, must be blocked at limit=2)
      step 3 -> plain content      (run finishes)
    """

    def _next_response(self) -> ModelResponse:
        step = self._step
        self._step += 1
        if step == 0:
            return ModelResponse(
                role="assistant",
                tool_calls=[_tool_call("Tokyo")],
                response_usage=MessageMetrics(),
            )
        if step == 1:
            return ModelResponse(
                role="assistant",
                tool_calls=[_tool_call("Paris")],
                response_usage=MessageMetrics(),
            )
        if step == 2:
            return ModelResponse(
                role="assistant",
                tool_calls=[_tool_call("Berlin")],
                response_usage=MessageMetrics(),
            )
        return ModelResponse(
            role="assistant",
            content="The weather has been reported.",
            response_usage=MessageMetrics(),
        )


def test_tool_call_limit_cumulative_no_double_count_across_hitl_resume_sync():
    """tool_call_limit=2: seed + in-loop increment count *disjoint* sets.

    This locks in the property the four limit=1 tests above do NOT prove:
    that the pre-pause call(s) seeded from ``run_response.tools`` and the
    post-resume call(s) counted inside the fresh model loop are summed
    without overlap (no double-count) *and* without forgetting prior calls
    (cumulative, not per-invocation).

      - Call #1 "Tokyo": cumulative 1 <= 2 -> allowed, pauses for confirm.
      - Resume, Call #2 "Paris": seed=1 (Tokyo) + 1 = 2 <= 2 -> STILL
        allowed (proves no double-count: a double-counted seed would be 2,
        making this 3 > 2 and wrongly blocked), pauses for confirm.
      - Resume, Call #3 "Berlin": seed=2 (Tokyo, Paris) + 1 = 3 > 2 ->
        BLOCKED (proves the count is cumulative across both resumes; with
        the pre-fix per-invocation reset the seed would be 0 and this 3rd
        call would be allowed and pause again).
    """
    executions.clear()
    agent = Agent(
        model=_ThreeCallScriptedModel(),
        tools=[get_the_weather],
        tool_call_limit=2,
        db=InMemoryDb(),
        telemetry=False,
    )

    # Call #1 -> allowed under limit=2, pauses for confirmation.
    response = agent.run("What is the weather?")
    assert response is not None
    assert response.is_paused
    assert response.tools is not None
    assert len(response.tools) == 1
    assert response.tools[0].tool_args == {"city": "Tokyo"}

    # Approve #1; resume. Call #2 must STILL be allowed (cumulative 2 == 2,
    # not over) -> it executes Tokyo then pauses again for Paris. If the
    # seed double-counted, #2 would be wrongly blocked here.
    response.tools[0].confirmed = True
    response = agent.continue_run(response)
    assert response is not None
    assert response.is_paused, "2nd call must be allowed under limit=2 (no double-count of the seed)"
    assert executions == ["Tokyo"]
    assert any(t.tool_args == {"city": "Paris"} for t in (response.tools or []))
    assert all(
        "Tool call limit reached" not in (m.content or "") for m in (response.messages or []) if m.tool_call_error
    )

    # Approve #2 (the still-paused Paris call; Tokyo is already executed) and
    # resume. Now cumulative is 2 (Tokyo + Paris); Call #3 "Berlin" pushes it
    # to 3 > 2 and must be BLOCKED. The run finishes instead of pausing a 3rd
    # time, and a tool_call_limit error surfaces.
    for paused_tool in response.tools or []:
        if paused_tool.result is None:
            paused_tool.confirmed = True
    final = agent.continue_run(response)
    assert final is not None
    assert final.is_paused is False, "3rd call must be blocked (cumulative limit reached across both resumes)"
    assert executions == ["Tokyo", "Paris"], "Berlin must never execute (blocked by cumulative limit)"

    weather_tools = [t for t in (final.tools or []) if t.tool_name == "get_the_weather"]
    assert len(weather_tools) == 2
    assert {t.tool_args["city"] for t in weather_tools} == {"Tokyo", "Paris"}

    limit_errors = [
        m
        for m in (final.messages or [])
        if m.tool_call_error and isinstance(m.content, str) and "Tool call limit reached" in m.content
    ]
    assert len(limit_errors) == 1, "3rd tool call should be blocked by the cumulative tool_call_limit"
