"""Run a harness agent's whole process inside its session's sandbox computer.

ClaudeAgent(sandbox=...) and CodexAgent(sandbox=...) delegate their run, background,
cancel and queue-terminal paths here. The coordinator is built from the agent's
PostgresDb and its sandbox on first use.
"""

from __future__ import annotations

import json
import os
import time
import weakref
from dataclasses import MISSING, asdict, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Tuple
from uuid import uuid4

from agno.models.message import Message
from agno.run.agent import RunInput, RunOutput
from agno.run.base import RunStatus
from agno.sandbox.base import Sandbox, SandboxError
from agno.utils.log import log_error, log_warning

if TYPE_CHECKING:
    from agno.agents.base import BaseExternalAgent
    from agno.sandbox.checkpoint import CheckpointStore
    from agno.sandbox.coordinator import SandboxCoordinator

# The runtime sets these inside the sandbox, so the service-side values are not sent.
_RUNTIME_OWNED = frozenset(
    {
        "id",
        "db",
        "sandbox",
        "output_schema",
        "store_events",
        "events_to_skip",
        "require_native_resume",
        "strict_persistence",
        "delay_between_retries",
        "exponential_backoff",
    }
)
# Host paths, process settings and native option objects have no meaning inside the sandbox.
_HOST_ONLY = frozenset(
    {
        "cwd",
        "keep_uploads",
        "retries",
        "codex_bin",
        "env",
        "options",
        "options_kwargs",
        "client_options",
        "thread_kwargs",
    }
)
# Model credentials forwarded from the host unless the sandbox's env sets them. Claude Code
# authenticates with either an API key or a Claude Code OAuth token.
_HARNESS_ENV_KEYS = {"claude": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"), "codex": ("OPENAI_API_KEY",)}
_CLAUDE_CLOUD_FLAGS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
_DEFAULT_CHECKPOINTS = Path.home() / ".agno" / "sandbox" / "checkpoints"

_coordinators: "weakref.WeakKeyDictionary[Sandbox, List[Tuple[Any, SandboxCoordinator]]]" = weakref.WeakKeyDictionary()


def _is_default(item: Any, value: Any) -> bool:
    if item.default is not MISSING:
        return value == item.default
    if item.default_factory is not MISSING:
        return value == item.default_factory()
    return False


def _sandbox(agent: "BaseExternalAgent") -> Sandbox:
    if agent.sandbox is None:
        raise SandboxError(f"{type(agent).__name__} has no sandbox")
    return agent.sandbox


def _check_db(agent: "BaseExternalAgent") -> None:
    from agno.db.postgres import AsyncPostgresDb, PostgresDb

    if not isinstance(agent.db, (PostgresDb, AsyncPostgresDb)):
        raise ValueError("A sandboxed agent requires a PostgresDb or AsyncPostgresDb, on the agent or its AgentOS")


async def acheck_tables(agent: "BaseExternalAgent", create: bool = True) -> None:
    """Validate the sandbox tables on the agent's database, creating them first unless ``create`` is off.

    A bindings table left by another build fails every turn inside the queue worker, where
    only the log sees it; checking at startup and at submission puts the error and its
    remedy in front of the operator instead.
    """
    from agno.sandbox.postgres import _SandboxStore

    _check_db(agent)
    for db, existing in _coordinators.get(_sandbox(agent), []):
        if db is agent.db:
            await existing.store._ensure_tables(create)
            return
    await _SandboxStore(agent.db)._ensure_tables(create)  # type: ignore[arg-type]


def validate(agent: "BaseExternalAgent") -> None:
    """Reject settings a sandboxed turn cannot honour, at construction."""
    if not isinstance(agent.sandbox, Sandbox):
        raise TypeError(
            f"sandbox= takes a Sandbox such as DockerSandbox(image), not {type(agent.sandbox).__name__}"
            + ("; CodexAgent's permission policy is sandbox_mode" if isinstance(agent.sandbox, str) else "")
        )
    sandbox = _sandbox(agent)
    runtime = agent._sandbox_runtime
    if runtime is None:
        raise ValueError(f"{type(agent).__name__} cannot run in a sandbox")
    if runtime == "fixture" and (sandbox.env or {}).get("AGNO_SANDBOX_TEST_RUNTIME") != "1":
        raise ValueError("The fixture harness requires explicit test-runtime opt-in")
    if agent.db is not None:
        _check_db(agent)
    if runtime in _HARNESS_ENV_KEYS and getattr(sandbox, "network", None) == "none":
        log_warning(
            f"{type(agent).__name__} cannot reach its model API from a sandbox with network='none'; "
            "use network='isolated'"
        )
    submission(agent, "validate", {})


def store(agent: "BaseExternalAgent") -> "CheckpointStore":
    """The checkpoint store this agent's turns write to: the sandbox's own, else the file default.

    A coordinator already built for this agent's sandbox and database owns the answer, so a
    reader opens exactly the store its turns commit to.
    """
    sandbox = _sandbox(agent)
    for db, existing in _coordinators.get(sandbox, []):
        if db is agent.db:
            return existing.transfer.store
    if sandbox.checkpoints is not None:
        return sandbox.checkpoints
    from agno.os.job_queue import get_active_queue_worker
    from agno.sandbox.checkpoint import FileCheckpointStore

    if get_active_queue_worker() is not None:
        # A durable queue hands retries to any replica, and a replica cannot restore from this
        # host's disk; refusing here is cheaper than a recovery that fails later somewhere else.
        raise ValueError(
            f"Sandbox checkpoints default to {_DEFAULT_CHECKPOINTS}, which other queue replicas cannot "
            "read and which does not survive losing this host; pass checkpoints= to the sandbox"
        )
    log_warning(
        f"Sandbox checkpoints default to {_DEFAULT_CHECKPOINTS}; pass checkpoints= to the sandbox before "
        "running more than one host"
    )
    return FileCheckpointStore(_DEFAULT_CHECKPOINTS)


def coordinator(agent: "BaseExternalAgent") -> "SandboxCoordinator":
    """The coordinator for this agent's sandbox and database, built once per pair."""
    from agno.sandbox.coordinator import SandboxCoordinator

    sandbox = _sandbox(agent)
    _check_db(agent)
    built = _coordinators.setdefault(sandbox, [])
    for db, existing in built:
        if db is agent.db:
            return existing
    result = SandboxCoordinator(agent.db, sandbox, sandbox.checkpoint_transfer(store(agent)))  # type: ignore[arg-type]
    built.append((agent.db, result))
    return result


def env(agent: "BaseExternalAgent") -> Dict[str, str]:
    runtime = agent._sandbox_runtime or ""
    configured = dict(_sandbox(agent).env or {})
    if agent.repository is not None and "GITHUB_TOKEN" in configured:
        raise ValueError("Sandbox repository access requires GITHUB_READ_TOKEN; remove GITHUB_TOKEN")
    # Claude Code on Bedrock or Vertex authenticates with cloud credentials, so a host key
    # would go unused while agent code inside the sandbox could still read it.
    if runtime == "claude" and any(configured.get(flag) for flag in _CLAUDE_CLOUD_FLAGS):
        return configured
    values = {key: os.environ[key] for key in _HARNESS_ENV_KEYS.get(runtime, ()) if key in os.environ}
    values.update(configured)
    return values


def _host_paths(name: str, value: Any) -> bool:
    """Whether a setting points at host files that do not exist inside the sandbox."""
    if name in _HOST_ONLY:
        return True
    if name in ("thread_options", "turn_options", "turn_kwargs") and isinstance(value, dict):
        return "cwd" in value
    if name == "plugins" and isinstance(value, list):
        return any(isinstance(plugin, dict) and plugin.get("type") == "local" for plugin in value)
    return False


def _config(agent: "BaseExternalAgent", output_schema: Any) -> Dict[str, Any]:
    """The agent's non-default settings as JSON; checked on every run, so later assignments are caught too."""
    config: Dict[str, Any] = {}
    host_only: List[str] = []
    for item in fields(agent):
        if not item.init or item.name in _RUNTIME_OWNED:
            continue
        value = getattr(agent, item.name)
        if _is_default(item, value):
            continue
        if _host_paths(item.name, value):
            host_only.append(item.name)
            continue
        if item.name == "repository":
            from agno.sandbox.repository import Repository

            if not isinstance(value, Repository):
                raise TypeError("agent.repository must be a Repository")
            value = asdict(value)
        try:
            config[item.name] = json.loads(json.dumps(value, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise ValueError(f"Sandboxed agent setting {item.name!r} must be a JSON value") from error
    if host_only:
        raise ValueError(
            "Not supported with sandbox=: "
            + ", ".join(sorted(host_only))
            + ". The sandbox owns the workspace, process and local files; configure retries on QueueConfig."
        )
    if output_schema is not None:
        config["output_schema"] = output_schema
    return config


def submission(agent: "BaseExternalAgent", input: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one submission and return the run options it carries."""
    from agno.sandbox.protocol import validate_request

    env(agent)
    if not isinstance(input, str):
        raise ValueError("Sandboxed agent input must be text")
    extra = {key: value for key, value in kwargs.items() if value is not None}
    for key in ("run_id", "session_id", "user_id", "yield_run_output", "stream_events", "background_tasks"):
        extra.pop(key, None)
    media = _media_wire(extra.pop("media", None))
    unknown = set(extra) - {"output_schema", "metadata"}
    if unknown:
        raise ValueError("Unsupported sandbox run options: " + ", ".join(sorted(unknown)))
    schema = extra.get("output_schema", agent.output_schema)
    agent._check_output_schema(schema)
    if schema is not None and not isinstance(schema, dict):
        schema = schema.model_json_schema()
    runtime = agent._sandbox_runtime
    validate_request(
        dict(
            version=1,
            execution_id="validate",
            run_id="validate",
            agent_id=agent.get_id(),
            session_id="validate",
            sdk="claude" if runtime == "fixture" else runtime,
            input=input,
            config=_config(agent, schema),
            execution_timeout=_sandbox(agent).execution_timeout,
            **({"media": media} if media else {}),
            **({"metadata": extra["metadata"]} if "metadata" in extra else {}),
        )
    )
    options: Dict[str, Any] = {}
    if schema is not None:
        options["output_schema"] = schema
    if "metadata" in extra:
        options["metadata"] = json.loads(json.dumps(extra["metadata"], allow_nan=False))
    if media:
        options["media"] = media
    return options


def _media_wire(media: Any) -> List[Dict[str, Any]]:
    """Attachments in their runtime wire form.

    A run's own images and files arrive as the adapter's accepted media mapping; a queued run
    arrives with the wire form its submission stored, which is validated again here.
    """
    from agno.sandbox.media import encode_media, validate_media

    if not media:
        return []
    if isinstance(media, list):
        validate_media(media)
        return media
    if not isinstance(media, dict):
        raise ValueError("Sandbox media must be images and files")
    return encode_media(images=media.get("images"), files=media.get("files"))


def _execution(agent: "BaseExternalAgent", input: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    from agno.run.concurrency import get_worker_ownership
    from agno.sandbox.media import decode_media

    options = submission(agent, input, kwargs)
    run_id = kwargs.get("run_id") or str(uuid4())
    owner = get_worker_ownership(run_id)
    return dict(
        agent_id=agent.get_id(),
        run_id=run_id,
        input=input,
        sdk=agent._sandbox_runtime,
        user_id=kwargs.get("user_id"),
        agent_name=agent.name,
        config=_config(agent, options.get("output_schema")),
        env=env(agent),
        queue_attempt=owner.attempt if owner is not None else None,
        execution_timeout=_sandbox(agent).execution_timeout,
        **decode_media(options.get("media", [])),
        **({"metadata": options["metadata"]} if "metadata" in options else {}),
    )


def _output_schema(agent: "BaseExternalAgent", kwargs: Dict[str, Any]) -> Any:
    schema = kwargs.get("output_schema")
    return schema if schema is not None else agent.output_schema


async def arun(agent: "BaseExternalAgent", input: Any, **kwargs: Any) -> RunOutput:
    from agno.run.cancel import acleanup_run, aregister_run

    execution = _execution(agent, input, kwargs)
    await aregister_run(execution["run_id"])
    try:
        run = await coordinator(agent).arun(kwargs.get("session_id") or str(uuid4()), **execution)
    finally:
        await acleanup_run(execution["run_id"])
    # The runtime returns structured output as JSON; parse it into the caller's schema as the host path does.
    agent._apply_output_schema(run, _output_schema(agent, kwargs))
    return run


async def astream(agent: "BaseExternalAgent", input: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
    from agno.run.cancel import acleanup_run, aregister_run

    execution = _execution(agent, input, kwargs)
    await aregister_run(execution["run_id"])
    runner = coordinator(agent)
    iterator = runner.astream(kwargs.get("session_id") or str(uuid4()), **execution)
    events: List[Dict[str, Any]] = []
    skipped = {event.value for event in agent.events_to_skip or []}
    try:
        async for value in iterator:
            if isinstance(value, RunOutput):
                if agent.store_events:
                    await runner.store._apublish_events(value.to_dict(), events)
                agent._apply_output_schema(value, _output_schema(agent, kwargs))
            if not isinstance(value, RunOutput) or kwargs.get("yield_run_output", False):
                yield value
            # The queue publisher stamps the same object before resuming us.
            if agent.store_events and not isinstance(value, RunOutput) and value.event not in skipped:
                events.append(value.to_dict())
    finally:
        try:
            await iterator.aclose()
        finally:
            await acleanup_run(execution["run_id"])


async def aprepare_pending_run(
    agent: "BaseExternalAgent",
    run_id: str,
    session_id: str,
    user_id: Optional[str],
    input: Any,
    media: Optional[List[Dict[str, Any]]] = None,
) -> RunOutput:
    from agno.sandbox.media import decode_media

    run = RunOutput(
        run_id=run_id,
        session_id=session_id,
        agent_id=agent.get_id(),
        user_id=user_id,
        agent_name=agent.name,
        input=RunInput(input_content=input, **decode_media(media or [])),
        # The user's turn is part of the history even if the run never produces output, as on
        # the host path; the runtime's messages replace these when the turn completes.
        messages=[Message(role="user", content=str(input), created_at=int(time.time()))],
        status=RunStatus.pending,
    )
    await coordinator(agent).store.aprepare(run.to_dict())
    return run


async def acancel_unowned_row(agent: "BaseExternalAgent", run_id: str) -> None:
    from contextlib import suppress

    from sqlalchemy import select

    from agno.sandbox.postgres import SandboxLeaseLost

    runner = coordinator(agent)
    store = runner.store
    row = await store._transaction(
        lambda connection: (
            connection.execute(
                select(store.bindings).where(
                    store.bindings.c.namespace == store.namespace,
                    store.bindings.c.agent_id == agent.get_id(),
                    store.bindings.c.run_id == run_id,
                )
            )
            .mappings()
            .first()
        )
    )
    if row is not None:
        # Explicit cancel may retire a detached coordinator too. The shared
        # intent remains authoritative if another cancellation wins this race.
        with suppress(SandboxLeaseLost):
            await runner._aterminate(
                row["session_id"],
                agent_id=agent.get_id(),
                run_id=run_id,
                user_id=row["user_id"],
                queue_attempt=row["queue_attempt"],
                status="CANCELLED",
                reason="Run cancelled",
                env=env(agent),
            )


async def apersist_queue_terminal(
    agent: "BaseExternalAgent", job: Dict[str, Any], error: str, status: str, cancellation_stage: Any
) -> Any:
    runner = coordinator(agent)
    try:
        await runner.store._ensure_tables()
    except SandboxError as schema_error:
        # No turn can have run through an unusable bindings table, so there is no compute to retire:
        # stamp the run row directly so the ticket can still settle instead of staying claimed forever.
        from agno.run.status_persist import apersist_run_status

        log_error(f"Sandbox terminal persist for run {job['id']} bypassed its bindings table: {schema_error}")
        fields: Dict[str, Any] = {"status": "CANCELLED" if status == "cancelled" else "ERROR"}
        stage = getattr(cancellation_stage, "value", cancellation_stage)
        if fields["status"] == "CANCELLED" and stage is not None:
            fields["cancellation_stage"] = stage
        return await apersist_run_status(
            agent,
            "agent",
            session_id=job["session_id"],
            run_id=job["id"],
            fields=fields,
            user_id=job.get("user_id"),
            expected_attempt=job.get("attempt"),
            content_if_absent=error[:8192],
        )
    return await runner._aterminate(
        job["session_id"],
        agent_id=agent.get_id(),
        run_id=job["id"],
        user_id=job.get("user_id"),
        queue_attempt=job.get("attempt"),
        status="CANCELLED" if status == "cancelled" else "ERROR",
        reason=error[:8192],
        cancellation_stage=getattr(cancellation_stage, "value", cancellation_stage),
        env=env(agent),
    )


async def astart_background(
    agent: "BaseExternalAgent",
    input: Any,
    *,
    run_id: str,
    session_id: str,
    user_id: Optional[str],
    stream: bool,
    yield_run_output: bool,
    **kwargs: Any,
) -> RunOutput:
    from agno.os.job_queue import get_active_queue_worker
    from agno.os.routers.agents.sandbox import enqueue_sandbox_run

    worker = get_active_queue_worker()
    registered = (
        await worker._aresolve_job_component({"component_type": "agent", "component_id": agent.get_id()})
        if worker is not None
        else None
    )
    if registered is not agent:
        raise ValueError("Sandbox background execution requires this agent's active AgentOS durable queue")
    job = await enqueue_sandbox_run(
        agent, worker, input=input, session_id=session_id, user_id=user_id, kwargs=kwargs, run_id=run_id
    )
    return RunOutput(
        run_id=job["id"],
        session_id=job["session_id"],
        agent_id=agent.get_id(),
        user_id=user_id,
        status=RunStatus.pending,
    )


async def astream_background(agent: "BaseExternalAgent", input: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
    from agno.os.utils import queued_run_tail_streamer

    run = await astart_background(agent, input, stream=True, **kwargs)
    run_id, session_id = str(run.run_id), str(run.session_id)
    async for event in queued_run_tail_streamer(run_id):
        yield event
    if kwargs.get("yield_run_output"):
        stored = await agent.aget_run_output(run_id, session_id, user_id=run.user_id)
        if stored is not None:
            yield stored


def refuse_fallback() -> None:
    raise SandboxError("Sandbox execution requires atomic service persistence; unfenced fallback is disabled")
