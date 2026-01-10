import logging
import time
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
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
from agno.utils.log import log_error

logger = logging.getLogger(__name__)


# ============================================
# Request/PrimitiveResponse Schemas
# ============================================


class PrimitiveCreate(BaseModel):
    entity_id: str = Field(..., description="Unique identifier for the entity")
    entity_type: str = Field(..., description="Type of entity: agent, team, or workflow")
    name: str = Field(..., description="Display name")
    description: Optional[str] = Field(None, description="Optional description")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional metadata")
    # Config parameters are optional, but if provided, they will be used to create the initial config
    config: Optional[Dict[str, Any]] = Field(None, description="Optional configuration")
    version_label: Optional[str] = Field(None, description="Optional label (e.g., 'stable')")
    stage: str = Field("draft", description="Stage: 'draft' or 'published'")
    notes: Optional[str] = Field(None, description="Optional notes")
    set_current: bool = Field(True, description="Set as current version")


class PrimitiveResponse(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    description: Optional[str] = None
    current_version: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: int
    updated_at: Optional[int] = None


class ConfigCreate(BaseModel):
    config: Dict[str, Any] = Field(..., description="The configuration data")
    version_label: Optional[str] = Field(None, description="Optional label (e.g., 'stable')")
    stage: str = Field("draft", description="Stage: 'draft' or 'published'")
    notes: Optional[str] = Field(None, description="Optional notes")
    set_current: bool = Field(True, description="Set as current version")
    upsert_version: bool = Field(False, description="Upsert the version if it already exists")


class ConfigResponse(BaseModel):
    entity_id: str
    version: int
    version_label: Optional[str] = None
    stage: str
    config: Dict[str, Any]
    notes: Optional[str] = None
    created_at: int
    updated_at: Optional[int] = None


# ============================================
# Router
# ============================================


def get_primitives_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], settings: AgnoAPISettings = AgnoAPISettings()
) -> APIRouter:
    """Create entities and configs router."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Entities"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, dbs=dbs)


def attach_routes(router: APIRouter, dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]]) -> APIRouter:
    # ============================================
    # ENTITY ENDPOINTS
    # ============================================

    @router.get(
        "/entities",
        response_model=PaginatedResponse[PrimitiveResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_entities",
        summary="List Primitives",
        description="Retrieve a paginated list of entities with optional filtering by type.",
    )
    async def list_entities(
        request: Request,
        entity_type: Optional[str] = Query(None, description="Filter by type: agent, team, workflow"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> PaginatedResponse[PrimitiveResponse]:
        db = await get_db(dbs, db_id)

        try:
            start_time_ms = time.time() * 1000
            entities = db.list_entities(entity_type=entity_type)

            total_count = len(entities)
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0
            start_idx = (page - 1) * limit
            paginated = entities[start_idx : start_idx + limit]

            return PaginatedResponse(
                data=[PrimitiveResponse(**e) for e in paginated],
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_pages=total_pages,
                    total_count=total_count,
                    search_time_ms=round(time.time() * 1000 - start_time_ms, 2),
                ),
            )
        except Exception as e:
            log_error(f"Error listing entities: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/entities",
        response_model=PrimitiveResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_entity",
        summary="Create Entity",
        description="Create a new entity (agent, team, or workflow).",
    )
    async def create_entity(
        request: Request,
        body: PrimitiveCreate,
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> PrimitiveResponse:
        db = await get_db(dbs, db_id)

        try:
            entity = db.upsert_entity(
                entity_id=body.entity_id,
                entity_type=body.entity_type,
                name=body.name,
                description=body.description,
                metadata=body.metadata,
            )
            # Create the initial config
            config = db.upsert_config(
                entity_id=body.entity_id,
                config=body.config,
                version_label=body.version_label,
                stage=body.stage,
                notes=body.notes,
                set_current=body.set_current,
            )
            return PrimitiveResponse(**entity)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error creating entity: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/entities/{entity_id}",
        response_model=PrimitiveResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_entity",
        summary="Get Entity",
        description="Retrieve an entity by ID.",
    )
    async def get_entity(
        request: Request,
        entity_id: str = Path(description="Entity ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> PrimitiveResponse:
        db = await get_db(dbs, db_id)

        try:
            entity = db.get_entity(entity_id)
            if entity is None:
                raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
            return PrimitiveResponse(**entity)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting entity: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete(
        "/entities/{entity_id}",
        status_code=204,
        operation_id="delete_entity",
        summary="Delete Entity",
        description="Delete an entity and all its configs.",
    )
    async def delete_entity(
        request: Request,
        entity_id: str = Path(description="Entity ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> None:
        db = await get_db(dbs, db_id)

        try:
            deleted = db.delete_entity(entity_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error deleting entity: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ============================================
    # CONFIG ENDPOINTS
    # ============================================

    @router.get(
        "/entities/{entity_id}/configs",
        response_model=List[ConfigResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_configs",
        summary="List Config Versions",
        description="List all config versions for an entity.",
    )
    async def list_configs(
        request: Request,
        entity_id: str = Path(description="Entity ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> List[ConfigResponse]:
        db = await get_db(dbs, db_id)

        try:
            configs = db.list_config_versions(entity_id)
            return [ConfigResponse(**c) for c in configs]
        except Exception as e:
            log_error(f"Error listing configs: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/entities/{entity_id}/configs",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_config",
        summary="Create Config Version",
        description="Create a new config version for an entity.",
    )
    async def create_config(
        request: Request,
        entity_id: str = Path(description="Entity ID"),
        body: ConfigCreate = Body(description="Config data"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ConfigResponse:
        db = await get_db(dbs, db_id)

        try:
            # Determine version to update (if overwriting)
            version_to_update = None
            if body.upsert_version:
                entity = db.get_entity(entity_id)
                if entity and entity.get("current_version"):
                    version_to_update = entity["current_version"]

            config = db.upsert_config(
                entity_id=entity_id,
                version=version_to_update,
                config=body.config,
                version_label=body.version_label,
                stage=body.stage,
                notes=body.notes,
                set_current=body.set_current,
            )
            return ConfigResponse(**config)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error creating config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/entities/{entity_id}/configs/current",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_current_config",
        summary="Get Current Config",
        description="Get the current config version for an entity.",
    )
    async def get_current_config(
        request: Request,
        entity_id: str = Path(description="Entity ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ConfigResponse:
        db = await get_db(dbs, db_id)

        try:
            config = db.get_config(entity_id)
            if config is None:
                raise HTTPException(status_code=404, detail=f"No config found for {entity_id}")
            return ConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/entities/{entity_id}/configs/{version}",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_config",
        summary="Get Config Version",
        description="Get a specific config version by number or label.",
    )
    async def get_config(
        request: Request,
        entity_id: str = Path(description="Entity ID"),
        version: str = Path(description="Version number or label"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ConfigResponse:
        db = await get_db(dbs, db_id)

        try:
            try:
                config = db.get_config(entity_id, version=int(version))
            except ValueError:
                config = db.get_config(entity_id, label=version)

            if config is None:
                raise HTTPException(status_code=404, detail=f"Config {entity_id} v{version} not found")
            return ConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
