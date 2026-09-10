"""OS-level metrics: numbers about the AgentOS itself rather than about the traffic
one database has seen.

The run metrics under ``/metrics`` are per-database usage telemetry, selected by
``db_id`` and partitioned per user. OS metrics are OS-wide and come from the OS's own
singletons. The first source is the managed user directory (and the role store when
one is configured); further sources land here as sibling sections of the response.

Everything is computed on read. The directory is bounded by the product's user limits
and its ``created_at`` column is indexed, so a bounded group-by is cheaper than keeping
a cache table in step with it. A source that does need one can add it without changing
this contract.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from agno.os.auth import get_authentication_dependency
from agno.os.routers.metrics.schemas import (
    OSMetricsResponse,
    UserDirectoryMetrics,
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


def collect_user_directory_metrics(
    user_store: "ManagedUserStore",
    role_store: "Optional[ManagedRoleStore]" = None,
    starting_at: Optional[int] = None,
    ending_before: Optional[int] = None,
) -> UserDirectoryMetrics:
    """The ``users`` section. The date range bounds only the per-day series; the counts
    always describe the whole directory as it is now."""
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

    return UserDirectoryMetrics(
        total=total,
        active=active,
        disabled=total - active,
        without_role=without_role,
        created_per_day=created,
        by_role=by_role,
    )


def collect_os_metrics(
    user_store: "ManagedUserStore",
    role_store: "Optional[ManagedRoleStore]" = None,
    starting_at: Optional[int] = None,
    ending_before: Optional[int] = None,
) -> OSMetricsResponse:
    """Assemble every OS metrics section. New sources add a section here."""
    return OSMetricsResponse(
        users=collect_user_directory_metrics(
            user_store, role_store, starting_at=starting_at, ending_before=ending_before
        )
    )


def get_os_metrics_router(
    user_store: "ManagedUserStore",
    role_store: "Optional[ManagedRoleStore]" = None,
    settings: AgnoAPISettings = AgnoAPISettings(),
    prefix: str = "/metrics/os",
) -> APIRouter:
    """Build the authenticated router serving OS-level metrics."""
    router = APIRouter(
        prefix=prefix,
        tags=["Metrics"],
        dependencies=[Depends(get_authentication_dependency(settings))],
    )

    @router.get(
        "",
        response_model=OSMetricsResponse,
        operation_id="get_os_metrics",
        summary="Get OS Metrics",
        description=(
            "OS-wide metrics, computed on read. The users section carries the directory size "
            "(total, active, disabled), users created per UTC day, and, when a role store is "
            "configured, how many users hold each role and how many hold none. The date range "
            "bounds only the per-day series."
        ),
    )
    async def get_os_metrics(
        starting_date: Optional[date] = Query(default=None, description="First UTC day of the series (YYYY-MM-DD)"),
        ending_date: Optional[date] = Query(default=None, description="Last UTC day of the series (YYYY-MM-DD)"),
    ) -> OSMetricsResponse:
        starting_at, ending_before = _day_bounds(starting_date, ending_date)
        try:
            return await run_in_threadpool(
                collect_os_metrics,
                user_store,
                role_store,
                starting_at=starting_at,
                ending_before=ending_before,
            )
        except Exception as error:
            logger.exception("GET /metrics/os failed")
            raise HTTPException(status_code=500, detail=f"Error getting OS metrics: {str(error)}")

    return router
