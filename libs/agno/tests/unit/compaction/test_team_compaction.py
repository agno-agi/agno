"""Compaction on a Team: the same implementation as the Agent's, reached through the team run path."""

import asyncio
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.compaction import Compaction, CompactionRecord, CompactionStatus
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.exceptions import ContextWindowExceededError
from agno.metrics import MessageMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.team import TeamRunOutput
from agno.team.team import Team


class _RecordingModel(Model):
    """An offline model that records every request, and can reject the next one as too long."""

    def __init__(self):
        super().__init__(id="test-model", name="test-model", provider="test")
        self.requests: List[list] = []
        self.tools_seen: List[list] = []
        self.reject_next = False

    def _reply(self) -> ModelResponse:
        return ModelResponse(content="ok", role="assistant", response_usage=MessageMetrics())

    def _record(self, kwargs: Any) -> None:
        self.requests.append(list(kwargs.get("messages") or []))
        self.tools_seen.append(list(kwargs.get("tools") or []))
        if self.reject_next:
            self.reject_next = False
            raise ContextWindowExceededError("prompt is too long")

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

    def invoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._reply()

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        self._record(kwargs)
        return self._reply()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        self._record(kwargs)
        yield self._reply()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        self._record(kwargs)
        yield self._reply()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return self._reply()

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return self._reply()


class _StubSummarizer:
    id = "stub"

    def response(self, messages, **kwargs):
        return ModelResponse(content="SUMMARY")

    async def aresponse(self, messages, **kwargs):
        return ModelResponse(content="SUMMARY")


def _db() -> SqliteDb:
    return SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "team.db"))


def _team(model: _RecordingModel, db: Any = None, **kwargs) -> Team:
    return Team(
        id="team-1",
        members=[Agent(name="helper", model=_RecordingModel())],
        model=model,
        db=db if db is not None else InMemoryDb(),
        session_id="s",
        add_history_to_context=True,
        telemetry=False,
        **kwargs,
    )


def _asked(request: list) -> List[int]:
    return [int(m.content.split()[-1]) for m in request if m.role == "user" and str(m.content).startswith("question")]


def _is_summary(message: Any) -> bool:
    return isinstance(message.content, str) and message.content.startswith("Summary of earlier conversation")


# --- what a run sends -------------------------------------------------------


@pytest.mark.parametrize("compaction", [True, Compaction()])
def test_compaction_does_not_widen_what_a_team_run_replays(compaction):
    """The planner reads past num_history_runs; the model must not, until something folds."""

    def sent(**kwargs) -> List[int]:
        model = _RecordingModel()
        team = _team(model, **kwargs)
        for i in range(8):
            team.run(f"question number {i}")
        return [len(r) for r in model.requests]

    assert sent(compaction=compaction) == sent()


def test_async_team_runs_do_not_widen_what_is_replayed():
    async def sent(**kwargs) -> List[int]:
        model = _RecordingModel()
        team = _team(model, **kwargs)
        for i in range(8):
            await team.arun(f"question number {i}")
        return [len(r) for r in model.requests]

    assert asyncio.run(sent(compaction=True)) == asyncio.run(sent())


# --- folding -----------------------------------------------------------------


def test_a_team_fold_replays_its_summary_and_everything_from_the_anchor():
    """Once a fold exists the anchor is replayed, even when it is older than the window."""
    model = _RecordingModel()
    team = _team(
        model,
        db=_db(),
        num_history_runs=2,
        compaction=Compaction(
            compact_at_tokens=None, uncompacted_runs=3, min_fold_ratio=0, searchable=False, model=_StubSummarizer()
        ),
    )
    for i in range(6):
        team.run(f"question number {i}")
    assert team.compact(session_id="s").compacted

    team.run("question number 6")
    sent = [m for m in model.requests[-1] if m.role != "system"]

    assert _is_summary(sent[0])
    assert _asked(model.requests[-1]) == [3, 4, 5, 6]


