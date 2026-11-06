"""A public session save must not report success when the database refuses it."""

import asyncio
import json
from logging import DEBUG
from unittest.mock import Mock

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.exceptions import SessionNotSavedError
from agno.models.openai.responses import OpenAIResponses
from agno.models.response import ModelResponse
from agno.run.agent import RunCompletedEvent
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.tools import tool


@pytest.fixture(params=["agent", "team"])
def runtime(request):
    if request.param == "agent":
        return Agent(id="entity"), AgentSession
    return Team(id="entity", members=[]), TeamSession


def _session(session_type, user_id="owner"):
    return session_type(
        session_id="shared",
        user_id=user_id,
        session_data={"session_state": {"marker": "original"}},
        created_at=1000,
    )


@pytest.fixture(params=["sqlite", "memory"])
def sync_db(request, tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "sessions.db")) if request.param == "sqlite" else InMemoryDb()
    yield db
    if isinstance(db, SqliteDb):
        db.close()


@pytest.mark.parametrize("requester", ["other-user", None, ""])
def test_save_rejection_reaches_caller_and_preserves_owned_session(runtime, sync_db, requester, caplog):
    entity, session_type = runtime
    entity.db = sync_db
    original = _session(session_type)
    entity.save_session(original)
    before = sync_db.get_session("shared", deserialize=False)
    incoming = _session(session_type, requester)
    incoming.session_data["session_state"] = {"marker": "replacement"}
    caplog.clear()

    with caplog.at_level(DEBUG, logger="agno"), pytest.raises(SessionNotSavedError, match="shared"):
        entity.save_session(incoming)

    assert sync_db.get_session("shared", deserialize=False) == before
    assert "Created or updated" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("async_database", [False, True])
async def test_async_save_rejection_reaches_caller(runtime, tmp_path, async_database, caplog):
    entity, session_type = runtime
    db_type = AsyncSqliteDb if async_database else SqliteDb
    db = db_type(db_file=str(tmp_path / "sessions.db"))
    entity.db = db
    try:
        await entity.asave_session(_session(session_type))
        caplog.clear()
        with caplog.at_level(DEBUG, logger="agno"), pytest.raises(SessionNotSavedError, match="shared"):
            await entity.asave_session(_session(session_type, "other-user"))

        stored = await db.get_session("shared") if async_database else db.get_session("shared")
        assert stored.user_id == "owner"
        assert stored.session_data["session_state"] == {"marker": "original"}
        assert "Created or updated" not in caplog.text
    finally:
        if async_database:
            await db.close()
        else:
            db.close()


@pytest.mark.parametrize("owner", ["owner", None])
def test_save_preserves_owner_updates_and_unowned_claims(runtime, sync_db, owner):
    entity, session_type = runtime
    entity.db = sync_db
    original = _session(session_type, owner)
    entity.save_session(original)
    incoming = _session(session_type, "owner")
    incoming.session_data["session_state"] = {"marker": "updated"}

    entity.save_session(incoming)

    stored = sync_db.get_session("shared")
    assert stored.user_id == "owner"
    assert stored.session_data["session_state"] == {"marker": "updated"}


def test_save_without_database_remains_optional(runtime):
    entity, session_type = runtime
    entity.save_session(_session(session_type))


@pytest.mark.asyncio
async def test_async_save_without_database_remains_optional(runtime):
    entity, session_type = runtime
    await entity.asave_session(_session(session_type))


def test_database_failure_is_not_reported_as_success(runtime, sync_db, monkeypatch):
    entity, session_type = runtime
    entity.db = sync_db

    def fail_write(session):
        raise OSError("database unavailable")

    monkeypatch.setattr(sync_db, "upsert_session", fail_write)
    with pytest.raises(SessionNotSavedError, match="shared"):
        entity.save_session(_session(session_type))


@pytest.fixture
def continuation():
    return False


