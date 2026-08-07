"""Routes for the RemoteAccess interface.

These routes mirror the default AgentOS run endpoints but resolve entities ONLY against
the lists passed to the RemoteAccess interface. Entities registered on the AgentOS but
not opted into the interface return 404 here, which is what makes remote execution opt-in.

Compared to the default routers, these routes do not support versioned components,
background execution, or factory entities. Workflows are not remotely executable.
"""

import json
from typing import Any, Dict, List, Literal, Optional, Union
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

from agno.agent.agent import Agent
from agno.agent.protocol import AgentProtocol
from agno.agent.remote import RemoteAgent
from agno.exceptions import (
    InputCheckError,
    RemoteServerUnavailableError,
    RunNotContinuableError,
    RunNotFoundError,
)
from agno.media import Audio, Image, Video
from agno.media import File as FileMedia
from agno.os.auth import get_auth_token_from_request, require_resource_access
from agno.os.config import (
    DatabaseConfig,
    EvalsConfig,
    EvalsDomainConfig,
    KnowledgeConfig,
    KnowledgeDatabaseConfig,
    KnowledgeDomainConfig,
    LearningConfig,
    LearningDomainConfig,
    MemoryConfig,
    MemoryDomainConfig,
    MetricsConfig,
    MetricsDomainConfig,
    SessionConfig,
    SessionDomainConfig,
    TracesConfig,
    TracesDomainConfig,
)
from agno.os.middleware.user_scope import (
    SESSION_ID_REQUIRED,
    get_scoped_user_id,
    verify_run_in_session,
)
from agno.os.routers.agents.schema import AgentResponse
from agno.os.routers.teams.schema import TeamResponse
from agno.os.schema import (
    AgentSummaryResponse,
    BadRequestResponse,
    ConfigResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    TeamSummaryResponse,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.utils import (
    classify_upload_file,
    get_agent_by_id,
    get_request_kwargs,
    get_team_by_id,
    process_audio,
    process_document,
    process_image,
    process_video,
)
from agno.team.remote import RemoteTeam
from agno.team.team import Team
from agno.utils.log import log_debug, log_error, log_warning


def _parse_continue_from(continue_from: str) -> Union[int, Literal["end", "last_user"]]:
    stripped = continue_from.strip()
    if stripped.lstrip("-").isdigit():
        return int(stripped)
    if stripped in ("end", "last_user"):
        return stripped  # type: ignore[return-value]
    raise HTTPException(
        status_code=400,
        detail="Invalid continue_from. Use 'end', 'last_user', or a numeric message index.",
    )


def _merge_request_state(
    request: Request,
    kwargs: Dict[str, Any],
    session_id: Optional[str],
    user_id: Optional[str],
) -> tuple:
    """Apply middleware-provided identity/state, mirroring the default routers."""
    scoped_user_id = get_scoped_user_id(request)
    if scoped_user_id is not None:
        user_id = scoped_user_id
    elif hasattr(request.state, "user_id") and request.state.user_id is not None:
        if user_id and user_id != request.state.user_id:
            log_warning("User ID parameter passed in both request state and kwargs, using request state")
        user_id = request.state.user_id
    if hasattr(request.state, "session_id") and request.state.session_id is not None:
        if session_id and session_id != request.state.session_id:
            log_warning("Session ID parameter passed in both request state and kwargs, using request state")
        session_id = request.state.session_id
    for state_key in ("session_state", "dependencies", "metadata"):
        state_value = getattr(request.state, state_key, None)
        if state_value is not None:
            if state_key in kwargs:
                log_warning(f"{state_key} parameter passed in both request state and kwargs, using request state")
            kwargs[state_key] = state_value
    return session_id, user_id


def _process_upload_files(files: Optional[List[UploadFile]]) -> tuple:
    """Classify and process uploaded files, mirroring the default agent router."""
    base64_images: List[Image] = []
    base64_audios: List[Audio] = []
    base64_videos: List[Video] = []
    input_files: List[FileMedia] = []

    if files:
        for file in files:
            file_category = classify_upload_file(file)
            if file_category == "image":
                try:
                    base64_images.append(process_image(file))
                except Exception as e:
                    log_error(f"Error processing image {file.filename}: {str(e)}")
                    continue
            elif file_category == "audio":
                try:
                    base64_audios.append(process_audio(file))
                except Exception as e:
                    log_error(f"Error processing audio {file.filename} with content type {file.content_type}: {str(e)}")
                    continue
            elif file_category == "video":
                try:
                    base64_videos.append(process_video(file))
                except Exception as e:
                    log_error(f"Error processing video {file.filename}: {str(e)}")
                    continue
            elif file_category == "document":
                try:
                    input_file = process_document(file)
                    if input_file is not None:
                        input_files.append(input_file)
                except Exception as e:
                    log_error(f"Error processing file {file.filename}: {str(e)}")
                    continue
            else:
                raise HTTPException(status_code=400, detail="Unsupported file type")

    return base64_images, base64_audios, base64_videos, input_files


def _filter_by_access(request: Request, entities: List[Any], resource_type: str) -> List[Any]:
    """Apply RBAC list filtering when authorization is enabled, mirroring the default routers."""
    if not getattr(request.state, "authorization_enabled", False):
        return entities

    from agno.os.auth import (
        build_insufficient_permissions_detail,
        filter_resources_by_access,
        get_accessible_resources,
    )

    accessible_ids = get_accessible_resources(request, resource_type)
    if not accessible_ids:
        required_scopes = getattr(request.state, "required_scopes", None)
        raise HTTPException(status_code=403, detail=build_insufficient_permissions_detail(required_scopes))

    return filter_resources_by_access(request, entities, resource_type)


def _collect_local_dbs(entities: List[Any]) -> Dict[str, List[Any]]:
    """Collect databases from local entities, keyed by db id.

    Remote entities are skipped: reading their db property triggers HTTP calls to
    their own upstream servers, which must not happen while serving config.
    """
    dbs_by_id: Dict[str, List[Any]] = {}
    for entity in entities:
        if not isinstance(entity, (Agent, Team)):
            continue
        db = getattr(entity, "db", None)
        db_id = getattr(db, "id", None) if db is not None else None
        if db is not None and db_id:
            dbs_by_id.setdefault(db_id, []).append(db)
    return dbs_by_id


def _domain_db_configs(
    dbs_by_id: Dict[str, List[Any]], table_attr: str, domain_config_cls: Any
) -> List[DatabaseConfig]:
    configs: List[DatabaseConfig] = []
    for db_id, dbs in dbs_by_id.items():
        tables = list({getattr(db, table_attr) for db in dbs if getattr(db, table_attr, None) is not None})
        configs.append(
            DatabaseConfig(
                db_id=db_id,
                domain_config=domain_config_cls(display_name=db_id),
                tables=tables,
            )
        )
    return configs


def attach_routes(
    router: APIRouter,
    agents: Optional[List[Union[Agent, RemoteAgent, AgentProtocol]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
) -> APIRouter:
    if not (agents or teams):
        raise ValueError("Agents or Teams are required to setup the RemoteAccess interface.")

    error_responses: Dict[Union[int, str], Dict[str, Any]] = {
        400: {"description": "Bad Request", "model": BadRequestResponse},
        401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
        404: {"description": "Not Found", "model": NotFoundResponse},
        422: {"description": "Validation Error", "model": ValidationErrorResponse},
        500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
    }

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    @router.get(
        "/config",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        operation_id="get_remote_config",
        summary="Get RemoteAccess Interface Config",
        description=(
            "Configuration for the remotely exposed entities. Serves the same shape as the main "
            "/config route, scoped to the entities opted into the RemoteAccess interface."
        ),
        responses=error_responses,
    )
    async def get_remote_config() -> ConfigResponse:
        all_entities: List[Any] = [*(agents or []), *(teams or [])]
        dbs_by_id = _collect_local_dbs(all_entities)

        try:
            agent_summaries = [AgentSummaryResponse.from_agent(a) for a in agents] if agents else []
            team_summaries = [TeamSummaryResponse.from_team(t) for t in teams] if teams else []
        except RemoteServerUnavailableError as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch config from remote AgentOS: {e}")

        return ConfigResponse(
            os_id="remote",
            description="Entities exposed for remote execution through the RemoteAccess interface",
            available_models=[],
            databases=list(dbs_by_id.keys()),
            session=SessionConfig(dbs=_domain_db_configs(dbs_by_id, "session_table_name", SessionDomainConfig)),
            memory=MemoryConfig(dbs=_domain_db_configs(dbs_by_id, "memory_table_name", MemoryDomainConfig)),
            learning=LearningConfig(dbs=_domain_db_configs(dbs_by_id, "learnings_table_name", LearningDomainConfig)),
            knowledge=KnowledgeConfig(
                dbs=[
                    KnowledgeDatabaseConfig(
                        db_id=config.db_id,
                        domain_config=KnowledgeDomainConfig(display_name=config.db_id),
                        tables=config.tables or [],
                    )
                    for config in _domain_db_configs(dbs_by_id, "knowledge_table_name", KnowledgeDomainConfig)
                ],
                knowledge_instances=[],
            ),
            evals=EvalsConfig(dbs=_domain_db_configs(dbs_by_id, "eval_table_name", EvalsDomainConfig)),
            metrics=MetricsConfig(dbs=_domain_db_configs(dbs_by_id, "metrics_table_name", MetricsDomainConfig)),
            traces=TracesConfig(dbs=_domain_db_configs(dbs_by_id, "trace_table_name", TracesDomainConfig)),
            agents=agent_summaries,
            teams=team_summaries,
            workflows=[],
            interfaces=[],
        )

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    if agents:

        def _resolve_agent(agent_id: str) -> Union[Agent, RemoteAgent, AgentProtocol]:
            agent = get_agent_by_id(agent_id=agent_id, agents=agents, create_fresh=True)
            if agent is None:
                raise HTTPException(status_code=404, detail="Agent not found or not exposed for remote execution")
            return agent

        @router.get(
            "/agents",
            response_model=List[AgentResponse],
            response_model_exclude_none=True,
            operation_id="get_remote_agents",
            summary="List Remotely Exposed Agents",
            description="List the agents exposed for remote execution through this interface.",
            responses=error_responses,
        )
        async def get_remote_agents(request: Request) -> List[AgentResponse]:
            accessible_agents = _filter_by_access(request, list(agents), "agents")

            responses: List[AgentResponse] = []
            for agent in accessible_agents:
                if isinstance(agent, Agent):
                    responses.append(await AgentResponse.from_agent(agent=agent, is_component=False))
                elif isinstance(agent, RemoteAgent):
                    responses.append(await agent.get_agent_config())
                else:
                    responses.append(
                        AgentResponse(
                            id=agent.id,
                            name=agent.name,
                            description=getattr(agent, "description", None),
                            metadata={"framework": getattr(agent, "framework", "external")},
                        )
                    )
            return responses

        @router.get(
            "/agents/{agent_id}",
            response_model=AgentResponse,
            response_model_exclude_none=True,
            operation_id="get_remote_agent",
            summary="Get Remotely Exposed Agent",
            description="Get the configuration of an agent exposed for remote execution.",
            responses=error_responses,
            dependencies=[Depends(require_resource_access("agents", "read", "agent_id"))],
        )
        async def get_remote_agent(agent_id: str) -> AgentResponse:
            agent = _resolve_agent(agent_id)
            if isinstance(agent, RemoteAgent):
                return await agent.get_agent_config()
            elif isinstance(agent, Agent):
                return await AgentResponse.from_agent(agent=agent)
            else:
                return AgentResponse(
                    id=agent.id,
                    name=agent.name,
                    description=getattr(agent, "description", None),
                    metadata={"framework": getattr(agent, "framework", "external")},
                )

        @router.post(
            "/agents/{agent_id}/runs",
            operation_id="create_remote_agent_run",
            response_model_exclude_none=True,
            summary="Create Remote Agent Run",
            description=(
                "Execute a remotely exposed agent. Supports both streaming (SSE) and non-streaming responses."
            ),
            responses=error_responses,
            dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
        )
        async def create_remote_agent_run(
            agent_id: str,
            request: Request,
            background_tasks: BackgroundTasks,
            message: str = Form(..., description="The input message or prompt to send to the agent"),
            stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
            session_id: Optional[str] = Form(None, description="Session ID for conversation continuity"),
            user_id: Optional[str] = Form(None, description="User identifier"),
            files: Optional[List[UploadFile]] = File(None, description="Files to upload"),
        ):
            from agno.os.routers.agents.router import agent_response_streamer

            kwargs = await get_request_kwargs(request, create_remote_agent_run)
            session_id, user_id = _merge_request_state(request, kwargs, session_id, user_id)

            agent = _resolve_agent(agent_id)

            if session_id is None or session_id == "":
                log_debug("Creating new session")
                session_id = str(uuid4())

            base64_images, base64_audios, base64_videos, input_files = _process_upload_files(files)

            # Merge media passed as JSON form fields with media from uploaded files.
            base64_images.extend(kwargs.pop("images", None) or [])
            base64_audios.extend(kwargs.pop("audio", None) or [])
            base64_videos.extend(kwargs.pop("videos", None) or [])
            input_files.extend(kwargs.pop("files", None) or [])

            auth_token = get_auth_token_from_request(request)

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
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
                if auth_token and isinstance(agent, RemoteAgent):
                    kwargs["auth_token"] = auth_token

                try:
                    run_response = await agent.arun(  # type: ignore[misc]
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
                    )
                    return run_response.to_dict()
                except InputCheckError as e:
                    raise HTTPException(status_code=400, detail=str(e))

        @router.post(
            "/agents/{agent_id}/runs/{run_id}/continue",
            operation_id="continue_remote_agent_run",
            response_model_exclude_none=True,
            summary="Continue Remote Agent Run",
            description="Continue a paused run of a remotely exposed agent with tool results.",
            responses=error_responses,
            dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
        )
        async def continue_remote_agent_run(
            agent_id: str,
            run_id: str,
            request: Request,
            background_tasks: BackgroundTasks,
            tools: str = Form("", description="JSON string of tool call results to continue the paused run"),
            input: Optional[str] = Form(None, description="Optional new user-message text to append before resuming"),
            continue_from: str = Form(
                "end", description="Continuation boundary. Use 'end', 'last_user', or a numeric message index."
            ),
            fork: bool = Form(False, description="Clone the run with a new run_id before resuming"),
            regenerate: bool = Form(False, description="Regenerate the last response of this run"),
            replace_original: Optional[bool] = Form(
                None, description="Only valid with regenerate=true. Hide the original response from history"
            ),
            additional_instructions: Optional[str] = Form(
                None, description="Only valid with regenerate=true: extra guidance for the regeneration"
            ),
            session_id: Optional[str] = Form(None, description="Session ID for the paused run"),
            user_id: Optional[str] = Form(None, description="User identifier"),
            stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        ):
            from agno.os.routers.agents.router import agent_continue_response_streamer

            kwargs = await get_request_kwargs(request, continue_remote_agent_run)
            session_id, user_id = _merge_request_state(request, kwargs, session_id, user_id)
            kwargs.pop("session_state", None)

            try:
                tools_data = json.loads(tools) if tools else None
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON in tools field")

            agent = _resolve_agent(agent_id)

            if (session_id is None or session_id == "") and not isinstance(agent, RemoteAgent):
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)

            scoped_user_id = get_scoped_user_id(request)
            if scoped_user_id is not None and not isinstance(agent, RemoteAgent):
                assert session_id
                await verify_run_in_session(
                    agent,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="agents",
                    component_id=agent_id,
                )

            updated_tools = None
            if tools_data:
                try:
                    from agno.models.response import ToolExecution

                    updated_tools = [ToolExecution.from_dict(tool) for tool in tools_data]
                except Exception as e:
                    raise HTTPException(status_code=400, detail=f"Invalid structure or content for tools: {str(e)}")

            auth_token = get_auth_token_from_request(request)
            continue_from_value = _parse_continue_from(continue_from)

            if stream:
                return StreamingResponse(
                    agent_continue_response_streamer(
                        agent,
                        run_id=run_id,
                        updated_tools=updated_tools,
                        input=input,
                        continue_from=continue_from_value,
                        fork=fork,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        session_id=session_id,
                        user_id=user_id,
                        background_tasks=background_tasks,
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
                extra_kwargs: Dict[str, Any] = {}
                if auth_token and isinstance(agent, RemoteAgent):
                    extra_kwargs["auth_token"] = auth_token

                try:
                    run_response_obj = await agent.acontinue_run(  # type: ignore
                        run_id=run_id,
                        updated_tools=updated_tools,
                        input=input,
                        continue_from=continue_from_value,
                        fork=fork,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        session_id=session_id,
                        user_id=user_id,
                        stream=False,
                        background_tasks=background_tasks,
                        **extra_kwargs,
                        **kwargs,
                    )
                    return run_response_obj.to_dict()
                except RunNotFoundError as e:
                    raise HTTPException(status_code=404, detail=str(e))
                except RunNotContinuableError as e:
                    raise HTTPException(status_code=409, detail=str(e))
                except (InputCheckError, ValueError) as e:
                    raise HTTPException(status_code=400, detail=str(e))

        @router.post(
            "/agents/{agent_id}/runs/{run_id}/cancel",
            operation_id="cancel_remote_agent_run",
            response_model_exclude_none=True,
            summary="Cancel Remote Agent Run",
            description="Cancel a currently executing run of a remotely exposed agent.",
            responses=error_responses,
            dependencies=[Depends(require_resource_access("agents", "run", "agent_id"))],
        )
        async def cancel_remote_agent_run(
            request: Request,
            agent_id: str,
            run_id: str,
            session_id: Optional[str] = Query(
                default=None,
                description="Session ID the run belongs to. Required for non-admin JWT users.",
            ),
        ):
            agent = _resolve_agent(agent_id)

            if not callable(getattr(agent, "acancel_run", None)):
                raise HTTPException(status_code=501, detail="This agent does not support cancel_run")

            scoped_user_id = get_scoped_user_id(request)
            if scoped_user_id is not None:
                if not session_id:
                    raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
                await verify_run_in_session(
                    agent,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="agents",
                    component_id=agent_id,
                )

            await agent.acancel_run(run_id=run_id)  # type: ignore[union-attr]
            return JSONResponse(content={}, status_code=200)

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    if teams:

        def _resolve_team(team_id: str) -> Union[Team, RemoteTeam]:
            team = get_team_by_id(team_id=team_id, teams=teams, create_fresh=True)
            if team is None:
                raise HTTPException(status_code=404, detail="Team not found or not exposed for remote execution")
            return team

        @router.get(
            "/teams",
            response_model=List[TeamResponse],
            response_model_exclude_none=True,
            operation_id="get_remote_teams",
            summary="List Remotely Exposed Teams",
            description="List the teams exposed for remote execution through this interface.",
            responses=error_responses,
        )
        async def get_remote_teams(request: Request) -> List[TeamResponse]:
            accessible_teams = _filter_by_access(request, list(teams), "teams")

            responses: List[TeamResponse] = []
            for team in accessible_teams:
                if isinstance(team, RemoteTeam):
                    responses.append(await team.get_team_config())
                else:
                    responses.append(await TeamResponse.from_team(team=team, is_component=False))
            return responses

        @router.get(
            "/teams/{team_id}",
            response_model=TeamResponse,
            response_model_exclude_none=True,
            operation_id="get_remote_team",
            summary="Get Remotely Exposed Team",
            description="Get the configuration of a team exposed for remote execution.",
            responses=error_responses,
            dependencies=[Depends(require_resource_access("teams", "read", "team_id"))],
        )
        async def get_remote_team(team_id: str) -> TeamResponse:
            team = _resolve_team(team_id)
            if isinstance(team, RemoteTeam):
                return await team.get_team_config()
            return await TeamResponse.from_team(team=team)

        @router.post(
            "/teams/{team_id}/runs",
            operation_id="create_remote_team_run",
            response_model_exclude_none=True,
            summary="Create Remote Team Run",
            description=("Execute a remotely exposed team. Supports both streaming (SSE) and non-streaming responses."),
            responses=error_responses,
            dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
        )
        async def create_remote_team_run(
            team_id: str,
            request: Request,
            background_tasks: BackgroundTasks,
            message: str = Form(..., description="The input message or prompt to send to the team"),
            stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
            session_id: Optional[str] = Form(None, description="Session ID for conversation continuity"),
            user_id: Optional[str] = Form(None, description="User identifier"),
            files: Optional[List[UploadFile]] = File(None, description="Files to upload"),
        ):
            from agno.os.routers.teams.router import team_response_streamer

            kwargs = await get_request_kwargs(request, create_remote_team_run)
            session_id, user_id = _merge_request_state(request, kwargs, session_id, user_id)

            team = _resolve_team(team_id)

            if not isinstance(team, RemoteTeam):
                team.store_member_responses = True

            if session_id is None or session_id == "":
                log_debug("Creating new session")
                session_id = str(uuid4())

            base64_images, base64_audios, base64_videos, input_files = _process_upload_files(files)

            base64_images.extend(kwargs.pop("images", None) or [])
            base64_audios.extend(kwargs.pop("audio", None) or [])
            base64_videos.extend(kwargs.pop("videos", None) or [])
            input_files.extend(kwargs.pop("files", None) or [])

            auth_token = get_auth_token_from_request(request)

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
                        files=input_files if input_files else None,
                        background_tasks=background_tasks,
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
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
                        files=input_files if input_files else None,
                        stream=False,
                        background_tasks=background_tasks,
                        **kwargs,
                    )
                    return run_response.to_dict()
                except InputCheckError as e:
                    raise HTTPException(status_code=400, detail=str(e))

        @router.post(
            "/teams/{team_id}/runs/{run_id}/continue",
            operation_id="continue_remote_team_run",
            response_model_exclude_none=True,
            summary="Continue Remote Team Run",
            description="Continue a paused run of a remotely exposed team with updated requirements.",
            responses=error_responses,
            dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
        )
        async def continue_remote_team_run(
            team_id: str,
            run_id: str,
            request: Request,
            background_tasks: BackgroundTasks,
            requirements: str = Form("", description="JSON string of requirement objects with tool results"),
            input: Optional[str] = Form(None, description="Optional new user-message text to append before resuming"),
            continue_from: str = Form(
                "end", description="Continuation boundary. Use 'end', 'last_user', or a numeric message index."
            ),
            fork: bool = Form(False, description="Clone the run with a new run_id before resuming"),
            regenerate: bool = Form(False, description="Regenerate the last response of this run"),
            replace_original: Optional[bool] = Form(
                None, description="Only valid with regenerate=true. Hide the original response from history"
            ),
            additional_instructions: Optional[str] = Form(
                None, description="Only valid with regenerate=true: extra guidance for the regeneration"
            ),
            session_id: Optional[str] = Form(None, description="Session ID for the paused run"),
            user_id: Optional[str] = Form(None, description="User identifier"),
            stream: bool = Form(True, description="Enable streaming responses via Server-Sent Events (SSE)"),
        ):
            from agno.os.routers.teams.router import team_continue_response_streamer

            kwargs = await get_request_kwargs(request, continue_remote_team_run)
            session_id, user_id = _merge_request_state(request, kwargs, session_id, user_id)
            kwargs.pop("session_state", None)

            try:
                requirements_data = json.loads(requirements) if requirements else None
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON in requirements field")

            team = _resolve_team(team_id)

            if not isinstance(team, RemoteTeam):
                team.store_member_responses = True

            if (session_id is None or session_id == "") and not isinstance(team, RemoteTeam):
                raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)

            scoped_user_id = get_scoped_user_id(request)
            if scoped_user_id is not None and not isinstance(team, RemoteTeam):
                assert session_id
                await verify_run_in_session(
                    team,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="teams",
                    component_id=team_id,
                )

            updated_requirements = None
            if requirements_data:
                try:
                    from agno.run.requirement import RunRequirement

                    updated_requirements = [RunRequirement.from_dict(req) for req in requirements_data]
                except Exception as e:
                    raise HTTPException(
                        status_code=400, detail=f"Invalid structure or content for requirements: {str(e)}"
                    )

            auth_token = get_auth_token_from_request(request)
            continue_from_value = _parse_continue_from(continue_from)

            if stream:
                return StreamingResponse(
                    team_continue_response_streamer(
                        team,
                        run_id=run_id,
                        requirements=updated_requirements or [],
                        input=input,
                        continue_from=continue_from_value,
                        fork=fork,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        session_id=session_id,
                        user_id=user_id,
                        background_tasks=background_tasks,
                        auth_token=auth_token,
                        **kwargs,
                    ),
                    media_type="text/event-stream",
                )
            else:
                extra_kwargs: Dict[str, Any] = {}
                if auth_token and isinstance(team, RemoteTeam):
                    extra_kwargs["auth_token"] = auth_token

                try:
                    run_response_obj = await team.acontinue_run(  # type: ignore
                        run_id=run_id,
                        requirements=updated_requirements or [],
                        input=input,
                        continue_from=continue_from_value,
                        fork=fork,
                        regenerate=regenerate,
                        replace_original=replace_original,
                        additional_instructions=additional_instructions,
                        session_id=session_id,
                        user_id=user_id,
                        stream=False,
                        background_tasks=background_tasks,
                        **extra_kwargs,
                        **kwargs,
                    )
                    return run_response_obj.to_dict()
                except RunNotFoundError as e:
                    raise HTTPException(status_code=404, detail=str(e))
                except RunNotContinuableError as e:
                    raise HTTPException(status_code=409, detail=str(e))
                except (InputCheckError, ValueError) as e:
                    raise HTTPException(status_code=400, detail=str(e))

        @router.post(
            "/teams/{team_id}/runs/{run_id}/cancel",
            operation_id="cancel_remote_team_run",
            response_model_exclude_none=True,
            summary="Cancel Remote Team Run",
            description="Cancel a currently executing run of a remotely exposed team.",
            responses=error_responses,
            dependencies=[Depends(require_resource_access("teams", "run", "team_id"))],
        )
        async def cancel_remote_team_run(
            request: Request,
            team_id: str,
            run_id: str,
            session_id: Optional[str] = Query(
                default=None,
                description="Session ID the run belongs to. Required for non-admin JWT users.",
            ),
        ):
            team = _resolve_team(team_id)

            if not callable(getattr(team, "acancel_run", None)):
                raise HTTPException(status_code=501, detail="This team does not support cancel_run")

            scoped_user_id = get_scoped_user_id(request)
            if scoped_user_id is not None:
                if not session_id:
                    raise HTTPException(status_code=400, detail=SESSION_ID_REQUIRED)
                await verify_run_in_session(
                    team,
                    session_id,
                    run_id,
                    scoped_user_id,
                    component_type="teams",
                    component_id=team_id,
                )

            await team.acancel_run(run_id=run_id)
            return JSONResponse(content={}, status_code=200)

    return router
