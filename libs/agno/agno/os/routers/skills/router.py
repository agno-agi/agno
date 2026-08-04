"""Skills API router -- CRUD over the agno_skills table."""

import logging
from typing import Optional, Union, cast

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.skills.schema import SkillCreate, SkillResponse, SkillSummaryResponse, SkillUpdate
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
from agno.skills.errors import SkillError, SkillValidationError
from agno.skills.validator import validate_metadata

logger = logging.getLogger(__name__)


def get_skills_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    settings: AgnoAPISettings = AgnoAPISettings(),
    **kwargs,
) -> APIRouter:
    """Factory that creates and returns the skills router."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Skills"],
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
        "/skills",
        response_model=PaginatedResponse[SkillSummaryResponse],
        operation_id="list_skills",
        summary="List Skills",
        description=(
            "List skills with pagination, metadata only (no instructions, scripts or "
            "references -- fetch a single skill for its content). `user_id` filters by "
            "owner. For a scoped (non-admin) caller with user isolation enabled, results "
            "are bound to that user's own skills; passing a `user_id` that differs from "
            "the caller is rejected with 403."
        ),
    )
    async def list_skills(
        request: Request,
        user_id: Optional[str] = Query(None, description="Filter by owning user ID"),
        limit: int = Query(100, ge=1, le=1000, description="Page size"),
        page: int = Query(1, ge=1, description="1-indexed page number"),
        db_id: Optional[str] = Query(None, description="Database ID to query"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> PaginatedResponse[SkillSummaryResponse]:
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None:
            if user_id is not None and user_id != scoped_user_id:
                raise HTTPException(status_code=403, detail="Cannot list skills for another user")
            user_id = scoped_user_id

        db = await get_db(dbs, db_id, table)

        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Skills endpoints not supported on remote DBs")

        try:
            if isinstance(db, AsyncBaseDb):
                records, total_count = await db.get_skills(user_id=user_id, limit=limit, page=page)
            else:
                records, total_count = cast(BaseDb, db).get_skills(user_id=user_id, limit=limit, page=page)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Skills not supported by the configured database")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to list skills: {e}")

        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=[SkillSummaryResponse.model_validate(r) for r in records],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_pages=total_pages,
                total_count=total_count,
            ),
        )

    @router.post(
        "/skills",
        response_model=SkillResponse,
        status_code=201,
        operation_id="create_skill",
        summary="Create Skill",
        description=(
            "Create a skill. The name must be unique (409 if taken); id and version are "
            "server-managed (version starts at 1). For a scoped (non-admin) caller, the "
            "body's `user_id` must be omitted/null (a shared skill) or match the caller "
            "(mismatch -> 403)."
        ),
    )
    async def create_skill(
        request: Request,
        body: SkillCreate,
        db_id: Optional[str] = Query(None, description="Database ID to use"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> SkillResponse:
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None and body.user_id is not None and body.user_id != scoped_user_id:
            raise HTTPException(status_code=403, detail="Cannot create skills for another user")
        if scoped_user_id is not None:
            # A scoped caller owns what it creates. A skill with no owner is mutable only by
            # an admin, so letting one be created here would mint a globally-loadable skill
            # its author could never edit or delete. Admins stay unscoped and can share.
            body.user_id = scoped_user_id

        db = await get_db(dbs, db_id, table)

        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Skills endpoints not supported on remote DBs")

        _validate_skill_metadata(body.model_dump())

        try:
            if isinstance(db, AsyncBaseDb):
                created = await db.create_skill(body.model_dump())
            else:
                created = cast(BaseDb, db).create_skill(body.model_dump())
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Skills not supported by the configured database")
        except SkillValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except SkillError as e:
            # create_skill turns the duplicate-name integrity error into a SkillError
            raise HTTPException(status_code=409, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create skill: {e}")

        return SkillResponse.model_validate(created)

    @router.get(
        "/skills/{name}",
        response_model=SkillResponse,
        operation_id="get_skill",
        summary="Get Skill",
        description=(
            "Retrieve a single skill by name, full content included. A shared skill "
            "(`user_id IS NULL`) is readable by any caller; for a scoped (non-admin) "
            "caller, a skill owned by another user returns 404."
        ),
    )
    async def get_skill(
        request: Request,
        name: str = Path(description="The skill name"),
        db_id: Optional[str] = Query(None, description="Database ID to query"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> SkillResponse:
        db = await get_db(dbs, db_id, table)
        record = await _fetch_skill(db, name)
        _enforce_user_scope(request, record)
        return SkillResponse.model_validate(record)

    @router.patch(
        "/skills/{name}",
        response_model=SkillResponse,
        operation_id="update_skill",
        summary="Update Skill",
        description=(
            "Update a skill. `version` names the version being edited: the update only "
            "applies if the stored version still matches (409 with the current version "
            "otherwise), and bumps the version by one on success. Ownership is immutable: "
            "`user_id` is set at create and is not an updatable field. Skills with no owner "
            "(`user_id IS NULL`) may only be modified by an admin."
        ),
    )
    async def update_skill(
        request: Request,
        body: SkillUpdate,
        name: str = Path(description="The skill name"),
        db_id: Optional[str] = Query(None, description="Database ID to use"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> SkillResponse:
        scoped_user_id = get_scoped_user_id(request)
        db = await get_db(dbs, db_id, table)
        existing = await _fetch_skill(db, name)
        _enforce_user_scope(request, existing, mutating=True)

        updates = body.model_dump(exclude_unset=True, exclude={"version"})
        # These columns are NOT NULL in the table: an explicit null can never be
        # stored, and the DB layer would surface it as a misleading version conflict.
        for field in ("description", "instructions", "scripts", "references", "source_type"):
            if field in updates and updates[field] is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field} cannot be null; omit the field to leave it unchanged",
                )
        _validate_skill_metadata({**existing, **updates})

        try:
            # scoped_user_id is an ownership predicate on WHICH row may be written, not a
            # value: checking the fetched row above and then writing unscoped would be a
            # TOCTOU, since the name can be re-owned between the check and the write.
            # Only sent when it actually scopes, leaving the unscoped call unchanged.
            scope = {"user_id": scoped_user_id} if scoped_user_id is not None else {}
            if isinstance(db, AsyncBaseDb):
                updated = await db.update_skill(name, expected_version=body.version, **scope, **updates)
            else:
                updated = cast(BaseDb, db).update_skill(name, expected_version=body.version, **scope, **updates)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Skills not supported by the configured database")
        except SkillValidationError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update skill: {e}")

        if updated is None:
            # The guarded update matched nothing: the row is gone (404, raised by the
            # re-fetch) or its version has moved -- tell the caller where it is now.
            current = await _fetch_skill(db, name, user_id=scoped_user_id)
            if current["version"] == body.version:
                # The version did not move, so this is no conflict: the DB layer
                # swallowed a real error into None. A 409 telling the caller to
                # retry with the version they already sent could never succeed.
                raise HTTPException(status_code=500, detail=f"Failed to update skill '{name}'")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Version conflict for skill '{name}': expected version {body.version}, "
                    f"current version is {current['version']}. Retry with the current version."
                ),
            )
        return SkillResponse.model_validate(updated)

    @router.delete(
        "/skills/{name}",
        status_code=204,
        operation_id="delete_skill",
        summary="Delete Skill",
        description=(
            "Permanently delete a skill by name. `user_id` restricts the delete to a "
            "skill owned by that user. Skills with no owner (`user_id IS NULL`) may "
            "only be deleted by an admin."
        ),
    )
    async def delete_skill(
        request: Request,
        name: str = Path(description="The skill name"),
        user_id: Optional[str] = Query(None, description="Only delete the skill if owned by this user ID"),
        db_id: Optional[str] = Query(None, description="Database ID to use"),
        table: Optional[str] = Query(None, description="The database table to use (requires db_id)"),
    ) -> None:
        scoped_user_id = get_scoped_user_id(request)
        if scoped_user_id is not None and user_id is not None and user_id != scoped_user_id:
            raise HTTPException(status_code=403, detail="Cannot delete skills for another user")

        db = await get_db(dbs, db_id, table)
        existing = await _fetch_skill(db, name)
        _enforce_user_scope(request, existing, mutating=True)

        # Bind the delete to the caller, not the raw query param: checking the fetched row
        # and then deleting by name alone is a TOCTOU, since a name can be re-owned between
        # the check and the write. Unscoped callers keep the param as a plain owner filter.
        owner_filter = scoped_user_id if scoped_user_id is not None else user_id
        try:
            if isinstance(db, AsyncBaseDb):
                deleted = await db.delete_skill(name, user_id=owner_filter)
            else:
                deleted = cast(BaseDb, db).delete_skill(name, user_id=owner_filter)
        except NotImplementedError:
            raise HTTPException(status_code=501, detail="Skills not supported by the configured database")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete skill: {e}")

        if not deleted:
            # Nothing matched: the row vanished, the user_id filter excluded it, or
            # the DB layer swallowed an error into False. Either way nothing was
            # deleted, and the filter case makes 404 the honest answer.
            raise HTTPException(status_code=404, detail="Skill not found")

    return router


def _validate_skill_metadata(skill_data: dict) -> None:
    """Reject metadata the loader would refuse, at write time rather than at load.

    The loader validates every row it reads and raises on the first bad one, so a skill
    stored with an invalid name disables loading for every skill alongside it. Validating
    here keeps that row out of the table, the way the schedules router validates a cron
    expression before the insert.
    """
    fields = {
        "name": skill_data.get("name"),
        "description": skill_data.get("description"),
        "license": skill_data.get("license"),
        "compatibility": skill_data.get("compatibility"),
        "allowed-tools": skill_data.get("allowed_tools"),
        "metadata": skill_data.get("metadata"),
    }
    # Unset optionals are omitted, not passed as None: the validator checks presence.
    errors = validate_metadata({key: value for key, value in fields.items() if value is not None})
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))


async def _fetch_skill(db: Union[BaseDb, AsyncBaseDb, RemoteDb], name: str, user_id: Optional[str] = None) -> dict:
    if isinstance(db, RemoteDb):
        raise HTTPException(status_code=501, detail="Skills endpoints not supported on remote DBs")
    try:
        if isinstance(db, AsyncBaseDb):
            record = await db.get_skill(name, user_id=user_id)
        else:
            record = cast(BaseDb, db).get_skill(name, user_id=user_id)
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="Skills not supported by the configured database")
    except Exception as e:
        # A DB error is not "not found" -- surface it rather than emit a misleading 404.
        raise HTTPException(status_code=500, detail=f"Failed to fetch skill: {e}")
    if record is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return record


def _enforce_user_scope(request: Request, record: dict, *, mutating: bool = False) -> None:
    """Block cross-user access without leaking existence.

    Scoping is the framework's opt-in ``user_isolation`` contract: admins and callers
    running with isolation disabled get ``None`` from ``get_scoped_user_id`` and have full
    access. For a scoped (non-admin) caller:

    - Skills with ``user_id IS NULL`` are shared. They remain readable to any
      authenticated caller, but mutating them (``mutating=True``, i.e. PATCH/DELETE) is
      admin-only -- a regular user must not overwrite or delete shared skills it
      doesn't own.
    - A skill owned by a different user returns 404 (not 403) to avoid leaking which
      names exist.
    """
    scoped_user_id = get_scoped_user_id(request)
    if scoped_user_id is None:
        return
    record_user_id = record.get("user_id")
    if record_user_id is None:
        if mutating:
            raise HTTPException(
                status_code=403, detail="Only admins can modify skills that have no owner (user_id is null)"
            )
        return
    if record_user_id != scoped_user_id:
        raise HTTPException(status_code=404, detail="Skill not found")
