"""Operations surface for the durable job queue.

Without these endpoints, max_attempts=1 turns every crash into a dead end: an
operator needs to see failed jobs (dead-letter list), requeue them, and watch
queue depth - depth trending up is the early-warning signal the queue exists
to provide.
"""

from typing import TYPE_CHECKING, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.db.schemas.jobs import JOB_STATUSES
from agno.os.auth import get_authentication_dependency
from agno.os.routers.job_queue.schema import QueueJobSchema
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    SortOrder,
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


def _queue_list_user_id(request: Request, session_ids: Optional[List[str]]) -> Optional[str]:
    """Return the mandatory owner filter for a contextual non-admin list.

    Open/security-key deployments and admin JWT callers retain the operator
    view. Every other JWT caller must name at least one session and is pinned
    to its authenticated user_id, regardless of whether global user isolation
    is enabled. Session IDs are selectors, never authorization boundaries.
    """
    from agno.os.middleware.user_scope import _has_admin_scope

    scopes = getattr(request.state, "scopes", None)
    user_id = getattr(request.state, "user_id", None)
    jwt_identity_present = isinstance(scopes, list) or user_id is not None
    if not jwt_identity_present:
        return None

    admin_scope_raw = getattr(request.state, "admin_scope", None)
    admin_scope = admin_scope_raw if isinstance(admin_scope_raw, str) else None
    if _has_admin_scope(scopes or [], admin_scope=admin_scope):
        return None
    if not session_ids:
        raise HTTPException(status_code=403, detail="Non-admin queue reads require at least one session_id")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=403, detail="Contextual queue reads require an authenticated user_id")
    return user_id


def _get_store(request: Request):
    worker = getattr(request.app.state, "queue_worker", None)
    if worker is None:
        # 503, not 404: "no active queue worker" is a service-availability
        # condition (queue not configured, or the worker not running on this
        # replica), not a missing resource - and the requeue path already
        # answered 503 for the same condition, so one operational state got
        # two different statuses depending on the endpoint.
        raise HTTPException(status_code=503, detail="Durable job queue is not enabled on this replica")
    return worker.store


def get_queue_router(os: "AgentOS", settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        prefix="/queue",
        tags=["Queue"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
            503: {"description": "Durable job queue not enabled on this replica"},
        },
    )

    @router.get(
        "/jobs",
        operation_id="list_queue_jobs",
        summary="List Queue Jobs",
        response_model=PaginatedResponse[QueueJobSchema],
        description=(
            "List job queue jobs, optionally filtered by status and session. Repeat either param to "
            "match any of several (e.g. status=failed&status=cancelled for the requeueable "
            "set, or session_id=s1&session_id=s2 for a contextual chat tray). Non-admin JWT "
            "callers must provide session_id and only receive jobs owned by their authenticated "
            "user. Useful sort_by fields: "
            "created_at (default), updated_at, completed_at, status, attempt, component_type, "
            "component_id, user_id. Unknown sort fields are ignored."
        ),
    )
    async def list_jobs(
        request: Request,
        status: Optional[List[str]] = Query(
            default=None, description="Status filter; repeatable to match any of several statuses"
        ),
        session_id: Optional[List[str]] = Query(
            default=None, description="Session filter; repeatable to match any of several sessions"
        ),
        limit: int = Query(default=20, description="Number of jobs to return per page", ge=1, le=1000),
        page: int = Query(default=1, description="Page number for pagination", ge=1),
        sort_by: str = Query(default="created_at", description="Field to sort jobs by"),
        sort_order: SortOrder = Query(default=SortOrder.DESC, description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[QueueJobSchema]:
        for s in status or []:
            if s not in JOB_STATUSES:
                raise HTTPException(status_code=400, detail=f"Invalid status {s!r}; expected one of {JOB_STATUSES}")
        scoped_user_id = _queue_list_user_id(request, session_id)
        store = _get_store(request)
        jobs, total_count = await store.list_jobs(
            status=status or None,
            session_id=session_id or None,
            user_id=scoped_user_id,
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order.value,
        )
        return PaginatedResponse(
            data=[QueueJobSchema(**job) for job in jobs],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=(total_count + limit - 1) // limit,
                total_count=total_count,
            ),
        )

    @router.get(
        "/jobs/{job_id}",
        operation_id="get_queue_job",
        summary="Get Queue Job",
        response_model=QueueJobSchema,
        dependencies=[Depends(_require_queue_admin)],
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
        response_model=QueueJobSchema,
        dependencies=[Depends(_require_queue_admin)],
        description=(
            "Requeue a terminally failed or cancelled job for one more execution "
            "(raises its attempt budget by one). The operator remedy for crashed runs "
            "under the no-silent-re-execution default. Requeueing a CANCELLED job "
            "whose cancellation intent is still live requires clear_cancellation=true "
            "- an explicit override of the recorded cancel; without it the re-driven "
            "attempt is re-cancelled at its first checkpoint. Requeueing a job that "
            "FAILED within the last lock_grace seconds requires force=true: its worker "
            "may still be executing (swept-but-alive), and a second producer would race "
            "unfenced writes."
        ),
    )
    async def requeue_job(request: Request, job_id: str, clear_cancellation: bool = False, force: bool = False):
        store = _get_store(request)
        # Live-zombie gate, kept as OPS HYGIENE now that the write fences
        # exist: a job FAILED within the last lock_grace was, in the worst
        # case, swept while its worker was actually alive - the sweep only
        # proves heartbeats stopped, not that execution did (the documented
        # event-loop-starvation mode). The fences make a requeue inside that
        # window SAFE (the zombie's row/stream writes are refused once the
        # new attempt begins), but not free: it burns an attempt re-running
        # work that may be about to finish, and the finished-work-wins
        # outcome the operator probably wants arrives by simply waiting.
        # Refuse with 409 until the grace elapses, unless the operator
        # explicitly forces. Heuristic by construction: completed_at is DB
        # time on Postgres and this compares against app time, so clock skew
        # shifts the refusal window - never ownership, which does not depend
        # on this gate. Cancelled jobs skip the gate: cancellation only
        # tombstones waiting tickets, so no zombie attempt can exist.
        gate_job = await store.get_job(job_id)
        if gate_job is not None and gate_job.get("status") == "failed" and not force:
            import time as _time

            worker = getattr(request.app.state, "queue_worker", None)
            lock_grace = worker.config.lock_grace_seconds if worker is not None else 60
            completed_at = gate_job.get("completed_at")
            if completed_at is not None and (_time.time() - completed_at) < lock_grace:
                raise HTTPException(
                    status_code=409,
                    detail=f"Job {job_id} failed within the last {lock_grace}s and its worker may "
                    "still be executing (a sweep proves lost heartbeats, not stopped execution). "
                    "Retry after the lock grace elapses, or pass force=true to override.",
                )
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
        dependencies=[Depends(_require_queue_admin)],
        description="Job counts by status and the oldest queued job's age - the queue-health signals to alert on.",
    )
    async def stats(request: Request):
        store = _get_store(request)
        return await store.queue_stats()

    return router
