from typing import Any, Callable, Dict, List, Union

from pydantic import BaseModel

from agno.models.message import Message
from agno.tools import Function, Toolkit
from agno.utils.log import logger


def extract_input_media(run_dict: Dict[str, Any]) -> Dict[str, Any]:
    input_media: Dict[str, List[Any]] = {
        "images": [],
        "videos": [],
        "audios": [],
        "files": [],
    }

    input = run_dict.get("input", {})
    input_media["images"].extend(input.get("images", []))
    input_media["videos"].extend(input.get("videos", []))
    input_media["audios"].extend(input.get("audios", []))
    input_media["files"].extend(input.get("files", []))

    return input_media


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
        if run_dict.get("input") is not None:
            input_value = run_dict.get("input")
            return str(input_value)

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

    # Otherwise use the original user message
    else:
        runs = session.get("runs", []) or []

        # For teams, identify the first Team run and avoid using the first member's run
        if session.get("session_type") == "team":
            run = None
            for r in runs:
                # If agent_id is not present, it's a team run
                if not r.get("agent_id"):
                    run = r
                    break

            # Fallback to first run if no team run found
            if run is None and runs:
                run = runs[0]

        elif session.get("session_type") == "workflow":
            try:
                workflow_run = runs[0]
                workflow_input = workflow_run.get("input")
                if isinstance(workflow_input, str):
                    return workflow_input
                elif isinstance(workflow_input, dict):
                    try:
                        import json

                        return json.dumps(workflow_input)
                    except (TypeError, ValueError):
                        pass

                workflow_name = session.get("workflow_data", {}).get("name")
                return f"New {workflow_name} Session" if workflow_name else ""
            except (KeyError, IndexError, TypeError):
                return ""

        # For agents, use the first run
        else:
            run = runs[0] if runs else None

        if run is None:
            return ""

        if not isinstance(run, dict):
            run = run.to_dict()

        if run and run.get("messages"):
            for message in run["messages"]:
                if message["role"] == "user":
                    return message["content"]
    return ""


def stringify_input_content(input_content: Union[str, Dict[str, Any], List[Any], BaseModel]) -> str:
    """Convert any given input_content into its string representation.

    This handles both serialized (dict) and live (object) input_content formats.
    """
    import json

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
