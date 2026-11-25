"""Trigger API router -- CRUD for event triggers, the sources they listen to, their events and replay."""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from agno.db.schemas.scheduler import build_run_endpoint
from agno.db.schemas.triggers import CODE_MANAGED, NOT_DECLARED_REASON, StoredTrigger
from agno.db.utils import is_unique_violation
from agno.os.middleware.user_scope import get_scoped_user_id
from agno.os.routers.run_permissions import _require_endpoint_permission
from agno.os.routers.triggers.schema import (
    TriggerCreate,
    TriggerEventResponse,
    TriggerResponse,
    TriggerSourceResponse,
    TriggerStateResponse,
    TriggerUpdate,
)
from agno.os.schema import PaginatedResponse, PaginationInfo
from agno.run.authorization import stamp_authorization
from agno.triggers.manager import TriggerManager
from agno.utils.log import log_info

# The fields that decide what a trigger runs and what may start it.
_CHANGES_RUNS = frozenset({"target_type", "target_id", "input", "source_id", "events", "continue_on", "filters"})


def get_trigger_router(os_db: Any, settings: Any, agent_os: Any) -> APIRouter:
    """Factory that creates and returns the trigger router.

    Triggers are data: they are created, changed and removed here. The sources they listen to are
    code, declared in ``interfaces=[...]``, so this API lists them and cannot add one.

    Args:
        os_db: The AgentOS-level DB adapter (must support trigger methods).
        settings: AgnoAPISettings instance.
        agent_os: The AgentOS the routes belong to: its sources, its components and its id.

    Returns:
        An APIRouter with all trigger endpoints attached.
    """
    from agno.os.auth import get_authentication_dependency
    from agno.tools.scheduler import aarchived_endpoint_refusal, adraft_endpoint_refusal, code_defined_probe
    from agno.triggers.runtime import supports_triggers

    router = APIRouter(tags=["Triggers"])
    auth_dependency = get_authentication_dependency(settings)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _manager() -> TriggerManager:
        if not supports_triggers(os_db):
            raise HTTPException(
                status_code=503,
                detail="Triggers are stored in PostgreSQL or SQLite; the configured database does not store them",
            )
        return TriggerManager(os_db)

    def _os_id() -> str:
        return agent_os._trigger_os_id

    def _sources() -> Dict[str, Any]:
        return {source.id: source for source in agent_os._trigger_sources()}

    def _source(source_id: str) -> Any:
        sources = _sources()
        source = sources.get(source_id)
        if source is None:
            declared = ", ".join(sorted(sources)) or "none"
            raise HTTPException(
                status_code=422,
                detail=f"Source '{source_id}' is not declared on this AgentOS. Declared sources: {declared}. "
                "A source is added in code, in interfaces=[...].",
            )
        return source

    def _filters(source: Any, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            return source.validate_filters(filters)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    async def _stored(manager: TriggerManager, trigger_id: str, request: Request) -> StoredTrigger:
        """The caller's trigger on this AgentOS, or 404."""
        trigger = await manager.aget(trigger_id, user_id=get_scoped_user_id(request))
        if trigger is None or trigger.os_id not in (None, _os_id()):
            raise HTTPException(status_code=404, detail="Trigger not found")
        return trigger

    def _require_data(trigger: StoredTrigger, change: str) -> None:
        if trigger.managed_by == CODE_MANAGED:
            raise HTTPException(
                status_code=409,
                detail=f"Trigger '{trigger.name}' is declared in code and cannot be {change} here. Change it in code.",
            )

    async def _require_name_free(manager: TriggerManager, name: str, owner: Optional[str]) -> None:
        # Names are unique within one AgentOS, so the name is looked up among this one's triggers.
        declared = await manager.aget_by_name(name, user_id=None, os_id=_os_id())
        if declared is not None and declared.managed_by == CODE_MANAGED:
            raise HTTPException(status_code=409, detail=f"Trigger '{name}' is declared in code; choose another name")
        if await manager.aget_by_name(name, user_id=owner, os_id=_os_id()) is not None:
            raise HTTPException(status_code=409, detail=f"Trigger with name '{name}' already exists")

    async def _require_target(request: Request, name: str, target_type: str, target_id: str, change: str) -> None:
        """Refuse a target the caller may not run, or one that could only fail when the trigger fires."""
        endpoint = build_run_endpoint(target_type, target_id)
        await _require_endpoint_permission(request, endpoint, "POST", action="trigger")
        # Scoped to the caller: an unscoped probe would tell them that another owner's component exists.
        scoped_user_id = get_scoped_user_id(request)
        archived = await aarchived_endpoint_refusal(os_db, endpoint, user_id=scoped_user_id)
        if archived is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot {change} trigger '{name}': its target {archived[0]} '{archived[1]}' is archived. "
                "Restore the component first.",
            )
        # A run starts the published version, so a target with only a draft could never run.
        probe = code_defined_probe(agent_os.agents, agent_os.teams, agent_os.workflows)
        draft = await adraft_endpoint_refusal(os_db, endpoint, user_id=scoped_user_id, is_code_defined=probe)
        if draft is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot {change} trigger '{name}': its target {draft[0]} '{draft[1]}' has no published "
                "version. Publish it first.",
            )

    def _page(data: List[Dict[str, Any]], total_count: int, limit: int, page: int) -> Any:
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        return PaginatedResponse(
            data=data,
            meta=PaginationInfo(page=page, limit=limit, total_pages=total_pages, total_count=total_count),
        )

    async def _events(
        manager: TriggerManager,
        request: Request,
        trigger_id: Optional[str],
        source_id: Optional[str],
        status: Optional[List[str]],
        event_key: Optional[str],
        limit: int,
        page: int,
    ) -> Any:
        rows, total_count = await manager._acall(
            "get_trigger_events",
            trigger_id=trigger_id,
            source_id=source_id,
            # Only what this AgentOS received: another app on the database has its own events.
            os_id=_os_id(),
            statuses=status or None,
            event_key=event_key,
            limit=limit,
            page=page,
            user_id=get_scoped_user_id(request),
        )
        return _page(rows, total_count, limit, page)

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("/triggers/sources", response_model=List[TriggerSourceResponse])
    async def list_trigger_sources(_: bool = Depends(auth_dependency)) -> List[Dict[str, Any]]:
        return [
            {"id": source.id, "type": source.type, "event_kinds": list(getattr(source, "event_kinds", ()))}
            for source in _sources().values()
        ]

    @router.get("/triggers/events", response_model=PaginatedResponse[TriggerEventResponse])
    async def list_trigger_events(
        request: Request,
        trigger_id: Optional[str] = Query(None),
        source_id: Optional[str] = Query(None),
        status: Optional[List[str]] = Query(None, description="Only events in one of these states."),
        event_key: Optional[str] = Query(None, description="Only events of one conversation, e.g. owner/name#12."),
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[TriggerEventResponse]:
        return await _events(_manager(), request, trigger_id, source_id, status, event_key, limit, page)

    @router.get("/triggers", response_model=PaginatedResponse[TriggerResponse])
    async def list_triggers(
        request: Request,
        source_id: Optional[str] = Query(None),
        enabled: Optional[bool] = Query(None),
        limit: int = Query(100, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[TriggerResponse]:
        # ``None`` means no scoping (admin / isolation off); a string filters to that owner.
        triggers, total_count = await _manager()._acall(
            "get_triggers",
            source_id=source_id,
            enabled=enabled,
            limit=limit,
            page=page,
            user_id=get_scoped_user_id(request),
            os_id=_os_id(),
        )
        return _page(triggers, total_count, limit, page)

    @router.post("/triggers", response_model=TriggerResponse, status_code=201)
    async def create_trigger(
        body: TriggerCreate,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        manager = _manager()
        filters = _filters(_source(body.source_id), body.filters)
        await _require_target(request, body.name, body.target_type, body.target_id, "create")

        # The trigger belongs to the caller, falling back to the unscoped JWT sub so a trigger
        # an admin creates still carries a creator id.
        scoped_user_id = get_scoped_user_id(request)
        creator_user_id = scoped_user_id or getattr(request.state, "user_id", None)
        from agno.os.auth import INTERNAL_SCHEDULER_USER_ID

        if creator_user_id == INTERNAL_SCHEDULER_USER_ID:
            raise HTTPException(status_code=403, detail="The scheduler executor may not own a trigger")
        await _require_name_free(manager, body.name, creator_user_id)

        try:
            # The manager saves the caller's authority with the trigger: its runs act as its creator.
            trigger = await manager.acreate(
                name=body.name,
                source_id=body.source_id,
                events=body.events,
                target_type=body.target_type,
                target_id=body.target_id,
                input=body.input,
                continue_on=body.continue_on,
                filters=filters,
                description=body.description,
                timeout_seconds=body.timeout_seconds,
                max_retries=body.max_retries,
                retry_delay_seconds=body.retry_delay_seconds,
                user_id=creator_user_id,
                provenance={"os_id": _os_id()},
            )
        except ValueError as exc:
            # The name check above races under concurrent creates; the unique index decides.
            status_code = 409 if "already exists" in str(exc) else 422
            raise HTTPException(status_code=status_code, detail=str(exc))
        log_info(f"Trigger '{trigger.name}' created on source {trigger.source_id}")
        return trigger.to_dict()

    @router.get("/triggers/{trigger_id}", response_model=TriggerResponse)
    async def get_trigger(
        trigger_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        return (await _stored(_manager(), trigger_id, request)).to_dict()

    @router.patch("/triggers/{trigger_id}", response_model=TriggerResponse)
    async def update_trigger(
        trigger_id: str,
        body: TriggerUpdate,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        manager = _manager()
        existing = await _stored(manager, trigger_id, request)
        _require_data(existing, "changed")

        updates = body.model_dump(exclude_unset=True)
        if not updates:
            return existing.to_dict()

        if "source_id" in updates or "filters" in updates:
            source = _source(updates.get("source_id", existing.source_id))
            updates["filters"] = _filters(source, updates.get("filters", existing.filters))
        if _CHANGES_RUNS.intersection(updates):
            # What the trigger runs changes, or what may start it. Either way the caller needs the
            # right to run the target, as on create, and the runs act as the caller from here on:
            # the authority saved with the trigger was given for what it did before. A new name, a
            # description or a timing keeps the saved authority.
            await _require_target(
                request,
                existing.name,
                updates.get("target_type", existing.target_type),
                updates.get("target_id", existing.target_id),
                "change",
            )
            updates["payload"] = stamp_authorization(existing.payload)
        if "name" in updates and updates["name"] != existing.name:
            await _require_name_free(manager, updates["name"], existing.user_id)

        try:
            result = await manager._acall("update_trigger", trigger_id, user_id=get_scoped_user_id(request), **updates)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            # The name check above races under concurrent renames; the unique index decides.
            if "name" in updates and is_unique_violation(exc):
                raise HTTPException(status_code=409, detail=f"Trigger with name '{updates['name']}' already exists")
            raise
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to update trigger")
        return result

    @router.delete("/triggers/{trigger_id}", status_code=204)
    async def delete_trigger(
        trigger_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> None:
        manager = _manager()
        existing = await _stored(manager, trigger_id, request)
        # A trigger declared in code would be stored again at the next start.
        _require_data(existing, "deleted")
        if not await manager.adelete(trigger_id, user_id=get_scoped_user_id(request)):
            raise HTTPException(status_code=500, detail="Failed to delete trigger")
        log_info(f"Trigger '{existing.name}' deleted")

    @router.post("/triggers/{trigger_id}/enable", response_model=TriggerStateResponse)
    async def enable_trigger(
        trigger_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        manager = _manager()
        existing = await _stored(manager, trigger_id, request)
        if existing.managed_by == CODE_MANAGED and existing.disabled_reason == NOT_DECLARED_REASON:
            # The code stopped declaring it, and a start turned it off. Declaring it again turns it on.
            raise HTTPException(
                status_code=409,
                detail=f"Trigger '{existing.name}' was declared in code and no longer is. Declare it in code to "
                "turn it on.",
            )
        # Turning it on puts its target back in reach of events, so it needs what creating it needs.
        await _require_target(request, existing.name, existing.target_type, existing.target_id, "enable")
        result = await manager.aenable(trigger_id, user_id=get_scoped_user_id(request))
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to enable trigger")
        log_info(f"Trigger '{existing.name}' enabled")
        return result.to_dict()

    @router.post("/triggers/{trigger_id}/disable", response_model=TriggerStateResponse)
    async def disable_trigger(
        trigger_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        manager = _manager()
        existing = await _stored(manager, trigger_id, request)
        result = await manager.adisable(trigger_id, user_id=get_scoped_user_id(request))
        if result is None:
            raise HTTPException(status_code=500, detail="Failed to disable trigger")
        log_info(f"Trigger '{existing.name}' disabled")
        return result.to_dict()

    @router.get("/triggers/{trigger_id}/events", response_model=PaginatedResponse[TriggerEventResponse])
    async def list_events_of_trigger(
        trigger_id: str,
        request: Request,
        status: Optional[List[str]] = Query(None, description="Only events in one of these states."),
        event_key: Optional[str] = Query(None, description="Only events of one conversation, e.g. owner/name#12."),
        limit: int = Query(20, ge=1, le=1000),
        page: int = Query(1, ge=1),
        _: bool = Depends(auth_dependency),
    ) -> PaginatedResponse[TriggerEventResponse]:
        manager = _manager()
        await _stored(manager, trigger_id, request)
        return await _events(manager, request, trigger_id, None, status, event_key, limit, page)

    @router.post(
        "/triggers/{trigger_id}/events/{event_id}/replay", response_model=TriggerEventResponse, status_code=202
    )
    async def replay_trigger_event(
        trigger_id: str,
        event_id: str,
        request: Request,
        _: bool = Depends(auth_dependency),
    ) -> Dict[str, Any]:
        manager = _manager()
        existing = await _stored(manager, trigger_id, request)
        scoped_user_id = get_scoped_user_id(request)
        row = await manager._acall("get_trigger_event", event_id, user_id=scoped_user_id)
        if row is None or row["trigger_id"] != trigger_id:
            raise HTTPException(status_code=404, detail="Trigger event not found")

        # The replay runs with the authority saved on the trigger, so the caller's own right to run
        # the target is checked first.
        endpoint = build_run_endpoint(existing.target_type, existing.target_id)
        await _require_endpoint_permission(request, endpoint, "POST", action="trigger")

        runtime = getattr(request.app.state, "trigger_runtime", None) or agent_os._get_trigger_runtime()
        if runtime is None:
            raise HTTPException(status_code=503, detail="No trigger source is declared, so no events are run")
        try:
            replay = await manager.areplay_event(event_id, user_id=scoped_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        if replay is None:
            raise HTTPException(status_code=404, detail="Trigger event not found")
        # Stored as a new event; the poller runs it, here at once and on any replica at its next poll.
        runtime.poller.wake()
        log_info(f"Trigger '{existing.name}': event {event_id} replayed as {replay.id}")
        return replay.to_dict()

    return router
