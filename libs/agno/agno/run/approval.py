"""Approval record creation and resolution gating for HITL tool runs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.utils.dttm import now_epoch_s
from agno.utils.log import log_debug, log_warning


def _get_pause_type(tool_execution: Any) -> str:
    """Determine the pause type from a tool execution's HITL flags."""
    if getattr(tool_execution, "requires_user_input", False):
        return "user_input"
    if getattr(tool_execution, "external_execution_required", False):
        return "external_execution"
    return "confirmation"


def _get_first_approval_tool(tools: Optional[List[Any]], requirements: Optional[List[Any]] = None) -> Any:
    """Return the first tool execution that has approval_type set."""
    if tools:
        for tool in tools:
            if getattr(tool, "approval_type", None) is not None:
                return tool
    if requirements:
        for req in requirements:
            te = getattr(req, "tool_execution", None)
            if te and getattr(te, "approval_type", None) is not None:
                return te
    return None


def _has_approval_requirement(tools: Optional[List[Any]], requirements: Optional[List[Any]] = None) -> bool:
    """Check if any paused tool execution has approval_type set.

    Checks both run_response.tools (agent-level) and run_response.requirements
    (team-level, where member tools are propagated via requirements).
    """
    tool = _get_first_approval_tool(tools, requirements)
    return tool is not None and getattr(tool, "approval_type", None) == "required"


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

    # Find the first approval tool to extract pause_type, tool_name, tool_args
    tools = getattr(run_response, "tools", None)
    requirements = getattr(run_response, "requirements", None)
    first_tool = _get_first_approval_tool(tools, requirements)

    pause_type = _get_pause_type(first_tool) if first_tool else "confirmation"
    tool_name = getattr(first_tool, "tool_name", None) if first_tool else None
    tool_args = getattr(first_tool, "tool_args", None) if first_tool else None

    # Build context with tool names for UI display.
    tool_names: List[str] = []
    if hasattr(run_response, "requirements") and run_response.requirements:
        for req in run_response.requirements:
            te = getattr(req, "tool_execution", None)
            if te and getattr(te, "approval_type", None) is not None:
                name = getattr(te, "tool_name", None)
                if name:
                    tool_names.append(name)
    # Fallback: extract from run_response.tools
    if not tool_names and tools:
        for t in tools:
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
        "approval_type": "required",
        "pause_type": pause_type,
        "tool_name": tool_name,
        "tool_args": tool_args,
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
    """Create an approval record when a run pauses for a tool with approval_type set.

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
        log_warning(f"Error creating approval record (sync): {e}")


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
        log_warning(f"Error creating approval record (async): {e}")


def create_audit_approval(
    db: Any,
    tool_execution: Any,
    run_response: Any,
    status: str,  # "approved" or "rejected"
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    team_id: Optional[str] = None,
    team_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Create an audit approval record AFTER a HITL interaction resolves.

    Unlike create_approval_from_pause (which creates a 'pending' record before resolution),
    this creates a completed record (status='approved'/'rejected') for audit logging.
    Only called for tools with approval_type='audit'.
    """
    if db is None:
        return
    try:
        source_type = "agent"
        source_name = agent_name
        if team_id:
            source_type = "team"
            source_name = team_name

        tool_name = getattr(tool_execution, "tool_name", None)
        tool_args = getattr(tool_execution, "tool_args", None)
        pause_type = _get_pause_type(tool_execution)

        context: Dict[str, Any] = {}
        if tool_name:
            context["tool_names"] = [tool_name]
        if source_name:
            context["source_name"] = source_name

        approval_data = {
            "id": str(uuid4()),
            "run_id": getattr(run_response, "run_id", None) or str(uuid4()),
            "session_id": getattr(run_response, "session_id", None) or "",
            "status": status,
            "approval_type": "audit",
            "pause_type": pause_type,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "source_type": source_type,
            "agent_id": agent_id,
            "team_id": team_id,
            "user_id": user_id,
            "source_name": source_name,
            "context": context if context else None,
            "resolved_at": now_epoch_s(),
            "created_at": now_epoch_s(),
            "updated_at": None,
        }
        db.create_approval(approval_data)
        log_debug(f"Audit approval {approval_data['id']} for tool {tool_name}")
    except NotImplementedError:
        pass
    except Exception as e:
        log_warning(f"Error creating audit approval record (sync): {e}")


# ---------------------------------------------------------------------------
# Approval gate: enforce external resolution before continue
# ---------------------------------------------------------------------------


