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


def _get_store(request: Request):
    worker = getattr(request.app.state, "queue_worker", None)
    if worker is None:
        raise HTTPException(status_code=404, detail="Durable job queue is not enabled")
    return worker.store


def get_queue_router(os: "AgentOS", settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        prefix="/queue",
        tags=["Run Queue"],
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
        summary="List Run Queue Jobs",
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
        summary="Get Run Queue Job",
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
        summary="Requeue Failed Run Queue Job",
        description=(
            "Requeue a terminally failed or cancelled job for one more execution "
            "(raises its attempt budget by one). The operator remedy for crashed runs "
            "under the no-silent-re-execution default."
        ),
    )
    async def requeue_job(request: Request, job_id: str):
        store = _get_store(request)
        if not await store.requeue_job(job_id):
            raise HTTPException(status_code=400, detail=f"Job {job_id} not found or not in a requeueable state")
        return await store.get_job(job_id)

    @router.get(
        "/stats",
        operation_id="get_queue_stats",
        summary="Run Queue Stats",
        description="Job counts by status and the oldest queued job's age - the queue-health signals to alert on.",
    )
    async def stats(request: Request):
        store = _get_store(request)
        return await store.queue_stats()

    return router
