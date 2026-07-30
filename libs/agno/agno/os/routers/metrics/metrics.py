import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union, cast

from fastapi import Depends, HTTPException, Query, Request
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.metrics.schemas import DayAggregatedMetrics, MetricsResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db, to_utc_datetime
from agno.remote.base import RemoteDb

logger = logging.getLogger(__name__)

_METRIC_COUNT_FIELDS = (
    "agent_sessions_count",
    "team_sessions_count",
    "workflow_sessions_count",
    "agent_runs_count",
    "team_runs_count",
    "workflow_runs_count",
    "users_count",
)


def _merge_model_metrics(target: List[dict], extra: List[dict]) -> None:
    """Merge extra model_metrics into target in place, summing counts per model."""
    index: Dict[Any, dict] = {}
    for m in [*target, *extra]:
        key = (m.get("model_id"), m.get("model_provider"))
        entry = index.get(key)
        if entry is None:
            index[key] = dict(m)
        else:
            entry["count"] = (entry.get("count") or 0) + (m.get("count") or 0)
    target[:] = list(index.values())


def _merge_timestamp(current: Any, candidate: Any, *, latest: bool) -> Any:
    """Merge two timestamps into the later (or earlier) one, tolerating None.

    A missing value is never coerced to 0, so the comparison stays between two
    values the adapter actually stored rather than between a stored value and an
    int the adapter never uses.
    """
    if candidate is None:
        return current
    if current is None:
        return candidate
    if latest:
        return candidate if candidate > current else current
    return candidate if candidate < current else current


def _aggregate_metrics_by_date(rows: List[dict]) -> List[dict]:
    """Collapse per-user metric rows into one aggregate row per date and period.

    Metrics are always stored per user. Unscoped callers (admins, or any caller
    when user_isolation is off) get this legacy one-row-per-day view instead of a
    per-user breakdown, so per-user activity is never exposed through an unscoped
    read. Scoped callers bypass this and receive only their own bucket.

    The aggregate carries a synthesised id: the stored per-user ids embed the owner
    on the key-value backends ({date}_{user_id}_daily) and rows arrive in no
    particular order, so keeping one member's id would both leak that owner and
    make the response unstable between calls.
    """
    by_bucket: Dict[Any, dict] = {}
    for row in rows:
        # A period-less row belongs in the daily bucket, and the same value has to
        # reach the id, or two buckets can end up sharing one id.
        period = row.get("aggregation_period") or "daily"
        day = row.get("date")
        bucket = (day, period)
        try:
            hash(bucket)
        except TypeError:
            continue  # a malformed stored date must not fail the whole read
        agg = by_bucket.get(bucket)
        if agg is None:
            # The date arrives as a date, a datetime or a string; the id is a day.
            if isinstance(day, datetime):
                day = day.date()
            agg = {**row, "id": f"{day.isoformat() if isinstance(day, date) else day}_{period}"}
            agg["token_metrics"] = dict(row.get("token_metrics") or {})
            agg["model_metrics"] = [dict(m) for m in (row.get("model_metrics") or [])]
            by_bucket[bucket] = agg
            continue
        for field in _METRIC_COUNT_FIELDS:
            agg[field] = (agg.get(field) or 0) + (row.get(field) or 0)
        for token, value in (row.get("token_metrics") or {}).items():
            agg["token_metrics"][token] = (agg["token_metrics"].get(token) or 0) + (value or 0)
        _merge_model_metrics(agg["model_metrics"], row.get("model_metrics") or [])
        agg["created_at"] = _merge_timestamp(agg.get("created_at"), row.get("created_at"), latest=False)
        agg["updated_at"] = _merge_timestamp(agg.get("updated_at"), row.get("updated_at"), latest=True)
    return list(by_bucket.values())


def get_metrics_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
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
    return attach_routes(router=router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]) -> APIRouter:
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
        db_id: Optional[str] = Query(default=None, description="Database ID to query metrics from"),
        table: Optional[str] = Query(default=None, description="The database table to use"),
    ) -> MetricsResponse:
        try:
            db = await get_db(dbs, db_id, table)

            # Scope metrics to the caller's bucket when user_isolation is on.
            # Admins (and isolation-off deployments) get the full table — which
            # in the legacy / single-tenant case is a single global bucket and
            # behaves identically to the pre-isolation API.
            scoped_user_id = get_scoped_user_id(request)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.get_metrics(
                    starting_date=starting_date, ending_date=ending_date, db_id=db_id, table=table, headers=headers
                )

            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                metrics, latest_updated_at = await db.get_metrics(
                    starting_date=starting_date, ending_date=ending_date, user_id=scoped_user_id
                )
            else:
                metrics, latest_updated_at = db.get_metrics(
                    starting_date=starting_date, ending_date=ending_date, user_id=scoped_user_id
                )

            # Unscoped callers (admins, or any caller when user_isolation is
            # off) get the legacy one-row-per-day aggregate rather than the
            # per-user rows, which are always stored. Scoped callers already
            # receive only their own bucket.
            if scoped_user_id is None:
                metrics = _aggregate_metrics_by_date(metrics)

            return MetricsResponse(
                metrics=[DayAggregatedMetrics.from_dict(metric) for metric in metrics],
                updated_at=to_utc_datetime(latest_updated_at),
            )

        except HTTPException:
            raise  # scoping and db lookup carry their own status
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error getting metrics: {str(e)}")

    @router.post(
        "/metrics/refresh",
        response_model=List[DayAggregatedMetrics],
        status_code=200,
        operation_id="refresh_metrics",
        summary="Refresh Metrics",
        description=(
            "Manually trigger recalculation of system metrics from raw data. "
            "This operation analyzes system activity logs and regenerates aggregated metrics. "
            "Useful for ensuring metrics are up-to-date or after system maintenance."
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
                                    "audio_total_tokens": 0,
                                    "audio_input_tokens": 0,
                                    "audio_output_tokens": 0,
                                    "cache_read_tokens": 0,
                                    "cache_write_tokens": 0,
                                    "reasoning_tokens": 0,
                                },
                                "model_metrics": [{"model_id": "gpt-4o", "model_provider": "OpenAI", "count": 2}],
                                "date": "2025-08-12T00:00:00Z",
                                "created_at": "2025-08-12T08:01:47Z",
                                "updated_at": "2025-08-12T08:01:47Z",
                            }
                        ]
                    }
                },
            },
            500: {"description": "Failed to refresh metrics", "model": InternalServerErrorResponse},
        },
    )
    async def calculate_metrics(
        request: Request,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for metrics calculation"),
        table: Optional[str] = Query(default=None, description="Table to use for metrics calculation"),
    ) -> List[DayAggregatedMetrics]:
        try:
            db = await get_db(dbs, db_id, table)

            # Scope the refresh response to the caller, like GET /metrics.
            scoped_user_id = get_scoped_user_id(request)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.refresh_metrics(db_id=db_id, table=table, headers=headers)

            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                result = await db.calculate_metrics()
            else:
                result = db.calculate_metrics()
            if result is None:
                return []

            # Non-admins see only their own bucket; unscoped callers (admins /
            # isolation-off) get the legacy one-row-per-day aggregate.
            if scoped_user_id is not None:
                result = [metric for metric in result if metric.get("user_id") == scoped_user_id]
            else:
                result = _aggregate_metrics_by_date(result)

            return [DayAggregatedMetrics.from_dict(metric) for metric in result]

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error refreshing metrics: {str(e)}")

    return router
