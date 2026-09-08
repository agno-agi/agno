"""Tests for deleting a session's offloaded media through the SDK.

Deleting the row destroys the only record of which object belongs to which session, so the
keys are read first and the objects swept after. ``delete_media`` is opt-in: without it the
objects outlive the rows, which is what every caller got before the flag existed.
"""

import asyncio
import os
import tempfile

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.media import Image
from agno.media.storage.local import AsyncLocalMediaStorage, LocalMediaStorage
from agno.run.agent import RunOutput
from agno.session import AgentSession
from agno.team.team import Team
from agno.utils.media_offload import (
    adelete_media_keys,
    delete_media_keys,
    offload_run_media,
    session_media_keys,
)
from agno.workflow.workflow import Workflow


def _offloaded_run(storage, session_id: str = "s1") -> RunOutput:
    """A run whose image has been offloaded to ``storage``."""
    run = RunOutput(run_id="r1", agent_id="a", images=[Image(id="i1", content=b"BYTES", mime_type="image/png")])
    offload_run_media(run, storage, session_id)
    return run


def _offloaded_session(storage, session_id: str = "s1") -> AgentSession:
    """A session holding one run whose image has been offloaded to ``storage``."""
    return AgentSession(session_id=session_id, agent_id="a", runs=[_offloaded_run(storage, session_id)])


def _agent(tmpdir, storage):
    return Agent(id="a", db=SqliteDb(db_file=os.path.join(tmpdir, "a.db")), media_storage=storage)


def _persist(entity, session, run) -> None:
    """Write the row the way a real run does: the session first, then its run."""
    entity.db.upsert_session(session)
    entity.db.upsert_run(run=run, session_id=session.session_id, run_index=0)


# ---------------------------------------------------------------------------
# session_media_keys
# ---------------------------------------------------------------------------


def test_keys_are_read_from_the_reference():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        session = _offloaded_session(storage)

        keys = session_media_keys(session, ["s1"], storage)

        assert len(keys) == 1
        assert os.path.exists(os.path.join(tmpdir, keys[0]))


def test_media_borrowed_from_another_session_is_left_be():
    """A run that inherited a reference names the session that uploaded it, so the borrower
    must not sweep it — deleting the borrower would take the owner's object with it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        session = _offloaded_session(storage, session_id="owner")
        session.session_id = "borrower"

        assert session_media_keys(session, ["borrower"], storage) == []
        assert session_media_keys(session, ["owner"], storage) != []


def test_a_key_from_another_backend_is_left_be():
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as other:
        session = _offloaded_session(LocalMediaStorage(base_path=tmpdir))

        assert session_media_keys(session, ["s1"], LocalMediaStorage(base_path=other)) == []


def test_a_key_from_another_backend_is_warned_about(monkeypatch):
    """The sweep cannot reach it, so the operator gets told rather than a clean delete."""
    from agno.utils import media_offload

    warnings: list = []
    monkeypatch.setattr(media_offload, "log_warning", lambda msg, *a, **kw: warnings.append(str(msg)))

    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as other:
        session = _offloaded_session(LocalMediaStorage(base_path=tmpdir))

        assert session_media_keys(session, ["s1"], LocalMediaStorage(base_path=other)) == []

    assert any("stored on another backend" in message for message in warnings)


def test_media_that_was_never_offloaded_yields_no_keys():
    with tempfile.TemporaryDirectory() as tmpdir:
        run = RunOutput(run_id="r1", images=[Image(id="i1", content=b"BYTES", mime_type="image/png")])
        session = AgentSession(session_id="s1", runs=[run])

        assert session_media_keys(session, ["s1"], LocalMediaStorage(base_path=tmpdir)) == []


# ---------------------------------------------------------------------------
# delete_media_keys
# ---------------------------------------------------------------------------


def test_the_same_key_twice_is_deleted_once():
    """One reference is reachable from several places on a run, so the raw list repeats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        session = _offloaded_session(storage)
        key = session_media_keys(session, ["s1"], storage)[0]

        delete_media_keys([key, key], storage)

        assert not os.path.exists(os.path.join(tmpdir, key))


def test_a_storage_failure_does_not_raise():
    """The rows are already gone by this point, so a sweep failure must not fail the delete."""

    class Failing(LocalMediaStorage):
        def delete_many(self, keys):
            raise OSError("bucket unreachable")

    with tempfile.TemporaryDirectory() as tmpdir:
        delete_media_keys(["k"], Failing(base_path=tmpdir))


@pytest.mark.asyncio
async def test_async_sweep_accepts_a_sync_backend():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalMediaStorage(base_path=tmpdir)
        session = _offloaded_session(storage)
        key = session_media_keys(session, ["s1"], storage)[0]

        await adelete_media_keys([key], storage)

        assert not os.path.exists(os.path.join(tmpdir, key))


# ---------------------------------------------------------------------------
# Agent / Team / Workflow
# ---------------------------------------------------------------------------


def test_delete_session_sweeps_the_media():
    with tempfile.TemporaryDirectory() as tmpdir:
        media = os.path.join(tmpdir, "media")
        storage = LocalMediaStorage(base_path=media)
        agent = _agent(tmpdir, storage)
        run = _offloaded_run(storage)
        _persist(agent, AgentSession(session_id="s1", agent_id="a", runs=[run]), run)
        assert os.listdir(media)

        agent.delete_session(session_id="s1", delete_media=True)

        assert [f for f in os.listdir(media) if not f.endswith(".meta.json")] == []


