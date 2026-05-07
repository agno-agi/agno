"""Learnings API router -- CRUD over the agno_learnings table."""

import logging
from typing import Optional, Union, cast
from uuid import uuid4

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.routers.learnings.schema import LearningCreate, LearningResponse, LearningUpdate
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_db
from agno.remote.base import RemoteDb

logger = logging.getLogger(__name__)


def get_learnings_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    settings: AgnoAPISettings = AgnoAPISettings(),
    **kwargs,
) -> APIRouter:
    """Factory that creates and returns the learnings router."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Learnings"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return _attach_routes(router=router, dbs=dbs)


def _attach_routes(router: APIRouter, dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]) -> APIRouter:
    @router.get(
        "/learnings",
        response_model=PaginatedResponse[LearningResponse],
        operation_id="list_learnings",
        summary="List Learnings",
        description=(
            "List learning records with pagination and optional filters. When the request is "
            "authenticated with a JWT, results are scoped to the JWT subject's user_id."
        ),
    )
    async def list_learnings(
        request: Request,
        learning_type: Optional[str] = Query(None, description="Filter by learning type"),
        user_id: Optional[str] = Query(None, description="Filter by user ID"),
        agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
        team_id: Optional[str] = Query(None, description="Filter by team ID"),
        session_id: Optional[str] = Query(None, description="Filter by session ID"),
        namespace: Optional[str] = Query(None, description="Filter by namespace"),
        entity_id: Optional[str] = Query(None, description="Filter by entity ID"),
        entity_type: Optional[str] = Query(None, description="Filter by entity type"),
        limit: int = Query(100, ge=1, le=1000, description="Page size"),
        page: int = Query(1, ge=1, description="1-indexed page number"),
        db_id: Optional[str] = Query(None, description="Database ID to query"),
    ) -> PaginatedResponse[LearningResponse]:
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            user_id = request.state.user_id

        db = await get_db(dbs, db_id)

        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Learnings endpoints not supported on remote DBs")

        try:
            if isinstance(db, AsyncBaseDb):
                records, total_count = await db.list_learnings(
                    learning_type=learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    limit=limit,
                    page=page,
                )
            else:
                records, total_count = cast(BaseDb, db).list_learnings(
                    learning_type=learning_type,
                    user_id=user_id,
                    agent_id=agent_id,
                    team_id=team_id,
                    session_id=session_id,
                    namespace=namespace,
                    entity_id=entity_id,
                    entity_type=entity_type,
                    limit=limit,
                    page=page,
                )
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Learnings not supported by the configured database")

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=[LearningResponse.model_validate(r) for r in records],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.post(
        "/learnings",
        response_model=LearningResponse,
        status_code=201,
        operation_id="create_learning",
        summary="Create Learning",
        description=(
            "Create a new learning record. When the request is authenticated with a JWT, "
            "the user_id field is bound to the JWT subject and any provided value is overridden."
        ),
    )
    async def create_learning(
        request: Request,
        body: LearningCreate,
        db_id: Optional[str] = Query(None, description="Database ID to use"),
    ) -> LearningResponse:
        if hasattr(request.state, "user_id") and request.state.user_id is not None:
            body.user_id = request.state.user_id

        db = await get_db(dbs, db_id)

        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Learnings endpoints not supported on remote DBs")

        learning_id = str(uuid4())
        try:
            if isinstance(db, AsyncBaseDb):
                await db.upsert_learning(
                    id=learning_id,
                    learning_type=body.learning_type,
                    content=body.content,
                    user_id=body.user_id,
                    agent_id=body.agent_id,
                    team_id=body.team_id,
                    session_id=body.session_id,
                    namespace=body.namespace,
                    entity_id=body.entity_id,
                    entity_type=body.entity_type,
                    metadata=body.metadata,
                )
                created = await db.get_learning_by_id(learning_id)
            else:
                sync_db = cast(BaseDb, db)
                sync_db.upsert_learning(
                    id=learning_id,
                    learning_type=body.learning_type,
                    content=body.content,
                    user_id=body.user_id,
                    agent_id=body.agent_id,
                    team_id=body.team_id,
                    session_id=body.session_id,
                    namespace=body.namespace,
                    entity_id=body.entity_id,
                    entity_type=body.entity_type,
                    metadata=body.metadata,
                )
                created = sync_db.get_learning_by_id(learning_id)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Learnings not supported by the configured database")

        if created is None:
            raise HTTPException(status_code=500, detail="Failed to create learning")
        return LearningResponse.model_validate(created)

    @router.get(
        "/learnings/{learning_id}",
        response_model=LearningResponse,
        operation_id="get_learning",
        summary="Get Learning",
        description="Retrieve a single learning record by its ID.",
    )
    async def get_learning(
        request: Request,
        learning_id: str = Path(description="The learning ID"),
        db_id: Optional[str] = Query(None, description="Database ID to query"),
    ) -> LearningResponse:
        db = await get_db(dbs, db_id)
        record = await _fetch_learning(db, learning_id)
        _enforce_user_scope(request, record)
        return LearningResponse.model_validate(record)

    @router.patch(
        "/learnings/{learning_id}",
        response_model=LearningResponse,
        operation_id="update_learning",
        summary="Update Learning",
        description=(
            "Update a learning record. Only `content` and `metadata` may be modified; "
            "identity fields (user_id, agent_id, team_id, etc.) are immutable. "
            "Provided fields fully replace the existing values."
        ),
    )
    async def update_learning(
        request: Request,
        body: LearningUpdate,
        learning_id: str = Path(description="The learning ID"),
        db_id: Optional[str] = Query(None, description="Database ID to use"),
    ) -> LearningResponse:
        db = await get_db(dbs, db_id)
        existing = await _fetch_learning(db, learning_id)
        _enforce_user_scope(request, existing)

        updates = body.model_dump(exclude_unset=True)
        if not updates:
            return LearningResponse.model_validate(existing)

        if "content" in updates and updates["content"] is None:
            raise HTTPException(
                status_code=422,
                detail="content cannot be null; omit the field to leave it unchanged",
            )

        new_content = updates["content"] if "content" in updates else existing.get("content") or {}
        new_metadata = updates["metadata"] if "metadata" in updates else existing.get("metadata")

        try:
            if isinstance(db, AsyncBaseDb):
                await db.upsert_learning(
                    id=learning_id,
                    learning_type=existing["learning_type"],
                    content=new_content,
                    user_id=existing.get("user_id"),
                    agent_id=existing.get("agent_id"),
                    team_id=existing.get("team_id"),
                    session_id=existing.get("session_id"),
                    namespace=existing.get("namespace"),
                    entity_id=existing.get("entity_id"),
                    entity_type=existing.get("entity_type"),
                    metadata=new_metadata,
                )
                updated = await db.get_learning_by_id(learning_id)
            else:
                sync_db = cast(BaseDb, db)
                sync_db.upsert_learning(
                    id=learning_id,
                    learning_type=existing["learning_type"],
                    content=new_content,
                    user_id=existing.get("user_id"),
                    agent_id=existing.get("agent_id"),
                    team_id=existing.get("team_id"),
                    session_id=existing.get("session_id"),
                    namespace=existing.get("namespace"),
                    entity_id=existing.get("entity_id"),
                    entity_type=existing.get("entity_type"),
                    metadata=new_metadata,
                )
                updated = sync_db.get_learning_by_id(learning_id)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Learnings not supported by the configured database")

        if updated is None:
            raise HTTPException(status_code=500, detail="Failed to update learning")
        return LearningResponse.model_validate(updated)

    @router.delete(
        "/learnings/{learning_id}",
        status_code=204,
        operation_id="delete_learning",
        summary="Delete Learning",
        description="Permanently delete a learning record by its ID.",
    )
    async def delete_learning(
        request: Request,
        learning_id: str = Path(description="The learning ID"),
        db_id: Optional[str] = Query(None, description="Database ID to use"),
    ) -> None:
        db = await get_db(dbs, db_id)
        existing = await _fetch_learning(db, learning_id)
        _enforce_user_scope(request, existing)

        try:
            if isinstance(db, AsyncBaseDb):
                deleted = await db.delete_learning(learning_id)
            else:
                deleted = cast(BaseDb, db).delete_learning(learning_id)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Learnings not supported by the configured database")

        if not deleted:
            raise HTTPException(status_code=500, detail="Failed to delete learning")

    return router


async def _fetch_learning(db: Union[BaseDb, AsyncBaseDb, RemoteDb], learning_id: str) -> dict:
    if isinstance(db, RemoteDb):
        raise HTTPException(status_code=501, detail="Learnings endpoints not supported on remote DBs")
    try:
        if isinstance(db, AsyncBaseDb):
            record = await db.get_learning_by_id(learning_id)
        else:
            record = cast(BaseDb, db).get_learning_by_id(learning_id)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="Learnings not supported by the configured database")
    if record is None:
        raise HTTPException(status_code=404, detail="Learning not found")
    return record


def _enforce_user_scope(request: Request, record: dict) -> None:
    """Return 404 (not 403) if the JWT subject doesn't own the record, to avoid leaking existence."""
    if not hasattr(request.state, "user_id") or request.state.user_id is None:
        return
    if record.get("user_id") != request.state.user_id:
        raise HTTPException(status_code=404, detail="Learning not found")
