"""Pure-Python merge rules for OS-level daily metrics.

Kept free of SQLAlchemy so the in-memory ``ManagedUserStore`` and the SQL-backed
``os_metrics_store`` apply identical incremental-refresh semantics.
"""

from typing import Any, Dict, List, Optional

SECONDS_PER_DAY = 24 * 60 * 60


def merge_os_metric_rows(
    existing: Dict[int, Dict[str, Any]],
    users_by_day: Dict[int, int],
    decision_metrics: Optional[List[Dict[str, Any]]],
    decisions_since: Optional[int],
    now: int,
) -> List[Dict[str, Any]]:
    """Combine fresh registration counts, fresh decision counts and preserved cached
    decision counts into the full set of daily rows. Shared by the SQL and in-memory
    backends so both apply the same incremental rules."""
    decisions_by_day: Dict[int, Dict[str, Any]] = {}
    if decisions_since is not None:
        for day, row in existing.items():
            if day < decisions_since:
                decisions_by_day[day] = row
    for row in decision_metrics or []:
        decisions_by_day[int(row["date"])] = row

    rows: List[Dict[str, Any]] = []
    for day in sorted(users_by_day.keys() | decisions_by_day.keys()):
        decision_row = decisions_by_day.get(day, {})
        users_created = users_by_day.get(day, 0)
        allowed = int(decision_row.get("authorization_allowed_count", 0))
        denied = int(decision_row.get("authorization_denied_count", 0))
        if users_created == 0 and allowed == 0 and denied == 0:
            # Nothing left on this day (e.g. its only users were deleted).
            continue
        rows.append(
            {
                "id": str(day),
                "date": day,
                "users_created_count": users_created,
                "authorization_allowed_count": allowed,
                "authorization_denied_count": denied,
                "created_at": int(existing.get(day, {}).get("created_at", now)),
                "updated_at": now,
            }
        )
    return rows
