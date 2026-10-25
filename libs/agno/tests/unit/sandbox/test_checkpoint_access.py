"""Opening a run's committed checkpoint on the host through the agent's public surface."""

import os
from dataclasses import asdict

import pytest

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.sandbox import Sandbox, SandboxError, _harness
from agno.sandbox.checkpoint import CheckpointArchive, CheckpointObjectNotFound, FileCheckpointStore
from agno.sandbox.docker import DockerSandbox

URL = "postgresql+psycopg://ai:ai@localhost:1/ai"


class StoreOnlySandbox(Sandbox):
    """Holds a checkpoint store and never creates compute."""

    def __init__(self, checkpoints=None):
        self.checkpoints = checkpoints
        self.network = "isolated"

    async def acreate(self, session_id, *, agent_id=None, generation=1, env=None):
        raise NotImplementedError

    async def aget(self, provider_ref):
        raise NotImplementedError

    async def aexec(self, handle, command, **kwargs):
        raise NotImplementedError

    async def astop(self, handle):
        raise NotImplementedError

    async def adestroy(self, handle):
        raise NotImplementedError


@pytest.fixture
def committed(tmp_path):
    """A checkpoint as a turn commits it: both roots captured, the object in a file store."""
    workspace, native = tmp_path / "workspace", tmp_path / "native"
    workspace.mkdir()
    native.mkdir()
    (workspace / "fixture-effects.txt").write_text("first\n")
    (native / "fixture-session").write_text("native-1")
    CheckpointArchive().capture(
        {"workspace": workspace, "native": native}, tmp_path / "checkpoint.tar", state={"binding": "b"}
    )
    store = FileCheckpointStore(tmp_path / "objects")
    return store, store.put(tmp_path / "checkpoint.tar")


def run_row(reference, *, run_id="run-1", agent_id="coder", status="COMPLETED", checkpoint=True):
    """The runs-table row as ``db.get_run(run_id, deserialize=False)`` returns it."""
    sandbox = {"checkpoint": asdict(reference)} if checkpoint else {"recovery_run_id": "run-0"}
    return {
        "run_id": run_id,
        "agent_id": agent_id,
        "status": status,
        "run_data": {"run_id": run_id, "status": status, "metadata": {"sandbox": sandbox}},
    }


def sync_db(monkeypatch, *rows):
    by_id = {row["run_id"]: row for row in rows}
    db = PostgresDb(db_url=URL)
    monkeypatch.setattr(db, "get_run", lambda run_id, deserialize=True: by_id.get(run_id))
    return db


def async_db(monkeypatch, *rows):
    by_id = {row["run_id"]: row for row in rows}
    db = AsyncPostgresDb(db_url=URL)

    async def get_run(run_id, deserialize=True):
        return by_id.get(run_id)

    monkeypatch.setattr(db, "get_run", get_run)
    return db


def agent_with(db, store):
    return ClaudeAgent(id="coder", db=db, sandbox=StoreOnlySandbox(checkpoints=store))


def test_checkpoint_store_is_the_sandbox_store(committed):
    store, _ = committed
    assert agent_with(None, store).checkpoint_store is store


def test_checkpoint_store_defaults_to_the_file_store_the_coordinator_uses(tmp_path, monkeypatch):
    from agno.os import job_queue

    monkeypatch.setattr(_harness, "_DEFAULT_CHECKPOINTS", tmp_path / "default")
    monkeypatch.setattr(job_queue, "get_active_queue_worker", lambda: None)
    warned = []
    monkeypatch.setattr(_harness, "log_warning", warned.append)
    db = PostgresDb(db_url=URL)
    agent = ClaudeAgent(id="coder", db=db, sandbox=DockerSandbox("agno-sandbox:claude", network="isolated"))
    before = agent.checkpoint_store
    assert isinstance(before, FileCheckpointStore) and before.root == tmp_path / "default"
    assert warned and "checkpoints=" in warned[0]
    # Once the coordinator exists, the property answers with the very store its turns commit to.
    built = _harness.coordinator(agent)
    assert agent.checkpoint_store is built.transfer.store
    assert built.transfer.store.root == tmp_path / "default"


def test_checkpoint_store_is_refused_under_a_queue_worker(tmp_path, monkeypatch):
    from agno.os import job_queue

    monkeypatch.setattr(_harness, "_DEFAULT_CHECKPOINTS", tmp_path / "default")
    monkeypatch.setattr(job_queue, "get_active_queue_worker", lambda: object())
    agent = ClaudeAgent(id="coder", sandbox=StoreOnlySandbox())
    with pytest.raises(ValueError, match="checkpoints="):
        agent.checkpoint_store
    # An explicit store is what the refusal asks for, so it is honoured.
    store = FileCheckpointStore(tmp_path / "objects")
    assert ClaudeAgent(id="coder", sandbox=StoreOnlySandbox(checkpoints=store)).checkpoint_store is store


def test_checkpoint_store_requires_a_sandbox():
    with pytest.raises(SandboxError, match="has no sandbox"):
        ClaudeAgent(id="coder").checkpoint_store


