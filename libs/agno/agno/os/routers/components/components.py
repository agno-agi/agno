import logging
import time
from typing import Any, Dict, List, Optional, Set, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.base import ComponentType as DbComponentType
from agno.db.utils import DB_TABLE_NAME_KEYS
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id
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
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_id_from_name, hash_string_sha256

logger = logging.getLogger(__name__)


def _resolve_db_in_config(
    config: Dict[str, Any],
    os_db: BaseDb,
    registry: Optional[Registry] = None,
) -> Dict[str, Any]:
    """
    Resolve db reference in config by looking up in registry or OS db.

    If config contains a db dict with an id, this function will:
    1. Check if the id matches the OS db
    2. Check if the id exists in the registry
    3. Merge the resolved db's connection details with the caller-provided
       fields, with caller-provided fields (e.g. custom table names) taking
       precedence. This preserves user-specified overrides like
       ``session_table`` / ``memory_table`` while still reusing the resolved
       db's connection configuration.

    Args:
        config: The config dict that may contain a db reference
        os_db: The OS database instance
        registry: Optional registry containing registered databases

    Returns:
        Updated config dict with resolved db
    """
    component_db = config.get("db")
    if component_db is not None and isinstance(component_db, dict):
        component_db_id = component_db.get("id")
        if component_db_id is not None:
            resolved_db = None
            # First check if it matches the OS db
            if component_db_id == os_db.id:
                resolved_db = os_db
            # Then check the registry
            elif registry is not None:
                resolved_db = registry.get_db(component_db_id)

            # Merge resolved db with caller-provided table-name overrides.
            # Connection-defining fields (type, db_url, db_file, db_schema,
            # id, ...) always come from the resolved db so the caller can't
            # redirect a referenced db to a different backend. Only the
            # whitelisted table-name keys are taken from the caller.
            if resolved_db is not None:
                resolved_dict = resolved_db.to_dict()
                table_overrides = {key: component_db[key] for key in DB_TABLE_NAME_KEYS if key in component_db}
                config["db"] = {**resolved_dict, **table_overrides}
            else:
                log_error(f"Could not resolve db with id: {component_db_id}")
    elif component_db is None and "db" in config:
        # Explicitly set to None, remove the key
        config.pop("db", None)

    return config


def _collect_referenced_component_ids(
    config: Optional[Dict[str, Any]],
    links: Optional[List[Dict[str, Any]]] = None,
) -> Set[str]:
    """
    Collect every component ID a config or links list references.

    Walks the config recursively picking up agent_id/team_id/workflow_id
    references (team members, workflow steps at any nesting depth) and adds
    the child_component_id of each explicit link.

    Args:
        config: The component config to walk for references
        links: Optional explicit links whose child_component_id is included

    Returns:
        The set of referenced component IDs
    """
    referenced_ids: Set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("agent_id", "team_id", "workflow_id"):
                value = node.get(key)
                if isinstance(value, str):
                    referenced_ids.add(value)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    if config:
        _walk(config)
    for link in links or []:
        child_component_id = link.get("child_component_id")
        if isinstance(child_component_id, str):
            referenced_ids.add(child_component_id)

    return referenced_ids


