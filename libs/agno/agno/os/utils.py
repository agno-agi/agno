from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import HTTPException, UploadFile

from agno.agent.agent import Agent
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.apps.base import BaseApp
from agno.os.apps.memory import MemoryApp
from agno.team.team import Team
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import logger
from agno.workflow.v2.workflow import Workflow


def get_run_input(run_dict: Dict[str, Any], is_workflow_run: bool = False) -> str:
    """Get the run input from the given run dictionary"""

    if is_workflow_run:
        step_member_runs = run_dict.get("step_member_runs", [])
        if step_member_runs:
            for message in step_member_runs[0].get("messages", []):
                if message.get("role") == "user":
                    return message.get("content", "")

    if run_dict.get("messages") is not None:
        for message in run_dict["messages"]:
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
        runs = session.get("runs", [])

        # For teams, identify the first Team run and avoid using the first member's run
        if session.get("session_type") == "team":
            run = runs[0] if not runs[0].get("agent_id") else runs[1]
        elif session.get("session_type") == "workflow":
            run = runs[0]["step_member_runs"][0]
        else:
            run = runs[0]

        if not isinstance(run, dict):
            run = run.to_dict()

        if run and run["messages"]:
            for message in run["messages"]:
                if message["role"] == "user":
                    return message["content"]
    return ""


def process_image(file: UploadFile) -> Image:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Image(content=content)


def process_audio(file: UploadFile) -> Audio:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    format = None
    if file.filename and "." in file.filename:
        format = file.filename.split(".")[-1].lower()
    elif file.content_type:
        format = file.content_type.split("/")[-1]

    return Audio(content=content, format=format)


def process_video(file: UploadFile) -> Video:
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return Video(content=content, format=file.content_type)


def process_document(file: UploadFile) -> Optional[FileMedia]:
    try:
        content = file.file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")

        return FileMedia(content=content)
    except Exception as e:
        logger.error(f"Error processing document {file.filename}: {e}")
        return None


def format_tools(agent_tools: List[Union[Dict[str, Any], Toolkit, Function, Callable]]):
    formatted_tools = []
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


def format_team_tools(team_tools: List[Function]):
    return [tool.to_dict() for tool in team_tools]


def get_agent_by_id(agent_id: str, agents: Optional[List[Agent]] = None) -> Optional[Agent]:
    if agent_id is None or agents is None:
        return None

    for agent in agents:
        if agent.agent_id == agent_id:
            return agent
    return None


def get_team_by_id(team_id: str, teams: Optional[List[Team]] = None) -> Optional[Team]:
    if team_id is None or teams is None:
        return None

    for team in teams:
        if team.team_id == team_id:
            return team
    return None


def get_workflow_by_id(workflow_id: str, workflows: Optional[List[Workflow]] = None) -> Optional[Workflow]:
    if workflow_id is None or workflows is None:
        return None

    for workflow in workflows:
        if workflow.workflow_id == workflow_id:
            return workflow
    return None


def get_component_memory_app(
    component: Union[Agent, Team], os_apps: Optional[List[BaseApp]] = None
) -> Optional[MemoryApp]:
    """Given an Agent or Team and a list of OS apps, return the memory app used by the component"""
    if not os_apps or not component.enable_user_memories:
        return None

    # Find the memory app that has the same database as the component
    for os_app in os_apps:
        if isinstance(os_app, MemoryApp) and os_app.db == component.db:
            return os_app

    return None
