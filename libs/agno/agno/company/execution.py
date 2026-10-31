"""Company Task execution using the platform's ordinary run and queue contracts."""

import asyncio
import json
from contextvars import ContextVar
from typing import Any, Dict, Optional, Tuple
from uuid import uuid4

from agno.db.base import AsyncBaseDb
from agno.db.schemas.tasks import task_run_id
from agno.exceptions import InputCheckError
from agno.registry._reserved import RESERVED_MANAGER_IDS
from agno.run.authorization import RunAuthorization

# Trusted, request-local handoff to the existing run routes. It never comes from
# a request field, tool argument, session state or run metadata.
_task_submission: ContextVar[Optional[Dict[str, Any]]] = ContextVar("company_task_submission", default=None)

_automatic_task: ContextVar[Optional[Dict[str, Any]]] = ContextVar("company_automatic_task", default=None)

# An already-authorized Company request may scope its executor session to a
# different owner. Bind the exception to exactly one internal route invocation.
_task_transport: ContextVar[Optional[Tuple[str, str, Optional[str]]]] = ContextVar(
    "company_task_transport", default=None
)


class _TaskRunConflict(ValueError):
    """The persisted reservation conflicts with the observed execution state."""


class _TaskRunUnavailable(ValueError):
    """The original execution store or component is unavailable for recovery."""


class _TaskRunRefused(InputCheckError):
    """A claimed Company run (a Task or a routine) may no longer start; the queue fails it without retrying."""


def _executor(registry: Any, executor_type: Optional[str], executor_id: Optional[str], accepting: bool = False) -> Any:
    if executor_type not in {"agent", "team", "workflow"} or executor_id in RESERVED_MANAGER_IDS:
        raise ValueError("Select a registered agent, team or workflow executor")
    component = getattr(registry, "get_" + executor_type)(executor_id) if registry is not None else None
    if component is None:
        raise ValueError("Task executor is missing from the registry")
    if not accepting:
        from agno.agent import RemoteAgent
        from agno.team import RemoteTeam
        from agno.workflow import RemoteWorkflow

        if isinstance(component, (RemoteAgent, RemoteTeam, RemoteWorkflow)):
            raise ValueError("Task execution requires a local executor supported by the durable queue")
    _validate_executor_tools(component)
    return component


async def _call(target: Any, method: str, *args: Any, **kwargs: Any) -> Any:
    from agno.company.manager import AsyncCompanyManager

    fn = getattr(target, method)
    if isinstance(target, (AsyncBaseDb, AsyncCompanyManager)):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


def _queued_run_id() -> str:
    submission = _task_submission.get()
    return task_run_id(submission["task"]["id"], submission["attempt"]) if submission else str(uuid4())