@pytest.fixture(params=["agent", "team"])
def rejected_run(request, monkeypatch, continuation):
    """Stub only provider I/O so real model loops execute the tool."""
    db = InMemoryDb()
    monkeypatch.setattr(db, "upsert_session", Mock(return_value=None))
    executed = []

    @tool(requires_confirmation=continuation)
    def record_work() -> str:
        executed.append("called")
        return "ok"

    calls = []
    model = OpenAIResponses()

    def invoke(*args, **kwargs):
        calls.append("invoked")
        if len(calls) % 2:
            return ModelResponse(
                role="assistant",
                tool_calls=[
                    {
                        "index": 0,
                        "id": f"call-{len(calls)}",
                        "type": "function",
                        "function": {"name": "record_work", "arguments": "{}"},
                    }
                ],
            )
        return ModelResponse(role="assistant", content="done")

    async def ainvoke(*args, **kwargs):
        return invoke()

    def invoke_stream(*args, **kwargs):
        yield invoke()

    async def ainvoke_stream(*args, **kwargs):
        yield invoke()

    monkeypatch.setattr(model, "invoke", invoke)
    monkeypatch.setattr(model, "ainvoke", ainvoke)
    monkeypatch.setattr(model, "invoke_stream", invoke_stream)
    monkeypatch.setattr(model, "ainvoke_stream", ainvoke_stream)
    options = dict(model=model, db=db, tools=[record_work], retries=1, delay_between_retries=0, telemetry=False)
    entity = Agent(**options) if request.param == "agent" else Team(members=[], **options)
    return entity, executed, calls


@pytest.mark.parametrize("stream", [False, True])
def test_rejected_terminal_save_does_not_repeat_completed_work(rejected_run, stream):
    entity, executed, calls = rejected_run
    events = []
    with pytest.raises(SessionNotSavedError):
        result = entity.run("do the work", stream=stream, stream_events=stream)
        if stream:
            for event in result:
                events.append(event)
    assert executed == ["called"]
    assert len(calls) == 2
    assert not any(isinstance(event, (RunCompletedEvent, TeamRunCompletedEvent)) for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_async_rejected_terminal_save_does_not_repeat_completed_work(rejected_run, stream):
    entity, executed, calls = rejected_run
    events = []
    with pytest.raises(SessionNotSavedError):
        if stream:
            async for event in entity.arun("do the work", stream=True, stream_events=True):
                events.append(event)
        else:
            await entity.arun("do the work")
    assert executed == ["called"]
    assert len(calls) == 2
    assert not any(isinstance(event, (RunCompletedEvent, TeamRunCompletedEvent)) for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("continuation", [False, True], ids=["run", "continue"])
async def test_background_stream_reports_failed_session_save(rejected_run, continuation, tmp_path, monkeypatch):
    entity, executed, calls = rejected_run
    db = SqliteDb(db_file=str(tmp_path / "sessions.db"))
    entity.db = db
    save_session = db.upsert_session
    rejected_saves = []

    def reject_after_tool(*args, **kwargs):
        if executed:
            rejected_saves.append(True)
            return None
        return save_session(*args, **kwargs)

    monkeypatch.setattr(db, "upsert_session", reject_after_tool)
    session = {"session_id": "shared", "user_id": "owner"}
    stream = {"background": True, "stream": True, "stream_events": True}
    if continuation:
        paused = await entity.arun("do the work", **session)
        assert paused.is_paused
        for requirement in paused.requirements:
            requirement.confirm()
        chunks = entity.acontinue_run(run_id=paused.run_id, requirements=paused.requirements, **session, **stream)
    else:
        chunks = entity.arun("do the work", **session, **stream)

    async def collect_events():
        return [
            json.loads(line.removeprefix("data:"))["event"]
            async for chunk in chunks
            for line in chunk.splitlines()
            if line.startswith("data:")
        ]

    events = await asyncio.wait_for(collect_events(), timeout=10)
    assert len(rejected_saves) == 2
    assert executed == ["called"]
    assert len(calls) == 2
    expected_error = "RunError" if isinstance(entity, Agent) else "TeamRunError"
    assert [event for event in events if event in ("RunError", "TeamRunError")] == [expected_error]
    assert "RunCompleted" not in events
    assert "TeamRunCompleted" not in events
