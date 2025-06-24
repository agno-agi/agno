from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException, Path, Query

from agno.os.connectors.session.schemas import (
    AgentSessionDetailSchema,
    RunSchema,
    SessionSchema,
    TeamRunSchema,
    TeamSessionDetailSchema,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
)
from agno.os.connectors.utils import PaginatedResponse, PaginationInfo, SortOrder
from agno.db.base import BaseDb, SessionType


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/sessions", response_model=PaginatedResponse[SessionSchema], status_code=200)
    async def get_sessions(
        session_type: SessionType = Query(default=SessionType.AGENT, alias="type"),
        component_id: Optional[str] = Query(default=None, description="Filter sessions by component ID"),
        limit: Optional[int] = Query(default=20, description="Number of sessions to return"),
        page: Optional[int] = Query(default=0, description="Page number"),
        sort_by: Optional[str] = Query(default=None, description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default=None, description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[SessionSchema]:
        sessions, total_count = db.get_sessions_raw(
            session_type=session_type,
            component_id=component_id,
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
        )

        return PaginatedResponse(
            data=[SessionSchema.from_dict(session) for session in sessions],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=total_count,
                total_pages=total_count // limit if limit is not None and limit > 0 else 0,
            ),
        )

    @router.get(
        "/sessions/{session_id}",
        response_model=Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema],
        status_code=200,
    )
    async def get_session_by_id(
        session_id: str = Path(...),
        session_type: SessionType = Query(default=SessionType.AGENT, description="Session type filter", alias="type"),
    ) -> Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema]:
        session = db.get_session(session_id=session_id, session_type=session_type)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with id '{session_id}' not found")

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.WORKFLOW:
            return WorkflowSessionDetailSchema.from_session(session)  # type: ignore

    @router.get(
        "/sessions/{session_id}/runs", response_model=Union[List[RunSchema], List[TeamRunSchema]], status_code=200
    )
    async def get_session_runs(
        session_id: str = Path(..., description="Session ID", alias="session_id"),
        session_type: SessionType = Query(default=SessionType.AGENT, description="Session type filter", alias="type"),
    ) -> Union[List[RunSchema], List[TeamRunSchema]]:
        runs = db.get_runs_raw(session_id=session_id, session_type=session_type)
        if not runs:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} has no runs")

        if session_type == SessionType.AGENT:
            return [RunSchema.from_dict(run) for run in runs]  # type: ignore
        elif session_type == SessionType.TEAM:
            return [TeamRunSchema.from_dict(run) for run in runs]  # type: ignore
        elif session_type == SessionType.WORKFLOW:
            return [WorkflowRunSchema.from_dict(run) for run in runs]  # type: ignore

    return router
