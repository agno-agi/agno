"""Approval record creation for HITL tool runs with requires_approval=True."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.dttm import now_epoch_s
from agno.utils.log import log_debug, log_warning


def _has_approval_requirement(tools: Optional[List[Any]], requirements: Optional[List[Any]] = None) -> bool:
    """Check if any paused tool execution has requires_approval=True.

    Checks both run_response.tools (agent-level) and run_response.requirements
    (team-level, where member tools are propagated via requirements).
    """
    if tools:
        for tool in tools:
            if hasattr(tool, "requires_approval") and tool.requires_approval:
                return True
    if requirements:
        for req in requirements:
            te = getattr(req, "tool_execution", None)
            if te and getattr(te, "requires_approval", False):
                return True
    return False


def _build_approval_dict(
    run_response: Any,
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
    """Build the approval record dict from run response and context."""
    # Determine source type
    source_type = "agent"
    source_name = agent_name
    if team_id:
        source_type = "team"
        source_name = team_name
    elif workflow_id:
        source_type = "workflow"
        source_name = workflow_name

    # Serialize requirements
    requirements_data: Optional[List[Dict[str, Any]]] = None
    if hasattr(run_response, "requirements") and run_response.requirements:
        requirements_data = []
        for req in run_response.requirements:
            if hasattr(req, "to_dict"):
                requirements_data.append(req.to_dict())
            elif isinstance(req, dict):
                requirements_data.append(req)

    # Build context with tool names for UI display.
    # Prefer approval-requiring tools from requirements (covers both agent and team level).
    tool_names: List[str] = []
    if hasattr(run_response, "requirements") and run_response.requirements:
        for req in run_response.requirements:
            te = getattr(req, "tool_execution", None)
            if te and getattr(te, "requires_approval", False):
                name = getattr(te, "tool_name", None)
                if name:
                    tool_names.append(name)
    # Fallback: extract from run_response.tools
    if not tool_names and hasattr(run_response, "tools") and run_response.tools:
        for t in run_response.tools:
            if hasattr(t, "tool_name") and t.tool_name:
                tool_names.append(t.tool_name)

    context: Dict[str, Any] = {}
    if tool_names:
        context["tool_names"] = tool_names
    if source_name:
        context["source_name"] = source_name

    return {
        "id": str(uuid4()),
        "run_id": getattr(run_response, "run_id", None) or str(uuid4()),
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
        "requirements": requirements_data,
        "context": context if context else None,
        "resolved_by": None,
        "resolved_at": None,
        "created_at": now_epoch_s(),
        "updated_at": None,
    }


def create_approval_from_pause(
    db: Any,
    run_response: Any,
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
    """Create an approval record when a run pauses for a tool with requires_approval=True.

    Silently returns if no approval requirement is found or if DB doesn't support approvals.
    """
    if db is None:
        return

    tools = getattr(run_response, "tools", None)
    requirements = getattr(run_response, "requirements", None)
    if not _has_approval_requirement(tools, requirements):
        return

    try:
        approval_data = _build_approval_dict(
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
        db.create_approval(approval_data)
        log_debug(f"Created approval {approval_data['id']} for run {approval_data['run_id']}")
    except NotImplementedError:
        pass
    except Exception as e:
        log_warning(f"Error creating approval record: {e}")


async def acreate_approval_from_pause(
    db: Any,
    run_response: Any,
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
    if db is None:
        return

    tools = getattr(run_response, "tools", None)
    requirements = getattr(run_response, "requirements", None)
    if not _has_approval_requirement(tools, requirements):
        return

    try:
        approval_data = _build_approval_dict(
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
        # Try async first, fall back to sync
        create_fn = getattr(db, "create_approval", None)
        if create_fn is None:
            return
        from inspect import iscoroutinefunction

        if iscoroutinefunction(create_fn):
            await create_fn(approval_data)
        else:
            create_fn(approval_data)
        log_debug(f"Created approval {approval_data['id']} for run {approval_data['run_id']}")
    except NotImplementedError:
        pass
    except Exception as e:
        log_warning(f"Error creating approval record: {e}")
