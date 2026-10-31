"""Validation and explicit lifecycle rules for Company projects."""

import time
from typing import Any, Dict, Optional, Sequence

PROJECT_TRANSITIONS = {
    "proposed": {"cancelled", "active"},
    "active": {"cancelled", "done"},
    "done": set(),
    "cancelled": set(),
}


def validate_project_fields(fields: Dict[str, Any]) -> None:
    """Identity, acceptance and lifecycle are never descriptive edits."""
    unknown = set(fields) - {"target_date", "name", "outcome"}
    if unknown:
        raise ValueError(f"Unsupported project fields: {sorted(unknown)}")
    if "name" in fields and (not isinstance(fields["name"], str) or not fields["name"].strip()):
        raise ValueError("name must be a non-empty string")
    if fields.get("outcome") is not None and not isinstance(fields["outcome"], str):
        raise ValueError("outcome must be a string or None")
    if fields.get("target_date") is not None and (
        not isinstance(fields["target_date"], int) or isinstance(fields["target_date"], bool)
    ):
        raise ValueError("target_date must be epoch seconds or None")


def project_transition_fields(
    existing: Dict[str, Any],
    target: str,
    reason: str,
    accepted_by: Optional[str] = None,
    tasks: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Build lifecycle fields after validating a transition; callers persist atomically."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("A transition requires a non-empty reason")
    if target not in PROJECT_TRANSITIONS.get(existing["status"], set()):
        raise ValueError(f"Invalid project transition from {existing['status']} to {target}")
    if target == "done":
        validate_project_completion(tasks)
    now = int(time.time())
    fields: Dict[str, Any] = {"status": target, "updated_at": now}
    fields["transitions"] = [
        *(existing.get("transitions") or []),
        {"from": existing["status"], "target": target, "reason": reason, "user_id": accepted_by, "created_at": now},
    ]
    return fields


def validate_project_completion(tasks: Sequence[Dict[str, Any]]) -> None:
    """A Project cannot finish while any of its Tasks is non-terminal."""
    open_tasks = [task for task in tasks if task["status"] not in {"done", "cancelled"}]
    if open_tasks:
        names = ", ".join(str(task["title"]) + " (" + str(task["id"]) + ")" for task in open_tasks)
        raise ValueError("Project has open Tasks: " + names)
