"""Shared SQLAlchemy storage for OS-level daily metrics."""

import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, inspect, insert, select
from sqlalchemy.engine import Engine


_AUTHORIZATION_COUNT_COLUMNS = (
    "authorization_allowed_count",
    "authorization_denied_count",
)
_LEGACY_OS_METRICS_COLUMNS = {
    "id",
    "users_created_count",
    "date",
    "created_at",
    "updated_at",
}


def upgrade_authorization_count_columns(
    engine: Engine,
    table_name: str,
    schema: Optional[str] = None,
) -> None:
    """Add authorization count columns to an existing OS metrics cache.

    ``os_metrics`` is a derived snapshot, but adding these columns in place avoids
    discarding a valid registration snapshot when upgrading from the first version
    of the table. Other schema mismatches are intentionally left to the backend's
    normal validation.
    """
    existing_columns = {column["name"] for column in inspect(engine).get_columns(table_name, schema=schema)}
    if not _LEGACY_OS_METRICS_COLUMNS.issubset(existing_columns):
        return

    missing_columns = [column for column in _AUTHORIZATION_COUNT_COLUMNS if column not in existing_columns]
    if not missing_columns:
        return

    quote = engine.dialect.identifier_preparer.quote
    qualified_table = quote(table_name)
    if schema:
        qualified_table = f"{quote(schema)}.{qualified_table}"
    if_not_exists = " IF NOT EXISTS" if engine.dialect.name == "postgresql" else ""

    with engine.begin() as connection:
        for column in missing_columns:
            connection.exec_driver_sql(
                f"ALTER TABLE {qualified_table} ADD COLUMN{if_not_exists} {quote(column)} BIGINT NOT NULL DEFAULT 0"
            )


def calculate_os_metrics(
    engine: Engine,
    users_table: Any,
    metrics_table: Any,
    decision_metrics: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
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
        users_by_day = {int(row.date): int(row.users_created_count) for row in grouped_users}
        decisions_by_day = {int(row["date"]): row for row in decision_metrics or []}
        rows = []
        for day in sorted(users_by_day.keys() | decisions_by_day.keys()):
            decision_row = decisions_by_day.get(day, {})
            rows.append(
                {
                    "id": str(day),
                    "date": day,
                    "users_created_count": users_by_day.get(day, 0),
                    "authorization_allowed_count": int(decision_row.get("authorization_allowed_count", 0)),
                    "authorization_denied_count": int(decision_row.get("authorization_denied_count", 0)),
                    "created_at": now,
                    "updated_at": now,
                }
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
