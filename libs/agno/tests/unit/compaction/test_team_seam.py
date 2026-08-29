"""Team seam: leader compaction under the team_id chain, owner isolation, in-run elision."""

import json
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.compaction import Compaction
from agno.compaction.compaction import get_owner_records
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.db.in_memory import InMemoryDb
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.team import Team

SUMMARY_TEXT = "## Goal\nSummarized team conversation."


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


class ToolLoopModel(Model):
    """Requests `tool_rounds` lookup calls, then finishes."""

    def __init__(self, tool_rounds: int, model_id: str = "team-tool-loop") -> None:
        super().__init__(id=model_id, name=model_id, provider="test")
        self.tool_rounds = tool_rounds
        self.calls: List[List] = []

    def __deepcopy__(self, memo: dict) -> "ToolLoopModel":
        clone = type(self)(self.tool_rounds, model_id=self.id)
        clone.calls = self.calls
        return clone

    def _respond(self, messages) -> ModelResponse:
        self.calls.append(list(messages))
        call_number = len(self.calls)
        if call_number <= self.tool_rounds:
            return ModelResponse(
                role="assistant",
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


def lookup(query: str) -> str:
    """Return a large fake result."""
    return "row " * 800


def make_member() -> Agent:
    # A trivial member that is never delegated to: the leader answers directly.
    return Agent(id="quiet-member", name="Quiet Member", model=EchoModel("member reply"), telemetry=False)


def make_team(leader_model=None, db=None, **compaction_kwargs) -> Team:
    reply = "word " * 400
    return Team(
        members=[make_member()],
        id="compaction-team",
        model=leader_model if leader_model is not None else EchoModel(reply),
        db=db if db is not None else InMemoryDb(),
        add_history_to_context=True,
        compaction=Compaction(
            context_window=4_000,
            model=EchoModel(SUMMARY_TEXT, model_id="team-summarizer"),
            background=False,
            **compaction_kwargs,
        ),
        telemetry=False,
    )


def run_until_compacted(team: Team, session_id: str, max_runs: int = 12) -> int:
    for count in range(1, max_runs + 1):
        team.run("continue " + "word " * 150, session_id=session_id)
        session = team.get_session(session_id=session_id)
        if get_owner_records(session.session_data, "compaction-team"):
            return count
    return max_runs


class TestTeamCrossRunSeam:
    def test_threshold_pass_under_team_id(self):
        team = make_team()
        session_id = "team-sess-1"
        runs_taken = run_until_compacted(team, session_id)
        session = team.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-team")
        assert records, "no compaction record under the team id"
        record = records[-1]
        assert record.reason == "threshold"
        assert record.created_by_run_id is None
        assert record.summary == SUMMARY_TEXT
        assert record.first_kept_run_id is not None

        # The transcript is untouched: every run still holds its messages.
        assert len(session.runs) >= runs_taken
        for run in session.runs:
            assert run.messages, "a stored team run lost its messages"

        # The next run's view carries the summary and is bounded.
        next_output = team.run("next " + "word " * 100, session_id=session_id)
        summary_messages = [
            m
            for m in (next_output.messages or [])
            if isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX)
        ]
        assert len(summary_messages) == 1
        total_stored = sum(len(run.messages or []) for run in session.runs)
        assert len(next_output.messages or []) < total_stored

        # compaction_id points at the committed record.
        session = team.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-team")
        assert next_output.compaction_id == records[-1].id

    def test_member_chain_never_crosses_team_chain(self):
        team = make_team()
        session_id = "team-sess-2"
        run_until_compacted(team, session_id)

        # A compacting agent on the same session folds under its own agent-id chain.
        member = Agent(
            id="solo-agent",
            model=EchoModel("word " * 400),
            db=team.db,
            add_history_to_context=True,
            compaction=Compaction(
                context_window=4_000, model=EchoModel(SUMMARY_TEXT, model_id="solo-summarizer"), background=False
            ),
            telemetry=False,
        )
        for _ in range(12):
            member.run("agent turn " + "word " * 150, session_id=session_id)
            session = member.get_session(session_id=session_id)
            if get_owner_records(session.session_data, "solo-agent"):
                break

        session = team.get_session(session_id=session_id)
        team_chain = get_owner_records(session.session_data, "compaction-team")
        agent_chain = get_owner_records(session.session_data, "solo-agent")
        assert team_chain and agent_chain
        assert {r.id for r in team_chain}.isdisjoint({r.id for r in agent_chain})

    def test_in_run_elision_pass(self):
        model = ToolLoopModel(tool_rounds=8)
        team = make_team(leader_model=model)
        team.tools = [lookup]
        output = team.run("look up many things", session_id="team-sess-3")
        assert str(output.content).endswith("All lookups done.")
        session = team.get_session(session_id="team-sess-3")
        records = get_owner_records(session.session_data, "compaction-team")
        assert records, "no in-run team compaction record"
        assert records[-1].elision_watermark_message_id is not None
        # Canonical tool results survived intact.
        tool_messages = [m for m in (output.messages or []) if m.role == "tool"]
        assert len(tool_messages) == 8
        assert all("elided by compaction" not in str(m.content) for m in tool_messages)
        # A late provider call saw elided placeholders.
        assert any(isinstance(m.content, str) and "elided by compaction" in m.content for m in model.calls[-1])


@pytest.mark.asyncio
async def test_async_team_cross_run_seam():
    team = make_team()
    session_id = "team-sess-async"
    records = []
    for _ in range(12):
        await team.arun("continue " + "word " * 150, session_id=session_id)
        session = team.get_session(session_id=session_id)
        records = get_owner_records(session.session_data, "compaction-team")
        if records:
            break
    assert records
    assert records[-1].summary == SUMMARY_TEXT