def _validate_referenced_component_ownership(
    db: BaseDb,
    config: Optional[Dict[str, Any]],
    links: Optional[List[Dict[str, Any]]],
    scoped_user_id: Optional[str],
    own_component_id: Optional[str] = None,
) -> None:
    """
    Reject configs/links that reference components the caller does not own.

    Only applies when the caller is scoped (user isolation on, non-admin).
    IDs that don't resolve to a stored component are allowed — they may refer
    to registry/code-defined components, which are shared. The error mirrors
    the regular not-found response so it doesn't confirm that another user's
    component exists.

    Args:
        db: Database to look up component ownership in
        config: The component config to validate references for
        links: Optional explicit links to validate
        scoped_user_id: The caller's owner id, or None when unscoped
        own_component_id: The component being written, excluded from checks
    """
    if scoped_user_id is None:
        return

    for referenced_id in _collect_referenced_component_ids(config, links):
        if referenced_id == own_component_id:
            continue
        if db.get_component(referenced_id) is None:
            continue
        if db.get_component(referenced_id, user_id=scoped_user_id) is None:
            raise HTTPException(status_code=404, detail=f"Component {referenced_id} not found")


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
    # Component routes require sync database
    if not isinstance(os_db, BaseDb):
        raise ValueError("Component routes require a sync database (BaseDb), not an async database.")
    db: BaseDb = os_db  # Type narrowed after isinstance check

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
        component_type: Optional[ComponentType] = Query(None, description="Filter by type: agent, team, workflow"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(20, ge=1, le=100, description="Items per page"),
    ) -> PaginatedResponse[ComponentResponse]:
        try:
            start_time_ms = time.time() * 1000
            offset = (page - 1) * limit

            # Exclude components whose IDs are owned by the registry
            exclude_ids = registry.get_all_component_ids() if registry else None

            components, total_count = db.list_components(
                component_type=DbComponentType(component_type.value) if component_type else None,
                limit=limit,
                offset=offset,
                exclude_component_ids=exclude_ids or None,
                user_id=get_scoped_user_id(request),
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
            log_error(f"Error listing components: {str(e)}")
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
        request: Request,
        body: ComponentCreate,
    ) -> ComponentResponse:
        try:
            scoped_user_id = get_scoped_user_id(request)
            component_id = body.component_id
            if component_id is None:
                component_id = generate_id_from_name(body.name)
                # Under user isolation, append a short owner-derived hex suffix so two
                # users can both create e.g. "Market Researcher" without colliding on
                # the global component_id. Hashing keeps the owner out of the visible
                # id. Unscoped callers (admin / isolation off) keep the plain id.
                if scoped_user_id:
                    component_id = f"{component_id}-{hash_string_sha256(scoped_user_id)[:8]}"

            # TODO: Create links from config

            # Prepare config - ensure it's a dict and resolve db reference
            config = body.config or {}
            config = _resolve_db_in_config(config, db, registry)

            # Warn if creating a team without members
            if body.component_type == ComponentType.TEAM:
                members = config.get("members")
                if not members or len(members) == 0:
                    log_warning(
                        f"Creating team '{body.name}' without members. "
                        "If this is unintended, add members to the config."
                    )

            # Attribute the created component to the caller. Falls back to
            # ``request.state.user_id`` (the unscoped JWT sub) for the owner
            # column, so even admin-created components carry the creator's id.
            creator_user_id = scoped_user_id or getattr(request.state, "user_id", None)

            # A scoped caller must not reference another user's components as
            # members/steps of the new component.
            _validate_referenced_component_ownership(
                db, config, links=None, scoped_user_id=scoped_user_id, own_component_id=component_id
            )

            component, _config = db.create_component_with_config(
                component_id=component_id,
                component_type=DbComponentType(body.component_type.value),
                name=body.name,
                description=body.description,
                metadata=body.metadata,
                config=config,
                label=body.label,
                stage=body.stage or "draft",
                notes=body.notes,
                user_id=creator_user_id,
            )

            return ComponentResponse(**component)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error creating component: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
    ) -> ComponentResponse:
        try:
            component = db.get_component(component_id, user_id=get_scoped_user_id(request))
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting component: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
        body: ComponentUpdate = Body(description="Component fields to update"),
    ) -> ComponentResponse:
        try:
            scoped_user_id = get_scoped_user_id(request)
            existing = db.get_component(component_id, user_id=scoped_user_id)
            if existing is None:
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

            component = db.upsert_component(**update_kwargs, user_id=scoped_user_id)
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error updating component: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

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
    ) -> None:
        try:
            deleted = db.delete_component(component_id, user_id=get_scoped_user_id(request))
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error deleting component: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
        include_config: bool = Query(True, description="Include full config blob"),
    ) -> List[ComponentConfigResponse]:
        try:
            if db.get_component(component_id, user_id=get_scoped_user_id(request)) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            configs = db.list_configs(component_id, include_config=include_config)
            return [ComponentConfigResponse(**c) for c in configs]
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error listing configs: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
        body: ConfigCreate = Body(description="Config data"),
    ) -> ComponentConfigResponse:
        try:
            scoped_user_id = get_scoped_user_id(request)
            if db.get_component(component_id, user_id=scoped_user_id) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Resolve db from config if present
            config_data = body.config or {}
            config_data = _resolve_db_in_config(config_data, db, registry)

            # A scoped caller must not reference another user's components as
            # members/steps/links of this config version.
            _validate_referenced_component_ownership(
                db, config_data, links=body.links, scoped_user_id=scoped_user_id, own_component_id=component_id
            )

            config = db.upsert_config(
                component_id=component_id,
                version=None,  # Always create new
                config=config_data,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=body.links,
            )
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error creating config: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
        body: ConfigUpdate = Body(description="Config fields to update"),
    ) -> ComponentConfigResponse:
        try:
            scoped_user_id = get_scoped_user_id(request)
            if db.get_component(component_id, user_id=scoped_user_id) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Resolve db from config if present
            config_data = body.config
            if config_data is not None:
                config_data = _resolve_db_in_config(config_data, db, registry)

            # A scoped caller must not reference another user's components as
            # members/steps/links of this config version.
            _validate_referenced_component_ownership(
                db, config_data, links=body.links, scoped_user_id=scoped_user_id, own_component_id=component_id
            )

            config = db.upsert_config(
                component_id=component_id,
                version=version,  # Always update existing
                config=config_data,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=body.links,
            )
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error updating config: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
    ) -> ComponentConfigResponse:
        try:
            if db.get_component(component_id, user_id=get_scoped_user_id(request)) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            config = db.get_config(component_id)
            if config is None:
                raise HTTPException(status_code=404, detail=f"No current config for {component_id}")
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> ComponentConfigResponse:
        try:
            if db.get_component(component_id, user_id=get_scoped_user_id(request)) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            config = db.get_config(component_id, version=version)

            if config is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except Exception as e:
            log_error(f"Error getting config: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.delete(
        "/components/{component_id}/configs/{version}",
        status_code=204,
        operation_id="delete_config",
        summary="Delete Config Version",
        description="Delete a specific draft config version. Cannot delete published or current configs.",
    )
    async def delete_config_version(
        request: Request,
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> None:
        try:
            if db.get_component(component_id, user_id=get_scoped_user_id(request)) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Resolve version number
            deleted = db.delete_config(component_id, version=version)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error deleting config: {str(e)}")
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
        request: Request,
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
    ) -> ComponentResponse:
        try:
            scoped_user_id = get_scoped_user_id(request)
            if db.get_component(component_id, user_id=scoped_user_id) is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            success = db.set_current_version(component_id, version=version)
            if not success:
                raise HTTPException(
                    status_code=404, detail=f"Component {component_id} or config version {version} not found"
                )

            # Fetch and return updated component
            component = db.get_component(component_id, user_id=scoped_user_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

            return ComponentResponse(**component)
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error setting current config: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router
