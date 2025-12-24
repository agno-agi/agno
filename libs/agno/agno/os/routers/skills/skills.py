"""Skills API router for CRUD operations on skills."""

import logging
import math
from typing import Optional, Union, cast

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.routing import APIRouter

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.skill import Skill
from agno.os.auth import get_authentication_dependency
from agno.os.routers.skills.schemas import (
    DeleteSkillsRequest,
    SkillCreateSchema,
    SkillSchema,
    SkillUpdateSchema,
)
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
from agno.skills.skill import compute_content_hash

logger = logging.getLogger(__name__)


def get_skill_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb]]], settings: AgnoAPISettings = AgnoAPISettings(), **kwargs
) -> APIRouter:
    """Create skills router with comprehensive OpenAPI documentation for skill management endpoints."""
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
    return attach_routes(router=router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, list[Union[BaseDb, AsyncBaseDb]]]) -> APIRouter:
    @router.get(
        "/skills",
        response_model=PaginatedResponse[SkillSchema],
        status_code=200,
        operation_id="list_skills",
        summary="List Skills",
        description="Get a paginated list of skills with optional filtering and sorting.",
        responses={
            200: {
                "description": "List of skills",
                "content": {
                    "application/json": {
                        "example": {
                            "items": [
                                {
                                    "id": "abc123...",
                                    "name": "code-review",
                                    "description": "Review code for quality and best practices",
                                    "instructions": "...",
                                    "version": 1,
                                    "scripts": [],
                                    "references": ["style-guide.md"],
                                }
                            ],
                            "pagination": {"total": 10, "page": 1, "limit": 20, "total_pages": 1},
                        }
                    }
                },
            },
        },
    )
    async def list_skills(
        request: Request,
        name: Optional[str] = Query(default=None, description="Filter by skill name"),
        limit: int = Query(default=20, ge=1, le=100, description="Number of skills per page"),
        page: int = Query(default=1, ge=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: SortOrder = Query(default=SortOrder.DESC, description="Sort order"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        table: Optional[str] = Query(default=None, description="Table to use"),
    ) -> PaginatedResponse[SkillSchema]:
        db = await get_db(dbs, db_id, table)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            result = await db.get_skills(
                name=name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order.value,
                deserialize=False,
            )
        else:
            result = db.get_skills(
                name=name,
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order.value,
                deserialize=False,
            )

        if isinstance(result, tuple):
            skills_raw, total = result
        else:
            skills_raw = result
            total = len(skills_raw)

        skills = [SkillSchema.from_dict(s) for s in skills_raw]
        total_pages = math.ceil(total / limit) if limit > 0 else 1

        return PaginatedResponse(
            data=skills,
            meta=PaginationInfo(
                total=total,
                page=page,
                limit=limit,
                total_pages=total_pages,
            ),
        )

    @router.get(
        "/skills/{skill_id}",
        response_model=SkillSchema,
        status_code=200,
        operation_id="get_skill",
        summary="Get Skill",
        description="Get a specific skill by its ID.",
        responses={
            200: {"description": "Skill details"},
            404: {"description": "Skill not found", "model": NotFoundResponse},
        },
    )
    async def get_skill(
        request: Request,
        skill_id: str = Path(description="Skill ID"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        table: Optional[str] = Query(default=None, description="Table to use"),
    ) -> SkillSchema:
        db = await get_db(dbs, db_id, table)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            skill = await db.get_skill(skill_id=skill_id, deserialize=False)
        else:
            skill = db.get_skill(skill_id=skill_id, deserialize=False)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill with ID '{skill_id}' not found")

        return SkillSchema.from_dict(skill)

    @router.post(
        "/skills",
        response_model=SkillSchema,
        status_code=201,
        operation_id="create_skill",
        summary="Create Skill",
        description="Create a new skill. The ID is automatically generated from the content hash.",
        responses={
            201: {"description": "Skill created successfully"},
            400: {"description": "Invalid request data", "model": BadRequestResponse},
            500: {"description": "Failed to create skill", "model": InternalServerErrorResponse},
        },
    )
    async def create_skill(
        request: Request,
        payload: SkillCreateSchema,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        table: Optional[str] = Query(default=None, description="Table to use"),
    ) -> SkillSchema:
        db = await get_db(dbs, db_id, table)

        # Generate ID from content hash
        skill_id = compute_content_hash(payload.name, payload.description, payload.instructions)

        # Convert SkillFileSchema objects to dicts for storage
        scripts = [{"name": s.name, "content": s.content} for s in payload.scripts]
        references = [{"name": r.name, "content": r.content} for r in payload.references]

        skill = Skill(
            id=skill_id,
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
            metadata=payload.metadata,
            version=payload.version,
            scripts=scripts,
            references=references,
        )

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            result = await db.upsert_skill(skill=skill, deserialize=False)
        else:
            result = db.upsert_skill(skill=skill, deserialize=False)

        if result is None:
            raise HTTPException(status_code=500, detail="Failed to create skill")

        return SkillSchema.from_dict(result)

    @router.patch(
        "/skills/{skill_id}",
        response_model=SkillSchema,
        status_code=200,
        operation_id="update_skill",
        summary="Update Skill",
        description="Update an existing skill. Only provided fields are updated.",
        responses={
            200: {"description": "Skill updated successfully"},
            404: {"description": "Skill not found", "model": NotFoundResponse},
            500: {"description": "Failed to update skill", "model": InternalServerErrorResponse},
        },
    )
    async def update_skill(
        request: Request,
        skill_id: str = Path(description="Skill ID"),
        payload: SkillUpdateSchema = ...,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        table: Optional[str] = Query(default=None, description="Table to use"),
    ) -> SkillSchema:
        db = await get_db(dbs, db_id, table)

        # Get existing skill
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            existing = await db.get_skill(skill_id=skill_id, deserialize=True)
        else:
            existing = db.get_skill(skill_id=skill_id, deserialize=True)

        if existing is None:
            raise HTTPException(status_code=404, detail=f"Skill with ID '{skill_id}' not found")

        # Update fields
        updated_skill = Skill(
            id=skill_id,
            name=payload.name if payload.name is not None else existing.name,
            description=payload.description if payload.description is not None else existing.description,
            instructions=payload.instructions if payload.instructions is not None else existing.instructions,
            metadata=payload.metadata if payload.metadata is not None else existing.metadata,
            version=payload.version if payload.version is not None else existing.version,
            scripts=payload.scripts if payload.scripts is not None else existing.scripts,
            references=payload.references if payload.references is not None else existing.references,
            created_at=existing.created_at,
        )

        if isinstance(db, AsyncBaseDb):
            result = await db.upsert_skill(skill=updated_skill, deserialize=False)
        else:
            result = db.upsert_skill(skill=updated_skill, deserialize=False)

        if result is None:
            raise HTTPException(status_code=500, detail="Failed to update skill")

        return SkillSchema.from_dict(result)

    @router.delete(
        "/skills/{skill_id}",
        status_code=204,
        operation_id="delete_skill",
        summary="Delete Skill",
        description="Permanently delete a skill. This action cannot be undone.",
        responses={
            204: {"description": "Skill deleted successfully"},
            404: {"description": "Skill not found", "model": NotFoundResponse},
        },
    )
    async def delete_skill(
        request: Request,
        skill_id: str = Path(description="Skill ID to delete"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        table: Optional[str] = Query(default=None, description="Table to use"),
    ) -> None:
        db = await get_db(dbs, db_id, table)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            success = await db.delete_skill(skill_id=skill_id)
        else:
            success = db.delete_skill(skill_id=skill_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Skill with ID '{skill_id}' not found")

    @router.delete(
        "/skills",
        status_code=204,
        operation_id="delete_skills",
        summary="Delete Multiple Skills",
        description="Delete multiple skills by their IDs. This action cannot be undone.",
        responses={
            204: {"description": "Skills deleted successfully"},
            400: {"description": "Invalid request - empty skill_ids list", "model": BadRequestResponse},
        },
    )
    async def delete_skills(
        http_request: Request,
        request: DeleteSkillsRequest,
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        table: Optional[str] = Query(default=None, description="Table to use"),
    ) -> None:
        db = await get_db(dbs, db_id, table)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            await db.delete_skills(skill_ids=request.skill_ids)
        else:
            db.delete_skills(skill_ids=request.skill_ids)

    @router.get(
        "/skills/{skill_id}/instructions",
        response_model=str,
        status_code=200,
        operation_id="get_skill_instructions",
        summary="Get Skill Instructions",
        description="Get the full instructions for a specific skill.",
        responses={
            200: {"description": "Skill instructions"},
            404: {"description": "Skill not found", "model": NotFoundResponse},
        },
    )
    async def get_skill_instructions(
        request: Request,
        skill_id: str = Path(description="Skill ID"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use"),
        table: Optional[str] = Query(default=None, description="Table to use"),
    ) -> str:
        db = await get_db(dbs, db_id, table)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            skill = await db.get_skill(skill_id=skill_id, deserialize=True)
        else:
            skill = db.get_skill(skill_id=skill_id, deserialize=True)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill with ID '{skill_id}' not found")

        return skill.instructions

    return router
