from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Union

from fastapi import HTTPException, UploadFile

from agno.agent.agent import Agent
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.run.team import RunResponseErrorEvent as TeamRunResponseErrorEvent
from agno.team.team import Team
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.utils.log import logger


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


async def team_chat_response_streamer(
    team: Team,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
) -> AsyncGenerator:
    """Run the given team asynchronously and yield its response"""
    try:
        run_response = await team.arun(
            message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_intermediate_steps=True,
        )
        async for run_response_chunk in run_response:
            yield run_response_chunk.to_json()
    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = TeamRunResponseErrorEvent(
            content=str(e),
        )
        yield error_response.to_json()
        return