def _apply_approval_to_tools(tools: List[Any], approval_status: str, resolution_data: Optional[Dict[str, Any]]) -> None:
    """Apply approval resolution status to tools that require approval.

    For 'approved': sets confirmed=True, applies resolution_data to user_input/external_execution fields.
    For 'rejected': sets confirmed=False.
    """
    for tool in tools:
        if getattr(tool, "approval_type", None) != "required":
            continue

        if approval_status == "approved":
            # Confirmation tools
            if getattr(tool, "requires_confirmation", False):
                tool.confirmed = True

            # User input tools: apply resolution_data values to user_input_schema
            if getattr(tool, "requires_user_input", False) and resolution_data:
                values = resolution_data.get("values", resolution_data)
                for ufield in tool.user_input_schema or []:
                    if ufield.name in values:
                        ufield.value = values[ufield.name]

            # External execution tools: apply resolution_data result
            if getattr(tool, "external_execution_required", False) and resolution_data:
                if "result" in resolution_data:
                    tool.result = resolution_data["result"]

        elif approval_status == "rejected":
            if getattr(tool, "requires_confirmation", False):
                tool.confirmed = False
            if getattr(tool, "requires_user_input", False):
                tool.confirmed = False
            if getattr(tool, "external_execution_required", False):
                tool.confirmed = False


def _get_approval_for_run(db: Any, run_id: str) -> Optional[Dict[str, Any]]:
    """Look up the most recent 'required' approval for a run_id (sync)."""
    try:
        approvals, _ = db.get_approvals(run_id=run_id, approval_type="required", limit=1)
        return approvals[0] if approvals else None
    except (NotImplementedError, Exception):
        return None


async def _aget_approval_for_run(db: Any, run_id: str) -> Optional[Dict[str, Any]]:
    """Look up the most recent 'required' approval for a run_id (async)."""
    try:
        get_fn = getattr(db, "get_approvals", None)
        if get_fn is None:
            return None
        from inspect import iscoroutinefunction

        if iscoroutinefunction(get_fn):
            approvals, _ = await get_fn(run_id=run_id, approval_type="required", limit=1)
        else:
            approvals, _ = get_fn(run_id=run_id, approval_type="required", limit=1)
        return approvals[0] if approvals else None
    except (NotImplementedError, Exception):
        return None


def check_and_apply_approval_resolution(db: Any, run_id: str, run_response: Any) -> None:
    """Gate: if any tool has approval_type='required', verify the approval is resolved before continuing.

    Raises RuntimeError if the approval is still pending or not found.
    No-op if no tools require approval or if db is None.
    """
    if db is None:
        return

    tools = getattr(run_response, "tools", None)
    if not tools or not any(getattr(t, "approval_type", None) == "required" for t in tools):
        return

    approval = _get_approval_for_run(db, run_id)
    if approval is None:
        raise RuntimeError(
            "No approval record found for this run. Cannot continue a run that requires external approval."
        )

    status = approval.get("status", "pending")
    if status == "pending":
        raise RuntimeError("Approval is still pending. Resolve the approval before continuing this run.")

    _apply_approval_to_tools(tools, status, approval.get("resolution_data"))


async def acheck_and_apply_approval_resolution(db: Any, run_id: str, run_response: Any) -> None:
    """Async variant of check_and_apply_approval_resolution."""
    if db is None:
        return

    tools = getattr(run_response, "tools", None)
    if not tools or not any(getattr(t, "approval_type", None) == "required" for t in tools):
        return

    approval = await _aget_approval_for_run(db, run_id)
    if approval is None:
        raise RuntimeError(
            "No approval record found for this run. Cannot continue a run that requires external approval."
        )

    status = approval.get("status", "pending")
    if status == "pending":
        raise RuntimeError("Approval is still pending. Resolve the approval before continuing this run.")

    _apply_approval_to_tools(tools, status, approval.get("resolution_data"))


async def acreate_audit_approval(
    db: Any,
    tool_execution: Any,
    run_response: Any,
    status: str,  # "approved" or "rejected"
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    team_id: Optional[str] = None,
    team_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """Async variant of create_audit_approval."""
    if db is None:
        return
    try:
        source_type = "agent"
        source_name = agent_name
        if team_id:
            source_type = "team"
            source_name = team_name

        tool_name = getattr(tool_execution, "tool_name", None)
        tool_args = getattr(tool_execution, "tool_args", None)
        pause_type = _get_pause_type(tool_execution)

        context: Dict[str, Any] = {}
        if tool_name:
            context["tool_names"] = [tool_name]
        if source_name:
            context["source_name"] = source_name

        approval_data = {
            "id": str(uuid4()),
            "run_id": getattr(run_response, "run_id", None) or str(uuid4()),
            "session_id": getattr(run_response, "session_id", None) or "",
            "status": status,
            "approval_type": "audit",
            "pause_type": pause_type,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "source_type": source_type,
            "agent_id": agent_id,
            "team_id": team_id,
            "user_id": user_id,
            "source_name": source_name,
            "context": context if context else None,
            "resolved_at": now_epoch_s(),
            "created_at": now_epoch_s(),
            "updated_at": None,
        }
        create_fn = getattr(db, "create_approval", None)
        if create_fn is None:
            return
        from inspect import iscoroutinefunction

        if iscoroutinefunction(create_fn):
            await create_fn(approval_data)
        else:
            create_fn(approval_data)
        log_debug(f"Audit approval {approval_data['id']} for tool {tool_name}")
    except NotImplementedError:
        pass
    except Exception as e:
        log_warning(f"Error creating audit approval record (async): {e}")
