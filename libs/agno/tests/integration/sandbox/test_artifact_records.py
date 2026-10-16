"""Artifact reads against real PostgreSQL recovery records. No provider, compute or model calls.

The fixtures drive the same store calls the coordinator makes to publish a turn, so the
records under test are the ones a real session leaves behind rather than a hand-built shape.
"""

import os
from dataclasses import asdict
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.sandbox.artifacts import SandboxArtifactNotFound, SandboxArtifacts, SandboxSessionNotFound
from agno.sandbox.base import SandboxError, SandboxHandle
from agno.sandbox.checkpoint import CheckpointArchive, FileCheckpointStore
from agno.sandbox.postgres import _SandboxStore

URL = os.environ.get("AGNO_TEST_SANDBOX_DB_URL")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Set AGNO_TEST_SANDBOX_DB_URL")]


@pytest_asyncio.fixture(params=[PostgresDb, AsyncPostgresDb])
async def store(request):
    suffix = uuid4().hex[:12]
    db = request.param(
        db_url=URL,
        session_table="ar_sessions_" + suffix,
        runs_table="ar_runs_" + suffix,
        sandbox_table="ar_bindings_" + suffix,
    )
    store = _SandboxStore(db)
    yield store
    await store._transaction(lambda c: [table.drop(c) for table in (store.bindings, store.runs, store.sessions)])
    if isinstance(db, AsyncPostgresDb):
        await db.db_engine.dispose()
    else:
        db.db_engine.dispose()


@pytest.fixture(params=[True, False], ids=["compressed", "plain"])
def compress(request):
    return request.param


@pytest.fixture
def objects(tmp_path):
    return FileCheckpointStore(tmp_path / "objects")


async def seed(store, *, run_id, session_id="session", agent_id="agent", user_id="user"):
    def write(c):
        if c.execute(select(store.sessions).where(store.sessions.c.session_id == session_id)).first() is None:
            c.execute(
                store.sessions.insert().values(
                    session_id=session_id,
                    session_type="agent",
                    agent_id=agent_id,
                    user_id=user_id,
                    session_data={},
                    created_at=1,
                )
            )
        c.execute(
            store.runs.insert().values(
                run_id=run_id,
                session_id=session_id,
                run_type="agent",
                agent_id=agent_id,
                user_id=user_id,
                status="RUNNING",
                created_at=1,
                run_data={
                    "run_id": run_id,
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "status": "RUNNING",
                    "input": {"input_content": "hello"},
                },
            )
        )

    await store._transaction(write)


def _result(lease):
    return {
        "type": "execution_finished",
        "run": {
            "run_id": lease.run_id,
            "session_id": lease.session_id,
            "agent_id": lease.agent_id,
            "user_id": lease.user_id,
            "status": "COMPLETED",
            "content": "done",
        },
        "session": {"session_id": lease.session_id, "user_id": lease.user_id, "session_data": {"native_id": "native"}},
    }


async def _stage(store, objects, tmp_path, lease, files, compress):
    """Capture a real archive and stamp it the way the coordinator's finalize does."""
    workspace, native = tmp_path / ("ws-" + lease.run_id), tmp_path / ("nat-" + lease.run_id)
    workspace.mkdir()
    native.mkdir()
    for name, content in files.items():
        (workspace / name).write_bytes(content)
    (native / "session.db").write_bytes(b"native state")
    archive = tmp_path / ("archive-" + lease.run_id)

    async def capture(record):
        identity = dict(
            agent_id=lease.agent_id,
            session_id=lease.session_id,
            user_id=lease.user_id,
            incarnation=record["incarnation"],
            run_id=lease.run_id,
            execution_id=record["execution_id"],
            generation=record["generation"],
        )
        CheckpointArchive(compress=compress).capture(
            {"workspace": workspace, "native": native}, archive, state={"binding": identity}
        )
        reference = objects.put(archive)
        record.update(staged_checkpoint=asdict(reference), staged_identity=identity)
        return record

    return await store._aoperation(lease, capture)


