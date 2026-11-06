"""Report the delegated Project's assessed outcome before retiring its receipt."""

import hashlib
import json
from typing import Any, Dict, List
from urllib.parse import quote


async def _collect_projects(delivery: Any, app: Any, row: Dict[str, Any], tasks: List[Dict[str, Any]]) -> bool:
    from agno.company.execution import _call

    authority = await delivery._authority(app, row["data"]["user"], row["principal"])
    try:
        await authority.arequire("projects", "read")
    except PermissionError:
        return False  # Task results remain available under their separate read permission.
    project_ids = set()
    for task in tasks:
        if task["status"] == "done":
            stored = await _call(delivery._os._company_db, "get_task", task["task_id"])
            if stored is not None:
                project_ids.add(stored["project_id"])
    pending = False
    for project_id in project_ids:
        project = await _call(delivery._os._company_db, "get_project", project_id)
        if project is None:
            continue
        history = project.get("transitions") or []
        marker = (history[-1].get("system_decision") or {}) if history else {}
        assessed = marker.get("operation") in {"project_assessment", "complete_project"} and marker.get(
            "outcome"
        ) == project.get("outcome")
        if project["status"] not in {"done", "cancelled"} and not assessed:
            pending = True
            continue
        key = (
            "project:"
            + project_id
            + ":"
            + hashlib.sha256(json.dumps(project, sort_keys=True, default=str).encode()).hexdigest()
        )
        state = marker.get("decision") if assessed else project["status"]
        reason = marker.get("reason") or (history[-1].get("reason") if history else "") or ""
        if marker.get("next_instruction"):
            reason += "\n" + marker["next_instruction"]
        link = (
            delivery.agent_os_url
            + ("&" if "?" in delivery.agent_os_url else "?")
            + "project="
            + quote(project_id, safe="")
        )
        delivery._intent(row, key, f"Project {project['name']}: {state}\n{reason}\n{link}")
    return pending
