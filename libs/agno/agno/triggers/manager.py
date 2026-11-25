"""Pythonic API for managing triggers -- direct DB access, no HTTP."""

import asyncio
import concurrent.futures
import time
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from agno.db.schemas.scheduler import INTERNAL_SCHEDULER_USER_ID, build_run_endpoint
from agno.db.schemas.triggers import (
    EVENT_IGNORED,
    EVENT_PAUSED,
    NO_TRIGGER_ID,
    UNFINISHED_EVENT_STATUSES,
    StoredTrigger,
    TriggerEvent,
    new_trigger_event_id,
)
from agno.run.authorization import (
    arequire_schedule_target,
    current_authorization,
    require_schedule_target,
    stamp_authorization,
)
from agno.triggers.source import CHECK_SENDER_KEY, CHECK_SENDER_SINCE_KEY, RUN_ENDPOINT_KEY, RUN_UNREAD_SINCE_KEY
from agno.utils.log import log_debug

TARGET_TYPES = ("agent", "team", "workflow")
_PROVENANCE_KEYS = {"managed_by", "os_id", "created_by_run_id", "created_by_session_id"}
# What a writer that updates a trigger in place may restate about it.
_RESTATED_PROVENANCE = ("managed_by", "os_id")
# Changing one of these changes what a trigger runs, as whom, or what may start it, so the caller's
# right to run the target is checked again and their authority is saved again. The authority of
# whoever created the trigger was given for what it did then.
_AUTHORITY_FIELDS = {"payload", "target_type", "target_id", "input", "source_id", "events", "continue_on", "filters"}


def _validated(
    name: str,
    source_id: str,
    events: Sequence[str],
    target_type: str,
    target_id: str,
    input: str,
    if_exists: str,
    user_id: Optional[str],
    provenance: Optional[Dict[str, str]],
) -> None:
    if if_exists not in ("raise", "skip", "update"):
        raise ValueError(f"if_exists must be 'raise', 'skip', or 'update', got '{if_exists}'")
    if not name or not name.strip():
        raise ValueError("A trigger needs a name")
    if not source_id:
        raise ValueError(f"Trigger '{name}' needs a source")
    if not events or not all(isinstance(kind, str) and kind for kind in events):
        raise ValueError(f"Trigger '{name}' needs at least one event kind")
    if target_type not in TARGET_TYPES:
        raise ValueError(f"Trigger '{name}': target_type must be one of {TARGET_TYPES}, got '{target_type}'")
    if not target_id:
        raise ValueError(f"Trigger '{name}' needs a target id")
    if not isinstance(input, str) or not input.strip():
        raise ValueError(f"Trigger '{name}' needs an input")
    # A blank or sentinel owner would be rejected by the run route on every fire.
    if user_id is not None and (not user_id.strip() or user_id == INTERNAL_SCHEDULER_USER_ID):
        raise ValueError(f"'{user_id}' is not a usable trigger owner")
    if provenance is not None and not set(provenance) <= _PROVENANCE_KEYS:
        raise ValueError(f"provenance may only carry {sorted(_PROVENANCE_KEYS)}, got {sorted(provenance)}")


def _fields(
    source_id: str,
    events: Sequence[str],
    target_type: str,
    target_id: str,
    input: str,
    continue_on: Optional[Sequence[str]],
    filters: Optional[Dict[str, Any]],
    key_path: Optional[str],
    description: Optional[str],
    payload: Optional[Dict[str, Any]],
    timeout_seconds: int,
    max_retries: int,
    retry_delay_seconds: int,
) -> Dict[str, Any]:
    """The columns both a create and an update-in-place write."""
    return {
        "source_id": source_id,
        "events": list(events),
        "continue_on": list(continue_on or []),
        "filters": dict(filters or {}),
        "target_type": target_type,
        "target_id": target_id,
        "input": input,
        "key_path": key_path,
        "description": description,
        # The caller's authority is saved with the trigger, so its runs act as whoever created it.
        "payload": stamp_authorization(payload),
        "timeout_seconds": timeout_seconds,
        "max_retries": max_retries,
        "retry_delay_seconds": retry_delay_seconds,
    }