async def turn(store, objects, tmp_path, *, run_id, files, compress, publish=True):
    """Run one durable turn through the store and publish it, as a completed session would."""
    await seed(store, run_id=run_id)
    state = await store.aclaim(agent_id="agent", session_id="session", user_id="user", run_id=run_id, owner="owner")
    lease = state.lease
    await store.aset_computer(
        lease, SandboxHandle("ref", "name", "agent", "session", state.record["generation"], "running", "digest")
    )
    await store.astage_result(lease, _result(lease))
    await _stage(store, objects, tmp_path, lease, files, compress)
    if not publish:
        return lease
    await store.aconfirm_stopped(lease, "ref")
    await store.acommit(lease)
    return lease


async def binding(store):
    return await store._transaction(lambda c: dict(c.execute(select(store.bindings)).mappings().one()))


def reader(store, objects):
    return SandboxArtifacts(store, objects)


async def test_a_committed_checkpoint_is_readable_without_taking_a_lease(store, objects, tmp_path, compress):
    await turn(store, objects, tmp_path, run_id="run", files={"a.txt": b"a"}, compress=compress)
    before = await binding(store)
    artifacts = reader(store, objects)

    status = await artifacts.astatus(agent_id="agent", session_id="session", user_id="user")
    listing = await artifacts.alist(agent_id="agent", session_id="session", user_id="user")
    artifact = await artifacts.aread("a.txt", agent_id="agent", session_id="session", user_id="user")

    assert status["phase"] == "idle" and status["has_checkpoint"] is True
    assert status["compute_allocated"] is False and status["active_run_id"] is None
    assert status["last_completed_run_id"] == "run"
    assert listing["files"] == [{"path": "a.txt", "size": 1}] and listing["total"] == 1
    assert artifact.content == b"a" and artifact.run_id == "run"
    after = await binding(store)
    # No lease, no ownership and no new generation: reads leave the session exactly as it was.
    assert (after["owner"], after["run_id"], after["queue_attempt"], after["expires_at"]) == (None, None, None, None)
    assert after["epoch"] == before["epoch"] and after["record"] == before["record"]
    assert after["record"]["computer"] is None


@pytest.mark.parametrize(
    "scope",
    [
        {"agent_id": "other-agent"},
        {"user_id": "other-user"},
        {"user_id": None},
        {"session_id": "other-session"},
    ],
)
async def test_reads_outside_the_owning_scope_are_refused(store, objects, tmp_path, compress, scope):
    await turn(store, objects, tmp_path, run_id="run", files={"a.txt": b"a"}, compress=compress)
    artifacts = reader(store, objects)
    owner = {"agent_id": "agent", "session_id": "session", "user_id": "user", **scope}

    with pytest.raises(SandboxSessionNotFound):
        await artifacts.astatus(**owner)
    with pytest.raises(SandboxSessionNotFound):
        await artifacts.alist(**owner)
    with pytest.raises(SandboxSessionNotFound):
        await artifacts.aread("a.txt", **owner)


async def test_a_recreated_session_cannot_inherit_the_deleted_session_artifacts(store, objects, tmp_path, compress):
    await turn(store, objects, tmp_path, run_id="run", files={"a.txt": b"a"}, compress=compress)
    first = (await binding(store))["record"]
    artifacts = reader(store, objects)

    await store._transaction(
        lambda c: (
            c.execute(delete(store.runs).where(store.runs.c.session_id == "session")),
            c.execute(delete(store.sessions).where(store.sessions.c.session_id == "session")),
        )
    )
    # Deleting the session takes its binding with it, so the checkpoint is unreachable.
    assert await store._transaction(lambda c: c.execute(select(store.bindings)).first()) is None
    with pytest.raises(SandboxSessionNotFound):
        await artifacts.astatus(agent_id="agent", session_id="session", user_id="user")

    await seed(store, run_id="run2")
    await store.aclaim(agent_id="agent", session_id="session", user_id="user", run_id="run2", owner="owner")
    recreated = (await binding(store))["record"]
    assert recreated["incarnation"] != first["incarnation"]
    status = await artifacts.astatus(agent_id="agent", session_id="session", user_id="user")
    assert status["has_checkpoint"] is False
    with pytest.raises(SandboxArtifactNotFound):
        await artifacts.alist(agent_id="agent", session_id="session", user_id="user")