async def _reserve_task(db: Any, job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Apply a committed ticket to its unchanged acceptance, once across submitter and worker."""
    payload = job["payload"]
    task = await _call(db, "get_task", payload["company_task_id"])
    if task is None:
        return None
    history = payload["company_task_transitions"]
    if task["transitions"] == history:
        # Queue JSON may reorder keys. Preserve the Task store's representation
        # for its conditional update after comparing the decoded history.
        reserved = await _call(
            db,
            "start_task_run",
            task["id"],
            payload["company_task_attempt"],
            task["transitions"],
            user_id=payload.get("company_started_by", job.get("user_id")),
            run_db_id=payload["company_run_db_id"],
            session_user_id=job.get("user_id"),
        )
        task = reserved or await _call(db, "get_task", task["id"])
    if (
        task is None
        or task["job_id"] != job["id"]
        or task["transitions"][:-1] != history
        or task["transitions"][-1].get("attempt") != payload["company_task_attempt"]
    ):
        return None
    return task


def _pending_task_attempt(task: Dict[str, Any]) -> Optional[int]:
    """Identify an unfinished reservation without authorizing another attempt."""
    history = task.get("transitions") or []
    attempt = history[-1].get("attempt") if history else None
    if (
        task["status"] == "in_progress"
        and task.get("result") is None
        and isinstance(attempt, int)
        and not isinstance(attempt, bool)
        and attempt > 0
        and history[-1].get("target") == "in_progress"
        and task.get("job_id") == task_run_id(task["id"], attempt)
    ):
        return attempt
    return None


def _task_run_database(os: Any, task: Dict[str, Any]) -> Any:
    """Resolve the original run store even if the executor's database has changed."""
    store_ids = [entry.get("run_db_id") for entry in task["transitions"] if entry.get("attempt")]
    if store_ids and store_ids[0]:
        stores = list({id(store): store for store in os.dbs.get(store_ids[0], [])}.values())
        if len(stores) == 1:
            return stores[0]
        raise _TaskRunUnavailable("Task session database is unavailable or ambiguous")
    return getattr(_executor(os.registry, task["executor_type"], task["executor_id"]), "db", None)


def _reservation_owner(task: Dict[str, Any], run: Dict[str, Any]) -> Optional[str]:
    """Use the recorded starter only for reservations predating stable ownership."""
    for entry in task.get("transitions") or []:
        attempt = entry.get("attempt")
        if attempt and task_run_id(task["id"], attempt) == run["run_id"]:
            owner = entry.get("session_user_id", task.get("user_id") if "started_by" in entry else entry.get("user_id"))
            if run.get("user_id") != owner:
                raise _TaskRunConflict("Task run owner does not match its reservation")
            return owner
    raise _TaskRunConflict("Task run has no recorded reservation")


def _task_session_owner(task: Dict[str, Any], component: Any) -> Optional[str]:
    """Retain the accountable owner, or the recorded executor default for unowned work."""
    if task.get("user_id") is not None:
        return task["user_id"]
    for entry in task.get("transitions") or []:
        if entry.get("attempt") and entry.get("session_user_id") is not None:
            return entry["session_user_id"]
    return getattr(component, "user_id", None)


async def _prepare_task_session(run_db: Any, task: Dict[str, Any], owner: Optional[str]) -> None:
    """Adopt an idle legacy session only with its original reservation's ownership proof."""
    from agno.db.base import SessionType
    from agno.os.middleware.user_scope import assert_session_writable

    kind = SessionType(task["executor_type"])
    session = await _call(run_db, "get_session", task["session_id"], session_type=kind, deserialize=False)
    if session and session.get("user_id") not in {None, owner}:
        entries = [entry for entry in task["transitions"] if entry.get("attempt")]
        first = entries[0] if entries else {}
        legacy_owner = first.get("session_user_id", first.get("user_id") if "started_by" not in first else owner)
        if first and legacy_owner == session["user_id"]:
            run = await _call(run_db, "get_run", task_run_id(task["id"], first["attempt"]), deserialize=False)
            if run and run["session_id"] == task["session_id"] and _reservation_owner(task, run) == session["user_id"]:
                await _call(
                    run_db,
                    "reassign_session_owner",
                    task["session_id"],
                    previous_user_id=session["user_id"],
                    user_id=owner,
                )
    await assert_session_writable(run_db, task["session_id"], owner, session_type=kind)


async def _recover_task(os: Any, worker: Any, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Reconcile reserved work independently of current dispatch authority; never enqueue."""
    if not task.get("job_id"):
        return None
    run_db = _task_run_database(os, task)
    if run_db is None:
        raise _TaskRunUnavailable("Task run database is unavailable")
    run = await _call(run_db, "get_run", task["job_id"], deserialize=False)
    ticket = await worker.store.get_job(task["job_id"])
    pending = _pending_task_attempt(task) is not None
    if run is not None:
        if run["session_id"] != task["session_id"]:
            raise _TaskRunConflict("Run identifier conflicts with another session")
        owner = _reservation_owner(task, run)
        if not pending:
            await _cancel_ticketless_pending_run(run_db, task, run, owner, worker)
        repaired = await _reconcile_task_run(os._company_db, run_db, task, run, owner, worker=worker)
        if pending:
            if ticket is not None and run["status"] not in {"COMPLETED", "ERROR", "CANCELLED"}:
                return {"status": "already_submitted", "run_id": task["job_id"]}
            return {
                "status": run["status"],
                "run_id": run["run_id"],
                "action": "reconciled" if repaired else "observed",
            }
    elif pending:
        if ticket is not None:
            return {"status": "already_submitted", "run_id": task["job_id"]}
        result = {
            "run_id": task["job_id"],
            "status": "CANCELLED",
            "content": "Reserved attempt lost its queue ticket and run; start the next attempt to retry.",
        }
        updated = await _call(
            os._company_db,
            "complete_task_run",
            task["id"],
            task["job_id"],
            result,
            expected_transitions=task["transitions"],
        )
        return {"status": "CANCELLED", "run_id": task["job_id"], "action": "reconciled" if updated else "observed"}
    return None


async def _cancel_ticketless_pending_run(
    run_db: Any,
    task: Dict[str, Any],
    run: Dict[str, Any],
    caller: Optional[str],
    worker: Any,
    is_admin: bool = False,
) -> None:
    """Close an orphaned Pending attempt; observe Running until durable completion."""
    if (
        worker is None
        or run["status"] not in {"PENDING", "RUNNING"}
        or run["run_id"] != task.get("job_id")
        or run["session_id"] != task.get("session_id")
    ):
        return
    from agno.db.base import SessionType
    from agno.os.middleware.user_scope import assert_session_writable

    await assert_session_writable(
        run_db, run["session_id"], caller, session_type=SessionType(run["run_type"]), is_admin=is_admin
    )
    if await worker.store.get_job(run["run_id"]) is not None:
        return
    current = await _call(run_db, "get_run", run["run_id"], deserialize=False)
    if current is None or current["session_id"] != task["session_id"]:
        raise _TaskRunConflict("Task run changed during recovery")
    if current["status"] != run["status"]:
        run.update(current)
        return
    if current["status"] in {"PENDING", "RUNNING"}:
        if current["status"] == "RUNNING":
            # Cancellation registries are not authoritative liveness records:
            # another process may own the run, or its registration may expire.
            # Wait for durable completion or an explicit cancellation request.
            run.update(current)
            return
        # A lost Pending ticket must not replay possibly executed side effects.
        kind = current["run_type"]
        job = {
            "id": run["run_id"],
            "session_id": task["session_id"],
            "component_type": kind,
            "component_id": current.get(kind + "_id"),
            "user_id": current.get("user_id"),
            "attempt": (current.get("run_data") or {}).get("queue_attempt"),
        }
        component = await worker._aresolve_job_component(job)
        if component is None or getattr(component, "db", None) is not run_db:
            raise _TaskRunUnavailable("Original Task executor database is unavailable for recovery")
        reason = "Queue ticket lost before completion; this attempt was cancelled. Start the next attempt to retry."
        cancelled = await _call(
            run_db,
            "cancel_pending_run",
            run["run_id"],
            session_id=task["session_id"],
            reason=reason,
            user_id=current.get("user_id"),
            expected_status=current["status"],
        )
        if cancelled:
            await component.acancel_run(run["run_id"])
        # The worker may have advanced to Running or settled the run while we
        # were resolving its executor. Reconcile that winner without rewriting it.
        current = await _call(run_db, "get_run", run["run_id"], deserialize=False)
        if current is None or current["status"] == "PENDING":
            raise RuntimeError("Ticketless Task cancellation has not reached durable storage")
    run.update(current)


async def _reconcile_task_run(
    db: Any,
    run_db: Any,
    task: Dict[str, Any],
    run: Dict[str, Any],
    caller: Optional[str],
    is_admin: bool = False,
    worker: Any = None,
) -> bool:
    """Repair a missing result without enqueueing or overwriting a newer acceptance."""
    if (
        _pending_task_attempt(task) is None
        or run["run_id"] != task["job_id"]
        or run["session_id"] != task["session_id"]
        or run["status"] not in {"COMPLETED", "ERROR", "CANCELLED", "PENDING", "RUNNING"}
    ):
        return False
    from agno.db.base import SessionType
    from agno.os.middleware.user_scope import assert_session_writable

    await assert_session_writable(
        run_db, task["session_id"], caller, session_type=SessionType(task["executor_type"]), is_admin=is_admin
    )
    await _cancel_ticketless_pending_run(run_db, task, run, caller, worker, is_admin=is_admin)
    if run["status"] not in {"COMPLETED", "ERROR", "CANCELLED"}:
        return False
    data = run.get("run_data") or {}
    result = {
        "run_id": run["run_id"],
        "status": run["status"],
        "content": data.get("content"),
        "content_type": data.get("content_type"),
    }
    checkout = None
    if run["status"] == "COMPLETED":
        from agno.company.sandbox import _is_sandboxed, _project_checkout

        kind = run["run_type"]
        component = (
            await worker._aresolve_job_component({"component_type": kind, "component_id": run.get(kind + "_id")})
            if worker is not None
            else None
        )
        if not _is_sandboxed(component) and (
            (data.get("metadata") or {}).get("sandbox") or (task.get("metadata") or {}).get("checkout")
        ):
            raise _TaskRunUnavailable("Sandboxed Task executor is unavailable while recovering its checkout")
        checkout, result = await _project_checkout(db, task, component, data, result)
    updated = await _call(
        db,
        "complete_task_run",
        task["id"],
        run["run_id"],
        result,
        expected_transitions=task["transitions"],
        **({"checkout": checkout} if checkout is not None else {}),
    )
    return updated is not None


async def _enqueue_ticket(worker: Any, job: Dict[str, Any]) -> Dict[str, Any]:
    submission = _task_submission.get()
    if submission is None:
        return await worker.store.enqueue_job(job, max_depth=worker.config.max_queue_depth)
    task = submission["task"]
    history = task["transitions"]
    if _pending_task_attempt(task) is not None:
        raise ValueError("An existing Task reservation cannot enqueue new work")
    job = {
        **job,
        "payload": {
            **job["payload"],
            "company_task_id": task["id"],
            "company_task_transitions": history,
            "company_task_attempt": submission["attempt"],
            "company_run_db_id": submission["run_db_id"],
            "company_started_by": submission.get("started_by"),
        },
    }
    try:
        result = await worker.store.enqueue_job(job, max_depth=worker.config.max_queue_depth)
    except Exception:
        # Queue keys are user-scoped. Simultaneous collaborators still share the
        # deterministic Task run id; an INSERT collision returns its committed winner.
        existing = await worker.store.get_job(job["id"])
        if existing is None or (existing.get("payload") or {}).get("company_task_id") != task["id"]:
            raise
        result = {"accepted": False, "reason": "duplicate", "job": existing}
    if result["job"] is not None:
        # Acceptance is the committed queue ticket. A rejected enqueue leaves the
        # Task untouched; a crash here is recovered by the worker before execution.
        reserved = await _reserve_task(submission["db"], result["job"])
        if reserved is None and result["accepted"]:
            current = await _call(submission["db"], "get_task", task["id"])
            # A fast worker may already have reserved and completed this attempt.
            # Its committed start still counts as acceptance, even after review.
            if current is None or current.get("job_id") != result["job"]["id"]:
                from fastapi import HTTPException

                # Abort a fresh ticket whose acceptance was revoked during submission.
                # If already claimed, the worker's acceptance check rejects execution.
                await worker.acancel_queued(result["job"]["id"])
                raise HTTPException(409, "Task acceptance was changed or revoked")
    return result


async def _check_task(worker: Any, job: Dict[str, Any]) -> None:
    task_id = (job.get("payload") or {}).get("company_task_id")
    if not task_id:
        return
    db = getattr(worker, "_company_db", None)
    if db is None:
        raise ValueError("Company is unavailable for this queued Task")
    task = await _reserve_task(db, job)
    if (
        task is None
        or task["job_id"] != job["id"]
        or task["status"] != "in_progress"
        or task["executor_id"] != job["component_id"]
        or task["executor_type"] != job["component_type"]
    ):
        raise _TaskRunRefused("Task acceptance was changed or revoked")
    from agno.company.routines import _check_automatic_policy

    try:
        await _check_automatic_policy(getattr(worker, "_company_schedule_db", None), task)
    except ValueError as exc:
        raise _TaskRunRefused(str(exc)) from exc
    from agno.run.authorization import current_authorization

    authority = current_authorization()
    if authority is not None:
        try:
            await authority.arequire(
                {"agent": "agents", "team": "teams", "workflow": "workflows"}[job["component_type"]],
                "run",
                job["component_id"],
            )
        except PermissionError as exc:
            raise _TaskRunRefused(str(exc)) from exc
    component = await worker._aresolve_job_component(job)
    try:
        _validate_executor_tools(component)
    except ValueError as exc:
        raise _TaskRunRefused(str(exc)) from exc


async def _project_run(worker: Any, job: Dict[str, Any], status: str, error: Optional[str] = None) -> None:
    task_id = (job.get("payload") or {}).get("company_task_id")
    if not task_id or status not in {"completed", "failed", "cancelled"}:
        return
    db = getattr(worker, "_company_db", None)
    if db is None:
        raise ValueError("Company is unavailable for this queued Task")
    task = await _reserve_task(db, job)
    if task is None:
        return
    result: Dict[str, Any] = {
        "run_id": job["id"],
        "status": "CANCELLED" if status == "cancelled" else "ERROR",
        "content": error or ("Run cancelled" if status == "cancelled" else None),
    }
    checkout = None
    if status == "completed":
        component = await worker._aresolve_job_component(job)
        if component is None:
            raise ValueError("Task executor is unavailable while saving results")
        output = await component.aget_run_output(job["id"], job["session_id"], user_id=job.get("user_id"))
        if output is None or str(getattr(output.status, "value", output.status)) != "COMPLETED":
            raise ValueError("Completed Task run is not durably readable")
        data = output.to_dict()
        result = {key: data.get(key) for key in ("run_id", "status", "content", "content_type")}
        from agno.company.sandbox import _project_checkout

        checkout, result = await _project_checkout(db, task, component, data, result)
    await _call(
        db,
        "complete_task_run",
        task_id,
        job["id"],
        result,
        expected_transitions=task["transitions"],
        **({"checkout": checkout} if checkout is not None else {}),
    )


async def _project_run_before_settle(
    worker: Any, job: Dict[str, Any], status: str, error: Optional[str] = None
) -> None:
    """Save the Task result before its ticket finishes, unless the run row can rebuild it."""
    try:
        await _project_run(worker, job, status, error)
    except Exception as exc:
        if not await _run_row_settled(worker, job) or not await _reservation_recorded(worker, job):
            raise
        from agno.utils.log import log_error

        log_error(
            f"Failed to save the Task result for run {job['id']}; finishing its queue ticket so Company "
            f"recovery rebuilds the Task from the run row: {exc}"
        )


async def _run_row_settled(worker: Any, job: Dict[str, Any]) -> bool:
    try:
        component = await worker._aresolve_job_component(job)
        if component is None:
            return False
        output = await component.aget_run_output(job["id"], job["session_id"], user_id=job.get("user_id"))
    except Exception:
        return False
    status = getattr(output, "status", None)
    return str(getattr(status, "value", status)).upper() in {"COMPLETED", "ERROR", "CANCELLED"}


async def _reservation_recorded(worker: Any, job: Dict[str, Any]) -> bool:
    """Company recovery finds a Task only through the run id its reservation recorded."""
    try:
        task = await _call(worker._company_db, "get_task", job["payload"]["company_task_id"])
    except Exception:
        return False
    return task is not None and task.get("job_id") == job["id"]


async def _task_input(manager: Any, task: Dict[str, Any], *, accepted_execution: bool = False) -> str:
    pages = []
    # Both namespaces have company-wide read visibility. No Source credentials,
    # Product metadata, other Tasks or caller-supplied runtime state are forwarded.
    for product_id in (None, task["product_id"]):
        page = 1
        while True:
            rows, total = await _call(manager, "list_wiki", product_id, limit=100, page=page)
            for row in rows:
                value = await _call(manager, "read_wiki", product_id, row.path)
                pages.append(
                    {
                        "namespace": "company" if product_id is None else "product",
                        "path": row.path,
                        "content": value.content,
                    }
                )
            if page * 100 >= total:
                break
            page += 1
    payload = {"brief": task.get("brief"), "wiki": pages, "evidence": task.get("evidence") or []}
    # Only the authorized execution route supplies this flag; a Task dictionary
    # or its brief alone does not establish acceptance.
    if accepted_execution:
        payload["execution_context"] = {
            "stage": "accepted_task_execution",
            "task_id": task["id"],
            "instructions": (
                "Execute this accepted Task and return its deliverable with verification evidence. "
                "This is execution, not a request to acknowledge or propose the Task. "
                "Preserve the brief's scope and restrictions; acceptance grants no additional permissions. "
                "If instructions conflict or the work cannot be completed within those bounds, "
                "report the precise blocker and what remains undone."
            ),
        }
    return json.dumps(payload, ensure_ascii=False)


def _validate_executor_tools(component: Any) -> None:
    from agno.tools.scheduler import SchedulerTools

    pending = [component]
    seen = set()
    while pending:
        item = pending.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        for tool in getattr(item, "tools", None) or []:
            if isinstance(tool, SchedulerTools) or isinstance(getattr(tool, "__self__", None), SchedulerTools):
                raise ValueError("Company executors cannot hold SchedulerTools")
        for name in ("members", "steps"):
            children = getattr(item, name, None)
            if isinstance(children, (list, tuple)):
                pending.extend(children)
        for name in ("agent", "team", "executor"):
            child = getattr(item, name, None)
            if child is not None:
                pending.append(child)


class _ExecutorAuthorization(RunAuthorization):
    """Attenuate the caller's authority for Company execution and its delegation."""

    def __init__(self, original: Optional[RunAuthorization]):
        from agno.os.auth import _default_authorization_provider
        from agno.os.authz.provider import AuthorizationContext

        self.original = original
        super().__init__(
            original.provider if original else _default_authorization_provider(),
            original.context if original else AuthorizationContext(),
            service_account=original.service_account if original else False,
            enforce_tools=True,
        )

    def require(self, resource: str, action: str, resource_id: Optional[str] = None) -> None:
        if resource == "schedules" and action != "read":
            raise PermissionError("Company executors cannot change schedules")
        if self.original is not None:
            self.original.require(resource, action, resource_id)

    async def arequire(self, resource: str, action: str, resource_id: Optional[str] = None) -> None:
        if resource == "schedules" and action != "read":
            raise PermissionError("Company executors cannot change schedules")
        if self.original is not None:
            await self.original.arequire(resource, action, resource_id)

    def snapshot(self) -> Dict[str, Any]:
        return {**super().snapshot(), "company_executor": True}


def _mount_executors(os: Any) -> None:
    """Expose registry executors through the normal routes when Company is enabled."""
    if os.registry is None:
        return
    for resource in ("agents", "teams", "workflows"):
        served = list(getattr(os, resource) or [])
        by_id = {getattr(component, "id", None): component for component in served}
        for component in getattr(os.registry, resource):
            component_id = getattr(component, "id", None)
            if component_id in RESERVED_MANAGER_IDS:
                continue
            if component_id in by_id:
                if by_id[component_id] is not component:
                    raise ValueError("Company requires one executor per registered type and id")
            else:
                try:
                    _validate_executor_tools(component)
                except ValueError:
                    continue
                served.append(component)
        setattr(os, resource, served)
