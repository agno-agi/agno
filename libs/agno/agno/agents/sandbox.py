"""AgentOS control-plane entry for a session-bound harness sandbox."""

import asyncio
import hashlib
import hmac
import json
import os
from contextlib import suppress
from dataclasses import asdict, dataclass, field, fields
from time import monotonic
from typing import Any, AsyncIterator, Dict, Optional
from uuid import uuid4

import httpx

from agno.agents.base import BaseExternalAgent
from agno.exceptions import RunCancelledException
from agno.run.agent import CustomEvent, RunOutput, run_output_event_from_dict
from agno.run.base import RunStatus
from agno.sandbox.base import SandboxProvider, SandboxSpec, _sync
from agno.sandbox.registry import _SandboxRegistry
from agno.sandbox.workspace import GitWorkspace
from agno.utils.log import log_error


class _ForwardedSandboxEvent(CustomEvent):
    """Preserve arbitrary JSON fields on runtime warnings and stream diagnostics."""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class SandboxAgent(BaseExternalAgent):
    """Execute harness turns outside AgentOS; requires a shared Postgres durable queue.

    ``runtime_db_url`` and ``runtime_redis_url`` are the addresses reachable from
    the sandbox network. Every API replica needs the same ``token_secret``. The
    sandbox receives only its derived token, never the shared signing secret.
    Direct storage credentials assume a trusted customer deployment.
    """

    provider: Optional[SandboxProvider] = None
    image: str = "agno-sandbox:latest"
    harness: str = "claude"
    harness_config: Dict[str, Any] = field(default_factory=dict)
    workspace: Optional[GitWorkspace] = None
    runtime_db_url: Optional[str] = field(default=None, repr=False)
    runtime_redis_url: Optional[str] = field(default=None, repr=False)
    token_secret: Optional[str] = field(default=None, repr=False)
    runtime_env: Dict[str, str] = field(default_factory=dict, repr=False)
    runtime_command: Optional[list[str]] = None
    idle_timeout: int = 900
    memory: str = "2g"
    cpus: float = 2.0
    pids_limit: int = 512
    startup_timeout: int = 120
    sweep_interval: float = 5
    _worker: Any = field(default=None, init=False, repr=False)
    _sweeper: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.framework = self.harness
        if self.provider is None:
            raise ValueError("SandboxAgent requires a provider")
        if self.harness not in ("claude", "codex"):
            raise ValueError("Supported sandbox harnesses are claude and codex")
        if self.cpus <= 0 or self.pids_limit <= 0:
            raise ValueError("Sandbox CPU and PID limits must be positive")
        if self.idle_timeout < 1 or self.startup_timeout < 1 or self.sweep_interval <= 0:
            raise ValueError("Sandbox timeouts must be positive")

    @property
    def _registry(self) -> _SandboxRegistry:
        return _SandboxRegistry(self.db)

    def _token(self, row: Dict[str, Any]) -> str:
        secret = self.token_secret or os.environ.get("AGNO_SANDBOX_SECRET", "")
        if len(secret) < 32:
            raise ValueError("AGNO_SANDBOX_SECRET/token_secret must contain at least 32 characters")
        message = json.dumps(
            [row["sandbox_id"], row["generation"], row["agent_id"], row["session_id"], row.get("user_id")]
        )
        return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    async def _astart(self, worker: Any) -> None:
        from agno.db.postgres import AsyncPostgresDb, PostgresDb

        if not isinstance(self.db, (PostgresDb, AsyncPostgresDb)):
            raise ValueError("SandboxAgent requires PostgresDb or AsyncPostgresDb")
        if getattr(worker.store, "_store", worker.store) is not self.db:
            raise ValueError("SandboxAgent requires the queue and sessions to use the same database instance")
        if not worker.config.redis:
            raise ValueError("SandboxAgent requires shared Redis coordination")
        self._worker = worker
        # Fail before accepting requests when credentials or storage are misconfigured.
        self._token(dict(sandbox_id="probe", generation=1, agent_id=self.id, session_id="probe"))
        await self._registry.list(self.get_id())
        self._sweeper = asyncio.create_task(self._sweep_loop())

    async def _astop(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
            with suppress(asyncio.CancelledError):
                await self._sweeper
            self._sweeper = None
        # API shutdown never destroys session sandboxes.
        self._worker = None

    def _spec(self, row: Dict[str, Any], worker: Any) -> SandboxSpec:
        queue = {
            item.name: getattr(worker.config, item.name)
            for item in fields(worker.config)
            if item.name not in ("db", "redis")
        }
        redis = worker.config.redis
        redis_url = self.runtime_redis_url or (redis if isinstance(redis, str) else redis.url)
        if not redis_url:
            raise ValueError("A Redis URL reachable from the sandbox is required")
        from sqlalchemy.engine import make_url

        from agno.db.postgres import AsyncPostgresDb, PostgresDb

        assert isinstance(self.db, (PostgresDb, AsyncPostgresDb))
        database_url = make_url(self.runtime_db_url or self.db.db_engine.url.render_as_string(hide_password=False))
        # The runtime uses the sync adapter, whose queue heartbeat has its own thread.
        database_url = database_url.set(drivername="postgresql+psycopg")
        database = dict(
            db_url=database_url.render_as_string(hide_password=False),
            db_schema=self.db.db_schema,
            id=self.db.id,
            session_table=self.db.session_table_name,
            runs_table=self.db.runs_table_name,
            job_table=self.db.job_table_name,
        )
        binding = {key: row[key] for key in ("sandbox_id", "generation", "agent_id", "session_id", "user_id")}
        config = dict(
            binding=binding,
            database=database,
            queue=queue,
            redis={"url": redis_url, "key_prefix": getattr(redis, "key_prefix", None)},
            executor_id=self._executor_id(row),
            harness=self.harness,
            harness_config=self.harness_config,
            workspace=asdict(self.workspace) if self.workspace else None,
        )
        env = {**self.runtime_env, "AGNO_RUNTIME_CONFIG": json.dumps(config), "AGNO_RUNTIME_TOKEN": self._token(row)}
        options: Dict[str, Any] = {}
        if self.runtime_command is not None:
            options["command"] = self.runtime_command
        return SandboxSpec(
            row["sandbox_id"],
            row["generation"],
            self.image,
            env=env,
            memory=self.memory,
            cpus=self.cpus,
            pids_limit=self.pids_limit,
            **options,
        )

    @staticmethod
    def _executor_id(row: Dict[str, Any]) -> str:
        return f"sandbox-{row['sandbox_id']}-{row['generation']}"

    async def _create(self, row: Dict[str, Any], worker: Any) -> None:
        assert self.provider is not None
        spec = self._spec(row, worker)
        handle = await self.provider.acreate(spec)
        deadline = monotonic() + self.startup_timeout
        async with httpx.AsyncClient(timeout=5, trust_env=False) as client:
            while monotonic() < deadline:
                try:
                    response = await client.get(handle.url + "/health")
                    if response.status_code == 200:
                        await self._registry.replace(
                            row, status="ready", url=handle.url, provider_ref=handle.provider_ref
                        )
                        return
                except httpx.HTTPError:
                    pass
                observed = await self.provider.aget(handle.provider_ref)
                if observed is None or observed.status != "running":
                    raise RuntimeError(observed.reason if observed else "Sandbox disappeared during startup")
                await asyncio.sleep(0.25)
        raise TimeoutError("Sandbox runtime readiness timed out")

    async def _resolve(self, job: Dict[str, Any], worker: Any) -> Dict[str, Any]:
        assert self.provider is not None
        deadline = monotonic() + self.startup_timeout + worker.config.lock_grace_seconds
        while monotonic() < deadline:
            from agno.run.cancel import araise_if_cancelled

            await araise_if_cancelled(job["id"])
            row = await self._registry.get(session_id=job["session_id"])
            if row is None:
                row = dict(
                    sandbox_id=str(uuid4()),
                    session_id=job["session_id"],
                    agent_id=self.get_id(),
                    user_id=job.get("user_id"),
                    provider=self.provider.name,
                    status="creating",
                    generation=1,
                    active_run_id=job["id"],
                    active_attempt=job["attempt"],
                    metadata={},
                )
                row["provider_ref"] = SandboxSpec(row["sandbox_id"], 1, self.image).name
                if await self._registry.insert(row):
                    row = await self._registry.get(session_id=job["session_id"])
                    assert row is not None
                    await self._create(row, worker)
                continue
            if (row["agent_id"], row.get("user_id")) != (self.get_id(), job.get("user_id")):
                raise PermissionError("Sandbox session belongs to another agent or user")
            if row["metadata"].get("session_deleted"):
                raise ValueError("The sandbox session has been deleted")
            if row["status"] == "creating":
                if row["db_now"] - row["updated_at"] > self.startup_timeout + 30:
                    if await self._registry.replace(row):
                        row = await self._registry.get(session_id=job["session_id"])
                        assert row is not None
                        await self._create(row, worker)
                else:
                    await asyncio.sleep(0.2)
                continue
            if row["status"] in ("destroyed", "error"):
                # Remove the prior execution environment before a new generation can write.
                handle = await self.provider.aget(row["provider_ref"]) if row.get("provider_ref") else None
                if handle:
                    await self.provider.adestroy(handle)
                generation = row["generation"] + 1
                if await self._registry.replace(
                    row,
                    status="creating",
                    generation=generation,
                    url=None,
                    provider_ref=SandboxSpec(row["sandbox_id"], generation, self.image).name,
                    active_run_id=job["id"],
                    active_attempt=job["attempt"],
                ):
                    row = await self._registry.get(session_id=job["session_id"])
                    assert row is not None
                    await self._create(row, worker)
                continue
            if row["status"] != "ready":
                await asyncio.sleep(0.2)
                continue
            handle = await self.provider.aget(row["provider_ref"])
            if handle is None or handle.status != "running":
                await self._registry.replace(
                    row,
                    status="error",
                    metadata={**row["metadata"], "error": handle.reason if handle else "Sandbox container disappeared"},
                )
                continue
            active = row.get("active_run_id")
            if active == job["id"] and row.get("active_attempt") != job["attempt"]:
                # A stale lease was reclaimed. Terminate the previous executor before retrying.
                if await self._registry.replace(row, status="error"):
                    continue
            elif active in (None, job["id"]):
                if active == job["id"] or await self._registry.replace(
                    row, active_run_id=job["id"], active_attempt=job["attempt"]
                ):
                    resolved = await self._registry.get(session_id=job["session_id"])
                    assert resolved is not None
                    return resolved
            else:
                # Waiting for another turn is queueing, not a sandbox startup failure.
                deadline = monotonic() + self.startup_timeout + worker.config.lock_grace_seconds
            await asyncio.sleep(0.2)
        raise TimeoutError("Session sandbox is busy or unavailable")

    async def adispatch_claimed_job(self, job: Dict[str, Any], worker: Any) -> None:
        from agno.agent.remote import RemoteAgent

        try:
            row = await self._resolve(job, worker)
            remote = RemoteAgent(row["url"], agent_id=self.get_id(), timeout=15)
            for attempt in range(3):
                try:
                    await remote.arun(
                        "",
                        stream=False,
                        session_id=job["session_id"],
                        run_id=job["id"],
                        attempt=job["attempt"],
                        worker_id=worker.worker_id,
                        auth_token=self._token(row),
                    )
                    return
                except (httpx.HTTPError, TimeoutError):
                    current = await worker.store.get_job(job["id"], strict=True)
                    if current and (
                        current.get("locked_by") == self._executor_id(row)
                        or current["status"] in ("completed", "failed", "cancelled")
                    ):
                        return
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.2)
        except RunCancelledException:
            from agno.run.base import CancellationStage

            # Resolution has not sent a dispatch yet. Preserve row-first cancellation
            # so a storage failure leaves a live claim for the normal lease reconciler.
            if await worker._persist_run_error(
                job,
                "Cancelled while waiting for the session sandbox",
                status="cancelled",
                cancellation_stage=CancellationStage.pending,
            ) and await worker._asettle_ticket(job["id"], job["attempt"], "cancelled"):
                await worker._terminate_stream_view(job, status="cancelled")
                cancelled_row = await self._registry.get(session_id=job["session_id"])
                if cancelled_row and (cancelled_row.get("active_run_id"), cancelled_row.get("active_attempt")) == (
                    job["id"],
                    job["attempt"],
                ):
                    await self._registry.replace(cancelled_row, active_run_id=None, active_attempt=None)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # A delayed dispatch may still be arriving. Settlement's owner/attempt
            # CAS arbitrates with handoff; never declare failure after transfer.
            current = await worker.store.get_job(job["id"], strict=True)
            if current and (current.get("locked_by"), current.get("attempt")) == (worker.worker_id, job["attempt"]):
                reason = f"Sandbox dispatch failed: {type(error).__name__}"
                # Do not race a remote writer's run row. Leave terminal persistence
                # to the exhausted-lease sweeper; record the diagnostic in registry.
                failed_row = await self._registry.get(session_id=job["session_id"])
                if failed_row and (failed_row["agent_id"], failed_row.get("user_id")) == (
                    self.get_id(),
                    job.get("user_id"),
                ):
                    await self._registry.replace(failed_row, metadata={**failed_row["metadata"], "error": reason})
            raise

    def dispatch_claimed_job(self, job: Dict[str, Any], worker: Any) -> None:
        _sync(self.adispatch_claimed_job(job, worker))

    def arun(
        self,
        input: Any,
        *,
        stream: Optional[bool] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        background: bool = False,
        **kwargs: Any,
    ) -> Any:
        if stream:
            return self._submit_stream(input, session_id, user_id, background, kwargs)
        return self._submit(input, session_id, user_id, background, False, kwargs)

    async def _arun_non_stream(self, input: Any, **kwargs: Any) -> RunOutput:
        return await self._submit(
            input, kwargs.pop("session_id", None), kwargs.pop("user_id", None), False, False, kwargs
        )

    async def _arun_stream(self, input: Any, **kwargs: Any) -> AsyncIterator[Any]:
        async for event in self._submit_stream(
            input, kwargs.pop("session_id", None), kwargs.pop("user_id", None), False, kwargs
        ):
            yield event

    async def _submit(
        self,
        input: Any,
        session_id: Optional[str],
        user_id: Optional[str],
        background: bool,
        stream: bool,
        kwargs: Dict[str, Any],
    ) -> RunOutput:
        from agno.db.schemas.jobs import QueuedJob
        from agno.os.event_streams import get_event_stream
        from agno.os.job_queue import aprepare_accepted_or_abort, payload_is_queueable

        worker = self._worker
        if worker is None:
            raise RuntimeError("SandboxAgent requires a running AgentOS with QueueConfig(durable=True)")
        kwargs = {
            k: v
            for k, v in kwargs.items()
            if k not in ("background_tasks", "run_id", "yield_run_output") and v is not None
        }
        payload = dict(input=input, stream=stream, kwargs=kwargs)
        if not payload_is_queueable(payload):
            raise ValueError("Sandbox runs require JSON-serializable inputs")
        session_id = session_id or str(uuid4())
        binding = await self._registry.get(session_id=session_id)
        if binding and binding["metadata"].get("session_deleted"):
            raise ValueError("The sandbox session has been deleted")
        run_id = str(uuid4())
        job = QueuedJob(
            id=run_id,
            component_type="agent",
            component_id=self.get_id(),
            session_id=session_id,
            user_id=user_id,
            payload=payload,
            max_attempts=worker.config.max_attempts,
            deployment_id=worker.config.deployment_id,
        ).to_dict()
        result = await worker.store.enqueue_job(job, max_depth=worker.config.max_queue_depth)
        if not result["accepted"]:
            raise RuntimeError("Sandbox run queue is full")
        await aprepare_accepted_or_abort(worker, self, "agent", run_id, session_id, user_id, input)
        if stream:
            await get_event_stream().register_run(run_id, RunStatus.pending)
        if background:
            return RunOutput(
                run_id=run_id, session_id=session_id, user_id=user_id, agent_id=self.get_id(), status=RunStatus.pending
            )
        while True:
            job = await worker.store.get_job(run_id, strict=True)
            if job and job["status"] in ("completed", "failed", "cancelled"):
                run = await self.aget_run_output(run_id, session_id, user_id)
                if run:
                    return run
            await asyncio.sleep(0.2)

    async def _submit_stream(
        self, input: Any, session_id: Optional[str], user_id: Optional[str], background: bool, kwargs: Dict[str, Any]
    ) -> AsyncIterator[Any]:
        from agno.os.utils import queued_run_tail_streamer

        run = await self._submit(input, session_id, user_id, True, True, kwargs)
        assert run.run_id is not None
        async for frame in queued_run_tail_streamer(run.run_id, from_index=-1):
            if background:
                yield frame
            else:
                for line in frame.splitlines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if data.get("event") == "CustomEvent":
                            yield _ForwardedSandboxEvent(**data)
                        else:
                            try:
                                yield run_output_event_from_dict(data)
                            except ValueError:
                                yield _ForwardedSandboxEvent(**data)

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await self._sweep()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log_error(f"Sandbox reconciliation failed: {type(error).__name__}")
            await asyncio.sleep(self.sweep_interval)

    async def _failure_reason(self, job: Dict[str, Any]) -> Optional[str]:
        row = await self._registry.get(session_id=job["session_id"])
        return row["metadata"].get("error") if row else None

    async def _sweep(self) -> None:
        assert self.provider is not None
        for row in await self._registry.list(self.get_id()):
            if row["status"] == "creating":
                if row["db_now"] - row["updated_at"] > self.startup_timeout + 30:
                    await self._registry.replace(
                        row, status="error", metadata={**row["metadata"], "error": "Sandbox creation lease expired"}
                    )
                continue
            if row["status"] == "destroying":
                await self.adestroy_sandbox(row["sandbox_id"], expected_revision=row["revision"])
                continue
            if row["status"] not in ("ready", "error"):
                continue
            handle = await self.provider.aget(row["provider_ref"]) if row.get("provider_ref") else None
            gone = handle is None or handle.status != "running"
            if gone:
                reason = handle.reason if handle else "Sandbox container disappeared"
                if row.get("active_run_id"):
                    job = await self._worker.store.get_job(row["active_run_id"], strict=True)
                    if (
                        job
                        and job["status"] == "running"
                        and job.get("attempt") == row.get("active_attempt")
                        and job.get("locked_by") == self._executor_id(row)
                    ):
                        # The provider confirmed the executor is gone. Record its
                        # failure now; the queue lease still arbitrates retry/settlement.
                        await self._worker._persist_run_error(job, reason)
                if row["status"] != "error":
                    await self._registry.replace(row, status="error", metadata={**row["metadata"], "error": reason})
                    continue
            if row.get("active_run_id"):
                job = await self._worker.store.get_job(row["active_run_id"], strict=True)
                if gone and job and job["status"] in ("failed", "cancelled", "completed"):
                    await self._registry.replace(row, active_run_id=None, active_attempt=None)
                continue
            if row["metadata"].get("checkpoint_error"):
                continue
            if gone or row["db_now"] - row["last_active_at"] >= self.idle_timeout:
                await self.adestroy_sandbox(row["sandbox_id"], expected_revision=row["revision"])

    async def adestroy_sandbox(
        self,
        sandbox_id: str,
        *,
        user_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
        delete_session: bool = False,
    ) -> bool:
        assert self.provider is not None
        row = await self._registry.get(sandbox_id=sandbox_id)
        if row is None or row["agent_id"] != self.get_id() or (user_id is not None and row.get("user_id") != user_id):
            return False
        if row.get("active_run_id"):
            raise ValueError("Cancel the active run before destroying its sandbox")
        if expected_revision is not None and row["revision"] != expected_revision:
            return False
        metadata = {**row["metadata"]}
        if delete_session:
            # Retain an ownership tombstone so queued requests cannot resurrect a deleted session.
            metadata["session_deleted"] = True
        if not await self._registry.replace(row, status="destroying", metadata=metadata):
            return False
        row = await self._registry.get(sandbox_id=sandbox_id)
        assert row is not None
        handle = await self.provider.aget(row["provider_ref"]) if row.get("provider_ref") else None
        if handle:
            await self.provider.adestroy(handle)
        return await self._registry.replace(row, status="destroyed", url=None)

    def destroy_sandbox(
        self,
        sandbox_id: str,
        *,
        user_id: Optional[str] = None,
        expected_revision: Optional[int] = None,
        delete_session: bool = False,
    ) -> bool:
        return _sync(
            self.adestroy_sandbox(
                sandbox_id, user_id=user_id, expected_revision=expected_revision, delete_session=delete_session
            )
        )
