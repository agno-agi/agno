"""Metrics about the managed user directory.

Everything here is computed on read from the directory (and the role store when one is
configured). There is no cache and no refresh step: the directory is bounded by the
product's user limits and its ``created_at`` column is indexed, so a bounded group-by
is cheaper than keeping a second table in step with it.

These numbers are OS-wide identity data, not per-database usage telemetry, which is why
they live beside ``/metrics`` rather than inside it: the run metrics are selected by
``db_id`` and partitioned per user, and the directory is neither.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from agno.os.auth import get_authentication_dependency
from agno.os.routers.metrics.schemas import (
    UserDirectoryCounts,
    UserMetricsResponse,
    UsersByRole,
    UsersCreatedOnDay,
)
from agno.os.settings import AgnoAPISettings

if TYPE_CHECKING:
    from agno.os.authz.role_store import ManagedRoleStore
    from agno.os.authz.user_store import ManagedUserStore

logger = logging.getLogger(__name__)


def _day_bounds(starting_date: Optional[date], ending_date: Optional[date]) -> tuple[Optional[int], Optional[int]]:
    """Inclusive start / exclusive end of the requested UTC day range, as epoch seconds."""
    if starting_date is not None and ending_date is not None and starting_date > ending_date:
        raise HTTPException(status_code=422, detail="starting_date must be on or before ending_date")
    starting_at = (
        int(datetime.combine(starting_date, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        if starting_date is not None
        else None
    )
    ending_before = (
        int((datetime.combine(ending_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)).timestamp())
        if ending_date is not None
        else None
    )
    return starting_at, ending_before


def collect_user_metrics(
    user_store: "ManagedUserStore",
    role_store: "Optional[ManagedRoleStore]" = None,
    starting_at: Optional[int] = None,
    ending_before: Optional[int] = None,
) -> UserMetricsResponse:
    """Read the directory metrics. The date range bounds only the per-day series; the
    counts always describe the whole directory as it is now."""
    total = user_store.count()
    active = user_store.count(include_disabled=False)
    created = [
        UsersCreatedOnDay(date=datetime.fromtimestamp(row["date"], tz=timezone.utc).date(), count=row["count"])
        for row in user_store.created_by_day(starting_at=starting_at, ending_before=ending_before)
    ]

    by_role: Optional[List[UsersByRole]] = None
    without_role: Optional[int] = None
    if role_store is not None:
        # Roles come from the role store, not the grouping table directly, so a custom
        # policy engine that keeps assignments elsewhere is counted correctly. Disabled
        # users keep their role and stay in the breakdown, matching ``total``.
        roles_of = role_store.roles_of_many(user_store.ids())
        counts: Dict[str, int] = {}
        without_role = 0
        for roles in roles_of.values():
            if not roles:
                without_role += 1
                continue
            for role in roles:
                counts[role] = counts.get(role, 0) + 1
        by_role = [UsersByRole(role=role, count=count) for role, count in sorted(counts.items())]

    return UserMetricsResponse(
        users=UserDirectoryCounts(total=total, active=active, disabled=total - active, without_role=without_role),
        users_created=created,
        users_by_role=by_role,
    )


def get_user_metrics_router(
    user_store: "ManagedUserStore",
    role_store: "Optional[ManagedRoleStore]" = None,
    settings: AgnoAPISettings = AgnoAPISettings(),
    prefix: str = "/metrics/users",
) -> APIRouter:
    """Build the authenticated router serving metrics about the user directory."""
    router = APIRouter(
        prefix=prefix,
        tags=["Metrics"],
        dependencies=[Depends(get_authentication_dependency(settings))],
    )

    @router.get(
        "",
        response_model=UserMetricsResponse,
        operation_id="get_user_metrics",
        summary="Get User Directory Metrics",
        description=(
            "Directory size (total, active, disabled), users created per UTC day, and, when a "
            "role store is configured, how many users hold each role and how many hold none. "
            "The date range bounds only the per-day series."
        ),
    )
    async def get_user_metrics(
        starting_date: Optional[date] = Query(default=None, description="First UTC day of the series (YYYY-MM-DD)"),
        ending_date: Optional[date] = Query(default=None, description="Last UTC day of the series (YYYY-MM-DD)"),
    ) -> UserMetricsResponse:
        starting_at, ending_before = _day_bounds(starting_date, ending_date)
        try:
            return await run_in_threadpool(
                collect_user_metrics,
                user_store,
                role_store,
                starting_at=starting_at,
                ending_before=ending_before,
            )
        except Exception as error:
            logger.exception("GET /metrics/users failed")
            raise HTTPException(status_code=500, detail=f"Error getting user metrics: {str(error)}")

    return router
