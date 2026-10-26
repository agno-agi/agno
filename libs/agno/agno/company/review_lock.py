"""Persisted admission for Product Routines, independent of scheduler process lifetime."""

import json
from contextvars import ContextVar
from hashlib import sha256
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote
from uuid import uuid4

from agno.fs import FileSystem
from agno.fs.errors import VersionConflictError

_PATH = "review.md"
_active_review: ContextVar[Optional[Tuple[FileSystem, int, Dict[str, Any]]]] = ContextVar(
    "company_review", default=None
)


def _review_filesystem(db: Any, product_id: str) -> FileSystem:
    # Filesystem storage may be shared by several Company schemas/tables in one database.
    # Hash the exact identities because literal filesystem namespaces normalize case.
    identity = json.dumps([getattr(db, "db_schema", None), db.products_table_name, product_id])
    namespace = "company/routine-state/" + sha256(identity.encode()).hexdigest()
    return FileSystem(db, namespace=namespace, user_scoped=False)


def _busy(state: Dict[str, Any]) -> ValueError:
    return ValueError(
        "Another Routine review holds this Product (Routine "
        + str(state.get("routine_id"))
        + ", run "
        + str(state.get("run_id") or "submission outcome unknown")
        + "). Retry after the review finishes; a paused review must be completed or cancelled first."
    )


async def _claim_review(executor: Any, schedule: Any, product_id: str) -> Tuple[FileSystem, int, Dict[str, Any]]:
    from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
    from agno.scheduler.executor import _active_schedule_run

    filesystem = _review_filesystem(executor.company_db, product_id)
    existing = await filesystem.aread_with_meta(_PATH)
    if existing is not None:
        state = json.loads(existing.content)
        if state:
            if not state.get("run_id") and state.get("schedule_run_id"):
                from agno.company.execution import _call

                record = await _call(executor.schedule_db, "get_schedule_run", state["schedule_run_id"])
                if record and record.get("run_id") and record.get("session_id"):
                    state.update(run_id=record["run_id"], session_id=record["session_id"])
            # A poll timeout, shutdown or expired schedule claim does not stop a background run.
            # Only the executor's persisted terminal outcome permits a new review. PAUSED is live.
            if not state.get("run_id") or not state.get("session_id"):
                raise _busy(state)
            headers = {"Authorization": f"Bearer {executor.internal_service_token}"}
            if state.get("user_id") is not None:
                headers[SCHEDULE_OWNER_HEADER] = quote(state["user_id"], safe="")
            client = await executor._get_client()
            response = await client.request(
                "GET",
                executor.base_url + state["endpoint"] + "/" + quote(state["run_id"], safe=""),
                headers=headers,
                params={"session_id": state["session_id"]},
            )
            if response.status_code != 200 or response.json().get("status") not in {"COMPLETED", "ERROR", "CANCELLED"}:
                raise _busy(state)
            # A failed attempt can already have an ERROR run row while its ticket is
            # queued for retry. Require queue settlement too, including the brief gap
            # between the run completing and its worker settling the ticket.
            store = getattr(executor, "queue_store", None)
            if store is not None:
                job = await store.get_job(state["run_id"], strict=True)
                if job is not None and job.get("status") not in {"completed", "failed", "cancelled"}:
                    raise _busy(state)
    active_run = _active_schedule_run.get()
    state = {
        "claim_id": str(uuid4()),
        "schedule_run_id": active_run[1] if active_run else None,
        "routine_id": schedule.id,
        "endpoint": schedule.endpoint.rstrip("/"),
        "user_id": schedule.user_id,
    }
    try:
        saved = await filesystem.awrite(
            _PATH, json.dumps(state), expected_version=existing.metadata.version if existing else 0
        )
    except VersionConflictError as exc:
        raise _busy(state) from exc
    assert saved.version is not None
    return filesystem, saved.version, state


async def _record_review_run(run_id: str, session_id: str) -> None:
    active = _active_review.get()
    if active is None:
        return
    filesystem, version, state = active
    state = {**state, "run_id": run_id, "session_id": session_id}
    saved = await filesystem.awrite(_PATH, json.dumps(state), expected_version=version)
    assert saved.version is not None
    _active_review.set((filesystem, saved.version, state))


async def _release_rejected_review() -> None:
    active = _active_review.get()
    if active is not None:
        filesystem, version, _ = active
        await filesystem.awrite(_PATH, "{}", expected_version=version)
