"""Shared SQLAlchemy storage for OS-level daily metrics."""

import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine

from agno.db.os_metrics_aggregation import SECONDS_PER_DAY, merge_os_metric_rows


def calculate_os_metrics(
    engine: Engine,
    users_table: Any,
    metrics_table: Any,
    decision_metrics: Optional[List[Dict[str, Any]]] = None,
    decisions_since: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Rebuild daily OS aggregates atomically.

    Registrations are always recomputed from the user directory: the table is small and
    deleted users must drop out of history. Authorization decisions are the fast-growing
    source (one row per authenticated request), so the caller aggregates only the rows
    at or after ``decisions_since`` and the cached counts for earlier days are kept.
    ``decisions_since=None`` means ``decision_metrics`` covers all history and replaces
    every cached count.
    """
    day_start = (users_table.c.created_at - (users_table.c.created_at % SECONDS_PER_DAY)).label("date")
    now = int(time.time())

    with engine.begin() as conn:
        existing = {int(row["date"]): dict(row) for row in conn.execute(select(metrics_table)).mappings()}
        grouped_users = list(
            conn.execute(
                select(day_start, func.count().label("users_created_count"))
                .group_by(day_start)
                .order_by(day_start.asc())
            )
        )
        users_by_day = {int(row.date): int(row.users_created_count) for row in grouped_users}
        rows = merge_os_metric_rows(
            existing=existing,
            users_by_day=users_by_day,
            decision_metrics=decision_metrics,
            decisions_since=decisions_since,
            now=now,
        )

        # Readers see either the old complete snapshot or the new one.
        conn.execute(delete(metrics_table))
        if rows:
            conn.execute(insert(metrics_table), rows)

    return rows


def get_os_metrics(
    engine: Engine,
    metrics_table: Any,
    starting_at: Optional[int] = None,
    ending_before: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    filters = []
    if starting_at is not None:
        filters.append(metrics_table.c.date >= starting_at)
    if ending_before is not None:
        filters.append(metrics_table.c.date < ending_before)

    statement = select(metrics_table).where(*filters).order_by(metrics_table.c.date.asc())
    with engine.connect() as conn:
        rows = [dict(row) for row in conn.execute(statement).mappings()]
        latest_updated_at = conn.execute(select(func.max(metrics_table.c.updated_at))).scalar()

    return rows, int(latest_updated_at) if latest_updated_at is not None else None
