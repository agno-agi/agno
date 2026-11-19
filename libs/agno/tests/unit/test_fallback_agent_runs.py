"""Agent runs on a sticky fallback keep its completed tool turns, whether the run is cancelled or the model fails."""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.exceptions import ModelProviderError
from agno.media import Image
from agno.models.base import Model
from agno.models.fallback import FallbackConfig
from agno.models.response import ModelResponse, ModelResponseEvent
from agno.run import RunContext
from agno.run.cancel import cancel_run
from agno.tools.function import ToolResult


class _ScriptedModel(Model):
    """Emits scripted turns offline: ('tool', name, call_id), ('content', text) or ('error',)."""

    def __init__(self, model_id: str, script: List[tuple]):
        super().__init__(id=model_id, name=model_id, provider="test")
        self._script = list(script)
        self._i = 0

    def _next(self) -> ModelResponse:
        turn = self._script[min(self._i, len(self._script) - 1)]
        self._i += 1
        if turn[0] == "error":
            raise ModelProviderError("service unavailable", status_code=503)
        if turn[0] == "tool":
            response = ModelResponse(role="assistant")
            response.tool_calls = [
                {"id": turn[2], "type": "function", "function": {"name": turn[1], "arguments": json.dumps({})}}
            ]
            return response
        response = ModelResponse(content=turn[1], role="assistant")
        response.event = ModelResponseEvent.assistant_response.value
        return response

    def invoke(self, *a, **k):
        return self._next()

    async def ainvoke(self, *a, **k):
        return self._next()

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next()

    def _parse_provider_response(self, response: Any, **k) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response if isinstance(response, ModelResponse) else ModelResponse()


def cancel_me(run_context: RunContext) -> str:
    """Cancel the run that called this tool."""
    cancel_run(run_context.run_id)
    return "cancel requested"


def _agent() -> Agent:
    primary = _ScriptedModel("primary", [("content", "primary should not run")])
    fallback = _ScriptedModel("fallback", [("tool", "cancel_me", "call-1"), ("content", "done")])
    config = FallbackConfig(on_error=[fallback], sticky=True)
    config.set_sticky_fallback(primary, fallback)
    return Agent(model=primary, fallback_config=config, tools=[cancel_me], db=InMemoryDb(), telemetry=False)


def _stored_roles(agent: Agent, session_id: str) -> List[str]:
    run = agent.get_session(session_id=session_id).runs[-1]
    return [m.role for m in run.messages or [] if m.role != "system"]


@pytest.mark.asyncio
async def test_async_stream_cancelled_on_sticky_keeps_tool_turn():
    agent = _agent()
    async for _ in agent.arun("go", session_id="s1", stream=True):
        pass

    assert _stored_roles(agent, "s1") == ["user", "assistant", "tool"]


def test_stream_cancelled_on_sticky_keeps_tool_turn():
    agent = _agent()
    for _ in agent.run("go", session_id="s2", stream=True):
        pass

    assert _stored_roles(agent, "s2") == ["user", "assistant", "tool"]


ORDERS: List[str] = []


def place_order() -> str:
    """Place the order."""
    ORDERS.append("order")
    return "order placed"


class _OrderingModel(_ScriptedModel):
    """Places the order unless it can see the order was already placed, as a real model would."""

    def _next(self, messages=None) -> ModelResponse:
        if any(m.role == "tool" for m in messages or []):
            self._script = [("content", "your order is placed")]
        else:
            self._script = [("tool", "place_order", "call-primary")]
        self._i = 0
        return super()._next()

    def invoke(self, *a, **k):
        return self._next(k.get("messages"))

    async def ainvoke(self, *a, **k):
        return self._next(k.get("messages"))

    def invoke_stream(self, *a, **k) -> Iterator[ModelResponse]:
        yield self._next(k.get("messages"))

    async def ainvoke_stream(self, *a, **k) -> AsyncIterator[ModelResponse]:
        yield self._next(k.get("messages"))


@pytest.mark.parametrize("stream", [False, True])
def test_primary_does_not_rerun_tools_the_failed_sticky_ran(stream):
    ORDERS.clear()
    primary = _OrderingModel("primary", [])
    fallback = _ScriptedModel("fallback", [("tool", "place_order", "call-1"), ("error",)])
    config = FallbackConfig(on_error=[fallback], sticky=True)
    config.set_sticky_fallback(primary, fallback)
    agent = Agent(model=primary, fallback_config=config, tools=[place_order], db=InMemoryDb(), telemetry=False)

    if stream:
        for _ in agent.run("buy it", session_id="s3", stream=True):
            pass
    else:
        agent.run("buy it", session_id="s3")

    assert ORDERS == ["order"]
    assert _stored_roles(agent, "s3") == ["user", "assistant", "tool", "assistant"]


@pytest.mark.asyncio
async def test_async_primary_does_not_rerun_tools_the_failed_sticky_ran():
    ORDERS.clear()
    primary = _OrderingModel("primary", [])
    fallback = _ScriptedModel("fallback", [("tool", "place_order", "call-1"), ("error",)])
    config = FallbackConfig(on_error=[fallback], sticky=True)
    config.set_sticky_fallback(primary, fallback)
    agent = Agent(model=primary, fallback_config=config, tools=[place_order], db=InMemoryDb(), telemetry=False)

    await agent.arun("buy it", session_id="s4")

    assert ORDERS == ["order"]


