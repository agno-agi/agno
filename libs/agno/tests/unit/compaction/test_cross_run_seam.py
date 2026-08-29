"""Cross-run seam: build-time compaction over a real agent run loop (stub models, in-memory db)."""

from typing import Any, AsyncIterator, Iterator

import pytest

from agno.agent import Agent
from agno.compaction import Compaction
from agno.compaction.compaction import get_owner_records
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse

SUMMARY_TEXT = "## Goal\nSummarized conversation."


class EchoModel(Model):
    """Real Model subclass so runs exercise the actual response loop."""

    def __init__(self, reply: str, model_id: str = "echo-test") -> None:
        super().__init__(id=model_id, name=model_id, provider="test")
        self.reply = reply

    def __deepcopy__(self, memo: dict) -> "EchoModel":
        return type(self)(reply=self.reply, model_id=self.id)

    def invoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse(role="assistant", content=self.reply)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> ModelResponse:
        return ModelResponse(role="assistant", content=self.reply)

    def invoke_stream(self, *args: Any, **kwargs: Any) -> Iterator[ModelResponse]:
        raise AssertionError("streaming not used in this test")
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[ModelResponse]:
        raise AssertionError("streaming not used in this test")
        yield  # pragma: no cover

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def make_agent(**compaction_kwargs) -> Agent:
    reply = "word " * 400  # ~400 tokens per assistant turn
    return Agent(
        id="compaction-agent",
        model=EchoModel(reply),
        db=InMemoryDb(),
        add_history_to_context=True,
        compaction=Compaction(
            context_window=4_000,
            model=EchoModel(SUMMARY_TEXT, model_id="summarizer-test"),
            background=False,
            **compaction_kwargs,
        ),
        telemetry=False,
    )


def run_until_compacted(agent: Agent, session_id: str, max_runs: int = 12) -> int:
    """Run until a record lands in the session row; returns the number of runs taken."""
    for count in range(1, max_runs + 1):
        agent.run("continue " + "word " * 150, session_id=session_id)
        session = agent.get_session(session_id=session_id)
        if get_owner_records(session.session_data, "compaction-agent"):
            return count
    return max_runs


class TestCrossRunSeam:
    def test_threshold_pass_creates_record_and_shrinks_view(self):
        agent = make_agent()
        session_id = "sess-compact-1"
        runs_taken = run_until_compacted(agent, session_id)
        session = agent.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-agent")
        assert records, "no compaction record after sustained growth"
        record = records[-1]
        assert record.reason == "threshold"
        assert record.created_by_run_id is None  # build-time pass covers completed runs only
        assert record.summary == SUMMARY_TEXT
        assert record.first_kept_run_id is not None
        assert record.first_kept_message_id is not None

        # INV-1: the transcript is untouched — every run still holds its own messages.
        assert len(session.runs) >= runs_taken
        for run in session.runs:
            assert run.messages, "a stored run lost its messages"

        # The next run's context is summary + tail, not the full flattened history.
        next_output = agent.run("next " + "word " * 100, session_id=session_id)
        summary_messages = [
            m
            for m in (next_output.messages or [])
            if isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX)
        ]
        assert len(summary_messages) == 1
        assert SUMMARY_TEXT in summary_messages[0].content
        # Messages covered by the summary do not also appear (INV-3): the view's history portion
        # is bounded, far below the total transcript.
        total_stored = sum(len(run.messages or []) for run in session.runs)
        assert len(next_output.messages or []) < total_stored

    def test_disabled_agent_on_same_session_sees_raw_history(self):
        agent = make_agent()
        session_id = "sess-compact-2"
        run_until_compacted(agent, session_id)

        plain = Agent(
            id="plain-agent",
            model=EchoModel("plain reply"),
            db=agent.db,
            add_history_to_context=True,
            num_history_runs=100,
            telemetry=False,
        )
        output = plain.run("hello", session_id=session_id)
        assert all(
            not (isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX))
            for m in (output.messages or [])
        )

    def test_chain_grows_and_folds_incrementally(self):
        agent = make_agent()
        session_id = "sess-compact-3"
        run_until_compacted(agent, session_id)
        for _ in range(6):
            agent.run("more " + "word " * 150, session_id=session_id)
        session = agent.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-agent")
        assert len(records) >= 2
        # Later records chain onto earlier ones and boundaries never move backward.
        positions = []
        run_ids = [run.run_id for run in session.runs]
        for record in records:
            if record.first_kept_run_id in run_ids:
                positions.append(run_ids.index(record.first_kept_run_id))
        assert positions == sorted(positions)

    def test_compaction_id_stamped_on_run_output(self):
        agent = make_agent()
        session_id = "sess-compact-4"
        run_until_compacted(agent, session_id)
        output = agent.run("after " + "word " * 100, session_id=session_id)
        session = agent.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-agent")
        assert output.compaction_id == records[-1].id


@pytest.mark.asyncio
async def test_async_cross_run_seam():
    agent = make_agent()
    session_id = "sess-compact-async"
    records = []
    for _ in range(12):
        await agent.arun("continue " + "word " * 150, session_id=session_id)
        session = agent.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-agent")
        if records:
            break
    assert records
    assert records[-1].summary == SUMMARY_TEXT
