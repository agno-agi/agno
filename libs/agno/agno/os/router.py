import json
from typing import AsyncGenerator, List, Optional, cast
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.params import Form
from fastapi.responses import JSONResponse, StreamingResponse

from agno.agent.agent import Agent
from agno.db.base import SessionType
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.interfaces.playground.schemas import AgentSessionsResponse
from agno.os.operator import get_session_title
from agno.os.schema import (
    AgentResponse,
    AppsResponse,
    ConfigResponse,
    InterfaceResponse,
    ManagerResponse,
    TeamResponse,
    WorkflowResponse,
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
            session=[
                ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix)
                for app in os.apps
                if app.type == "session"
            ],
            knowledge=[
                ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix)
                for app in os.apps
                if app.type == "knowledge"
            ],
            memory=[
                ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix)
                for app in os.apps
                if app.type == "memory"
            ],
            eval=[
                ManagerResponse(type=app.type, name=app.name, version=app.version, route=app.router_prefix)
                for app in os.apps
                if app.type == "eval"
            ],
        )

        app_response.session = app_response.session or None
        app_response.knowledge = app_response.knowledge or None
        app_response.memory = app_response.memory or None
        app_response.eval = app_response.eval or None

        return ConfigResponse(
            os_id=os.os_id,
            name=os.name,
            description=os.description,
            interfaces=[
                InterfaceResponse(type=interface.type, version=interface.version, route=interface.router_prefix)
                for interface in os.interfaces
            ],
            apps=app_response,
        )

    @router.get("/agents", response_model=List[AgentResponse], response_model_exclude_none=True)
    async def get_agents():
        if os.agents is None:
            return []

        return [AgentResponse.from_agent(agent) for agent in os.agents]

    @router.get("/teams", response_model=List[TeamResponse], response_model_exclude_none=True)
    async def get_teams():
        if os.teams is None:
            return []

        return [TeamResponse.from_team(team) for team in os.teams]

    @router.get("/workflows", response_model=List[WorkflowResponse], response_model_exclude_none=True)
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
        stream: bool = Form(False),
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
                elif file.content_type in [
                    "application/pdf",
                    "text/csv",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "text/plain",
                    "application/json",
                ]:
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


    @router.get("/agents/{agent_id}/sessions/{session_id}")
    async def get_agent_session(agent_id: str, session_id: str, user_id: Optional[str] = Query(None, min_length=1)):

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        session_manager = None
        for app in os.apps:
            if app.type == "session":
                session_manager = app
                break
        
        log_debug(f"Session manager found: {session_manager}")
        if session_manager is None:
            return JSONResponse(status_code=404, content="Session management not enabled.")

        # Use the session manager's database to get the session
        try:
            from agno.db.base import SessionType
            # Use get_session instead of read
            agent_session = session_manager.db.get_session(
                session_id=session_id, 
                user_id=user_id,
                session_type=SessionType.AGENT
            )
        except Exception as e:
            return JSONResponse(status_code=500, content=f"Error reading session: {str(e)}")
        
        if agent_session is None:
            return JSONResponse(status_code=404, content="Session not found.")

        # Convert to dict first
        agent_session_dict = agent_session.to_dict()
        
        # Check if memory exists in the dict and process runs
        if agent_session_dict.get("memory") is not None:
            memory = agent_session_dict["memory"]
            runs = memory.get("runs") if isinstance(memory, dict) else None
            
            if runs is not None and len(runs) > 0:
                first_run = runs[0]
                # This is how we know it is a RunResponse or RunPaused
                if "content" in first_run or first_run.get("is_paused", False) or first_run.get("event") == "RunPaused":
                    agent_session_dict["runs"] = []

                    for run in runs:
                        first_user_message = None
                        for msg in run.get("messages", []):
                            if msg.get("role") == "user" and msg.get("from_history", False) is False:
                                first_user_message = msg
                                break
                        # Remove the memory from the response
                        run.pop("memory", None)
                        agent_session_dict["runs"].append(
                            {
                                "message": first_user_message,
                                "response": run,
                            }
                        )
        
        return agent_session_dict
    

    @router.get("/agents/{agent_id}/sessions")
    async def get_all_agent_sessions(
        agent_id: str, 
        user_id: Optional[str] = Query(None, min_length=1),
        limit: Optional[int] = Query(None, ge=1, le=100),
        page: Optional[int] = Query(None, ge=1),
        sort_by: Optional[str] = Query(None),
        sort_order: Optional[str] = Query(None, regex="^(asc|desc)$")
    ):
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            return JSONResponse(status_code=404, content="Agent not found.")

        session_manager = None
        for app in os.apps:
            if app.type == "session":
                session_manager = app
                break
        
        log_debug(f"Session manager found: {session_manager}")
        if session_manager is None:
            return JSONResponse(status_code=404, content="Session management not enabled.")

        try:
            from agno.db.base import SessionType
            # Use get_sessions_raw to get both sessions and total count
            sessions_raw, total_count = session_manager.db.get_sessions_raw(
                session_type=SessionType.AGENT,
                user_id=user_id,
                component_id=agent_id,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
            )
            
            log_debug(f"Found {total_count} total sessions, returning {len(sessions_raw)} sessions")
            
        except Exception as e:
            log_error(f"Error getting sessions: {str(e)}")
            return JSONResponse(status_code=500, content=f"Error retrieving sessions: {str(e)}")

        agent_sessions: List[AgentSessionsResponse] = []
        for session_dict in sessions_raw:
            try:
                # Convert dict to session object or work with dict directly
                session_id = session_dict.get("session_id")
                created_at = session_dict.get("created_at")
                session_data = session_dict.get("session_data", {})
                
                # You might need to adjust this based on your session structure
                title = session_dict.get("title") or f"Session {session_id}"
                
                agent_sessions.append(
                    AgentSessionsResponse(
                        title=title,
                        session_id=session_id,
                        session_name=session_data.get("session_name") if session_data is not None else None,
                        created_at=created_at,
                    )
                )
            except Exception as e:
                log_error(f"Error processing session {session_dict.get('session_id', 'unknown')}: {str(e)}")
                continue
        
        # Return with pagination info
        return {
            "sessions": agent_sessions,
            "total_count": total_count,
            "page": page,
            "limit": limit,
            "returned_count": len(agent_sessions)
        }
    
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
            log_warning(
                f"Continuing run without session_id. This might lead to unexpected behavior if session context is important."
            )

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
