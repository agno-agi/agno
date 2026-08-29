"""In-run seam: mid-loop passes, derived views, INV-2 (one list), overflow recovery."""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.compaction import Compaction
from agno.compaction.compaction import get_owner_records
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.db.in_memory import InMemoryDb
from agno.exceptions import ContextWindowExceededError
from agno.models.base import Model
from agno.models.response import ModelResponse

SUMMARY_TEXT = "## Goal\nSummarized tool loop."


class ToolLoopModel(Model):
    """Requests `tool_rounds` lookup calls, then finishes. Records every payload it received."""

    def __init__(
        self,
        tool_rounds: int,
        model_id: str = "tool-loop-test",
        overflow_on_call: int = 0,
        assistant_padding: int = 0,
    ) -> None:
        super().__init__(id=model_id, name=model_id, provider="test")
        self.tool_rounds = tool_rounds
        self.overflow_on_call = overflow_on_call  # 1-based call number that raises overflow once
        self.assistant_padding = assistant_padding  # tokens of prose alongside each tool call
        self.calls: List[List] = []
        self.overflow_raised = False

    def __deepcopy__(self, memo: dict) -> "ToolLoopModel":
        clone = type(self)(
            self.tool_rounds,
            model_id=self.id,
            overflow_on_call=self.overflow_on_call,
            assistant_padding=self.assistant_padding,
        )
        clone.calls = self.calls
        return clone

    def _respond(self, messages) -> ModelResponse:
        self.calls.append(list(messages))
        if self.overflow_on_call and len(self.calls) == self.overflow_on_call and not self.overflow_raised:
            self.overflow_raised = True
            raise ContextWindowExceededError("prompt is too long", model_name=self.name, model_id=self.id)
        call_number = len([c for c in self.calls])
        if call_number <= self.tool_rounds:
            return ModelResponse(
                role="assistant",
                content=("thinking " * self.assistant_padding) or None,
                tool_calls=[
                    {
                        "id": f"call-{call_number}",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": json.dumps({"query": f"q{call_number}"})},
                    }
                ],
            )
        return ModelResponse(role="assistant", content="All lookups done.")

    def invoke(self, *args: Any, messages=None, **kwargs: Any) -> ModelResponse:
        return self._respond(messages or [])

    async def ainvoke(self, *args: Any, messages=None, **kwargs: Any) -> ModelResponse:
        return self._respond(messages or [])

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


class SummarizerModel(Model):
    def __init__(self) -> None:
        super().__init__(id="summarizer-test", name="summarizer-test", provider="test")
        self.fold_calls = 0

    def __deepcopy__(self, memo: dict) -> "SummarizerModel":
        clone = type(self)()
        clone.fold_calls = self.fold_calls
        return clone

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        self.fold_calls += 1
        return ModelResponse(role="assistant", content=SUMMARY_TEXT)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return self.invoke()

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


def lookup(query: str) -> str:
    """Return a large fake result."""
    return "row " * 800  # ~800 tokens per tool result


def make_agent(model: ToolLoopModel, **compaction_kwargs) -> Agent:
    return Agent(
        id="inrun-agent",
        model=model,
        db=InMemoryDb(),
        tools=[lookup],
        compaction=Compaction(
            context_window=4_000,
            model=SummarizerModel(),
            background=False,
            **compaction_kwargs,
        ),
        telemetry=False,
    )


