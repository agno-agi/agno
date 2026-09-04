"""API for metrics derived from OS-level data sources.

What the authorization counts mean: every enforcement choke point records one
``access.allowed`` / ``access.denied`` decision per check (see
``agno.os.authz.audit.record_decision``). They are decisions, not requests or users:

* A request that passes the route gate and is then denied by the per-resource gate
  contributes one allow AND one deny.
* Allow-by-default routes (no required scopes) still record an allow, and so do the
  metrics endpoints themselves, so a dashboard polling this API adds to ``allowed``.
* Allowed + denied is therefore the number of authorization checks, not of requests.

Refreshes are incremental for decisions: only audit rows at or after the last two
cached days are re-aggregated; earlier days keep their cached counts, so a refresh
stays cheap as the decision trail grows and survives audit retention purges.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from starlette.concurrency import run_in_threadpool

from agno.db.os_metrics_aggregation import SECONDS_PER_DAY
from agno.os.auth import get_authentication_dependency
from agno.os.routers.metrics.schemas import (
    DayAggregatedOSMetrics,
    MetricsRefreshResponse,
    MetricsRefreshStatusResponse,
    OSMetricsResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import to_utc_datetime

if TYPE_CHECKING:
    from agno.os.authz.audit import AuditSink
    from agno.os.authz.user_store import ManagedUserStore

logger = logging.getLogger(__name__)


def get_os_metrics_router(
    user_store: "ManagedUserStore",
    audit_sink: Optional["AuditSink"] = None,
    settings: AgnoAPISettings = AgnoAPISettings(),
    prefix: str = "/metrics/os",
) -> APIRouter:
    """Build the authenticated router for metrics derived from OS-level sources."""
    router = APIRouter(
        prefix=prefix,
        tags=["OS metrics"],
        dependencies=[Depends(get_authentication_dependency(settings))],
    )
    # Per-process: under several workers each one tracks its own refresh, so this is
    # a courtesy status, not a lock. Mirrors the run-metrics router.
    refresh_state: Optional[MetricsRefreshStatusResponse] = None

    def _calculate_os_metrics() -> List[dict]:
        if audit_sink is None:
            return user_store.calculate_os_metrics(decision_metrics=[])

        # Re-aggregate from the day before the latest cached day so a decision written
        # just before a refresh (or by a worker with a slightly behind clock) is still
        # picked up; everything older keeps its cached counts.
        cached, _ = user_store.os_metrics()
        latest_day = max((int(row["date"]) for row in cached), default=None)
        decisions_since = latest_day - SECONDS_PER_DAY if latest_day is not None else None
        decision_metrics = audit_sink.aggregate_decisions_by_day(starting_at=decisions_since)
        return user_store.calculate_os_metrics(decision_metrics=decision_metrics, decisions_since=decisions_since)

    def _date_bounds(starting_date: Optional[date], ending_date: Optional[date]) -> tuple[Optional[int], Optional[int]]:
        if starting_date is not None and ending_date is not None and starting_date > ending_date:
            raise HTTPException(status_code=422, detail="starting_date must be on or before ending_date")
        starting_at = (
            int(datetime.combine(starting_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
            if starting_date is not None
            else None
        )
        ending_before = (
            int(
                (
                    datetime.combine(ending_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
                ).timestamp()
            )
            if ending_date is not None
            else None
        )
        return starting_at, ending_before

    def _mark_running() -> None:
        nonlocal refresh_state
        refresh_state = MetricsRefreshStatusResponse(status="running", started_at=datetime.now(timezone.utc))

    def _record_outcome(error: Optional[str] = None) -> None:
        nonlocal refresh_state
        refresh_state = MetricsRefreshStatusResponse(
            status="failed" if error else "completed",
            started_at=refresh_state.started_at if refresh_state else None,
            finished_at=datetime.now(timezone.utc),
            error=error,
        )

    async def _do_refresh() -> None:
        try:
            await run_in_threadpool(_calculate_os_metrics)
        except Exception as error:
            logger.exception("OS metrics refresh failed")
            _record_outcome(str(error))
        else:
            _record_outcome()

    @router.get("", response_model=OSMetricsResponse, operation_id="get_os_metrics", summary="Get OS Metrics")
    async def get_os_metrics(
        starting_date: Optional[date] = Query(default=None, description="Starting date (YYYY-MM-DD)"),
        ending_date: Optional[date] = Query(default=None, description="Ending date (YYYY-MM-DD)"),
    ) -> OSMetricsResponse:
        starting_at, ending_before = _date_bounds(starting_date, ending_date)
        try:
            rows, latest_updated_at = await run_in_threadpool(
                user_store.os_metrics, starting_at=starting_at, ending_before=ending_before
            )
        except Exception as error:
            logger.exception("GET /metrics/os failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS metrics: {str(error)}")
        return OSMetricsResponse(
            metrics=[DayAggregatedOSMetrics.from_dict(row) for row in rows],
            updated_at=to_utc_datetime(latest_updated_at),
        )

    @router.post(
        "/refresh",
        response_model=Union[List[DayAggregatedOSMetrics], MetricsRefreshResponse],
        operation_id="refresh_os_metrics",
        summary="Refresh OS Metrics",
    )
    async def refresh_os_metrics(
        response: Response,
        background_tasks: BackgroundTasks,
        background: bool = Query(default=False, description="Run the refresh in the background"),
    ) -> Union[List[DayAggregatedOSMetrics], MetricsRefreshResponse]:
        if refresh_state is not None and refresh_state.status == "running":
            return MetricsRefreshResponse(
                status="already_running", message="An OS metrics refresh is already in progress"
            )

        _mark_running()
        if background:
            response.status_code = 202
            background_tasks.add_task(_do_refresh)
            return MetricsRefreshResponse(status="started", message="OS metrics refresh started in background")

        try:
            rows = await run_in_threadpool(_calculate_os_metrics)
        except Exception as error:
            _record_outcome(str(error))
            raise HTTPException(status_code=500, detail=f"Error refreshing OS metrics: {str(error)}")
        _record_outcome()
        return [DayAggregatedOSMetrics.from_dict(row) for row in rows]

    @router.get(
        "/refresh/status",
        response_model=MetricsRefreshStatusResponse,
        operation_id="get_os_metrics_refresh_status",
        summary="Get OS Metrics Refresh Status",
    )
    async def get_os_metrics_refresh_status() -> MetricsRefreshStatusResponse:
        return refresh_state or MetricsRefreshStatusResponse(status="idle")

    return router
