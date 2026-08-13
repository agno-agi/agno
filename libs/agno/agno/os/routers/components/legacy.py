"""Compatibility Components API for pre-2.9 database adapters.

Catalog-v1 adapters expose independent, unguarded component/config writes.
Keep those request and call shapes separate from the guarded catalog-v2 router
so OpenAPI never promises compare-and-set or atomic lifecycle semantics that a
legacy adapter cannot provide.
"""

import time
from copy import deepcopy
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field

from agno.db.base import BaseDb
from agno.db.base import ComponentType as DbComponentType
from agno.os.schema import (
    ComponentConfigResponse,
    ComponentResponse,
    ComponentType,
    PaginatedResponse,
    PaginationInfo,
)
from agno.registry import Registry
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_component_id_from_name


class LegacyComponentCreate(BaseModel):
    """Pre-2.9 component plus initial mutable config request."""

    name: str = Field(..., description="Display name")
    component_id: Optional[str] = None
    component_type: ComponentType
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None
    label: Optional[str] = None
    stage: str = "draft"
    notes: Optional[str] = None
    set_current: bool = True


class LegacyComponentUpdate(BaseModel):
    """Unguarded catalog-v1 component-row patch."""

    name: Optional[str] = None
    description: Optional[str] = None
    component_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    current_version: Optional[int] = None


class LegacyConfigCreate(BaseModel):
    """Unguarded catalog-v1 config append."""

    config: Dict[str, Any] = Field(..., description="The configuration data")
    version: Optional[int] = None
    label: Optional[str] = None
    stage: str = "draft"
    notes: Optional[str] = None
    links: Optional[List[Dict[str, Any]]] = None
    set_current: bool = True


class LegacyConfigUpdate(BaseModel):
    """Mutable catalog-v1 draft config patch."""

    config: Optional[Dict[str, Any]] = None
    label: Optional[str] = None
    stage: Optional[str] = None
    notes: Optional[str] = None
    links: Optional[List[Dict[str, Any]]] = None


