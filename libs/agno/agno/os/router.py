import json
from typing import TYPE_CHECKING, Any, AsyncGenerator, Dict, List, Optional, Union, cast
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from agno.agent.agent import Agent
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    AgentResponse,
    AgentSummaryResponse,
    ConfigResponse,
    InterfaceResponse,
    Model,
    TeamResponse,
    TeamSummaryResponse,
    WorkflowResponse,
    WorkflowSummaryResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import (
    get_agent_by_id,
    get_team_by_id,
    get_workflow_by_id,
    process_audio,
    process_document,
    process_image,
    process_video,
)
from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.workflow import WorkflowErrorEvent
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_warning, logger
from agno.workflow.workflow import Workflow

if TYPE_CHECKING:
    from agno.os.app import AgentOS


def format_sse_event(json_data: str) -> str:
    """Parse JSON data into SSE-compliant format.

    Args:
        json_data: JSON string containing the event data

    Returns:
        SSE-formatted response:

        ```
        event: EventName
        data: { ... }

        event: AnotherEventName
        data: { ... }
        ```
    """
    try:
        # Parse the JSON to extract the event type
        data = json.loads(json_data)
        event_type = data.get("event", "message")

        # Format as SSE: event: <event_type>\ndata: <json_data>\n\n
        return f"event: {event_type}\ndata: {json_data}\n\n"
    except (json.JSONDecodeError, KeyError):
        # Fallback to generic message event if parsing fails
        return f"event: message\ndata: {json_data}\n\n"


class WebSocketManager:
    """Manages WebSocket connections for workflow runs"""

    active_connections: Dict[str, WebSocket]  # {run_id: websocket}

    def __init__(
        self,
        active_connections: Optional[Dict[str, WebSocket]] = None,
    ):
        # Store active connections: {run_id: websocket}
        self.active_connections = active_connections or {}

    async def connect(self, websocket: WebSocket):
        """Accept WebSocket connection"""
        await websocket.accept()
        logger.debug("WebSocket connected")

        # Send connection confirmation
        await websocket.send_text(
            json.dumps(
                {
                    "event": "connected",
                    "message": "Connected to workflow events",
                }
            )
        )

    async def register_workflow_websocket(self, run_id: str, websocket: WebSocket):
        """Register a workflow run with its WebSocket connection"""
        self.active_connections[run_id] = websocket
        logger.debug(f"Registered WebSocket for run_id: {run_id}")

    async def disconnect_by_run_id(self, run_id: str):
        """Remove WebSocket connection by run_id"""
        if run_id in self.active_connections:
            del self.active_connections[run_id]
            logger.debug(f"WebSocket disconnected for run_id: {run_id}")

    async def get_websocket_for_run(self, run_id: str) -> Optional[WebSocket]:
        """Get WebSocket connection for a workflow run"""
        return self.active_connections.get(run_id)


# Global manager instance
websocket_manager = WebSocketManager(
    active_connections={},
)


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
        run_response = agent.arun(
            input=message,
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
            yield format_sse_event(run_response_chunk.to_json())

    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response.to_json())


async def agent_continue_response_streamer(
    agent: Agent,
    run_id: Optional[str] = None,
    updated_tools: Optional[List] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> AsyncGenerator:
    try:
        continue_response = agent.acontinue_run(
            run_id=run_id,
            updated_tools=updated_tools,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_intermediate_steps=True,
        )
        async for run_response_chunk in continue_response:
            yield format_sse_event(run_response_chunk.to_json())

    except Exception as e:
        import traceback

        traceback.print_exc(limit=3)
        error_response = RunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response.to_json())
        return


