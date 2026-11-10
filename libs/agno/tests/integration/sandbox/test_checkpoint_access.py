"""A run's committed checkpoint opened on the host through the agent: real Docker and Postgres, fixture harness."""

import asyncio
import json
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.exceptions import RunCancelledException
from agno.run.base import RunStatus
from agno.sandbox import Repository, _harness
from agno.sandbox.checkpoint import CheckpointArchive, FileCheckpointStore
from agno.sandbox.docker import DockerSandbox
from agno.sandbox.fixture import FixtureAgent

URL, IMAGE = os.environ.get("AGNO_TEST_SANDBOX_DB_URL"), os.environ.get("AGNO_TEST_RUNTIME_IMAGE")
SUBNET = {"subnet": os.environ["AGNO_TEST_SANDBOX_SUBNET"]} if os.environ.get("AGNO_TEST_SANDBOX_SUBNET") else {}
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not URL or not IMAGE, reason="Enable real Postgres and runtime image"),
]


@pytest_asyncio.fixture(params=[PostgresDb, AsyncPostgresDb])
async def system(request, tmp_path):
    suffix = uuid4().hex[:12]
    db = request.param(
        db_url=URL,
        session_table="ca_sessions_" + suffix,
        runs_table="ca_runs_" + suffix,
        sandbox_table="ca_bindings_" + suffix,
    )
    provider = DockerSandbox(
        IMAGE,
        namespace="checkpoint-access-" + suffix,
        memory_mb=512,
        workspace_mb=32,
        env={"AGNO_SANDBOX_TEST_RUNTIME": "1"},
        checkpoints=FileCheckpointStore(tmp_path / "objects"),
        **SUBNET,
    )
    handles = []
    original = provider.acreate

    async def create(session_id, **kwargs):
        handle = await original(session_id, **kwargs)
        handles.append(handle)
        return handle

    provider.acreate = create  # type: ignore[method-assign]
    agent = FixtureAgent(id="coder", db=db, sandbox=provider)
    yield agent, tmp_path
    for handle in handles:
        await provider.adestroy(handle)
    store = _harness.coordinator(agent).store
    await store._transaction(lambda c: [t.drop(c) for t in (store.bindings, store.runs, store.sessions)])
    if isinstance(db, AsyncPostgresDb):
        await db.db_engine.dispose()
    else:
        db.db_engine.dispose()


def effects(opened):
    return (opened / "workspace" / "fixture-effects.txt").read_text().split()


async def test_checkpoint_store_is_the_store_the_turns_commit_to(system):
    agent, _ = system
    assert agent.checkpoint_store is agent.sandbox.checkpoints
    assert agent.checkpoint_store is _harness.coordinator(agent).transfer.store


async def test_completed_run_checkpoint_opens_and_restores(system):
    agent, root = system
    session_id = "session-" + uuid4().hex[:8]
    first = await agent.arun("first", session_id=session_id, run_id="first")
    assert first.status == RunStatus.completed

    async with agent.aopen_run_checkpoint("first") as archive:
        held = archive
        state = await CheckpointArchive().arestore(archive, root / "async")
    assert not held.exists()
    assert effects(root / "async") == ["first"]
    assert (root / "async" / "native" / "fixture-session").is_file()
    # The manifest binds the archive to the turn that captured it.
    assert (state["binding"]["run_id"], state["binding"]["session_id"], state["binding"]["agent_id"]) == (
        "first",
        session_id,
        "coder",
    )

    def sync_path():
        with agent.open_run_checkpoint("first") as archive:
            return CheckpointArchive().restore(archive, root / "sync")

    if isinstance(agent.db, AsyncPostgresDb):
        # The sync form never runs an async engine on a loop of its own.
        with pytest.raises(ValueError, match="Use aopen_run_checkpoint"):
            await asyncio.to_thread(sync_path)
    else:
        assert (await asyncio.to_thread(sync_path))["binding"]["run_id"] == "first"
        assert effects(root / "sync") == ["first"]


