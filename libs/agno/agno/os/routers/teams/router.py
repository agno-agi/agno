from typing import TYPE_CHECKING, Any, AsyncGenerator, List, Optional, Union
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, StreamingResponse

from agno.db.base import BaseDb
from agno.exceptions import InputCheckError, OutputCheckError
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency, require_resource_access
from agno.os.routers.teams.schema import TeamResponse
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
    get_request_kwargs,
    get_team_by_id,
    process_audio,
    process_document,
    process_image,
    process_video,
)
from agno.registry import Registry
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_warning, logger

if TYPE_CHECKING:
    from agno.os.app import AgentOS


async def team_response_streamer(
    team: Union[Team, RemoteTeam],
    message: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    images: Optional[List[Image]] = None,
    audio: Optional[List[Audio]] = None,
    videos: Optional[List[Video]] = None,
    files: Optional[List[FileMedia]] = None,
    background_tasks: Optional[BackgroundTasks] = None,
    auth_token: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    """Run the given team asynchronously and yield its response"""
    try:
        # Pass background_tasks if provided
        if background_tasks is not None:
            kwargs["background_tasks"] = background_tasks

        if "stream_events" in kwargs:
            stream_events = kwargs.pop("stream_events")
        else:
            stream_events = True

        # Pass auth_token for remote teams
        if auth_token and isinstance(team, RemoteTeam):
            kwargs["auth_token"] = auth_token

        run_response = team.arun(
            input=message,
            session_id=session_id,
            user_id=user_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=True,
            stream_events=stream_events,
            **kwargs,
        )
        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk)  # type: ignore
    except (InputCheckError, OutputCheckError) as e:
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type,
            error_id=e.error_id,
            additional_data=e.additional_data,
        )
        yield format_sse_event(error_response)

    except BaseException as e:
        import traceback

        traceback.print_exc()
        error_response = TeamRunErrorEvent(
            content=str(e),
            error_type=e.type if hasattr(e, "type") else None,
            error_id=e.error_id if hasattr(e, "error_id") else None,
        )
        yield format_sse_event(error_response)
        return


