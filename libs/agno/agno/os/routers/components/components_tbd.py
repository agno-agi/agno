import logging
import time
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    ComponentCreate,
    ComponentResponse,
    ComponentUpdate,
    ConfigCreate,
    ConfigResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.remote.base import RemoteDb
from agno.utils.log import log_error
from agno.utils.string import generate_id_from_name

logger = logging.getLogger(__name__)


def get_components_router(
    os_db: Union[BaseDb, AsyncBaseDb, RemoteDb], registry: Registry, settings: AgnoAPISettings = AgnoAPISettings()
) -> APIRouter:
    """Create components router."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Components"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, os_db=os_db, registry=registry)


def attach_routes(router: APIRouter, os_db: Union[BaseDb, AsyncBaseDb, RemoteDb], registry: Registry) -> APIRouter:
    @router.get(
        "/components",
        response_model=PaginatedResponse[ComponentResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_components",
        summary="List Components",
        description="Retrieve a paginated list of components with optional filtering by type.",
    )
    async def list_components(
        request: Request,
        component_type: Optional[str] = Query(None, description="Filter by type: agent, team, workflow"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> PaginatedResponse[ComponentResponse]:
        try:
            start_time_ms = time.time() * 1000
            components = os_db.list_components(component_type=component_type)

            total_count = len(components)
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0
            start_idx = (page - 1) * limit
            paginated = components[start_idx : start_idx + limit]

            return PaginatedResponse(
                data=[ComponentResponse(**c) for c in paginated],
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_pages=total_pages,
                    total_count=total_count,
                    search_time_ms=round(time.time() * 1000 - start_time_ms, 2),
                ),
            )
        except Exception as e:
            log_error(f"Error listing components: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/components",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_component",
        summary="Create Component",
        description="Create a new component (agent, team, or workflow).",
    )
    async def create_component(
        request: Request,
        body: ComponentCreate,
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ComponentResponse:
        try:
            # Auto-generate component_id if not provided
            component_id = body.component_id
            if component_id is None:
                component_id = generate_id_from_name(body.name)

            component = os_db.upsert_component(
                component_id=component_id,
                component_type=body.component_type,
                name=body.name,
                description=body.description,
                metadata=body.metadata,
            )

            # Prepare config - ensure it's a dict
            config = body.config or {}

            db_dict: Dict[str, Any] = {}
            try:
                component_db = config.get("db")
                if component_db is not None:
                    component_db_id = component_db.get("id")
                    if component_db_id is not None and component_db_id == db_id:
                        db_dict = os_db.to_dict()
                    else:
                        if registry.dbs is not None and len(registry.dbs) > 0:
                            for db in registry.dbs:
                                if db.id == component_db_id:
                                    db_dict = db.to_dict()
                                    break
            except Exception as e:
                log_error(f"Error getting OS Database: {e}")
                raise HTTPException(status_code=500, detail=str(e))

            config["db"] = db_dict

            # Create the initial config
            os_db.upsert_config(
                component_id=component_id,
                config=config,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                set_current=body.set_current,
            )
            return ComponentResponse(**component)
        except Exception as e:
            log_error(f"Error creating component: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/components/{component_id}",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_component",
        summary="Get Component",
        description="Retrieve a component by ID.",
    )
    async def get_component(
        request: Request,
        component_id: str = Path(description="Component ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ComponentResponse:
        try:
            component = os_db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting component: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.patch(
        "/components/{component_id}",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="update_component",
        summary="Update Component",
        description="Partially update a component by ID.",
    )
    async def update_component(
        request: Request,
        component_id: str = Path(description="Component ID"),
        body: ComponentUpdate = Body(description="Component fields to update"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ComponentResponse:
        try:
            # First check if component exists
            existing = os_db.get_component(component_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

            # Build update kwargs from provided fields only
            update_kwargs: Dict[str, Any] = {"component_id": component_id}
            if body.name is not None:
                update_kwargs["name"] = body.name
            if body.description is not None:
                update_kwargs["description"] = body.description
            if body.metadata is not None:
                update_kwargs["metadata"] = body.metadata
            if body.component_type is not None:
                update_kwargs["component_type"] = body.component_type

            component = os_db.upsert_component(**update_kwargs)
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error updating component: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete(
        "/components/{component_id}",
        status_code=204,
        operation_id="delete_component",
        summary="Delete Component",
        description="Delete a component by ID.",
    )
    async def delete_component(
        request: Request,
        component_id: str = Path(description="Component ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> None:
        try:
            deleted = os_db.delete_component(component_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error deleting component: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/components/{component_id}/configs",
        response_model=List[ConfigResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_configs",
        summary="List Configs",
        description="List all configs for a component.",
    )
    async def list_configs(
        component_id: str = Path(description="Component ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> List[ConfigResponse]:
        try:
            configs = os_db.list_config_versions(component_id)
            return [ConfigResponse(**c) for c in configs]
        except Exception as e:
            log_error(f"Error listing configs: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/components/{component_id}/configs",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_config",
        summary="Create Config Version",
        description="Create a new config version for a component. Set upsert_version=true to update the current version instead of creating a new one.",
    )
    async def create_config(
        component_id: str = Path(description="Component ID"),
        body: ConfigCreate = Body(description="Config data"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ConfigResponse:
        try:
            # Determine version to update (if overwriting)
            version_to_update = None
            if body.upsert_version:
                component = os_db.get_component(component_id)
                if component and component.get("current_version"):
                    version_to_update = component["current_version"]

            config = os_db.upsert_config(
                component_id=component_id,
                version=version_to_update,
                config=body.config,
                label=body.label,
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
        "/components/{component_id}/configs/current",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_current_config",
        summary="Get Current Config",
        description="Get the current config version for a component.",
    )
    async def get_current_config(
        component_id: str = Path(description="Component ID"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ConfigResponse:
        try:
            config = os_db.get_config(component_id)
            if config is None:
                raise HTTPException(status_code=404, detail=f"No config found for {component_id}")
            return ConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get(
        "/components/{component_id}/configs/{version}",
        response_model=ConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_config",
        summary="Get Config Version",
        description="Get a specific config version by number or label.",
    )
    async def get_component_config(
        component_id: str = Path(description="Component ID"),
        version: str = Path(description="Version number or label"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ConfigResponse:
        try:
            try:
                config = os_db.get_config(component_id, version=int(version))
            except ValueError:
                config = os_db.get_config(component_id, label=version)

            if config is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
            return ConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete(
        "/components/{component_id}/configs/{version}",
        status_code=204,
        operation_id="delete_config",
        summary="Delete Config Version",
        description="Delete a specific config version. Cannot delete the current version.",
    )
    async def delete_component_config(
        component_id: str = Path(description="Component ID"),
        version: str = Path(description="Version number or label"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> None:
        try:
            # Get the version number
            try:
                version_num = int(version)
            except ValueError:
                # It's a label, need to look up the version number
                config = os_db.get_config(component_id, label=version)
                if config is None:
                    raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
                version_num = config.get("version")

            # Check if this is the current version
            component = os_db.get_component(component_id)
            if component and component.get("current_version") == version_num:
                raise HTTPException(status_code=400, detail="Cannot delete the current config version")

            deleted = os_db.delete_config(component_id, version=version_num)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error deleting config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/components/{component_id}/configs/{version}/set-current",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="set_current_config",
        summary="Set Current Config Version",
        description="Set a specific config version as the current version (rollback/promote).",
    )
    async def set_current_config(
        component_id: str = Path(description="Component ID"),
        version: str = Path(description="Version number or label"),
        db_id: Optional[str] = Query(None, description="Database ID"),
    ) -> ComponentResponse:
        try:
            # Get the version number
            try:
                version_num = int(version)
            except ValueError:
                # It's a label, need to look up the version number
                config = os_db.get_config(component_id, label=version)
                if config is None:
                    raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
                version_num = config.get("version")

            # Verify the config exists
            config = os_db.get_config(component_id, version=version_num)
            if config is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")

            # Update the component's current version
            component = os_db.set_current_config(component_id, version=version_num)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

            return ComponentResponse(**component)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error setting current config: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
