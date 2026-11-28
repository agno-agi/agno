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


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_checkpoint_after_setup_retry(tmp_path, kind, mode):
    class RetrySetup(KilledAfter):
        def get_instructions_for_model(self, *args, **kwargs):
            if not getattr(self, "retried", False):
                self.retried = True
                raise RuntimeError("temporary instruction lookup failure")
            return super().get_instructions_for_model(*args, **kwargs)

    db = SqliteDb(db_file=str(tmp_path / "retry.db"))
    options = dict(model=RetrySetup(), db=db, retries=1, delay_between_retries=0, checkpoint="tool-batch")
    component = Agent(**options) if kind == "agent" else Team(members=[], **options)
    try:
        with pytest.raises(Killed):
            turn(component, "Hello", mode, run_id="initial")
        assert db.get_run("initial").status == RunStatus.running
    finally:
        db.close()


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind", ["agent", "team"])
def test_model_retry_excludes_current_checkpoint_from_history(tmp_path, mode, kind):
    from tests.unit.os.test_super_agent_linked_work import Scripted

    class RetryModel(Scripted):
        def invoke(self, *args, **kwargs):
            if not getattr(self, "retried", False):
                self.retried = True
                raise RuntimeError("temporary model failure")
            return super().invoke(*args, **kwargs)

    db = SqliteDb(db_file=str(tmp_path / "history.db"))
    options = dict(
        model=Scripted(),
        db=db,
        retries=1,
        delay_between_retries=0,
        add_history_to_context=True,
        num_history_runs=1,
        checkpoint="tool-batch",
    )
    component = Agent(**options) if kind == "agent" else Team(members=[], **options)
    try:
        turn(component, "Keep the limit at ten", mode)
        model = RetryModel()
        component.model = model
        turn(component, "How many?", mode)
        users = [(content, bool(old)) for role, content, old in model.requests[-1] if role == "user"]
        assert users == [("Keep the limit at ten", True), ("How many?", False)]
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["agent", "team", "task-team"])
def test_closing_sync_stream_persists_cancellation(tmp_path, kind):
    from agno.run.cancel import get_active_runs
    from tests.unit.os.test_super_agent_linked_work import Scripted

    db = SqliteDb(db_file=str(tmp_path / "stream.db"))
    options = dict(model=Scripted(), db=db, checkpoint="tool-batch")
    component = (
        Agent(**options)
        if kind == "agent"
        else Team(members=[], mode=TeamMode.tasks if kind == "task-team" else TeamMode.coordinate, **options)
    )
    try:
        stream = component.run("Hello", stream=True, session_id="chat", run_id="initial", stream_events=True)
        next(stream)
        stream.close()
        assert db.get_run("initial").status == RunStatus.cancelled
        assert "initial" not in get_active_runs()
    finally:
        db.close()


@pytest.mark.parametrize("kind", ["agent", "team"])
@pytest.mark.parametrize("mode", ["sync", "async"])
def test_all_checkpoints_share_media_uploads(tmp_path, kind, mode):
    from agno.media import Image
    from tests.unit.media.test_workflow_media_storage import CountingLocalStorage
    from tests.unit.os.test_super_agent_linked_work import Scripted

    def echo() -> str:
        """Return a test message."""
        return "ok"

    db = SqliteDb(db_file=str(tmp_path / "media.db"))
    storage = CountingLocalStorage(base_path=str(tmp_path / "files"))
    options = dict(
        model=Scripted([("echo", {}), ("echo", {})]),
        db=db,
        checkpoint="tool-batch",
        media_storage=storage,
        tools=[echo],
    )
    component = Agent(**options) if kind == "agent" else Team(members=[], **options)
    try:
        out = turn(component, "Hello", mode, images=[Image(content=b"image bytes", mime_type="image/png")])
        assert out.status == RunStatus.completed and len(out.tools) == 2
        assert len(storage.uploads) == 1
    finally:
        db.close()
