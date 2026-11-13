"""Run content is the last model call's text, not every call's text glued together (#11641).

In a run like "text + tool call -> text + tool call -> final text", each model call
writes its own assistant message. ``RunOutput.content`` must hold only the final
call's text in every mode (run/arun, with and without streaming), while the earlier
texts stay in ``RunOutput.messages`` and are still streamed as content deltas.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent, RunContentEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent

PROMPT = "add apples and bananas to my cart"
NARRATION = ["Let me add the apples.", "Now the bananas."]
FINAL_TEXT = "Both fruits are in your cart."
NARRATED_SCRIPT = [
    {"content": NARRATION[0], "tool": "add_to_cart", "args": '{"item": "apples"}'},
    {"content": NARRATION[1], "tool": "add_to_cart", "args": '{"item": "bananas"}'},
    {"content": FINAL_TEXT},
]

# (stream, use_async) for run, arun, run(stream=True), arun(stream=True)
MODES = [(False, False), (False, True), (True, False), (True, True)]
MODE_IDS = ["run", "arun", "run-stream", "arun-stream"]


class ScriptedModel(Model):
    """Offline model that plays back one scripted step per model call.

    When streaming, the text arrives in two chunks followed by a separate tool-call
    chunk, the way providers stream it.
    """

    def __init__(self, script: list[dict]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = script
        self.calls = 0

    def _step(self) -> dict:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return step

    def _tool_calls(self, step: dict) -> Any:
        if not step.get("tool"):
            return None
        call = {"name": step["tool"], "arguments": step["args"]}
        return [{"type": "function", "id": f"call_{self.calls}", "function": call}]

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        step = self._step()
        return ModelResponse(
            role="assistant",
            content=step.get("content"),
            tool_calls=self._tool_calls(step),
            response_usage=MessageMetrics(),
        )

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        step = self._step()
        text = step.get("content") or ""
        half = len(text) // 2
        for chunk in (text[:half], text[half:]):
            if chunk:
                yield ModelResponse(role="assistant", content=chunk)
        yield ModelResponse(role="assistant", tool_calls=self._tool_calls(step), response_usage=MessageMetrics())

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        for chunk in self.invoke_stream(*args, **kwargs):
            yield chunk

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def add_to_cart(item: str) -> str:
    """Add an item to the grocery cart."""
    return f"added {item}"


def run_in_mode(entity: Any, stream: bool, use_async: bool) -> tuple[Any, list[Any]]:
    """Run an Agent or Team in one of the four modes; return its stored run output and streamed events."""
    if not stream:
        output = asyncio.run(entity.arun(PROMPT)) if use_async else entity.run(PROMPT)
        return output, []

    async def collect() -> list[Any]:
        return [event async for event in entity.arun(PROMPT, stream=True, stream_events=True)]

    events = asyncio.run(collect()) if use_async else list(entity.run(PROMPT, stream=True, stream_events=True))
    return entity.get_last_run_output(), events


def assert_last_call_text(output: Any, events: list[Any], stream: bool) -> None:
    assert output.content == FINAL_TEXT
    # The narration is not lost: each model call keeps its own assistant message.
    assistant_texts = [m.get_content_string() for m in output.messages if m.role == "assistant" and m.content]
    assert assistant_texts == [*NARRATION, FINAL_TEXT]
    if stream:
        completed = [e for e in events if isinstance(e, (RunCompletedEvent, TeamRunCompletedEvent))]
        assert completed[-1].content == FINAL_TEXT
        # Streaming still emits every delta, narration included.
        deltas = [e.content for e in events if isinstance(e, (RunContentEvent, TeamRunContentEvent))]
        assert "".join(deltas) == "".join([*NARRATION, FINAL_TEXT])


def make_agent(script: list[dict]) -> Agent:
    return Agent(model=ScriptedModel(script), tools=[add_to_cart], db=InMemoryDb())


@pytest.mark.parametrize("stream,use_async", MODES, ids=MODE_IDS)
def test_content_is_last_model_call_text(stream: bool, use_async: bool):
    output, events = run_in_mode(make_agent(NARRATED_SCRIPT), stream, use_async)
    assert_last_call_text(output, events, stream)


@pytest.mark.parametrize("stream,use_async", MODES, ids=MODE_IDS)
def test_single_model_call_is_unchanged(stream: bool, use_async: bool):
    output, _ = run_in_mode(make_agent([{"content": "Hello!"}]), stream, use_async)
    assert output.content == "Hello!"


@pytest.mark.parametrize("stream,use_async", MODES, ids=MODE_IDS)
def test_tool_call_without_narration(stream: bool, use_async: bool):
    script = [{"tool": "add_to_cart", "args": '{"item": "apples"}'}, {"content": "Added."}]
    output, _ = run_in_mode(make_agent(script), stream, use_async)
    assert output.content == "Added."


@pytest.mark.parametrize("stream,use_async", MODES, ids=MODE_IDS)
def test_final_call_without_text_gives_no_content(stream: bool, use_async: bool):
    """Every mode agrees when the last call writes nothing: the narration is not the answer."""
    script = [{"content": NARRATION[0], "tool": "add_to_cart", "args": '{"item": "apples"}'}, {"content": ""}]
    output, _ = run_in_mode(make_agent(script), stream, use_async)
    assert not output.content
