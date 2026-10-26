"""Validation and explicit lifecycle rules for Company tasks."""

import time
from typing import Any, Dict, Optional

TASK_TRANSITIONS = {
    "backlog": {"ready", "cancelled"},
    "ready": {"cancelled", "in_progress", "backlog"},
    "in_progress": {"in_review", "cancelled", "backlog"},
    "in_review": {"cancelled", "done", "in_progress", "backlog"},
    "done": set(),
    "cancelled": set(),
}


def validate_task_fields(fields: Dict[str, Any]) -> None:
    """Identity, acceptance and lifecycle are never descriptive edits."""
    unknown = set(fields) - {"title", "brief", "project_id", "evidence", "executor_type", "executor_id"}
    if unknown:
        raise ValueError(f"Unsupported task fields: {sorted(unknown)}")
    if fields.get("executor_type") is not None and fields["executor_type"] not in {
        "agent",
        "team",
        "workflow",
    }:
        raise ValueError("Invalid proposed executor type")
    if fields.get("executor_id") is not None and (
        not isinstance(fields["executor_id"], str) or not fields["executor_id"].strip()
    ):
        raise ValueError("Invalid proposed executor id")
    if fields.get("evidence") is not None and not isinstance(fields["evidence"], list):
        raise ValueError("evidence must be a list or None")
    if "title" in fields and (not isinstance(fields["title"], str) or not fields["title"].strip()):
        raise ValueError("title must be a non-empty string")
    if fields.get("brief") is not None and not isinstance(fields["brief"], str):
        raise ValueError("brief must be a string or None")
    if fields.get("project_id") is not None and (
        not isinstance(fields["project_id"], str) or not fields["project_id"].strip()
    ):
        raise ValueError("project_id must be a non-empty string or None")


def task_transition_fields(
    existing: Dict[str, Any],
    target: str,
    reason: str,
    accepted_by: Optional[str] = None,
    executor_type: Optional[str] = None,
    executor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build lifecycle fields after validating a transition; callers persist atomically."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("A transition requires a non-empty reason")
    if target not in TASK_TRANSITIONS.get(existing["status"], set()):
        raise ValueError(f"Invalid task transition from {existing['status']} to {target}")
    now = int(time.time())
    fields: Dict[str, Any] = {"status": target, "updated_at": now}
    if target == "ready":
        if (
            executor_type not in {"agent", "team", "workflow"}
            or not isinstance(executor_id, str)
            or not executor_id.strip()
        ):
            raise ValueError("Ready requires an executor type and id")
        fields.update(executor_type=executor_type, executor_id=executor_id, accepted_by=accepted_by, accepted_at=now)
    elif executor_type is not None or executor_id is not None:
        raise ValueError("Only Ready can set an executor")
    if target == "backlog":
        fields.update(executor_type=None, executor_id=None, accepted_by=None, accepted_at=None)
    fields["transitions"] = [
        *(existing.get("transitions") or []),
        {"from": existing["status"], "target": target, "reason": reason, "user_id": accepted_by, "created_at": now},
    ]
    if target == "ready":
        from agno.run.authorization import AUTHORIZATION_KEY, authorization_snapshot

        fields["transitions"][-1][AUTHORIZATION_KEY] = authorization_snapshot()
    return fields


def public_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Keep persisted caller claims out of API and tool results."""
    from agno.run.authorization import AUTHORIZATION_KEY

    return {
        **task,
        "transitions": [
            {k: v for k, v in entry.items() if k != AUTHORIZATION_KEY} for entry in task.get("transitions", [])
        ],
    }


def task_run_id(task_id: str, attempt: int) -> str:
    """The same Task attempt always names the same ordinary queued run."""
    from uuid import NAMESPACE_URL, uuid5

    return str(uuid5(NAMESPACE_URL, f"agno:company:task:{task_id}:attempt:{attempt}"))


def task_run_fields(
    existing: Dict[str, Any],
    attempt: int,
    user_id: Optional[str],
    run_db_id: Optional[str] = None,
    session_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reserve execution in the Task lifecycle, retaining the session across attempts."""
    from uuid import NAMESPACE_URL, uuid5

    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    if existing["status"] not in {"ready", "in_progress", "in_review"} or not existing.get("executor_id"):
        raise ValueError("Only accepted work can be started")
    if existing.get("executor_type") not in {"agent", "team", "workflow"}:
        raise ValueError("Select a registered agent, team or workflow executor")
    history = existing.get("transitions") or []
    attempts = [entry["attempt"] for entry in history if "attempt" in entry]
    if existing["status"] == "in_review" and not attempts:
        raise ValueError("A revision requires a previous Task attempt")
    if attempt != max(attempts, default=0) + 1:
        raise ValueError("Start the next Task attempt, or retry the original attempt")
    now = int(time.time())
    return {
        "session_id": existing.get("session_id") or str(uuid5(NAMESPACE_URL, f"agno:company:task:{existing['id']}")),
        "job_id": task_run_id(existing["id"], attempt),
        "status": "in_progress",
        "updated_at": now,
        "result": None,
        "transitions": [
            *history,
            {
                "from": existing["status"],
                "target": "in_progress",
                "reason": "Task execution requested",
                "user_id": user_id,
                "started_by": user_id,
                "session_user_id": session_user_id if session_user_id is not None else existing.get("user_id"),
                "created_at": now,
                "attempt": attempt,
                "run_db_id": run_db_id,
            },
        ],
    }


def _acceptance_count(histories, routine_id, policy):
    # Each row is one work record; repeated acceptance spends its budget once.
    return sum(
        any(
            entry.get("target") in {"ready", "done"}
            and (entry.get("auto_accept") or {}).get("routine_id") == routine_id
            and entry["auto_accept"].get("policy") == policy
            for entry in (history or [])
        )
        for history in histories
    )
