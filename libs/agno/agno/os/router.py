import json
from typing import AsyncGenerator, List, Optional, cast
from uuid import uuid4
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.params import Form
from fastapi.responses import StreamingResponse

from agno.agent.agent import Agent
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.schema import (
    AppsResponse,
    ConfigResponse,
    AgentResponse,
    InterfaceResponse,
    ManagerResponse,
    TeamResponse,
    WorkflowResponse
)
from agno.os.utils import get_agent_by_id, process_audio, process_image, process_video
from agno.run.response import RunResponse, RunResponseErrorEvent
from agno.utils.log import log_debug, log_error, log_warning


async def agent_response_streamer(
    agent: Agent,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
) -> AsyncGenerator:
    try:
        run_response = await agent.arun(
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

        traceback.print_exc(limit=3)
        error_response = RunResponseErrorEvent(
            content=str(e),
        )
        yield error_response.to_json()

async def agent_continue_response_streamer(
    agent: Agent,
    run_id: Optional[str] = None,
    updated_tools: Optional[List] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> AsyncGenerator:
    try:
        continue_response = await agent.acontinue_run(
            run_id=run_id,
            updated_tools=updated_tools,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_intermediate_steps=True,
        )
        async for run_response_chunk in continue_response:
            yield run_response_chunk.to_json()
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunResponseErrorEvent(
            content=str(e),
        )
        yield error_response.to_json()
        return



def get_base_router(
    os: "AgentOS",
) -> APIRouter:
    router = APIRouter(tags=["Built-In"])

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.get("/config", response_model=ConfigResponse, response_model_exclude_none=True)
    async def config() -> ConfigResponse:
        app_response = AppsResponse(
                session=[ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix) for app in os.apps if app.type == "session"],
                knowledge=[ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix) for app in os.apps if app.type == "knowledge"],
                memory=[ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix) for app in os.apps if app.type == "memory"],
                eval=[ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix) for app in os.apps if app.type == "eval"],
            )

        app_response.session = app_response.session or None
        app_response.knowledge = app_response.knowledge or None
        app_response.memory = app_response.memory or None
        app_response.eval = app_response.eval or None

        return ConfigResponse(
            os_id=os.os_id,
            name=os.name,
            description=os.description,
            interfaces=[InterfaceResponse(type=interface.type, version=interface.version, route=interface.router_prefix) for interface in os.interfaces],
            apps=app_response,
        )

    @router.get("/agents",
                response_model=List[AgentResponse],
                response_model_exclude_none=True)
    async def get_agents():
        if os.agents is None:
            return []

        return [
            AgentResponse.from_agent(agent)
            for agent in os.agents
        ]

    @router.get("/teams",
                response_model=List[TeamResponse],
                response_model_exclude_none=True)
    async def get_teams():
        if os.teams is None:
            return []

        return [
            TeamResponse.from_team(team)
            for team in os.teams
        ]

    @router.get("/workflows",
                response_model=List[WorkflowResponse],
                response_model_exclude_none=True)
    async def get_workflows():
        if os.workflows is None:
            return []

        return [
            WorkflowResponse(
                workflow_id=str(workflow.workflow_id),
                name=workflow.name,
                description=workflow.description,
            )
            for workflow in os.workflows
        ]


    @router.post("/agents/{agent_id}/runs")
    async def create_agent_run(
        agent_id: str,
        message: str = Form(...),
        stream: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if session_id is None or session_id == "":
            log_debug(f"Creating new session")
            session_id = str(uuid4())

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        input_files: List[FileMedia] = []

        if files:
            for file in files:
                if file.content_type in ["image/png", "image/jpeg", "image/jpg", "image/webp"]:
                    try:
                        base64_image = process_image(file)
                        base64_images.append(base64_image)
                    except Exception as e:
                        log_error(f"Error processing image {file.filename}: {e}")
                        continue
                elif file.content_type in ["audio/wav", "audio/mp3", "audio/mpeg"]:
                    try:
                        base64_audio = process_audio(file)
                        base64_audios.append(base64_audio)
                    except Exception as e:
                        log_error(f"Error processing audio {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "video/x-flv",
                    "video/quicktime",
                    "video/mpeg",
                    "video/mpegs",
                    "video/mpgs",
                    "video/mpg",
                    "video/mpg",
                    "video/mp4",
                    "video/webm",
                    "video/wmv",
                    "video/3gpp",
                ]:
                    try:
                        base64_video = process_video(file)
                        base64_videos.append(base64_video)
                    except Exception as e:
                        log_error(f"Error processing video {file.filename}: {e}")
                        continue
                elif file.content_type in ["application/pdf", "text/csv", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain", "application/json"]:
                    # Process document files
                    try:
                        file_content = await file.read()
                        input_files.append(FileMedia(content=file_content))
                    except Exception as e:
                        log_error(f"Error processing file {file.filename}: {e}")
                        continue
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        if stream and agent.is_streamable:
            return StreamingResponse(
                agent_response_streamer(
                    agent,
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=input_files if input_files else None,
                ),
                media_type="text/event-stream",
            )
        else:
            run_response = cast(
                RunResponse,
                await agent.arun(
                    message=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=input_files if input_files else None,
                    stream=False,
                ),
            )
            return run_response.to_dict()


    @router.post("/agents/{agent_id}/runs/{run_id}/continue")
    async def continue_agent_run(
        agent_id: str,
        run_id: str,
        tools: str = Form(...),  # JSON string of tools
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        stream: bool = Form(True),
    ):
        # Parse the JSON string manually
        try:
            tools_data = json.loads(tools) if tools else None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON in tools field")

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if session_id is None or session_id == "":
            log_warning(f"Continuing run without session_id. This might lead to unexpected behavior if session context is important.")

        # Convert tools dict to ToolExecution objects if provided
        updated_tools = None
        if tools_data:
            try:
                from agno.models.response import ToolExecution

                updated_tools = [ToolExecution.from_dict(tool) for tool in tools_data]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid structure or content for tools: {str(e)}")

        if stream and agent.is_streamable:
            return StreamingResponse(
                agent_continue_response_streamer(
                    agent,
                    run_id=run_id,  # run_id from path
                    updated_tools=updated_tools,
                    session_id=session_id,
                    user_id=user_id,
                ),
                media_type="text/event-stream",
            )
        else:
            run_response_obj = cast(
                RunResponse,
                await agent.acontinue_run(
                    run_id=run_id,  # run_id from path
                    updated_tools=updated_tools,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                ),
            )
            return run_response_obj.to_dict()


    return router


