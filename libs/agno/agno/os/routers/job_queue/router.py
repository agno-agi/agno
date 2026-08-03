"""Operations surface for the durable job queue.

Without these endpoints, max_attempts=1 turns every crash into a dead end: an
operator needs to see failed jobs (dead-letter list), requeue them, and watch
queue depth - depth trending up is the early-warning signal the queue exists
to provide.
"""

from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from agno.db.schemas.jobs import JOB_STATUSES
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from agno.os.app import AgentOS


async def _require_queue_admin(request: Request) -> None:
    """Queue operations are an operator surface: job rows expose payloads
    (verbatim user input) and user_ids ACROSS tenants, and requeue grants
    execution budget.

    The gate keys on the caller's IDENTITY, not on data-scoping: RBAC
    (authorization) and user_isolation are independent flags, and
    get_scoped_user_id returns None for a non-admin JWT caller whenever
    isolation is off - which must NOT read as "operator". Any request that
    carries a JWT identity (scopes/user_id stamped by JWTMiddleware) requires
    the admin scope. Deployments without JWT enforcement (security-key or
    open) pass, matching how the run routes treat scope enforcement."""
    from agno.os.middleware.user_scope import _has_admin_scope

    scopes = getattr(request.state, "scopes", None)
    user_id = getattr(request.state, "user_id", None)
    jwt_identity_present = isinstance(scopes, list) or user_id is not None
    if not jwt_identity_present:
        return  # no JWT enforcement on this deployment

    admin_scope_raw = getattr(request.state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None
    if not _has_admin_scope(scopes or [], admin_scope=admin_scope):
        raise HTTPException(status_code=403, detail="Job queue operations require an admin scope")


def _get_store(request: Request):
    worker = getattr(request.app.state, "queue_worker", None)
    if worker is None:
        raise HTTPException(status_code=404, detail="Durable job queue is not enabled")
    return worker.store


def get_queue_router(os: "AgentOS", settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings)), Depends(_require_queue_admin)],
        prefix="/queue",
        tags=["Queue"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.get(
        "/jobs",
        operation_id="list_queue_jobs",
        summary="List Queue Jobs",
        description="List job queue jobs, optionally filtered by status (e.g. status=failed for the dead-letter list).",
    )
    async def list_jobs(request: Request, status: Optional[str] = None, limit: int = 50):
        if status is not None and status not in JOB_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status; expected one of {JOB_STATUSES}")
        store = _get_store(request)
        return {"jobs": await store.list_jobs(status=status, limit=min(limit, 200))}

    @router.get(
        "/jobs/{job_id}",
        operation_id="get_queue_job",
        summary="Get Queue Job",
    )
    async def get_job(request: Request, job_id: str):
        store = _get_store(request)
        job = await store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job queue job {job_id} not found")
        return job

    @router.post(
        "/jobs/{job_id}/requeue",
        operation_id="requeue_queue_job",
        summary="Requeue Failed Queue Job",
        description=(
            "Requeue a terminally failed or cancelled job for one more execution "
            "(raises its attempt budget by one). The operator remedy for crashed runs "
            "under the no-silent-re-execution default."
        ),
    )
    async def requeue_job(request: Request, job_id: str):
        import contextlib

        store = _get_store(request)
        # A cancelled job's cancellation intent outlives the tombstone (nothing
        # executed, so nothing cleaned it up). Clear it, or the requeued
        # attempt is instantly re-cancelled at its first checkpoint. The
        # cleanup is TOKEN-SCOPED (see acontinue_via_queue): the intent's
        # token is read BEFORE the transition, and the post-success cleanup
        # deletes intent ONLY if that exact token is still stored - so a
        # rejected requeue touches nothing (no successful transition), a
        # concurrent losing requeue clears nothing, and however delayed this
        # request gets, it can never erase a NEWER cancel aimed at the
        # requeued attempt (that cancel minted a different token).
        cancel_token = None
        with contextlib.suppress(Exception):
            from agno.run.cancel import aget_cancellation_token

            cancel_token = await aget_cancellation_token(job_id)
        if not await store.requeue_job(job_id):
            raise HTTPException(status_code=400, detail=f"Job {job_id} not found or not in a requeueable state")
        if cancel_token is not None:
            try:
                from agno.run.cancel import acleanup_run_if_token

                await acleanup_run_if_token(job_id, cancel_token)
            except Exception:
                log_warning(f"Could not clear stale cancellation intent for requeued job {job_id}")
        return await store.get_job(job_id)

    @router.get(
        "/stats",
        operation_id="get_queue_stats",
        summary="Queue Stats",
        description="Job counts by status and the oldest queued job's age - the queue-health signals to alert on.",
    )
    async def stats(request: Request):
        store = _get_store(request)
        return await store.queue_stats()

    return router
