"""Learnings API router -- CRUD over the agno_learnings table."""

import logging
from typing import Optional, Union, cast
from uuid import uuid4

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.learnings.schema import LearningCreate, LearningResponse, LearningUpdate, LearningUserStats
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    SortOrder,
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
            "List learning records with pagination and optional filters. For a scoped (non-admin) "
            "caller with user isolation enabled, results are bound to that user and also include "
            "records with no owner (`user_id IS NULL`) — this covers global, agent, team, session, "
            "and entity-scoped learnings; passing a `user_id` that differs from the caller is "
            "rejected with 403. Admins and unscoped callers see all records (optionally filtered by "
            "`user_id`)."
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
        sort_by: Optional[str] = Query(None, description="Field to sort by (defaults to updated_at)"),
        sort_order: Optional[SortOrder] = Query(SortOrder.DESC, description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(None, description="Database ID to query"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> PaginatedResponse[LearningResponse]:
        include_global = False
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if user_id is not None and user_id != scoped_user_id:
                raise HTTPException(status_code=403, detail="Cannot list learnings for another user")
            user_id = scoped_user_id
            include_global = True

        db = await get_db(dbs, db_id, table)

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
                    include_global=include_global,
                    limit=limit,
                    page=page,
                    sort_by=sort_by,
                    sort_order=sort_order.value if sort_order else None,
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
                    include_global=include_global,
                    limit=limit,
                    page=page,
                    sort_by=sort_by,
                    sort_order=sort_order.value if sort_order else None,
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
            "Create a new learning record. For a scoped (non-admin) caller, the body's `user_id` "
            "must either be omitted/null (creates a global / non-user-scoped record) or match the "
            "caller. A mismatch is rejected with 403. Admins and unscoped callers may set any `user_id`."
        ),
    )
    async def create_learning(
        request: Request,
        body: LearningCreate,
        db_id: Optional[str] = Query(None, description="Database ID to use"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> LearningResponse:
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None and body.user_id is not None and body.user_id != scoped_user_id:
            raise HTTPException(status_code=403, detail="Cannot create learnings for another user")

        db = await get_db(dbs, db_id, table)

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
        "/learnings/users",
        response_model=PaginatedResponse[LearningUserStats],
        operation_id="list_learning_users",
        summary="List Learning Users",
        description=(
            "List the users that own learning records, with a per-user count and last-updated "
            "timestamp. Intended as the entry point for a per-user view: list users here, then "
            "drill into a single user's learnings via `GET /learnings?user_id=...`. Records with "
            "no owner (`user_id IS NULL`) are excluded. Pass `learning_type` to restrict the "
            "grouping to a single store (e.g. `user_profile` or `user_memory`). For a scoped "
            "(non-admin) caller results are bound to that user; an explicit `user_id` that differs "
            "is rejected with 403. Admins and unscoped callers list all users. Sortable by "
            "`user_id` or `last_learning_updated_at` (the default)."
        ),
    )
    async def list_learning_users(
        request: Request,
        learning_type: Optional[str] = Query(None, description="Restrict the grouping to a single learning type"),
        user_id: Optional[str] = Query(None, description="Restrict the result to a single user"),
        limit: int = Query(20, ge=1, le=1000, description="Page size"),
        page: int = Query(1, ge=1, description="1-indexed page number"),
        sort_by: Optional[str] = Query(
            None,
            description="Field to sort by: user_id or last_learning_updated_at (the default)",
        ),
        sort_order: Optional[SortOrder] = Query(SortOrder.DESC, description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(None, description="Database ID to query"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> PaginatedResponse[LearningUserStats]:
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if user_id is not None and user_id != scoped_user_id:
                raise HTTPException(status_code=403, detail="Cannot list learning users for another user")
            user_id = scoped_user_id

        db = await get_db(dbs, db_id, table)

        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Learnings endpoints not supported on remote DBs")

        try:
            if isinstance(db, AsyncBaseDb):
                records, total_count = await db.get_learnings_user_stats(
                    learning_type=learning_type,
                    user_id=user_id,
                    limit=limit,
                    page=page,
                    sort_by=sort_by,
                    sort_order=sort_order.value if sort_order else None,
                )
            else:
                records, total_count = cast(BaseDb, db).get_learnings_user_stats(
                    learning_type=learning_type,
                    user_id=user_id,
                    limit=limit,
                    page=page,
                    sort_by=sort_by,
                    sort_order=sort_order.value if sort_order else None,
                )
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Learnings not supported by the configured database")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to get learning users: {e}")

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=[LearningUserStats.model_validate(r) for r in records],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.delete(
        "/learnings/users/{user_id}",
        status_code=204,
        operation_id="delete_learning_user",
        summary="Delete Learning User",
        description=(
            "Delete the learning records owned by a user. By default removes every learning type "
            "backed by the agno_learnings table (user_profile, user_memory, and any user-scoped "
            "entity records); pass `learning_type` to restrict deletion to a single store. Records "
            "with no owner (`user_id IS NULL`) are not affected. For a scoped (non-admin) caller, "
            "only their own learnings may be deleted; a different `user_id` is rejected with 403. "
            "Admins and unscoped callers may delete any user's learnings. Returns 204 even if the "
            "user had no matching records."
        ),
    )
    async def delete_learning_user(
        request: Request,
        user_id: str = Path(description="The user whose learnings should be deleted"),
        learning_type: Optional[str] = Query(
            None, description="Restrict deletion to a single learning type; omit to delete all of the user's learnings"
        ),
        db_id: Optional[str] = Query(None, description="Database ID to use"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> None:
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None and user_id != scoped_user_id:
            raise HTTPException(status_code=403, detail="Cannot delete learnings for another user")

        db = await get_db(dbs, db_id, table)

        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Learnings endpoints not supported on remote DBs")

        try:
            if isinstance(db, AsyncBaseDb):
                await db.delete_user_learnings(user_id, learning_type=learning_type)
            else:
                cast(BaseDb, db).delete_user_learnings(user_id, learning_type=learning_type)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Learnings not supported by the configured database")

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
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> LearningResponse:
        db = await get_db(dbs, db_id, table)
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
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> LearningResponse:
        db = await get_db(dbs, db_id, table)
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

        # TOCTOU guard: if the row was deleted between our fetch and the upsert,
        # the upsert silently re-created it via INSERT instead of UPDATE. The SQL
        # adapters preserve created_at on ON CONFLICT DO UPDATE (only content/
        # metadata/updated_at are set), so a created_at delta is the signature of
        # an unintended re-creation. Roll it back and report 404.
        if existing.get("created_at") is not None and updated.get("created_at") != existing.get("created_at"):
            try:
                if isinstance(db, AsyncBaseDb):
                    await db.delete_learning(learning_id)
                else:
                    cast(BaseDb, db).delete_learning(learning_id)
            except Exception:
                pass
            raise HTTPException(status_code=404, detail="Learning not found")

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
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> None:
        db = await get_db(dbs, db_id, table)
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
    """Block cross-user access without leaking existence.

    Scoping is the framework's opt-in ``user_isolation`` contract: admins and callers
    running with isolation disabled get ``None`` from ``get_scoped_user_id`` and have full
    access. For a scoped (non-admin) caller, records with ``user_id IS NULL`` are global /
    non-user-scoped (e.g. agent, team, session, or entity learnings) and remain accessible;
    a record owned by a different user returns 404 (not 403) to avoid leaking which IDs exist.
    """
    scoped_user_id = get_scoped_user_id(request)
    if scoped_user_id is None:
        return
    record_user_id = record.get("user_id")
    if record_user_id is None:
        return
    if record_user_id != scoped_user_id:
        raise HTTPException(status_code=404, detail="Learning not found")