def _replayed_event(row: Dict[str, Any]) -> Dict[str, Any]:
    """The stored event a replay starts from, without the marks the first handling left on it."""
    stored = dict(row.get("event") or {})
    for mark in (CHECK_SENDER_SINCE_KEY, RUN_UNREAD_SINCE_KEY, RUN_ENDPOINT_KEY):
        stored.pop(mark, None)
    if row.get("run_id"):
        # The event started a run, so its sender was let through then. One that never ran, such
        # as an event skipped because its trigger was off, was never asked about: it still is.
        stored.pop(CHECK_SENDER_KEY, None)
    return stored


def _replayed(row: Dict[str, Any], trigger: Optional[StoredTrigger]) -> Dict[str, Any]:
    """A new event that runs a stored one again. Raises ValueError when the stored one cannot be replayed."""
    event_id = row["id"]
    if row["trigger_id"] == NO_TRIGGER_ID or trigger is None:
        raise ValueError(f"Event {event_id} belongs to no trigger, so there is nothing to run")
    if row["status"] == EVENT_IGNORED:
        raise ValueError(f"Event {event_id} was ignored and stored without its payload, so it cannot be run")
    if row["status"] in UNFINISHED_EVENT_STATUSES:
        raise ValueError(f"Event {event_id} is still being handled")
    if row["status"] == EVENT_PAUSED:
        raise ValueError(f"Event {event_id} has a paused run; continue or cancel that run instead of replaying")
    if not trigger.enabled:
        raise ValueError(f"Trigger '{trigger.name}' is disabled; enable it before replaying its events")
    return TriggerEvent(
        id=new_trigger_event_id(),
        source_id=row["source_id"],
        # A delivery is stored once for each trigger, so a replay is stored as a delivery of its own.
        delivery_id=f"{row['delivery_id']}:replay:{uuid4().hex[:12]}",
        trigger_id=row["trigger_id"],
        kind=row["kind"],
        event_key=row.get("event_key"),
        event=_replayed_event(row),
        session_id=row.get("session_id"),
        user_id=row.get("user_id"),
        os_id=row.get("os_id"),
    ).to_dict()


