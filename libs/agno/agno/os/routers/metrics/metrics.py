import asyncio
import hashlib
import json
import logging
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from itertools import chain
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, List, Optional, Union

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRouter
from httpx import HTTPStatusError
from starlette.concurrency import run_in_threadpool

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.utils import (
    METRICS_TOKEN_FIELDS,
    aggregate_metrics_by_date,
    database_error_message,
    identify_metrics_by_owner,
    is_legacy_metric,
    merge_metrics_totals,
    metrics_percentile,
)
from agno.exceptions import AgnoError
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.authz.admin_router import _day_bounds, _make_require_admin
from agno.os.middleware.user_scope import get_scoped_user_id, resolve_db_and_scope
from agno.os.routers.metrics.schemas import (
    DayAggregatedMetrics,
    DayLatencyMetrics,
    DayRunMetrics,
    DaySessionMetrics,
    DayTokenMetrics,
    DayUserMetrics,
    MetricsRefreshResponse,
    MetricsRefreshStatusResponse,
    MetricsResponse,
    ModelUsage,
    OSLatencyMetricsResponse,
    OSMetricsRefreshResponse,
    OSMetricsRefreshStatusResponse,
    OSModelMetricsResponse,
    OSRunMetricsResponse,
    OSSessionMetricsResponse,
    OSTokenMetricsResponse,
    OSUserMetricsResponse,
)
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    AgnoHTTPException,
    get_db,
    get_metrics_calculation,
    has_metrics_lock_row,
    keeps_metrics_versions,
    stop_metrics_refresh_on_read,
    to_utc_datetime,
)
from agno.remote.base import RemoteDb
from agno.run.base import RunStatus

if TYPE_CHECKING:
    from agno.os.authz.authorization import Authorization

logger = logging.getLogger(__name__)

# Without bounds a route covers the last 30 days. Both days are inclusive, so a starting_date
# equal to the ending_date covers that one day.
_DEFAULT_WINDOW_DAYS = 30

# How many databases the /os/metrics routes read or refresh at once
_MAX_CONCURRENT_OS_METRICS_READS = 8
# How many answers of the /os/metrics routes are kept for reuse
_MAX_OS_METRICS_RESPONSES = 256
# An answer for a longer window is returned but not kept
_MAX_OS_METRICS_KEPT_WINDOW_DAYS = 366

# What the latency route reads: each timing's count, total and maximum, and the bucket counts its median and p95
# are read from
_LATENCY_FIELDS = [
    "duration_runs_count",
    "total_duration_ms",
    "max_duration_ms",
    "duration_buckets",
    "time_to_first_token_runs_count",
    "total_time_to_first_token_ms",
    "max_time_to_first_token_ms",
    "time_to_first_token_buckets",
    "model_calls_count",
    "total_model_call_ms",
    "max_model_call_ms",
    "model_call_buckets",
]

# The refresh statuses in the order one answers for several databases: the first one any of them has
_REFRESH_STATUS_ORDER = ["running", "failed", "idle", "completed"]


def _window(starting_date: Optional[date], ending_date: Optional[date], max_window_days: int) -> tuple[date, date]:
    """Resolve the UTC days a route covers, ending today and covering _DEFAULT_WINDOW_DAYS days by default."""
    if ending_date is None:
        ending_date = datetime.now(timezone.utc).date()
    if starting_date is None:
        # A limit shorter than the default window shortens the default window to it
        window_days = min(_DEFAULT_WINDOW_DAYS, max_window_days)
        if (ending_date - date.min).days < window_days - 1:
            raise HTTPException(status_code=422, detail="starting_date is required for an ending_date this early")
        starting_date = ending_date - timedelta(days=window_days - 1)
    if starting_date > ending_date:
        raise HTTPException(status_code=422, detail="starting_date must be on or before ending_date")
    if (ending_date - starting_date).days + 1 > max_window_days:
        raise HTTPException(
            status_code=422, detail=f"starting_date and ending_date can cover at most {max_window_days} days"
        )
    return starting_date, ending_date


def _os_metrics_location(db: Union[BaseDb, AsyncBaseDb, RemoteDb]) -> tuple[Optional[str], ...]:
    """Where a database keeps its OS metrics rows: databases at one location hold the same rows."""
    if isinstance(db, RemoteDb):
        # Two remote AgentOSes can each have a database with the same id
        return (db.client.base_url, str(db.id))
    table_names = (getattr(db, "component_metrics_table_name", None), getattr(db, "aggregate_metrics_table_name", None))
    address: Optional[str] = None
    db_engine = getattr(db, "db_engine", None)
    connection_kwargs = getattr(
        getattr(getattr(db, "redis_client", None), "connection_pool", None), "connection_kwargs", None
    )
    database_string = getattr(getattr(db, "db_client", None), "_database_string", None)
    db_path = getattr(db, "db_path", None)
    if db_engine is not None:
        url = db_engine.url
        # A URL that names no server, or no SQLite file, cannot tell two databases apart
        if url.get_backend_name() == "sqlite":
            named = bool(url.database) and url.query.get("mode") != "memory" and ":memory:" not in url.database
        else:
            # The driver takes the server from the query before the URL: a unix socket (host for PostgreSQL,
            # unix_socket for MySQL), a port and a database name
            host = url.query.get("host") or url.query.get("unix_socket") or url.host
            # A PostgreSQL schema lives inside a database, while a MySQL schema is the database itself
            named = bool(host) and (bool(url.database) or url.get_backend_name() != "postgresql")
        if named:
            # The driver, the login and the connection options are left out, and a default port is written out, so
            # every adapter on one database shares a location
            backend_name = url.get_backend_name()
            if backend_name == "sqlite":
                address = f"sqlite:///{url.database}"
            else:
                port = url.query.get("port") or url.port or {"postgresql": 5432, "mysql": 3306}.get(backend_name)
                address = f"{backend_name}://{host}:{port}/{url.query.get('dbname') or url.database}"
    elif isinstance(connection_kwargs, dict):
        # A client on a unix socket names its path instead of a host and port, and a Sentinel client names neither
        if connection_kwargs.get("path"):
            address = f"unix://{connection_kwargs['path']}?db={connection_kwargs.get('db')}"
        elif connection_kwargs.get("host") is not None:
            address = (
                f"redis://{connection_kwargs['host']}:{connection_kwargs.get('port')}/{connection_kwargs.get('db')}"
            )
    elif isinstance(database_string, str):
        # A Firestore client names its project and database together
        address = database_string
    elif isinstance(db_path, Path):
        address = str(db_path.resolve())
    else:
        for name in ("db_url", "_db_url", "project_id", "bucket_name"):
            if isinstance(getattr(db, name, None), str):
                address = getattr(db, name)
                break
    if address is None:
        # A client given without a URL is named the way its adapter seeds its default id
        for name in ("db_client", "_provided_client", "redis_client"):
            if getattr(db, name, None) is not None:
                address = str(getattr(db, name))
                break
    if address is None:
        return (str(db.id), *table_names)
    store_names = (
        getattr(db, name, None) for name in ("db_schema", "db_name", "_db_ns", "_db_db", "db_prefix", "prefix")
    )
    return (address, *(name for name in store_names if isinstance(name, str)), *table_names)


def _unique_os_dbs(
    os_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
) -> dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]:
    """Keep each location once, under the first id it is registered with, so its rows are read once."""
    locations = set()
    unique_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]] = {}
    for db_id, db_list in os_dbs.items():
        for db in db_list:
            location = _os_metrics_location(db)
            if location not in locations:
                locations.add(location)
                unique_dbs.setdefault(db_id, []).append(db)
    return unique_dbs


def _merge_totals(totals: list[dict[str, Any]], fields: list[str]) -> dict[str, Any]:
    """Merge the totals of several dates or databases into one set of totals, their models listed as the reads list
    them."""
    merged = merge_metrics_totals(totals, [field for field in fields if field != "model_metrics"])
    if "model_metrics" in fields:
        merged["model_metrics"] = [model for day_totals in totals for model in day_totals.get("model_metrics", [])]
    return merged


def _owner(request: Request, user_id: Optional[str]) -> Optional[str]:
    """The owner a read covers: the caller's own scope, else the requested user_id, else every owner."""
    scoped_user_id = get_scoped_user_id(request)
    return scoped_user_id if scoped_user_id is not None else user_id


