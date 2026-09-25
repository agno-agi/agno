"""Continuation history and observable status, without provider requests."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from agno.agent import Agent
from agno.agent._messages import _build_continue_run_messages as agent_messages
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.exceptions import RunNotContinuableError
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse, ToolExecution
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput
from agno.run.continuation import _apersist_continue_start, _persist_continue_start
from agno.run.requirement import RunRequirement
from agno.run.status_persist import RunPersistOutcome
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.team._run import _build_continue_run_messages as team_messages
from agno.tools import tool
from agno.tools.function import UserInputField


class InspectModel(Model):
    def __init__(self, inspect_messages):
        super().__init__(id="offline", provider="test")
        self.inspect_messages = inspect_messages
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        self.inspect_messages(messages)
        return ModelResponse(role="assistant", content="done")

    async def ainvoke(self, messages, **kwargs):
        return self.invoke(messages, **kwargs)

    def invoke_stream(self, messages, **kwargs):
        yield self.invoke(messages, **kwargs)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self.invoke(messages, **kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


@pytest.fixture(params=["agent", "team"])
def kind(request):
    return request.param


def make_component(kind, **kwargs):
    if kind == "agent":
        return Agent(id="component", telemetry=False, **kwargs)
    return Team(id="component", members=[], telemetry=False, **kwargs)


def make_run(kind, run_id, **kwargs):
    cls = RunOutput if kind == "agent" else TeamRunOutput
    return cls(run_id=run_id, session_id="session", user_id="owner", **{kind + "_id": "component"}, **kwargs)


def make_session(kind, runs):
    cls = AgentSession if kind == "agent" else TeamSession
    return cls(session_id="session", user_id="owner", runs=runs, **{kind + "_id": "component"})


@pytest.mark.parametrize("status", list(RunStatus))
@pytest.mark.parametrize("fork_depth", [0, 2])
def test_history_excludes_current_transcript_before_limits(kind, status, fork_depth):
    component = make_component(kind, add_history_to_context=True, num_history_runs=1)
    prior = make_run(kind, "prior", status=RunStatus.completed, messages=[Message(role="user", content="prior")])
    source = make_run(kind, "source", status=status, messages=[Message(role="user", content="current")])
    runs = [prior, source]
    current = source
    for index in range(fork_depth):
        current = make_run(
            kind,
            f"fork-{index}",
            status=status,
            messages=deepcopy(source.messages),
            forked_from_run_id=current.run_id,
        )
        runs.append(current)
    session = make_session(kind, runs)
    before = deepcopy(session.to_dict())
    builder = agent_messages if kind == "agent" else team_messages
    result = builder(component, input=deepcopy(current.messages), session=session, run_response=current)
    assert [m.content for m in result.messages] == ["prior", "current"]
    assert session.to_dict() == before


def prepare_continuation(kind, tmp_path, pause_type):
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    tool_calls = []

    @tool(
        external_execution=pause_type == "external",
        requires_confirmation=pause_type == "confirmation",
        requires_user_input=pause_type == "user_input",
        user_input_fields=["city"] if pause_type == "user_input" else None,
    )
    def location(city: str) -> str:
        """Return a city after approval or user input."""
        assert db.get_run("current").status == RunStatus.running
        tool_calls.append(city)
        return city

    execution = ToolExecution(
        tool_call_id="call-location",
        tool_name="location",
        tool_args={"city": "Paris"},
        external_execution_required=pause_type == "external",
        requires_confirmation=pause_type == "confirmation",
        requires_user_input=pause_type == "user_input",
        user_input_schema=[UserInputField(name="city", field_type=str)] if pause_type == "user_input" else None,
    )
    requirement = RunRequirement(tool_execution=execution)
    current = make_run(
        kind,
        "current",
        status=RunStatus.paused,
        messages=[
            Message(role="user", content="current request"),
            Message(
                role="assistant",
                tool_calls=[
                    {
                        "id": execution.tool_call_id,
                        "type": "function",
                        "function": {"name": "location", "arguments": '{"city":"Paris"}'},
                    }
                ],
            ),
        ],
        tools=[execution],
        requirements=[requirement],
    )
    prior = make_run(kind, "prior", status=RunStatus.completed, messages=[Message(role="user", content="prior")])
    session = make_session(kind, [prior, current])
    db.upsert_session(session)
    for index, run in enumerate(session.runs):
        db.upsert_run(run, session_id=session.session_id, user_id="owner", run_index=index)

    def inspect_messages(messages):
        assert db.get_run("current").status == RunStatus.running
        assert sum(m.content == "prior" for m in messages) == 1
        assert sum(m.content == "current request" for m in messages) == 1
        assert sum(bool(m.tool_calls) for m in messages) == 1
        assert sum(m.tool_call_id == "call-location" for m in messages) == 1

    model = InspectModel(inspect_messages)
    component = make_component(
        kind, model=model, tools=[location], db=db, add_history_to_context=True, num_history_runs=1
    )
    if pause_type == "external":
        requirement.set_external_execution_result("Paris")
    elif pause_type == "confirmation":
        requirement.confirm()
    else:
        requirement.provide_user_input({"city": "Paris"})
    return component, current, model, tool_calls


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("by_id", [False, True])
@pytest.mark.parametrize("pause_type", ["external", "confirmation", "user_input"])
def test_sync_continue_persists_running_and_pairs_tools(kind, tmp_path, stream, by_id, pause_type):
    component, current, model, calls = prepare_continuation(kind, tmp_path, pause_type)
    args = {"run_id": current.run_id, "requirements": current.requirements} if by_id else {"run_response": current}
    result = component.continue_run(session_id="session", stream=stream, **args)
    if stream:
        list(result)
    assert model.calls == 1
    assert component.db.get_run("current").status == RunStatus.completed
    assert calls == ([] if pause_type == "external" else ["Paris"])


@pytest.mark.asyncio
@pytest.mark.parametrize("stream,background", [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize("by_id", [False, True])
@pytest.mark.parametrize("pause_type", ["external", "confirmation", "user_input"])
@pytest.mark.parametrize("async_db", [False, True])
async def test_async_continue_persists_running_and_pairs_tools(
    kind, tmp_path, stream, background, by_id, pause_type, async_db
):
    component, current, model, calls = prepare_continuation(kind, tmp_path, pause_type)
    reader = component.db
    if async_db:
        component.db = AsyncSqliteDb(db_file=str(tmp_path / "runs.db"))
    args = {"run_id": current.run_id, "requirements": current.requirements} if by_id else {"run_response": current}
    result = component.acontinue_run(session_id="session", stream=stream, background=background, **args)
    if stream:
        async for _ in result:
            pass
    else:
        await result
    assert model.calls == 1
    assert reader.get_run("current").status == RunStatus.completed
    assert calls == ([] if pause_type == "external" else ["Paris"])


def test_unconsumed_agent_stream_does_not_persist_running(tmp_path):
    component, current, model, _ = prepare_continuation("agent", tmp_path, "external")
    stream = component.continue_run(run_response=current, session_id="session", stream=True)
    assert component.db.get_run("current").status == RunStatus.paused
    assert model.calls == 0
    stream.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_completed_continue_creates_running_fork_and_keeps_source(kind, tmp_path, asynchronous, stream):
    component, current, model, _ = prepare_continuation(kind, tmp_path, "external")
    current.status = RunStatus.completed
    current.tools = None
    current.requirements = None
    current.messages = [
        Message(role="user", content="source request"),
        Message(role="assistant", content="source answer"),
    ]
    component.db.upsert_run(current, session_id="session", user_id="owner")
    source_before = component.db.get_run("current").to_dict()

    def inspect_fork(messages):
        assert sum(m.content == "source request" for m in messages) == 1
        assert sum(m.content == "source answer" for m in messages) == 1
        assert sum(m.content == "prior" for m in messages) == 1
        running = component.db.get_runs(session_id="session", status=RunStatus.running)
        assert len(running) == 1
        assert running[0].run_id != "current"
        assert running[0].forked_from_run_id == "current"
        assert component.db.get_run(running[0].run_id, deserialize=False)["run_index"] is not None

    model.inspect_messages = inspect_fork
    method = component.acontinue_run if asynchronous else component.continue_run
    result = method(run_id="current", session_id="session", stream=stream)
    if asynchronous:
        if stream:
            async for _ in result:
                pass
        else:
            await result
    elif stream:
        list(result)
    assert model.calls == 1
    assert component.db.get_run("current").to_dict() == source_before


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("outage", [False, True])
async def test_start_uses_scoped_atomic_patch_and_propagates_failure(kind, monkeypatch, asynchronous, outage):
    from agno.run.concurrency import worker_managed_execution

    component = make_component(kind)
    component.db = Mock()
    update = AsyncMock() if asynchronous else Mock()
    update.return_value = RunPersistOutcome.UPDATED
    if outage:
        update.side_effect = RuntimeError("database unavailable")
    component.db.update_run_in_session = update
    run = make_run(kind, "current", status=RunStatus.paused)
    session = make_session(kind, [run])
    context = RunContext(run_id=run.run_id, session_id="session", user_id="owner")

    async def start():
        if asynchronous:
            await _apersist_continue_start(component, kind, run, session, context)
        else:
            _persist_continue_start(component, kind, run, session, context)

    with worker_managed_execution(run.run_id, "worker", attempt=3):
        if outage:
            with pytest.raises(RuntimeError, match="database unavailable"):
                await start()
        else:
            await start()
    update.assert_called_once_with(
        session_id="session", run_id="current", fields={"status": "RUNNING"}, user_id="owner", expected_attempt=3
    )
    component.db.upsert_run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("async_db", [False, True])
@pytest.mark.parametrize("outcome", [RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED])
async def test_refused_start_does_not_fall_back(kind, monkeypatch, async_db, outcome):
    component = make_component(kind)
    component.db = Mock()
    update = AsyncMock(return_value=outcome) if async_db else Mock(return_value=outcome)
    component.db.update_run_in_session = update
    run = make_run(kind, "current", status=RunStatus.paused)
    session = make_session(kind, [run])
    context = RunContext(run_id=run.run_id, session_id="session", user_id="owner")
    fallback_path = (
        "agno.agent._run.apersist_run_in_session" if kind == "agent" else "agno.team._run._apersist_team_run_in_session"
    )
    fallback = AsyncMock()
    monkeypatch.setattr(fallback_path, fallback)
    with pytest.raises(RunNotContinuableError):
        await _apersist_continue_start(component, kind, run, session, context)
    fallback.assert_not_called()
    if not async_db:
        sync_path = (
            "agno.agent._run.persist_run_in_session"
            if kind == "agent"
            else "agno.team._run._persist_team_run_in_session"
        )
        sync_fallback = Mock()
        monkeypatch.setattr(sync_path, sync_fallback)
        with pytest.raises(RunNotContinuableError):
            _persist_continue_start(component, kind, run, session, context)
        sync_fallback.assert_not_called()