class _GuidanceStrippingModel(_ScriptedModel):
    """Fails once with retry guidance, then streams an answer and strips the guidance, as Gemini does."""

    def __init__(self, model_id: str):
        super().__init__(model_id, [("content", "answer")])
        self._failed = False

    def _stream(self, messages, retry_with_guidance):
        from agno.exceptions import RetryableModelProviderError

        if not self._failed:
            self._failed = True
            raise RetryableModelProviderError(original_error="bad output", retry_guidance_message="be precise")
        yield self._next()
        if retry_with_guidance:
            self._remove_temporary_messages(messages)

    def invoke_stream(self, *a, messages=None, retry_with_guidance=False, **k) -> Iterator[ModelResponse]:
        yield from self._stream(messages, retry_with_guidance)

    async def ainvoke_stream(self, *a, messages=None, retry_with_guidance=False, **k) -> AsyncIterator[ModelResponse]:
        for response in self._stream(messages, retry_with_guidance):
            yield response


def _guidance_agent() -> Agent:
    primary = _ScriptedModel("primary", [("content", "primary should not run")])
    fallback = _GuidanceStrippingModel("fallback")
    config = FallbackConfig(on_error=[fallback], sticky=True)
    config.set_sticky_fallback(primary, fallback)
    return Agent(model=primary, fallback_config=config, db=InMemoryDb(), telemetry=False)


def _stored_contents(agent: Agent, session_id: str) -> List[str]:
    run = agent.get_session(session_id=session_id).runs[-1]
    return [m.content for m in run.messages or [] if m.role != "system"]


def test_stream_sticky_retry_with_guidance_stores_the_answer():
    agent = _guidance_agent()
    for _ in agent.run("go", session_id="g1", stream=True):
        pass

    assert _stored_contents(agent, "g1") == ["go", "answer"]


@pytest.mark.asyncio
async def test_async_stream_sticky_retry_with_guidance_stores_the_answer():
    agent = _guidance_agent()
    async for _ in agent.arun("go", session_id="g2", stream=True):
        pass

    assert _stored_contents(agent, "g2") == ["go", "answer"]


def _ordering_agent() -> Agent:
    primary = _OrderingModel("primary", [])
    fallback = _ScriptedModel("fallback", [("tool", "place_order", "call-1"), ("error",)])
    config = FallbackConfig(on_error=[fallback], sticky=True)
    config.set_sticky_fallback(primary, fallback)
    return Agent(model=primary, fallback_config=config, tools=[place_order], db=InMemoryDb(), telemetry=False)


def test_run_tools_include_the_failed_sticky_models_tools():
    ORDERS.clear()
    run = _ordering_agent().run("buy it", session_id="t1")

    assert [t.tool_name for t in run.tools or []] == ["place_order"]


@pytest.mark.asyncio
async def test_async_run_tools_include_the_failed_sticky_models_tools():
    ORDERS.clear()
    run = await _ordering_agent().arun("buy it", session_id="t2")

    assert [t.tool_name for t in run.tools or []] == ["place_order"]


def test_run_tools_include_the_failed_primarys_tools():
    """The primary runs a tool, then fails; the fallback that finishes the run reports that tool too."""
    ORDERS.clear()
    primary = _ScriptedModel("primary", [("tool", "place_order", "call-1"), ("error",)])
    fallback = _OrderingModel("fallback", [])
    agent = Agent(model=primary, fallback_models=[fallback], tools=[place_order], db=InMemoryDb(), telemetry=False)

    run = agent.run("buy it", session_id="t3")

    assert ORDERS == ["order"]
    assert [t.tool_name for t in run.tools or []] == ["place_order"]


def draw_chart() -> ToolResult:
    """Draw the chart."""
    return ToolResult(content="chart drawn", images=[Image(url="https://example.com/chart.png")])


def _media_agent(fallback_script) -> Agent:
    primary = _ScriptedModel("primary", [("content", "here is your chart")])
    fallback = _ScriptedModel("fallback", fallback_script)
    config = FallbackConfig(on_error=[fallback], sticky=True)
    config.set_sticky_fallback(primary, fallback)
    return Agent(model=primary, fallback_config=config, tools=[draw_chart], db=InMemoryDb(), telemetry=False)


def test_run_keeps_media_a_failed_sticky_tool_produced():
    run = _media_agent([("tool", "draw_chart", "call-1"), ("error",)]).run("chart it", session_id="m1")

    assert [t.tool_name for t in run.tools or []] == ["draw_chart"]
    assert [i.url for i in run.images or []] == ["https://example.com/chart.png"]


@pytest.mark.asyncio
async def test_async_run_keeps_media_a_failed_sticky_tool_produced():
    run = await _media_agent([("tool", "draw_chart", "call-1"), ("error",)]).arun("chart it", session_id="m2")

    assert [i.url for i in run.images or []] == ["https://example.com/chart.png"]