async def test_each_turn_opens_its_own_checkpoint(system):
    agent, root = system
    session_id = "session-" + uuid4().hex[:8]
    await agent.arun("first", session_id=session_id, run_id="first")
    second = await agent.arun("second", session_id=session_id, run_id="second")
    assert second.status == RunStatus.completed
    async with agent.aopen_run_checkpoint("second") as archive:
        await CheckpointArchive().arestore(archive, root / "second")
    assert effects(root / "second") == ["first", "second"]
    # The earlier turn's checkpoint is still the one it committed.
    async with agent.aopen_run_checkpoint("first") as archive:
        await CheckpointArchive().arestore(archive, root / "first")
    assert effects(root / "first") == ["first"]


async def test_another_agents_run_and_an_unknown_run_are_refused(system):
    agent, _ = system
    other = FixtureAgent(id="other", db=agent.db, sandbox=agent.sandbox)
    theirs = await other.arun("theirs", session_id="session-" + uuid4().hex[:8], run_id="theirs")
    assert theirs.status == RunStatus.completed
    with pytest.raises(ValueError, match="belongs to another agent"):
        async with agent.aopen_run_checkpoint("theirs"):
            pass
    with pytest.raises(ValueError, match="does not exist"):
        async with agent.aopen_run_checkpoint("never-ran"):
            pass
    async with other.aopen_run_checkpoint("theirs") as archive:
        assert archive.is_file()


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("AGNO_TEST_LIVE_REPOSITORY") != "1", reason="Set AGNO_TEST_LIVE_REPOSITORY=1")
async def test_repository_checkout_restores_under_workspace_repository(system):
    agent, root = system
    # The checkout is fetched inside the computer, so this computer needs GitHub egress.
    agent.sandbox.network = "isolated"
    engineer = FixtureAgent(
        id="engineer",
        db=agent.db,
        sandbox=agent.sandbox,
        repository=Repository("https://github.com/octocat/Hello-World", branch="master"),
    )
    pinned = await engineer.arun("pinned", session_id="session-" + uuid4().hex[:8], run_id="pinned")
    assert pinned.status == RunStatus.completed, pinned.content
    pin = pinned.metadata["sandbox"]["repository"]
    async with engineer.aopen_run_checkpoint("pinned") as archive:
        await CheckpointArchive().arestore(archive, root / "pinned")
    assert (root / "pinned" / "workspace" / "repository" / ".git").is_dir()
    assert json.loads((root / "pinned" / "native" / "repository.json").read_text()) == pin
    assert effects(root / "pinned") == ["pinned"]


async def test_running_and_cancelled_runs_are_refused(system):
    agent, _ = system
    slow = FixtureAgent(id="coder", db=agent.db, sandbox=agent.sandbox, delay=30)
    session_id = "session-" + uuid4().hex[:8]
    turn = asyncio.create_task(slow.arun("slow", session_id=session_id, run_id="slow"))
    store = _harness.coordinator(slow).store
    for _ in range(600):
        row = await store._transaction(
            lambda c: c.execute(select(store.runs.c.status).where(store.runs.c.run_id == "slow")).scalar()
        )
        if row == "RUNNING":
            break
        await asyncio.sleep(0.1)
    assert row == "RUNNING"
    with pytest.raises(ValueError, match="RUNNING, not COMPLETED"):
        async with slow.aopen_run_checkpoint("slow"):
            pass
    assert await slow.acancel_run("slow")
    # Cancelling from outside the turn fences its lease, so the awaiting caller sees the cancellation.
    with pytest.raises(RunCancelledException):
        await turn
    status = await store._transaction(
        lambda c: c.execute(select(store.runs.c.status).where(store.runs.c.run_id == "slow")).scalar()
    )
    assert status == "CANCELLED"
    with pytest.raises(ValueError, match="CANCELLED, not COMPLETED"):
        async with slow.aopen_run_checkpoint("slow"):
            pass
