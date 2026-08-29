"""expose_tools: compact_status / compact_run model tools and the requested trigger."""

import json
from typing import Any, AsyncIterator, Iterator, List

from agno.agent import Agent
from agno.compaction import Compaction
from agno.compaction.compaction import get_owner_records
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse

SUMMARY_TEXT = "## Goal\nRequested summary."


class ScriptedModel(Model):
    """Plays a fixed script of responses; records payloads."""

    def __init__(self, script: List[ModelResponse], model_id: str = "scripted-test") -> None:
        super().__init__(id=model_id, name=model_id, provider="test")
        self.script = script
        self.calls: List[List] = []

    def __deepcopy__(self, memo: dict) -> "ScriptedModel":
        clone = type(self)(self.script, model_id=self.id)
        clone.calls = self.calls
        return clone

    def invoke(self, *args: Any, messages=None, **kwargs: Any) -> ModelResponse:
        self.calls.append(list(messages or []))
        index = min(len(self.calls) - 1, len(self.script) - 1)
        return self.script[index]

    async def ainvoke(self, *args: Any, messages=None, **kwargs: Any) -> ModelResponse:
        return self.invoke(messages=messages)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("streaming not used")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("streaming not used")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


class SummarizerModel(ScriptedModel):
    def __init__(self) -> None:
        super().__init__([ModelResponse(role="assistant", content=SUMMARY_TEXT)], model_id="summarizer-test")


def tool_call(call_id: str, name: str, arguments: dict) -> ModelResponse:
    return ModelResponse(
        role="assistant",
        tool_calls=[
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
        ],
    )


def make_agent(script: List[ModelResponse]) -> Agent:
    return Agent(
        id="tools-agent",
        model=ScriptedModel(script),
        db=InMemoryDb(),
        add_history_to_context=True,
        compaction=Compaction(
            context_window=4_000,
            model=SummarizerModel(),
            background=False,
            expose_tools=True,
        ),
        telemetry=False,
    )


def grow_history(agent: Agent, session_id: str, turns: int = 4) -> None:
    filler = Agent(
        id="tools-agent",
        model=ScriptedModel([ModelResponse(role="assistant", content="pad " * 400)]),
        db=agent.db,
        add_history_to_context=True,
        compaction=Compaction(context_window=4_000, model=SummarizerModel(), background=False),
        telemetry=False,
    )
    for _ in range(turns):
        filler.run("more " + "word " * 200, session_id=session_id)


class TestExposeTools:
    def test_compact_run_schedules_requested_pass(self):
        script = [
            tool_call("c1", "compact_run", {"instructions": "keep the file list"}),
            ModelResponse(role="assistant", content="done after compaction"),
        ]
        agent = make_agent(script)
        session_id = "s-tools-1"
        grow_history(agent, session_id)

        output = agent.run("now compact", session_id=session_id)
        assert "done after compaction" in str(output.content)
        session = agent.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "tools-agent")
        assert any(r.reason == "requested" for r in records), [r.reason for r in records]

    def test_compact_status_returns_numbers(self):
        script = [
            tool_call("c1", "compact_status", {}),
            ModelResponse(role="assistant", content="checked"),
        ]
        agent = make_agent(script)
        session_id = "s-tools-2"
        output = agent.run("status please", session_id=session_id)
        tool_messages = [m for m in (output.messages or []) if m.role == "tool"]
        assert tool_messages, "no tool result"
        payload = json.loads(tool_messages[0].content)
        assert payload["window"] == 4_000
        assert payload["trigger_tokens"] == 3_400
        assert "records" in payload

    def test_tools_absent_by_default(self):
        class ToolCapturingModel(ScriptedModel):
            def invoke(self, *args: Any, messages=None, tools=None, **kwargs: Any) -> ModelResponse:
                self.seen_tools = tools or []
                return super().invoke(messages=messages)

        model = ToolCapturingModel([ModelResponse(role="assistant", content="hi")])
        agent = Agent(
            id="tools-agent-off",
            model=model,
            db=InMemoryDb(),
            compaction=Compaction(context_window=4_000, background=False),
            telemetry=False,
        )
        agent.run("hello", session_id="s-tools-3")
        names = {tool.get("function", {}).get("name") for tool in model.seen_tools if isinstance(tool, dict)}
        assert "compact_status" not in names and "compact_run" not in names

    def test_tools_present_when_exposed(self):
        class ToolCapturingModel(ScriptedModel):
            def invoke(self, *args: Any, messages=None, tools=None, **kwargs: Any) -> ModelResponse:
                self.seen_tools = tools or []
                return super().invoke(messages=messages)

        model = ToolCapturingModel([ModelResponse(role="assistant", content="hi")])
        agent = Agent(
            id="tools-agent-on",
            model=model,
            db=InMemoryDb(),
            compaction=Compaction(context_window=4_000, background=False, expose_tools=True),
            telemetry=False,
        )
        agent.run("hello", session_id="s-tools-4")
        names = {tool.get("function", {}).get("name") for tool in model.seen_tools if isinstance(tool, dict)}
        assert "compact_status" in names and "compact_run" in names
