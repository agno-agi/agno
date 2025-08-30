import logging
from typing import List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from agno.db.base import BaseDb, SessionType
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    AgentSessionDetailSchema,
    DeleteSessionRequest,
    PaginatedResponse,
    PaginationInfo,
    RunSchema,
    SessionSchema,
    SortOrder,
    TeamRunSchema,
    TeamSessionDetailSchema,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db

logger = logging.getLogger(__name__)


def get_session_router(dbs: dict[str, BaseDb], settings: AgnoAPISettings = AgnoAPISettings()) -> APIRouter:
    session_router = APIRouter(dependencies=[Depends(get_authentication_dependency(settings))], tags=["Sessions"])
    return attach_routes(router=session_router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, BaseDb]) -> APIRouter:
    @router.get("/sessions", response_model=PaginatedResponse[SessionSchema], status_code=200)
    async def get_sessions(
        session_type: SessionType = Query(default=SessionType.AGENT, alias="type"),
        component_id: Optional[str] = Query(default=None, description="Filter sessions by component ID"),
        user_id: Optional[str] = Query(default=None, description="Filter sessions by user ID"),
        session_name: Optional[str] = Query(default=None, description="Filter sessions by name"),
        limit: Optional[int] = Query(default=20, description="Number of sessions to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
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
    )
    async def get_session_by_id(
        session_id: str = Path(...),
        session_type: SessionType = Query(default=SessionType.AGENT, description="Session type filter", alias="type"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
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
    )
    async def get_session_runs(
        session_id: str = Path(..., description="Session ID", alias="session_id"),
        session_type: SessionType = Query(default=SessionType.AGENT, description="Session type filter", alias="type"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
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

    @router.delete("/sessions/{session_id}", status_code=204)
    async def delete_session(
        session_id: str = Path(...),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> None:
        db = get_db(dbs, db_id)
        db.delete_session(session_id=session_id)

    @router.delete("/sessions", status_code=204)
    async def delete_sessions(
        request: DeleteSessionRequest,
        session_type: SessionType = Query(default=SessionType.AGENT, description="Session type filter", alias="type"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> None:
        if len(request.session_ids) != len(request.session_types):
            raise HTTPException(status_code=400, detail="Session IDs and session types must have the same length")

        db = get_db(dbs, db_id)
        db.delete_sessions(session_ids=request.session_ids)

    @router.post(
        "/sessions/{session_id}/rename",
        response_model=Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema],
    )
    async def rename_session(
        session_id: str = Path(...),
        session_type: SessionType = Query(default=SessionType.AGENT, description="Session type filter", alias="type"),
        session_name: str = Body(embed=True),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
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
