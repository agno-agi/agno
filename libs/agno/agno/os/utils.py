from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import HTTPException, UploadFile

from agno.agent.agent import Agent
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.team.team import Team
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import logger
from agno.workflow.workflow import Workflow


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


def get_agent_by_id(agent_id: str, agents: Optional[List[Agent]] = None) -> Optional[Agent]:
    if agent_id is None or agents is None:
        return None

    for agent in agents:
        if agent.agent_id == agent_id:
            return agent
    return None


def get_workflow_by_id(workflow_id: str, workflows: Optional[List[Workflow]] = None) -> Optional[Workflow]:
    if workflows is None or workflow_id is None:
        return None

    for workflow in workflows:
        if workflow.workflow_id == workflow_id:
            return workflow
    return None


def get_team_by_id(team_id: str, teams: Optional[List[Team]] = None) -> Optional[Team]:
    if teams is None or team_id is None:
        return None

    for team in teams:
        if team.team_id == team_id:
            return team
    return None
