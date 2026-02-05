from __future__ import annotations

from time import time
from typing import Any, Dict, Optional


def pause_job_snapshot(
    snapshot: Dict[str, Any],
    *,
    reason: str,
    message: Optional[str] = None,
    gate_type: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    snapshot["status"] = "paused"
    snapshot["pause"] = {
        "reason": reason,
        "gate_type": gate_type,
        "message": message,
        "payload": payload or {},
        "paused_at": now if now is not None else int(time()),
    }
    snapshot["updated_at"] = now if now is not None else int(time())
    return snapshot


def resume_job_snapshot(
    snapshot: Dict[str, Any],
    *,
    now: Optional[int] = None,
    reset_running_steps: bool = True,
) -> Dict[str, Any]:
    if reset_running_steps:
        for step in snapshot.get("steps") or []:
            if isinstance(step, dict) and step.get("status") == "running":
                step["status"] = "pending"

    snapshot["pause"] = None
    snapshot["status"] = "running"
    snapshot["updated_at"] = now if now is not None else int(time())
    return snapshot

