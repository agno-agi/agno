from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException, Path, Query

from agno.app.agno_api.managers.session.schemas import (
    AgentSessionDetailSchema,
    RunSchema,
    SessionSchema,
    TeamRunSchema,
    TeamSessionDetailSchema,
    WorkflowRunSchema,
    WorkflowSessionDetailSchema,
)
from agno.db.base import BaseDb, SessionType


def attach_sync_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/sessions", response_model=List[SessionSchema], status_code=200)
    def get_sessions(
        session_type: SessionType = Query(default=SessionType.AGENT, alias="type"),
        component_id: Optional[str] = Query(default=None, description="Component (Agent, Team, Workflow) ID"),
        limit: Optional[int] = Query(default=20, description="Number of sessions to return"),
        offset: Optional[int] = Query(default=0, description="Number of sessions to skip"),
    ) -> List[SessionSchema]:
        sessions = db.get_sessions(session_type=session_type, component_id=component_id, limit=limit, offset=offset)
        return [SessionSchema.from_session(session) for session in sessions]

    @router.get(
        "/sessions/{session_id}",
        response_model=Union[AgentSessionDetailSchema, TeamSessionDetailSchema, WorkflowSessionDetailSchema],
        status_code=200,
    )
    def get_session_by_id(
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

    @router.get("/sessions/{session_id}/runs", response_model=List[RunSchema], status_code=200)
    def get_session_runs(
        session_id: str = Path(..., description="Session ID", alias="session-id"),
        session_type: SessionType = Query(default=SessionType.AGENT, description="Session type filter", alias="type"),
    ) -> List[RunSchema]:
        session = db.get_session(session_id=session_id, session_type=session_type)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        runs = db.get_runs(session_id=session_id, session_type=session_type)
        if not runs:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} has no runs")

        if session_type == SessionType.AGENT:
            return [RunSchema.from_run_response(run) for run in runs]  # type: ignore
        elif session_type == SessionType.TEAM:
            return [TeamRunSchema.from_team_run_response(run) for run in runs]  # type: ignore
        elif session_type == SessionType.WORKFLOW:
            return [WorkflowRunSchema.from_workflow_run_response(run) for run in runs]  # type: ignore

    return router
