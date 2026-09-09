"""Unit tests for the AgentOS teams router stream helpers."""

from typing import Any

import pytest

from agno.os.routers.teams.router import team_continue_response_streamer, team_response_streamer
from agno.run.agent import RunOutput
from agno.run.team import RunContentEvent, RunErrorEvent, TeamRunOutput


class FakeTeam:
    def __init__(self, chunks: list[Any]):
        self.chunks = chunks
        self.arun_kwargs: dict[str, Any] | None = None
        self.acontinue_run_kwargs: dict[str, Any] | None = None

    def arun(self, **kwargs: Any):
        self.arun_kwargs = kwargs
        return self._stream()

    def acontinue_run(self, **kwargs: Any):
        self.acontinue_run_kwargs = kwargs
        return self._stream()

    async def _stream(self):
        for chunk in self.chunks:
            yield chunk


@pytest.mark.asyncio
async def test_team_response_streamer_skips_run_output_accumulators_before_formatting():
    team: Any = FakeTeam(
        [
            TeamRunOutput(run_id="team-aggregate"),
            RunOutput(run_id="agent-aggregate"),
            RunContentEvent(run_id="run-1", content="hello"),
        ]
    )

    sse_chunks = [chunk async for chunk in team_response_streamer(team, "hello")]

    assert len(sse_chunks) == 1
    assert sse_chunks[0].startswith("event: TeamRunContent\n")
    assert '"content":"hello"' in sse_chunks[0]
    assert "team-aggregate" not in sse_chunks[0]
    assert "agent-aggregate" not in sse_chunks[0]
    assert team.arun_kwargs is not None
    assert team.arun_kwargs["stream"] is True
    assert team.arun_kwargs["stream_events"] is True


@pytest.mark.asyncio
async def test_team_continue_response_streamer_skips_accumulators_and_formats_error_events():
    team: Any = FakeTeam(
        [
            TeamRunOutput(run_id="team-aggregate"),
            RunOutput(run_id="agent-aggregate"),
            RunErrorEvent(run_id="run-1", content="boom"),
        ]
    )

    sse_chunks = [
        chunk
        async for chunk in team_continue_response_streamer(
            team, run_id="run-1", requirements=[], session_id="session-1"
        )
    ]

    assert len(sse_chunks) == 1
    assert sse_chunks[0].startswith("event: TeamRunError\n")
    assert '"content":"boom"' in sse_chunks[0]
    assert "team-aggregate" not in sse_chunks[0]
    assert "agent-aggregate" not in sse_chunks[0]
    assert team.acontinue_run_kwargs is not None
    assert team.acontinue_run_kwargs["stream"] is True
    assert team.acontinue_run_kwargs["stream_events"] is True
