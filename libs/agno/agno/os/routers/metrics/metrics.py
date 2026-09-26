import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRouter
from starlette.concurrency import run_in_threadpool

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.utils import (
    aggregate_metrics_by_date,
    identify_metrics_by_owner,
    is_legacy_metric,
    merge_os_metrics_json,
    merge_os_model_metrics,
    os_metrics_percentile,
)
from agno.exceptions import AgnoError
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_db_and_scope
from agno.os.routers.metrics.schemas import (
    DayAggregatedMetrics,
    DayLatencyMetrics,
    DayRunMetrics,
    DaySessionMetrics,
    DayTokenMetrics,
    MetricsRefreshResponse,
    MetricsRefreshStatusResponse,
    MetricsResponse,
    ModelUsage,
    OSLatencyMetricsResponse,
    OSMetricsRefreshStatusResponse,
    OSModelMetricsResponse,
    OSRunMetricsResponse,
    OSSessionMetricsResponse,
    OSTokenMetricsResponse,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import AgnoHTTPException, get_db, to_utc_datetime
from agno.remote.base import RemoteDb
from agno.run.base import RunStatus
from agno.utils.log import log_error

logger = logging.getLogger(__name__)

# Without bounds a route covers the last 30 days. Both days are inclusive, so a starting_date
# equal to the ending_date covers that one day.
DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365


def _window(starting_date: Optional[date], ending_date: Optional[date]) -> Tuple[date, date]:
    """The UTC days a route covers, with the same bounds GET /metrics takes.

    Without an end the window ends today, without a start it covers the last
    DEFAULT_WINDOW_DAYS days.
    """
    if ending_date is None:
        ending_date = datetime.now(timezone.utc).date()
    if starting_date is None:
        starting_date = ending_date - timedelta(days=DEFAULT_WINDOW_DAYS - 1)
    if starting_date > ending_date:
        raise HTTPException(status_code=400, detail="starting_date must not be after ending_date")
    if (ending_date - starting_date).days >= MAX_WINDOW_DAYS:
        raise HTTPException(status_code=400, detail=f"The window must not cover more than {MAX_WINDOW_DAYS} days")
    return starting_date, ending_date


def get_metrics_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    settings: AgnoAPISettings = AgnoAPISettings(),
    os_db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
    **kwargs,
) -> APIRouter:
    """Create metrics router with comprehensive OpenAPI documentation for system metrics and analytics endpoints."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Metrics"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, dbs=dbs, os_db=os_db)


def attach_routes(
    router: APIRouter,
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    os_db: Optional[Union[BaseDb, AsyncBaseDb]] = None,
) -> APIRouter:
    @router.get(
        "/metrics",
        response_model=MetricsResponse,
        status_code=200,
        operation_id="get_metrics",
        summary="Get AgentOS Metrics",
        description=(
            "Retrieve AgentOS metrics and analytics data for a specified date range. "
            "If no date range is specified, returns all available metrics."
        ),
        responses={
            200: {
                "description": "Metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "metrics": [
                                {
                                    "id": "2025-07-31_daily",
                                    "agent_runs_count": 5,
                                    "agent_sessions_count": 5,
                                    "team_runs_count": 0,
                                    "team_sessions_count": 0,
                                    "workflow_runs_count": 0,
                                    "workflow_sessions_count": 0,
                                    "users_count": 1,
                                    "token_metrics": {
                                        "input_tokens": 448,
                                        "output_tokens": 148,
                                        "total_tokens": 596,
                                        "audio_tokens": 0,
                                        "input_audio_tokens": 0,
                                        "output_audio_tokens": 0,
                                        "cached_tokens": 0,
                                        "cache_write_tokens": 0,
                                        "reasoning_tokens": 0,
                                    },
                                    "model_metrics": [{"model_id": "gpt-4o", "model_provider": "OpenAI", "count": 5}],
                                    "date": "2025-07-31T00:00:00Z",
                                    "created_at": "2025-07-31T12:38:52Z",
                                    "updated_at": "2025-07-31T12:49:01Z",
                                }
                            ]
                        }
                    }
                },
            },
            400: {"description": "Invalid date range parameters", "model": BadRequestResponse},
            500: {"description": "Failed to retrieve metrics", "model": InternalServerErrorResponse},
        },
    )
    async def get_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's metrics. Ignored for non-admin callers"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to query metrics from"),
        table: Optional[str] = Query(default=None, description="The database table to use"),
    ) -> MetricsResponse:
        try:
            db, effective_user_id = await resolve_db_and_scope(request, dbs, db_id, table, fallback_user_id=user_id)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.get_metrics(
                    starting_date=starting_date, ending_date=ending_date, db_id=db_id, table=table, headers=headers
                )

            if isinstance(db, AsyncBaseDb):
                metrics, latest_updated_at = await db.get_metrics(
                    starting_date=starting_date, ending_date=ending_date, user_id=effective_user_id
                )
            else:
                metrics, latest_updated_at = await run_in_threadpool(
                    db.get_metrics,
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                )

            # A read of one owner keeps that owner's rows; every other read collapses to the
            # legacy one-row-per-day shape.
            if effective_user_id is None:
                metrics = aggregate_metrics_by_date(metrics)
            else:
                # The unowned bucket is asked for by the same sentinel the SQL adapters stamp
                # pre-ownership records with, and those hold every user's traffic
                if not effective_user_id:
                    metrics = [metric for metric in metrics if not is_legacy_metric(metric)]
                metrics = identify_metrics_by_owner(metrics, effective_user_id)

            return MetricsResponse(
                metrics=[DayAggregatedMetrics.from_dict(metric) for metric in metrics],
                updated_at=to_utc_datetime(latest_updated_at),
            )

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /metrics failed")
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

    # Most recent refresh state per db id, doubling as the in-flight guard ('running').
    # Only mutated on the event loop (the sync calculation itself runs in the threadpool),
    # so no lock is needed. Per-process: each worker tracks the refreshes it started.
    refresh_states: dict[str, MetricsRefreshStatusResponse] = {}

    def _refresh_is_running(refresh_key: str) -> bool:
        state = refresh_states.get(refresh_key)
        return state is not None and state.status == "running"

    def _mark_refresh_running(refresh_key: str) -> None:
        refresh_states[refresh_key] = MetricsRefreshStatusResponse(
            status="running", started_at=datetime.now(timezone.utc)
        )

    def _record_refresh_outcome(refresh_key: str, error: Optional[str] = None) -> None:
        state = refresh_states.get(refresh_key)
        refresh_states[refresh_key] = MetricsRefreshStatusResponse(
            status="failed" if error else "completed",
            started_at=state.started_at if state else None,
            finished_at=datetime.now(timezone.utc),
            error=error,
        )

    def _already_running_response() -> MetricsRefreshResponse:
        return MetricsRefreshResponse(
            status="already_running", message="A metrics refresh is already in progress for this database"
        )

    async def _do_refresh(
        db: Union[BaseDb, AsyncBaseDb, RemoteDb],
        db_id: Optional[str],
        table: Optional[str],
        headers: Optional[dict],
    ) -> None:
        refresh_key = str(db.id)
        try:
            if isinstance(db, RemoteDb):
                await db.refresh_metrics(db_id=db_id, table=table, headers=headers, background=True)
            elif isinstance(db, AsyncBaseDb):
                await db.calculate_metrics()
            else:
                await run_in_threadpool(db.calculate_metrics)
        except Exception as e:
            logger.error(f"Metrics refresh failed: {e}")
            _record_refresh_outcome(refresh_key, error=str(e))
        else:
            _record_refresh_outcome(refresh_key)

    @router.post(
        "/metrics/refresh",
        response_model=Union[List[DayAggregatedMetrics], MetricsRefreshResponse],
        status_code=200,
        operation_id="refresh_metrics",
        summary="Refresh Metrics",
        description=(
            "Manually trigger recalculation of system metrics from raw data. "
            "This operation analyzes system activity logs and regenerates aggregated metrics. "
            "Useful for ensuring metrics are up-to-date or after system maintenance. "
            "By default the refresh runs synchronously and returns the refreshed metrics. "
            "Pass background=true to run the refresh in the background instead: the endpoint "
            "returns 202 Accepted immediately and GET /metrics can be polled for results. "
            "If a background refresh is already in progress for the target database, "
            "returns status 'already_running' without starting a new one."
        ),
        responses={
            200: {
                "description": "Metrics refreshed successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "2025-08-12_daily",
                                "agent_runs_count": 2,
                                "agent_sessions_count": 2,
                                "team_runs_count": 0,
                                "team_sessions_count": 0,
                                "workflow_runs_count": 0,
                                "workflow_sessions_count": 0,
                                "users_count": 1,
                                "token_metrics": {
                                    "input_tokens": 256,
                                    "output_tokens": 441,
                                    "total_tokens": 697,
                                },
                                "model_metrics": [{"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": 2}],
                                "date": "2025-08-12T00:00:00Z",
                                "created_at": "2025-08-12T08:01:47Z",
                                "updated_at": "2025-08-12T08:01:47Z",
                            }
                        ]
                    }
                },
            },
            202: {
                "description": "Background refresh started",
                "content": {
                    "application/json": {
                        "example": {"status": "started", "message": "Metrics refresh started in background"}
                    }
                },
            },
            500: {"description": "Failed to refresh metrics", "model": InternalServerErrorResponse},
        },
    )
    async def calculate_metrics(
        request: Request,
        response: Response,
        background_tasks: BackgroundTasks,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for metrics calculation"),
        table: Optional[str] = Query(default=None, description="Table to use for metrics calculation"),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's metrics. Ignored for non-admin callers"
        ),
        background: bool = Query(
            default=False, description="Run the refresh in the background and return 202 immediately"
        ),
    ) -> Union[List[DayAggregatedMetrics], MetricsRefreshResponse]:
        try:
            # Resolved before the background branch so an identity-less token cannot start a refresh.
            db, effective_user_id = await resolve_db_and_scope(request, dbs, db_id, table, fallback_user_id=user_id)

            headers = None
            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None

            refresh_key = str(db.id)

            if background:
                response.status_code = 202
                if _refresh_is_running(refresh_key):
                    return _already_running_response()

                _mark_refresh_running(refresh_key)
                background_tasks.add_task(_do_refresh, db, db_id, table, headers)

                return MetricsRefreshResponse(status="started", message="Metrics refresh started in background")

            # A remote database keeps its own state, so it is left to guard itself
            if isinstance(db, RemoteDb):
                return await db.refresh_metrics(db_id=db_id, table=table, headers=headers)

            # The same guard the background path has: without it every concurrent caller
            # starts its own full recalculation of every date the database still needs
            if _refresh_is_running(refresh_key):
                return _already_running_response()

            _mark_refresh_running(refresh_key)
            try:
                if isinstance(db, AsyncBaseDb):
                    result = await db.calculate_metrics()
                else:
                    result = await run_in_threadpool(db.calculate_metrics)
            except Exception as e:
                _record_refresh_outcome(refresh_key, error=str(e))
                raise
            _record_refresh_outcome(refresh_key)

            if result is None:
                return []

            # A read of one owner keeps that owner's rows; every other read collapses to the
            # legacy one-row-per-day shape.
            if effective_user_id is not None:
                owned = [metric for metric in result if metric.get("user_id") == effective_user_id]
                result = identify_metrics_by_owner(owned, effective_user_id)
            else:
                result = aggregate_metrics_by_date(result)

            return [DayAggregatedMetrics.from_dict(metric) for metric in result]

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

    @router.get(
        "/metrics/refresh/status",
        response_model=MetricsRefreshStatusResponse,
        status_code=200,
        operation_id="get_metrics_refresh_status",
        summary="Get Metrics Refresh Status",
        description=(
            "Get the status of the most recent metrics refresh for the target database. "
            "Returns 'running' while a refresh is in progress, then 'completed' or 'failed' with "
            "the finish timestamp — the state updates even when a refresh completes without "
            "writing new data. Returns 'idle' if no refresh has been triggered since this server "
            "process started. For remote databases the status is fetched from the remote AgentOS. "
            "Intended for polling after starting a background refresh via POST /metrics/refresh?background=true."
        ),
        responses={
            200: {
                "description": "Current refresh status",
                "content": {
                    "application/json": {
                        "example": {
                            "status": "completed",
                            "started_at": "2025-08-12T08:01:47Z",
                            "finished_at": "2025-08-12T08:01:49Z",
                            "error": None,
                        }
                    }
                },
            },
            400: {"description": "Invalid request", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            500: {"description": "Failed to get refresh status", "model": InternalServerErrorResponse},
        },
    )
    async def get_metrics_refresh_status(
        request: Request,
        db_id: Optional[str] = Query(default=None, description="Database ID to get the refresh status for"),
        table: Optional[str] = Query(default=None, description="Table to get the refresh status for"),
    ) -> MetricsRefreshStatusResponse:
        try:
            db = await get_db(dbs, db_id, table)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.get_metrics_refresh_status(db_id=db_id, table=table, headers=headers)

            state = refresh_states.get(str(db.id))
            if state is None:
                return MetricsRefreshStatusResponse(status="idle")
            return state

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics refresh status: {str(e)}")

    def _require_os_db() -> Union[BaseDb, AsyncBaseDb]:
        if os_db is None:
            raise HTTPException(
                status_code=503,
                detail="Metrics not available: pass a `db` to AgentOS to enable this feature.",
            )
        return os_db

    def _owner(request: Request, user_id: Optional[str]) -> Optional[str]:
        """The owner a read covers: the caller's own scope, else the requested user_id, else every owner."""
        scoped_user_id = get_scoped_user_id(request)
        return scoped_user_id if scoped_user_id is not None else user_id

    async def _os_metrics(
        db: Union[BaseDb, AsyncBaseDb],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        fields: List[str],
    ) -> Tuple[List[Dict[str, Any]], Optional[datetime]]:
        """The window's OS metrics, totalled by the database per day, oldest first."""
        try:
            if isinstance(db, AsyncBaseDb):
                totals, latest_updated_at = await db.get_os_metrics(
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    fields=fields,
                )
            else:
                totals, latest_updated_at = await run_in_threadpool(
                    db.get_os_metrics,
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    fields=fields,
                )
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="OS metrics not supported by the configured database")
        return totals, to_utc_datetime(latest_updated_at)

    async def _os_metrics_by_day(
        db: Union[BaseDb, AsyncBaseDb],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        fields: List[str],
    ) -> Tuple[Dict[date, Dict[str, Any]], Optional[datetime]]:
        """The window's OS metrics, totalled per day by the database, keyed by day."""
        totals, updated_at = await _os_metrics(db, effective_user_id, starting_date, ending_date, fields)
        return {day_totals["date"]: day_totals for day_totals in totals}, updated_at

    def _days(starting_date: date, ending_date: date) -> List[date]:
        """Every day of the window, a day without rows included."""
        return [starting_date + timedelta(days=offset) for offset in range((ending_date - starting_date).days + 1)]

    def _previous_starting_date(starting_date: date, ending_date: date) -> date:
        """The first day of the window of the same length that ends the day before this one starts.

        Both windows then come from one read.
        """
        return starting_date - timedelta(days=(ending_date - starting_date).days + 1)

    def _change_percent(total: int, previous_total: int) -> Optional[float]:
        # Nothing before means no rate to compare against, rather than an infinite rise
        return round((total - previous_total) / previous_total * 100, 1) if previous_total else None

    def _average(total: int, count: int) -> Optional[int]:
        return round(total / count) if count else None

    def _latency(duration_metrics: Dict[str, Any], buckets: Dict[str, Any]) -> Dict[str, Optional[int]]:
        """The latency numbers of one set of totals: the runs, and the average, median, p95 and max of each timing."""
        duration_ms_buckets = buckets.get("duration_ms_buckets", {})
        time_to_first_token_ms_buckets = buckets.get("time_to_first_token_ms_buckets", {})
        model_call_ms_buckets = buckets.get("model_call_ms_buckets", {})
        max_duration_ms = duration_metrics.get("max_duration_ms")
        max_time_to_first_token_ms = duration_metrics.get("max_time_to_first_token_ms")
        max_model_call_ms = duration_metrics.get("max_model_call_ms")
        return {
            "runs_count": duration_metrics.get("duration_runs_count", 0),
            "avg_duration_ms": _average(
                duration_metrics.get("total_duration_ms", 0), duration_metrics.get("duration_runs_count", 0)
            ),
            "median_duration_ms": os_metrics_percentile(duration_ms_buckets, 0.5, max_duration_ms),
            "p95_duration_ms": os_metrics_percentile(duration_ms_buckets, 0.95, max_duration_ms),
            "max_duration_ms": max_duration_ms,
            "avg_time_to_first_token_ms": _average(
                duration_metrics.get("total_time_to_first_token_ms", 0),
                duration_metrics.get("time_to_first_token_runs_count", 0),
            ),
            "median_time_to_first_token_ms": os_metrics_percentile(
                time_to_first_token_ms_buckets, 0.5, max_time_to_first_token_ms
            ),
            "p95_time_to_first_token_ms": os_metrics_percentile(
                time_to_first_token_ms_buckets, 0.95, max_time_to_first_token_ms
            ),
            "max_time_to_first_token_ms": max_time_to_first_token_ms,
            "avg_model_call_ms": _average(
                duration_metrics.get("total_model_call_ms", 0), duration_metrics.get("model_calls_count", 0)
            ),
            "median_model_call_ms": os_metrics_percentile(model_call_ms_buckets, 0.5, max_model_call_ms),
            "p95_model_call_ms": os_metrics_percentile(model_call_ms_buckets, 0.95, max_model_call_ms),
            "max_model_call_ms": max_model_call_ms,
        }

    @router.get(
        "/os/metrics/sessions",
        response_model=OSSessionMetricsResponse,
        status_code=200,
        operation_id="get_os_session_metrics",
        summary="Get OS Session Metrics",
        description=(
            "Retrieve the sessions created on each day of a date range, their total, and how that total "
            "compares with the date range of the same length before it. "
            "If no date range is specified, covers the last 30 days."
        ),
        responses={
            200: {
                "description": "OS session metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "metrics": [{"date": "2025-07-31T00:00:00Z", "sessions_count": 7}],
                            "total_sessions": 200,
                            "previous_total_sessions": 161,
                            "change_percent": 24.2,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            500: {"description": "Failed to get OS session metrics", "model": InternalServerErrorResponse},
            501: {"description": "OS metrics not supported by the configured database"},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def get_os_session_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None,
            description="Starting date for the window (YYYY-MM-DD format). Defaults to 29 days before ending_date",
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for the window (YYYY-MM-DD format). Defaults to today"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's sessions. Ignored for non-admin callers"
        ),
    ) -> OSSessionMetricsResponse:
        try:
            db = _require_os_db()
            starting_date, ending_date = _window(starting_date, ending_date)
            previous_starting_date = _previous_starting_date(starting_date, ending_date)
            totals, updated_at = await _os_metrics_by_day(
                db, _owner(request, user_id), previous_starting_date, ending_date, ["sessions_count"]
            )

            metrics = [
                DaySessionMetrics(
                    date=to_utc_datetime(day), sessions_count=totals.get(day, {}).get("sessions_count", 0)
                )
                for day in _days(starting_date, ending_date)
            ]
            total_sessions = sum(day_metrics.sessions_count for day_metrics in metrics)
            previous_total_sessions = sum(
                day_totals["sessions_count"] for day, day_totals in totals.items() if day < starting_date
            )
            return OSSessionMetricsResponse(
                metrics=metrics,
                total_sessions=total_sessions,
                previous_total_sessions=previous_total_sessions,
                change_percent=_change_percent(total_sessions, previous_total_sessions),
                window_days=(ending_date - starting_date).days + 1,
                updated_at=updated_at,
            )

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_error(f"Error getting OS session metrics: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OS session metrics: {str(e)}")

    @router.get(
        "/os/metrics/tokens",
        response_model=OSTokenMetricsResponse,
        status_code=200,
        operation_id="get_os_token_metrics",
        summary="Get OS Token Metrics",
        description=(
            "Retrieve the tokens used on each day of a date range, their total, and how that total "
            "compares with the date range of the same length before it. "
            "If no date range is specified, covers the last 30 days."
        ),
        responses={
            200: {
                "description": "OS token metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "metrics": [
                                {
                                    "date": "2025-07-31T00:00:00Z",
                                    "tokens_count": 5962,
                                }
                            ],
                            "total_tokens": 184500,
                            "previous_total_tokens": 150000,
                            "change_percent": 23.0,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            500: {"description": "Failed to get OS token metrics", "model": InternalServerErrorResponse},
            501: {"description": "OS metrics not supported by the configured database"},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def get_os_token_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None,
            description="Starting date for the window (YYYY-MM-DD format). Defaults to 29 days before ending_date",
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for the window (YYYY-MM-DD format). Defaults to today"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's tokens. Ignored for non-admin callers"
        ),
    ) -> OSTokenMetricsResponse:
        try:
            db = _require_os_db()
            starting_date, ending_date = _window(starting_date, ending_date)
            previous_starting_date = _previous_starting_date(starting_date, ending_date)
            totals, updated_at = await _os_metrics_by_day(
                db, _owner(request, user_id), previous_starting_date, ending_date, ["token_metrics"]
            )

            metrics = []
            for day in _days(starting_date, ending_date):
                token_metrics = totals.get(day, {}).get("token_metrics", {})
                metrics.append(
                    DayTokenMetrics(date=to_utc_datetime(day), tokens_count=token_metrics.get("total_tokens", 0))
                )
            total_tokens = sum(day_metrics.tokens_count for day_metrics in metrics)
            previous_total_tokens = sum(
                day_totals["token_metrics"].get("total_tokens", 0)
                for day, day_totals in totals.items()
                if day < starting_date
            )
            return OSTokenMetricsResponse(
                metrics=metrics,
                total_tokens=total_tokens,
                previous_total_tokens=previous_total_tokens,
                change_percent=_change_percent(total_tokens, previous_total_tokens),
                window_days=(ending_date - starting_date).days + 1,
                updated_at=updated_at,
            )

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_error(f"Error getting OS token metrics: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OS token metrics: {str(e)}")

    @router.get(
        "/os/metrics/models",
        response_model=OSModelMetricsResponse,
        status_code=200,
        operation_id="get_os_model_metrics",
        summary="Get OS Model Metrics",
        description=(
            "Retrieve how many runs each model served over a date range. "
            "If no date range is specified, covers the last 30 days."
        ),
        responses={
            200: {
                "description": "OS model metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "models": [
                                {
                                    "model_id": "gpt-5.5",
                                    "model_provider": "OpenAI",
                                    "run_count": 96,
                                    "run_share": 80.0,
                                }
                            ],
                            "total_model_runs": 120,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            500: {"description": "Failed to get OS model metrics", "model": InternalServerErrorResponse},
            501: {"description": "OS metrics not supported by the configured database"},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def get_os_model_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None,
            description="Starting date for the window (YYYY-MM-DD format). Defaults to 29 days before ending_date",
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for the window (YYYY-MM-DD format). Defaults to today"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's metrics. Ignored for non-admin callers"
        ),
    ) -> OSModelMetricsResponse:
        try:
            db = _require_os_db()
            starting_date, ending_date = _window(starting_date, ending_date)
            totals, updated_at = await _os_metrics(
                db, _owner(request, user_id), starting_date, ending_date, ["model_metrics"]
            )

            model_metrics: List[Dict[str, Any]] = []
            for day_totals in totals:
                merge_os_model_metrics(model_metrics, day_totals["model_metrics"])

            # One entry per model and caller, so the runs add up per model
            run_counts: Dict[Tuple[str, Optional[str]], int] = {}
            for model_metric in model_metrics:
                key = (model_metric["model_id"], model_metric["model_provider"] or None)
                run_counts[key] = run_counts.get(key, 0) + model_metric["count"]

            total_model_runs = sum(run_counts.values())
            return OSModelMetricsResponse(
                models=[
                    ModelUsage(
                        model_id=model_id,
                        model_provider=model_provider,
                        run_count=count,
                        run_share=round(count / total_model_runs * 100, 1),
                    )
                    for (model_id, model_provider), count in sorted(
                        run_counts.items(), key=lambda item: (-item[1], item[0][0])
                    )
                ],
                total_model_runs=total_model_runs,
                window_days=(ending_date - starting_date).days + 1,
                updated_at=updated_at,
            )

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_error(f"Error getting OS model metrics: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OS model metrics: {str(e)}")

    @router.get(
        "/os/metrics/runs",
        response_model=OSRunMetricsResponse,
        status_code=200,
        operation_id="get_os_run_metrics",
        summary="Get OS Run Metrics",
        description=(
            "Retrieve the runs started on each day of a date range by status, their total, the share of "
            "finished runs that completed, and how the total compares with the date range of the same length "
            "before it. A team member's run counts as a run of its own, beside the team's run. "
            "If no date range is specified, covers the last 30 days."
        ),
        responses={
            200: {
                "description": "OS run metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "metrics": [
                                {
                                    "date": "2025-07-31T00:00:00Z",
                                    "runs_count": 12,
                                    "status_metrics": {"COMPLETED": 10, "ERROR": 1, "CANCELLED": 1},
                                }
                            ],
                            "total_runs": 310,
                            "status_metrics": {"COMPLETED": 281, "ERROR": 17, "CANCELLED": 8, "PAUSED": 4},
                            "success_rate": 91.8,
                            "previous_total_runs": 262,
                            "change_percent": 18.3,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            500: {"description": "Failed to get OS run metrics", "model": InternalServerErrorResponse},
            501: {"description": "OS metrics not supported by the configured database"},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def get_os_run_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None,
            description="Starting date for the window (YYYY-MM-DD format). Defaults to 29 days before ending_date",
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for the window (YYYY-MM-DD format). Defaults to today"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's runs. Ignored for non-admin callers"
        ),
    ) -> OSRunMetricsResponse:
        try:
            db = _require_os_db()
            starting_date, ending_date = _window(starting_date, ending_date)
            previous_starting_date = _previous_starting_date(starting_date, ending_date)
            totals, updated_at = await _os_metrics_by_day(
                db, _owner(request, user_id), previous_starting_date, ending_date, ["runs_count", "status_metrics"]
            )

            metrics = []
            status_metrics: Dict[str, int] = {}
            for day in _days(starting_date, ending_date):
                day_totals = totals.get(day, {})
                day_status_metrics = day_totals.get("status_metrics", {})
                metrics.append(
                    DayRunMetrics(
                        date=to_utc_datetime(day),
                        runs_count=day_totals.get("runs_count", 0),
                        status_metrics=day_status_metrics,
                    )
                )
                merge_os_metrics_json(status_metrics, day_status_metrics)

            total_runs = sum(day_metrics.runs_count for day_metrics in metrics)
            previous_total_runs = sum(
                day_totals["runs_count"] for day, day_totals in totals.items() if day < starting_date
            )
            # A run still pending, running or paused has no outcome to rate yet
            finished_runs = sum(
                status_metrics.get(status, 0)
                for status in (RunStatus.completed.value, RunStatus.error.value, RunStatus.cancelled.value)
            )
            return OSRunMetricsResponse(
                metrics=metrics,
                total_runs=total_runs,
                status_metrics=status_metrics,
                success_rate=round(status_metrics.get(RunStatus.completed.value, 0) / finished_runs * 100, 1)
                if finished_runs
                else None,
                previous_total_runs=previous_total_runs,
                change_percent=_change_percent(total_runs, previous_total_runs),
                window_days=(ending_date - starting_date).days + 1,
                updated_at=updated_at,
            )

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_error(f"Error getting OS run metrics: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OS run metrics: {str(e)}")

    @router.get(
        "/os/metrics/latency",
        response_model=OSLatencyMetricsResponse,
        status_code=200,
        operation_id="get_os_latency_metrics",
        summary="Get OS Latency Metrics",
        description=(
            "Retrieve how long completed runs and their model calls took on each day of a date range and "
            "across the whole range: the average, median, 95th percentile and slowest run duration, time to "
            "the first token and model call. Medians and percentiles are approximate. "
            "If no date range is specified, covers the last 30 days."
        ),
        responses={
            200: {
                "description": "OS latency metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "metrics": [
                                {
                                    "date": "2025-07-31T00:00:00Z",
                                    "runs_count": 40,
                                    "avg_duration_ms": 3120,
                                    "median_duration_ms": 2400,
                                    "p95_duration_ms": 8100,
                                    "max_duration_ms": 9404,
                                    "avg_time_to_first_token_ms": 820,
                                    "median_time_to_first_token_ms": 640,
                                    "p95_time_to_first_token_ms": 1900,
                                    "max_time_to_first_token_ms": 2210,
                                    "avg_model_call_ms": 1410,
                                    "median_model_call_ms": 1150,
                                    "p95_model_call_ms": 3600,
                                    "max_model_call_ms": 4120,
                                }
                            ],
                            "runs_count": 310,
                            "avg_duration_ms": 2987,
                            "median_duration_ms": 2250,
                            "p95_duration_ms": 9800,
                            "max_duration_ms": 14210,
                            "avg_time_to_first_token_ms": 790,
                            "median_time_to_first_token_ms": 610,
                            "p95_time_to_first_token_ms": 2400,
                            "max_time_to_first_token_ms": 3104,
                            "avg_model_call_ms": 1390,
                            "median_model_call_ms": 1100,
                            "p95_model_call_ms": 4600,
                            "max_model_call_ms": 6100,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            500: {"description": "Failed to get OS latency metrics", "model": InternalServerErrorResponse},
            501: {"description": "OS metrics not supported by the configured database"},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def get_os_latency_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None,
            description="Starting date for the window (YYYY-MM-DD format). Defaults to 29 days before ending_date",
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for the window (YYYY-MM-DD format). Defaults to today"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's runs. Ignored for non-admin callers"
        ),
    ) -> OSLatencyMetricsResponse:
        try:
            db = _require_os_db()
            starting_date, ending_date = _window(starting_date, ending_date)
            # The medians and p95s are read from each day's bucket counts
            totals, updated_at = await _os_metrics_by_day(
                db, _owner(request, user_id), starting_date, ending_date, ["duration_metrics", "duration_buckets"]
            )

            metrics = []
            window_duration_metrics: Dict[str, Any] = {}
            window_buckets: Dict[str, Any] = {}
            for day in _days(starting_date, ending_date):
                duration_metrics = totals.get(day, {}).get("duration_metrics", {})
                buckets = totals.get(day, {}).get("duration_buckets", {})
                metrics.append(DayLatencyMetrics(date=to_utc_datetime(day), **_latency(duration_metrics, buckets)))
                merge_os_metrics_json(window_duration_metrics, duration_metrics)
                merge_os_metrics_json(window_buckets, buckets)

            return OSLatencyMetricsResponse(
                metrics=metrics,
                window_days=(ending_date - starting_date).days + 1,
                updated_at=updated_at,
                **_latency(window_duration_metrics, window_buckets),
            )

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_error(f"Error getting OS latency metrics: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OS latency metrics: {str(e)}")

    def _stores_os_metrics(db: Union[BaseDb, AsyncBaseDb]) -> bool:
        """Whether the database implements the OS metrics table, both the read and the rebuild, rather than the stubs."""
        db_class = type(db)
        return getattr(db_class, "get_os_metrics", None) not in (
            BaseDb.get_os_metrics,
            AsyncBaseDb.get_os_metrics,
        ) and getattr(db_class, "calculate_os_metrics", None) not in (
            BaseDb.calculate_os_metrics,
            AsyncBaseDb.calculate_os_metrics,
        )

    async def _do_os_refresh(db: Union[BaseDb, AsyncBaseDb], refresh_key: str) -> None:
        try:
            if isinstance(db, AsyncBaseDb):
                await db.calculate_os_metrics()
            else:
                await run_in_threadpool(db.calculate_os_metrics)
        except Exception as e:
            # An exception with no message, like a bare NotImplementedError, is recorded by its type
            error = str(e) or type(e).__name__
            log_error(f"Error refreshing OS metrics: {error}")
            _record_refresh_outcome(refresh_key, error=error)
        else:
            _record_refresh_outcome(refresh_key)

    @router.post(
        "/os/metrics/refresh",
        response_model=Union[MetricsRefreshStatusResponse, MetricsRefreshResponse],
        status_code=200,
        operation_id="refresh_os_metrics",
        summary="Refresh OS Metrics",
        description=(
            "Rebuild the OS metrics of the AgentOS database from its sessions and runs. "
            "By default the refresh runs synchronously and returns its outcome. Pass background=true "
            "to run the refresh in the background instead: the endpoint returns 202 Accepted immediately. "
            "If this server process is already refreshing, returns status 'already_running' without "
            "starting a new one."
        ),
        responses={
            200: {
                "description": "OS metrics refreshed successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "status": "completed",
                            "started_at": "2025-08-12T08:01:47Z",
                            "finished_at": "2025-08-12T08:01:49Z",
                            "error": None,
                        }
                    }
                },
            },
            202: {
                "description": "Background refresh started",
                "content": {
                    "application/json": {
                        "example": {"status": "started", "message": "Metrics refresh started in background"}
                    }
                },
            },
            500: {"description": "Failed to refresh OS metrics", "model": InternalServerErrorResponse},
            501: {"description": "OS metrics not supported by the configured database"},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def refresh_os_metrics(
        request: Request,
        response: Response,
        background_tasks: BackgroundTasks,
        background: bool = Query(
            default=False, description="Run the refresh in the background and return 202 immediately"
        ),
    ) -> Union[MetricsRefreshStatusResponse, MetricsRefreshResponse]:
        try:
            db = _require_os_db()
            # Resolved before the background branch so an identity-less token cannot start a refresh.
            get_scoped_user_id(request)
            # Kept apart from the daily metrics refresh of the same database, which rebuilds another table
            refresh_key = f"os_metrics:{db.id}"
            # Refused before anything runs, so a database without the table is never told "started"
            if not _stores_os_metrics(db):
                raise HTTPException(status_code=501, detail="OS metrics not supported by the configured database")

            if background:
                response.status_code = 202
                if _refresh_is_running(refresh_key):
                    return _already_running_response()

                _mark_refresh_running(refresh_key)
                background_tasks.add_task(_do_os_refresh, db, refresh_key)

                return MetricsRefreshResponse(status="started", message="Metrics refresh started in background")

            # The same guard the background path has: without it every concurrent caller
            # starts its own rebuild of every day the table still needs
            if _refresh_is_running(refresh_key):
                return _already_running_response()

            _mark_refresh_running(refresh_key)
            try:
                if isinstance(db, AsyncBaseDb):
                    await db.calculate_os_metrics()
                else:
                    await run_in_threadpool(db.calculate_os_metrics)
            except Exception as e:
                _record_refresh_outcome(refresh_key, error=str(e) or type(e).__name__)
                raise
            _record_refresh_outcome(refresh_key)

            return refresh_states[refresh_key]

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_error(f"Error refreshing OS metrics: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error refreshing OS metrics: {str(e)}")

    @router.get(
        "/os/metrics/refresh/status",
        response_model=OSMetricsRefreshStatusResponse,
        status_code=200,
        operation_id="get_os_metrics_refresh_status",
        summary="Get OS Metrics Refresh Status",
        description=(
            "Get when the OS metrics of a date range were last written, as the database records it, so every "
            "server process reports the same time. Intended for showing how fresh the numbers are. To refresh "
            "and know when it is done, call POST /os/metrics/refresh without background=true: it answers when "
            "the rebuild has landed. If no date range is specified, covers the last 30 days."
        ),
        responses={
            200: {
                "description": "Current OS metrics refresh status",
                "content": {"application/json": {"example": {"updated_at": "2025-08-12T08:01:49Z"}}},
            },
            500: {"description": "Failed to get OS metrics refresh status", "model": InternalServerErrorResponse},
            501: {"description": "OS metrics not supported by the configured database"},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def get_os_metrics_refresh_status(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None,
            description="Starting date for the window (YYYY-MM-DD format). Defaults to 29 days before ending_date",
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for the window (YYYY-MM-DD format). Defaults to today"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's metrics. Ignored for non-admin callers"
        ),
    ) -> OSMetricsRefreshStatusResponse:
        try:
            db = _require_os_db()
            starting_date, ending_date = _window(starting_date, ending_date)
            # The cheapest total to read; only its updated_at is used
            _, updated_at = await _os_metrics(
                db, _owner(request, user_id), starting_date, ending_date, ["sessions_count"]
            )
            return OSMetricsRefreshStatusResponse(updated_at=updated_at)

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_error(f"Error getting OS metrics refresh status: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error getting OS metrics refresh status: {str(e)}")

    return router