def attach_legacy_routes(router: APIRouter, db: BaseDb, registry: Optional[Registry] = None) -> APIRouter:
    """Attach the exact unguarded API supported by catalog-v1 adapters."""
    # Imported lazily by the v2 module after it has finished initialization,
    # avoiding a module cycle while reusing its DB-reference resolver.
    from agno.os.routers.components.components import _resolve_db_in_config, _resolve_member_links

    @router.get(
        "/components",
        response_model=PaginatedResponse[ComponentResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_components",
        summary="List Components (Legacy Catalog)",
        description="Retrieve components from an unguarded catalog-v1 database adapter.",
    )
    async def list_components(
        component_type: Optional[ComponentType] = Query(None, description="Filter by type"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> PaginatedResponse[ComponentResponse]:
        try:
            start_time_ms = time.time() * 1000
            exclude_ids = registry.get_all_component_ids() if registry else None
            components, total_count = db.list_components(
                component_type=DbComponentType(component_type.value) if component_type else None,
                limit=limit,
                offset=(page - 1) * limit,
                exclude_component_ids=exclude_ids or None,
            )
            return PaginatedResponse(
                data=[ComponentResponse(**component) for component in components],
                meta=PaginationInfo(
                    page=page,
                    limit=limit,
                    total_pages=(total_count + limit - 1) // limit,
                    total_count=total_count,
                    search_time_ms=round(time.time() * 1000 - start_time_ms, 2),
                ),
            )
        except Exception as error:
            log_error(f"Error listing components through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_component",
        summary="Create Component (Legacy Catalog)",
        description="Create a component and config with two non-atomic catalog-v1 writes.",
    )
    async def create_component(body: LegacyComponentCreate) -> ComponentResponse:
        try:
            component_id = body.component_id or generate_component_id_from_name(body.name)
            config = _resolve_db_in_config(deepcopy(body.config or {}), db, registry)

            links: Optional[List[Dict[str, Any]]] = None
            if body.component_type == ComponentType.TEAM:
                members = config.get("members") or []
                if not members:
                    log_warning(
                        f"Creating team '{body.name}' without members. If this is unintended, add members "
                        "to the config."
                    )
                else:
                    member_links, unresolved = _resolve_member_links(config, db, registry)
                    if unresolved:
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"Cannot create team '{body.name}': the following members could not be "
                                f"resolved: {', '.join(unresolved)}. Referenced agents/teams must exist "
                                "as components or be registered with the AgentOS instance."
                            ),
                        )
                    links = member_links or None

            component = db.upsert_component(
                component_id=component_id,
                component_type=DbComponentType(body.component_type.value),
                name=body.name,
                description=body.description,
                metadata=body.metadata,
            )
            db.upsert_config(
                component_id=component_id,
                config=config,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=links,
            )
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            log_error(f"Error creating component through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get(
        "/components/{component_id}",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_component",
        summary="Get Component (Legacy Catalog)",
    )
    async def get_component(component_id: str = Path(description="Component ID")) -> ComponentResponse:
        try:
            component = db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except Exception as error:
            log_error(f"Error getting component through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.patch(
        "/components/{component_id}",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="update_component",
        summary="Update Component (Legacy Catalog)",
        description="Apply an unguarded catalog-v1 component-row patch.",
    )
    async def update_component(
        component_id: str = Path(description="Component ID"),
        body: LegacyComponentUpdate = Body(description="Unguarded component fields"),
    ) -> ComponentResponse:
        try:
            if db.get_component(component_id) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

            update_kwargs: Dict[str, Any] = {"component_id": component_id}
            if body.name is not None:
                update_kwargs["name"] = body.name
            if body.description is not None:
                update_kwargs["description"] = body.description
            if body.metadata is not None:
                update_kwargs["metadata"] = body.metadata
            if body.current_version is not None:
                update_kwargs["current_version"] = body.current_version
            if body.component_type is not None:
                update_kwargs["component_type"] = DbComponentType(body.component_type)
            return ComponentResponse(**db.upsert_component(**update_kwargs))
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            log_error(f"Error updating component through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete(
        "/components/{component_id}",
        status_code=204,
        operation_id="delete_component",
        summary="Delete Component (Legacy Catalog)",
        description="Delete a component without v2 dependency or version guards.",
    )
    async def delete_component(component_id: str = Path(description="Component ID")) -> None:
        try:
            if not db.delete_component(component_id):
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
        except HTTPException:
            raise
        except Exception as error:
            log_error(f"Error deleting component through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get(
        "/components/{component_id}/configs",
        response_model=List[ComponentConfigResponse],
        response_model_exclude_none=True,
        status_code=200,
        operation_id="list_configs",
        summary="List Configs (Legacy Catalog)",
    )
    async def list_configs(
        component_id: str = Path(description="Component ID"),
        include_config: bool = Query(True, description="Include full config blob"),
    ) -> List[ComponentConfigResponse]:
        try:
            return [
                ComponentConfigResponse(**config)
                for config in db.list_configs(component_id, include_config=include_config)
            ]
        except Exception as error:
            log_error(f"Error listing configs through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components/{component_id}/configs",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=201,
        operation_id="create_config",
        summary="Create Config Version (Legacy Catalog)",
        description="Append an unguarded catalog-v1 config version.",
    )
    async def create_config(
        component_id: str = Path(description="Component ID"),
        body: LegacyConfigCreate = Body(description="Unguarded config data"),
    ) -> ComponentConfigResponse:
        try:
            config_data = _resolve_db_in_config(deepcopy(body.config), db, registry)
            config = db.upsert_config(
                component_id=component_id,
                version=None,
                config=config_data,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=body.links,
            )
            return ComponentConfigResponse(**config)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            log_error(f"Error creating config through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.patch(
        "/components/{component_id}/configs/{version}",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="update_config",
        summary="Update Draft Config (Legacy Catalog)",
        description="Mutate a draft through the unguarded catalog-v1 contract.",
    )
    async def update_config(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
        body: LegacyConfigUpdate = Body(description="Unguarded config fields"),
    ) -> ComponentConfigResponse:
        try:
            config_data = deepcopy(body.config)
            if config_data is not None:
                config_data = _resolve_db_in_config(config_data, db, registry)
            config = db.upsert_config(
                component_id=component_id,
                version=version,
                config=config_data,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=body.links,
            )
            return ComponentConfigResponse(**config)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            log_error(f"Error updating config through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get(
        "/components/{component_id}/configs/current",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_current_config",
        summary="Get Current Config (Legacy Catalog)",
        description="Resolve the adapter's historical default config selection.",
    )
    async def get_current_config(component_id: str = Path(description="Component ID")) -> ComponentConfigResponse:
        try:
            config = db.get_config(component_id)
            if config is None:
                raise HTTPException(status_code=404, detail=f"No current config for {component_id}")
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as error:
            log_error(f"Error getting current config through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.get(
        "/components/{component_id}/configs/{version}",
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="get_config",
        summary="Get Config Version (Legacy Catalog)",
    )
    async def get_config_version(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> ComponentConfigResponse:
        try:
            config = db.get_config(component_id, version=version)
            if config is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as error:
            log_error(f"Error getting config through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete(
        "/components/{component_id}/configs/{version}",
        status_code=204,
        operation_id="delete_config",
        summary="Delete Config Version (Legacy Catalog)",
        description="Delete a draft without a v2 compare-and-set guard.",
    )
    async def delete_config_version(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> None:
        try:
            if not db.delete_config(component_id, version=version):
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            log_error(f"Error deleting config through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components/{component_id}/configs/{version}/set-current",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="set_current_config",
        summary="Set Current Config Version (Legacy Catalog)",
        description="Move the current pointer without a v2 compare-and-set guard.",
    )
    async def set_current_config(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> ComponentResponse:
        try:
            if not db.set_current_version(component_id, version=version):
                raise HTTPException(
                    status_code=404,
                    detail=f"Component {component_id} or config version {version} not found",
                )
            component = db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error))
        except Exception as error:
            log_error(f"Error setting current config through catalog v1: {error}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router


__all__ = ["attach_legacy_routes"]
