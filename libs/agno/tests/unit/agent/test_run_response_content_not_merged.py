"""Regression tests for agno-agi/agno#10936.

When an agent made multiple LLM API calls within a single run (e.g.
text -> tool call -> text -> tool call), ``Model._process_model_response``
concatenated the assistant text of *every* call into ``model_response.content``,
and ``update_run_response`` copied that merged blob into ``run_response.content``.
The saved history then lost the text<->tool-call interleaving order.

Expected behavior: each LLM call keeps its own assistant message, and
``run_response.content`` holds only the latest call's assistant text.
"""

from collections.abc import AsyncIterator, Iterator
from typing import Any

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.message import Message, MessageMetrics
from agno.models.response import ModelResponse
from agno.tools.function import Function


class ScriptedModel(Model):
    """Offline model returning a canned script of (text, tool_calls) steps.

    Once the script is exhausted it answers with a plain final text so the
    run always terminates.
    """

    def __init__(self, script: list[dict]):
        super().__init__(id="scripted", name="scripted", provider="test")
        self.script = list(script)
        self.calls = 0

    def get_instructions_for_model(self, *args, **kwargs):
        return None

    def get_system_message_for_model(self, *args, **kwargs):
        return None

    async def aget_instructions_for_model(self, *args, **kwargs):
        return None

    async def aget_system_message_for_model(self, *args, **kwargs):
        return None

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response

    def _next(self) -> ModelResponse:
        self.calls += 1
        if self.calls <= len(self.script):
            item = self.script[self.calls - 1]
        else:
            item = {"content": "Fallback final answer."}
        return ModelResponse(
            content=item.get("content"),
            role="assistant",
            tool_calls=item.get("tool_calls"),
            response_usage=MessageMetrics(),
        )

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self._next()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self._next()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self._next()
        return


def get_weather(city: str) -> str:
    """Get the weather for a city."""
    return "sunny"


def _tool_call(call_id: str = "call_1") -> list[dict]:
    return [
        {
            "type": "function",
            "id": call_id,
            "function": {"name": "get_weather", "arguments": '{"city": "SF"}'},
        }
    ]


def _make_agent(script: list[dict], **kwargs) -> Agent:
    return Agent(model=ScriptedModel(script), tools=[get_weather], db=InMemoryDb(), **kwargs)


def _message_summary(resp) -> list[tuple]:
    return [
        (m.role, m.get_content_string() if m.content is not None else None, bool(m.tool_calls)) for m in resp.messages
    ]


class TestRunResponseContentNotMerged:
    def test_sync_run_content_is_last_assistant_text(self):
        """text -> tool -> text: content must be the last text, not a merge."""
        agent = _make_agent(
            [
                {"content": "Let me check.", "tool_calls": _tool_call()},
                {"content": "Here is the result: sunny."},
            ]
        )
        resp = agent.run("What is the weather in SF?")

        assert resp.content == "Here is the result: sunny."
        # The individual messages keep their own text in order.
        assert _message_summary(resp) == [
            ("user", "What is the weather in SF?", False),
            ("assistant", "Let me check.", True),
            ("tool", "sunny", False),
            ("assistant", "Here is the result: sunny.", False),
        ]

    def test_three_calls_content_is_last_text_only(self):
        """text -> tool -> text -> tool -> text: earlier texts must not leak in."""
        agent = _make_agent(
            [
                {"content": "First thought.", "tool_calls": _tool_call("call_1")},
                {"content": "Second thought.", "tool_calls": _tool_call("call_2")},
                {"content": "Final answer."},
            ]
        )
        resp = agent.run("What is the weather in SF?")

        assert resp.content == "Final answer."
        assert "First thought." not in (resp.content or "")
        assert "Second thought." not in (resp.content or "")

    async def test_async_run_content_is_last_assistant_text(self):
        agent = _make_agent(
            [
                {"content": "Let me check.", "tool_calls": _tool_call()},
                {"content": "Here is the result: sunny."},
            ]
        )
        resp = await agent.arun("What is the weather in SF?")

        assert resp.content == "Here is the result: sunny."

    def test_streaming_run_content_is_last_assistant_text(self):
        agent = _make_agent(
            [
                {"content": "Let me check.", "tool_calls": _tool_call()},
                {"content": "Here is the result: sunny."},
            ]
        )
        for _event in agent.run("What is the weather in SF?", stream=True):
            pass

        # The persisted run (what lands in the session DB) must hold only the
        # latest call's text, not the concatenation of every streamed call.
        session = agent.get_session()
        assert session.runs
        assert session.runs[-1].content == "Here is the result: sunny."

    def test_model_response_content_replaced_per_call(self):
        """Model layer: content reflects the latest call, never the concatenation."""
        model = ScriptedModel(
            [
                {"content": "Let me check.", "tool_calls": _tool_call()},
                {"content": "Here is the result: sunny."},
            ]
        )
        model_response = model.response(
            messages=[Message(role="user", content="What is the weather in SF?")],
            tools=[Function.from_callable(get_weather)],
        )

        assert model_response.content == "Here is the result: sunny."

    def test_tool_call_only_response_does_not_crash(self):
        """A call with no assistant text must not break content handling."""
        agent = _make_agent(
            [
                {"content": "Let me check.", "tool_calls": _tool_call()},
                {"content": None, "tool_calls": _tool_call("call_2")},
            ]
        )
        resp = agent.run("What is the weather in SF?")

        # Script exhausted -> fallback final answer; the point is no crash and
        # no merged blob.
        assert resp.content == "Fallback final answer."
