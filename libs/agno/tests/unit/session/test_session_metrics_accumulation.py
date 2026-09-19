"""Session usage includes each run contribution once, including pauses and checkpoints."""

from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any, AsyncIterator, Iterator, List

import pytest

from agno.agent import Agent
from agno.agent._run import acheckpoint_run, checkpoint_run, persist_run_in_session
from agno.agent._storage import read_or_create_session
from agno.db.base import SessionType
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.metrics import MessageMetrics, ModelMetrics, RunMetrics
from agno.models.base import Model
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team import Team
from agno.team._run import _cleanup_and_store, acheckpoint_team_run, checkpoint_team_run
from agno.team._storage import _read_or_create_session
from agno.tools.function import Function


def _metrics(scale):
    counters = dict(
        input_tokens=7 * scale,
        output_tokens=3 * scale,
        total_tokens=10 * scale,
        audio_input_tokens=5 * scale,
        audio_output_tokens=6 * scale,
        audio_total_tokens=11 * scale,
        cache_read_tokens=2 * scale,
        cache_write_tokens=4 * scale,
        reasoning_tokens=scale,
        cost=0.25 * scale,
    )
    return RunMetrics(
        **counters,
        additional_metrics={"requests": scale, "label": "latest"},
        details={
            "model": [
                ModelMetrics(
                    id="test-model",
                    provider="test-provider",
                    provider_metrics={"requests": scale, "label": "latest"},
                    **counters,
                )
            ]
        },
    )


@pytest.mark.parametrize("team", [False, True])
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("session_data", [None, {}])
@pytest.mark.asyncio
async def test_checkpoints_count_only_new_usage(team, asynchronous, session_data):
    db = InMemoryDb()
    session_data = session_data.copy() if session_data is not None else None
    if team:
        actor = Team(id="actor", members=[], db=db, checkpoint="tool-batch", telemetry=False)
        session = TeamSession(session_id="session", team_id="actor", session_data=session_data)
        run = TeamRunOutput(run_id="run", team_id="actor", metrics=_metrics(1))
        checkpoint, acheckpoint = checkpoint_team_run, acheckpoint_team_run
    else:
        actor = Agent(id="actor", db=db, checkpoint="tool-batch", telemetry=False)
        session = AgentSession(session_id="session", agent_id="actor", session_data=session_data)
        run = RunOutput(run_id="run", agent_id="actor", metrics=_metrics(1))
        checkpoint, acheckpoint = checkpoint_run, acheckpoint_run

    # Summary generation may upsert before accounting. Checkpoints share metrics with the live run.
    session.upsert_run(run)
    for scale in (1, 1, 2, 3):
        run.metrics.__dict__.update(_metrics(scale).__dict__)
        if asynchronous:
            await acheckpoint(actor, run, session)
        else:
            checkpoint(actor, run, session)
        assert session.session_data is not None
        assert session.session_data["session_metrics"] == _metrics(scale).to_dict()


@pytest.mark.parametrize("team", [False, True])
@pytest.mark.parametrize("prior_scale, resumed_tokens, final_tokens", [(None, 20, 50), (10, 110, 140)])
def test_resumed_run_preserves_usage_from_removed_history(team, prior_scale, resumed_tokens, final_tokens):
    db = InMemoryDb()
    if team:
        actor = Team(id="actor", members=[], db=db, telemetry=False)
        session = TeamSession(session_id="session", team_id="actor")
        run = TeamRunOutput(run_id="run", team_id="actor", metrics=_metrics(1))
        load, persist = _read_or_create_session, _cleanup_and_store
    else:
        actor = Agent(id="actor", db=db, telemetry=False)
        session = AgentSession(session_id="session", agent_id="actor")
        run = RunOutput(run_id="run", agent_id="actor", metrics=_metrics(1))
        load, persist = read_or_create_session, persist_run_in_session
    if prior_scale is not None:
        session.session_data = {"session_metrics": _metrics(prior_scale).to_dict()}
    db.upsert_session(session)
    db.upsert_run(run, session_id="session")

    session = load(actor, "session")
    run = session.runs[0]
    run.metrics = _metrics(2)
    persist(actor, run, session)
    assert session.session_data["session_metrics"]["total_tokens"] == resumed_tokens

    db.delete_run("run")
    session = load(actor, "session")
    run.run_id = "new-run"
    run.metrics = _metrics(3)
    persist(actor, run, session)
    assert session.session_data["session_metrics"]["total_tokens"] == final_tokens
    assert session.session_data["session_metrics"]["details"]["model"][0]["total_tokens"] == final_tokens


@pytest.mark.parametrize("reload", [False, True])
def test_team_resaves_count_flat_and_nested_members_once(reload):
    team = Team(id="leader", members=[], db=InMemoryDb(), store_member_responses=True, telemetry=False)
    session = _read_or_create_session(team, "session")
    member = RunOutput(run_id="member", agent_id="member", parent_run_id="run", metrics=_metrics(2))
    child = RunOutput(run_id="child", agent_id="child", parent_run_id="nested", metrics=_metrics(4))
    nested = TeamRunOutput(
        run_id="nested", team_id="nested", parent_run_id="run", metrics=_metrics(3), member_responses=[child]
    )
    run = TeamRunOutput(run_id="run", team_id="leader", metrics=_metrics(1), member_responses=[member, nested])
    session.upsert_run(member)
    _cleanup_and_store(team, run, session)
    assert session.session_data["session_metrics"]["total_tokens"] == 100
    if reload:
        session = _read_or_create_session(team, "session")
    run.metrics = _metrics(2)
    member.metrics = _metrics(3)
    _cleanup_and_store(team, run, session)
    assert session.session_data["session_metrics"]["total_tokens"] == 120
    assert session.session_data["session_metrics"]["cost"] == 3