def _remote_os_db(os_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]) -> Optional[RemoteDb]:
    """A remote database a read covers when every database it covers is on one remote AgentOS, so that AgentOS
    answers the read for the ids of those databases and no other."""
    os_db_list = [db for db_list in os_dbs.values() for db in db_list]
    remote_dbs = [db for db in os_db_list if isinstance(db, RemoteDb)]
    if remote_dbs and len(remote_dbs) == len(os_db_list) and len({db.client.base_url for db in remote_dbs}) == 1:
        return remote_dbs[0]
    return None


def _seconds_left(deadline: float) -> float:
    """The seconds a request has left before its deadline."""
    return max(deadline - asyncio.get_running_loop().time(), 0.0)


def _os_metrics_answer(request: Request, response: Response, os_metrics_response: Any) -> Any:
    """The answer of a read route with its ETag, or 304 with no body for a caller that already holds it."""
    etag = f'"{hashlib.sha256(os_metrics_response.model_dump_json().encode()).hexdigest()[:32]}"'
    # A proxy that compresses the answer, such as nginx with gzip, sends the ETag back weak
    if (request.headers.get("if-none-match") or "").removeprefix("W/") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    response.headers["ETag"] = etag
    return os_metrics_response


def _refresh_status_rank(refresh_status: MetricsRefreshStatusResponse) -> int:
    """Where a refresh status comes in _REFRESH_STATUS_ORDER, a status it does not name last."""
    if refresh_status.status in _REFRESH_STATUS_ORDER:
        return _REFRESH_STATUS_ORDER.index(refresh_status.status)
    return len(_REFRESH_STATUS_ORDER)


def _refresh_status_code(refreshes: dict[str, MetricsRefreshResponse]) -> int:
    """207 when the refresh of a database could not be started, 202 when one was started or is already running, else
    200."""
    if any(refresh.status == "failed" for refresh in refreshes.values()):
        return 207
    if any(refresh.status in ("started", "already_running") for refresh in refreshes.values()):
        return 202
    return 200


def _days(starting_date: date, ending_date: date) -> list[date]:
    """Every day of the window, a day without rows included."""
    return [starting_date + timedelta(days=offset) for offset in range((ending_date - starting_date).days + 1)]


def _previous_starting_date(starting_date: date, ending_date: date) -> date:
    """The first day of the window of the same length that ends the day before this one starts."""
    days = (ending_date - starting_date).days + 1
    if (starting_date - date.min).days < days:
        raise HTTPException(status_code=422, detail="starting_date is too early to compare with the window before it")
    return starting_date - timedelta(days=days)


def _change_percent(total: int, previous_total: int) -> Optional[float]:
    """The change from the previous total to this one, in percent."""
    # Nothing before means no rate to compare against, rather than an infinite rise
    return round((total - previous_total) / previous_total * 100, 1) if previous_total else None


def _average(total: int, count: int) -> Optional[int]:
    """The average of a total over its count, rounded."""
    return round(total / count) if count else None


def _latency(totals: dict[str, Any]) -> dict[str, Optional[int]]:
    """The latency numbers of one set of totals: the runs, and the average, median, p95 and max of each timing."""
    return {
        "runs_count": totals.get("duration_runs_count", 0),
        "avg_duration_ms": _average(totals.get("total_duration_ms", 0), totals.get("duration_runs_count", 0)),
        "median_duration_ms": metrics_percentile(
            totals.get("duration_buckets", {}), 0.5, totals.get("max_duration_ms")
        ),
        "p95_duration_ms": metrics_percentile(totals.get("duration_buckets", {}), 0.95, totals.get("max_duration_ms")),
        "max_duration_ms": totals.get("max_duration_ms"),
        "avg_time_to_first_token_ms": _average(
            totals.get("total_time_to_first_token_ms", 0), totals.get("time_to_first_token_runs_count", 0)
        ),
        "median_time_to_first_token_ms": metrics_percentile(
            totals.get("time_to_first_token_buckets", {}), 0.5, totals.get("max_time_to_first_token_ms")
        ),
        "p95_time_to_first_token_ms": metrics_percentile(
            totals.get("time_to_first_token_buckets", {}), 0.95, totals.get("max_time_to_first_token_ms")
        ),
        "max_time_to_first_token_ms": totals.get("max_time_to_first_token_ms"),
        "avg_model_call_ms": _average(totals.get("total_model_call_ms", 0), totals.get("model_calls_count", 0)),
        "median_model_call_ms": metrics_percentile(
            totals.get("model_call_buckets", {}), 0.5, totals.get("max_model_call_ms")
        ),
        "p95_model_call_ms": metrics_percentile(
            totals.get("model_call_buckets", {}), 0.95, totals.get("max_model_call_ms")
        ),
        "max_model_call_ms": totals.get("max_model_call_ms"),
    }


def get_metrics_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    settings: AgnoAPISettings = AgnoAPISettings(),
    role_store: "Optional[Authorization]" = None,
    auth_enabled: bool = True,
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
    return attach_routes(router=router, dbs=dbs, settings=settings, role_store=role_store, auth_enabled=auth_enabled)


