import logging
import time
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRouter
from starlette.concurrency import run_in_threadpool

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.utils import aggregate_metrics_by_date, identify_metrics_by_owner, is_legacy_metric
from agno.exceptions import AgnoError
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_db_and_scope
from agno.os.routers.metrics.schemas import (
    DayAggregatedMetrics,
    MetricsRefreshResponse,
    MetricsRefreshStatusResponse,
    MetricsResponse,
    ModelUsage,
    OSMetricsResponse,
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
from agno.utils.log import log_error, log_exception

logger = logging.getLogger(__name__)

# OS metrics are recomputed at most this often per owner and window, which bounds how far they
# can trail the daily metrics. Past this age an entry is still served, and a recompute starts
# in the background.
CACHE_TTL_SECONDS = 300

# The window is caller-supplied, so a multi-tenant OS can be walked across owners and day
# counts. Entries are evicted least-recently-read beyond this.
CACHE_MAX_ENTRIES = 512


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

    # Most recent computation per owner and window. Only mutated on the event loop (the sync
    # database reads themselves run in the threadpool), so no lock is needed. Per-process:
    # each worker warms its own entries.
    cache: "OrderedDict[Tuple[Optional[str], int], Tuple[OSMetricsResponse, float]]" = OrderedDict()

    # Keys with a background recompute in flight, so concurrent opens of a stale entry start
    # one recompute between them rather than one each.
    recomputing: Set[Tuple[Optional[str], int]] = set()

    def _drop_os_metrics_cache(db: Union[BaseDb, AsyncBaseDb, RemoteDb]) -> None:
        """Forget the OS metrics once the daily metrics they are built from have been rebuilt."""
        if os_db is None or db is not os_db:
            return
        cache.clear()
        # A recompute already in flight read the metrics before the rebuild, so its result is
        # dropped rather than written back over the entry this just cleared
        recomputing.clear()

    def _cache_get(key: Tuple[Optional[str], int]) -> Optional[Tuple[OSMetricsResponse, bool]]:
        entry = cache.get(key)
        if entry is None:
            return None
        metrics, cached_at = entry
        cache.move_to_end(key)
        return metrics, time.monotonic() - cached_at <= CACHE_TTL_SECONDS

    def _cache_put(key: Tuple[Optional[str], int], metrics: OSMetricsResponse) -> None:
        cache[key] = (metrics, time.monotonic())
        cache.move_to_end(key)
        while len(cache) > CACHE_MAX_ENTRIES:
            cache.popitem(last=False)

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
            _drop_os_metrics_cache(db)

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
            _drop_os_metrics_cache(db)

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

    async def _daily_metrics(
        db: Union[BaseDb, AsyncBaseDb],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
    ) -> List[Dict[str, Any]]:
        """The daily metrics the AgentOS database holds for the window, scoped the way GET /metrics scopes them."""
        if isinstance(db, AsyncBaseDb):
            metrics, _ = await db.get_metrics(
                starting_date=starting_date, ending_date=ending_date, user_id=effective_user_id
            )
        else:
            metrics, _ = await run_in_threadpool(
                db.get_metrics,
                starting_date=starting_date,
                ending_date=ending_date,
                user_id=effective_user_id,
            )

        # A read of one owner keeps that owner's rows; every other read collapses to the
        # legacy one-row-per-day shape.
        if effective_user_id is None:
            metrics = aggregate_metrics_by_date(metrics)
        elif not effective_user_id:
            # The unowned bucket is asked for by the same sentinel the SQL adapters stamp
            # pre-ownership records with, and those hold every user's traffic
            metrics = [metric for metric in metrics if not is_legacy_metric(metric)]
        return list(metrics)

    async def _compute_os_metrics(
        db: Union[BaseDb, AsyncBaseDb],
        effective_user_id: Optional[str],
        days: int,
    ) -> OSMetricsResponse:
        ending_date = datetime.now(timezone.utc).date()
        starting_date = ending_date - timedelta(days=days - 1)
        metrics = await _daily_metrics(db, effective_user_id, starting_date, ending_date)

        run_counts: Dict[Tuple[str, Optional[str]], int] = {}
        for metric in metrics:
            for model_metric in metric.get("model_metrics") or []:
                model_id = model_metric.get("model_id")
                if not model_id:
                    continue
                key = (model_id, model_metric.get("model_provider") or None)
                run_counts[key] = run_counts.get(key, 0) + (model_metric.get("count") or 0)

        total_model_runs = sum(run_counts.values())
        models = [
            ModelUsage(
                model_id=model_id,
                model_provider=model_provider,
                run_count=count,
                run_share=round(count / total_model_runs * 100, 1) if total_model_runs else 0.0,
            )
            for (model_id, model_provider), count in sorted(run_counts.items(), key=lambda item: (-item[1], item[0][0]))
        ]

        return OSMetricsResponse(
            models=models,
            total_model_runs=total_model_runs,
            window_days=days,
            computed_at=datetime.now(timezone.utc),
        )

    async def _do_recompute(
        db: Union[BaseDb, AsyncBaseDb],
        key: Tuple[Optional[str], int],
        effective_user_id: Optional[str],
        days: int,
    ) -> None:
        try:
            metrics = await _compute_os_metrics(db, effective_user_id, days)
            # A rebuild of the daily metrics forgets this key while the read above was in
            # flight, so these numbers predate it and must not be written back over it
            if key in recomputing:
                _cache_put(key, metrics)
        except Exception as e:
            # The stale entry keeps being served, and the next open retries
            log_error(f"OS metrics recompute failed: {e}")
        finally:
            recomputing.discard(key)

    @router.get(
        "/os/metrics",
        response_model=OSMetricsResponse,
        status_code=200,
        operation_id="get_os_metrics",
        summary="Get OS Metrics",
        description=(
            "Retrieve metrics about this AgentOS built from its daily metrics: how many runs each "
            "model served over a window of days.\n\n"
            "Reads the AgentOS database. A component keeping a database of its own is not included.\n\n"
            "These are the same daily metrics GET /metrics returns, so they are only as current as "
            "those. POST /metrics/refresh rebuilds the daily metrics; SQLite and Postgres also "
            "rebuild them at most once a minute when they are read.\n\n"
            "The result is cached per owner and window. Once an entry is older than its TTL it is "
            "still returned immediately, and a recompute starts in the background. Pass refresh=true "
            "to recompute from the daily metrics and wait for the result; it does not rebuild the "
            "daily metrics themselves."
        ),
        responses={
            200: {
                "description": "OS metrics computed successfully",
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
                            "computed_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            500: {"description": "Failed to compute OS metrics", "model": InternalServerErrorResponse},
            503: {"description": "No AgentOS database configured", "model": InternalServerErrorResponse},
        },
    )
    async def get_os_metrics(
        request: Request,
        background_tasks: BackgroundTasks,
        days: int = Query(default=30, description="Number of days the metrics cover", ge=1, le=365),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's metrics. Ignored for non-admin callers"
        ),
        refresh: bool = Query(default=False, description="Recompute now instead of serving the cached result"),
    ) -> OSMetricsResponse:
        try:
            if os_db is None:
                raise HTTPException(
                    status_code=503,
                    detail="Metrics not available: pass a `db` to AgentOS to enable this feature.",
                )

            scoped_user_id = get_scoped_user_id(request)
            effective_user_id = scoped_user_id if scoped_user_id is not None else user_id

            cache_key = (effective_user_id, days)
            if not refresh:
                cached = _cache_get(cache_key)
                if cached is not None:
                    metrics, fresh = cached
                    # A stale entry is still served straight away; opening the page never waits on
                    # a recompute once one has completed for this owner and window
                    if not fresh and cache_key not in recomputing:
                        recomputing.add(cache_key)
                        background_tasks.add_task(_do_recompute, os_db, cache_key, effective_user_id, days)
                    return metrics

            metrics = await _compute_os_metrics(os_db, effective_user_id, days)
            _cache_put(cache_key, metrics)
            return metrics

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_exception("GET /os/metrics failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS metrics: {str(e)}")

    return router
