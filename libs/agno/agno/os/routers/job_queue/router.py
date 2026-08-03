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
            "under the no-silent-re-execution default. Requeueing a CANCELLED job "
            "whose cancellation intent is still live requires clear_cancellation=true "
            "- an explicit override of the recorded cancel; without it the re-driven "
            "attempt is re-cancelled at its first checkpoint."
        ),
    )
    async def requeue_job(request: Request, job_id: str, clear_cancellation: bool = False):
        store = _get_store(request)
        # Cancellation intent is never cleared AUTOMATICALLY: every silent
        # scheme reviewed had a window where a delayed cleanup could erase a
        # newer, legitimate cancel. Instead the OPERATOR opts in with
        # clear_cancellation=true - an explicit, human-initiated override of
        # a recorded cancel (intent outlives a cancelled-while-queued
        # tombstone: nothing executed, so nothing cleaned it up; TTL bounds
        # it at ~24h). Without the flag the re-driven attempt is re-cancelled
        # at its first checkpoint, visibly - annoying but never wrong.
        #
        # The override is STATE-GATED and coupled to the transition:
        # 1) Gate: only a currently-requeueable (failed/cancelled) job may
        #    have intent cleared. Intent can only target a LIVE attempt, and
        #    live attempts exist only on running/queued/paused tickets - so
        #    rejecting those up front, WITHOUT touching intent, makes the
        #    dangerous class (erasing a running attempt's cancel and then
        #    400ing) unreachable.
        # 2) Clear BEFORE the requeue CAS: cleared after it, the clear could
        #    be delayed past a worker's claim and a fresh cancel of the
        #    re-driven attempt - the erase-a-newer-cancel window again.
        #    Cleared first, the ticket only becomes claimable once the
        #    override already happened.
        # 3) Clear failure ABORTS (503, nothing requeued): the operator asked
        #    for clear+requeue and must get both or neither - a silent
        #    requeue-without-clear would insta-cancel the re-driven attempt
        #    while reporting the override succeeded.
        # Residual (documented, accepted): between the gate read and the
        # clear, a CONCURRENT requeue + claim + fresh cancel could interleave
        # and be erased - cross-store atomicity between the job store and the
        # cancellation manager does not exist (same constraint as the sweep).
        # That needs two operators acting on one job simultaneously on an
        # admin-only surface; attempt-scoped intent (roadmap) closes it.
        if clear_cancellation:
            job = await store.get_job(job_id)
            if job is None or job.get("status") not in ("failed", "cancelled"):
                raise HTTPException(status_code=400, detail=f"Job {job_id} not found or not in a requeueable state")
            try:
                from agno.run.cancel import acleanup_run

                await acleanup_run(job_id)
            except Exception:
                raise HTTPException(
                    status_code=503,
                    detail=f"Could not clear cancellation intent for job {job_id}; "
                    "the job was NOT requeued - retry the request",
                )
        if not await store.requeue_job(job_id):
            raise HTTPException(status_code=400, detail=f"Job {job_id} not found or not in a requeueable state")
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
