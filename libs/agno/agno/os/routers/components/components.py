import logging
import time
from token import OP
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request

from agno.db.base import AsyncBaseDb, BaseDb
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    ComponentConfigResponse,
    ComponentCreate,
    ComponentResponse,
    ComponentType,
    ComponentUpdate,
    ConfigCreate,
    ConfigUpdate,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.utils.log import log_error
from agno.utils.string import generate_id_from_name

logger = logging.getLogger(__name__)


def get_components_router(
    os_db: Union[BaseDb, AsyncBaseDb],
    settings: AgnoAPISettings = AgnoAPISettings(),
    registry: Optional[Registry] = None,
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


def attach_routes(
    router: APIRouter, os_db: Union[BaseDb, AsyncBaseDb], registry: Optional[Registry] = None
) -> APIRouter:
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
        component_type: Optional[ComponentType] = Query(None, description="Filter by type: agent, team, workflow"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> PaginatedResponse[ComponentResponse]:
        try:
            start_time_ms = time.time() * 1000
            offset = (page - 1) * limit

            components, total_count = os_db.list_components(
                component_type=component_type,
                limit=limit,
                offset=offset,
            )

            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

            return PaginatedResponse(
                data=[ComponentResponse(**c) for c in components],
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
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_component",
        summary="Create Component",
        description="Create a new component (agent, team, or workflow) with initial config.",
    )
    async def create_component(
        body: ComponentCreate,
    ) -> ComponentResponse:
        try:
            component_id = body.component_id
            if component_id is None:
                component_id = generate_id_from_name(body.name)

            # TODO: Create links from config
            # TODO: Use DB from registry

            # Prepare config - ensure it's a dict
            config = body.config or {}

            db_dict: Dict[str, Any] = {}
            try:
                component_db = config.get("db")
                if component_db is not None:
                    component_db_id = component_db.get("id")
                    if component_db_id is not None and component_db_id == os_db.id:
                        db_dict = os_db.to_dict()
                    else:
                        if registry is not None and registry.dbs is not None and len(registry.dbs) > 0:
                            for db in registry.dbs:
                                if db.id == component_db_id:
                                    db_dict = db.to_dict()
                                    break
            except Exception as e:
                log_error(f"Error getting OS Database: {e}")
                raise HTTPException(status_code=500, detail=str(e))

            config["db"] = db_dict

            component, _config = os_db.create_component_with_config(
                component_id=component_id,
                component_type=body.component_type,
                name=body.name,
                description=body.description,
                metadata=body.metadata,
                config=config,
                label=body.label,
                stage=body.stage or "draft",
                notes=body.notes,
            )

            return ComponentResponse(**component)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error creating component: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

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
        component_id: str = Path(description="Component ID"),
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
            raise HTTPException(status_code=500, detail="Internal server error")

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
        component_id: str = Path(description="Component ID"),
        body: ComponentUpdate = Body(description="Component fields to update"),
    ) -> ComponentResponse:
        try:
            existing = os_db.get_component(component_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

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
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error updating component: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete(
        "/components/{component_id}",
        status_code=204,
        operation_id="delete_component",
        summary="Delete Component",
        description="Delete a component by ID.",
    )
    async def delete_component(
        component_id: str = Path(description="Component ID"),
    ) -> None:
        try:
            deleted = os_db.delete_component(component_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error deleting component: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get(
        "/components/{component_id}/configs",
        response_model=List[ComponentConfigResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_configs",
        summary="List Configs",
        description="List all configs for a component.",
    )
    async def list_configs(
        component_id: str = Path(description="Component ID"),
        include_config: bool = Query(True, description="Include full config blob"),
    ) -> List[ComponentConfigResponse]:
        try:
            configs = os_db.list_configs(component_id, include_config=include_config)
            return [ComponentConfigResponse(**c) for c in configs]
        except Exception as e:
            log_error(f"Error listing configs: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components/{component_id}/configs",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_config",
        summary="Create Config Version",
        description="Create a new config version for a component.",
    )
    async def create_config(
        component_id: str = Path(description="Component ID"),
        body: ConfigCreate = Body(description="Config data"),
    ) -> ComponentConfigResponse:
        try:
            config = os_db.upsert_config(
                component_id=component_id,
                version=None,  # Always create new
                config=body.config,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=body.links,
            )
            return ComponentConfigResponse(**config)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error creating config: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.patch(
        "/components/{component_id}/configs/{version}",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="update_config",
        summary="Update Draft Config",
        description="Update an existing draft config. Cannot update published configs.",
    )
    async def update_config(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
        body: ConfigUpdate = Body(description="Config fields to update"),
    ) -> ComponentConfigResponse:
        try:
            config = os_db.upsert_config(
                component_id=component_id,
                version=version,  # Always update existing
                config=body.config,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=body.links,
            )
            return ComponentConfigResponse(**config)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error updating config: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get(
        "/components/{component_id}/configs/current",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_current_config",
        summary="Get Current Config",
        description="Get the current config version for a component.",
    )
    async def get_current_config(
        component_id: str = Path(description="Component ID"),
    ) -> ComponentConfigResponse:
        try:
            config = os_db.get_config(component_id)
            if config is None:
                raise HTTPException(status_code=404, detail=f"No current config for {component_id}")
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get(
        "/components/{component_id}/configs/{version}",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_config",
        summary="Get Config Version",
        description="Get a specific config version by number.",
    )
    async def get_config_version(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> ComponentConfigResponse:
        try:
            config = os_db.get_config(component_id, version=version)

            if config is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete(
        "/components/{component_id}/configs/{version}",
        status_code=204,
        operation_id="delete_config",
        summary="Delete Config Version",
        description="Delete a specific draft config version. Cannot delete published or current configs.",
    )
    async def delete_config_version(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> None:
        try:
            # Resolve version number
            deleted = os_db.delete_config(component_id, version=version)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error deleting config: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components/{component_id}/configs/{version}/set-current",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="set_current_config",
        summary="Set Current Config Version",
        description="Set a published config version as current (for rollback).",
    )
    async def set_current_config(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> ComponentResponse:
        try:
            success = os_db.set_current_version(component_id, version=version)
            if not success:
                raise HTTPException(
                    status_code=404, detail=f"Component {component_id} or config version {version} not found"
                )

            # Fetch and return updated component
            component = os_db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

            return ComponentResponse(**component)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error setting current config: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router
