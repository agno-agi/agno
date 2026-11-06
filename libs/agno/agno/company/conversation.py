"""Authorized conversation intake and non-blocking Company Task dispatch."""

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import quote

from agno.company.execution import _call
from agno.registry._reserved import MANAGER_TEAM_ID
from agno.run.authorization import AUTHORIZATION_HEADER, current_authorization

# Trusted service context, never reconstructed from caller-supplied metadata.
_conversation_run_id: ContextVar[Optional[str]] = ContextVar("company_conversation_run_id", default=None)
_conversation_origin: ContextVar[Optional[Dict[str, Any]]] = ContextVar("company_conversation_origin", default=None)
_conversation_task_submission: ContextVar[Optional[str]] = ContextVar(
    "company_conversation_task_submission", default=None
)
_conversation_submission: ContextVar[bool] = ContextVar("company_conversation_submission", default=False)


@contextmanager
def _conversation_scope(origin: Optional[Dict[str, Any]]) -> Iterator[None]:
    token = _conversation_origin.set(origin)
    try:
        yield
    finally:
        _conversation_origin.reset(token)


def _authority(run_context: Any) -> Any:
    return current_authorization() or getattr(run_context, "authorization", None)


def _identity(run_context: Any) -> Optional[str]:
    authority = _authority(run_context)
    return authority.context.principal_id if authority is not None else getattr(run_context, "user_id", None)


