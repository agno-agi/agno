"""Bound sandbox executor. Start with ``python -m agno.sandbox.runtime``.

Only the control plane submits requests. The authenticated request identifies a
queue claim; its input and owner are loaded from Postgres rather than trusting an
HTTP payload. This runtime never polls the queue for unrelated sessions.
"""

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Form, Header, HTTPException

from agno.agents.base import BaseExternalAgent
from agno.job_queue import QueueConfig, RedisCoordination
from agno.os.job_queue import QueueWorker, apply_queue_config, resolve_queue_store, resolve_stop_timeout
from agno.sandbox.registry import _SandboxRegistry
from agno.sandbox.workspace import GitWorkspace


def create_runtime_app(config: Dict[str, Any], agent: Optional[BaseExternalAgent] = None, db: Any = None) -> FastAPI:
    if db is None:
        from agno.db.postgres import PostgresDb

        db = PostgresDb(**config["database"])
    binding = config["binding"]
    registry = _SandboxRegistry(db)
    queue_config = QueueConfig(**config.get("queue", {}))
    queue_config.durable = True
    if config.get("redis"):
        queue_config.redis = RedisCoordination(**config["redis"])
    apply_queue_config(queue_config)
    if agent is None:
        harness = config["harness"]
        harness_config = dict(config.get("harness_config", {}))
        # Identity and persistence cannot be overridden by adapter configuration.
        for key in ("id", "db", "name"):
            harness_config.pop(key, None)
        harness_config["cwd"] = config.get("workspace_path", "/workspace")
        if harness == "claude":
            from agno.agents.claude import ClaudeAgent

            agent = ClaudeAgent(id=binding["agent_id"], db=db, **harness_config)
        elif harness == "codex":
            from agno.agents.codex import CodexAgent

            harness_config.setdefault("approval_mode", "deny_all")
            agent = CodexAgent(id=binding["agent_id"], db=db, **harness_config)
        else:
            raise ValueError("Supported runtime harnesses are claude and codex")
    if not config.get("token"):
        raise ValueError("A runtime bearer token is required")
    store = resolve_queue_store(queue_config, db)
    worker = QueueWorker(
        store,
        lambda kind, identifier: agent if kind == "agent" and identifier == binding["agent_id"] else None,
        queue_config,
        worker_id=config["executor_id"],
        stop_timeout=resolve_stop_timeout(queue_config),
    )
    lock = asyncio.Lock()
    workspace = GitWorkspace(**config["workspace"]) if config.get("workspace") else None
    workspace_path = Path(config.get("workspace_path", "/workspace"))
    finalizers: set[asyncio.Task] = set()
    ready = False

    async def finish(job: Dict[str, Any], task: asyncio.Task) -> None:
        try:
            await task
        except (Exception, asyncio.CancelledError):
            pass
        checkpoint, checkpoint_error = None, None
        if workspace is not None:
            try:
                checkpoint = await workspace.acheckpoint(workspace_path, binding["session_id"])
            except Exception:
                checkpoint_error = "Workspace checkpoint failed; workspace retained until a checkpoint succeeds"
        for _ in range(10):
            row = await registry.get(sandbox_id=binding["sandbox_id"])
            if row is None or row["generation"] != binding["generation"]:
                return
            if (row.get("active_run_id"), row.get("active_attempt")) != (job["id"], job["attempt"]):
                return
            metadata = {**row["metadata"], "checkpoint_error": checkpoint_error}
            if checkpoint:
                metadata["checkpoint"] = checkpoint
            if await registry.replace(
                row, active_run_id=None, active_attempt=None, last_active_at=row["db_now"], metadata=metadata
            ):
                return

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal ready
        if workspace:
            await workspace.aon_create(workspace_path, binding["session_id"])
        await worker.start(claim_jobs=False)
        ready = True
        try:
            yield
        finally:
            ready = False
            await worker.stop()
            if finalizers:
                await asyncio.gather(*finalizers, return_exceptions=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health() -> Dict[str, str]:
        if not ready:
            raise HTTPException(503, "Runtime is not ready")
        return {"status": "ready"}

    @app.post("/agents/{agent_id}/runs", status_code=202)
    async def dispatch(
        agent_id: str,
        run_id: str = Form(...),
        attempt: int = Form(...),
        worker_id: str = Form(...),
        session_id: str = Form(...),
        authorization: Optional[str] = Header(None),
    ) -> Dict[str, Any]:
        expected = "Bearer " + config["token"]
        if not hmac.compare_digest(authorization or "", expected):
            raise HTTPException(401, "Invalid runtime token")
        if agent_id != binding["agent_id"] or session_id != binding["session_id"]:
            raise HTTPException(403, "Runtime session binding mismatch")
        async with lock:
            row = await registry.get(sandbox_id=binding["sandbox_id"])
            if row is None or row["generation"] != binding["generation"] or row["status"] != "ready":
                raise HTTPException(409, "Sandbox generation is no longer active")
            job = await store.get_job(run_id)
            if job is None or (job["component_id"], job["session_id"], job.get("user_id")) != (
                binding["agent_id"],
                binding["session_id"],
                binding.get("user_id"),
            ):
                raise HTTPException(403, "Queue claim binding mismatch")
            if job["attempt"] != attempt or job.get("payload", {}).get("continue"):
                raise HTTPException(409, "Stale or unsupported queue claim")
            existing = worker._in_flight.get(run_id)
            if existing is not None and job.get("locked_by") == worker.worker_id:
                return {"run_id": run_id, "session_id": session_id, "status": "RUNNING"}
            if (row.get("active_run_id"), row.get("active_attempt")) != (run_id, attempt):
                raise HTTPException(409, "Session is reserved by another execution")
            if not await store.handoff_job(run_id, worker_id, attempt, worker.worker_id):
                raise HTTPException(409, "Queue claim is no longer owned by dispatcher")
            # No await between committed handoff and task registration. A process
            # crash in this window is recovered through the same durable lease.
            job["locked_by"] = worker.worker_id
            task = worker._execute_handed_off(job)
            finalizer = asyncio.create_task(finish(job, task))
            finalizers.add(finalizer)
            finalizer.add_done_callback(finalizers.discard)
            return {"run_id": run_id, "session_id": session_id, "status": "PENDING"}

    app.state.sandbox_worker = worker
    return app


def serve() -> None:
    import uvicorn

    config = json.loads(os.environ["AGNO_RUNTIME_CONFIG"])
    config["token"] = os.environ["AGNO_RUNTIME_TOKEN"]
    os.environ.setdefault("CLAUDE_CONFIG_DIR", "/tmp/claude")
    os.environ.setdefault("CODEX_HOME", "/tmp/codex")
    uvicorn.run(create_runtime_app(config), host="0.0.0.0", port=7777, access_log=False)


if __name__ == "__main__":
    serve()
