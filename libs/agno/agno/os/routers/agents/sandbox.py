"""Durable submission for sandboxed agents in every HTTP response mode."""

import asyncio
import contextlib
import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agno.db.schemas.jobs import QueuedJob
from agno.os.job_queue import _new_queued_run_id, aenqueue_ticket, aprepare_accepted_or_abort, normalize_idempotency_key
from agno.sandbox.base import SandboxError


async def enqueue_sandbox_run(
    agent: Any,
    worker: Any,
    *,
    input: str,
    session_id: str,
    user_id: Optional[str],
    kwargs: Dict[str, Any],
    run_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    if (
        worker is None
        or worker.config.durable is not True
        or getattr(worker.store, "serializes_sessions", False) is not True
    ):
        raise ValueError("Sandbox API execution requires a durable queue with shared session admission")
    registered = await worker._aresolve_job_component({"component_type": "agent", "component_id": agent.get_id()})
    if registered is not agent:
        raise ValueError("Sandbox submissions must use the registered agent instance")
    from agno.sandbox import _harness

    options = _harness.submission(agent, input, kwargs)
    payload = {"input": input, "kwargs": options, "stream": True, "serialize_session": True}
    if len(json.dumps(payload, allow_nan=False).encode()) > 1024 * 1024:
        raise ValueError("Sandbox submission exceeds 1 MiB")
    # Before the ticket exists: a bindings table from another build would otherwise fail only inside the worker.
    await _harness.acheck_tables(agent)
    owner = await _session_owner(agent, session_id)
    if owner is not None and owner != (agent.get_id(), user_id or None):
        # Stricter than the route's shared-session rule, which admits a user into an unowned session:
        # the sandbox binding pins the session to one agent and one user for good, so the store would
        # refuse this turn as a lost lease after the ticket exists. Answer as that rule does.
        raise HTTPException(status_code=404, detail="Session not found")
    job = QueuedJob(
        id=run_id or _new_queued_run_id(),
        component_type="agent",
        component_id=agent.get_id(),
        session_id=session_id,
        user_id=user_id,
        payload=payload,
        max_attempts=worker.config.max_attempts,
        deployment_id=worker.config.deployment_id,
        idempotency_key=normalize_idempotency_key(idempotency_key),
    ).to_dict()
    accepted = await aenqueue_ticket(worker, job, agent)
    if accepted["reason"] == "queue_full":
        raise HTTPException(status_code=429, detail="Job queue is full")
    if accepted["reason"] == "duplicate":
        existing = accepted.get("job")
        if existing is None or any(
            existing.get(key) != job.get(key) for key in ("component_type", "component_id", "user_id", "session_id")
        ):
            raise HTTPException(status_code=409, detail="Idempotency-Key belongs to a different submission scope")
        # The store stamps its own fields (such as session_seq) onto the payload; compare what was submitted.
        stored = existing.get("payload") or {}
        if {key: stored.get(key) for key in payload} != payload:
            raise HTTPException(status_code=409, detail="Idempotency-Key already has different input or options")
        return existing
    from agno.os.event_streams import get_event_stream
    from agno.run.base import RunStatus

    with contextlib.suppress(Exception):
        # Fail-open: the queue row is already committed - a Redis blip
        # must not fail an accepted submission (tails degrade gracefully)
        await get_event_stream().register_run(job["id"], RunStatus.pending)
    media = options.get("media")
    await aprepare_accepted_or_abort(
        worker, agent, "agent", job["id"], session_id, user_id, input, **({"media": media} if media else {})
    )
    return job


async def _session_owner(agent: Any, session_id: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """The (agent_id, user_id) a stored session belongs to, or None when the session does not exist."""
    from agno.db.base import AsyncBaseDb, SessionType

    if isinstance(agent.db, AsyncBaseDb):
        row = await agent.db.get_session(
            session_id=session_id, session_type=SessionType.AGENT, deserialize=False, runs_limit=1
        )
    else:
        row = await asyncio.to_thread(
            agent.db.get_session, session_id=session_id, session_type=SessionType.AGENT, deserialize=False, runs_limit=1
        )
    if not isinstance(row, dict):
        return None
    return row.get("agent_id"), row.get("user_id") or None


def _uploaded_media(images: List[Any], files: List[Any]) -> Dict[str, List[Any]]:
    """Request media as Image/File objects; JSON entries arrive as dicts and must not name server paths."""
    from agno.utils.media import reconstruct_file_from_dict, reconstruct_image_from_dict

    media: Dict[str, List[Any]] = {
        "images": [reconstruct_image_from_dict(item) for item in images],
        "files": [reconstruct_file_from_dict(item) for item in files],
    }
    if any(item is None for values in media.values() for item in values):
        raise ValueError("Sandbox attachments must be valid images and files")
    if any(item.filepath for values in media.values() for item in values):
        raise ValueError("Sandboxed runs accept uploaded bytes; server file paths are not accepted")
    return media


async def sandbox_run_response(
    agent: Any,
    worker: Any,
    request: Request,
    *,
    input: str,
    session_id: str,
    user_id: Optional[str],
    kwargs: Dict[str, Any],
    stream: bool,
    background: bool,
    version: Any = None,
    images: Optional[List[Any]] = None,
    files: Optional[List[Any]] = None,
    unsupported_media: bool = False,
) -> Any:
    if version is not None:
        raise HTTPException(
            status_code=400, detail="Sandboxed runs use the registered agent; version pinning is not supported"
        )
    if unsupported_media:
        raise HTTPException(
            status_code=400, detail="Sandboxed runs accept images and files; audio and video are not supported"
        )
    try:
        if images or files:
            kwargs = {**kwargs, "media": _uploaded_media(images or [], files or [])}
        job = await enqueue_sandbox_run(
            agent,
            worker,
            input=input,
            session_id=session_id,
            user_id=user_id,
            kwargs=kwargs,
            idempotency_key=request.headers.get("idempotency-key"),
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except SandboxError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    if stream:
        # Existing resume machinery chooses retained events or database replay,
        # including for an idempotent submission whose live keys have expired.
        from agno.os.routers.agents.router import _resume_stream_generator
        from agno.os.utils import queued_run_tail_streamer

        if job.get("status") in ("completed", "failed", "cancelled"):
            iterator = _resume_stream_generator(agent, job["id"], None, job["session_id"], user_id)
        else:
            iterator = queued_run_tail_streamer(job["id"])
        return StreamingResponse(iterator, media_type="text/event-stream")
    if background:
        from agno.os.job_queue import ticket_status_to_api

        return JSONResponse(
            status_code=202,
            content={
                "run_id": job["id"],
                "session_id": job["session_id"],
                "status": ticket_status_to_api(job["status"]) or "PENDING",
            },
        )
    delay = 0.1
    while True:
        current = await worker.store.get_job(job["id"])
        if current is None:
            raise HTTPException(
                status_code=503, detail="Accepted sandbox job is temporarily unavailable; reconnect using its run ID"
            )
        if current["status"] in ("completed", "failed", "cancelled"):
            result = await agent.aget_run_output(job["id"], job["session_id"], user_id=user_id)
            if result is None and current["status"] == "failed" and current.get("error"):
                # The job failed before its run row could be written; the ticket's error is all there is.
                raise HTTPException(status_code=500, detail=current["error"])
            if result is None:
                raise HTTPException(
                    status_code=503, detail="Sandbox result is temporarily unavailable; reconnect using its run ID"
                )
            return JSONResponse(content=result.to_dict())
        if await request.is_disconnected():
            return JSONResponse(
                status_code=202, content={"run_id": job["id"], "session_id": job["session_id"], "status": "RUNNING"}
            )
        await asyncio.sleep(delay)
        delay = min(delay * 2, 1.0)
