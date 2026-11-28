"""A fresh run is durable while the first model call is still in progress."""

import asyncio

import pytest

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus
from agno.run.concurrency import worker_managed_execution
from agno.team import Team
from agno.team.mode import TeamMode
from tests.unit.os.test_super_agent_interrupted_turn import MODES, Killed, KilledAfter, turn


@pytest.mark.parametrize("kind", ["agent", "team", "task-team"])
@pytest.mark.parametrize("mode", MODES)
def test_start_checkpoint_before_first_model_response(tmp_path, kind, mode):
    db = SqliteDb(db_file=str(tmp_path / "chat.db"))
    component = (
        Agent(model=KilledAfter(), db=db, checkpoint="tool-batch")
        if kind == "agent"
        else Team(
            members=[],
            mode=TeamMode.tasks if kind == "task-team" else TeamMode.coordinate,
            model=KilledAfter(),
            db=db,
            checkpoint="tool-batch",
        )
    )
    try:
        with pytest.raises(Killed):
            turn(component, "First question", mode, session_state={"topic": "invoices"})
        session = db.get_session("chat", SessionType.AGENT if kind == "agent" else SessionType.TEAM)
        (run,) = session.runs
        assert run.status == RunStatus.running and run.input.input_content == "First question"
        assert run.session_state == {"topic": "invoices"}
        assert run.last_checkpoint_at_message_index == len(run.messages)
        assert any(m.role == "user" and m.content == "First question" for m in run.messages)
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_queue_keeps_ownership_of_the_start_transition(tmp_path, kind, mode):
    db = SqliteDb(db_file=str(tmp_path / "queue.db"))
    component = (
        Agent(model=KilledAfter(), db=db, checkpoint="tool-batch")
        if kind == "agent"
        else Team(members=[], model=KilledAfter(), db=db, checkpoint="tool-batch")
    )
    try:
        with worker_managed_execution("queued", "worker", 1), pytest.raises(Killed):
            if mode == "sync":
                component.run("Hello", run_id="queued", session_id="chat")
            else:
                asyncio.run(component.arun("Hello", run_id="queued", session_id="chat"))
        assert db.get_run("queued") is None
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_explicit_continue_uses_initial_checkpoint(tmp_path, kind, mode):
    from tests.unit.os.test_super_agent_linked_work import Scripted

    db = SqliteDb(db_file=str(tmp_path / "resume.db"))
    component = (
        Agent(model=KilledAfter(), db=db, checkpoint="tool-batch")
        if kind == "agent"
        else Team(members=[], model=KilledAfter(), db=db, checkpoint="tool-batch")
    )
    try:
        with pytest.raises(Killed):
            turn(component, "The original question", mode)
        session_type = SessionType.AGENT if kind == "agent" else SessionType.TEAM
        (initial,) = db.get_session("chat", session_type).runs
        model = Scripted()
        component.model = model
        options = dict(run_id=initial.run_id, session_id="chat", user_id="alice")
        if mode == "async":
            asyncio.run(component.acontinue_run(**options))
        else:
            component.continue_run(**options)
        (completed,) = db.get_session("chat", session_type).runs
        assert (completed.run_id, completed.status) == (initial.run_id, RunStatus.completed)
        assert [content for role, content, old in model.requests[0] if role == "user"] == ["The original question"]
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_start_checkpoint_uses_stored_history_policy(tmp_path, kind):
    from tests.unit.os.test_super_agent_linked_work import Scripted

    db = SqliteDb(db_file=str(tmp_path / "history.db"))
    options = dict(
        model=Scripted(), db=db, checkpoint="tool-batch", add_history_to_context=True, store_history_messages=False
    )
    component = Agent(**options) if kind == "agent" else Team(members=[], **options)
    try:
        turn(component, "Old question", "sync")
        component.model = KilledAfter()
        with pytest.raises(Killed):
            turn(component, "New question", "sync")
        session_type = SessionType.AGENT if kind == "agent" else SessionType.TEAM
        completed, partial = db.get_session("chat", session_type).runs
        assert completed.status == RunStatus.completed
        assert partial.last_checkpoint_at_message_index == len(partial.messages)
        assert [m.content for m in partial.messages if m.role == "user"] == ["New question"]
    finally:
        db.close()