def test_open_run_checkpoint_restores_the_committed_archive(committed, tmp_path, monkeypatch):
    store, reference = committed
    agent = agent_with(sync_db(monkeypatch, run_row(reference)), store)
    with agent.open_run_checkpoint("run-1") as archive:
        state = CheckpointArchive().restore(archive, tmp_path / "opened")
        held = archive
    assert state == {"binding": "b"}
    assert (tmp_path / "opened/workspace/fixture-effects.txt").read_text() == "first\n"
    assert (tmp_path / "opened/native/fixture-session").read_text() == "native-1"
    # The store's lease on the object ends with the context.
    assert not held.exists()


async def test_aopen_run_checkpoint_restores_the_committed_archive(committed, tmp_path, monkeypatch):
    store, reference = committed
    agent = agent_with(async_db(monkeypatch, run_row(reference)), store)
    async with agent.aopen_run_checkpoint("run-1") as archive:
        state = await CheckpointArchive().arestore(archive, tmp_path / "opened")
        held = archive
    assert state == {"binding": "b"}
    assert (tmp_path / "opened/workspace/fixture-effects.txt").read_text() == "first\n"
    assert not held.exists()


async def test_async_open_reads_a_sync_database(committed, monkeypatch):
    store, reference = committed
    agent = agent_with(sync_db(monkeypatch, run_row(reference)), store)
    async with agent.aopen_run_checkpoint("run-1") as archive:
        assert archive.stat().st_size == reference.size


def test_sync_open_refuses_an_async_database(committed, monkeypatch):
    store, reference = committed
    agent = agent_with(async_db(monkeypatch, run_row(reference)), store)
    with pytest.raises(ValueError, match="Use aopen_run_checkpoint with an async database"):
        with agent.open_run_checkpoint("run-1"):
            pass


@pytest.mark.parametrize(
    "row, message",
    [
        (None, "does not exist"),
        ("other agent", "belongs to another agent"),
        ("ERROR", "ERROR, not COMPLETED"),
        ("CANCELLED", "CANCELLED, not COMPLETED"),
        ("RUNNING", "RUNNING, not COMPLETED"),
        ("PENDING", "PENDING, not COMPLETED"),
        ("no checkpoint", "committed no sandbox checkpoint"),
    ],
)
async def test_open_run_checkpoint_refusals(committed, monkeypatch, row, message):
    store, reference = committed
    if row is None:
        rows = []
    elif row == "other agent":
        rows = [run_row(reference, agent_id="someone-else")]
    elif row == "no checkpoint":
        rows = [run_row(reference, checkpoint=False)]
    else:
        rows = [run_row(reference, status=row, checkpoint=False)]
    agent = agent_with(sync_db(monkeypatch, *rows), store)
    with pytest.raises(ValueError, match=message):
        with agent.open_run_checkpoint("run-1"):
            pass
    with pytest.raises(ValueError, match=message):
        async with agent.aopen_run_checkpoint("run-1"):
            pass


async def test_open_run_checkpoint_requires_a_database(committed):
    store, _ = committed
    agent = agent_with(None, store)
    with pytest.raises(ValueError, match="no database"):
        with agent.open_run_checkpoint("run-1"):
            pass
    with pytest.raises(ValueError, match="no database"):
        async with agent.aopen_run_checkpoint("run-1"):
            pass


def test_a_retired_object_is_reported_as_missing(committed, monkeypatch):
    store, reference = committed
    agent = agent_with(sync_db(monkeypatch, run_row(reference)), store)
    store.delete(reference)
    with pytest.raises(CheckpointObjectNotFound):
        with agent.open_run_checkpoint("run-1"):
            pass


async def test_a_tampered_object_is_refused_before_it_is_yielded(committed, monkeypatch):
    store, reference = committed
    agent = agent_with(async_db(monkeypatch, run_row(reference)), store)
    stored = store.root / reference.sha256
    stored.chmod(0o600)
    stored.write_bytes(bytes(reference.size))
    with pytest.raises(SandboxError, match="checksum"):
        async with agent.aopen_run_checkpoint("run-1"):
            pytest.fail("a tampered archive must not be yielded")


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the mode this test relies on")
def test_the_yielded_path_cannot_alter_the_stored_checkpoint(committed, tmp_path, monkeypatch):
    store, reference = committed
    agent = agent_with(sync_db(monkeypatch, run_row(reference)), store)
    with agent.open_run_checkpoint("run-1") as archive:
        with pytest.raises(PermissionError):
            archive.open("r+b")
        with pytest.raises(PermissionError):
            archive.write_bytes(b"clobbered")
    # The object the run points at is untouched, so the session can still recover from it.
    store.verify(reference)
    with agent.open_run_checkpoint("run-1") as archive:
        CheckpointArchive().restore(archive, tmp_path / "still-intact")
    assert (tmp_path / "still-intact/workspace/fixture-effects.txt").read_text() == "first\n"
