import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Optional, cast
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, StreamingResponse

from agno.agent.agent import Agent
from agno.exceptions import InputCheckError, OutputCheckError
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.auth import get_authentication_dependency, require_resource_access
from agno.os.routers.agents.schema import AgentResponse
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    format_sse_event,
    get_agent_by_id,
    get_request_kwargs,
    process_audio,
    process_document,
    process_image,
    process_video,
)
from agno.run.agent import RunErrorEvent, RunOutput
from agno.utils.log import log_debug, log_error, log_warning

if TYPE_CHECKING:
    from agno.os.app import AgentOS


async def agent_response_streamer(
    agent: Agent,
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        # Pass background_tasks if provided
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        run_response = agent.arun(
            input=message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_events=True,
            **kwargs,
        )
        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)
    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response)


async def agent_continue_response_streamer(
    agent: Agent,
    run_id: Optional[str] = None,
    updated_tools: Optional[List] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    background_tasks: Optional[BackgroundTasks] = None,
) -> AsyncGenerator:
    try:
        continue_response = agent.acontinue_run(
            run_id=run_id,
            updated_tools=updated_tools,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_events=True,
            background_tasks=background_tasks,
        )
        async for run_response_chunk in continue_response:
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


def get_agent_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """
    Create the agent router with comprehensive OpenAPI documentation.
    """
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )

    @router.post(
        "/agents/{agent_id}/runs",
        tags=["Agents"],
        operation_id="create_agent_run",
        response_model_exclude_none=True,
        summary="Create Agent Run",
        description=(
            "Execute an agent with a message and optional media files. Supports both streaming and non-streaming responses.\n\n"
            "**Features:**\n"
            "- Text message input with optional session management\n"
            "- Multi-media support: images (PNG, JPEG, WebP), audio (WAV, MP3), video (MP4, WebM, etc.)\n"
            "- Document processing: PDF, CSV, DOCX, TXT, JSON\n"
            "- Real-time streaming responses with Server-Sent Events (SSE)\n"
            "- User and session context preservation\n\n"
            "**Streaming Response:**\n"
            "When `stream=true`, returns SSE events with `event` and `data` fields."
        ),
        responses={
            200: {
                "description": "Agent run executed successfully",
                "content": {
                    "text/event-stream": {
                        "examples": {
                            "event_stream": {
                                "summary": "Example event stream response",
                                "value": 'event: RunStarted\ndata: {"content": "Hello!", "run_id": "123..."}\n\n',
                            }
                        }
                    },
                },
            },
            400: {"description": "Invalid request or unsupported file type", "model": BadRequestResponse},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def create_agent_run(
        agent_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        message: str = Form(...),
        stream: bool = Form(False),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        kwargs = await get_request_kwargs(request, create_agent_run)

        if hasattr(request.state, "user_id"):
            if user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = request.state.user_id
        if hasattr(request.state, "session_id"):
            if session_id:
                log_warning("Session ID parameter passed in both request state and kwargs, using request state")
            session_id = request.state.session_id
        if hasattr(request.state, "session_state"):
            session_state = request.state.session_state
            if "session_state" in kwargs:
                log_warning("Session state parameter passed in both request state and kwargs, using request state")
            kwargs["session_state"] = session_state
        if hasattr(request.state, "dependencies"):
            dependencies = request.state.dependencies
            if "dependencies" in kwargs:
                log_warning("Dependencies parameter passed in both request state and kwargs, using request state")
            kwargs["dependencies"] = dependencies
        if hasattr(request.state, "metadata"):
            metadata = request.state.metadata
            if "metadata" in kwargs:
                log_warning("Metadata parameter passed in both request state and kwargs, using request state")
            kwargs["metadata"] = metadata

        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if session_id is None or session_id == "":
            log_debug("Creating new session")
            session_id = str(uuid4())

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        input_files: List[FileMedia] = []

        if files:
            for file in files:
                if file.content_type in [
                    "image/png",
                    "image/jpeg",
                    "image/jpg",
                    "image/gif",
                    "image/webp",
                    "image/bmp",
                    "image/tiff",
                    "image/tif",
                    "image/avif",
                ]:
                    try:
                        base64_image = process_image(file)
                        base64_images.append(base64_image)
                    except Exception as e:
                        log_error(f"Error processing image {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "audio/wav",
                    "audio/wave",
                    "audio/mp3",
                    "audio/mpeg",
                    "audio/ogg",
                    "audio/mp4",
                    "audio/m4a",
                    "audio/aac",
                    "audio/flac",
                ]:
                    try:
                        audio = process_audio(file)
                        base64_audios.append(audio)
                    except Exception as e:
                        log_error(f"Error processing audio {file.filename} with content type {file.content_type}: {e}")
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
                    "application/json",
                    "application/x-javascript",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "text/javascript",
                    "application/x-python",
                    "text/x-python",
                    "text/plain",
                    "text/html",
                    "text/css",
                    "text/md",
                    "text/csv",
                    "text/xml",
                    "text/rtf",
                ]:
                    # Process document files
                    try:
                        input_file = process_document(file)
                        if input_file is not None:
                            input_files.append(input_file)
                    except Exception as e:
                        log_error(f"Error processing file {file.filename}: {e}")
                        continue
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        if stream:
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
                    background_tasks=background_tasks,
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        else:
            try:
                run_response = cast(
                    RunOutput,
                    await agent.arun(
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        images=base64_images if base64_images else None,
                        audio=base64_audios if base64_audios else None,
                        videos=base64_videos if base64_videos else None,
                        files=input_files if input_files else None,
                        stream=False,
                        background_tasks=background_tasks,
                        **kwargs,
                    ),
                )
                return run_response.to_dict()

            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/agents/{agent_id}/runs/{run_id}/cancel",
        tags=["Agents"],
        operation_id="cancel_agent_run",
        response_model_exclude_none=True,
        summary="Cancel Agent Run",
        description=(
            "Cancel a currently executing agent run. This will attempt to stop the agent's execution gracefully.\n\n"
            "**Note:** Cancellation may not be immediate for all operations."
        ),
        responses={
            200: {},
            404: {"description": "Agent not found", "model": NotFoundResponse},
            500: {"description": "Failed to cancel run", "model": InternalServerErrorResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def cancel_agent_run(
        agent_id: str,
        run_id: str,
    ):
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        if not agent.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    @router.post(
        "/agents/{agent_id}/runs/{run_id}/continue",
        tags=["Agents"],
        operation_id="continue_agent_run",
        response_model_exclude_none=True,
        summary="Continue Agent Run",
        description=(
            "Continue a paused or incomplete agent run with updated tool results.\n\n"
            "**Use Cases:**\n"
            "- Resume execution after tool approval/rejection\n"
            "- Provide manual tool execution results\n\n"
            "**Tools Parameter:**\n"
            "JSON string containing array of tool execution objects with results."
        ),
        responses={
            200: {
                "description": "Agent run continued successfully",
                "content": {
                    "text/event-stream": {
                        "example": 'event: RunContent\ndata: {"created_at": 1757348314, "run_id": "123..."}\n\n'
                    },
                },
            },
            400: {"description": "Invalid JSON in tools field or invalid tool structure", "model": BadRequestResponse},
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
    )
    async def continue_agent_run(
        agent_id: str,
        run_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        tools: str = Form(...),  # JSON string of tools
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        stream: bool = Form(True),
    ):
        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id
        if hasattr(request.state, "session_id"):
            session_id = request.state.session_id

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
                "Continuing run without session_id. This might lead to unexpected behavior if session context is important."
            )

        # Convert tools dict to ToolExecution objects if provided
        updated_tools = None
        if tools_data:
            try:
                from agno.models.response import ToolExecution

                updated_tools = [ToolExecution.from_dict(tool) for tool in tools_data]
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid structure or content for tools: {str(e)}")

        if stream:
            return StreamingResponse(
                agent_continue_response_streamer(
                    agent,
                    run_id=run_id,  # run_id from path
                    updated_tools=updated_tools,
                    session_id=session_id,
                    user_id=user_id,
                    background_tasks=background_tasks,
                ),
                media_type="text/event-stream",
            )
        else:
            try:
                run_response_obj = cast(
                    RunOutput,
                    await agent.acontinue_run(
                        run_id=run_id,  # run_id from path
                        updated_tools=updated_tools,
                        session_id=session_id,
                        user_id=user_id,
                        stream=False,
                        background_tasks=background_tasks,
                    ),
                )
                return run_response_obj.to_dict()

            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))

    @router.get(
        "/agents",
        response_model=List[AgentResponse],
        response_model_exclude_none=True,
        tags=["Agents"],
        operation_id="get_agents",
        summary="List All Agents",
        description=(
            "Retrieve a comprehensive list of all agents configured in this OS instance.\n\n"
            "**Returns:**\n"
            "- Agent metadata (ID, name, description)\n"
            "- Model configuration and capabilities\n"
            "- Available tools and their configurations\n"
            "- Session, knowledge, memory, and reasoning settings\n"
            "- Only meaningful (non-default) configurations are included"
        ),
        responses={
            200: {
                "description": "List of agents retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "main-agent",
                                "name": "Main Agent",
                                "db_id": "c6bf0644-feb8-4930-a305-380dae5ad6aa",
                                "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                "tools": None,
                                "sessions": {"session_table": "agno_sessions"},
                                "knowledge": {"knowledge_table": "main_knowledge"},
                                "system_message": {"markdown": True, "add_datetime_to_context": True},
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_agents(request: Request) -> List[AgentResponse]:
        """Return the list of all Agents present in the contextual OS"""
        if os.agents is None:
            return []

        # Filter agents based on user's scopes (only if authorization is enabled)
        if getattr(request.state, "authorization_enabled", False):
            from agno.os.auth import filter_resources_by_access, get_accessible_resources

            # Check if user has any agent scopes at all
            accessible_ids = get_accessible_resources(request, "agents")
            if not accessible_ids:
                raise HTTPException(status_code=403, detail="Insufficient permissions")

            # Limit results based on the user's access/scopes
            accessible_agents = filter_resources_by_access(request, os.agents, "agents")
        else:
            accessible_agents = os.agents

        agents = []
        for agent in accessible_agents:
            agent_response = await AgentResponse.from_agent(agent=agent)
            agents.append(agent_response)

        return agents

    @router.get(
        "/agents/{agent_id}",
        response_model=AgentResponse,
        response_model_exclude_none=True,
        tags=["Agents"],
        operation_id="get_agent",
        summary="Get Agent Details",
        description=(
            "Retrieve detailed configuration and capabilities of a specific agent.\n\n"
            "**Returns comprehensive agent information including:**\n"
            "- Model configuration and provider details\n"
            "- Complete tool inventory and configurations\n"
            "- Session management settings\n"
            "- Knowledge base and memory configurations\n"
            "- Reasoning capabilities and settings\n"
            "- System prompts and response formatting options"
        ),
        responses={
            200: {
                "description": "Agent details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "main-agent",
                            "name": "Main Agent",
                            "db_id": "9e064c70-6821-4840-a333-ce6230908a70",
                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                            "tools": None,
                            "sessions": {"session_table": "agno_sessions"},
                            "knowledge": {"knowledge_table": "main_knowledge"},
                            "system_message": {"markdown": True, "add_datetime_to_context": True},
                        }
                    }
                },
            },
            404: {"description": "Agent not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("agents", "read", "agent_id"))],
    )
    async def get_agent(agent_id: str, request: Request) -> AgentResponse:
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        return await AgentResponse.from_agent(agent)

    return router
