import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from fastapi import BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.routing import APIRouter
from starlette.concurrency import run_in_threadpool

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.utils import aggregate_metrics_by_date, is_legacy_metric
from agno.exceptions import AgnoError
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.middleware.user_scope import resolve_db_and_scope
from agno.os.routers.insights.schemas import MetricsInsightsResponse, ModelUsage
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import AgnoHTTPException
from agno.remote.base import RemoteDb
from agno.utils.log import log_error, log_exception

# Insights are recomputed at most this often per owner and window, which bounds how far they
# can trail the daily metrics. Past this age an entry is still served, and a recompute starts
# in the background.
CACHE_TTL_SECONDS = 300

# The window is caller-supplied, so a multi-tenant OS can be walked across owners and day
# counts. Entries are evicted least-recently-read beyond this.
CACHE_MAX_ENTRIES = 512


def get_insights_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
) -> APIRouter:
    """Create insights router with comprehensive OpenAPI documentation for insight endpoints."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Insights"],
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
    # Most recent computation per db id, owner and window. Only mutated on the event loop
    # (the sync database reads themselves run in the threadpool), so no lock is needed.
    # Per-process: each worker warms its own entries.
    cache: "OrderedDict[Tuple[str, Optional[str], int], Tuple[MetricsInsightsResponse, float]]" = OrderedDict()

    # Keys with a background recompute in flight, so concurrent opens of a stale entry start
    # one recompute between them rather than one each.
    recomputing: Set[Tuple[str, Optional[str], int]] = set()

    def _cache_get(key: Tuple[str, Optional[str], int]) -> Optional[Tuple[MetricsInsightsResponse, bool]]:
        entry = cache.get(key)
        if entry is None:
            return None
        insights, cached_at = entry
        cache.move_to_end(key)
        return insights, time.monotonic() - cached_at <= CACHE_TTL_SECONDS

    def _cache_put(key: Tuple[str, Optional[str], int], insights: MetricsInsightsResponse) -> None:
        cache[key] = (insights, time.monotonic())
        cache.move_to_end(key)
        while len(cache) > CACHE_MAX_ENTRIES:
            cache.popitem(last=False)

    async def _compute_metrics_insights(
        db: Union[BaseDb, AsyncBaseDb], effective_user_id: Optional[str], days: int
    ) -> MetricsInsightsResponse:
        ending_date = datetime.now(timezone.utc).date()
        starting_date = ending_date - timedelta(days=days - 1)

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

        return _build_metrics_insights(metrics, days)

    def _build_metrics_insights(metrics: List[Dict[str, Any]], days: int) -> MetricsInsightsResponse:
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
                model_provider=provider,
                run_count=count,
                run_share=round(count / total_model_runs * 100, 1) if total_model_runs else 0.0,
            )
            for (model_id, provider), count in sorted(run_counts.items(), key=lambda item: (-item[1], item[0][0]))
        ]

        return MetricsInsightsResponse(
            models=models,
            total_runs=total_model_runs,
            window_days=days,
            computed_at=datetime.now(timezone.utc),
        )

    async def _do_recompute(
        db: Union[BaseDb, AsyncBaseDb],
        key: Tuple[str, Optional[str], int],
        effective_user_id: Optional[str],
        days: int,
    ) -> None:
        try:
            _cache_put(key, await _compute_metrics_insights(db, effective_user_id, days))
        except Exception as e:
            # The stale entry keeps being served, and the next open retries
            log_error(f"Insights recompute failed: {e}")
        finally:
            recomputing.discard(key)

    @router.get(
        "/insights/metrics",
        response_model=MetricsInsightsResponse,
        status_code=200,
        operation_id="get_metrics_insights",
        summary="Get Metrics Insights",
        description=(
            "Retrieve insights about this AgentOS built from its daily metrics: how many runs each "
            "model served over a window of days.\n\n"
            "Insights read the same daily metrics GET /metrics returns, so they are only as current "
            "as those. POST /metrics/refresh rebuilds the daily metrics; SQLite and Postgres also "
            "rebuild them at most once a minute when they are read.\n\n"
            "The result is cached per owner and window. Once an entry is older than its TTL it is "
            "still returned immediately, and a recompute starts in the background. Pass refresh=true "
            "to recompute from the daily metrics and wait for the result; it does not rebuild the "
            "daily metrics themselves."
        ),
        responses={
            200: {
                "description": "Insights computed successfully",
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
                            "total_runs": 120,
                            "window_days": 30,
                            "computed_at": "2025-07-31T12:49:01Z",
                        }
                    }
                },
            },
            500: {"description": "Failed to compute insights", "model": InternalServerErrorResponse},
        },
    )
    async def get_metrics_insights(
        request: Request,
        background_tasks: BackgroundTasks,
        days: int = Query(default=30, description="Number of days the insights cover", ge=1, le=365),
        user_id: Optional[str] = Query(
            default=None, description="Return only this user's insights. Ignored for non-admin callers"
        ),
        refresh: bool = Query(default=False, description="Recompute now instead of serving the cached result"),
        db_id: Optional[str] = Query(default=None, description="Database ID to compute insights from"),
    ) -> MetricsInsightsResponse:
        try:
            db, effective_user_id = await resolve_db_and_scope(request, dbs, db_id, fallback_user_id=user_id)

            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                ending_date = datetime.now(timezone.utc).date()
                remote_metrics = await db.get_metrics(
                    starting_date=ending_date - timedelta(days=days - 1),
                    ending_date=ending_date,
                    db_id=db_id,
                    headers=headers,
                )
                # Not cached: the remote AgentOS scopes the metrics by the forwarded token, which
                # the cache key cannot tell apart
                return _build_metrics_insights([metric.model_dump() for metric in remote_metrics.metrics], days)

            cache_key = (str(db.id), effective_user_id, days)
            if not refresh:
                cached = _cache_get(cache_key)
                if cached is not None:
                    insights, fresh = cached
                    # A stale entry is still served straight away; opening the page never waits on
                    # a recompute once one has completed for this owner and window
                    if not fresh and cache_key not in recomputing:
                        recomputing.add(cache_key)
                        background_tasks.add_task(_do_recompute, db, cache_key, effective_user_id, days)
                    return insights

            insights = await _compute_metrics_insights(db, effective_user_id, days)
            _cache_put(cache_key, insights)
            return insights

        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
        except Exception as e:
            log_exception("GET /insights/metrics failed")
            raise HTTPException(status_code=500, detail=f"Error getting insights: {str(e)}")

    return router
