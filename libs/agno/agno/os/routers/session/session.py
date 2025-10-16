import logging
from typing import List, Optional, Union, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request

from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    AgentSessionDetailSchema,
    BadRequestResponse,
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
    ValidationErrorResponse,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db

logger = logging.getLogger(__name__)


def get_session_router(
    dbs: dict[str, Union[BaseDb, AsyncBaseDb]], settings: AgnoAPISettings = AgnoAPISettings()
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


def attach_routes(router: APIRouter, dbs: dict[str, Union[BaseDb, AsyncBaseDb]]) -> APIRouter:
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
        limit: Optional[int] = Query(default=20, description="Number of sessions to return per page"),
        page: Optional[int] = Query(default=1, description="Page number for pagination"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort sessions by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="Database ID to query sessions from"),
    ) -> PaginatedResponse[SessionSchema]:
        db = get_db(dbs, db_id)

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

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
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        db = get_db(dbs, db_id)

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

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
            "Retrieve all runs (executions) for a specific session. Runs represent individual "
            "interactions or executions within a session. Response schema varies based on session type."
        ),
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
        db_id: Optional[str] = Query(default=None, description="Database ID to query runs from"),
    ) -> List[Union[RunSchema, TeamRunSchema, WorkflowRunSchema]]:
        db = get_db(dbs, db_id)

        if hasattr(request.state, "user_id"):
            user_id = request.state.user_id

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

        run_responses: List[Union[RunSchema, TeamRunSchema, WorkflowRunSchema]] = []

        if session_type == SessionType.AGENT:
            return [RunSchema.from_dict(run) for run in runs]

        elif session_type == SessionType.TEAM:
            for run in runs:
                if run.get("agent_id") is not None:
                    run_responses.append(RunSchema.from_dict(run))
                elif run.get("team_id") is not None:
                    run_responses.append(TeamRunSchema.from_dict(run))
            return run_responses

        elif session_type == SessionType.WORKFLOW:
            for run in runs:
                if run.get("workflow_id") is not None:
                    run_responses.append(WorkflowRunSchema.from_dict(run))
                elif run.get("team_id") is not None:
                    run_responses.append(TeamRunSchema.from_dict(run))
                else:
                    run_responses.append(RunSchema.from_dict(run))
            return run_responses
        else:
            raise HTTPException(status_code=400, detail=f"Invalid session type: {session_type}")

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
        session_id: str = Path(description="Session ID to delete"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
    ) -> None:
        db = get_db(dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_session(session_id=session_id)
        else:
            db.delete_session(session_id=session_id)

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
        request: DeleteSessionRequest,
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Default session type filter", alias="type"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
    ) -> None:
        if len(request.session_ids) != len(request.session_types):
            raise HTTPException(status_code=400, detail="Session IDs and session types must have the same length")

        db = get_db(dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_sessions(session_ids=request.session_ids)
        else:
            db.delete_sessions(session_ids=request.session_ids)

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
        session_id: str = Path(description="Session ID to rename"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        session_name: str = Body(embed=True, description="New name for the session"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for rename operation"),
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        db = get_db(dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            session = await db.rename_session(
                session_id=session_id, session_type=session_type, session_name=session_name
            )
        else:
            session = db.rename_session(session_id=session_id, session_type=session_type, session_name=session_name)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with id '{session_id}' not found")

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session)  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(session)  # type: ignore

    return router