async def team_response_streamer(
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
        run_response = team.arun(
            input=message,
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
            yield format_sse_event(run_response_chunk.to_json())

    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = TeamRunErrorEvent(
            content=str(e),
        )
        yield format_sse_event(error_response.to_json())
        return


async def handle_workflow_via_websocket(websocket: WebSocket, message: dict, os: "AgentOS"):
    """Handle workflow execution directly via WebSocket"""
    try:
        workflow_id = message.get("workflow_id")
        session_id = message.get("session_id")
        user_message = message.get("message", "")
        user_id = message.get("user_id")

        if not workflow_id:
            await websocket.send_text(json.dumps({"event": "error", "error": "workflow_id is required"}))
            return

        # Get workflow from OS
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if not workflow:
            await websocket.send_text(json.dumps({"event": "error", "error": f"Workflow {workflow_id} not found"}))
            return

        # Generate session_id if not provided
        # Use workflow's default session_id if not provided in message
        if not session_id:
            if workflow.session_id:
                session_id = workflow.session_id
            else:
                session_id = str(uuid4())

        # Execute workflow in background with streaming
        await workflow.arun(
            input=user_message,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_intermediate_steps=True,
            background=True,
            websocket=websocket,
        )

    except Exception as e:
        logger.error(f"Error executing workflow via WebSocket: {e}")
        await websocket.send_text(json.dumps({"event": "error", "error": str(e)}))


async def workflow_response_streamer(
    workflow: Workflow,
    input: Optional[Union[str, Dict[str, Any], List[Any], BaseModel]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    **kwargs: Any,
) -> AsyncGenerator:
    try:
        run_response = await workflow.arun(
            input=input,
            session_id=session_id,
            user_id=user_id,
            stream=True,
            stream_intermediate_steps=True,
            **kwargs,
        )

        async for run_response_chunk in run_response:
            yield format_sse_event(run_response_chunk.to_json())

    except Exception as e:
        import traceback

        traceback.print_exc()
        error_response = WorkflowErrorEvent(
            error=str(e),
        )
        yield format_sse_event(error_response.to_json())
        return


def get_base_router(
    os: "AgentOS",
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_authentication_dependency(settings))])

    # -- Main Routes ---

    @router.get("/health", tags=["Core"])
    async def health_check():
        return JSONResponse(content={"status": "ok"})

    @router.get(
        "/config",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        tags=["Core"],
    )
    async def config() -> ConfigResponse:
        return ConfigResponse(
            os_id=os.os_id or "Unnamed OS",
            description=os.description,
            available_models=os.config.available_models if os.config else [],
            databases=[db.id for db in os.dbs.values()],
            chat=os.config.chat if os.config else None,
            session=os._get_session_config(),
            memory=os._get_memory_config(),
            knowledge=os._get_knowledge_config(),
            evals=os._get_evals_config(),
            metrics=os._get_metrics_config(),
            agents=[AgentSummaryResponse.from_agent(agent) for agent in os.agents] if os.agents else [],
            teams=[TeamSummaryResponse.from_team(team) for team in os.teams] if os.teams else [],
            workflows=[WorkflowSummaryResponse.from_workflow(w) for w in os.workflows] if os.workflows else [],
            interfaces=[
                InterfaceResponse(type=interface.type, version=interface.version, route=interface.router_prefix)
                for interface in os.interfaces
            ],
        )

    @router.get(
        "/models",
        response_model=List[Model],
        response_model_exclude_none=True,
        tags=["Core"],
    )
    async def get_models():
        """Return the list of all models used by agents and teams in the contextual OS"""
        all_components: List[Union[Agent, Team]] = []
        if os.agents:
            all_components.extend(os.agents)
        if os.teams:
            all_components.extend(os.teams)

        unique_models = {}
        for item in all_components:
            model = cast(Model, item.model)
            if model.id is not None and model.provider is not None:
                key = (model.id, model.provider)
                if key not in unique_models:
                    unique_models[key] = Model(id=model.id, provider=model.provider)

        return list(unique_models.values())

    # -- Agent routes ---

    @router.post("/agents/{agent_id}/runs", tags=["Agents"])
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
            log_debug("Creating new session")
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
                ),
                media_type="text/event-stream",
            )
        else:
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
                ),
            )
            return run_response.to_dict()

    @router.post(
        "/agents/{agent_id}/runs/{run_id}/cancel",
        tags=["Agents"],
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
    )
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
                ),
                media_type="text/event-stream",
            )
        else:
            run_response_obj = cast(
                RunOutput,
                await agent.acontinue_run(
                    run_id=run_id,  # run_id from path
                    updated_tools=updated_tools,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                ),
            )
            return run_response_obj.to_dict()

    @router.get(
        "/agents",
        response_model=List[AgentResponse],
        response_model_exclude_none=True,
        tags=["Agents"],
    )
    async def get_agents():
        """Return the list of all Agents present in the contextual OS"""
        if os.agents is None:
            return []

        agents = []
        for agent in os.agents:
            agents.append(AgentResponse.from_agent(agent=agent))

        return agents

    @router.get(
        "/agents/{agent_id}",
        response_model=AgentResponse,
        response_model_exclude_none=True,
        tags=["Agents"],
    )
    async def get_agent(agent_id: str):
        agent = get_agent_by_id(agent_id, os.agents)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")

        return AgentResponse.from_agent(agent)

    # -- Team routes ---

    @router.post("/teams/{team_id}/runs", tags=["Teams"])
    async def create_team_run(
        team_id: str,
        message: str = Form(...),
        stream: bool = Form(True),
        monitor: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        files: Optional[List[UploadFile]] = File(None),
    ):
        logger.debug(f"Creating team run: {message} {session_id} {monitor} {user_id} {team_id} {files}")
        team = get_team_by_id(team_id, os.teams)
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
                ),
                media_type="text/event-stream",
            )
        else:
            run_response = await team.arun(
                input=message,
                session_id=session_id,
                user_id=user_id,
                images=base64_images if base64_images else None,
                audio=base64_audios if base64_audios else None,
                videos=base64_videos if base64_videos else None,
                files=document_files if document_files else None,
                stream=False,
            )
            return run_response.to_dict()

    @router.post(
        "/teams/{team_id}/runs/{run_id}/cancel",
        tags=["Teams"],
    )
    async def cancel_team_run(
        team_id: str,
        run_id: str,
    ):
        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        if not team.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    @router.get(
        "/teams",
        response_model=List[TeamResponse],
        response_model_exclude_none=True,
        tags=["Teams"],
    )
    async def get_teams():
        """Return the list of all Teams present in the contextual OS"""
        if os.teams is None:
            return []

        teams = []
        for team in os.teams:
            teams.append(TeamResponse.from_team(team=team))

        return teams

    @router.get(
        "/teams/{team_id}",
        response_model=TeamResponse,
        response_model_exclude_none=True,
        tags=["Teams"],
    )
    async def get_team(team_id: str):
        team = get_team_by_id(team_id, os.teams)
        if team is None:
            raise HTTPException(status_code=404, detail="Team not found")

        return TeamResponse.from_team(team)

    # -- Workflow routes ---

    @router.websocket("/workflows/ws")
    async def workflow_websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for receiving real-time workflow events"""
        await websocket_manager.connect(websocket)

        try:
            while True:
                data = await websocket.receive_text()
                message = json.loads(data)
                action = message.get("action")

                if action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))

                elif action == "start-workflow":
                    # Handle workflow execution directly via WebSocket
                    await handle_workflow_via_websocket(websocket, message, os)

        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            # Clean up any run_ids associated with this websocket
            runs_to_remove = [run_id for run_id, ws in websocket_manager.active_connections.items() if ws == websocket]
            for run_id in runs_to_remove:
                await websocket_manager.disconnect_by_run_id(run_id)

    @router.get(
        "/workflows",
        response_model=List[WorkflowResponse],
        response_model_exclude_none=True,
        tags=["Workflows"],
    )
    async def get_workflows():
        if os.workflows is None:
            return []

        return [WorkflowSummaryResponse.from_workflow(workflow) for workflow in os.workflows]

    @router.get(
        "/workflows/{workflow_id}",
        response_model=WorkflowResponse,
        response_model_exclude_none=True,
        tags=["Workflows"],
    )
    async def get_workflow(workflow_id: str):
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return WorkflowResponse.from_workflow(workflow)

    @router.post("/workflows/{workflow_id}/runs", tags=["Workflows"])
    async def create_workflow_run(
        workflow_id: str,
        message: str = Form(...),
        stream: bool = Form(True),
        session_id: Optional[str] = Form(None),
        user_id: Optional[str] = Form(None),
        **kwargs: Any,
    ):
        # Retrieve the workflow by ID
        workflow = get_workflow_by_id(workflow_id, os.workflows)
        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if session_id:
            logger.debug(f"Continuing session: {session_id}")
        else:
            logger.debug("Creating new session")
            session_id = str(uuid4())

        # Return based on stream parameter
        try:
            if stream:
                return StreamingResponse(
                    workflow_response_streamer(
                        workflow,
                        input=message,
                        session_id=session_id,
                        user_id=user_id,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
                run_response = await workflow.arun(
                    input=message,
                    session_id=session_id,
                    user_id=user_id,
                    stream=False,
                    **kwargs,
                )
                return run_response.to_dict()
        except Exception as e:
            # Handle unexpected runtime errors
            raise HTTPException(status_code=500, detail=f"Error running workflow: {str(e)}")

    @router.post("/workflows/{workflow_id}/runs/{run_id}/cancel", tags=["Workflows"])
    async def cancel_workflow_run(workflow_id: str, run_id: str):
        workflow = get_workflow_by_id(workflow_id, os.workflows)

        if workflow is None:
            raise HTTPException(status_code=404, detail="Workflow not found")

        if not workflow.cancel_run(run_id=run_id):
            raise HTTPException(status_code=500, detail="Failed to cancel run")

        return JSONResponse(content={}, status_code=200)

    return router