@dataclass
class ScriptedModel(Model):
    responses: List[ModelResponse] = field(default_factory=list)

    def invoke(self, *args, **kwargs) -> ModelResponse:
        return self.responses.pop(0)

    async def ainvoke(self, *args, **kwargs) -> ModelResponse:
        return self.invoke()

    def invoke_stream(self, *args, **kwargs) -> Iterator[ModelResponse]:
        yield self.invoke()

    async def ainvoke_stream(self, *args, **kwargs) -> AsyncIterator[ModelResponse]:
        yield self.invoke()

    def _parse_provider_response(self, response: Any, **kwargs) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _tool_response(name, tokens, arguments="{}"):
    return ModelResponse(
        role="assistant",
        tool_calls=[{"id": f"call-{tokens}", "type": "function", "function": {"name": name, "arguments": arguments}}],
        response_usage=MessageMetrics(total_tokens=tokens),
    )


async def _run_or_continue(actor, mode, paused=None):
    kwargs = {"session_id": "session"}
    if "stream" in mode:
        kwargs.update(stream=True, stream_events=True, yield_run_output=True)
    if paused is None:
        response = actor.arun("Do work", **kwargs) if mode.startswith("async") else actor.run("Do work", **kwargs)
    else:
        for requirement in paused.requirements or []:
            if requirement.needs_confirmation:
                requirement.confirm()
        kwargs.update(run_id=paused.run_id, requirements=paused.requirements)
        response = actor.acontinue_run(**kwargs) if mode.startswith("async") else actor.continue_run(**kwargs)
    if mode == "async_stream":
        return [event async for event in response if isinstance(event, (RunOutput, TeamRunOutput))][-1]
    if mode == "sync_stream":
        return [event for event in response if isinstance(event, (RunOutput, TeamRunOutput))][-1]
    return await response if mode == "async" else response


async def _db_result(result):
    return await result if isawaitable(result) else result


@pytest.mark.parametrize("mode", ["sync", "sync_stream", "async", "async_stream"])
@pytest.mark.parametrize("team", [False, True])
@pytest.mark.parametrize("reload", [False, True])
@pytest.mark.asyncio
async def test_approval_usage_after_each_pause_and_resume(tmp_path, mode, team, reload):
    database = AsyncSqliteDb if mode.startswith("async") else SqliteDb
    db_file = str(tmp_path / "sessions.db")
    db = database(db_file=db_file)
    worker_model = ScriptedModel(
        id="worker-model",
        provider="test-provider",
        responses=[_tool_response("approved_tool", tokens) for tokens in (10, 20, 30)]
        + [ModelResponse(role="assistant", content="Done", response_usage=MessageMetrics(total_tokens=40))],
    )
    leader_model = ScriptedModel(
        id="leader-model",
        provider="test-provider",
        responses=[
            _tool_response("delegate_task_to_member", 5, '{"member_id":"worker","task":"Do work"}'),
            ModelResponse(role="assistant", content="Done", response_usage=MessageMetrics(total_tokens=15)),
        ],
    )

    def approved_tool():
        return "Done"

    def create_actor():
        worker = Agent(
            id="worker",
            name="worker",
            model=worker_model,
            db=db,
            cache_session=True,
            telemetry=False,
            tools=[Function(name="approved_tool", entrypoint=approved_tool, requires_confirmation=True)],
        )
        return (
            Team(id="leader", members=[worker], model=leader_model, db=db, cache_session=True, telemetry=False)
            if team
            else worker
        )

    actor = create_actor()
    session_type = SessionType.TEAM if team else SessionType.AGENT
    await _db_result(
        db.upsert_session(
            TeamSession(session_id="session", team_id="leader", session_data={})
            if team
            else AgentSession(session_id="session", agent_id="worker", session_data={})
        )
    )
    response = None
    try:
        for expected, status in [
            (10, RunStatus.paused),
            (30, RunStatus.paused),
            (60, RunStatus.paused),
            (100, RunStatus.completed),
        ]:
            if reload:
                await _db_result(db.close())
                db = database(db_file=db_file)
                actor = create_actor()
            response = await _run_or_continue(actor, mode, response)
            assert response.status == status
            saved = await _db_result(db.get_session("session", session_type=session_type))
            assert saved.session_data is not None
            metrics = saved.session_data["session_metrics"]
            leader_tokens = 20 if status == RunStatus.completed else 5
            assert metrics["total_tokens"] == expected + (leader_tokens if team else 0)
            assert sum(row["total_tokens"] for row in metrics["details"]["model"]) == metrics["total_tokens"]
    finally:
        await _db_result(db.close())
