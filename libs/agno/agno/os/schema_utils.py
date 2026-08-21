"""Helpers for building AgentOS response schemas from session and run dicts.

These run on the client side as well (AgentOSClient parses server responses
with the schema modules), so this module must stay importable without the
`os` extra: no fastapi imports, directly or transitively.
"""

import json
from datetime import date, datetime, time, timezone
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.tools import Function, Toolkit
from agno.utils.log import logger


def to_utc_datetime(value: Optional[Union[str, int, float, date, datetime]]) -> Optional[datetime]:
    """Convert a timestamp, ISO 8601 string, date, or datetime to a UTC datetime."""
    if value is None:
        return None

    if isinstance(value, datetime):
        # If already a datetime, make sure the timezone is UTC
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    # datetime is a subclass of date, so this must come after the datetime check
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)

    if isinstance(value, str):
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    return datetime.fromtimestamp(value, tz=timezone.utc)


def get_run_input(run_dict: Dict[str, Any], is_workflow_run: bool = False) -> str:
    """Get the run input from the given run dictionary

    Uses the RunInput/TeamRunInput object which stores the original user input.
    """

    # For agent or team runs, use the stored input_content
    if not is_workflow_run and run_dict.get("input") is not None:
        input_data = run_dict.get("input")
        if isinstance(input_data, dict) and input_data.get("input_content") is not None:
            return stringify_input_content(input_data["input_content"])

    if is_workflow_run:
        # Check the input field directly
        input_value = run_dict.get("input")
        if input_value is not None:
            return stringify_input_content(input_value)

        # Check the step executor runs for fallback
        step_executor_runs = run_dict.get("step_executor_runs", [])
        if step_executor_runs:
            for message in reversed(step_executor_runs[0].get("messages", [])):
                if message.get("role") == "user":
                    return message.get("content", "")

    # Final fallback: scan messages
    if run_dict.get("messages") is not None:
        for message in reversed(run_dict["messages"]):
            if message.get("role") == "user":
                return message.get("content", "")

    return ""


def get_session_name(session: Dict[str, Any]) -> str:
    """Get the session name from the given session dictionary"""

    # If session_data.session_name is set, return that
    session_data = session.get("session_data")
    if session_data is not None and session_data.get("session_name") is not None:
        return session_data["session_name"]

    runs = session.get("runs", []) or []
    session_type = session.get("session_type")

    # Handle workflows separately
    if session_type == "workflow":
        if not runs:
            return ""
        workflow_run = runs[0]
        workflow_input = workflow_run.get("input")
        if isinstance(workflow_input, str):
            return workflow_input
        elif isinstance(workflow_input, dict):
            try:
                return json.dumps(workflow_input)
            except (TypeError, ValueError):
                pass
        workflow_name = session.get("workflow_data", {}).get("name")
        return f"New {workflow_name} Session" if workflow_name else ""

    # For team, filter to team runs (runs without agent_id); for agents, use all runs
    if session_type == "team":
        runs_to_check = [r for r in runs if not r.get("agent_id")]
    else:
        runs_to_check = runs

    # Find the first user message across runs
    for r in runs_to_check:
        if r is None:
            continue
        run_dict = r if isinstance(r, dict) else r.to_dict()

        for message in run_dict.get("messages") or []:
            if message.get("role") == "user" and message.get("content"):
                return message["content"]

        run_input = r.get("input")
        if run_input is not None:
            return stringify_input_content(run_input)

    return ""


def extract_input_media(run_dict: Dict[str, Any]) -> Dict[str, Any]:
    input_media: Dict[str, List[Any]] = {
        "images": [],
        "videos": [],
        "audios": [],
        "files": [],
    }

    input_data = run_dict.get("input", {})
    if isinstance(input_data, dict):
        input_media["images"].extend(input_data.get("images", []))
        input_media["videos"].extend(input_data.get("videos", []))
        input_media["audios"].extend(input_data.get("audios", []))
        input_media["files"].extend(input_data.get("files", []))

    return input_media


def stringify_input_content(input_content: Union[str, Dict[str, Any], List[Any], BaseModel]) -> str:
    """Convert any given input_content into its string representation.

    This handles both serialized (dict) and live (object) input_content formats.
    """
    if isinstance(input_content, str):
        return input_content
    elif isinstance(input_content, Message):
        return json.dumps(input_content.to_dict())
    elif isinstance(input_content, dict):
        return json.dumps(input_content, indent=2, default=str)
    elif isinstance(input_content, list):
        if input_content:
            # Handle live Message objects
            if isinstance(input_content[0], Message):
                return json.dumps([m.to_dict() for m in input_content])
            # Handle serialized Message dicts
            elif isinstance(input_content[0], dict) and input_content[0].get("role") == "user":
                return input_content[0].get("content", str(input_content))
        return str(input_content)
    else:
        return str(input_content)


def format_duration_ms(duration_ms: Optional[int]) -> str:
    """Format a duration in milliseconds to a human-readable string.

    Args:
        duration_ms: Duration in milliseconds

    Returns:
        Formatted string like "150ms" or "1.50s"
    """
    if duration_ms is None or duration_ms < 1000:
        return f"{duration_ms or 0}ms"
    return f"{duration_ms / 1000:.2f}s"


def format_team_tools(team_tools: List[Union[Function, dict]]):
    formatted_tools: List[Dict] = []
    if team_tools is not None:
        for tool in team_tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            elif isinstance(tool, Function):
                formatted_tools.append(tool.to_dict())
    return formatted_tools


def format_tools(agent_tools: List[Union[Dict[str, Any], Toolkit, Function, Callable]]):
    formatted_tools: List[Dict] = []
    if agent_tools is not None:
        for tool in agent_tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            elif isinstance(tool, Toolkit):
                for _, f in tool.functions.items():
                    formatted_tools.append(f.to_dict())
            elif isinstance(tool, Function):
                formatted_tools.append(tool.to_dict())
            elif callable(tool):
                func = Function.from_callable(tool)
                formatted_tools.append(func.to_dict())
            else:
                logger.warning(f"Unknown tool type: {type(tool)}")
    return formatted_tools
