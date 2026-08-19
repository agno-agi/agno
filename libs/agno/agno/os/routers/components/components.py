import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request

from agno.db.base import (
    AsyncBaseDb,
    BaseDb,
    ComponentArchivedError,
    ComponentCycleError,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentLastConfigError,
    ComponentVersionConflictError,
)
from agno.db.base import ComponentType as DbComponentType
from agno.db.utils import DB_TABLE_NAME_KEYS
from agno.os.auth import get_authentication_dependency
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.schema import (
    BadRequestResponse,
    ComponentConfigResponse,
    ComponentCreate,
    ComponentDeleteRequest,
    ComponentResponse,
    ComponentType,
    ComponentUpdate,
    ConfigCreate,
    ConfigUpdate,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    SetCurrentRequest,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import draft_preview_identity, may_read_draft_configs
from agno.registry import Registry
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_id_from_name, hash_string_sha256

logger = logging.getLogger(__name__)


def _related_component_ids(db: BaseDb, component_id: str, version: Optional[int] = None) -> Set[str]:
    """The ids the graph around a component can name in a conflict message.

    Both directions matter: the parents that pin this component (a delete or
    an archive names them) and the children its live - or explicitly named -
    version pins (a restore or a publish names those instead).
    """
    related: Set[str] = set()
    for link in db.get_dependents(component_id) or []:
        parent_component_id = link.get("parent_component_id")
        if isinstance(parent_component_id, str):
            related.add(parent_component_id)

    versions: Set[int] = set()
    component = db.get_component(component_id, include_deleted=True)
    current_version = component.get("current_version") if isinstance(component, dict) else None
    if isinstance(current_version, int):
        versions.add(current_version)
    if version is not None:
        versions.add(version)
    for pinned_version in versions:
        try:
            child_links = db.get_links(component_id, version=pinned_version) or []
        except NotImplementedError:
            continue
        for link in child_links:
            child_component_id = link.get("child_component_id")
            if isinstance(child_component_id, str):
                related.add(child_component_id)
    return related


def _conflict_detail(
    db: BaseDb,
    component_id: Optional[str],
    scoped_user_id: Optional[str],
    exc: Exception,
    version: Optional[int] = None,
) -> str:
    """409 detail for a conflict, with the ids a scoped caller may not see
    redacted out of it.

    ``db`` is typed sync on purpose: the routes reject an async database, and
    this helper reads the graph inline. An async catalog needs its own branch
    here, not a coroutine handed to ``get_dependents``.

    A ComponentDependencyError embeds component ids in its message and a
    scoped caller must not learn another owner's ids from one. Only those ids
    are substituted: the message itself is preserved, because the true cause
    differs per raise site - a blocking parent, an archived child to restore,
    a draft child to publish - and each carries the remedy the caller needs.
    Re-authoring it as a dependents claim asserts something that is false
    wherever the conflict points at a child.
    """
    detail = str(exc)
    if not isinstance(exc, ComponentDependencyError) or scoped_user_id is None or component_id is None:
        return detail
    try:
        related = _related_component_ids(db, component_id, version)
        foreign = sorted(
            (
                related_id
                for related_id in related
                if related_id != component_id
                and db.get_component(related_id, user_id=scoped_user_id, include_deleted=True) is None
            ),
            key=lambda related_id: (-len(related_id), related_id),
        )
    except Exception:
        # Without the graph there is no telling which ids the caller may see,
        # so none of them can be shown.
        return f"Cannot modify {component_id}: blocked by a related component."
    if not foreign:
        return detail
    # One pass over the whole alternation: substituting id by id could rewrite
    # text a previous substitution just inserted. The lookarounds keep an id
    # that is a prefix of a visible one from matching inside it.
    pattern = re.compile(r"(?<![\w.-])(" + "|".join(re.escape(related_id) for related_id in foreign) + r")(?![\w.-])")
    return pattern.sub("another component", detail)


def _reject_unsupported_guard(guard: Any, supported: str) -> None:
    """400 when the request carries a guard half this route does not check.

    Silently ignoring it lets a caller believe the write was protected.
    ``supported`` is "latest_version" or "current_version"."""
    if guard is None:
        return
    unsupported = "current_version" if supported == "latest_version" else "latest_version"
    if getattr(guard, unsupported, None) is not None:
        raise HTTPException(
            status_code=400,
            detail=f"This route checks guard.{supported} only; guard.{unsupported} is not honoured here. "
            "Remove it, or use the route that enforces it.",
        )


# Typed catalog errors that map to 409 Conflict. They are ValueError
# subclasses, so routes must catch them before any generic ValueError clause
# or they would surface with the wrong status code.
_CONFLICT_ERRORS = (
    ComponentVersionConflictError,
    ComponentArchivedError,
    ComponentDependencyError,
    ComponentCycleError,
    ComponentLastConfigError,
)


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

    Args:
        config: The component config to walk for agent_id/team_id/workflow_id references
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

    Unresolvable IDs are allowed: they may be shared registry/code-defined components.
    A cross-user hit raises 404, not 403, so the error can't confirm the component exists.

    Args:
        db: Database to look up component ownership in
        config: The component config to validate references for
        links: Optional explicit links to validate
        scoped_user_id: The caller's owner id; None (unscoped) skips the check
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


def _validate_pinned_versions_readable(
    db: BaseDb,
    links: Optional[List[Dict[str, Any]]],
    request: Request,
) -> None:
    """Reject a caller-supplied pin at a version that caller may not read.

    ``_validate_referenced_component_ownership`` asks whether the referenced
    COMPONENT is visible; a link also names a VERSION, and visibility is not
    readable depth. Publishing shares one version, so a pin at an unpublished
    version of a shared component would let a caller compose another owner's
    draft into its own component and read it back through the detail routes --
    the disclosure ``GET /components/{id}/configs/{version}`` refuses.

    The refusal is that route's, verbatim, so the two agree and neither
    becomes an oracle for the other. A version that does not exist is left
    alone: the adapter's own pin validation answers that.
    """
    if not links:
        return
    actor, privileged = draft_preview_identity(request)
    if privileged or actor is None:
        return
    for link in links:
        if not isinstance(link, dict):
            continue
        child_id = link.get("child_component_id")
        child_version = link.get("child_version")
        if not isinstance(child_id, str) or not isinstance(child_version, int):
            continue
        try:
            child_row = db.get_component(child_id)
            if child_row is None:
                continue  # Code-defined or absent: not this check's business.
            child_config = db.get_config(component_id=child_id, version=child_version)
        except NotImplementedError:
            return
        if not isinstance(child_config, dict):
            continue
        if child_config.get("stage") != "published" and not may_read_draft_configs(child_row, actor, privileged):
            raise HTTPException(status_code=404, detail=f"Config {child_id} v{child_version} not found")


def _redact_db_connection(value: Any) -> Any:
    """Strip connection-defining fields from every ``db`` block in a config.

    ``_resolve_db_in_config`` stores the resolved database's full ``to_dict()``
    so the component rebuilds without the registry. That dict carries whatever
    the adapter exposes -- ``db_url`` with its credentials on Postgres, a
    ``db_file`` path on SQLite, a plaintext ``password`` on ClickHouse -- and
    publishing a component now makes its config readable by every actor.

    The keep-list is positive, not a list of secrets to remove: an adapter that
    grows a new connection field must not silently start leaking it. What
    survives is what a reader legitimately needs to understand the component --
    which database it points at, and which tables it uses.
    """
    if isinstance(value, list):
        return [_redact_db_connection(item) for item in value]
    if not isinstance(value, dict):
        return value
    redacted = {key: _redact_db_connection(item) for key, item in value.items()}
    db_block = redacted.get("db")
    if isinstance(db_block, dict):
        redacted["db"] = {
            key: item for key, item in db_block.items() if key in ("id", "type") or key.endswith("_table")
        }
    return redacted


def _config_response(
    config: Dict[str, Any], component_row: Optional[Dict[str, Any]], request: Request
) -> ComponentConfigResponse:
    """A config as this caller may read it.

    The owner, an unscoped caller and a privileged one read the config as
    stored; anyone else reads it without the database's connection details.
    """
    actor, privileged = draft_preview_identity(request)
    owner = (component_row or {}).get("user_id")
    if not privileged and actor is not None and owner != actor:
        blob = config.get("config")
        if isinstance(blob, dict):
            config = {**config, "config": _redact_db_connection(blob)}
    return ComponentConfigResponse(**config)


def _require_write_ownership(existing: Dict[str, Any], scoped_user_id: Optional[str], verb: str = "modify") -> None:
    """Refuse a scoped caller writing to a component it does not own.

    Publishing shares a component for reading, running and composing; mutation
    stays owner-scoped. The route has already resolved the row through the
    scoped visibility read, so this refusal is never an existence oracle: a row
    the caller cannot see answered 404 there, and a row it can see - shared
    (unowned), or another owner's published one - gets the honest 403 here.
    """
    if scoped_user_id is None:
        return
    owner = existing.get("user_id")
    if owner is None:
        raise HTTPException(status_code=403, detail=f"Cannot {verb} shared component")
    if owner != scoped_user_id:
        raise HTTPException(status_code=403, detail=f"Cannot {verb} component owned by another user")


def _resolve_member_links(
    config: Dict[str, Any],
    db: BaseDb,
    registry: Optional[Registry] = None,
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
      registry at load time and therefore do not get a link row.
    - Members that resolve to neither are returned as unresolved so the caller
      can surface an error instead of silently creating a team with no members.

    Returns:
        A tuple of (links, unresolved_member_ids).
    """
    links: List[Dict[str, Any]] = []
    unresolved: List[str] = []

    members = config.get("members") or []
    for position, member in enumerate(members):
        if not isinstance(member, dict):
            continue

        member_type = member.get("type")
        if member_type == "agent":
            child_id = member.get("agent_id")
            in_registry = bool(registry and child_id and registry.get_agent(child_id) is not None)
        elif member_type == "team":
            child_id = member.get("team_id")
            in_registry = bool(registry and child_id and registry.get_team(child_id) is not None)
        else:
            continue

        # A member reference is a component id; anything else is caller garbage
        # that would reach the db layer as a bind parameter and 500 there.
        if not child_id or not isinstance(child_id, str):
            continue

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
            # A draft-only component (no current_version) still exists; leave it
            # to be resolved at load time rather than flagging it as unresolved.
            continue

        # Not a DB component. If it is a code-defined component it will be
        # resolved from the registry at load time; otherwise it is unresolved.
        if not in_registry:
            unresolved.append(child_id)

    return links, unresolved


def _resolve_step_links(
    config: Dict[str, Any],
    db: BaseDb,
    registry: Optional[Registry] = None,
) -> List[Dict[str, Any]]:
    """Build ``component_links`` rows for a workflow config's ``steps``.

    The traversal, the link keys and the collision rule are shared with
    ``Workflow.save`` so a workflow written here pins exactly what the same
    workflow written through the SDK pins. The archive and publish guards read
    these rows, and a write that skips them lets a step's agent archive while
    a published workflow still points at it.

    A step whose child is not a persisted component gets no row: it is a
    code-defined component, resolved from the registry at load time. A child
    that exists but has no current version gets none either - a link pins one
    published version, and pinning a draft would refuse the parent's own
    publish.

    Raises:
        WorkflowLinkCollisionError: If two steps share a link key but pin
            different children. It is a ValueError, so the routes answer 400.
    """
    from agno.workflow.workflow import derive_step_links

    def pin_child(link: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        child_component_id = link.get("child_component_id")
        # A step reference is a component id; anything else is caller garbage
        # that would reach the db layer as a bind parameter and 500 there.
        if not child_component_id or not isinstance(child_component_id, str):
            return None
        child_component = db.get_component(child_component_id)
        if child_component is None:
            return None
        child_version = child_component.get("current_version")
        if child_version is None:
            return None
        link["child_version"] = child_version
        return link

    return derive_step_links(
        config.get("steps"),
        pin_child=pin_child,
        workflow_id=config.get("id"),
    )


def _derived_links_for_config(
    component_id: str,
    config: Optional[Dict[str, Any]],
    links: Optional[List[Dict[str, Any]]],
    db: BaseDb,
    registry: Optional[Registry] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Link rows for a team or workflow config saved through the config routes.

    ``create_component`` derives these from the config; the config routes only
    persisted caller-supplied ``links``, so a member or step added by editing a
    config got no link row. Without one the child is not a dependent: it
    archives freely and the parent keeps a reference that resolves to nothing,
    while the same child at create time correctly conflicts.

    Explicit links win - a caller that sent its own link set is authoritative.
    None means "nothing to derive from", which leaves the version's existing
    rows alone; a config that derives nothing returns an empty list, which
    clears them. Collapsing the two would leave a version storing an empty
    composition next to a live link row, and the ex-child could never be
    archived.
    """
    if links is not None:
        return links
    if not isinstance(config, dict):
        return None
    existing = db.get_component(component_id)
    if existing is None:
        return None
    component_type = str(existing.get("component_type"))
    if component_type == ComponentType.TEAM.value:
        derived, _unresolved = _resolve_member_links(config, db, registry)
        # Unresolved members are not raised here: unlike create, an edit may
        # legitimately reference a code-defined member this process cannot see.
        return derived
    if component_type == ComponentType.WORKFLOW.value:
        return _resolve_step_links(config, db, registry)
    return None


def _project_live_version(
    db: BaseDb,
    component_id: str,
    scoped_user_id: Optional[str],
) -> Dict[str, Any]:
    """The catalog row fields the component's live config version owns.

    Publishing re-projects name/description/metadata onto the row inside the
    pointer transaction, so a pointer moved any other way - a rollback - has to
    do the same or listings keep serving the identity of a version that is no
    longer live. The live version is read back from the row rather than taken
    from the version that was asked for: a pointer that moved on since must not
    be projected over.
    """
    component = db.get_component(component_id, user_id=scoped_user_id)
    if component is None:
        return {}
    live_version = component.get("current_version")
    if live_version is None:
        return {}
    row = db.get_config(component_id=component_id, version=live_version)
    config = row.get("config") if isinstance(row, dict) else None
    if not isinstance(config, dict):
        return {}
    projection: Dict[str, Any] = {}
    for field in ("name", "description", "metadata"):
        value = config.get(field)
        if value is not None:
            projection[field] = value
    return projection


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
        include_deleted: bool = Query(
            False, description="Also list archived (soft-deleted) components, marked by a deleted_at timestamp"
        ),
    ) -> PaginatedResponse[ComponentResponse]:
        try:
            start_time_ms = time.time() * 1000
            offset = (page - 1) * limit

            # Exclude components whose IDs are owned by the registry
            exclude_ids = registry.get_all_component_ids() if registry else None

            components, total_count = db.list_components(
                component_type=DbComponentType(component_type.value) if component_type else None,
                include_deleted=include_deleted,
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
        except HTTPException:
            raise
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
                # Owner-derived suffix so two users creating the same name get distinct component_ids.
                if scoped_user_id:
                    component_id = f"{component_id}-{hash_string_sha256(scoped_user_id)[:8]}"

            # Prepare config - ensure it's a dict and resolve db reference
            config = body.config or {}
            config = _resolve_db_in_config(config, db, registry)

            # Resolve member references into component links so the component
            # graph reflects the team structure (implements the members TODO).
            links: Optional[List[Dict[str, Any]]] = None
            if body.component_type == ComponentType.TEAM:
                members = config.get("members")
                if not members or len(members) == 0:
                    log_warning(
                        f"Creating team '{body.name}' without members. "
                        "If this is unintended, add members to the config."
                    )
                else:
                    member_links, unresolved = _resolve_member_links(config, db, registry)
                    # Surface unresolved members instead of silently creating a
                    # team whose members render as "unknown" in the UI.
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
            elif body.component_type == ComponentType.WORKFLOW:
                # A workflow's steps pin their children the same way a team's
                # members do. Unresolved step references are not rejected the
                # way unresolved members are: a step may name a code-defined
                # executor this process cannot see.
                links = _resolve_step_links(config, db, registry) or None

            # Falls back to the unscoped JWT sub so admin-created components still carry an owner.
            creator_user_id = scoped_user_id or getattr(request.state, "user_id", None)

            _validate_referenced_component_ownership(
                db, config, links=links, scoped_user_id=scoped_user_id, own_component_id=component_id
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
                links=links,
                user_id=creator_user_id,
            )

            return ComponentResponse(**component)
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e))
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
        include_deleted: bool = Query(
            False, description="Also return an archived (soft-deleted) component, marked by a deleted_at timestamp"
        ),
    ) -> ComponentResponse:
        try:
            component = db.get_component(
                component_id, user_id=get_scoped_user_id(request), include_deleted=include_deleted
            )
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
            # Reads share on publish; writes stay owner-scoped.
            _require_write_ownership(existing, scoped_user_id)

            # upsert_component has no CAS parameter; the guard is enforced as a
            # pre-check against the row that was just read.
            _reject_unsupported_guard(body.guard, "current_version")
            if body.guard is not None and body.guard.current_version is not None:
                actual_current = existing.get("current_version")
                if actual_current != body.guard.current_version:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Component {component_id} current version is {actual_current}, "
                            f"expected {body.guard.current_version}"
                        ),
                    )

            # ALL body validation precedes the first write: the pointer move
            # below commits immediately, so a late parse failure (a bogus
            # component_type ValueError -> 400) must not land AFTER the pointer
            # already moved - the 400 has to leave the component untouched.
            update_kwargs: Dict[str, Any] = {"component_id": component_id}
            if body.name is not None:
                update_kwargs["name"] = body.name
            if body.description is not None:
                update_kwargs["description"] = body.description
            if body.metadata is not None:
                update_kwargs["metadata"] = body.metadata
            if body.component_type is not None:
                update_kwargs["component_type"] = DbComponentType(body.component_type)

            # Pointer moves go through set_current_version, never through
            # upsert_component: it enforces the published-only dispatch
            # invariant (drafts and tombstones are refused with ValueError ->
            # 400, conflicts with ComponentVersionConflictError -> 409), while
            # upsert_component would write the pointer blindly.
            if body.current_version is not None:
                moved = db.set_current_version(
                    component_id,
                    version=body.current_version,
                    expected_current_version=body.guard.current_version if body.guard else None,
                    user_id=scoped_user_id,
                )
                if not moved:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Config {component_id} v{body.current_version} not found",
                    )
                # The row's identity follows the version that is now live,
                # except where this request sets those fields itself.
                for field, value in _project_live_version(db, component_id, scoped_user_id).items():
                    update_kwargs.setdefault(field, value)

            component = db.upsert_component(**update_kwargs, user_id=scoped_user_id)
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e))
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
        expected_current_version: Optional[int] = Query(
            None, description="Optional compare-and-set guard on the current version"
        ),
        body: Optional[ComponentDeleteRequest] = Body(
            None, description="Optional compare-and-set guard, matching the other guarded routes"
        ),
    ) -> None:
        try:
            scoped_user_id = get_scoped_user_id(request)
            # The other four guarded routes take a ComponentGuard in the body;
            # this one historically took a bare query param. Accept both so a
            # caller who follows the body pattern is honoured rather than
            # silently ignored on the one destructive route, and reject
            # guard.latest_version, which this route cannot enforce.
            body_guard = body.guard if body is not None else None
            _reject_unsupported_guard(body_guard, "current_version")
            if body_guard is not None and body_guard.current_version is not None:
                if expected_current_version is not None and expected_current_version != body_guard.current_version:
                    raise HTTPException(
                        status_code=400,
                        detail="Conflicting guards: expected_current_version query param and "
                        "guard.current_version disagree. Send one.",
                    )
                expected_current_version = body_guard.current_version

            existing = db.get_component(component_id, user_id=scoped_user_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Reads share on publish; writes stay owner-scoped.
            _require_write_ownership(existing, scoped_user_id, verb="delete")
            # The schedule cascade rides the delete inside the adapter, so every
            # delete surface carries it and a cascade failure rolls the archive
            # back rather than leaving an archived component with live schedules.
            deleted = db.delete_component(
                component_id, user_id=scoped_user_id, expected_current_version=expected_current_version
            )
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e))
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error deleting component: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    @router.post(
        "/components/{component_id}/restore",
        response_model=ComponentResponse,
        response_model_exclude_none=True,
        status_code=200,
        operation_id="restore_component",
        summary="Restore Component",
        description="Restore an archived (soft-deleted) component by ID.",
    )
    async def restore_component(
        request: Request,
        component_id: str = Path(description="Component ID"),
    ) -> ComponentResponse:
        try:
            scoped_user_id = get_scoped_user_id(request)
            restored = db.restore_component(component_id, user_id=scoped_user_id)
            if not restored:
                existing = db.get_component(component_id, user_id=scoped_user_id, include_deleted=True)
                if existing is None:
                    raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
                if existing.get("deleted_at") is None:
                    raise HTTPException(status_code=409, detail="Component is not archived")
                # Archived but not restorable by this caller: the row is shared
                # (unowned) and the caller is scoped.
                raise HTTPException(status_code=403, detail="Cannot modify shared component")

            component = db.get_component(component_id, user_id=scoped_user_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            return ComponentResponse(**component)
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e))
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
        request: Request,
        component_id: str = Path(description="Component ID"),
        include_config: bool = Query(True, description="Include full config blob"),
    ) -> List[ComponentConfigResponse]:
        try:
            component_row = db.get_component(component_id, user_id=get_scoped_user_id(request))
            if component_row is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            configs = db.list_configs(component_id, include_config=include_config)
            actor, privileged = draft_preview_identity(request)
            if not may_read_draft_configs(component_row, actor, privileged):
                configs = [c for c in configs if c.get("stage") == "published"]
            return [_config_response(c, component_row, request) for c in configs]
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
            existing = db.get_component(component_id, user_id=scoped_user_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Reads share on publish; writes stay owner-scoped.
            _require_write_ownership(existing, scoped_user_id)
            # Resolve db from config if present
            config_data = body.config or {}
            config_data = _resolve_db_in_config(config_data, db, registry)

            _validate_referenced_component_ownership(
                db,
                config_data,
                links=body.links,
                scoped_user_id=scoped_user_id,
                own_component_id=component_id,
            )
            # A link names a version as well as a component, and visibility is
            # not readable depth.
            _validate_pinned_versions_readable(db, body.links, request)

            _reject_unsupported_guard(body.guard, "latest_version")
            links = _derived_links_for_config(component_id, config_data, body.links, db, registry)
            config = db.upsert_config(
                component_id=component_id,
                version=None,  # Always create new
                config=config_data,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=links,
                expected_latest_version=body.guard.latest_version if body.guard else None,
                user_id=scoped_user_id,
            )
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e))
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
            existing = db.get_component(component_id, user_id=scoped_user_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Reads share on publish; writes stay owner-scoped.
            _require_write_ownership(existing, scoped_user_id)
            # Resolve db from config if present
            config_data = body.config
            if config_data is not None:
                config_data = _resolve_db_in_config(config_data, db, registry)

            _validate_referenced_component_ownership(
                db,
                config_data,
                links=body.links,
                scoped_user_id=scoped_user_id,
                own_component_id=component_id,
            )
            # A link names a version as well as a component, and visibility is
            # not readable depth.
            _validate_pinned_versions_readable(db, body.links, request)

            _reject_unsupported_guard(body.guard, "latest_version")
            links = _derived_links_for_config(component_id, config_data, body.links, db, registry)
            config = db.upsert_config(
                component_id=component_id,
                version=version,  # Always update existing
                config=config_data,
                label=body.label,
                stage=body.stage,
                notes=body.notes,
                links=links,
                expected_latest_version=body.guard.latest_version if body.guard else None,
                user_id=scoped_user_id,
            )
            return ComponentConfigResponse(**config)
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(
                status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e, version=version)
            )
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
            component_row = db.get_component(component_id, user_id=get_scoped_user_id(request))
            if component_row is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            config = db.get_config(component_id)
            if config is None:
                raise HTTPException(status_code=404, detail=f"No current config for {component_id}")
            return _config_response(config, component_row, request)
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
            component_row = db.get_component(component_id, user_id=get_scoped_user_id(request))
            if component_row is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            config = db.get_config(component_id, version=version)
            actor, privileged = draft_preview_identity(request)
            if (
                config is not None
                and config.get("stage") != "published"
                and not may_read_draft_configs(component_row, actor, privileged)
            ):
                # A draft version answers as if absent, so the 404 cannot be read
                # as "exists but withheld".
                config = None

            if config is None:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
            return _config_response(config, component_row, request)
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
            scoped_user_id = get_scoped_user_id(request)
            existing = db.get_component(component_id, user_id=scoped_user_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Reads share on publish; writes stay owner-scoped.
            _require_write_ownership(existing, scoped_user_id, verb="delete")
            # Resolve version number
            deleted = db.delete_config(component_id, version=version, user_id=scoped_user_id)
            if not deleted:
                raise HTTPException(status_code=404, detail=f"Config {component_id} v{version} not found")
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(
                status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e, version=version)
            )
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
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
        body: Optional[SetCurrentRequest] = Body(None, description="Optional guard; an empty POST keeps working"),
    ) -> ComponentResponse:
        try:
            scoped_user_id = get_scoped_user_id(request)
            existing = db.get_component(component_id, user_id=scoped_user_id)
            if existing is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
            # Reads share on publish; writes stay owner-scoped.
            _require_write_ownership(existing, scoped_user_id)
            _reject_unsupported_guard(body.guard if body else None, "current_version")
            success = db.set_current_version(
                component_id,
                version=version,
                expected_current_version=body.guard.current_version if body and body.guard else None,
                user_id=scoped_user_id,
            )
            if not success:
                raise HTTPException(
                    status_code=404, detail=f"Component {component_id} or config version {version} not found"
                )

            # The pointer moved, so the row's name/description/metadata must
            # follow it. The rollback itself is committed either way: a failure
            # here leaves the row stale, which must not fail the request.
            projection = _project_live_version(db, component_id, scoped_user_id)
            if projection:
                try:
                    db.upsert_component(component_id=component_id, **projection, user_id=scoped_user_id)
                except Exception as e:
                    log_warning(f"Rolled back {component_id} to v{version} but could not re-project its row: {e}")

            # Fetch and return updated component
            component = db.get_component(component_id, user_id=scoped_user_id)
            if component is None:
                raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

            return ComponentResponse(**component)
        except HTTPException:
            raise
        except _CONFLICT_ERRORS as e:
            raise HTTPException(
                status_code=409, detail=_conflict_detail(db, component_id, scoped_user_id, e, version=version)
            )
        except ComponentDraftRequiredError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            log_error(f"Error setting current config: {str(e)}")
            raise HTTPException(status_code=500, detail="Internal server error")

    return router
