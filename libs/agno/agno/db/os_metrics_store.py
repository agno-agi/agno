"""Shared SQLAlchemy storage for OS-level daily metrics."""

import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine


def calculate_os_metrics(engine: Engine, users_table: Any, metrics_table: Any) -> List[Dict[str, Any]]:
    """Rebuild daily OS aggregates from their source tables atomically."""
    seconds_per_day = 24 * 60 * 60
    day_start = (users_table.c.created_at - (users_table.c.created_at % seconds_per_day)).label("date")
    now = int(time.time())

    with engine.begin() as conn:
        grouped_users = list(
            conn.execute(
                select(day_start, func.count().label("users_created_count"))
                .group_by(day_start)
                .order_by(day_start.asc())
            )
        )
        rows = [
            {
                "id": str(int(row.date)),
                "date": int(row.date),
                "users_created_count": int(row.users_created_count),
                "created_at": now,
                "updated_at": now,
            }
            for row in grouped_users
        ]

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
