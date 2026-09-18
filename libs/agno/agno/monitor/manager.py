"""Pythonic API for managing monitors -- direct DB access, no HTTP."""

import asyncio
import concurrent.futures
import time
from typing import Any, Dict, List, Literal, Mapping, Optional, Union
from uuid import uuid4

from agno.db.schemas.monitor import (
    TERMINAL_STATUSES,
    Monitor,
    MonitorEvent,
    resolve_watch_description,
    validate_event_budget,
    validate_restart_budget,
    validate_run_watch_is_bounded,
    validate_watch_path,
    validate_watch_target,
)
from agno.db.schemas.scheduler import INTERNAL_SCHEDULER_USER_ID
from agno.monitor.watch import WatchCommand, normalize_watch_commands
from agno.utils.log import log_debug

# Valid DB method names for the monitor subsystem
MonitorDbMethod = Literal[
    "get_monitor",
    "get_monitor_by_name",
    "get_monitors",
    "create_monitor",
    "update_monitor",
    "delete_monitor",
    "claim_pending_monitor",
    "create_monitor_event",
    "update_monitor_event",
    "get_monitor_event",
    "get_monitor_events",
]


class MonitorManager:
    """Direct DB-backed monitor management API.

    Provides a Pythonic interface for creating, listing, stopping, and
    inspecting monitors without going through HTTP. Used by cookbooks
    and MonitorTools. The MonitorPoller (started by AgentOS) picks up
    pending monitors and runs their commands.
    """

    def __init__(
        self,
        db: Any,
        max_per_user: int = 0,
        base_dir: Optional[str] = None,
        watch_commands: Optional[Mapping[str, Union[str, WatchCommand]]] = None,
    ) -> None:
        """
        Args:
            db: A database adapter implementing the monitor DB methods.
            max_per_user: How many unfinished monitors one owner may have, or 0
                for no limit. Off by default: this is a trusted in-process API,
                the same as calling ``db.*`` directly. Callers whose input is not
                trusted -- MonitorTools, whose caller is a model -- pass a limit.
            base_dir: Root a ``watch_path`` is contained to, defaulting to the
                process's working directory. A path outside it is refused here
                rather than watched, because an event names the files that
                changed and an uncontained watch hands those names to whoever
                can read the monitor's events.
            watch_commands: The watches this deployment declares, as they were
                declared on AgentOS. Only their descriptions are read here: a row
                stores the NAME of a command, so a monitor created without a
                description of its own has nothing but that name to explain it
                later, and the declaration already carries the operator's own
                sentence about what it does.
        """
        self.db = db
        self.max_per_user = max_per_user
        self.base_dir = base_dir
        # Normalised so the bare-string and full declaration forms behave the
        # same here as they do in the executor.
        self.watch_commands = normalize_watch_commands(watch_commands)
        self._is_async = asyncio.iscoroutinefunction(getattr(db, "get_monitor", None))
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def _quota_refusal(self, active: int) -> str:
        return (
            f"Monitor limit reached: {active} unfinished monitors, maximum {self.max_per_user}. "
            "Stop or delete one before creating another."
        )

    def _check_quota(self, user_id: Optional[str]) -> None:
        """Refuse a create that would put this owner over their unfinished ceiling."""
        if self.max_per_user <= 0:
            return
        active = 0
        for unfinished in ("pending", "running", "stopping"):
            _, count = self._call("get_monitors", status=unfinished, limit=1, page=1, user_id=user_id)
            active += count
        if active >= self.max_per_user:
            raise ValueError(self._quota_refusal(active))

    async def _acheck_quota(self, user_id: Optional[str]) -> None:
        """Async variant of _check_quota."""
        if self.max_per_user <= 0:
            return
        active = 0
        for unfinished in ("pending", "running", "stopping"):
            _, count = await self._acall("get_monitors", status=unfinished, limit=1, page=1, user_id=user_id)
            active += count
        if active >= self.max_per_user:
            raise ValueError(self._quota_refusal(active))

    def close(self) -> None:
        """Shut down the internal thread pool (if created)."""
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None

    def __del__(self) -> None:
        self.close()

    def _call(self, method_name: MonitorDbMethod, *args: Any, **kwargs: Any) -> Any:
        """Call a DB method, handling sync/async transparently."""
        fn = getattr(self.db, method_name, None)
        if fn is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(fn):
            try:
                asyncio.get_running_loop()
                # Running inside an async context — bridge via thread
                if self._pool is None:
                    self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                return self._pool.submit(asyncio.run, fn(*args, **kwargs)).result()
            except RuntimeError:
                # No running loop — safe to use asyncio.run directly
                return asyncio.run(fn(*args, **kwargs))
        return fn(*args, **kwargs)

    async def _acall(self, method_name: MonitorDbMethod, *args: Any, **kwargs: Any) -> Any:
        """Async call a DB method."""
        fn = getattr(self.db, method_name, None)
        if fn is None:
            raise NotImplementedError(f"Database does not support {method_name}")
        if asyncio.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        # A sync adapter (SqliteDb, sync PostgresDb) would hold the event loop for the
        # whole query, so it runs on a worker thread.
        return await asyncio.to_thread(fn, *args, **kwargs)

    @staticmethod
    def _to_monitor(data: Any) -> Optional[Monitor]:
        """Convert a DB result to a Monitor object."""
        if data is None:
            return None
        if isinstance(data, Monitor):
            return data
        return Monitor.from_dict(data)

    @staticmethod
    def _to_monitor_list(data: Any) -> List[Monitor]:
        """Convert a list of DB results to Monitor objects."""
        if not data:
            return []
        return [Monitor.from_dict(d) if isinstance(d, dict) else d for d in data]

    @staticmethod
    def _to_event_list(data: Any) -> List[MonitorEvent]:
        """Convert a list of DB results to MonitorEvent objects."""
        if not data:
            return []
        return [MonitorEvent.from_dict(d) if isinstance(d, dict) else d for d in data]

    @staticmethod
    def _build_monitor(
        name: str,
        watch_command: Optional[str],
        endpoint: Optional[str],
        method: str,
        description: Optional[str],
        payload: Optional[Dict[str, Any]],
        timeout_seconds: int,
        persistent: bool,
        max_events: int,
        user_id: Optional[str],
        watch_run_id: Optional[str] = None,
        watch_path: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
        use_default_filter: bool = True,
    ) -> Monitor:
        """Build a new pending Monitor with generated ID and timestamps."""
        return Monitor(
            id=str(uuid4()),
            name=name,
            description=description,
            watch_path=watch_path,
            watch_command=watch_command,
            watch_run_id=watch_run_id,
            exclude=exclude,
            use_default_filter=use_default_filter,
            endpoint=endpoint,
            method=method.upper(),
            payload=payload,
            timeout_seconds=timeout_seconds,
            persistent=persistent,
            max_events=max_events,
            status="pending",
            exit_code=None,
            error=None,
            event_count=0,
            started_at=None,
            finished_at=None,
            locked_by=None,
            locked_at=None,
            user_id=user_id,
            created_at=int(time.time()),
            updated_at=None,
        )

    # --- Sync API ---

    def create(
        self,
        name: str,
        watch_command: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: str = "POST",
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
        persistent: bool = False,
        max_events: int = 100,
        user_id: Optional[str] = None,
        watch_run_id: Optional[str] = None,
        watch_path: Optional[Union[str, List[str]]] = None,
        exclude: Optional[List[str]] = None,
        use_default_filter: bool = True,
    ) -> Monitor:
        """Create a new monitor. It starts as ``pending`` and is picked up by the poller.

        Args:
            name: A unique name for the monitor.
            watch_command: Name of a command declared on AgentOS via ``watch_commands``.
            endpoint: Optional endpoint events are delivered to (e.g. ``/agents/<id>/runs``).
            method: HTTP method for the endpoint (default: ``POST``).
            description: Human-readable description of what is being watched.
                Falls back to the declared command's own description when unset.
            payload: Extra fields merged into each event delivery.
            timeout_seconds: Give up after this deadline (ignored when persistent).
            persistent: Run until stopped, with no timeout.
            max_events: Auto-stop after this many events (0 for unlimited).
            watch_run_id: Follow this run instead of running a command; one event
                is emitted when the run reaches a terminal state.
            watch_path: Watch this file or directory instead -- or several of
                them, which are one watch, not one monitor each; one event is
                emitted per batch of changes, naming what changed. Stored
                resolved and contained inside ``base_dir``.
            exclude: Glob patterns a path watch ignores, matched against both the
                full path and the file name, so ``*.log`` means log files
                anywhere under the watch.
            use_default_filter: Whether the watcher's own exclusions (.git,
                .venv, __pycache__, node_modules, editor swap files) apply. Turn
                it off to watch something on that list.
        """
        validate_watch_target(watch_command, watch_run_id, watch_path)
        validate_run_watch_is_bounded(watch_run_id, persistent)
        validate_event_budget(persistent, max_events, endpoint)
        resolved_path = validate_watch_path(watch_path, self.base_dir, must_exist=True)
        description = resolve_watch_description(description, watch_command, self.watch_commands)
        if user_id is not None and (not user_id.strip() or user_id == INTERNAL_SCHEDULER_USER_ID):
            raise ValueError(f"'{user_id}' is not a usable monitor owner")
        self._check_quota(user_id)

        existing = self._to_monitor(self._call("get_monitor_by_name", name, user_id=user_id))
        if existing is not None:
            raise ValueError(f"Monitor with name '{name}' already exists")

        monitor = self._build_monitor(
            name,
            watch_command,
            endpoint,
            method,
            description,
            payload,
            timeout_seconds,
            persistent,
            max_events,
            user_id,
            watch_run_id,
            resolved_path,
            exclude,
            use_default_filter,
        )
        result = self._to_monitor(self._call("create_monitor", monitor.to_dict()))
        if result is None:
            raise RuntimeError("Failed to create monitor")
        log_debug(f"Monitor '{name}' created (id={result.id})")
        return result

    def list(
        self, status: Optional[str] = None, limit: int = 100, page: int = 1, user_id: Optional[str] = None
    ) -> List[Monitor]:
        """List monitors. ``user_id`` scopes the listing to one owner."""
        result = self._call("get_monitors", status=status, limit=limit, page=page, user_id=user_id)
        # get_monitors returns (monitors_list, total_count) tuple
        monitors_data = result[0] if isinstance(result, tuple) else result
        return self._to_monitor_list(monitors_data)

    def get(self, monitor_id: str, user_id: Optional[str] = None) -> Optional[Monitor]:
        """Get a monitor by ID."""
        return self._to_monitor(self._call("get_monitor", monitor_id, user_id=user_id))

    def update(self, monitor_id: str, user_id: Optional[str] = None, **kwargs: Any) -> Optional[Monitor]:
        """Update a monitor. ``user_id`` filters the row, it does not reassign the owner."""
        return self._to_monitor(self._call("update_monitor", monitor_id, user_id=user_id, **kwargs))

    def delete(self, monitor_id: str, user_id: Optional[str] = None) -> bool:
        """Delete a monitor and its events. A running monitor is killed by the poller."""
        return self._call("delete_monitor", monitor_id, user_id=user_id)

    def stop(self, monitor_id: str, user_id: Optional[str] = None) -> Optional[Monitor]:
        """Request a monitor to stop. Pending monitors stop immediately."""
        monitor = self._to_monitor(self._call("get_monitor", monitor_id, user_id=user_id))
        if monitor is None:
            return None
        # Only an UNCLAIMED pending monitor stops here: once the poller has locked
        # it, the executor is starting, and a "stopped" written into that window is
        # overwritten by the executor's own "running" -- the stop is lost outright,
        # not merely missed later. A claimed row goes through "stopping", which is
        # what the execution that owns it is watching for.
        if monitor.status == "pending" and monitor.locked_by is None:
            return self._to_monitor(self._call("update_monitor", monitor_id, user_id=user_id, status="stopped"))
        if monitor.status in ("pending", "running"):
            return self._to_monitor(self._call("update_monitor", monitor_id, user_id=user_id, status="stopping"))
        return monitor

    def restart(self, monitor_id: str, user_id: Optional[str] = None) -> Optional[Monitor]:
        """Re-arm a finished monitor so the poller picks it up again.

        Old events are kept and ``event_count`` is preserved so the new run's
        event sequence continues monotonically rather than colliding with the
        retained history.
        """
        monitor = self._to_monitor(self._call("get_monitor", monitor_id, user_id=user_id))
        if monitor is None:
            return None
        if monitor.status not in TERMINAL_STATUSES:
            raise ValueError(f"Monitor is {monitor.status}; only finished monitors can be restarted")
        validate_restart_budget(monitor.max_events, monitor.event_count)
        return self._to_monitor(
            self._call(
                "update_monitor",
                monitor_id,
                user_id=user_id,
                status="pending",
                exit_code=None,
                error=None,
                started_at=None,
                finished_at=None,
                locked_by=None,
                locked_at=None,
            )
        )

    def get_events(
        self, monitor_id: str, limit: int = 20, page: int = 1, user_id: Optional[str] = None
    ) -> List[MonitorEvent]:
        """Get the event history for a monitor."""
        result = self._call("get_monitor_events", monitor_id, limit=limit, page=page, user_id=user_id)
        # get_monitor_events returns (events_list, total_count) tuple
        events_data = result[0] if isinstance(result, tuple) else result
        return self._to_event_list(events_data)

    # --- Async API ---

    async def acreate(
        self,
        name: str,
        watch_command: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: str = "POST",
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
        persistent: bool = False,
        max_events: int = 100,
        user_id: Optional[str] = None,
        watch_run_id: Optional[str] = None,
        watch_path: Optional[Union[str, List[str]]] = None,
        exclude: Optional[List[str]] = None,
        use_default_filter: bool = True,
    ) -> Monitor:
        """Async create a new monitor. It starts as ``pending`` and is picked up by the poller.

        Args:
            name: A unique name for the monitor.
            watch_command: Name of a command declared on AgentOS via ``watch_commands``.
            endpoint: Optional endpoint events are delivered to (e.g. ``/agents/<id>/runs``).
            method: HTTP method for the endpoint (default: ``POST``).
            description: Human-readable description of what is being watched.
                Falls back to the declared command's own description when unset.
            payload: Extra fields merged into each event delivery.
            timeout_seconds: Give up after this deadline (ignored when persistent).
            persistent: Run until stopped, with no timeout.
            max_events: Auto-stop after this many events (0 for unlimited).
            watch_run_id: Follow this run instead of running a command; one event
                is emitted when the run reaches a terminal state.
            watch_path: Watch this file or directory instead -- or several of
                them, which are one watch, not one monitor each; one event is
                emitted per batch of changes, naming what changed. Stored
                resolved and contained inside ``base_dir``.
            exclude: Glob patterns a path watch ignores, matched against both the
                full path and the file name, so ``*.log`` means log files
                anywhere under the watch.
            use_default_filter: Whether the watcher's own exclusions (.git,
                .venv, __pycache__, node_modules, editor swap files) apply. Turn
                it off to watch something on that list.
        """
        validate_watch_target(watch_command, watch_run_id, watch_path)
        validate_run_watch_is_bounded(watch_run_id, persistent)
        validate_event_budget(persistent, max_events, endpoint)
        resolved_path = validate_watch_path(watch_path, self.base_dir, must_exist=True)
        description = resolve_watch_description(description, watch_command, self.watch_commands)
        if user_id is not None and (not user_id.strip() or user_id == INTERNAL_SCHEDULER_USER_ID):
            raise ValueError(f"'{user_id}' is not a usable monitor owner")
        await self._acheck_quota(user_id)

        existing = self._to_monitor(await self._acall("get_monitor_by_name", name, user_id=user_id))
        if existing is not None:
            raise ValueError(f"Monitor with name '{name}' already exists")

        monitor = self._build_monitor(
            name,
            watch_command,
            endpoint,
            method,
            description,
            payload,
            timeout_seconds,
            persistent,
            max_events,
            user_id,
            watch_run_id,
            resolved_path,
            exclude,
            use_default_filter,
        )
        result = self._to_monitor(await self._acall("create_monitor", monitor.to_dict()))
        if result is None:
            raise RuntimeError("Failed to create monitor")
        log_debug(f"Monitor '{name}' created (id={result.id})")
        return result

    async def alist(
        self, status: Optional[str] = None, limit: int = 100, page: int = 1, user_id: Optional[str] = None
    ) -> List[Monitor]:
        """Async list monitors. ``user_id`` scopes the listing to one owner."""
        result = await self._acall("get_monitors", status=status, limit=limit, page=page, user_id=user_id)
        # get_monitors returns (monitors_list, total_count) tuple
        monitors_data = result[0] if isinstance(result, tuple) else result
        return self._to_monitor_list(monitors_data)

    async def aget(self, monitor_id: str, user_id: Optional[str] = None) -> Optional[Monitor]:
        """Async get a monitor by ID."""
        return self._to_monitor(await self._acall("get_monitor", monitor_id, user_id=user_id))

    async def aupdate(self, monitor_id: str, user_id: Optional[str] = None, **kwargs: Any) -> Optional[Monitor]:
        """Async update a monitor. ``user_id`` filters the row, it does not reassign the owner."""
        return self._to_monitor(await self._acall("update_monitor", monitor_id, user_id=user_id, **kwargs))

    async def adelete(self, monitor_id: str, user_id: Optional[str] = None) -> bool:
        """Async delete a monitor and its events."""
        return await self._acall("delete_monitor", monitor_id, user_id=user_id)

    async def astop(self, monitor_id: str, user_id: Optional[str] = None) -> Optional[Monitor]:
        """Async request a monitor to stop. Pending monitors stop immediately."""
        monitor = self._to_monitor(await self._acall("get_monitor", monitor_id, user_id=user_id))
        if monitor is None:
            return None
        # Only an UNCLAIMED pending monitor stops here: once the poller has locked
        # it, the executor is starting, and a "stopped" written into that window is
        # overwritten by the executor's own "running" -- the stop is lost outright,
        # not merely missed later. A claimed row goes through "stopping", which is
        # what the execution that owns it is watching for.
        if monitor.status == "pending" and monitor.locked_by is None:
            return self._to_monitor(await self._acall("update_monitor", monitor_id, user_id=user_id, status="stopped"))
        if monitor.status in ("pending", "running"):
            return self._to_monitor(await self._acall("update_monitor", monitor_id, user_id=user_id, status="stopping"))
        return monitor

    async def arestart(self, monitor_id: str, user_id: Optional[str] = None) -> Optional[Monitor]:
        """Async re-arm a finished monitor so the poller picks it up again.

        Old events are kept and ``event_count`` is preserved so the new run's
        event sequence continues monotonically rather than colliding with the
        retained history.
        """
        monitor = self._to_monitor(await self._acall("get_monitor", monitor_id, user_id=user_id))
        if monitor is None:
            return None
        if monitor.status not in TERMINAL_STATUSES:
            raise ValueError(f"Monitor is {monitor.status}; only finished monitors can be restarted")
        validate_restart_budget(monitor.max_events, monitor.event_count)
        return self._to_monitor(
            await self._acall(
                "update_monitor",
                monitor_id,
                user_id=user_id,
                status="pending",
                exit_code=None,
                error=None,
                started_at=None,
                finished_at=None,
                locked_by=None,
                locked_at=None,
            )
        )

    async def aget_events(
        self, monitor_id: str, limit: int = 20, page: int = 1, user_id: Optional[str] = None
    ) -> List[MonitorEvent]:
        """Async get the event history for a monitor."""
        result = await self._acall("get_monitor_events", monitor_id, limit=limit, page=page, user_id=user_id)
        # get_monitor_events returns (events_list, total_count) tuple
        events_data = result[0] if isinstance(result, tuple) else result
        return self._to_event_list(events_data)