class TestInRunSeam:
    def test_mid_loop_pass_and_views(self):
        model = ToolLoopModel(tool_rounds=8)
        agent = make_agent(model)
        output = agent.run("look up many things", session_id="s-inrun-1")

        # The run finished despite ~6400 tokens of tool results on a 4k window.
        assert output.content == "All lookups done."

        # A pass ran mid-loop and committed on completion. Tool bloat alone is handled by the
        # cheap phase: an elision-only record (watermark, no fold).
        session = agent.get_session(session_id="s-inrun-1")
        records = get_owner_records(session.session_data, "inrun-agent")
        assert records, "no in-run compaction record"
        assert output.compaction_id == records[-1].id
        assert records[-1].elision_watermark_message_id is not None
        assert records[-1].summary is None

        # INV-2: the canonical transcript kept every tool round (nothing lost to views).
        tool_messages = [m for m in (output.messages or []) if m.role == "tool"]
        assert len(tool_messages) == 8

        # Later provider calls received an elided view, not the raw transcript.
        late_call = model.calls[-1]
        raw_size = sum(len(str(m.content or "")) for m in (output.messages or []))
        late_size = sum(len(str(m.content or "")) for m in late_call)
        assert late_size < raw_size
        assert any(isinstance(m.content, str) and "elided by compaction" in m.content for m in late_call)
        # Canonical tool results are untouched.
        assert all("elided by compaction" not in str(m.content) for m in tool_messages)

    def test_mid_loop_fold_when_elision_insufficient(self):
        # Large assistant prose cannot be elided; the pass must fold into a summary.
        model = ToolLoopModel(tool_rounds=8, assistant_padding=600)
        agent = make_agent(model)
        output = agent.run("look up many things", session_id="s-inrun-fold")
        # Assistant prose accumulates across iterations; the loop still ran to completion.
        assert str(output.content).endswith("All lookups done.")

        session = agent.get_session(session_id="s-inrun-fold")
        records = get_owner_records(session.session_data, "inrun-agent")
        folded = [r for r in records if r.summary]
        assert folded, "no fold record despite un-elidable growth"
        record = folded[-1]
        assert record.summary == SUMMARY_TEXT
        # The fold covered this run's own messages, so it is scoped to the run.
        assert record.created_by_run_id == output.run_id
        assert record.first_kept_run_id == output.run_id
        # A late provider call saw the injected summary instead of the folded prefix.
        assert any(isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX) for m in model.calls[-1])

    def test_overflow_pass_retries_once(self):
        model = ToolLoopModel(tool_rounds=3, overflow_on_call=3)
        agent = make_agent(model)
        output = agent.run("look up things", session_id="s-inrun-2")
        assert output.content == "All lookups done."
        assert model.overflow_raised
        session = agent.get_session(session_id="s-inrun-2")
        records = get_owner_records(session.session_data, "inrun-agent")
        assert any(r.reason == "overflow" for r in records)

    def test_error_run_commits_nothing(self):
        class ExplodingModel(ToolLoopModel):
            def _respond(self, messages):
                response = super()._respond(messages)
                if len(self.calls) >= 6:
                    raise RuntimeError("provider blew up")
                return response

        model = ExplodingModel(tool_rounds=10)
        agent = make_agent(model)
        agent.retries = 0
        output = agent.run("look up many things", session_id="s-inrun-3")
        from agno.run.base import RunStatus

        assert output.status == RunStatus.error
        session = agent.get_session(session_id="s-inrun-3")
        assert get_owner_records(session.session_data, "inrun-agent") == []


@pytest.mark.asyncio
async def test_async_in_run_seam():
    model = ToolLoopModel(tool_rounds=8)
    agent = make_agent(model)
    output = await agent.arun("look up many things", session_id="s-inrun-async")
    assert output.content == "All lookups done."
    session = agent.get_session(session_id="s-inrun-async")
    assert get_owner_records(session.session_data, "inrun-agent")


class TestOwnRegionScoping:
    def test_first_own_index_points_at_the_user_message(self):
        # The build appends the run's user message before the state is created; the own region
        # starts AT that message. A fold whose boundary lands past it folded unpersisted content
        # and must be scoped to the creating run (committed only if the run completes).
        from agno.agent._compaction import _first_own_index
        from agno.models.message import Message
        from agno.run.messages import RunMessages

        history = [
            Message(role="system", content="sys"),
            Message(role="user", content="old turn"),
            Message(role="assistant", content="old reply"),
        ]
        current = Message(role="user", content="current ask")
        run_messages = RunMessages(messages=history + [current], user_message=current)
        assert _first_own_index(run_messages) == 3

        # Without a recorded user message (rare builds), everything present counts as history.
        run_messages_bare = RunMessages(messages=history + [current])
        assert _first_own_index(run_messages_bare) == 4

    def test_team_twin_matches(self):
        from agno.models.message import Message
        from agno.run.messages import RunMessages
        from agno.team._compaction import _first_own_index

        current = Message(role="user", content="current ask")
        run_messages = RunMessages(messages=[Message(role="system", content="sys"), current], user_message=current)
        assert _first_own_index(run_messages) == 1
