from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException, Path, Query

from agno.app.agno_api.managers.storage.schemas import (
    AgentSessionDetailSchema,
    RunSchema,
    SessionSchema,
    TeamSessionDetailSchema,
    WorkflowSessionDetailSchema,
)
from agno.db.base import SessionType
from agno.db.base import Storage as StorageBase


def attach_sync_routes(router: APIRouter, storage: StorageBase) -> APIRouter:
    @router.get("/sessions", response_model=List[SessionSchema], status_code=200)
    def get_sessions(session_type: Optional[SessionType] = Query(None, alias="type")) -> List[SessionSchema]:
        if session_type is not None:
            sessions = storage.get_all_sessions(session_type=session_type)
        else:
            sessions = storage.get_all_sessions()

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
        session = storage.read_session(session_id=session_id, session_type=session_type)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        if session_type == SessionType.AGENT:
            return AgentSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.TEAM:
            return TeamSessionDetailSchema.from_session(session)  # type: ignore
        elif session_type == SessionType.WORKFLOW:
            return WorkflowSessionDetailSchema.from_session(session)  # type: ignore

    @router.get("/sessions/{session_id}/runs", response_model=List[RunSchema], status_code=200)
    def get_session_runs(
        session_id: str = Path(..., description="Session ID", alias="session-id"),
        session_type: Optional[SessionType] = Query(None, description="Session type filter", alias="type"),
    ) -> List[RunSchema]:
        session = storage.read_session(session_id=session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session with ID {session_id} not found")

        runs = storage.get_all_runs(session_id=session_id)

        return runs

    return router