@pytest.mark.parametrize("field", ["run_id", "incarnation"])
async def test_a_checkpoint_whose_manifest_identity_differs_is_refused(store, objects, tmp_path, compress, field):
    await turn(store, objects, tmp_path, run_id="run", files={"a.txt": b"a"}, compress=compress)

    def tamper(c):
        record = dict(c.execute(select(store.bindings.c.record)).scalar_one())
        identity = dict(record["checkpoint_identity"])
        identity[field] = "elsewhere"
        if field == "incarnation":
            record["incarnation"] = "elsewhere"
        record["checkpoint_identity"] = identity
        c.execute(store.bindings.update().values(record=record))

    await store._transaction(tamper)
    artifacts = reader(store, objects)
    with pytest.raises(SandboxError, match="does not match this session"):
        await artifacts.alist(agent_id="agent", session_id="session", user_id="user")
    with pytest.raises(SandboxError, match="does not match this session"):
        await artifacts.aread("a.txt", agent_id="agent", session_id="session", user_id="user")


async def test_turn_one_stays_readable_until_turn_two_publishes(store, objects, tmp_path, compress):
    await turn(store, objects, tmp_path, run_id="run", files={"a.txt": b"a"}, compress=compress)
    artifacts = reader(store, objects)
    lease = await turn(store, objects, tmp_path, run_id="run2", files={"b.txt": b"b"}, compress=compress, publish=False)

    # Turn two has staged its checkpoint but not committed it; the visible artifact is still turn one.
    status = await artifacts.astatus(agent_id="agent", session_id="session", user_id="user")
    assert status["active_run_id"] == "run2" and status["last_completed_run_id"] == "run"
    listing = await artifacts.alist(agent_id="agent", session_id="session", user_id="user")
    assert [entry["path"] for entry in listing["files"]] == ["a.txt"]
    with pytest.raises(SandboxArtifactNotFound):
        await artifacts.aread("b.txt", agent_id="agent", session_id="session", user_id="user")

    await store.aconfirm_stopped(lease, "ref")
    await store.acommit(lease)
    listing = await artifacts.alist(agent_id="agent", session_id="session", user_id="user")
    assert [entry["path"] for entry in listing["files"]] == ["b.txt"]
    assert (await artifacts.aread("b.txt", agent_id="agent", session_id="session", user_id="user")).content == b"b"
    status = await artifacts.astatus(agent_id="agent", session_id="session", user_id="user")
    assert status["last_completed_run_id"] == "run2" and status["active_run_id"] is None


async def test_a_turn_that_fails_before_publication_leaves_turn_one_readable(store, objects, tmp_path, compress):
    await turn(store, objects, tmp_path, run_id="run", files={"a.txt": b"a"}, compress=compress)
    artifacts = reader(store, objects)
    lease = await turn(store, objects, tmp_path, run_id="run2", files={"b.txt": b"b"}, compress=compress, publish=False)

    await store.abegin_stop(lease, status="ERROR", reason="Compute was lost before publication")
    await store.aconfirm_stopped(lease, "ref")
    await store.afinish_stop(lease)

    listing = await artifacts.alist(agent_id="agent", session_id="session", user_id="user")
    assert [entry["path"] for entry in listing["files"]] == ["a.txt"]
    status = await artifacts.astatus(agent_id="agent", session_id="session", user_id="user")
    assert status["last_completed_run_id"] == "run" and status["phase"] == "idle"