def get_team_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
    registry: Optional[Registry] = None,
) -> APIRouter:
    """Create the team router with comprehensive OpenAPI documentation."""
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
        "/teams/{team_id}/runs",
        tags=["Teams"],
        operation_id="create_team_run",
        response_model_exclude_none=True,
        summary="Create Team Run",
        description=(
            "Execute a team collaboration with multiple agents working together on a task.\n\n"
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
                "description": "Team run executed successfully",
                "content": {
                    "text/event-stream": {
                        "example": 'event: RunStarted\ndata: {"content": "Hello!", "run_id": "123..."}\n\n'
                    },
                },
            },
            400: {"description": "Invalid request or unsupported file type", "model": BadRequestResponse},
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def create_team_run(
        team_id: str,
        request: Request,
        background_tasks: BackgroundTasks,
        message: str = Form(...),
        stream: bool = Form(True),
        monitor: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
        version: Optional[int] = Form(None),
        background: bool = Form(False),
    ):
        kwargs = await get_request_kwargs(request, create_team_run)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            if user_id and user_id != request.state.user_id:
                log_warning("User ID parameter passed in both request state and kwargs, using request state")
            user_id = request.state.user_id
        if hasattr(request.state, "session_id") and request.state.session_id is not None:
            if session_id and session_id != request.state.session_id:
                log_warning("Session ID parameter passed in both request state and kwargs, using request state")
            session_id = request.state.session_id
        if hasattr(request.state, "session_state") and request.state.session_state is not None:
            session_state = request.state.session_state
            if "session_state" in kwargs:
                log_warning("Session state parameter passed in both request state and kwargs, using request state")
            kwargs["session_state"] = session_state
        if hasattr(request.state, "dependencies") and request.state.dependencies is not None:
            dependencies = request.state.dependencies
            if "dependencies" in kwargs:
                log_warning("Dependencies parameter passed in both request state and kwargs, using request state")
            kwargs["dependencies"] = dependencies
        if hasattr(request.state, "metadata") and request.state.metadata is not None:
            metadata = request.state.metadata
            if "metadata" in kwargs:
                log_warning("Metadata parameter passed in both request state and kwargs, using request state")
            kwargs["metadata"] = metadata

        logger.debug(f"Creating team run: {message=} {session_id=} {monitor=} {user_id=} {team_id=} {files=} {kwargs=}")

        team = get_team_by_id(
            team_id=team_id, teams=os.teams, db=os.db, version=version, registry=registry, create_fresh=True
        )
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if session_id is not None and session_id != "":
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        base64_images: List[Image] = []
        base64_audios: List[Audio] = []
        base64_videos: List[Video] = []
        document_files: List[FileMedia] = []

        if files:
            for file in files:
                if file.content_type in ["image/png", "image/jpeg", "image/jpg", "image/webp"]:
                    try:
                        base64_image = process_image(file)
                        base64_images.append(base64_image)
                    except Exception as e:
                        logger.error(f"Error processing image {file.filename}: {e}")
                        continue
                elif file.content_type in ["audio/wav", "audio/mp3", "audio/mpeg"]:
                    try:
                        base64_audio = process_audio(file)
                        base64_audios.append(base64_audio)
                    except Exception as e:
                        logger.error(f"Error processing audio {file.filename}: {e}")
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
                        logger.error(f"Error processing video {file.filename}: {e}")
                        continue
                elif file.content_type in [
                    "application/pdf",
                    "text/csv",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "text/plain",
                    "application/json",
                ]:
                    document_file = process_document(file)
                    if document_file is not None:
                        document_files.append(document_file)
                else:
                    raise HTTPException(status_code=400, detail="Unsupported file type")

        # Extract auth token for remote teams
        auth_token = get_auth_token_from_request(request)

        # Background execution: return 202 immediately with run metadata
        if background:
            if isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail="Background execution is not supported for remote teams")
            if not team.db:
                raise HTTPException(
                    status_code=400, detail="Background execution requires a database to be configured on the team"
                )

            run_response = await team.arun(  # type: ignore[misc]
                input=message,
                session_id=session_id,
                user_id=user_id,
                images=base64_images if base64_images else None,
                audio=base64_audios if base64_audios else None,
                videos=base64_videos if base64_videos else None,
                files=document_files if document_files else None,
                stream=False,
                background=True,
                **kwargs,
            )
            return JSONResponse(
                status_code=202,
                content={
                    "run_id": run_response.run_id,
                    "session_id": run_response.session_id,
                    "status": run_response.status.value if run_response.status else "PENDING",
                },
            )

        if stream:
            return StreamingResponse(
                team_response_streamer(
                    team,
                    message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    background_tasks=background_tasks,
                    auth_token=auth_token,
                    **kwargs,
                ),
                media_type="text/event-stream",
            )
        else:
            # Pass auth_token for remote teams
            if auth_token and isinstance(team, RemoteTeam):
                kwargs["auth_token"] = auth_token

            try:
                run_response = await team.arun(  # type: ignore[misc]
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    images=base64_images if base64_images else None,
                    audio=base64_audios if base64_audios else None,
                    videos=base64_videos if base64_videos else None,
                    files=document_files if document_files else None,
                    stream=False,
                    background_tasks=background_tasks,
                    **kwargs,
                )
                return run_response.to_dict()

            except InputCheckError as e:
                raise HTTPException(status_code=400, detail=str(e))

    @router.post(
        "/teams/{team_id}/runs/{run_id}/cancel",
        tags=["Teams"],
        operation_id="cancel_team_run",
        response_model_exclude_none=True,
        summary="Cancel Team Run",
        description=(
            "Cancel a currently executing team run. This will attempt to stop the team's execution gracefully.\n\n"
            "**Note:** Cancellation may not be immediate for all operations."
        ),
        responses={
            200: {},
            404: {"description": "Team not found", "model": NotFoundResponse},
            500: {"description": "Failed to cancel team run", "model": InternalServerErrorResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def cancel_team_run(
        team_id: str,
        run_id: str,
    ):
        team = get_team_by_id(team_id=team_id, teams=os.teams, db=os.db, registry=registry, create_fresh=True)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        # cancel_run always stores cancellation intent (even for not-yet-registered runs
        # in cancel-before-start scenarios), so we always return success.
        await team.acancel_run(run_id=run_id)
        return JSONResponse(content={}, status_code=200)

    @router.get(
        "/teams",
        response_model=List[TeamResponse],
        response_model_exclude_none=True,
        tags=["Teams"],
        operation_id="get_teams",
        summary="List All Teams",
        description=(
            "Retrieve a comprehensive list of all teams configured in this OS instance.\n\n"
            "**Returns team information including:**\n"
            "- Team metadata (ID, name, description, execution mode)\n"
            "- Model configuration for team coordination\n"
            "- Team member roster with roles and capabilities\n"
            "- Knowledge sharing and memory configurations"
        ),
        responses={
            200: {
                "description": "List of teams retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "team_id": "basic-team",
                                "name": "Basic Team",
                                "mode": "coordinate",
                                "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                "tools": [
                                    {
                                        "name": "transfer_task_to_member",
                                        "description": "Use this function to transfer a task to the selected team member.\nYou must provide a clear and concise description of the task the member should achieve AND the expected output.",
                                        "parameters": {
                                            "type": "object",
                                            "properties": {
                                                "member_id": {
                                                    "type": "string",
                                                    "description": "(str) The ID of the member to transfer the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.",
                                                },
                                                "task_description": {
                                                    "type": "string",
                                                    "description": "(str) A clear and concise description of the task the member should achieve.",
                                                },
                                                "expected_output": {
                                                    "type": "string",
                                                    "description": "(str) The expected output from the member (optional).",
                                                },
                                            },
                                            "additionalProperties": False,
                                            "required": ["member_id", "task_description"],
                                        },
                                    }
                                ],
                                "members": [
                                    {
                                        "agent_id": "basic-agent",
                                        "name": "Basic Agent",
                                        "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI gpt-4o"},
                                        "memory": {
                                            "app_name": "Memory",
                                            "app_url": None,
                                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                        },
                                        "session_table": "agno_sessions",
                                        "memory_table": "agno_memories",
                                    }
                                ],
                                "enable_agentic_context": False,
                                "memory": {
                                    "app_name": "agno_memories",
                                    "app_url": "/memory/1",
                                    "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                },
                                "async_mode": False,
                                "session_table": "agno_sessions",
                                "memory_table": "agno_memories",
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_teams(request: Request) -> List[TeamResponse]:
        """Return the list of all Teams present in the contextual OS"""
        # Filter teams based on user's scopes (only if authorization is enabled)
        if getattr(request.state, "authorization_enabled", False):
            from agno.os.auth import filter_resources_by_access, get_accessible_resources

            # Check if user has any team scopes at all
            accessible_ids = get_accessible_resources(request, "teams")
            if not accessible_ids:
                raise HTTPException(status_code=403, detail="Insufficient permissions")

            accessible_teams = filter_resources_by_access(request, os.teams or [], "teams")
        else:
            accessible_teams = os.teams or []

        teams = []
        for team in accessible_teams:
            if isinstance(team, RemoteTeam):
                teams.append(await team.get_team_config())
            else:
                team_response = await TeamResponse.from_team(team=team)
                teams.append(team_response)

        # Also load teams from database
        if os.db and isinstance(os.db, BaseDb):
            from agno.team.team import get_teams

            db_teams = get_teams(db=os.db, registry=registry)
            for db_team in db_teams:
                team_response = await TeamResponse.from_team(team=db_team)
                teams.append(team_response)

        return teams

    @router.get(
        "/teams/{team_id}",
        response_model=TeamResponse,
        response_model_exclude_none=True,
        tags=["Teams"],
        operation_id="get_team",
        summary="Get Team Details",
        description=("Retrieve detailed configuration and member information for a specific team."),
        responses={
            200: {
                "description": "Team details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "team_id": "basic-team",
                            "name": "Basic Team",
                            "description": None,
                            "mode": "coordinate",
                            "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                            "tools": [
                                {
                                    "name": "transfer_task_to_member",
                                    "description": "Use this function to transfer a task to the selected team member.\nYou must provide a clear and concise description of the task the member should achieve AND the expected output.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {
                                            "member_id": {
                                                "type": "string",
                                                "description": "(str) The ID of the member to transfer the task to. Use only the ID of the member, not the ID of the team followed by the ID of the member.",
                                            },
                                            "task_description": {
                                                "type": "string",
                                                "description": "(str) A clear and concise description of the task the member should achieve.",
                                            },
                                            "expected_output": {
                                                "type": "string",
                                                "description": "(str) The expected output from the member (optional).",
                                            },
                                        },
                                        "additionalProperties": False,
                                        "required": ["member_id", "task_description"],
                                    },
                                }
                            ],
                            "instructions": None,
                            "members": [
                                {
                                    "agent_id": "basic-agent",
                                    "name": "Basic Agent",
                                    "description": None,
                                    "instructions": None,
                                    "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI gpt-4o"},
                                    "tools": None,
                                    "memory": {
                                        "app_name": "Memory",
                                        "app_url": None,
                                        "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                                    },
                                    "knowledge": None,
                                    "session_table": "agno_sessions",
                                    "memory_table": "agno_memories",
                                    "knowledge_table": None,
                                }
                            ],
                            "expected_output": None,
                            "dependencies": None,
                            "enable_agentic_context": False,
                            "memory": {
                                "app_name": "Memory",
                                "app_url": None,
                                "model": {"name": "OpenAIChat", "model": "gpt-4o", "provider": "OpenAI"},
                            },
                            "knowledge": None,
                            "async_mode": False,
                            "session_table": "agno_sessions",
                            "memory_table": "agno_memories",
                            "knowledge_table": None,
                        }
                    }
                },
            },
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "read", "team_id"))],
    )
    async def get_team(team_id: str, request: Request) -> TeamResponse:
        team = get_team_by_id(team_id=team_id, teams=os.teams, db=os.db, registry=registry, create_fresh=True)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if isinstance(team, RemoteTeam):
            return await team.get_team_config()
        else:
            return await TeamResponse.from_team(team=team)

    @router.get(
        "/teams/{team_id}/runs/{run_id}",
        tags=["Teams"],
        operation_id="get_team_run",
        summary="Get Team Run",
        description=(
            "Retrieve the status and output of a team run. Use this to poll for background run completion.\n\n"
            "Requires the `session_id` that was returned when the run was created."
        ),
        responses={
            200: {"description": "Run output retrieved successfully"},
            404: {"description": "Team or run not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def get_team_run(
        team_id: str,
        run_id: str,
        session_id: str = Query(..., description="Session ID for the run"),
    ):
        team = get_team_by_id(team_id=team_id, teams=os.teams, db=os.db, registry=registry, create_fresh=True)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        if isinstance(team, RemoteTeam):
            raise HTTPException(status_code=400, detail="Run polling is not supported for remote teams")

        run_output = await team.aget_run_output(run_id=run_id, session_id=session_id)
        if run_output is None:
            raise HTTPException(status_code=404, detail="Run not found")

        return run_output.to_dict()

    @router.get(
        "/teams/{team_id}/runs",
        tags=["Teams"],
        operation_id="list_team_runs",
        summary="List Team Runs",
        description=(
            "List runs for a team within a session, optionally filtered by status.\n\n"
            "Useful for monitoring background runs and viewing run history."
        ),
        responses={
            200: {"description": "List of runs retrieved successfully"},
            404: {"description": "Team not found", "model": NotFoundResponse},
        },
        dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
    )
    async def list_team_runs(
        team_id: str,
        session_id: str = Query(..., description="Session ID to list runs for"),
        status: Optional[str] = Query(None, description="Filter by run status (PENDING, RUNNING, COMPLETED, ERROR)"),
    ):
        from agno.os.schema import TeamRunSchema
        from agno.team._storage import _aread_or_create_session

        team = get_team_by_id(team_id=team_id, teams=os.teams, db=os.db, registry=registry, create_fresh=True)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")
        if isinstance(team, RemoteTeam):
            raise HTTPException(status_code=400, detail="Run listing is not supported for remote teams")

        session = await _aread_or_create_session(team, session_id=session_id)
        runs = session.runs or []

        result = []
        for run in runs:
            run_dict = run.to_dict()
            if status and run_dict.get("status") != status:
                continue
            result.append(TeamRunSchema.from_dict(run_dict))

        return result

    return router
