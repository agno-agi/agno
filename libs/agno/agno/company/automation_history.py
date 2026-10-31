"""Bound repeated Task diagnostics in the existing scheduler history."""

import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from agno.company.execution import _call
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, ScheduleRun
from agno.scheduler.run_id import new_schedule_run_id


def _task_state(task: Dict[str, Any]) -> str:
    fields = {
        key: task.get(key) for key in ("status", "project_id", "updated_at", "transitions", "result", "deleted_at")
    }
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


async def _history(db: Any) -> List[Dict[str, Any]]:
    rows = []
    page = 1
    while True:
        batch, total = await _call(db, "get_schedule_runs", COMPANY_AUTOMATION_SCHEDULE_ID, limit=100, page=page)
        rows.extend(batch)
        if page * 100 >= total:
            return sorted(rows, key=lambda row: (row["triggered_at"], row["id"]), reverse=True)
        page += 1


async def _record_task_failures(db: Any, company_db: Any, outcomes: List[Dict[str, Any]]) -> None:
    """The scheduler's exclusive tick claim serializes updates to each failure streak."""
    latest: Dict[str, Tuple[Dict[str, Any], Dict[str, Any]]] = {}
    for row in await _history(db):
        diagnostic = (row.get("output") or {}).get("automation_failure")
        if diagnostic:
            latest.setdefault(diagnostic["task_id"], (row, diagnostic))
    for outcome in outcomes:
        task_id = outcome.get("task_id")
        if not task_id:
            continue
        previous = latest.get(task_id)
        if outcome.get("status") != "failed":
            if previous and previous[1].get("active"):
                await _call(
                    db,
                    "update_schedule_run",
                    previous[0]["id"],
                    output={**previous[0]["output"], "automation_failure": {**previous[1], "active": False}},
                )
            continue
        try:
            task = await _call(company_db, "get_task", task_id)
        except Exception:
            # The Task read itself can be the failure being recorded.
            task = None
        state = _task_state(task) if task is not None else None
        now = int(time.time())
        same = (
            previous
            and previous[1].get("active")
            and previous[1].get("state") == state
            and previous[1]["reason"] == outcome["reason"]
        )
        diagnostic = {
            "task_id": task_id,
            "product_id": task.get("product_id") if task else None,
            "reason": outcome["reason"],
            "count": previous[1]["count"] + 1 if same and previous is not None else 1,
            "state": state,
            "active": True,
        }
        output = {"tasks": [outcome], "automation_failure": diagnostic}
        if same and previous is not None:
            await _call(db, "update_schedule_run", previous[0]["id"], output=output, completed_at=now)
        else:
            await _call(
                db,
                "create_schedule_run",
                ScheduleRun(
                    id=new_schedule_run_id(),
                    schedule_id=COMPANY_AUTOMATION_SCHEDULE_ID,
                    triggered_at=now,
                    completed_at=now,
                    status="failed",
                    error=outcome["reason"],
                    output=output,
                ).to_dict(),
            )


async def aautomation_failures(db: Any, company_db: Any, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return current actionable failure streaks, including their repeated tick counts."""
    failures = []
    seen = set()
    for row in await _history(db):
        diagnostic = (row.get("output") or {}).get("automation_failure")
        if not diagnostic or diagnostic["task_id"] in seen:
            continue
        seen.add(diagnostic["task_id"])
        if not diagnostic.get("active") or (product_id is not None and diagnostic.get("product_id") != product_id):
            continue
        task = await _call(company_db, "get_task", diagnostic["task_id"])
        if task is not None and _task_state(task) == diagnostic["state"]:
            failures.append({key: diagnostic[key] for key in ("task_id", "reason", "count")})
    return failures


def automation_failures(db: Any, company_db: Any, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read current failure streaks through synchronous stores."""
    rows = []
    page = 1
    while True:
        batch, total = db.get_schedule_runs(COMPANY_AUTOMATION_SCHEDULE_ID, limit=100, page=page)
        rows.extend(batch)
        if page * 100 >= total:
            break
        page += 1
    failures = []
    seen = set()
    for row in sorted(rows, key=lambda row: (row["triggered_at"], row["id"]), reverse=True):
        diagnostic = (row.get("output") or {}).get("automation_failure")
        if not diagnostic or diagnostic["task_id"] in seen:
            continue
        seen.add(diagnostic["task_id"])
        if not diagnostic.get("active") or (product_id is not None and diagnostic.get("product_id") != product_id):
            continue
        task = company_db.get_task(diagnostic["task_id"])
        if task is not None and _task_state(task) == diagnostic["state"]:
            failures.append({key: diagnostic[key] for key in ("task_id", "reason", "count")})
    return failures