def _conversation_origins(
    task: Dict[str, Any], session_id: str, identity: Optional[str], origin_run_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    return [
        origin
        for event in task.get("transitions") or []
        for origin in [event.get("company_conversation", {}), *event.get("company_conversations", [])]
        if origin.get("session_id") == session_id
        and origin.get("user_id") == identity
        and (origin_run_id is None or origin.get("run_id") == origin_run_id)
    ]


def _require_conversation(run_context: Any) -> str:
    session_id = getattr(run_context, "session_id", None)
    if not session_id:
        raise ValueError("A conversation session is required")
    return session_id


async def _request(agent_os: Any, path: str, run_context: Any, *, data: Any = None, body: Any = None, key: str = ""):
    import httpx

    from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER

    app = getattr(agent_os, "_company_conversation_app", None)
    if app is None:
        raise ValueError("Company conversation requires an initialized AgentOS application")
    authority = _authority(run_context)
    if authority is None and agent_os.authorization:
        raise PermissionError("Verified caller authority is required")
    headers = {"Authorization": "Bearer " + agent_os._internal_service_token}
    if authority is not None:
        headers[AUTHORIZATION_HEADER] = json.dumps(authority.snapshot())
    identity = _identity(run_context)
    if identity:
        headers[SCHEDULE_OWNER_HEADER] = quote(identity, safe="")
    if key:
        headers["Idempotency-Key"] = key
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://company") as client:
        response = await client.post(path, data=data, json=body, headers=headers)
    if response.status_code >= 300:
        from fastapi import HTTPException

        raise HTTPException(response.status_code, response.json().get("detail", "Submission failed"))
    return response.json()


async def asubmit_company_task(
    agent_os: Any,
    task_id: str,
    run_context: Any,
    *,
    attempt: Optional[int] = None,
    component_type: str = "team",
    component_id: str = MANAGER_TEAM_ID,
) -> Dict[str, Any]:
    """Submit already accepted work and return its durable receipt without waiting for execution."""
    from agno.company.execution import _ExecutorAuthorization
    from agno.company.routines import _RoutineAuthorization

    session_id = _require_conversation(run_context)
    authority = _authority(run_context)
    if isinstance(authority, (_ExecutorAuthorization, _RoutineAuthorization)):
        raise PermissionError("Task workers and Routines cannot submit conversation work")
    if authority is not None:
        await authority.arequire("tasks", "write")
        await authority.arequire("wiki", "read")
    if agent_os._company_db is None:
        raise ValueError("Company requires a database")
    task = await _call(agent_os._company_db, "get_task", task_id)
    if task is None:
        raise ValueError("Task not found")
    if task["status"] not in {"ready", "in_progress"} or not task.get("accepted_at"):
        # A manager member may already have dispatched this Task for the same conversation.
        if (
            task.get("job_id")
            and task.get("executor_type")
            and _conversation_origins(task, session_id, _identity(run_context))
        ):
            if authority is not None:
                await authority.arequire(task["executor_type"] + "s", "run", task["executor_id"])
            return {
                "task_id": task_id,
                "run_id": task["job_id"],
                "session_id": task.get("session_id"),
                "task_status": task["status"],
                "already_submitted": True,
            }
        raise ValueError("Only accepted Tasks can be submitted; request an accepted revision before another attempt")
    if authority is not None:
        await authority.arequire(task["executor_type"] + "s", "run", task["executor_id"])
    origin = _conversation_origin.get() or {
        "session_id": session_id,
        "run_id": getattr(run_context, "run_id", None),
        "user_id": _identity(run_context),
        "component_type": component_type,
        "component_id": component_id,
    }
    from uuid import NAMESPACE_URL, uuid5

    worker_session = task.get("session_id") or str(uuid5(NAMESPACE_URL, "agno:company:task:" + task_id))
    if worker_session == origin["session_id"]:
        raise ValueError("Task worker session must differ from the conversation session")
    transport = _conversation_task_submission.set(task_id)
    try:
        with _conversation_scope(origin):
            receipt = await _request(
                agent_os,
                f"/company/tasks/{quote(task_id, safe='')}/runs",
                run_context,
                body={"attempt": attempt} if attempt is not None else {},
            )
    finally:
        _conversation_task_submission.reset(transport)
    associated = await _call(agent_os._company_db, "associate_task_conversation", task_id, receipt["run_id"], origin)
    if associated is None:
        raise ValueError("Task attempt changed before conversation association; reload its status")
    return {"task_id": task_id, **receipt}


def submit_company_task(agent_os: Any, task_id: str, run_context: Any, **kwargs: Any) -> Dict[str, Any]:
    """Synchronous counterpart of asubmit_company_task; use async inside an event loop."""
    return asyncio.run(asubmit_company_task(agent_os, task_id, run_context, **kwargs))


async def aget_conversation_tasks(
    agent_os: Any, run_context: Any, *, origin_run_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Read work associated with this caller's conversation, including after queue retention."""
    session_id = _require_conversation(run_context)
    authority = _authority(run_context)
    if authority is None and agent_os.authorization:
        raise PermissionError("Verified caller authority is required")
    if authority is not None:
        await authority.arequire("tasks", "read")
    identity = _identity(run_context)
    rows: List[Dict[str, Any]] = []
    page = 1
    while True:
        tasks, total = await _call(agent_os._company_db, "get_tasks", limit=100, page=page)
        for task in tasks:
            origins = _conversation_origins(task, session_id, identity, origin_run_id)
            if origins:
                rows.append(
                    {
                        "task_id": task["id"],
                        "title": task["title"],
                        "status": task["status"],
                        "updated_at": task.get("updated_at"),
                        "reason": (task.get("transitions") or [{}])[-1].get("reason"),
                        "run_id": task.get("job_id"),
                        "session_id": task.get("session_id"),
                        "result": task.get("result"),
                        "conversation": origins[0],
                    }
                )
        if page * 100 >= total:
            return rows
        page += 1


def get_conversation_tasks(agent_os: Any, run_context: Any, **kwargs: Any) -> List[Dict[str, Any]]:
    """Synchronous counterpart of aget_conversation_tasks."""
    return asyncio.run(aget_conversation_tasks(agent_os, run_context, **kwargs))


async def asubmit_conversation(
    agent_os: Any,
    message: str,
    run_context: Any,
    *,
    idempotency_key: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Durably accept a coordinator turn; trusted transports may supply a stable run id."""
    from uuid import NAMESPACE_URL, uuid4, uuid5

    from agno.os.job_queue import store_serializes_sessions, ticket_status_to_api

    session_id = _require_conversation(run_context)
    authority = _authority(run_context)
    if authority is None and agent_os.authorization:
        raise PermissionError("Verified caller authority is required")
    if authority is not None:
        await authority.arequire("teams", "run", MANAGER_TEAM_ID)
    identity = _identity(run_context)
    manager = agent_os.manager
    if manager is None or manager.db is None:
        raise ValueError("Super Agent conversation requires a manager with a database")
    app = getattr(agent_os, "_company_conversation_app", None)
    worker = getattr(getattr(app, "state", None), "queue_worker", None)
    if worker is None or not worker.config.durable or not store_serializes_sessions(worker.store):
        raise ValueError("Company conversations require a durable queue with session serialization")
    if not message.strip():
        raise ValueError("A message is required")
    session = await _call(manager.db, "claim_company_conversation", session_id, identity, MANAGER_TEAM_ID)
    _check_conversation_owner(session, identity)
    stable_id = (
        run_id
        or _conversation_run_id.get()
        or (
            str(
                uuid5(
                    NAMESPACE_URL,
                    json.dumps(["agno:company:conversation", agent_os.id, session_id, identity, idempotency_key]),
                )
            )
            if idempotency_key
            else str(uuid4())
        )
    )
    existing = await worker.store.get_job(stable_id)
    if existing is not None:
        if (
            existing.get("session_id") != session_id
            or existing.get("user_id") != identity
            or existing.get("component_id") != MANAGER_TEAM_ID
        ):
            raise ValueError("Conversation receipt conflicts with another run")
        return {"run_id": stable_id, "session_id": session_id, "status": ticket_status_to_api(existing["status"])}
    # Run storage outlives queue retention: redelivery must not execute it again.
    saved = await _call(manager.db, "get_run", stable_id, deserialize=False)
    if saved is not None:
        if (
            saved.get("session_id") != session_id
            or saved.get("user_id") != identity
            or saved.get("team_id") != MANAGER_TEAM_ID
        ):
            raise ValueError("Conversation receipt conflicts with another run")
        return {"run_id": stable_id, "session_id": session_id, "status": saved["status"]}
    origin = {
        "session_id": session_id,
        "run_id": stable_id,
        "user_id": identity,
        "authorization_required": authority is not None or bool(agent_os.authorization),
        "component_type": "team",
        "component_id": MANAGER_TEAM_ID,
    }
    token = _conversation_run_id.set(stable_id)
    submission = _conversation_submission.set(True)
    try:
        with _conversation_scope(origin):
            return await _request(
                agent_os,
                f"/teams/{MANAGER_TEAM_ID}/runs",
                run_context,
                data={
                    "message": message,
                    "session_id": session_id,
                    "stream": "false",
                    "background": "true",
                    **({"user_id": identity} if identity else {}),
                },
                key="company-conversation:" + stable_id,
            )
    finally:
        _conversation_submission.reset(submission)
        _conversation_run_id.reset(token)


def submit_conversation(agent_os: Any, message: str, run_context: Any, **kwargs: Any) -> Dict[str, Any]:
    """Synchronous counterpart of asubmit_conversation."""
    return asyncio.run(asubmit_conversation(agent_os, message, run_context, **kwargs))


def _check_conversation_owner(session: Optional[Dict[str, Any]], identity: Optional[str]) -> None:
    from agno.registry._reserved import _manager_id

    if session is None or session.get("user_id") != identity:
        raise PermissionError("Conversation belongs to another caller")
    if session.get("session_type") != "team" or _manager_id(session.get("team_id")) != MANAGER_TEAM_ID:
        raise PermissionError("Session belongs to another component")


async def _check_conversation_turn(worker: Any, job: Dict[str, Any], component: Any) -> None:
    """Recheck persisted ownership and current caller grants before a queued coordinator runs."""
    from agno.company.execution import _TaskRunRefused

    origin = (job.get("payload") or {}).get("company_conversation")
    if not origin or (job.get("payload") or {}).get("company_task_id"):
        return
    if job.get("component_type") != "team" or job.get("component_id") != MANAGER_TEAM_ID:
        raise _TaskRunRefused("Conversation coordinator changed")
    identity = job.get("user_id")
    try:
        session = await _call(component.db, "get_session", job["session_id"], deserialize=False)
        _check_conversation_owner(session, identity)
        if origin.get("authorization_required"):
            authority = current_authorization()
            if authority is None or authority.context.principal_id != identity:
                raise PermissionError("Verified conversation caller is required")
            await authority.arequire("teams", "run", MANAGER_TEAM_ID)
            state = getattr(worker.authorization_app, "state", None)
            directory = getattr(state, "user_store", None)
            if directory is not None:
                try:
                    disabled = await directory.ais_disabled(identity)
                except Exception:
                    if getattr(state, "user_directory_fail_closed", False):
                        raise
                    disabled = False
                if disabled:
                    raise PermissionError("User is disabled")
    except PermissionError as exc:
        raise _TaskRunRefused(str(exc)) from exc