def test_a_team_folds_automatically_and_reports_it_on_the_run():
    model = _RecordingModel()
    team = _team(
        model,
        compaction=Compaction(compact_at_tokens=5, uncompacted_runs=1, min_fold_ratio=0, model=_StubSummarizer()),
    )
    runs = [team.run(f"question number {i}") for i in range(4)]

    folded = [r for r in runs if r.compaction is not None]
    assert folded
    assert isinstance(folded[-1], TeamRunOutput)
    assert folded[-1].compaction.messages_compacted > 0


def test_a_streamed_team_run_emits_the_compaction_events():
    model = _RecordingModel()
    team = _team(
        model,
        compaction=Compaction(compact_at_tokens=5, uncompacted_runs=1, min_fold_ratio=0, model=_StubSummarizer()),
    )
    events: List[str] = []
    for i in range(4):
        for event in team.run(f"question number {i}", stream=True, stream_events=True):
            events.append(getattr(event, "event", ""))

    assert "TeamCompactionStarted" in events
    assert "TeamCompactionCompleted" in events
    assert events.index("TeamRunStarted") < events.index("TeamCompactionStarted")


def test_a_streamed_async_team_run_emits_the_compaction_events():
    model = _RecordingModel()
    team = _team(
        model,
        compaction=Compaction(compact_at_tokens=5, uncompacted_runs=1, min_fold_ratio=0, model=_StubSummarizer()),
    )

    async def collect() -> List[str]:
        seen: List[str] = []
        for i in range(4):
            async for event in team.arun(f"question number {i}", stream=True, stream_events=True):
                seen.append(getattr(event, "event", ""))
        return seen

    events = asyncio.run(collect())
    assert "TeamCompactionCompleted" in events


def test_a_team_recovers_from_a_context_window_rejection():
    """The provider's rejection folds the request and retries once, instead of failing the run."""
    model = _RecordingModel()
    team = _team(
        model,
        compaction=Compaction(
            compact_at_tokens=None, on_context_overflow=True, uncompacted_runs=1, model=_StubSummarizer()
        ),
    )
    for i in range(5):
        team.run(f"question number {i}")

    calls_before = len(model.requests)
    model.reject_next = True
    run = team.run("question number 5")

    assert run.status.value == "COMPLETED"
    rejected, retried = model.requests[calls_before], model.requests[calls_before + 1]
    assert len(retried) < len(rejected)
    assert run.compaction is not None


def test_the_archive_search_tool_is_offered_after_a_team_fold():
    model = _RecordingModel()
    team = _team(
        model,
        db=_db(),
        compaction=Compaction(compact_at_tokens=None, uncompacted_runs=1, min_fold_ratio=0, model=_StubSummarizer()),
    )
    for i in range(4):
        team.run(f"question number {i}")

    def tool_names(tools: list) -> List[str]:
        return [
            getattr(t, "name", None) or (t.get("function", {}).get("name") if isinstance(t, dict) else None)
            for t in tools
        ]

    assert "search_compacted_history" not in tool_names(model.tools_seen[-1])
    assert team.compact(session_id="s").compacted

    team.run("question number 4")
    assert "search_compacted_history" in tool_names(model.tools_seen[-1])


# --- surface -----------------------------------------------------------------


def test_compacting_a_team_without_compaction_says_so():
    team = _team(_RecordingModel())

    result = team.compact(session_id="s")

    assert result.status == CompactionStatus.NOT_ENABLED
    assert "team" in result.message


def test_acompact_is_the_async_variant():
    team = _team(_RecordingModel(), compaction=Compaction())

    result = asyncio.run(team.acompact(session_id="does-not-exist"))

    assert result.status == CompactionStatus.NO_HISTORY


def test_team_run_output_carries_compaction_through_serialization():
    record = CompactionRecord(messages_compacted=4, summary="s", first_kept_message_id="m1", tokens_before=100)
    run = TeamRunOutput(run_id="r", team_id="t", session_id="s", compaction=record)

    restored = TeamRunOutput.from_dict(run.to_dict())

    assert isinstance(restored.compaction, CompactionRecord)
    assert restored.compaction.messages_compacted == 4
    assert restored.compaction.first_kept_message_id == "m1"