def attach_routes(
    router: APIRouter,
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    settings: AgnoAPISettings = AgnoAPISettings(),
    role_store: "Optional[Authorization]" = None,
    auth_enabled: bool = True,
) -> APIRouter:
    require_user_admin = _make_require_admin(role_store, auth_enabled=auth_enabled)

    if not settings.metrics_calculation_enabled:
        for db in chain.from_iterable(dbs.values()):
            stop_metrics_refresh_on_read(db)

    # Most recent refresh state per db id, doubling as the in-flight guard ('running'), for a database that
    # keeps no refresh status of its own.
    # Only mutated on the event loop (the sync calculation itself runs in the threadpool),
    # so no lock is needed. Per-process: each worker tracks the refreshes it started.
    refresh_states: dict[str, MetricsRefreshStatusResponse] = {}

    async def _get_refresh_status(db: Union[BaseDb, AsyncBaseDb]) -> MetricsRefreshStatusResponse:
        """The status of the most recent refresh: the database's, for every process, or this process's own."""
        if not has_metrics_lock_row(db):
            return refresh_states.get(str(db.id)) or MetricsRefreshStatusResponse(status="idle")
        if isinstance(db, AsyncBaseDb):
            refresh_status = await db.get_metrics_refresh_status()
        else:
            refresh_status = await run_in_threadpool(db.get_metrics_refresh_status)
        if refresh_status is None:
            return MetricsRefreshStatusResponse(status="idle")
        return MetricsRefreshStatusResponse(
            status=refresh_status["status"],
            started_at=to_utc_datetime(refresh_status["started_at"]),
            finished_at=to_utc_datetime(refresh_status["finished_at"]),
            error=refresh_status["error"],
        )

    async def _read_metrics(
        db: Union[BaseDb, AsyncBaseDb],
        starting_date: Optional[date],
        ending_date: Optional[date],
        user_id: Optional[str],
    ) -> tuple[list[dict[str, Any]], Optional[int]]:
        """The stored metrics of the date range, and when they were last updated."""
        # A read of one owner keeps that owner's rows; every other read takes one row per day
        if user_id is None:
            if isinstance(db, AsyncBaseDb):
                return await db.get_metrics_by_date(starting_date=starting_date, ending_date=ending_date)
            return await run_in_threadpool(db.get_metrics_by_date, starting_date=starting_date, ending_date=ending_date)
        if isinstance(db, AsyncBaseDb):
            metrics, latest_updated_at = await db.get_metrics(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
        else:
            metrics, latest_updated_at = await run_in_threadpool(
                db.get_metrics,
                starting_date=starting_date,
                ending_date=ending_date,
                user_id=user_id,
            )
        # The unowned bucket is asked for by the same sentinel the SQL adapters stamp
        # pre-ownership records with, and those hold every user's traffic
        if not user_id:
            metrics = [metric for metric in metrics if not is_legacy_metric(metric)]
        return identify_metrics_by_owner(metrics, user_id), latest_updated_at

    @router.get(
        "/metrics",
        response_model=MetricsResponse,
        status_code=200,
        operation_id="get_metrics",
        summary="Get AgentOS Metrics",
        description=(
            "Retrieve AgentOS metrics and analytics data for a specified date range. "
            "If no date range is specified, returns all available metrics. "
            "Reading never calculates metrics; the response carries the status of the most recent refresh."
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
                                        "cost": 0.0042,
                                    },
                                    "model_metrics": [
                                        {
                                            "model_id": "gpt-4o",
                                            "model_provider": "OpenAI",
                                            "count": 5,
                                            "cost": 0.0042,
                                        }
                                    ],
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
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    db_id=db_id,
                    table=table,
                    headers=headers,
                )

            metrics, latest_updated_at = await _read_metrics(db, starting_date, ending_date, effective_user_id)

            return MetricsResponse(
                metrics=[DayAggregatedMetrics.from_dict(metric) for metric in metrics],
                updated_at=to_utc_datetime(latest_updated_at),
                refresh=await _get_refresh_status(db),
            )

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /metrics failed")
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

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
        user_id: Optional[str],
        rebuild_from: Optional[date],
        headers: Optional[dict],
    ) -> None:
        refresh_key = str(db.id)
        try:
            if isinstance(db, RemoteDb):
                await db.refresh_metrics(
                    db_id=db_id,
                    table=table,
                    user_id=user_id,
                    rebuild_from=rebuild_from,
                    headers=headers,
                    background=True,
                )
            elif isinstance(db, AsyncBaseDb):
                await get_metrics_calculation(db, rebuild_from=rebuild_from)()
            else:
                await run_in_threadpool(get_metrics_calculation(db, rebuild_from=rebuild_from))
        except Exception as e:
            logger.error(f"Metrics refresh failed: {e}")
            if not has_metrics_lock_row(db):
                _record_refresh_outcome(refresh_key, error=database_error_message(e))
        else:
            if not has_metrics_lock_row(db):
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
            "If a refresh is already in progress for the target database, in any process on a database that keeps "
            "its refresh status, returns status 'already_running' without starting a new one. "
            "Returns status 'disabled' when metrics calculation is turned off."
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
                                    "cost": 0.0051,
                                },
                                "model_metrics": [
                                    {"model_id": "gpt-5.5", "model_provider": "OpenAI", "count": 2, "cost": 0.0051}
                                ],
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
            503: {"description": "rebuild_from not supported by the configured database"},
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
        rebuild_from: Optional[date] = Query(
            default=None,
            description="Also rebuild every day from this date to today, as after a release that changed how "
            "metrics are counted",
        ),
    ) -> Union[List[DayAggregatedMetrics], MetricsRefreshResponse]:
        try:
            # Resolved before the background branch so an identity-less token cannot start a refresh.
            db, effective_user_id = await resolve_db_and_scope(request, dbs, db_id, table, fallback_user_id=user_id)

            headers = None
            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None

            # Answered the same way for a background refresh, which never starts
            if not isinstance(db, RemoteDb) and not settings.metrics_calculation_enabled:
                return MetricsRefreshResponse(status="disabled", message="Metrics calculation is turned off")

            if background:
                response.status_code = 202

            # A remote database keeps its own state, so it is left to guard itself
            if isinstance(db, RemoteDb):
                if background:
                    background_tasks.add_task(_do_refresh, db, db_id, table, effective_user_id, rebuild_from, headers)
                    return MetricsRefreshResponse(status="started", message="Metrics refresh started in background")
                return await db.refresh_metrics(
                    db_id=db_id, table=table, user_id=effective_user_id, rebuild_from=rebuild_from, headers=headers
                )

            refresh_key = str(db.id)
            has_lock_row = has_metrics_lock_row(db)
            if rebuild_from is not None and not has_lock_row:
                raise HTTPException(status_code=503, detail="rebuild_from not supported by the configured database")
            if rebuild_from is not None and rebuild_from > datetime.now(timezone.utc).date():
                raise HTTPException(status_code=422, detail="rebuild_from cannot be a future date")

            # A database with a lock row lets one refresh run at a time for every process, and claims it when the
            # refresh starts; without one, the same guard holds for this process
            if has_lock_row:
                if background and (await _get_refresh_status(db)).status == "running":
                    # A rebuild still reopens its days, through a calculation that then finds the refresh held, so
                    # the next refresh rebuilds them
                    if rebuild_from is not None:
                        background_tasks.add_task(
                            _do_refresh, db, db_id, table, effective_user_id, rebuild_from, headers
                        )
                    return _already_running_response()
            else:
                if _refresh_is_running(refresh_key):
                    return _already_running_response()
                _mark_refresh_running(refresh_key)

            if background:
                background_tasks.add_task(_do_refresh, db, db_id, table, effective_user_id, rebuild_from, headers)

                return MetricsRefreshResponse(status="started", message="Metrics refresh started in background")

            calculate = get_metrics_calculation(db, rebuild_from=rebuild_from)
            try:
                if isinstance(db, AsyncBaseDb):
                    result = await calculate()
                else:
                    result = await run_in_threadpool(calculate)
            except Exception as e:
                if not has_lock_row:
                    _record_refresh_outcome(refresh_key, error=database_error_message(e))
                raise
            if not has_lock_row:
                _record_refresh_outcome(refresh_key)

            if result is None:
                # The claim of the lock row is the check: a refresh that lost it calculated nothing
                return _already_running_response() if has_lock_row else []
            # The days alone came back: their rows are read from the tables
            if has_lock_row:
                # A refresh that changed no day answers with today's metrics
                days = result or [datetime.now(timezone.utc).date()]
                metrics, _ = await _read_metrics(db, days[0], days[-1], effective_user_id)
                metrics_by_date = {metric["date"]: metric for metric in metrics if metric["date"] in days}
                # A day calculated to no sessions or runs keeps a row of zeros, which reads leave out, so it comes
                # back with zero counts
                for day in result:
                    metrics_by_date.setdefault(
                        day,
                        {
                            "id": f"{day.isoformat()}_daily"
                            if effective_user_id is None
                            else f"{day.isoformat()}_{effective_user_id}_daily",
                            "date": day,
                            "token_metrics": {**{field: 0 for field in METRICS_TOKEN_FIELDS}, "cost": None},
                            "model_metrics": [],
                        },
                    )
                return [DayAggregatedMetrics.from_dict(metrics_by_date[day]) for day in sorted(metrics_by_date)]

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
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            # The database's own message, as the refresh status keeps it
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {database_error_message(e)}")

    @router.get(
        "/metrics/refresh/status",
        response_model=MetricsRefreshStatusResponse,
        status_code=200,
        operation_id="get_metrics_refresh_status",
        summary="Get Metrics Refresh Status",
        description=(
            "Get the status of the most recent metrics refresh for the target database: in any process on a database "
            "that keeps its refresh status, otherwise in this server process. "
            "Returns 'running' while a refresh is in progress, then 'completed' with the finish "
            "timestamp or 'failed' with its error — the state updates even when a refresh completes "
            "without writing new data. Returns 'idle' if no refresh has run on the database. "
            "For remote databases the status is fetched from the remote AgentOS. "
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

            return await _get_refresh_status(db)

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics refresh status: {str(e)}")

    def _os_dbs(db_ids: Optional[list[str]]) -> dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]:
        """The databases a read covers, by id: the requested ones, else every database of the AgentOS, each once."""
        if not any(dbs.values()):
            raise HTTPException(status_code=400, detail="No database is configured on this AgentOS")
        if not db_ids:
            return _unique_os_dbs(dbs)
        os_dbs = {}
        for db_id in db_ids:
            if db_id not in dbs:
                raise HTTPException(status_code=404, detail=f"No database found with id '{db_id}'")
            os_dbs[db_id] = dbs[db_id]
        return _unique_os_dbs(os_dbs)

    async def _read_os_metrics(
        db: Union[BaseDb, AsyncBaseDb],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        fields: list[str],
    ) -> tuple[list[dict[str, Any]], Optional[int]]:
        """One database's OS metrics for the window, totalled by the database per day, oldest first."""
        if isinstance(db, AsyncBaseDb):
            return await db.get_component_metrics(
                starting_date=starting_date,
                ending_date=ending_date,
                user_id=effective_user_id,
                fields=fields,
            )
        return await run_in_threadpool(
            db.get_component_metrics,
            starting_date=starting_date,
            ending_date=ending_date,
            user_id=effective_user_id,
            fields=fields,
        )

    async def _read_os_metrics_totals(
        db: Union[BaseDb, AsyncBaseDb],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        fields: list[str],
    ) -> tuple[dict[str, Any], Optional[int]]:
        """One database's OS metrics for the window, totalled by the database into one set of totals."""
        if isinstance(db, AsyncBaseDb):
            return await db.get_metrics_totals(
                starting_date=starting_date,
                ending_date=ending_date,
                user_id=effective_user_id,
                fields=fields,
            )
        return await run_in_threadpool(
            db.get_metrics_totals,
            starting_date=starting_date,
            ending_date=ending_date,
            user_id=effective_user_id,
            fields=fields,
        )

    async def _wait_for_db(awaitable: Awaitable[Any], timeout_seconds: float) -> Any:
        """Wait for a database at most timeout_seconds, leaving the call to finish in the background."""
        task = asyncio.ensure_future(awaitable)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # The call finishes in the background; retrieve its eventual result so it never warns
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
            raise

    async def _read_os_dbs(
        os_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
        read: Callable[[Union[BaseDb, AsyncBaseDb]], Awaitable[tuple[Any, Optional[int]]]],
        timeout_seconds: float,
        skipped_db_ids: dict[str, str],
    ) -> tuple[list[Any], dict[str, Any]]:
        """Read every database at the same time, at most _MAX_CONCURRENT_OS_METRICS_READS at once.

        A database already in skipped_db_ids is not read, and is reported skipped for its reason.
        """

        async def _read_one(db: Union[BaseDb, AsyncBaseDb, RemoteDb]) -> Any:
            if isinstance(db, RemoteDb):
                raise NotImplementedError
            return await _wait_for_db(read(db), timeout_seconds)

        results: list[Any] = []
        db_ids: dict[str, Optional[datetime]] = {}
        skipped_db_ids = dict(skipped_db_ids)
        sources = [(db_id, db) for db_id, db_list in os_dbs.items() if db_id not in skipped_db_ids for db in db_list]
        for start in range(0, len(sources), _MAX_CONCURRENT_OS_METRICS_READS):
            batch = sources[start : start + _MAX_CONCURRENT_OS_METRICS_READS]
            outcomes = await asyncio.gather(*(_read_one(db) for _, db in batch), return_exceptions=True)
            for (db_id, _), outcome in zip(batch, outcomes):
                if isinstance(outcome, NotImplementedError):
                    skipped_db_ids.setdefault(db_id, "unsupported")
                elif isinstance(outcome, asyncio.TimeoutError):
                    skipped_db_ids.setdefault(db_id, "timeout")
                elif isinstance(outcome, BaseException):
                    logger.warning(f"OS metrics read failed for database '{db_id}': {outcome}")
                    skipped_db_ids.setdefault(db_id, "failed")
                else:
                    result, latest_updated_at = outcome
                    results.append(result)
                    updated_at = to_utc_datetime(latest_updated_at)
                    current_updated_at = db_ids.get(db_id)
                    if current_updated_at is None or (updated_at is not None and updated_at > current_updated_at):
                        db_ids[db_id] = updated_at

        # A response from no database at all would read as a window without traffic
        if not db_ids:
            if all(reason == "unsupported" for reason in skipped_db_ids.values()):
                raise HTTPException(status_code=503, detail="OS metrics not supported by the configured database")
            skipped = ", ".join(f"'{db_id}' ({reason})" for db_id, reason in skipped_db_ids.items())
            raise HTTPException(status_code=503, detail=f"OS metrics not available from any database: {skipped}")
        updated_ats = [updated_at for updated_at in db_ids.values() if updated_at is not None]
        return results, {
            "updated_at": max(updated_ats) if updated_ats else None,
            "db_ids": db_ids,
            "skipped_db_ids": skipped_db_ids,
        }

    async def _os_metrics_by_day(
        os_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        fields: list[str],
        timeout_seconds: float,
        skipped_db_ids: dict[str, str],
    ) -> tuple[dict[date, dict[str, Any]], dict[str, Any]]:
        """The window's OS metrics, totalled per day and added up across the databases, keyed by day."""
        results, databases = await _read_os_dbs(
            os_dbs,
            lambda db: _read_os_metrics(db, effective_user_id, starting_date, ending_date, fields),
            timeout_seconds,
            skipped_db_ids,
        )
        totals_by_date: dict[date, list[dict[str, Any]]] = {}
        for totals in results:
            for day_totals in totals:
                totals_by_date.setdefault(day_totals["date"], []).append(day_totals)
        return {
            day: {"date": day, **_merge_totals(totals_by_date[day], fields)} for day in sorted(totals_by_date)
        }, databases

    async def _os_metrics_totals(
        os_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        fields: list[str],
        timeout_seconds: float,
        skipped_db_ids: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """The window's OS metrics, totalled into one set of totals and added up across the databases."""
        results, databases = await _read_os_dbs(
            os_dbs,
            lambda db: _read_os_metrics_totals(db, effective_user_id, starting_date, ending_date, fields),
            timeout_seconds,
            skipped_db_ids,
        )
        return _merge_totals(results, fields), databases

    # Answers of the read routes. Only read and written on the event loop, so no lock is needed.
    # Per-process: every server asks the databases for their versions before it reuses an answer.
    os_metrics_responses: "OrderedDict[str, Any]" = OrderedDict()

    async def _os_metrics_response_key(
        route: str,
        os_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        timeout_seconds: float,
    ) -> tuple[Optional[str], dict[str, str]]:
        """The key an answer of a read route is kept under, or None when the answer may not be reused, and the
        databases that did not answer in time or have not finished a first calculation, which the read then skips.

        A route gives this half the time of its request, so the rows can still be read within the other half.
        """
        # The routes also read the window before this one, to compare against
        versions_starting_date = _previous_starting_date(starting_date, ending_date)

        async def _versions_of(db: Union[BaseDb, AsyncBaseDb, RemoteDb], seconds_left: float) -> Any:
            if isinstance(db, RemoteDb) or not keeps_metrics_versions(db):
                return "unsupported"
            if isinstance(db, AsyncBaseDb):
                task = asyncio.ensure_future(db.get_metrics_versions(versions_starting_date, ending_date))
            else:
                task = asyncio.ensure_future(
                    run_in_threadpool(db.get_metrics_versions, versions_starting_date, ending_date)
                )
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=seconds_left)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                # The read finishes in the background, so a rebuild it started is not rolled
                # back; retrieve its eventual result so it never warns
                task.add_done_callback(lambda t: t.cancelled() or t.exception())
                raise

        sources = [(db_id, db) for db_id, db_list in os_dbs.items() for db in db_list]
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        versions: list[Any] = []
        skipped_db_ids: dict[str, str] = {}
        # In the batches of _read_os_dbs, so no more rebuilds are started at once than a read without this starts
        for start in range(0, len(sources), _MAX_CONCURRENT_OS_METRICS_READS):
            if _seconds_left(deadline) <= 0:
                return None, skipped_db_ids
            batch = sources[start : start + _MAX_CONCURRENT_OS_METRICS_READS]
            outcomes = await asyncio.gather(
                *(_versions_of(db, _seconds_left(deadline)) for _, db in batch), return_exceptions=True
            )
            for (db_id, _), outcome in zip(batch, outcomes):
                # Still calculating after half the request, or before its first calculation has finished, so its
                # rows would be read half built
                if isinstance(outcome, asyncio.TimeoutError):
                    skipped_db_ids.setdefault(db_id, "timeout")
                elif outcome is None:
                    skipped_db_ids.setdefault(db_id, "incomplete")
            versions.extend(outcomes)
        # A database that cannot say its versions, did not answer, or has not finished a first calculation has no
        # answer kept for it
        if any(isinstance(outcome, BaseException) or outcome is None for outcome in versions):
            return None, skipped_db_ids
        # A rebuild that changes a day moves its version, so a reused answer is never older than the rows
        try:
            return json.dumps(
                [
                    route,
                    starting_date.isoformat(),
                    ending_date.isoformat(),
                    effective_user_id,
                    [[db_id, db_versions] for (db_id, _), db_versions in zip(sources, versions)],
                ]
            ), skipped_db_ids
        except (TypeError, ValueError):
            return None, skipped_db_ids

    async def _keep_os_metrics_response(
        key: Optional[str],
        os_metrics_response: Any,
        route: str,
        os_dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
        effective_user_id: Optional[str],
        starting_date: date,
        ending_date: date,
        timeout_seconds: float,
    ) -> None:
        """Keep the answer of a read route under its key, when no database changed while it was read."""
        if key is None or os_metrics_response.window_days > _MAX_OS_METRICS_KEPT_WINDOW_DAYS:
            return
        # A database that timed out or failed may answer the next request, so an answer without it is not kept
        if any(reason != "unsupported" for reason in os_metrics_response.skipped_db_ids.values()):
            return
        # A rebuild that landed between the versions read and the rows read would be kept under the older versions
        latest_key, _ = await _os_metrics_response_key(
            route, os_dbs, effective_user_id, starting_date, ending_date, timeout_seconds
        )
        if latest_key != key:
            return
        os_metrics_responses[key] = os_metrics_response
        os_metrics_responses.move_to_end(key)
        while len(os_metrics_responses) > _MAX_OS_METRICS_RESPONSES:
            os_metrics_responses.popitem(last=False)

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
                            "db_ids": {"agno-db": "2025-07-31T12:49:01Z"},
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            400: {"description": "No database configured", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            422: {"description": "Invalid date range parameters", "model": ValidationErrorResponse},
            500: {"description": "Failed to get OS session metrics", "model": InternalServerErrorResponse},
            503: {"description": "OS metrics not available from any database"},
        },
    )
    async def get_os_session_metrics(
        request: Request,
        response: Response,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's sessions. Ignored for non-admin callers"
        ),
        db_id: Optional[List[str]] = Query(
            default=None, description="Database ID to query metrics from; repeatable, every database by default"
        ),
        timeout_seconds: float = Query(default=30, gt=0, description="Seconds to wait for each database to answer"),
    ) -> Union[OSSessionMetricsResponse, Response]:
        try:
            os_dbs = _os_dbs(db_id)
            effective_user_id = _owner(request, user_id)
            remote_db = _remote_os_db(os_dbs)
            if remote_db is not None:
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                remote_response = await remote_db.get_os_session_metrics(
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    db_id=list(os_dbs),
                    timeout_seconds=timeout_seconds,
                    headers=headers,
                )
                return _os_metrics_answer(request, response, remote_response)
            starting_date, ending_date = _window(starting_date, ending_date, settings.os_metrics_max_window_days)
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            response_key, skipped_db_ids = await _os_metrics_response_key(
                "sessions", os_dbs, effective_user_id, starting_date, ending_date, timeout_seconds / 2
            )
            if response_key is not None and response_key in os_metrics_responses:
                os_metrics_responses.move_to_end(response_key)
                return _os_metrics_answer(request, response, os_metrics_responses[response_key])
            previous_starting_date = _previous_starting_date(starting_date, ending_date)
            totals, databases = await _os_metrics_by_day(
                os_dbs,
                effective_user_id,
                previous_starting_date,
                ending_date,
                ["sessions_count"],
                _seconds_left(deadline),
                skipped_db_ids,
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
            os_metrics_response = OSSessionMetricsResponse(
                metrics=metrics,
                total_sessions=total_sessions,
                previous_total_sessions=previous_total_sessions,
                change_percent=_change_percent(total_sessions, previous_total_sessions),
                window_days=(ending_date - starting_date).days + 1,
                **databases,
            )
            await _keep_os_metrics_response(
                response_key,
                os_metrics_response,
                "sessions",
                os_dbs,
                effective_user_id,
                starting_date,
                ending_date,
                _seconds_left(deadline),
            )
            return _os_metrics_answer(request, response, os_metrics_response)

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /os/metrics/sessions failed")
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
                            "metrics": [{"date": "2025-07-31T00:00:00Z", "tokens_count": 5962}],
                            "total_tokens": 184500,
                            "previous_total_tokens": 150000,
                            "change_percent": 23.0,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                            "db_ids": {"agno-db": "2025-07-31T12:49:01Z"},
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            400: {"description": "No database configured", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            422: {"description": "Invalid date range parameters", "model": ValidationErrorResponse},
            500: {"description": "Failed to get OS token metrics", "model": InternalServerErrorResponse},
            503: {"description": "OS metrics not available from any database"},
        },
    )
    async def get_os_token_metrics(
        request: Request,
        response: Response,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's tokens. Ignored for non-admin callers"
        ),
        db_id: Optional[List[str]] = Query(
            default=None, description="Database ID to query metrics from; repeatable, every database by default"
        ),
        timeout_seconds: float = Query(default=30, gt=0, description="Seconds to wait for each database to answer"),
    ) -> Union[OSTokenMetricsResponse, Response]:
        try:
            os_dbs = _os_dbs(db_id)
            effective_user_id = _owner(request, user_id)
            remote_db = _remote_os_db(os_dbs)
            if remote_db is not None:
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                remote_response = await remote_db.get_os_token_metrics(
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    db_id=list(os_dbs),
                    timeout_seconds=timeout_seconds,
                    headers=headers,
                )
                return _os_metrics_answer(request, response, remote_response)
            starting_date, ending_date = _window(starting_date, ending_date, settings.os_metrics_max_window_days)
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            response_key, skipped_db_ids = await _os_metrics_response_key(
                "tokens", os_dbs, effective_user_id, starting_date, ending_date, timeout_seconds / 2
            )
            if response_key is not None and response_key in os_metrics_responses:
                os_metrics_responses.move_to_end(response_key)
                return _os_metrics_answer(request, response, os_metrics_responses[response_key])
            previous_starting_date = _previous_starting_date(starting_date, ending_date)
            totals, databases = await _os_metrics_by_day(
                os_dbs,
                effective_user_id,
                previous_starting_date,
                ending_date,
                ["total_tokens"],
                _seconds_left(deadline),
                skipped_db_ids,
            )

            metrics = [
                DayTokenMetrics(date=to_utc_datetime(day), tokens_count=totals.get(day, {}).get("total_tokens", 0))
                for day in _days(starting_date, ending_date)
            ]
            total_tokens = sum(day_metrics.tokens_count for day_metrics in metrics)
            previous_total_tokens = sum(
                day_totals["total_tokens"] for day, day_totals in totals.items() if day < starting_date
            )
            os_metrics_response = OSTokenMetricsResponse(
                metrics=metrics,
                total_tokens=total_tokens,
                previous_total_tokens=previous_total_tokens,
                change_percent=_change_percent(total_tokens, previous_total_tokens),
                window_days=(ending_date - starting_date).days + 1,
                **databases,
            )
            await _keep_os_metrics_response(
                response_key,
                os_metrics_response,
                "tokens",
                os_dbs,
                effective_user_id,
                starting_date,
                ending_date,
                _seconds_left(deadline),
            )
            return _os_metrics_answer(request, response, os_metrics_response)

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /os/metrics/tokens failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS token metrics: {str(e)}")

    @router.get(
        "/os/metrics/users",
        response_model=OSUserMetricsResponse,
        status_code=200,
        operation_id="get_os_user_metrics",
        summary="Get OS User Metrics",
        description=(
            "Retrieve the users in the user directory at the end of each day of a date range, their total, and "
            "how that total compares with the date range of the same length before it. "
            "If no date range is specified, covers the last 30 days."
        ),
        responses={
            200: {
                "description": "OS user metrics retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "metrics": [{"date": "2025-07-31T00:00:00Z", "users_count": 25}],
                            "total_users": 25,
                            "previous_total_users": 20,
                            "change_percent": 25.0,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            403: {"description": "The caller is not an admin"},
            422: {"description": "Invalid date range parameters", "model": ValidationErrorResponse},
            500: {"description": "Failed to get OS user metrics", "model": InternalServerErrorResponse},
            503: {"description": "No user directory configured"},
        },
    )
    async def get_os_user_metrics(
        request: Request,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
    ) -> OSUserMetricsResponse:
        try:
            user_store = getattr(request.app.state, "user_store", None)
            if user_store is None:
                # An AgentOS whose databases are all on one remote AgentOS has its users in that AgentOS's directory
                remote_db = _remote_os_db(dbs)
                if remote_db is not None:
                    await require_user_admin(request)
                    auth_token = get_auth_token_from_request(request)
                    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                    return await remote_db.get_os_user_metrics(
                        starting_date=starting_date, ending_date=ending_date, headers=headers
                    )
                raise HTTPException(
                    status_code=503,
                    detail="User metrics not available: pass a `user_directory` to AgentOS to enable this feature.",
                )
            # In the handler, not a route dependency, so an AgentOS without a user directory answers 503 before 403
            await require_user_admin(request)
            # A security key names no user, so nobody is ever added to the directory
            if getattr(request.state, "security_key_verified", False):
                users_by_status = await user_store.acount_by_status()
                if users_by_status["total"] == 0:
                    raise HTTPException(
                        status_code=503,
                        detail="User metrics not available: a security key adds no user to the user directory.",
                    )

            starting_date, ending_date = _window(starting_date, ending_date, settings.os_metrics_max_window_days)
            starting_at, ending_before = _day_bounds(starting_date, ending_date)
            # Every user created before the end of the window, so both windows come from one read
            created_by_day = await user_store.acreated_by_day(ending_before=ending_before)

            created: dict[date, int] = {}
            previous_total_users = 0
            for row in created_by_day:
                if row["date"] < starting_at:
                    previous_total_users += row["count"]
                else:
                    day = datetime.fromtimestamp(row["date"], tz=timezone.utc).date()
                    created[day] = created.get(day, 0) + row["count"]

            # A day counts every user created up to its end, the ones created before the window included
            total_users = previous_total_users
            metrics = []
            for day in _days(starting_date, ending_date):
                total_users += created.get(day, 0)
                metrics.append(DayUserMetrics(date=to_utc_datetime(day), users_count=total_users))
            return OSUserMetricsResponse(
                metrics=metrics,
                total_users=total_users,
                previous_total_users=previous_total_users,
                change_percent=_change_percent(total_users, previous_total_users),
                window_days=(ending_date - starting_date).days + 1,
                updated_at=datetime.now(timezone.utc),
            )

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /os/metrics/users failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS user metrics: {str(e)}")

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
                                    "runs_count": 96,
                                    "runs_share": 80.0,
                                }
                            ],
                            "total_model_runs": 120,
                            "window_days": 30,
                            "updated_at": "2025-07-31T12:49:01Z",
                            "db_ids": {"agno-db": "2025-07-31T12:49:01Z"},
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            400: {"description": "No database configured", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            422: {"description": "Invalid date range parameters", "model": ValidationErrorResponse},
            500: {"description": "Failed to get OS model metrics", "model": InternalServerErrorResponse},
            503: {"description": "OS metrics not available from any database"},
        },
    )
    async def get_os_model_metrics(
        request: Request,
        response: Response,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's metrics. Ignored for non-admin callers"
        ),
        db_id: Optional[List[str]] = Query(
            default=None, description="Database ID to query metrics from; repeatable, every database by default"
        ),
        timeout_seconds: float = Query(default=30, gt=0, description="Seconds to wait for each database to answer"),
    ) -> Union[OSModelMetricsResponse, Response]:
        try:
            os_dbs = _os_dbs(db_id)
            effective_user_id = _owner(request, user_id)
            remote_db = _remote_os_db(os_dbs)
            if remote_db is not None:
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                remote_response = await remote_db.get_os_model_metrics(
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    db_id=list(os_dbs),
                    timeout_seconds=timeout_seconds,
                    headers=headers,
                )
                return _os_metrics_answer(request, response, remote_response)
            starting_date, ending_date = _window(starting_date, ending_date, settings.os_metrics_max_window_days)
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            response_key, skipped_db_ids = await _os_metrics_response_key(
                "models", os_dbs, effective_user_id, starting_date, ending_date, timeout_seconds / 2
            )
            if response_key is not None and response_key in os_metrics_responses:
                os_metrics_responses.move_to_end(response_key)
                return _os_metrics_answer(request, response, os_metrics_responses[response_key])
            totals, databases = await _os_metrics_totals(
                os_dbs,
                effective_user_id,
                starting_date,
                ending_date,
                ["model_metrics"],
                _seconds_left(deadline),
                skipped_db_ids,
            )

            # A model stored without a provider is reported without one
            run_counts: dict[tuple[str, Optional[str]], int] = {}
            for model_metric in totals["model_metrics"]:
                key = (model_metric["model_id"], model_metric["model_provider"] or None)
                run_counts[key] = run_counts.get(key, 0) + model_metric["count"]

            total_model_runs = sum(run_counts.values())
            os_metrics_response = OSModelMetricsResponse(
                models=[
                    ModelUsage(
                        model_id=model_id,
                        model_provider=model_provider,
                        runs_count=count,
                        runs_share=round(count / total_model_runs * 100, 1),
                    )
                    for (model_id, model_provider), count in sorted(
                        run_counts.items(), key=lambda item: (-item[1], item[0][0])
                    )
                ],
                total_model_runs=total_model_runs,
                window_days=(ending_date - starting_date).days + 1,
                **databases,
            )
            await _keep_os_metrics_response(
                response_key,
                os_metrics_response,
                "models",
                os_dbs,
                effective_user_id,
                starting_date,
                ending_date,
                _seconds_left(deadline),
            )
            return _os_metrics_answer(request, response, os_metrics_response)

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /os/metrics/models failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS model metrics: {str(e)}")

    @router.get(
        "/os/metrics/runs",
        response_model=OSRunMetricsResponse,
        status_code=200,
        operation_id="get_os_run_metrics",
        summary="Get OS Run Metrics",
        description=(
            "Retrieve the runs started on each day of a date range by status, their total and success rate, and "
            "how that total compares with the date range of the same length before it. "
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
                            "db_ids": {"agno-db": "2025-07-31T12:49:01Z"},
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            400: {"description": "No database configured", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            422: {"description": "Invalid date range parameters", "model": ValidationErrorResponse},
            500: {"description": "Failed to get OS run metrics", "model": InternalServerErrorResponse},
            503: {"description": "OS metrics not available from any database"},
        },
    )
    async def get_os_run_metrics(
        request: Request,
        response: Response,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's runs. Ignored for non-admin callers"
        ),
        db_id: Optional[List[str]] = Query(
            default=None, description="Database ID to query metrics from; repeatable, every database by default"
        ),
        timeout_seconds: float = Query(default=30, gt=0, description="Seconds to wait for each database to answer"),
    ) -> Union[OSRunMetricsResponse, Response]:
        try:
            os_dbs = _os_dbs(db_id)
            effective_user_id = _owner(request, user_id)
            remote_db = _remote_os_db(os_dbs)
            if remote_db is not None:
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                remote_response = await remote_db.get_os_run_metrics(
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    db_id=list(os_dbs),
                    timeout_seconds=timeout_seconds,
                    headers=headers,
                )
                return _os_metrics_answer(request, response, remote_response)
            starting_date, ending_date = _window(starting_date, ending_date, settings.os_metrics_max_window_days)
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            response_key, skipped_db_ids = await _os_metrics_response_key(
                "runs", os_dbs, effective_user_id, starting_date, ending_date, timeout_seconds / 2
            )
            if response_key is not None and response_key in os_metrics_responses:
                os_metrics_responses.move_to_end(response_key)
                return _os_metrics_answer(request, response, os_metrics_responses[response_key])
            previous_starting_date = _previous_starting_date(starting_date, ending_date)
            totals, databases = await _os_metrics_by_day(
                os_dbs,
                effective_user_id,
                previous_starting_date,
                ending_date,
                ["root_runs_count", "status_metrics"],
                _seconds_left(deadline),
                skipped_db_ids,
            )

            metrics = []
            status_metrics: dict[str, int] = {}
            for day in _days(starting_date, ending_date):
                day_totals = totals.get(day, {})
                day_status_metrics = day_totals.get("status_metrics", {})
                metrics.append(
                    DayRunMetrics(
                        date=to_utc_datetime(day),
                        runs_count=day_totals.get("root_runs_count", 0),
                        status_metrics=day_status_metrics,
                    )
                )
                for status, count in day_status_metrics.items():
                    status_metrics[status] = status_metrics.get(status, 0) + count

            total_runs = sum(day_metrics.runs_count for day_metrics in metrics)
            previous_total_runs = sum(
                day_totals["root_runs_count"] for day, day_totals in totals.items() if day < starting_date
            )
            # A run still pending, running or paused has no outcome to rate yet
            finished_runs = sum(
                status_metrics.get(status, 0)
                for status in (RunStatus.completed.value, RunStatus.error.value, RunStatus.cancelled.value)
            )
            success_rate = (
                round(status_metrics.get(RunStatus.completed.value, 0) / finished_runs * 100, 1)
                if finished_runs
                else None
            )
            os_metrics_response = OSRunMetricsResponse(
                metrics=metrics,
                total_runs=total_runs,
                status_metrics=status_metrics,
                success_rate=success_rate,
                previous_total_runs=previous_total_runs,
                change_percent=_change_percent(total_runs, previous_total_runs),
                window_days=(ending_date - starting_date).days + 1,
                **databases,
            )
            await _keep_os_metrics_response(
                response_key,
                os_metrics_response,
                "runs",
                os_dbs,
                effective_user_id,
                starting_date,
                ending_date,
                _seconds_left(deadline),
            )
            return _os_metrics_answer(request, response, os_metrics_response)

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /os/metrics/runs failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS run metrics: {str(e)}")

    @router.get(
        "/os/metrics/latency",
        response_model=OSLatencyMetricsResponse,
        status_code=200,
        operation_id="get_os_latency_metrics",
        summary="Get OS Latency Metrics",
        description=(
            "Retrieve the average, median, p95 and slowest duration, time to the first token and model call of the "
            "completed runs on each day of a date range and across it. Medians and percentiles are approximate. "
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
                            "db_ids": {"agno-db": "2025-07-31T12:49:01Z"},
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            400: {"description": "No database configured", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            422: {"description": "Invalid date range parameters", "model": ValidationErrorResponse},
            500: {"description": "Failed to get OS latency metrics", "model": InternalServerErrorResponse},
            503: {"description": "OS metrics not available from any database"},
        },
    )
    async def get_os_latency_metrics(
        request: Request,
        response: Response,
        starting_date: Optional[date] = Query(
            default=None, description="Starting date for metrics range (YYYY-MM-DD format)"
        ),
        ending_date: Optional[date] = Query(
            default=None, description="Ending date for metrics range (YYYY-MM-DD format)"
        ),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's runs. Ignored for non-admin callers"
        ),
        db_id: Optional[List[str]] = Query(
            default=None, description="Database ID to query metrics from; repeatable, every database by default"
        ),
        timeout_seconds: float = Query(default=30, gt=0, description="Seconds to wait for each database to answer"),
    ) -> Union[OSLatencyMetricsResponse, Response]:
        try:
            os_dbs = _os_dbs(db_id)
            effective_user_id = _owner(request, user_id)
            remote_db = _remote_os_db(os_dbs)
            if remote_db is not None:
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                remote_response = await remote_db.get_os_latency_metrics(
                    starting_date=starting_date,
                    ending_date=ending_date,
                    user_id=effective_user_id,
                    db_id=list(os_dbs),
                    timeout_seconds=timeout_seconds,
                    headers=headers,
                )
                return _os_metrics_answer(request, response, remote_response)
            starting_date, ending_date = _window(starting_date, ending_date, settings.os_metrics_max_window_days)
            deadline = asyncio.get_running_loop().time() + timeout_seconds
            response_key, skipped_db_ids = await _os_metrics_response_key(
                "latency", os_dbs, effective_user_id, starting_date, ending_date, timeout_seconds / 2
            )
            if response_key is not None and response_key in os_metrics_responses:
                os_metrics_responses.move_to_end(response_key)
                return _os_metrics_answer(request, response, os_metrics_responses[response_key])
            # The medians and p95s are read from each day's bucket counts
            totals, databases = await _os_metrics_by_day(
                os_dbs,
                effective_user_id,
                starting_date,
                ending_date,
                _LATENCY_FIELDS,
                _seconds_left(deadline),
                skipped_db_ids,
            )

            metrics = [
                DayLatencyMetrics(date=to_utc_datetime(day), **_latency(totals.get(day, {})))
                for day in _days(starting_date, ending_date)
            ]

            os_metrics_response = OSLatencyMetricsResponse(
                metrics=metrics,
                window_days=(ending_date - starting_date).days + 1,
                **databases,
                **_latency(_merge_totals(list(totals.values()), _LATENCY_FIELDS)),
            )
            await _keep_os_metrics_response(
                response_key,
                os_metrics_response,
                "latency",
                os_dbs,
                effective_user_id,
                starting_date,
                ending_date,
                _seconds_left(deadline),
            )
            return _os_metrics_answer(request, response, os_metrics_response)

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /os/metrics/latency failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS latency metrics: {str(e)}")

    async def _do_os_refreshes(refresh_dbs: list[Union[BaseDb, AsyncBaseDb]]) -> None:
        """Refresh every database at the same time, at most _MAX_CONCURRENT_OS_METRICS_READS at once."""
        for start in range(0, len(refresh_dbs), _MAX_CONCURRENT_OS_METRICS_READS):
            batch = refresh_dbs[start : start + _MAX_CONCURRENT_OS_METRICS_READS]
            await asyncio.gather(*(_do_refresh(db, None, None, None, None, None) for db in batch))

    @router.post(
        "/os/metrics/refresh",
        response_model=OSMetricsRefreshResponse,
        status_code=200,
        operation_id="refresh_os_metrics",
        summary="Refresh OS Metrics",
        description=(
            "Recalculate the metrics of every database the /os/metrics routes read, from their sessions and runs, in "
            "the background. Returns immediately with the status of each database: 'started', "
            "'already_running' if a refresh is already in progress for it, in any process, or 'disabled' when "
            "metrics calculation is turned off. "
            "Returns 202 Accepted when the refresh of a database was started or is already running, 200 when none "
            "is, and 207 Multi-Status when the refresh of a database could not be started. A database that does not "
            "answer within timeout_seconds is skipped. "
            "GET /os/metrics/refresh/status can be polled for the outcome: the first reads after the POST can still "
            "show the previous refresh, so poll until its finished_at is at or after the time of the POST, to the "
            "second."
        ),
        responses={
            200: {
                "description": "No refresh started",
                "content": {
                    "application/json": {
                        "example": {
                            "db_ids": {
                                "agno-db": {"status": "disabled", "message": "Metrics calculation is turned off"}
                            },
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            202: {
                "description": "Background refresh started",
                "content": {
                    "application/json": {
                        "example": {
                            "db_ids": {
                                "agno-db": {"status": "started", "message": "Metrics refresh started in background"}
                            },
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            207: {"description": "The refresh of some databases could not be started"},
            400: {"description": "No database configured", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            500: {"description": "Failed to refresh OS metrics", "model": InternalServerErrorResponse},
            503: {"description": "OS metrics not supported by the configured database"},
        },
    )
    async def refresh_os_metrics(
        request: Request,
        response: Response,
        background_tasks: BackgroundTasks,
        db_id: Optional[List[str]] = Query(
            default=None, description="Database ID to refresh metrics for; repeatable, every database by default"
        ),
        timeout_seconds: float = Query(default=30, gt=0, description="Seconds to wait for each database to answer"),
    ) -> OSMetricsRefreshResponse:
        try:
            os_dbs = _os_dbs(db_id)
            # Resolved before any refresh starts so an identity-less token cannot start one.
            get_scoped_user_id(request)
            remote_db = _remote_os_db(os_dbs)
            if remote_db is not None:
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                remote_response = await remote_db.refresh_os_metrics(
                    db_id=list(os_dbs), timeout_seconds=timeout_seconds, headers=headers
                )
                response.status_code = _refresh_status_code(remote_response.db_ids)
                return remote_response

            async def _start_refresh(db: Union[BaseDb, AsyncBaseDb, RemoteDb]) -> MetricsRefreshResponse:
                if isinstance(db, RemoteDb) or not has_metrics_lock_row(db):
                    raise NotImplementedError
                if not settings.metrics_calculation_enabled:
                    return MetricsRefreshResponse(status="disabled", message="Metrics calculation is turned off")
                if (await _wait_for_db(_get_refresh_status(db), timeout_seconds)).status == "running":
                    return _already_running_response()
                return MetricsRefreshResponse(status="started", message="Metrics refresh started in background")

            refreshes: dict[str, MetricsRefreshResponse] = {}
            skipped_db_ids: dict[str, str] = {}
            refresh_dbs: list[Union[BaseDb, AsyncBaseDb]] = []
            sources = [(refresh_db_id, db) for refresh_db_id, db_list in os_dbs.items() for db in db_list]
            for start in range(0, len(sources), _MAX_CONCURRENT_OS_METRICS_READS):
                batch = sources[start : start + _MAX_CONCURRENT_OS_METRICS_READS]
                outcomes = await asyncio.gather(*(_start_refresh(db) for _, db in batch), return_exceptions=True)
                for (refresh_db_id, db), outcome in zip(batch, outcomes):
                    if isinstance(outcome, NotImplementedError):
                        skipped_db_ids.setdefault(refresh_db_id, "unsupported")
                        continue
                    if isinstance(outcome, asyncio.TimeoutError):
                        skipped_db_ids.setdefault(refresh_db_id, "timeout")
                        continue
                    if isinstance(outcome, Exception):
                        logger.warning(f"OS metrics refresh failed for database '{refresh_db_id}': {outcome}")
                        refresh = MetricsRefreshResponse(status="failed", message=database_error_message(outcome))
                    elif isinstance(outcome, BaseException):
                        logger.warning(f"OS metrics refresh failed for database '{refresh_db_id}': {outcome}")
                        skipped_db_ids.setdefault(refresh_db_id, "failed")
                        continue
                    else:
                        refresh = outcome
                        if refresh.status == "started" and not isinstance(db, RemoteDb):
                            refresh_dbs.append(db)
                    # A failure of any database under an id is reported over the others under it
                    if refresh_db_id not in refreshes or refresh.status == "failed":
                        refreshes[refresh_db_id] = refresh

            # An answer that refreshed no database at all would read as a refresh of every database
            if not refreshes:
                if all(reason == "unsupported" for reason in skipped_db_ids.values()):
                    raise HTTPException(status_code=503, detail="OS metrics not supported by the configured database")
                skipped = ", ".join(f"'{db_id}' ({reason})" for db_id, reason in skipped_db_ids.items())
                raise HTTPException(status_code=503, detail=f"OS metrics not available from any database: {skipped}")
            if refresh_dbs:
                background_tasks.add_task(_do_os_refreshes, refresh_dbs)
            response.status_code = _refresh_status_code(refreshes)
            return OSMetricsRefreshResponse(db_ids=refreshes, skipped_db_ids=skipped_db_ids)

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("POST /os/metrics/refresh failed")
            raise HTTPException(status_code=500, detail=f"Error refreshing OS metrics: {str(e)}")

    @router.get(
        "/os/metrics/refresh/status",
        response_model=OSMetricsRefreshStatusResponse,
        status_code=200,
        operation_id="get_os_metrics_refresh_status",
        summary="Get OS Metrics Refresh Status",
        description=(
            "Get the status of the most recent metrics refresh of every database the /os/metrics routes read, in any "
            "process. "
            "The overall status is 'running' while any database refreshes, else 'failed' if any refresh failed, "
            "else 'idle' if any database has not refreshed, else 'completed', and finished_at is the finish of the "
            "database refreshed longest ago, so a database refreshed just now does not hide one that is not. "
            "A database that does not answer within timeout_seconds is skipped. "
            "Intended for polling after starting a refresh via POST /os/metrics/refresh: the first reads after it can "
            "still show the previous refresh, so poll until finished_at is at or after the time of the POST, to the "
            "second. "
            "'idle' means no refresh of that database has finished, and a database the POST started no refresh for "
            "stays 'idle'."
        ),
        responses={
            200: {
                "description": "Current refresh status",
                "content": {
                    "application/json": {
                        "example": {
                            "status": "completed",
                            "finished_at": "2025-08-12T08:01:49Z",
                            "db_ids": {
                                "agno-db": {
                                    "status": "completed",
                                    "started_at": "2025-08-12T08:01:47Z",
                                    "finished_at": "2025-08-12T08:01:49Z",
                                    "error": None,
                                }
                            },
                            "skipped_db_ids": {},
                        }
                    }
                },
            },
            400: {"description": "No database configured", "model": BadRequestResponse},
            404: {"description": "Database not found", "model": NotFoundResponse},
            500: {"description": "Failed to get OS metrics refresh status", "model": InternalServerErrorResponse},
            503: {"description": "OS metrics not available from any database"},
        },
    )
    async def get_os_metrics_refresh_status(
        request: Request,
        db_id: Optional[List[str]] = Query(
            default=None, description="Database ID to get the refresh status for; repeatable, every database by default"
        ),
        timeout_seconds: float = Query(default=30, gt=0, description="Seconds to wait for each database to answer"),
    ) -> OSMetricsRefreshStatusResponse:
        try:
            os_dbs = _os_dbs(db_id)
            remote_db = _remote_os_db(os_dbs)
            if remote_db is not None:
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await remote_db.get_os_metrics_refresh_status(
                    db_id=list(os_dbs), timeout_seconds=timeout_seconds, headers=headers
                )

            async def _status_of(db: Union[BaseDb, AsyncBaseDb, RemoteDb]) -> Any:
                if isinstance(db, RemoteDb) or not has_metrics_lock_row(db):
                    raise NotImplementedError
                return await _wait_for_db(_get_refresh_status(db), timeout_seconds)

            statuses: dict[str, MetricsRefreshStatusResponse] = {}
            skipped_db_ids: dict[str, str] = {}
            sources = [(status_db_id, db) for status_db_id, db_list in os_dbs.items() for db in db_list]
            for start in range(0, len(sources), _MAX_CONCURRENT_OS_METRICS_READS):
                batch = sources[start : start + _MAX_CONCURRENT_OS_METRICS_READS]
                outcomes = await asyncio.gather(*(_status_of(db) for _, db in batch), return_exceptions=True)
                for (status_db_id, _), outcome in zip(batch, outcomes):
                    if isinstance(outcome, NotImplementedError):
                        skipped_db_ids.setdefault(status_db_id, "unsupported")
                    elif isinstance(outcome, asyncio.TimeoutError):
                        skipped_db_ids.setdefault(status_db_id, "timeout")
                    elif isinstance(outcome, BaseException):
                        logger.warning(
                            f"OS metrics refresh status read failed for database '{status_db_id}': {outcome}"
                        )
                        skipped_db_ids.setdefault(status_db_id, "failed")
                    # The databases under one id answer with the status that answers for them all
                    elif status_db_id not in statuses or _refresh_status_rank(outcome) < _refresh_status_rank(
                        statuses[status_db_id]
                    ):
                        statuses[status_db_id] = outcome

            # A status of no database at all would read as a refresh of every database
            if not statuses:
                if all(reason == "unsupported" for reason in skipped_db_ids.values()):
                    raise HTTPException(status_code=503, detail="OS metrics not supported by the configured database")
                skipped = ", ".join(f"'{db_id}' ({reason})" for db_id, reason in skipped_db_ids.items())
                raise HTTPException(status_code=503, detail=f"OS metrics not available from any database: {skipped}")
            # The earliest finish, so a database refreshed just now does not hide one that is not
            finished_ats = [
                refresh_status.finished_at
                for refresh_status in statuses.values()
                if refresh_status.finished_at is not None
            ]
            return OSMetricsRefreshStatusResponse(
                status=min(statuses.values(), key=_refresh_status_rank).status,
                finished_at=min(finished_ats) if len(finished_ats) == len(statuses) else None,
                db_ids=statuses,
                skipped_db_ids=skipped_db_ids,
            )

        except HTTPException:
            raise
        except HTTPStatusError:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            logger.exception("GET /os/metrics/refresh/status failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS metrics refresh status: {str(e)}")

    return router
