"""Validation and explicit lifecycle rules for Company tasks."""

import time
from typing import Any, Dict, Optional

# In progress is entered only by starting a run; review and completion need an earlier attempt.
TASK_TRANSITIONS = {
    "backlog": {"ready", "in_review", "done", "cancelled"},
    "ready": {"backlog", "in_progress", "in_review", "done", "cancelled"},
    "in_progress": {"backlog", "ready", "in_review", "done", "cancelled"},
    "in_review": {"backlog", "ready", "in_progress", "done", "cancelled"},
    "done": {"backlog", "ready", "in_review", "cancelled"},
    "cancelled": {"backlog", "ready", "in_review", "done"},
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


def task_transition_blocker(task: Dict[str, Any], target: str, run_holding: bool = False) -> Optional[str]:
    """Name the error a move to target raises, or None when the Task allows it."""
    attempted = any("attempt" in entry for entry in task.get("transitions") or [])
    if target == "in_progress":
        if task["status"] not in {"ready", "in_progress", "in_review"} or not task.get("executor_id"):
            return "Only accepted work can be started"
        if task.get("executor_type") not in {"agent", "team", "workflow"}:
            return "Select a registered agent, team or workflow executor"
        if task["status"] == "in_review" and not attempted:
            return "A revision requires a previous Task attempt"
        return None
    if target not in TASK_TRANSITIONS.get(task["status"], set()):
        return f"Invalid task transition from {task['status']} to {target}"
    # An executing or paused run holds the Task in progress until it is cancelled.
    if run_holding:
        return f"Cancel the run with POST /company/runs/{task['job_id']}/cancel to leave In progress"
    # Review and completion reached from anywhere but the step before them need an earlier attempt.
    previous = {"in_review": "in_progress", "done": "in_review"}
    if target in previous and task["status"] != previous[target] and not attempted:
        return ("Review" if target == "in_review" else "Completion") + " requires a previous Task attempt"
    return None


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
    # Runs, not direct moves, apply the run rules to In progress.
    blocker = None if target == "in_progress" else task_transition_blocker(existing, target)
    if blocker is not None:
        raise ValueError(blocker)
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


def task_next_attempt(task: Dict[str, Any]) -> int:
    """A new run takes the attempt after the highest one recorded on the Task."""
    return max((entry["attempt"] for entry in task.get("transitions") or [] if "attempt" in entry), default=0) + 1


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
    blocker = task_transition_blocker(existing, "in_progress")
    if blocker is not None:
        raise ValueError(blocker)
    history = existing.get("transitions") or []
    if attempt != task_next_attempt(existing):
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
