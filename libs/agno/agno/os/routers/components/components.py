import logging
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from agno.db.base import (
    AsyncBaseDb,
    BaseDb,
    ComponentAlreadyExistsError,
    ComponentCycleError,
    ComponentDependencyError,
    ComponentDependencyUnavailableError,
    ComponentDraftRequiredError,
    ComponentLastConfigError,
    ComponentProjection,
    ComponentVersionConflictError,
    ComponentVersionGuard,
)
from agno.db.base import ComponentType as DbComponentType
from agno.db.utils import DB_TABLE_NAME_KEYS
from agno.os.auth import get_authentication_dependency
from agno.os.schema import (
    BadRequestResponse,
    ComponentConfigResponse,
    ComponentCreate,
    ComponentDelete,
    ComponentResponse,
    ComponentRestore,
    ComponentType,
    ComponentUpdate,
    ConfigCreate,
    ConfigDelete,
    ConfigUpdate,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    SetCurrentConfig,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_component_id_from_name

logger = logging.getLogger(__name__)

_STUDIO_CONFIG_KEY = "_agno_studio"
_STUDIO_WRITE_CONFLICT = "Studio-owned components must be mutated through StudioTools."
_LEGACY_COMPONENT_METHODS = (
    "get_component",
    "upsert_component",
    "delete_component",
    "list_components",
    "get_config",
    "upsert_config",
    "delete_config",
    "list_configs",
    "set_current_version",
)


def supports_component_routes(db: Union[BaseDb, AsyncBaseDb]) -> bool:
    """Return whether a DB implements a complete sync component catalog.

    Catalog v2 is an explicit capability because its guarded, atomic contract
    cannot be inferred from method names. Catalog v1 predates the capability
    flag, so retain adapters that override the complete legacy method set even
    when they inherit the old ``False`` default.
    """
    if not isinstance(db, BaseDb):
        return False
    if getattr(db, "component_catalog_api_version", 1) >= 2:
        return bool(getattr(db, "supports_component_persistence", False))
    if getattr(db, "supports_component_persistence", False):
        return True

    db_type = type(db)
    return all(
        getattr(db_type, method_name, None) is not getattr(BaseDb, method_name)
        for method_name in _LEGACY_COMPONENT_METHODS
    )


def _version_guard(latest_version: Optional[int], current_version: Optional[int]) -> ComponentVersionGuard:
    return ComponentVersionGuard(latest_version=latest_version, current_version=current_version)


def _projection_from_config(
    config: Dict[str, Any], *, fallback: Optional[Dict[str, Any]] = None
) -> ComponentProjection:
    """Build the complete component projection owned by one config version."""
    fallback = fallback or {}
    name = config.get("name")
    if not isinstance(name, str):
        name = fallback.get("name")
    if not isinstance(name, str):
        raise ValueError("Component config must resolve to a string name")

    description = config.get("description") if "description" in config else fallback.get("description")
    if description is not None and not isinstance(description, str):
        description = fallback.get("description")
    if description is not None and not isinstance(description, str):
        description = None

    metadata = config.get("metadata") if "metadata" in config else fallback.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        metadata = fallback.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        metadata = None

    return ComponentProjection(
        name=name,
        description=description,
        metadata=deepcopy(metadata),
    )


def _canonicalize_component_config(config: Dict[str, Any], *, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """Embed a complete immutable projection in a generic config payload."""
    canonical = deepcopy(config)
    canonical.update(_projection_from_config(canonical, fallback=fallback))
    return canonical


def _project_component_response(
    component: Dict[str, Any], projection: ComponentProjection, *, current_version: int
) -> Dict[str, Any]:
    """Build the state committed by a pointer mutation without a post-commit read."""
    projected = dict(component)
    projected.update(projection)
    projected["current_version"] = current_version
    return projected


def _append_component_metadata_patch(
    config: Dict[str, Any],
    *,
    patch: ComponentUpdate,
) -> Dict[str, Any]:
    """Copy a generic config and apply the metadata-only edit contract."""
    fields = patch.model_fields_set - {"guard"}
    if not fields:
        raise ValueError("Component update must contain at least one field in addition to guard")
    if "name" in fields and (patch.name is None or not patch.name.strip()):
        raise ValueError("Component name cannot be null or blank")

    result = deepcopy(config)
    if "name" in fields:
        result["name"] = patch.name
    if "description" in fields:
        result["description"] = patch.description
    if "metadata" in fields:
        result["metadata"] = deepcopy(patch.metadata)
    return result


def _reject_reserved_studio_config(config: Dict[str, Any]) -> None:
    """Keep the Studio manifest namespace exclusive to the typed control plane."""
    if _STUDIO_CONFIG_KEY in config:
        raise HTTPException(
            status_code=400,
            detail=f"Config key '{_STUDIO_CONFIG_KEY}' is reserved for StudioTools.",
        )


def _reject_studio_owned_mutation(db: BaseDb, component_id: str, *, include_deleted: bool = False) -> None:
    """Prevent generic lifecycle routes from mutating any Studio-owned version.

    Ownership is derived from immutable config history rather than only the
    latest/current pointer. That keeps this boundary effective even if a raw
    config was appended before the boundary existed.
    """
    kwargs = {"include_deleted": True} if include_deleted else {}
    for config_row in db.list_configs(component_id, include_config=True, **kwargs):
        _reject_studio_owned_config(config_row)


def _reject_studio_owned_config(config_row: Dict[str, Any]) -> None:
    config = config_row.get("config")
    if isinstance(config, dict) and _STUDIO_CONFIG_KEY in config:
        raise HTTPException(status_code=409, detail=_STUDIO_WRITE_CONFLICT)


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


def _resolve_member_links(
    config: Dict[str, Any],
    db: BaseDb,
    registry: Optional[Registry] = None,
    *,
    require_published_pins: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Build ``component_links`` rows for a team config's ``members``.

    A team config references its members as
    ``{"type": "agent", "agent_id": "..."}`` / ``{"type": "team", "team_id": "..."}``.
    This resolves each reference and returns the links that should be persisted
    alongside the config, plus any references that could not be resolved.

    - Members that are persisted DB components get a link row (with the child's
      current version) so the component graph reflects the team structure.
    - Members that are code-defined components (registered with the AgentOS
      instance but not persisted as DB components) are resolved from the
      registry at load time and therefore do not get a link row for drafts.
      Published configs require durable exact-version pins, so code-defined
      and draft-only members are rejected when ``require_published_pins`` is
      true.
    - Members that resolve to neither are returned as unresolved so the caller
      can surface an error instead of silently creating a team with no members.

    Returns:
        A tuple of (links, unresolved_member_ids).
    """
    links: List[Dict[str, Any]] = []
    unresolved: List[str] = []

    members = config["members"] if "members" in config else []
    if not isinstance(members, list):
        raise ValueError("Team config.members must be a list")

    for position, member in enumerate(members):
        if not isinstance(member, dict):
            raise ValueError(f"Team config.members[{position}] must be an object")

        member_type = member.get("type")
        if member_type == "agent":
            child_id = member.get("agent_id")
            if "team_id" in member:
                raise ValueError(f"Team config.members[{position}] must declare exactly one of agent_id or team_id")
            in_registry = bool(registry and child_id and registry.get_agent(child_id) is not None)
        elif member_type == "team":
            child_id = member.get("team_id")
            if "agent_id" in member:
                raise ValueError(f"Team config.members[{position}] must declare exactly one of agent_id or team_id")
            in_registry = bool(registry and child_id and registry.get_team(child_id) is not None)
        else:
            raise ValueError(f"Team config.members[{position}].type must be 'agent' or 'team'")

        if not isinstance(child_id, str) or not child_id:
            reference_field = "agent_id" if member_type == "agent" else "team_id"
            raise ValueError(f"Team config.members[{position}].{reference_field} must be a non-empty string")

        # Prefer a persisted DB component: create a link so the graph is complete.
        child_component = db.get_component(child_id)
        if child_component is not None:
            child_version = child_component.get("current_version")
            if child_version is not None:
                links.append(
                    {
                        "link_kind": "member",
                        "link_key": f"member_{position}",
                        "child_component_id": child_id,
                        "child_version": child_version,
                        "position": position,
                        "meta": {"type": member_type},
                    }
                )
            elif require_published_pins:
                unresolved.append(child_id)
            # A draft-only component (no current_version) may still be used by
            # a draft parent and resolved after it is published.
            continue

        # A code-defined component can be resolved only by the live registry,
        # so it is valid for drafts but cannot satisfy a durable published pin.
        if require_published_pins or not in_registry:
            unresolved.append(child_id)

    return links, unresolved


def _published_member_pin_error(team_name: str, unresolved: List[str]) -> str:
    return (
        f"Cannot publish team '{team_name}': the following members do not have durable published versions: "
        f"{', '.join(unresolved)}. Publish DB-backed members first; code-defined members are supported only in "
        "drafts."
    )


def _unresolved_member_error(team_name: str, unresolved: List[str]) -> str:
    return (
        f"Cannot create team '{team_name}': the following members could not be resolved: {', '.join(unresolved)}. "
        "Referenced agents/teams must exist as components or be registered with the AgentOS instance."
    )


def _component_type_value(component: Dict[str, Any]) -> Optional[str]:
    component_type = component.get("component_type")
    if isinstance(component_type, DbComponentType):
        return component_type.value
    return component_type if isinstance(component_type, str) else None


_WORKFLOW_CONTAINER_FIELDS: Dict[str, Tuple[str, ...]] = {
    "Parallel": ("steps",),
    "Loop": ("steps",),
    "Steps": ("steps",),
    "Condition": ("steps", "else_steps"),
    "Router": ("choices",),
}
_WORKFLOW_STEP_REFS: Dict[str, Tuple[str, str]] = {
    "agent_id": ("step_agent", DbComponentType.AGENT.value),
    "team_id": ("step_team", DbComponentType.TEAM.value),
    "workflow_id": ("step_workflow", DbComponentType.WORKFLOW.value),
}


def _resolve_workflow_links(
    config: Dict[str, Any],
    db: BaseDb,
    registry: Optional[Registry] = None,
    *,
    require_published_pins: bool = False,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Validate a serialized workflow graph and derive its component links.

    The generic components API accepts raw workflow dictionaries, so link rows
    are a server-owned projection of ``config.steps``.  Drafts may reference a
    draft-only DB component or a live registry component without a durable
    link.  Published workflows require every component step to resolve to the
    child's exact current published version.

    Nested workflow containers are walked recursively.  Unknown container
    types, malformed lists, ambiguous Step executors, unresolved functions,
    and duplicate link keys fail closed before any database mutation.
    """
    if "steps" not in config:
        steps: Any = []
    else:
        steps = config["steps"]
    if not isinstance(steps, list):
        raise ValueError("Workflow config.steps must be a list")

    links: List[Dict[str, Any]] = []
    unresolved: List[str] = []
    seen_link_keys: set[Tuple[str, str]] = set()
    position = 0

    def _walk(step: Any, path: str) -> None:
        nonlocal position
        if not isinstance(step, dict):
            raise ValueError(f"Workflow {path} must be an object")

        step_type = step.get("type", "Step")
        if not isinstance(step_type, str) or not step_type:
            raise ValueError(f"Workflow {path}.type must be a non-empty string")

        if step_type in _WORKFLOW_CONTAINER_FIELDS:
            unexpected_refs = [key for key in (*_WORKFLOW_STEP_REFS, "executor_ref") if key in step]
            if unexpected_refs:
                raise ValueError(
                    f"Workflow {path} is a {step_type} container and cannot declare executor references: "
                    f"{', '.join(unexpected_refs)}"
                )
            for field in _WORKFLOW_CONTAINER_FIELDS[step_type]:
                children = step.get(field)
                if children is None and step_type == "Condition" and field == "else_steps":
                    continue
                if not isinstance(children, list):
                    raise ValueError(f"Workflow {path}.{field} must be a list")
                for child_position, child in enumerate(children):
                    _walk(child, f"{path}.{field}[{child_position}]")
            return

        if step_type != "Step":
            raise ValueError(f"Workflow {path} has unsupported step type '{step_type}'")

        reference_fields = [key for key in (*_WORKFLOW_STEP_REFS, "executor_ref") if key in step]
        if len(reference_fields) != 1:
            raise ValueError(
                f"Workflow {path} must declare exactly one of agent_id, team_id, workflow_id, or executor_ref"
            )
        reference_field = reference_fields[0]
        reference = step[reference_field]
        if not isinstance(reference, str) or not reference:
            raise ValueError(f"Workflow {path}.{reference_field} must be a non-empty string")

        leaf_position = position
        position += 1

        if reference_field == "executor_ref":
            function_matches = (
                [function for function in registry.functions if function.__name__ == reference]
                if registry is not None
                else []
            )
            if len(function_matches) > 1:
                raise ValueError(
                    f"Workflow {path}.executor_ref is ambiguous: multiple registered functions are named {reference!r}"
                )
            if len(function_matches) != 1:
                unresolved.append(reference)
            return

        link_kind, expected_type = _WORKFLOW_STEP_REFS[reference_field]
        child_component = db.get_component(reference)
        if child_component is not None:
            actual_type = _component_type_value(child_component)
            if actual_type != expected_type:
                raise ValueError(
                    f"Workflow {path}.{reference_field} references {reference!r}, which is a "
                    f"{actual_type or 'component of unknown type'} instead of a {expected_type}"
                )
            child_version = child_component.get("current_version")
            if child_version is None:
                if require_published_pins:
                    unresolved.append(reference)
                return
            if not isinstance(child_version, int):
                raise ValueError(f"Workflow child {reference!r} has an invalid current_version")

            link_key = step.get("step_id") or step.get("name")
            if not isinstance(link_key, str) or not link_key:
                raise ValueError(
                    f"Workflow {path} must have a non-empty step_id or name when it references a component"
                )
            key = (link_kind, link_key)
            if key in seen_link_keys:
                raise ValueError(f"Workflow contains duplicate {link_kind} link key {link_key!r}")
            seen_link_keys.add(key)
            links.append(
                {
                    "link_kind": link_kind,
                    "link_key": link_key,
                    "child_component_id": reference,
                    "child_version": child_version,
                    "position": leaf_position,
                }
            )
            return

        # Registry-backed agents and teams can be rehydrated only while the
        # live registry is present, so they remain a draft-only convenience.
        in_registry = False
        if registry is not None and reference_field == "agent_id":
            in_registry = registry.get_agent(reference) is not None
        elif registry is not None and reference_field == "team_id":
            in_registry = registry.get_team(reference) is not None
        if require_published_pins or not in_registry:
            unresolved.append(reference)

    for step_position, step in enumerate(steps):
        _walk(step, f"config.steps[{step_position}]")

    return links, unresolved


def _published_workflow_pin_error(workflow_name: str, unresolved: List[str]) -> str:
    return (
        f"Cannot publish workflow '{workflow_name}': the following step references do not have durable "
        f"published versions: {', '.join(unresolved)}. Publish DB-backed agents, teams, and workflows first; "
        "code-defined components are supported only in drafts."
    )


def _unresolved_workflow_ref_error(workflow_name: str, unresolved: List[str]) -> str:
    return (
        f"Cannot create workflow '{workflow_name}': the following step references could not be resolved: "
        f"{', '.join(unresolved)}. Component steps must exist in the catalog or live registry, and function "
        "steps must be registered with the AgentOS instance."
    )


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
    if not supports_component_routes(os_db):
        raise ValueError("Component routes require a database with component persistence support.")
    if getattr(os_db, "component_catalog_api_version", 1) < 2:
        # Keep the old adapter calls and HTTP semantics isolated: accepting a
        # v2 guard and then ignoring it would falsely advertise atomicity.
        from agno.os.routers.components.legacy import attach_legacy_routes

        log_warning(
            f"Database {type(os_db).__name__} uses component catalog API v1; "
            "serving the legacy unguarded Components API"
        )
        return attach_legacy_routes(router=router, db=os_db, registry=registry)
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
        body: ComponentCreate,
    ) -> ComponentResponse:
        try:
            component_id = body.component_id
            if component_id is None:
                component_id = generate_component_id_from_name(body.name)

            # Prepare config - ensure it's a dict and resolve db reference
            config = deepcopy(body.config or {})
            # ComponentCreate's top-level catalog fields are authoritative for
            # version one. Persist them in the immutable config so a later
            # rollback can restore null description/metadata as well as name.
            config.update(
                {
                    "name": body.name,
                    "description": body.description,
                    "metadata": deepcopy(body.metadata),
                }
            )
            _reject_reserved_studio_config(config)
            config = _resolve_db_in_config(config, db, registry)

            # Resolve member references into component links so the component
            # graph reflects the team structure (implements the members TODO).
            links: Optional[List[Dict[str, Any]]] = None
            if body.component_type == ComponentType.TEAM:
                member_links, unresolved = _resolve_member_links(
                    config,
                    db,
                    registry,
                    require_published_pins=body.stage == "published",
                )
                members = config["members"] if "members" in config else []
                if len(members) == 0:
                    log_warning(
                        f"Creating team '{body.name}' without members. "
                        "If this is unintended, add members to the config."
                    )
                else:
                    # Surface unresolved members instead of silently creating a
                    # team whose members render as "unknown" in the UI.
                    if unresolved:
                        if body.stage == "published":
                            detail = _published_member_pin_error(body.name, unresolved)
                        else:
                            detail = _unresolved_member_error(body.name, unresolved)
                        raise HTTPException(
                            status_code=400,
                            detail=detail,
                        )
                    links = member_links or None
            elif body.component_type == ComponentType.WORKFLOW:
                require_published_pins = body.stage == "published"
                workflow_links, unresolved = _resolve_workflow_links(
                    config,
                    db,
                    registry,
                    require_published_pins=require_published_pins,
                )
                if unresolved:
                    detail = (
                        _published_workflow_pin_error(body.name, unresolved)
                        if require_published_pins
                        else _unresolved_workflow_ref_error(body.name, unresolved)
                    )
                    raise HTTPException(status_code=400, detail=detail)
                links = workflow_links or None

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
                links=links,
            )

            return ComponentResponse(**component)
        except HTTPException:
            raise
        except ComponentAlreadyExistsError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ComponentCycleError as e:
            raise HTTPException(status_code=409, detail=str(e))
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
        component_id: str = Path(description="Component ID"),
    ) -> ComponentResponse:
        try:
            component = db.get_component(component_id)
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
        response_model=ComponentConfigResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="update_component",
        summary="Append Component Metadata Draft",
        description="Copy the latest config and append a guarded metadata-only draft edit.",
    )
    async def update_component(
        component_id: str = Path(description="Component ID"),
        body: ComponentUpdate = Body(description="Guarded component metadata edit"),
    ) -> ComponentConfigResponse:
        try:
            existing = db.get_component(component_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            _reject_studio_owned_mutation(db, component_id)

            latest_version = body.guard.latest_version
            if latest_version is None:
                raise HTTPException(status_code=409, detail="Component update requires the latest config version")
            latest = db.get_config(component_id, version=latest_version)
            if latest is None:
                raise HTTPException(status_code=409, detail=f"Latest config {component_id} v{latest_version} not found")
            latest_config = latest.get("config")
            if not isinstance(latest_config, dict):
                raise HTTPException(status_code=400, detail=f"Config {component_id} v{latest_version} is invalid")

            component_type = _component_type_value(existing)
            if component_type is None:
                raise HTTPException(status_code=400, detail=f"Component {component_id} has an invalid type")
            config = _append_component_metadata_patch(
                _canonicalize_component_config(latest_config, fallback=existing),
                patch=body,
            )

            if component_type == DbComponentType.TEAM.value:
                _, unresolved = _resolve_member_links(config, db, registry)
                if unresolved:
                    team_name = config.get("name") or existing.get("name") or component_id
                    raise HTTPException(
                        status_code=400,
                        detail=_unresolved_member_error(str(team_name), unresolved),
                    )
            elif component_type == DbComponentType.WORKFLOW.value:
                _, unresolved = _resolve_workflow_links(config, db, registry)
                if unresolved:
                    workflow_name = config.get("name") or existing.get("name") or component_id
                    raise HTTPException(
                        status_code=400,
                        detail=_unresolved_workflow_ref_error(str(workflow_name), unresolved),
                    )

            # Metadata-only edits copy the exact graph owned by the guarded
            # source version. Publication is the explicit point at which Team
            # and Workflow references are re-resolved to current exact pins.
            links = db.get_links(component_id, latest_version)

            projection = (
                _projection_from_config(config, fallback=existing) if existing.get("current_version") is None else None
            )
            appended = db.upsert_config(
                component_id=component_id,
                config=config,
                stage="draft",
                links=links,
                guard=_version_guard(body.guard.latest_version, body.guard.current_version),
                projection=projection,
            )
            return ComponentConfigResponse(**appended)
        except HTTPException:
            raise
        except ComponentVersionConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ComponentCycleError as e:
            raise HTTPException(status_code=409, detail=str(e))
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
        component_id: str = Path(description="Component ID"),
        body: ComponentDelete = Body(description="Guarded soft-archive request"),
    ) -> None:
        try:
            component = db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            _reject_studio_owned_mutation(db, component_id)

            projection_version = component.get("current_version")
            if projection_version is None:
                projection_version = body.guard.latest_version
            if projection_version is None:
                raise HTTPException(status_code=409, detail="Component archive requires the latest config version")
            projection_config = db.get_config(component_id, version=projection_version)
            if projection_config is None or not isinstance(projection_config.get("config"), dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Config {component_id} v{projection_version} cannot provide an archive projection",
                )

            deleted = db.delete_component(
                component_id,
                hard_delete=False,
                guard=_version_guard(body.guard.latest_version, body.guard.current_version),
                projection=_projection_from_config(projection_config["config"], fallback=component),
            )
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
        except HTTPException:
            raise
        except (ComponentDependencyError, ComponentVersionConflictError) as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error deleting component: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components/{component_id}/restore",
        status_code=204,
        operation_id="restore_component",
        summary="Restore Component",
        description="Restore a guarded soft-archived component without reusing its ID or history.",
    )
    async def restore_component(
        component_id: str = Path(description="Component ID"),
        body: ComponentRestore = Body(description="Guarded restore request"),
    ) -> None:
        try:
            component = db.get_component(component_id, include_deleted=True)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            if component.get("deleted_at") is None:
                raise HTTPException(status_code=409, detail=f"Component {component_id} is not archived")
            _reject_studio_owned_mutation(db, component_id, include_deleted=True)

            projection_version = component.get("current_version")
            if projection_version is None:
                projection_version = body.guard.latest_version
            config_row = db.get_config(
                component_id,
                version=projection_version,
                include_deleted=True,
            )
            if config_row is None or not isinstance(config_row.get("config"), dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Config {component_id} v{projection_version} cannot provide a restore projection",
                )
            _reject_studio_owned_config(config_row)

            restored = db.restore_component(
                component_id,
                guard=_version_guard(body.guard.latest_version, body.guard.current_version),
                projection=_projection_from_config(config_row["config"], fallback=component),
            )
            if not restored:
                raise HTTPException(status_code=409, detail=f"Component {component_id} is not archived")
        except HTTPException:
            raise
        except (ComponentDependencyUnavailableError, ComponentVersionConflictError) as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error restoring component: {str(e)}")
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
            configs = db.list_configs(component_id, include_config=include_config)
            return [ComponentConfigResponse(**c) for c in configs]
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
        component_id: str = Path(description="Component ID"),
        body: ConfigCreate = Body(description="Config data"),
    ) -> ComponentConfigResponse:
        try:
            component = db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            _reject_studio_owned_mutation(db, component_id)

            # Resolve db from config if present
            config_data = _canonicalize_component_config(body.config or {}, fallback=component)
            _reject_reserved_studio_config(config_data)
            config_data = _resolve_db_in_config(config_data, db, registry)

            links = body.links
            component_type = _component_type_value(component)
            if component_type == DbComponentType.TEAM.value:
                if body.links is not None:
                    raise HTTPException(
                        status_code=400,
                        detail="Team links are derived from config.members and must not be supplied by the caller.",
                    )
                require_published_pins = body.stage == "published"
                member_links, unresolved = _resolve_member_links(
                    config_data,
                    db,
                    registry,
                    require_published_pins=require_published_pins,
                )
                if unresolved:
                    team_name = config_data.get("name")
                    if not isinstance(team_name, str) or not team_name:
                        team_name = component.get("name") or component_id
                    detail = (
                        _published_member_pin_error(team_name, unresolved)
                        if require_published_pins
                        else _unresolved_member_error(team_name, unresolved)
                    )
                    raise HTTPException(status_code=400, detail=detail)
                links = member_links or None
            elif component_type == DbComponentType.WORKFLOW.value:
                if body.links is not None:
                    raise HTTPException(
                        status_code=400,
                        detail="Workflow links are derived from config.steps and must not be supplied by the caller.",
                    )
                require_published_pins = body.stage == "published"
                workflow_links, unresolved = _resolve_workflow_links(
                    config_data,
                    db,
                    registry,
                    require_published_pins=require_published_pins,
                )
                if unresolved:
                    workflow_name = config_data.get("name")
                    if not isinstance(workflow_name, str) or not workflow_name:
                        workflow_name = component.get("name") or component_id
                    detail = (
                        _published_workflow_pin_error(workflow_name, unresolved)
                        if require_published_pins
                        else _unresolved_workflow_ref_error(workflow_name, unresolved)
                    )
                    raise HTTPException(status_code=400, detail=detail)
                links = workflow_links or None
            elif body.links is not None:
                raise HTTPException(
                    status_code=400,
                    detail="Agent configs do not support component links; links are owned by Team and Workflow config.",
                )

            config = db.upsert_config(
                component_id=component_id,
                version=None,  # Always create new
                config=config_data,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=links,
                guard=_version_guard(body.guard.latest_version, body.guard.current_version),
                projection=(
                    _projection_from_config(config_data, fallback=component)
                    if body.stage == "published" or component.get("current_version") is None
                    else None
                ),
            )
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except ComponentVersionConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ComponentCycleError as e:
            raise HTTPException(status_code=409, detail=str(e))
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
        summary="Publish Draft Config",
        description="Publish the latest draft config without mutating its payload.",
    )
    async def update_config(
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
        body: ConfigUpdate = Body(description="Guarded draft publication request"),
    ) -> ComponentConfigResponse:
        try:
            component = db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            _reject_studio_owned_mutation(db, component_id)

            target = db.get_config(component_id, version=version)
            if target is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")

            component_type = _component_type_value(component)
            is_team = component_type == DbComponentType.TEAM.value
            is_workflow = component_type == DbComponentType.WORKFLOW.value
            links: List[Dict[str, Any]] = []
            target_config: Dict[str, Any] = {}
            if is_team or is_workflow:
                target_config_data = target.get("config")
                if not isinstance(target_config_data, dict):
                    raise HTTPException(status_code=400, detail=f"Config {component_id} v{version} is invalid")
                target_config = target_config_data

            if is_team:
                member_links, unresolved = _resolve_member_links(
                    target_config,
                    db,
                    registry,
                    require_published_pins=True,
                )
                if unresolved:
                    team_name = target_config.get("name")
                    if not isinstance(team_name, str) or not team_name:
                        team_name = component.get("name") or component_id
                    raise HTTPException(
                        status_code=400,
                        detail=_published_member_pin_error(team_name, unresolved),
                    )
                links = member_links
            elif is_workflow:
                workflow_links, unresolved = _resolve_workflow_links(
                    target_config,
                    db,
                    registry,
                    require_published_pins=True,
                )
                if unresolved:
                    workflow_name = target_config.get("name")
                    if not isinstance(workflow_name, str) or not workflow_name:
                        workflow_name = component.get("name") or component_id
                    raise HTTPException(
                        status_code=400,
                        detail=_published_workflow_pin_error(workflow_name, unresolved),
                    )
                links = workflow_links

            upsert_kwargs: Dict[str, Any] = {
                "component_id": component_id,
                "version": version,
                "stage": body.stage,
                "guard": _version_guard(body.guard.latest_version, body.guard.current_version),
                "projection": _projection_from_config(target["config"], fallback=component),
            }
            if is_team or is_workflow:
                upsert_kwargs["links"] = links

            config = db.upsert_config(
                **upsert_kwargs,
            )
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except ComponentVersionConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ComponentCycleError as e:
            raise HTTPException(status_code=409, detail=str(e))
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
        component_id: str = Path(description="Component ID"),
    ) -> ComponentConfigResponse:
        try:
            config = db.get_current_config(component_id=component_id)
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
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
        body: ConfigDelete = Body(description="Guarded draft-version deletion request"),
    ) -> None:
        try:
            component = db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            _reject_studio_owned_mutation(db, component_id)

            projection_config: Optional[Dict[str, Any]] = None
            current_version = component.get("current_version")
            if isinstance(current_version, int):
                current = db.get_config(component_id, version=current_version)
                if current is not None and isinstance(current.get("config"), dict):
                    projection_config = current["config"]
            else:
                remaining = [
                    row
                    for row in db.list_configs(component_id, include_config=True)
                    if row.get("version") != version and isinstance(row.get("config"), dict)
                ]
                if remaining:
                    projection_config = remaining[0]["config"]

            deleted = db.delete_config(
                component_id,
                version=version,
                guard=_version_guard(body.guard.latest_version, body.guard.current_version),
                projection=(
                    _projection_from_config(projection_config, fallback=component)
                    if projection_config is not None
                    else None
                ),
            )
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
        except HTTPException:
            raise
        except (
            ComponentDependencyError,
            ComponentDraftRequiredError,
            ComponentLastConfigError,
            ComponentVersionConflictError,
        ) as e:
            raise HTTPException(status_code=409, detail=str(e))
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
        component_id: str = Path(description="Component ID"),
        version: int = Path(description="Version number"),
        body: SetCurrentConfig = Body(description="Guarded current-version update"),
    ) -> ComponentResponse:
        try:
            component = db.get_component(component_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            _reject_studio_owned_mutation(db, component_id)

            target = db.get_config(component_id, version=version)
            if target is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
            projection = _projection_from_config(target["config"], fallback=component)

            success = db.set_current_version(
                component_id,
                version=version,
                guard=_version_guard(body.guard.latest_version, body.guard.current_version),
                projection=projection,
            )
            if not success:
                raise HTTPException(
                    status_code=404, detail=f"Component {component_id} or config version {version} not found"
                )

            return ComponentResponse(**_project_component_response(component, projection, current_version=version))
        except HTTPException:
            raise
        except ComponentVersionConflictError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error setting current config: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router
