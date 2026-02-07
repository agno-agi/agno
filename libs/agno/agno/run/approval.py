"""Helper to create approval records when a run pauses with requires_approval tools."""

import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.log import log_debug, log_error


def _has_approval_requirement(tools: Optional[List[Any]]) -> bool:
    """Check if any tool in the list has requires_approval=True."""
    if not tools:
        return False
    for tool in tools:
        if hasattr(tool, "requires_approval") and tool.requires_approval:
            return True
        if isinstance(tool, dict) and tool.get("requires_approval"):
            return True
    return False


def _build_approval_dict(
    run_response: Any,
    *,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    team_id: Optional[str] = None,
    team_name: Optional[str] = None,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    user_id: Optional[str] = None,
    schedule_id: Optional[str] = None,
    schedule_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the approval dict from a paused run response."""
    now = int(time.time())

    # Determine source_type and source_name
    if team_id:
        source_type = "team"
        source_name = team_name
    elif workflow_id:
        source_type = "workflow"
        source_name = workflow_name
    else:
        source_type = "agent"
        source_name = agent_name

    # Serialize requirements
    requirements_list: List[Dict[str, Any]] = []
    if run_response.requirements:
        for req in run_response.requirements:
            if hasattr(req, "to_dict"):
                requirements_list.append(req.to_dict())
            elif isinstance(req, dict):
                requirements_list.append(req)

    # Build context for UI display
    tool_names: List[str] = []
    if run_response.tools:
        for tool in run_response.tools:
            name = getattr(tool, "function_name", None) or getattr(tool, "name", None)
            if isinstance(tool, dict):
                name = tool.get("function_name") or tool.get("name")
            if name:
                tool_names.append(name)

    context: Dict[str, Any] = {}
    if tool_names:
        context["tool_names"] = tool_names
    if source_name:
        context["source_name"] = source_name

    return {
        "id": str(uuid4()),
        "run_id": getattr(run_response, "run_id", None) or "",
        "session_id": getattr(run_response, "session_id", None) or "",
        "status": "pending",
        "source_type": source_type,
        "agent_id": agent_id,
        "team_id": team_id,
        "workflow_id": workflow_id,
        "user_id": user_id,
        "schedule_id": schedule_id,
        "schedule_run_id": schedule_run_id,
        "source_name": source_name,
        "requirements": requirements_list or None,
        "context": context or None,
        "resolved_by": None,
        "resolved_at": None,
        "created_at": now,
        "updated_at": None,
    }


def create_approval_from_pause(
    db: Any,
    run_response: Any,
    *,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    team_id: Optional[str] = None,
    team_name: Optional[str] = None,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    user_id: Optional[str] = None,
    schedule_id: Optional[str] = None,
    schedule_run_id: Optional[str] = None,
) -> None:
    """Create an approval record when a run pauses -- only if any tool has requires_approval=True.

    Silently returns if:
    - No tools have requires_approval=True
    - The DB does not support approvals (NotImplementedError)
    - The DB has no create_approval method
    """
    if not _has_approval_requirement(run_response.tools):
        return

    approval_dict = _build_approval_dict(
        run_response,
        agent_id=agent_id,
        agent_name=agent_name,
        team_id=team_id,
        team_name=team_name,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        user_id=user_id,
        schedule_id=schedule_id,
        schedule_run_id=schedule_run_id,
    )

    fn = getattr(db, "create_approval", None)
    if fn is None:
        return

    try:
        fn(approval_dict)
        log_debug(f"Created approval {approval_dict['id']} for run {approval_dict['run_id']}")
    except NotImplementedError:
        pass
    except Exception as exc:
        log_error(f"Failed to create approval record: {exc}")


async def acreate_approval_from_pause(
    db: Any,
    run_response: Any,
    *,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    team_id: Optional[str] = None,
    team_name: Optional[str] = None,
    workflow_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
    user_id: Optional[str] = None,
    schedule_id: Optional[str] = None,
    schedule_run_id: Optional[str] = None,
) -> None:
    """Async variant of create_approval_from_pause."""
    import asyncio

    if not _has_approval_requirement(run_response.tools):
        return

    approval_dict = _build_approval_dict(
        run_response,
        agent_id=agent_id,
        agent_name=agent_name,
        team_id=team_id,
        team_name=team_name,
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        user_id=user_id,
        schedule_id=schedule_id,
        schedule_run_id=schedule_run_id,
    )

    fn = getattr(db, "create_approval", None)
    if fn is None:
        return

    try:
        if asyncio.iscoroutinefunction(fn):
            await fn(approval_dict)
        else:
            fn(approval_dict)
        log_debug(f"Created approval {approval_dict['id']} for run {approval_dict['run_id']}")
    except NotImplementedError:
        pass
    except Exception as exc:
        log_error(f"Failed to create approval record: {exc}")
