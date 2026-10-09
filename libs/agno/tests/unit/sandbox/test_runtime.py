import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import pytest

from agno.agents.base import BaseExternalAgent
from agno.db.schemas.jobs import QueuedJob
from agno.db.sqlite import SqliteDb
from agno.job_queue.store import InMemoryQueueStore
from agno.run.agent import RunContentEvent
from agno.sandbox.runtime import create_runtime_app
from agno.sandbox.workspace import GitWorkspace


@dataclass
class ControlledAgent(BaseExternalAgent):
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    executions: int = 0

    async def _arun_adapter(self, input, **kwargs):
        self.executions += 1
        self.started.set()
        await self.release.wait()
        return "finished"

    async def _arun_adapter_stream(self, input, **kwargs):
        result = await self._arun_adapter(input, **kwargs)
        yield RunContentEvent(content=result, run_id=kwargs["run_id"])


@pytest.mark.asyncio
async def test_runtime_scope_duplicate_ack_and_single_execution(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "runtime.db"))
    store = InMemoryQueueStore()
    binding = dict(sandbox_id=str(uuid4()), generation=1, session_id="session", agent_id="coder", user_id="owner")
    assert db.upsert_sandbox(
        {
            **binding,
            "provider": "docker",
            "status": "ready",
            "metadata": {},
            "active_run_id": "run",
            "active_attempt": 1,
        }
    )
    job = QueuedJob(
        id="run",
        component_id="coder",
        component_type="agent",
        session_id="session",
        user_id="owner",
        payload={"input": "test", "stream": True},
    ).to_dict()
    await store.enqueue_job(job)
    await store.claim_job("api-a")
    agent = ControlledAgent(id="coder", db=db)
    config = dict(
        binding=binding,
        token="bound-token",
        executor_id="sandbox-owner",
        queue={"db": store, "durable": True, "lock_grace_seconds": 6, "stop_timeout_seconds": 1},
    )
    app = create_runtime_app(config, agent=agent, db=db)
    data = dict(run_id="run", attempt=1, worker_id="api-a", session_id="session")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://runtime") as client:
            assert (await client.post("/agents/coder/runs", data=data)).status_code == 401
            headers = {"Authorization": "Bearer bound-token"}
            assert (await client.post("/agents/wrong/runs", data=data, headers=headers)).status_code == 403
            assert (
                await client.post("/agents/coder/runs", data={**data, "session_id": "wrong"}, headers=headers)
            ).status_code == 403
            assert (
                await client.post("/agents/coder/runs", data={**data, "attempt": 2}, headers=headers)
            ).status_code == 409
            assert (await client.post("/agents/coder/runs", data=data, headers=headers)).status_code == 202
            await asyncio.wait_for(agent.started.wait(), 2)
            assert (await client.post("/agents/coder/runs", data=data, headers=headers)).status_code == 202
            assert agent.executions == 1
            assert (await store.get_job("run"))["locked_by"] == "sandbox-owner"
            agent.release.set()
            for _ in range(50):
                if (await store.get_job("run"))["status"] == "completed":
                    break
                await asyncio.sleep(0.02)
            assert (await store.get_job("run"))["status"] == "completed"
            assert (await agent.aget_run_output("run", "session")).content == "finished"
    db.db_engine.dispose()


@pytest.mark.asyncio
async def test_workspace_checkpoint_restores_files_after_deletion(tmp_path):
    import shutil
    import subprocess

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("initial\n")
    for args in (
        ["add", "."],
        ["-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "Initial"],
        ["remote", "add", "origin", str(remote)],
        ["push", "origin", "main"],
    ):
        subprocess.run(["git", "-C", str(seed), *args], check=True, capture_output=True)
    workspace = GitWorkspace(repo=str(remote))
    first = tmp_path / "first"
    await workspace.aon_create(first, "session")
    (first / "code.py").write_text("answer = 42\n")
    checkpoint = await workspace.acheckpoint(first, "session")
    assert checkpoint
    (first / "uncheckpointed.py").write_text("lost\n")
    shutil.rmtree(first)
    second = tmp_path / "second"
    assert await workspace.aon_create(second, "session") == checkpoint
    assert (second / "code.py").read_text() == "answer = 42\n"
    assert not (second / "uncheckpointed.py").exists()