class TriggerManager:
    """Direct DB-backed trigger management API.

    Creates, lists, updates and removes event triggers, and reads the events stored for them,
    without going through HTTP.
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def close(self) -> None:
        """Shut down the internal thread pool (if created)."""
        pool = getattr(self, "_pool", None)
        if pool is not None:
            pool.shutdown(wait=False)
            self._pool = None

    def __del__(self) -> None:
        self.close()

    def _call(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call a DB method, handling sync/async transparently."""
        fn = getattr(self.db, method_name)
        if asyncio.iscoroutinefunction(fn):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # No running loop: safe to use asyncio.run directly.
                return asyncio.run(fn(*args, **kwargs))
            # Running inside an async context: bridge via a thread.
            if self._pool is None:
                self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            return self._pool.submit(asyncio.run, fn(*args, **kwargs)).result()
        return fn(*args, **kwargs)

    async def _acall(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        """Async call a DB method."""
        fn = getattr(self.db, method_name)
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        # A sync adapter would hold the event loop for the whole query, so it runs on a worker thread.
        return await asyncio.to_thread(fn, *args, **kwargs)

    @staticmethod
    def _to_trigger(data: Any) -> Optional[StoredTrigger]:
        if data is None or isinstance(data, StoredTrigger):
            return data
        return StoredTrigger.from_dict(data)

    @staticmethod
    def _to_events(data: Any) -> List[TriggerEvent]:
        rows = data[0] if isinstance(data, tuple) else data
        return [TriggerEvent.from_dict(row) if isinstance(row, dict) else row for row in rows or []]

    @staticmethod
    def _new(
        name: str, user_id: Optional[str], enabled: bool, provenance: Optional[Dict[str, str]], fields: Dict
    ) -> Dict:
        row: Dict[str, Any] = {
            "id": str(uuid4()),
            "name": name,
            "user_id": user_id,
            "enabled": enabled,
            "created_at": int(time.time()),
            **fields,
            **(provenance or {}),
        }
        return StoredTrigger.from_dict(row).to_dict()

    @staticmethod
    def _authority_updates(existing: StoredTrigger, updates: Dict[str, Any]) -> bool:
        """Stamp the caller's authority into an update that needs it. True when the target must be checked."""
        if current_authorization() is None and not _AUTHORITY_FIELDS.intersection(updates):
            return False
        updates["payload"] = stamp_authorization(updates["payload"] if "payload" in updates else existing.payload)
        return True

    # --- Sync API ---

    def create(
        self,
        name: str,
        source_id: str,
        events: Sequence[str],
        target_type: str,
        target_id: str,
        input: str,
        continue_on: Optional[Sequence[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        key_path: Optional[str] = None,
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 3600,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        if_exists: str = "raise",
        user_id: Optional[str] = None,
        provenance: Optional[Dict[str, str]] = None,
        enabled_on_create: bool = True,
    ) -> StoredTrigger:
        """Create a trigger.

        Args:
            source_id: The source the events come from, e.g. "github".
            events: The event kinds that start a run, e.g. ["issues.opened"].
            target_type: "agent", "team" or "workflow".
            continue_on: Event kinds that only continue a conversation the trigger already started.
            filters: The source's filter for the events, e.g. labels and who may start a run.
            if_exists: Behaviour when a trigger with the same name already exists. ``"raise"`` (default)
                raises ``ValueError``, ``"skip"`` returns the existing trigger unchanged, ``"update"``
                overwrites it with the supplied values.
            user_id: Owner of the trigger; names are unique per owner. ``None`` leaves it unowned,
                and its runs act as the system.
            provenance: Who wrote the row. ``managed_by`` is "code" for a trigger declared in code.
                ``os_id`` is the AgentOS the trigger belongs to: only that one matches deliveries
                against it and runs its events. With no ``os_id``, any AgentOS that has the source does.
            enabled_on_create: Enabled state written with the insert. An existing trigger keeps its
                stored state, including under ``if_exists="update"``; use enable/disable to change it.
        """
        _validated(name, source_id, events, target_type, target_id, input, if_exists, user_id, provenance)
        # Names are unique within one AgentOS, so the name is looked up where the trigger is stored.
        os_id = (provenance or {}).get("os_id")
        require_schedule_target(build_run_endpoint(target_type, target_id))
        fields = _fields(
            source_id,
            events,
            target_type,
            target_id,
            input,
            continue_on,
            filters,
            key_path,
            description,
            payload,
            timeout_seconds,
            max_retries,
            retry_delay_seconds,
        )

        existing = self._to_trigger(self._call("get_trigger_by_name", name, user_id=user_id, os_id=os_id))
        if existing is None:
            try:
                created = self._to_trigger(
                    self._call("create_trigger", self._new(name, user_id, enabled_on_create, provenance, fields))
                )
            except Exception:
                # Another process declared the same name first: the unique index refused this insert.
                existing = self._to_trigger(self._call("get_trigger_by_name", name, user_id=user_id, os_id=os_id))
                if existing is None:
                    raise
            else:
                if created is None:
                    raise RuntimeError("Failed to create trigger")
                log_debug(f"Trigger '{name}' created (id={created.id})")
                return created
        if if_exists == "skip":
            return existing
        if if_exists == "raise":
            raise ValueError(f"Trigger with name '{name}' already exists")
        fields.update({key: provenance[key] for key in _RESTATED_PROVENANCE if provenance and provenance.get(key)})
        updated = self._to_trigger(self._call("update_trigger", existing.id, user_id=user_id, **fields))
        return updated or existing

    def get(self, trigger_id: str, user_id: Optional[str] = None) -> Optional[StoredTrigger]:
        """Get a trigger by ID."""
        return self._to_trigger(self._call("get_trigger", trigger_id, user_id=user_id))

    def get_by_name(
        self, name: str, user_id: Optional[str] = None, os_id: Optional[str] = None
    ) -> Optional[StoredTrigger]:
        """Get a trigger by name.

        Names are unique for each AgentOS and, within it, for each owner. ``user_id=None`` matches
        only an unowned trigger, and ``os_id=None`` only one tied to no AgentOS.
        """
        return self._to_trigger(self._call("get_trigger_by_name", name, user_id=user_id, os_id=os_id))

    def list(
        self,
        source_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        managed_by: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> List[StoredTrigger]:
        """List one page of triggers, newest first. ``user_id`` scopes the listing to one owner."""
        rows, _ = self._call(
            "get_triggers",
            source_id=source_id,
            enabled=enabled,
            managed_by=managed_by,
            limit=limit,
            page=page,
            user_id=user_id,
        )
        return [StoredTrigger.from_dict(row) for row in rows]

    def update(self, trigger_id: str, user_id: Optional[str] = None, **kwargs: Any) -> Optional[StoredTrigger]:
        """Update a trigger. ``user_id`` filters the row, it does not reassign the owner."""
        existing = self.get(trigger_id, user_id=user_id)
        if existing is None:
            return None
        if self._authority_updates(existing, kwargs):
            require_schedule_target(
                build_run_endpoint(
                    kwargs.get("target_type", existing.target_type), kwargs.get("target_id", existing.target_id)
                )
            )
        return self._to_trigger(self._call("update_trigger", trigger_id, user_id=user_id, **kwargs))

    def enable(self, trigger_id: str, user_id: Optional[str] = None) -> Optional[StoredTrigger]:
        """Enable a trigger and clear the reason it was disabled."""
        return self._to_trigger(
            self._call("update_trigger", trigger_id, user_id=user_id, enabled=True, disabled_reason=None)
        )

    def disable(
        self, trigger_id: str, user_id: Optional[str] = None, reason: Optional[str] = None
    ) -> Optional[StoredTrigger]:
        """Disable a trigger. Events that arrive while it is disabled start nothing."""
        return self._to_trigger(
            self._call("update_trigger", trigger_id, user_id=user_id, enabled=False, disabled_reason=reason)
        )

    def delete(self, trigger_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a trigger and its events."""
        return bool(self._call("delete_trigger", trigger_id, user_id=user_id))

    def get_events(
        self,
        trigger_id: Optional[str] = None,
        source_id: Optional[str] = None,
        statuses: Optional[Sequence[str]] = None,
        limit: int = 20,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> List[TriggerEvent]:
        """List stored events, newest first: the runs a trigger started and the events it ignored, with reasons."""
        return self._to_events(
            self._call(
                "get_trigger_events",
                trigger_id=trigger_id,
                source_id=source_id,
                statuses=list(statuses) if statuses is not None else None,
                limit=limit,
                page=page,
                user_id=user_id,
            )
        )

    def replay_event(self, event_id: str, user_id: Optional[str] = None) -> Optional[TriggerEvent]:
        """Store a finished event again, so its trigger runs it once more.

        The first event keeps its record; the replay is a new event with a run of its own, in the
        same conversation. It waits its turn behind any event for the same key that is not finished.

        Returns:
            The new event, or None when no event has this id.

        Raises:
            ValueError: The event cannot be replayed: it matched no trigger, it was ignored and so
                has no payload, it is still being handled, or its trigger is disabled.
        """
        row = self._call("get_trigger_event", event_id, user_id=user_id)
        if row is None:
            return None
        new = _replayed(row, self.get(row["trigger_id"]) if row["trigger_id"] else None)
        self._call("create_trigger_event", new)
        return TriggerEvent.from_dict(new)

    # --- Async API ---

    async def acreate(
        self,
        name: str,
        source_id: str,
        events: Sequence[str],
        target_type: str,
        target_id: str,
        input: str,
        continue_on: Optional[Sequence[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        key_path: Optional[str] = None,
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 3600,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        if_exists: str = "raise",
        user_id: Optional[str] = None,
        provenance: Optional[Dict[str, str]] = None,
        enabled_on_create: bool = True,
    ) -> StoredTrigger:
        """Async create a trigger. See ``create``."""
        _validated(name, source_id, events, target_type, target_id, input, if_exists, user_id, provenance)
        # Names are unique within one AgentOS, so the name is looked up where the trigger is stored.
        os_id = (provenance or {}).get("os_id")
        await arequire_schedule_target(build_run_endpoint(target_type, target_id))
        fields = _fields(
            source_id,
            events,
            target_type,
            target_id,
            input,
            continue_on,
            filters,
            key_path,
            description,
            payload,
            timeout_seconds,
            max_retries,
            retry_delay_seconds,
        )

        existing = self._to_trigger(await self._acall("get_trigger_by_name", name, user_id=user_id, os_id=os_id))
        if existing is None:
            try:
                created = self._to_trigger(
                    await self._acall("create_trigger", self._new(name, user_id, enabled_on_create, provenance, fields))
                )
            except Exception:
                # Another process declared the same name first: the unique index refused this insert.
                existing = self._to_trigger(
                    await self._acall("get_trigger_by_name", name, user_id=user_id, os_id=os_id)
                )
                if existing is None:
                    raise
            else:
                if created is None:
                    raise RuntimeError("Failed to create trigger")
                log_debug(f"Trigger '{name}' created (id={created.id})")
                return created
        if if_exists == "skip":
            return existing
        if if_exists == "raise":
            raise ValueError(f"Trigger with name '{name}' already exists")
        fields.update({key: provenance[key] for key in _RESTATED_PROVENANCE if provenance and provenance.get(key)})
        updated = self._to_trigger(await self._acall("update_trigger", existing.id, user_id=user_id, **fields))
        return updated or existing

    async def aget(self, trigger_id: str, user_id: Optional[str] = None) -> Optional[StoredTrigger]:
        """Async get a trigger by ID."""
        return self._to_trigger(await self._acall("get_trigger", trigger_id, user_id=user_id))

    async def aget_by_name(
        self, name: str, user_id: Optional[str] = None, os_id: Optional[str] = None
    ) -> Optional[StoredTrigger]:
        """Async get a trigger by name. See ``get_by_name``."""
        return self._to_trigger(await self._acall("get_trigger_by_name", name, user_id=user_id, os_id=os_id))

    async def alist(
        self,
        source_id: Optional[str] = None,
        enabled: Optional[bool] = None,
        managed_by: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> List[StoredTrigger]:
        """Async list one page of triggers, newest first."""
        rows, _ = await self._acall(
            "get_triggers",
            source_id=source_id,
            enabled=enabled,
            managed_by=managed_by,
            limit=limit,
            page=page,
            user_id=user_id,
        )
        return [StoredTrigger.from_dict(row) for row in rows]

    async def aupdate(self, trigger_id: str, user_id: Optional[str] = None, **kwargs: Any) -> Optional[StoredTrigger]:
        """Async update a trigger. ``user_id`` filters the row, it does not reassign the owner."""
        existing = await self.aget(trigger_id, user_id=user_id)
        if existing is None:
            return None
        if self._authority_updates(existing, kwargs):
            await arequire_schedule_target(
                build_run_endpoint(
                    kwargs.get("target_type", existing.target_type), kwargs.get("target_id", existing.target_id)
                )
            )
        return self._to_trigger(await self._acall("update_trigger", trigger_id, user_id=user_id, **kwargs))

    async def aenable(self, trigger_id: str, user_id: Optional[str] = None) -> Optional[StoredTrigger]:
        """Async enable a trigger and clear the reason it was disabled."""
        return self._to_trigger(
            await self._acall("update_trigger", trigger_id, user_id=user_id, enabled=True, disabled_reason=None)
        )

    async def adisable(
        self, trigger_id: str, user_id: Optional[str] = None, reason: Optional[str] = None
    ) -> Optional[StoredTrigger]:
        """Async disable a trigger."""
        return self._to_trigger(
            await self._acall("update_trigger", trigger_id, user_id=user_id, enabled=False, disabled_reason=reason)
        )

    async def adelete(self, trigger_id: str, user_id: Optional[str] = None) -> bool:
        """Async delete a trigger and its events."""
        return bool(await self._acall("delete_trigger", trigger_id, user_id=user_id))

    async def aget_events(
        self,
        trigger_id: Optional[str] = None,
        source_id: Optional[str] = None,
        statuses: Optional[Sequence[str]] = None,
        limit: int = 20,
        page: int = 1,
        user_id: Optional[str] = None,
    ) -> List[TriggerEvent]:
        """Async list stored events, newest first."""
        return self._to_events(
            await self._acall(
                "get_trigger_events",
                trigger_id=trigger_id,
                source_id=source_id,
                statuses=list(statuses) if statuses is not None else None,
                limit=limit,
                page=page,
                user_id=user_id,
            )
        )

    async def areplay_event(self, event_id: str, user_id: Optional[str] = None) -> Optional[TriggerEvent]:
        """Async store a finished event again, so its trigger runs it once more. See ``replay_event``."""
        row = await self._acall("get_trigger_event", event_id, user_id=user_id)
        if row is None:
            return None
        new = _replayed(row, await self.aget(row["trigger_id"]) if row["trigger_id"] else None)
        await self._acall("create_trigger_event", new)
        return TriggerEvent.from_dict(new)