def test_delete_session_keeps_the_media_without_the_flag():
    with tempfile.TemporaryDirectory() as tmpdir:
        media = os.path.join(tmpdir, "media")
        storage = LocalMediaStorage(base_path=media)
        agent = _agent(tmpdir, storage)
        run = _offloaded_run(storage)
        _persist(agent, AgentSession(session_id="s1", agent_id="a", runs=[run]), run)

        agent.delete_session(session_id="s1")

        assert [f for f in os.listdir(media) if not f.endswith(".meta.json")] != []


def test_an_async_backend_is_refused_before_the_row_is_deleted():
    """Raising after the delete would leave the object with nothing pointing at it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        media = os.path.join(tmpdir, "media")
        agent = _agent(tmpdir, LocalMediaStorage(base_path=media))
        run = _offloaded_run(agent.media_storage)
        _persist(agent, AgentSession(session_id="s1", agent_id="a", runs=[run]), run)
        agent.media_storage = AsyncLocalMediaStorage(base_path=media)

        with pytest.raises(ValueError, match="Use adelete_session"):
            agent.delete_session(session_id="s1", delete_media=True)

        assert agent.db.get_session(session_id="s1") is not None
        assert [f for f in os.listdir(media) if not f.endswith(".meta.json")] != []


def test_delete_media_without_a_backend_is_a_no_op():
    with tempfile.TemporaryDirectory() as tmpdir:
        agent = Agent(id="a", db=SqliteDb(db_file=os.path.join(tmpdir, "a.db")))
        agent.db.upsert_session(AgentSession(session_id="s1", agent_id="a", runs=[]))

        agent.delete_session(session_id="s1", delete_media=True)

        assert agent.db.get_session(session_id="s1") is None


@pytest.mark.asyncio
async def test_adelete_session_sweeps_the_media():
    with tempfile.TemporaryDirectory() as tmpdir:
        media = os.path.join(tmpdir, "media")
        storage = AsyncLocalMediaStorage(base_path=media)
        agent = _agent(tmpdir, storage)
        run = RunOutput(run_id="r1", agent_id="a", images=[Image(id="i1", content=b"BYTES", mime_type="image/png")])
        from agno.utils.media_offload import aoffload_run_media

        await aoffload_run_media(run, storage, "s1")
        _persist(agent, AgentSession(session_id="s1", agent_id="a", runs=[run]), run)
        assert os.listdir(media)

        await agent.adelete_session(session_id="s1", delete_media=True)

        assert [f for f in os.listdir(media) if not f.endswith(".meta.json")] == []


def test_team_and_workflow_take_the_same_flag():
    """Parity: the parameter exists with the same default on all three entities."""
    import inspect

    for fn in (
        Agent.delete_session,
        Agent.adelete_session,
        Team.delete_session,
        Team.adelete_session,
        Workflow.delete_session,
        Workflow.adelete_session,
    ):
        param = inspect.signature(fn).parameters.get("delete_media")
        assert param is not None, fn.__qualname__
        assert param.default is False, fn.__qualname__


def test_workflow_delete_session_sweeps_the_media():
    with tempfile.TemporaryDirectory() as tmpdir:
        from agno.session import WorkflowSession

        media = os.path.join(tmpdir, "media")
        storage = LocalMediaStorage(base_path=media)
        wf = Workflow(id="w", name="w", db=SqliteDb(db_file=os.path.join(tmpdir, "w.db")), media_storage=storage)
        run = RunOutput(run_id="r1", workflow_id="w", images=[Image(id="i1", content=b"BYTES", mime_type="image/png")])
        offload_run_media(run, storage, "s1")
        wf.db.upsert_session(WorkflowSession(session_id="s1", workflow_id="w", runs=[run]))
        wf.db.upsert_run(run=run, session_id="s1", run_index=0)
        assert os.listdir(media)

        wf.delete_session(session_id="s1", delete_media=True)

        assert [f for f in os.listdir(media) if not f.endswith(".meta.json")] == []


def test_a_delete_without_the_flag_hints_at_delete_media(monkeypatch):
    """The objects outlive the row by default, so the operator is told the flag that sweeps them exists."""
    from agno.agent import _session as agent_session

    messages: list = []
    monkeypatch.setattr(agent_session, "log_debug", lambda msg, *a, **kw: messages.append(str(msg)))

    with tempfile.TemporaryDirectory() as tmpdir:
        media = os.path.join(tmpdir, "media")
        storage = LocalMediaStorage(base_path=media)
        agent = _agent(tmpdir, storage)
        run = _offloaded_run(storage)
        _persist(agent, AgentSession(session_id="s1", agent_id="a", runs=[run]), run)

        agent.delete_session(session_id="s1")

        assert any("pass delete_media=True" in message for message in messages)

        messages.clear()
        _persist(agent, AgentSession(session_id="s2", agent_id="a", runs=[_offloaded_run(storage, "s2")]), run)

        agent.delete_session(session_id="s2", delete_media=True)

        assert not any("pass delete_media=True" in message for message in messages)


def test_asyncio_is_importable_without_the_agentos_layer():
    """The SDK delete path must not pull in fastapi, which is not a core dependency."""
    import subprocess
    import sys

    code = (
        "import sys, importlib.abc\n"
        "class B(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('fastapi', 'starlette'):\n"
        "            raise ImportError(name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, B())\n"
        "from agno.utils.media_offload import session_media_keys, delete_media_keys, iter_run_media\n"
    )
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


assert asyncio  # imported for the async tests above
