import logging
import time
from typing import Any, List, Optional, Union, cast
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.os.auth import get_auth_token_from_request, get_authentication_dependency
from agno.os.schema import (
    AgentSessionDetailSchema,
    BadRequestResponse,
    CreateSessionRequest,
    DeleteSessionRequest,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    RunSchema,
    SessionSchema,
    SortOrder,
    TeamRunSchema,
    TeamSessionDetailSchema,
    UnauthenticatedResponse,
    UpdateSessionRequest,
    ValidationErrorResponse,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db
from agno.remote.base import RemoteDb
from agno.session import AgentSession, TeamSession, WorkflowSession

logger = logging.getLogger(__name__)


def get_session_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], settings: AgnoAPISettings = AgnoAPISettings()
) -> APIRouter:
    """Create session router with comprehensive OpenAPI documentation for session management endpoints."""
    session_router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Sessions"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=session_router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]) -> APIRouter:
    @router.get(
        "/sessions",
        response_model=PaginatedResponse[SessionSchema],
        status_code=200,
        operation_id="get_sessions",
        summary="List Sessions",
        description=(
            "Retrieve paginated list of sessions with filtering and sorting options. "
            "Supports filtering by session type (agent, team, workflow), component, user, and name. "
            "Sessions represent conversation histories and execution contexts."
        ),
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Sessions retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "session_example": {
                                "summary": "Example session response",
                                "value": {
                                    "data": [
                                        {
                                            "session_id": "6f6cfbfd-9643-479a-ae47-b8f32eb4d710",
                                            "session_name": "What tools do you have?",
                                            "session_state": {},
                                            "created_at": "2025-09-05T16:02:09Z",
                                            "updated_at": "2025-09-05T16:02:09Z",
                                        }
                                    ]
                                },
                            }
                        }
                    }
                },
            },
            400: {"description": "Invalid session type or filter parameters", "model": BadRequestResponse},
            404: {"description": "Not found", "model": NotFoundResponse},
            422: {"description": "Validation error in query parameters", "model": ValidationErrorResponse},
        },
    )
    async def get_sessions(
        request: Request,
        session_type: SessionType = Query(
            default=SessionType.AGENT,
            alias="type",
            description="Type of sessions to retrieve (agent, team, or workflow)",
        ),
        component_id: Optional[str] = Query(
            default=None, description="Filter sessions by component ID (agent/team/workflow ID)"
        ),
        user_id: Optional[str] = Query(default=None, description="Filter sessions by user ID"),
        session_name: Optional[str] = Query(default=None, description="Filter sessions by name (partial match)"),
        limit: Optional[int] = Query(default=20, description="Number of sessions to return per page", ge=1),
        page: Optional[int] = Query(default=1, description="Page number for pagination", ge=0),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort sessions by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query sessions from"),
        table: Optional[str] = Query(default=None, description="The database table to use"),
    ) -> PaginatedResponse[SessionSchema]:
        try:
            db = await get_db(dbs, db_id, table)
        except Exception as e:
            raise HTTPException(status_code=404, detail=f"{e}")

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_sessions(
                session_type=session_type,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order.value if sort_order else None,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            sessions, total_count = await db.get_sessions(
                session_type=session_type,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )
        else:
            sessions, total_count = db.get_sessions(  # type: ignore
                session_type=session_type,
                component_id=component_id,
                user_id=user_id,
                session_name=session_name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order,
                deserialize=False,
            )

        return PaginatedResponse(
            data=[SessionSchema.from_dict(session) for session in sessions],  # type: ignore
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=total_count,  # type: ignore
                total_pages=(total_count + limit - 1) // limit if limit is not None and limit > 0 else 0,  # type: ignore
            ),
        )

    @router.post(
        "/sessions",
        response_model=Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema],
        status_code=201,
        operation_id="create_session",
        summary="Create New Session",
        description=(
            "Create a new empty session with optional configuration. "
            "Useful for pre-creating sessions with specific session_state, metadata, or other properties "
            "before running any agent/team/workflow interactions. "
            "The session can later be used by providing its session_id in run requests."
        ),
        response_model_exclude_none=True,
        responses={
            201: {
                "description": "Session created successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "agent_session_example": {
                                "summary": "Example created agent session",
                                "value": {
                                    "user_id": "user-123",
                                    "agent_session_id": "new-session-id",
                                    "session_id": "new-session-id",
                                    "session_name": "New Session",
                                    "session_state": {"key": "value"},
                                    "metadata": {"key": "value"},
                                    "agent_id": "agent-1",
                                    "created_at": "2025-10-21T12:00:00Z",
                                    "updated_at": "2025-10-21T12:00:00Z",
                                },
                            }
                        }
                    }
                },
            },
            400: {"description": "Invalid request parameters", "model": BadRequestResponse},
            422: {"description": "Validation error", "model": ValidationErrorResponse},
            500: {"description": "Failed to create session", "model": InternalServerErrorResponse},
        },
    )
    async def create_session(
        request: Request,
        session_type: SessionType = Query(
            default=SessionType.AGENT, alias="type", description="Type of session to create (agent, team, or workflow)"
        ),
        create_session_request: CreateSessionRequest = Body(
            default=CreateSessionRequest(), description="Session configuration data"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to create session in"),
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        db = await get_db(dbs, db_id)

        # Get user_id from request state if available (from auth middleware)
        user_id = create_session_request.user_id
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.create_session(
                session_type=session_type,
                session_id=create_session_request.session_id,
                session_name=create_session_request.session_name,
                session_state=create_session_request.session_state,
                metadata=create_session_request.metadata,
                user_id=user_id,
                agent_id=create_session_request.agent_id,
                team_id=create_session_request.team_id,
                workflow_id=create_session_request.workflow_id,
                db_id=db_id,
                headers=headers,
            )

        # Generate session_id if not provided
        session_id = create_session_request.session_id or str(uuid4())

        # Prepare session_data with session_state and session_name
        session_data: dict[str, Any] = {}
        if create_session_request.session_state is not None:
            session_data["session_state"] = create_session_request.session_state
        if create_session_request.session_name is not None:
            session_data["session_name"] = create_session_request.session_name

        current_time = int(time.time())

        # Create the appropriate session type
        session: Union[AgentSession, TeamSession, WorkflowSession]
        if session_type == SessionType.AGENT:
            session = AgentSession(
                session_id=session_id,
                agent_id=create_session_request.agent_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=create_session_request.metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        elif session_type == SessionType.TEAM:
            session = TeamSession(
                session_id=session_id,
                team_id=create_session_request.team_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=create_session_request.metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        elif session_type == SessionType.WORKFLOW:
            session = WorkflowSession(
                session_id=session_id,
                workflow_id=create_session_request.workflow_id,
                user_id=user_id,
                session_data=session_data if session_data else None,
                metadata=create_session_request.metadata,
                created_at=current_time,
                updated_at=current_time,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Invalid session type: {session_type}")

        # Upsert the session to the database
        try:
            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                created_session = await db.upsert_session(session, deserialize=True)
            else:
                created_session = db.upsert_session(session, deserialize=True)

            if not created_session:
                raise HTTPException(status_code=500, detail="Failed to create session")

            # Return appropriate schema based on session type
            if session_type == SessionType.AGENT:
                return AgentSessionDetailSchema.from_session(created_session)  # type: ignore
            elif session_type == SessionType.TEAM:
                return TeamSessionDetailSchema.from_session(created_session)  # type: ignore
            else:
                return WorkflowSessionDetailSchema.from_session(created_session)  # type: ignore
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

    @router.get(
        "/sessions/{session_id}",
        response_model=Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema],
        status_code=200,
        operation_id="get_session_by_id",
        summary="Get Session by ID",
        description=(
            "Retrieve detailed information about a specific session including metadata, configuration, "
            "and run history. Response schema varies based on session type (agent, team, or workflow)."
        ),
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Session details retrieved successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "agent_session_example": {
                                "summary": "Example agent session response",
                                "value": {
                                    "user_id": "123",
                                    "agent_session_id": "6f6cfbfd-9643-479a-ae47-b8f32eb4d710",
                                    "session_id": "6f6cfbfd-9643-479a-ae47-b8f32eb4d710",
                                    "session_name": "What tools do you have?",
                                    "session_summary": {
                                        "summary": "The user and assistant engaged in a conversation about the tools the agent has available.",
                                        "updated_at": "2025-09-05T18:02:12.269392",
                                    },
                                    "session_state": {},
                                    "agent_id": "basic-agent",
                                    "total_tokens": 160,
                                    "agent_data": {
                                        "name": "Basic Agent",
                                        "agent_id": "basic-agent",
                                        "model": {"provider": "OpenAI", "name": "OpenAIChat", "id": "gpt-4o"},
                                    },
                                    "metrics": {
                                        "input_tokens": 134,
                                        "output_tokens": 26,
                                        "total_tokens": 160,
                                        "audio_input_tokens": 0,
                                        "audio_output_tokens": 0,
                                        "audio_total_tokens": 0,
                                        "cache_read_tokens": 0,
                                        "cache_write_tokens": 0,
                                        "reasoning_tokens": 0,
                                        "timer": None,
                                        "time_to_first_token": None,
                                        "duration": None,
                                        "provider_metrics": None,
                                        "additional_metrics": None,
                                    },
                                    "chat_history": [
                                        {
                                            "content": "<additional_information>\n- Use markdown to format your answers.\n- The current time is 2025-09-05 18:02:09.171627.\n</additional_information>\n\nYou have access to memories from previous interactions with the user that you can use:\n\n<memories_from_previous_interactions>\n- User really likes Digimon and Japan.\n- User really likes Japan.\n- User likes coffee.\n</memories_from_previous_interactions>\n\nNote: this information is from previous interactions and may be updated in this conversation. You should always prefer information from this conversation over the past memories.",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "system",
                                            "created_at": 1757088129,
                                        },
                                        {
                                            "content": "What tools do you have?",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "user",
                                            "created_at": 1757088129,
                                        },
                                        {
                                            "content": "I don't have access to external tools or the internet. However, I can assist you with a wide range of topics by providing information, answering questions, and offering suggestions based on the knowledge I've been trained on. If there's anything specific you need help with, feel free to ask!",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "assistant",
                                            "metrics": {"input_tokens": 134, "output_tokens": 26, "total_tokens": 160},
                                            "created_at": 1757088129,
                                        },
                                    ],
                                    "created_at": "2025-09-05T16:02:09Z",
                                    "updated_at": "2025-09-05T16:02:09Z",
                                },
                            }
                        }
                    }
                },
            },
            404: {"description": "Session not found", "model": NotFoundResponse},
            422: {"description": "Invalid session type", "model": ValidationErrorResponse},
        },
    )
    async def get_session_by_id(
        request: Request,
        session_id: str = Path(description="Session ID to retrieve"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        user_id: Optional[str] = Query(default=None, description="User ID to query session from"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query session from"),
        table: Optional[str] = Query(default=None, description="Table to query session from"),
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_session(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.get_session(session_id=session_id, session_type=session_type, user_id=user_id)
        else:
            session = db.get_session(session_id=session_id, session_type=session_type, user_id=user_id)
        if not session:
            raise HTTPException(
                status_code=404, detail=f"{session_type.value.title()} Session with id '{session_id}' not found"
            )

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session)  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(session)  # type: ignore

    @router.get(
        "/sessions/{session_id}/runs",
        response_model=List[Union[RunSchema, TeamRunSchema, WorkflowRunSchema]],
        status_code=200,
        operation_id="get_session_runs",
        summary="Get Session Runs",
        description=(
            "Retrieve all runs (executions) for a specific session with optional timestamp filtering. "
            "Runs represent individual interactions or executions within a session. "
            "Response schema varies based on session type."
        ),
        response_model_exclude_none=True,
        responses={
            200: {
                "description": "Session runs retrieved successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "completed_run": {
                                "summary": "Example completed run",
                                "value": {
                                    "run_id": "fcdf50f0-7c32-4593-b2ef-68a558774340",
                                    "parent_run_id": "80056af0-c7a5-4d69-b6a2-c3eba9f040e0",
                                    "agent_id": "basic-agent",
                                    "user_id": "",
                                    "run_input": "Which tools do you have access to?",
                                    "content": "I don't have access to external tools or the internet. However, I can assist you with a wide range of topics by providing information, answering questions, and offering suggestions based on the knowledge I've been trained on. If there's anything specific you need help with, feel free to ask!",
                                    "run_response_format": "text",
                                    "reasoning_content": "",
                                    "metrics": {
                                        "input_tokens": 82,
                                        "output_tokens": 56,
                                        "total_tokens": 138,
                                        "time_to_first_token": 0.047505500027909875,
                                        "duration": 4.840060166025069,
                                    },
                                    "messages": [
                                        {
                                            "content": "<additional_information>\n- Use markdown to format your answers.\n- The current time is 2025-09-08 17:52:10.101003.\n</additional_information>\n\nYou have the capability to retain memories from previous interactions with the user, but have not had any interactions with the user yet.",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "system",
                                            "created_at": 1757346730,
                                        },
                                        {
                                            "content": "Which tools do you have access to?",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "user",
                                            "created_at": 1757346730,
                                        },
                                        {
                                            "content": "I don't have access to external tools or the internet. However, I can assist you with a wide range of topics by providing information, answering questions, and offering suggestions based on the knowledge I've been trained on. If there's anything specific you need help with, feel free to ask!",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "assistant",
                                            "metrics": {"input_tokens": 82, "output_tokens": 56, "total_tokens": 138},
                                            "created_at": 1757346730,
                                        },
                                    ],
                                    "tools": None,
                                    "events": [
                                        {
                                            "created_at": 1757346730,
                                            "event": "RunStarted",
                                            "agent_id": "basic-agent",
                                            "agent_name": "Basic Agent",
                                            "run_id": "fcdf50f0-7c32-4593-b2ef-68a558774340",
                                            "session_id": "80056af0-c7a5-4d69-b6a2-c3eba9f040e0",
                                            "model": "gpt-4o",
                                            "model_provider": "OpenAI",
                                        },
                                        {
                                            "created_at": 1757346733,
                                            "event": "MemoryUpdateStarted",
                                            "agent_id": "basic-agent",
                                            "agent_name": "Basic Agent",
                                            "run_id": "fcdf50f0-7c32-4593-b2ef-68a558774340",
                                            "session_id": "80056af0-c7a5-4d69-b6a2-c3eba9f040e0",
                                        },
                                        {
                                            "created_at": 1757346734,
                                            "event": "MemoryUpdateCompleted",
                                            "agent_id": "basic-agent",
                                            "agent_name": "Basic Agent",
                                            "run_id": "fcdf50f0-7c32-4593-b2ef-68a558774340",
                                            "session_id": "80056af0-c7a5-4d69-b6a2-c3eba9f040e0",
                                        },
                                        {
                                            "created_at": 1757346734,
                                            "event": "RunCompleted",
                                            "agent_id": "basic-agent",
                                            "agent_name": "Basic Agent",
                                            "run_id": "fcdf50f0-7c32-4593-b2ef-68a558774340",
                                            "session_id": "80056af0-c7a5-4d69-b6a2-c3eba9f040e0",
                                            "content": "I don't have access to external tools or the internet. However, I can assist you with a wide range of topics by providing information, answering questions, and offering suggestions based on the knowledge I've been trained on. If there's anything specific you need help with, feel free to ask!",
                                            "content_type": "str",
                                            "metrics": {
                                                "input_tokens": 82,
                                                "output_tokens": 56,
                                                "total_tokens": 138,
                                                "time_to_first_token": 0.047505500027909875,
                                                "duration": 4.840060166025069,
                                            },
                                        },
                                    ],
                                    "created_at": "2025-09-08T15:52:10Z",
                                },
                            }
                        }
                    }
                },
            },
            404: {"description": "Session not found or has no runs", "model": NotFoundResponse},
            422: {"description": "Invalid session type", "model": ValidationErrorResponse},
        },
    )
    async def get_session_runs(
        request: Request,
        session_id: str = Path(description="Session ID to get runs from"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        user_id: Optional[str] = Query(default=None, description="User ID to query runs from"),
        created_after: Optional[int] = Query(
            default=None,
            description="Filter runs created after this Unix timestamp (epoch time in seconds)",
        ),
        created_before: Optional[int] = Query(
            default=None,
            description="Filter runs created before this Unix timestamp (epoch time in seconds)",
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to query runs from"),
        table: Optional[str] = Query(default=None, description="Table to query runs from"),
    ) -> List[Union[RunSchema, TeamRunSchema, WorkflowRunSchema]]:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_session_runs(
                session_id=session_id,
                session_type=session_type,
                user_id=user_id,
                created_after=created_after,
                created_before=created_before,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        # Use timestamp filters directly (already in epoch format)
        start_timestamp = created_after
        end_timestamp = created_before

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.get_session(
                session_id=session_id, session_type=session_type, user_id=user_id, deserialize=False
            )
        else:
            session = db.get_session(
                session_id=session_id, session_type=session_type, user_id=user_id, deserialize=False
            )

        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        runs = session.get("runs")  # type: ignore
        if not runs:
            return []

        # Filter runs by timestamp if specified
        # TODO: Move this filtering into the DB layer
        filtered_runs = []
        for run in runs:
            if start_timestamp or end_timestamp:
                run_created_at = run.get("created_at")
                if run_created_at:
                    # created_at is stored as epoch int
                    if start_timestamp and run_created_at < start_timestamp:
                        continue
                    if end_timestamp and run_created_at > end_timestamp:
                        continue

            filtered_runs.append(run)

        if not filtered_runs:
            return []

        run_responses: List[Union[RunSchema, TeamRunSchema, WorkflowRunSchema]] = []

        if session_type == SessionType.AGENT:
            return [RunSchema.from_dict(run) for run in filtered_runs]

        elif session_type == SessionType.TEAM:
            for run in filtered_runs:
                if run.get("agent_id") is not None:
                    run_responses.append(RunSchema.from_dict(run))
                elif run.get("team_id") is not None:
                    run_responses.append(TeamRunSchema.from_dict(run))
            return run_responses

        elif session_type == SessionType.WORKFLOW:
            for run in filtered_runs:
                if run.get("workflow_id") is not None:
                    run_responses.append(WorkflowRunSchema.from_dict(run))
                elif run.get("team_id") is not None:
                    run_responses.append(TeamRunSchema.from_dict(run))
                else:
                    run_responses.append(RunSchema.from_dict(run))
            return run_responses
        else:
            raise HTTPException(status_code=400, detail=f"Invalid session type: {session_type}")

    @router.get(
        "/sessions/{session_id}/runs/{run_id}",
        response_model=Union[RunSchema, TeamRunSchema, WorkflowRunSchema],
        status_code=200,
        operation_id="get_session_run",
        summary="Get Run by ID",
        description=(
            "Retrieve a specific run by its ID from a session. Response schema varies based on the "
            "run type (agent run, team run, or workflow run)."
        ),
        responses={
            200: {
                "description": "Run retrieved successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "agent_run": {
                                "summary": "Example agent run",
                                "value": {
                                    "run_id": "fcdf50f0-7c32-4593-b2ef-68a558774340",
                                    "parent_run_id": "80056af0-c7a5-4d69-b6a2-c3eba9f040e0",
                                    "agent_id": "basic-agent",
                                    "user_id": "user_123",
                                    "run_input": "Which tools do you have access to?",
                                    "content": "I don't have access to external tools.",
                                    "created_at": 1728499200,
                                },
                            }
                        }
                    }
                },
            },
            404: {"description": "Session or run not found", "model": NotFoundResponse},
            422: {"description": "Invalid session type", "model": ValidationErrorResponse},
        },
    )
    async def get_session_run(
        request: Request,
        session_id: str = Path(description="Session ID to get run from"),
        run_id: str = Path(description="Run ID to retrieve"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        user_id: Optional[str] = Query(default=None, description="User ID to query run from"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query run from"),
        table: Optional[str] = Query(default=None, description="Table to query run from"),
    ) -> Union[RunSchema, TeamRunSchema, WorkflowRunSchema]:
        db = await get_db(dbs, db_id)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_session_run(
                session_id=session_id,
                run_id=run_id,
                session_type=session_type,
                user_id=user_id,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.get_session(
                session_id=session_id, session_type=session_type, user_id=user_id, deserialize=False
            )
        else:
            session = db.get_session(
                session_id=session_id, session_type=session_type, user_id=user_id, deserialize=False
            )

        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        runs = session.get("runs")  # type: ignore
        if not runs:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} has no runs")

        # Find the specific run
        # TODO: Move this filtering into the DB layer
        target_run = None
        for run in runs:
            if run.get("run_id") == run_id:
                target_run = run
                break

        if not target_run:
            raise HTTPException(status_code=404, detail=f"Run with ID {run_id} not found in session {session_id}")

        # Return the appropriate schema based on run type
        if target_run.get("workflow_id") is not None:
            return WorkflowRunSchema.from_dict(target_run)
        elif target_run.get("team_id") is not None:
            return TeamRunSchema.from_dict(target_run)
        else:
            return RunSchema.from_dict(target_run)

    @router.delete(
        "/sessions/{session_id}",
        status_code=204,
        operation_id="delete_session",
        summary="Delete Session",
        description=(
            "Permanently delete a specific session and all its associated runs. "
            "This action cannot be undone and will remove all conversation history."
        ),
        responses={
            204: {},
            500: {"description": "Failed to delete session", "model": InternalServerErrorResponse},
        },
    )
    async def delete_session(
        request: Request,
        session_id: str = Path(description="Session ID to delete"),
        user_id: Optional[str] = Query(default=None, description="User ID to scope deletion to"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
        table: Optional[str] = Query(default=None, description="Table to use for deletion"),
    ) -> None:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            await db.delete_session(session_id=session_id, db_id=db_id, table=table, headers=headers, user_id=user_id)
            return

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_session(session_id=session_id, user_id=user_id)
        else:
            db.delete_session(session_id=session_id, user_id=user_id)

    @router.delete(
        "/sessions",
        status_code=204,
        operation_id="delete_sessions",
        summary="Delete Multiple Sessions",
        description=(
            "Delete multiple sessions by their IDs in a single operation. "
            "This action cannot be undone and will permanently remove all specified sessions and their runs."
        ),
        responses={
            204: {"description": "Sessions deleted successfully"},
            400: {
                "description": "Invalid request - session IDs and types length mismatch",
                "model": BadRequestResponse,
            },
            500: {"description": "Failed to delete sessions", "model": InternalServerErrorResponse},
        },
    )
    async def delete_sessions(
        http_request: Request,
        request: DeleteSessionRequest,
        user_id: Optional[str] = Query(default=None, description="User ID to scope deletion to"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
        table: Optional[str] = Query(default=None, description="Table to use for deletion"),
    ) -> None:
        if len(request.session_ids) != len(request.session_types):
            raise HTTPException(status_code=400, detail="Session IDs and session types must have the same length")

        db = await get_db(dbs, db_id, table)

        if hasattr(http_request.state, "user_id") and http_request.state.user_id is not None:
            user_id = http_request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(http_request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            await db.delete_sessions(
                session_ids=request.session_ids,
                session_types=request.session_types,
                db_id=db_id,
                table=table,
                headers=headers,
                user_id=user_id,
            )
            return

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_sessions(session_ids=request.session_ids, user_id=user_id)
        else:
            db.delete_sessions(session_ids=request.session_ids, user_id=user_id)

    @router.post(
        "/sessions/{session_id}/rename",
        response_model=Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema],
        status_code=200,
        operation_id="rename_session",
        summary="Rename Session",
        description=(
            "Update the name of an existing session. Useful for organizing and categorizing "
            "sessions with meaningful names for better identification and management."
        ),
        responses={
            200: {
                "description": "Session renamed successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "agent_session_example": {
                                "summary": "Example agent session response",
                                "value": {
                                    "user_id": "123",
                                    "agent_session_id": "6f6cfbfd-9643-479a-ae47-b8f32eb4d710",
                                    "session_id": "6f6cfbfd-9643-479a-ae47-b8f32eb4d710",
                                    "session_name": "What tools do you have?",
                                    "session_summary": {
                                        "summary": "The user and assistant engaged in a conversation about the tools the agent has available.",
                                        "updated_at": "2025-09-05T18:02:12.269392",
                                    },
                                    "session_state": {},
                                    "agent_id": "basic-agent",
                                    "total_tokens": 160,
                                    "agent_data": {
                                        "name": "Basic Agent",
                                        "agent_id": "basic-agent",
                                        "model": {"provider": "OpenAI", "name": "OpenAIChat", "id": "gpt-4o"},
                                    },
                                    "metrics": {
                                        "input_tokens": 134,
                                        "output_tokens": 26,
                                        "total_tokens": 160,
                                        "audio_input_tokens": 0,
                                        "audio_output_tokens": 0,
                                        "audio_total_tokens": 0,
                                        "cache_read_tokens": 0,
                                        "cache_write_tokens": 0,
                                        "reasoning_tokens": 0,
                                        "timer": None,
                                        "time_to_first_token": None,
                                        "duration": None,
                                        "provider_metrics": None,
                                        "additional_metrics": None,
                                    },
                                    "chat_history": [
                                        {
                                            "content": "<additional_information>\n- Use markdown to format your answers.\n- The current time is 2025-09-05 18:02:09.171627.\n</additional_information>\n\nYou have access to memories from previous interactions with the user that you can use:\n\n<memories_from_previous_interactions>\n- User really likes Digimon and Japan.\n- User really likes Japan.\n- User likes coffee.\n</memories_from_previous_interactions>\n\nNote: this information is from previous interactions and may be updated in this conversation. You should always prefer information from this conversation over the past memories.",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "system",
                                            "created_at": 1757088129,
                                        },
                                        {
                                            "content": "What tools do you have?",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "user",
                                            "created_at": 1757088129,
                                        },
                                        {
                                            "content": "I don't have access to external tools or the internet. However, I can assist you with a wide range of topics by providing information, answering questions, and offering suggestions based on the knowledge I've been trained on. If there's anything specific you need help with, feel free to ask!",
                                            "from_history": False,
                                            "stop_after_tool_call": False,
                                            "role": "assistant",
                                            "metrics": {"input_tokens": 134, "output_tokens": 26, "total_tokens": 160},
                                            "created_at": 1757088129,
                                        },
                                    ],
                                    "created_at": "2025-09-05T16:02:09Z",
                                    "updated_at": "2025-09-05T16:02:09Z",
                                },
                            }
                        }
                    }
                },
            },
            400: {"description": "Invalid session name", "model": BadRequestResponse},
            404: {"description": "Session not found", "model": NotFoundResponse},
            422: {"description": "Invalid session type or validation error", "model": ValidationErrorResponse},
        },
    )
    async def rename_session(
        request: Request,
        session_id: str = Path(description="Session ID to rename"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        session_name: str = Body(embed=True, description="New name for the session"),
        user_id: Optional[str] = Query(default=None, description="User ID to scope rename to"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for rename operation"),
        table: Optional[str] = Query(default=None, description="Table to use for rename operation"),
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        db = await get_db(dbs, db_id, table)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.rename_session(
                session_id=session_id,
                session_name=session_name,
                session_type=session_type,
                db_id=db_id,
                table=table,
                headers=headers,
                user_id=user_id,
            )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.rename_session(
                session_id=session_id, session_type=session_type, session_name=session_name, user_id=user_id
            )
        else:
            session = db.rename_session(
                session_id=session_id, session_type=session_type, session_name=session_name, user_id=user_id
            )
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with id '{session_id}' not found")

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session)  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(session)  # type: ignore

    @router.patch(
        "/sessions/{session_id}",
        response_model=Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema],
        status_code=200,
        operation_id="update_session",
        summary="Update Session",
        description=(
            "Update session properties such as session_name, session_state, metadata, or summary. "
            "Use this endpoint to modify the session name, update state, add metadata, or update the session summary."
        ),
        responses={
            200: {
                "description": "Session updated successfully",
                "content": {
                    "application/json": {
                        "examples": {
                            "update_summary": {
                                "summary": "Update session summary",
                                "value": {
                                    "summary": {
                                        "summary": "The user discussed project planning with the agent.",
                                        "updated_at": "2025-10-21T14:30:00Z",
                                    }
                                },
                            },
                            "update_metadata": {
                                "summary": "Update session metadata",
                                "value": {
                                    "metadata": {
                                        "tags": ["planning", "project"],
                                        "priority": "high",
                                    }
                                },
                            },
                            "update_session_name": {
                                "summary": "Update session name",
                                "value": {"session_name": "Updated Session Name"},
                            },
                            "update_session_state": {
                                "summary": "Update session state",
                                "value": {
                                    "session_state": {
                                        "step": "completed",
                                        "context": "Project planning finished",
                                        "progress": 100,
                                    }
                                },
                            },
                        }
                    }
                },
            },
            404: {"description": "Session not found", "model": NotFoundResponse},
            422: {"description": "Invalid request", "model": ValidationErrorResponse},
            500: {"description": "Failed to update session", "model": InternalServerErrorResponse},
        },
    )
    async def update_session(
        request: Request,
        session_id: str = Path(description="Session ID to update"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        update_data: UpdateSessionRequest = Body(description="Session update data"),
        user_id: Optional[str] = Query(default=None, description="User ID"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for update operation"),
        table: Optional[str] = Query(default=None, description="Table to use for update operation"),
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        db = await get_db(dbs, db_id)

        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.update_session(
                session_id=session_id,
                session_type=session_type,
                session_name=update_data.session_name,
                session_state=update_data.session_state,
                metadata=update_data.metadata,
                summary=update_data.summary,
                user_id=user_id,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        # Get the existing session
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            existing_session = await db.get_session(
                session_id=session_id, session_type=session_type, user_id=user_id, deserialize=True
            )
        else:
            existing_session = db.get_session(
                session_id=session_id, session_type=session_type, user_id=user_id, deserialize=True
            )

        if not existing_session:
            raise HTTPException(status_code=404, detail=f"Session with id '{session_id}' not found")

        # Update session properties
        # Handle session_name - stored in session_data
        if update_data.session_name is not None:
            if existing_session.session_data is None:  # type: ignore
                existing_session.session_data = {}  # type: ignore
            existing_session.session_data["session_name"] = update_data.session_name  # type: ignore

        # Handle session_state - stored in session_data
        if update_data.session_state is not None:
            if existing_session.session_data is None:  # type: ignore
                existing_session.session_data = {}  # type: ignore
            existing_session.session_data["session_state"] = update_data.session_state  # type: ignore

        if update_data.metadata is not None:
            existing_session.metadata = update_data.metadata  # type: ignore

        if update_data.summary is not None:
            from agno.session.summary import SessionSummary

            existing_session.summary = SessionSummary.from_dict(update_data.summary)  # type: ignore

        # Upsert the updated session
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            updated_session = await db.upsert_session(existing_session, deserialize=True)  # type: ignore
        else:
            updated_session = db.upsert_session(existing_session, deserialize=True)  # type: ignore

        if not updated_session:
            raise HTTPException(status_code=500, detail="Failed to update session")

        # Return appropriate schema based on session type
        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(updated_session)  # type: ignore
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(updated_session)  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(updated_session)  # type: ignore

    return router
