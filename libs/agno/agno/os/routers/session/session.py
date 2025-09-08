import logging
from typing import List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from agno.db.base import BaseDb, SessionType
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


def get_session_router(dbs: dict[str, BaseDb], settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
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


def attach_routes(router: APIRouter, dbs: dict[str, BaseDb]) -> APIRouter:
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
                            "data": [
                                {
                                    "session_id": "sess-123",
                                    "session_name": "Customer Support Chat",
                                    "session_type": "agent",
                                    "component_id": "agent-456",
                                    "user_id": "user-789",
                                    "created_at": "2024-01-15T10:30:00Z",
                                    "updated_at": "2024-01-15T11:45:00Z",
                                    "run_count": 8,
                                    "last_message": "Thank you for your help!",
                                },
                                {
                                    "session_id": "sess-124",
                                    "session_name": "Technical Planning Session",
                                    "session_type": "team",
                                    "component_id": "team-789",
                                    "user_id": "user-123",
                                    "created_at": "2024-01-14T14:20:00Z",
                                    "updated_at": "2024-01-15T09:30:00Z",
                                    "run_count": 15,
                                    "last_message": "Let's proceed with the implementation",
                                },
                            ],
                            "meta": {"page": 1, "limit": 20, "total_count": 67, "total_pages": 4},
                        }
                    }
                },
            },
            400: {"description": "Invalid session type or filter parameters", "model": BadRequestResponse},
            422: {"description": "Validation error in query parameters", "model": ValidationErrorResponse},
        },
    )
    async def get_sessions(
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
        sessions, total_count = db.get_sessions(
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
                            "agent_session": {
                                "summary": "Agent Session Details",
                                "value": {
                                    "session_id": "sess-123",
                                    "session_name": "Customer Support Chat",
                                    "session_type": "agent",
                                    "agent_id": "agent-456",
                                    "user_id": "user-789",
                                    "agent_data": {
                                        "name": "Support Assistant",
                                        "model": "gpt-4",
                                        "instructions": "Help customers with their inquiries",
                                    },
                                    "created_at": "2024-01-15T10:30:00Z",
                                    "updated_at": "2024-01-15T11:45:00Z",
                                    "run_count": 8,
                                    "runs": [
                                        {
                                            "run_id": "run-001",
                                            "message": "How can I reset my password?",
                                            "response": "I'll help you reset your password...",
                                            "created_at": "2024-01-15T10:31:00Z",
                                        }
                                    ],
                                },
                            },
                            "team_session": {
                                "summary": "Team Session Details",
                                "value": {
                                    "session_id": "sess-124",
                                    "session_name": "Technical Planning Session",
                                    "session_type": "team",
                                    "team_id": "team-789",
                                    "user_id": "user-123",
                                    "team_data": {
                                        "name": "Engineering Team",
                                        "agents": ["architect", "developer", "reviewer"],
                                    },
                                    "created_at": "2024-01-14T14:20:00Z",
                                    "updated_at": "2024-01-15T09:30:00Z",
                                    "run_count": 15,
                                },
                            },
                        }
                    }
                },
            },
            404: {"description": "Session not found", "model": NotFoundResponse},
            422: {"description": "Invalid session type", "model": ValidationErrorResponse},
        },
    )
    async def get_session_by_id(
        session_id: str = Path(description="Session ID to retrieve"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to query session from"),
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        db = get_db(dbs, db_id)
        session = db.get_session(session_id=session_id, session_type=session_type)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with id '{session_id}' not found")

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session)  # type: ignore
        else:
            return WorkflowSessionDetailSchema.from_session(session)  # type: ignore

    @router.get(
        "/sessions/{session_id}/runs",
        response_model=Union[List[RunSchema], List[TeamRunSchema], List[WorkflowRunSchema]],
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
                            "agent_runs": {
                                "summary": "Agent Session Runs",
                                "value": [
                                    {
                                        "run_id": "run-001",
                                        "session_id": "sess-123",
                                        "message": "How can I reset my password?",
                                        "response": "I'll help you reset your password. Please follow these steps...",
                                        "model_used": "gpt-4",
                                        "tokens_consumed": 150,
                                        "response_time": 1.2,
                                        "created_at": "2024-01-15T10:31:00Z",
                                    },
                                    {
                                        "run_id": "run-002",
                                        "session_id": "sess-123",
                                        "message": "Thank you, that worked!",
                                        "response": "You're welcome! Is there anything else I can help you with?",
                                        "model_used": "gpt-4",
                                        "tokens_consumed": 75,
                                        "response_time": 0.8,
                                        "created_at": "2024-01-15T10:35:00Z",
                                    },
                                ],
                            },
                            "team_runs": {
                                "summary": "Team Session Runs",
                                "value": [
                                    {
                                        "run_id": "run-003",
                                        "session_id": "sess-124",
                                        "task": "Design system architecture",
                                        "agents_involved": ["architect", "developer"],
                                        "result": "Proposed microservices architecture with API gateway",
                                        "execution_time": 45.5,
                                        "created_at": "2024-01-14T14:25:00Z",
                                    }
                                ],
                            },
                        }
                    }
                },
            },
            404: {"description": "Session not found or has no runs", "model": NotFoundResponse},
            422: {"description": "Invalid session type", "model": ValidationErrorResponse},
        },
    )
    async def get_session_runs(
        session_id: str = Path(description="Session ID to get runs from"),
        session_type: SessionType = Query(
            default=SessionType.AGENT, description="Session type (agent, team, or workflow)", alias="type"
        ),
        db_id: Optional[str] = Query(default=None, description="Database ID to query runs from"),
    ) -> Union[List[RunSchema], List[TeamRunSchema], List[WorkflowRunSchema]]:
        db = get_db(dbs, db_id)
        session = db.get_session(session_id=session_id, session_type=session_type, deserialize=False)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        runs = session.get("runs")  # type: ignore
        if not runs:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} has no runs")

        if session_type == SessionType.AGENT:
            return [RunSchema.from_dict(run) for run in runs]

        elif session_type == SessionType.TEAM:
            return [TeamRunSchema.from_dict(run) for run in runs]

        elif session_type == SessionType.WORKFLOW:
            return [WorkflowRunSchema.from_dict(run) for run in runs]

        else:
            return [RunSchema.from_dict(run) for run in runs]

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
            204: {"description": "Session deleted successfully"},
            404: {"description": "Session not found", "model": NotFoundResponse},
            500: {"description": "Failed to delete session", "model": InternalServerErrorResponse},
        },
    )
    async def delete_session(
        session_id: str = Path(description="Session ID to delete"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
    ) -> None:
        db = get_db(dbs, db_id)
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
                            "agent_session": {
                                "summary": "Renamed Agent Session",
                                "value": {
                                    "session_id": "sess-123",
                                    "session_name": "Updated Customer Support Chat",
                                    "session_type": "agent",
                                    "agent_id": "agent-456",
                                    "user_id": "user-789",
                                    "created_at": "2024-01-15T10:30:00Z",
                                    "updated_at": "2024-01-15T12:00:00Z",
                                    "run_count": 8,
                                },
                            },
                            "team_session": {
                                "summary": "Renamed Team Session",
                                "value": {
                                    "session_id": "sess-124",
                                    "session_name": "Updated Technical Planning Session",
                                    "session_type": "team",
                                    "team_id": "team-789",
                                    "user_id": "user-123",
                                    "created_at": "2024-01-14T14:20:00Z",
                                    "updated_at": "2024-01-15T10:15:00Z",
                                    "run_count": 15,
                                },
                            },
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
