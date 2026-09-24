"""Monitor poller -- periodically claims and executes pending monitors."""

import asyncio
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Set, Union
from uuid import uuid4

from agno.db.schemas.monitor import Monitor
from agno.db.utils import implements_db_method
from agno.utils.log import log_debug, log_error, log_info, log_warning

# Default timeout (in seconds) when stopping the poller
_DEFAULT_STOP_TIMEOUT = 30

# How often the retention sweep runs, and how long events are kept by default
_CLEANUP_INTERVAL = 3600
_DEFAULT_RETENTION = 7 * 24 * 3600

# Shortest grace that still outlives a healthy monitor's heartbeat. Beats are
# one third of the grace apart, and the floor of 1s that _heartbeat_loop applies
# starts biting below this -- at which point a live monitor's lock can expire
# between beats and the poller reclaims its own work.
MIN_LOCK_GRACE_SECONDS = 6

# How long a claim may go unrefreshed before a peer may take it. Much tighter
# than the scheduler's 300s because a monitor is heartbeated three times inside
# every grace window -- the scheduler has no heartbeat at all, so it has to
# assume the worst. A long grace here is a window where a dead worker's monitors
# still read as "running" to everyone asking.
_DEFAULT_LOCK_GRACE = 30

# Fraction of this worker's slots any one owner may hold when no explicit
# per-owner cap is configured. A quarter leaves room for three more tenants
# behind the greediest one.
_DEFAULT_PER_USER_SLOT_DIVISOR = 4


class MonitorPoller:
    """Periodically poll the DB for pending monitors and execute them.

    Each poll tick repeatedly calls ``db.claim_pending_monitor()`` until no more
    monitors are pending, spawning an ``asyncio.create_task`` for each claimed
    monitor so they run concurrently. The claimed monitor is handed to the
    executor, which runs its command and streams its events.
    """

    def __init__(
        self,
        db: Any,
        executor: Any,
        poll_interval: int = 5,
        worker_id: Optional[str] = None,
        max_concurrent: int = 10,
        stop_timeout: int = _DEFAULT_STOP_TIMEOUT,
        lock_grace_seconds: int = _DEFAULT_LOCK_GRACE,
        retention_seconds: int = _DEFAULT_RETENTION,
        max_concurrent_per_user: Optional[int] = None,
    ) -> None:
        self.db = db
        self.executor = executor
        self.poll_interval = poll_interval
        self.worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self.max_concurrent = max_concurrent
        self.stop_timeout = stop_timeout
        self.lock_grace_seconds = lock_grace_seconds
        self.retention_seconds = retention_seconds
        self.max_concurrent_per_user = (
            max(1, max_concurrent // _DEFAULT_PER_USER_SLOT_DIVISOR)
            if max_concurrent_per_user is None
            else max_concurrent_per_user
        )
        self._last_cleanup = 0.0
        # Names of the monitors holding slots when the cap was last hit, so the
        # warning is logged once per starvation rather than on every tick.
        self._starved_on: Optional[str] = None
        self._task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._heartbeat_task: Optional[asyncio.Task] = None  # type: ignore[type-arg]
        self._running = False
        self._in_flight: Set[asyncio.Task] = set()  # type: ignore[type-arg]
        # Keyed by monitor id, not name: names are unique per OWNER, so two
        # tenants can each run a "log-watch" and one would evict the other's
        # slot entry when it finished, under-reporting who holds the cap. The
        # whole row is kept because the owner and the display name are both read
        # off it every tick.
        self._running_slots: Dict[str, Monitor] = {}

    async def start(self) -> None:
        """Start the polling loop as a background task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        # The lock heartbeat is the poller's job, not each executor's: it knows
        # every monitor this worker holds, so one statement per beat refreshes
        # all of them instead of one statement per monitor per beat.
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        log_info(f"Monitor poller started (worker={self.worker_id}, interval={self.poll_interval}s)")

    async def stop(self) -> None:
        """Stop the polling loop gracefully and cancel in-flight monitors."""
        self._running = False
        # Stop CLAIMING first, but leave the heartbeat alive: the drain below can
        # take stop_timeout seconds, and monitors still winding down need their
        # leases kept fresh for all of it or a peer reclaims work that is alive.
        if self._task is not None:
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=self.stop_timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None
        # Cancel and await all in-flight execution tasks
        for task in list(self._in_flight):
            task.cancel()
        if self._in_flight:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._in_flight, return_exceptions=True),
                    timeout=self.stop_timeout,
                )
            except asyncio.TimeoutError as e:
                log_warning(
                    f"Timed out waiting for {len(self._in_flight)} in-flight monitors during shutdown: {e}",
                )

            self._in_flight.clear()
            self._running_slots.clear()
        # Only now that nothing is executing does the heartbeat have nothing left
        # to keep alive. Its loop condition already covers the drain, so this is a
        # backstop for a loop parked mid-sleep.
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await asyncio.wait_for(self._heartbeat_task, timeout=self.stop_timeout)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._heartbeat_task = None
        # Close the executor's httpx client
        if hasattr(self.executor, "close"):
            await self.executor.close()
        log_info("Monitor poller stopped")

    async def _poll_loop(self) -> None:
        """Main loop: poll first, then sleep."""
        import time as _time

        while self._running:
            try:
                await self._poll_once()
                # Events accrue under live persistent watches, so nothing prunes
                # them unless something does it on a timer. Guarded on the method
                # existing so an adapter without it is skipped, not broken.
                if (
                    self.retention_seconds > 0
                    and _time.time() - self._last_cleanup > _CLEANUP_INTERVAL
                    and implements_db_method(self.db, "cleanup_monitor_events")
                ):
                    self._last_cleanup = _time.time()
                    await self._cleanup_events()
                if not self._running:
                    break
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_error(f"Monitor poll error: {exc}")
                await asyncio.sleep(self.poll_interval)

    async def _heartbeat_loop(self) -> None:
        """Refresh the lock on every monitor this worker holds, on one timer.

        The cadence is derived from the grace rather than fixed: three beats
        inside one grace window means two can be lost -- to a slow query, a
        blocked loop -- before a peer is entitled to call this worker dead and
        reclaim work that is still running.
        """
        interval = max(1.0, self.lock_grace_seconds / 3)
        # Runs while claiming OR draining. stop() flips _running before the drain,
        # so a bare `while self._running` would kill the heartbeat at drain start
        # and let a peer sweep monitors that are still shutting down cleanly. The
        # in-flight check keeps leases fresh exactly as long as anything is still
        # executing, and ends the loop on its own once the drain empties it.
        while self._running or self._in_flight:
            try:
                await asyncio.sleep(interval)
                monitor_ids = list(self._running_slots)
                if not monitor_ids:
                    continue
                if not implements_db_method(self.db, "heartbeat_monitors"):
                    continue
                fn = self.db.heartbeat_monitors
                refreshed = (
                    await fn(self.worker_id, monitor_ids)
                    if asyncio.iscoroutinefunction(fn)
                    else fn(self.worker_id, monitor_ids)
                )
                # Fewer rows than monitors means someone else now holds those
                # locks. The executors find out for themselves on their next
                # read and stand down; this is only worth saying out loud.
                if refreshed < len(monitor_ids):
                    log_debug(
                        f"Monitor heartbeat refreshed {refreshed}/{len(monitor_ids)} locks; "
                        "the rest are no longer held by this worker"
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log_warning(f"Monitor heartbeat error: {exc}")

    def _release_slot(self, monitor_id: str) -> Callable[["asyncio.Task"], None]:  # type: ignore[type-arg]
        """A done-callback that frees this monitor's slot, whatever it exits by.

        The id is bound now rather than read at call time: by the time the task
        finishes, the loop variable it came from has moved on.
        """

        def done(task: "asyncio.Task") -> None:  # type: ignore[type-arg]
            self._in_flight.discard(task)
            self._running_slots.pop(monitor_id, None)

        return done

    def _over_cap_owners(self) -> List[str]:
        """Owners already holding their share of this worker's slots.

        The cap is a hard reservation, not a tiebreak applied under contention:
        a persistent watch never finishes, so whoever fills the slots first
        holds them for the life of the process. Capacity has to be kept free
        before the tenant who needs it has created anything at all -- by the
        time they ask, deprioritising the greedy owner would be too late.

        Unowned monitors are exempt. A NULL owner means user isolation is off
        (or an admin created the row), and capping a deployment that has no
        tenant boundary would only cripple the single-user case it protects
        nobody from.
        """
        if self.max_concurrent_per_user <= 0:
            return []
        held = Counter(m.user_id for m in self._running_slots.values() if m.user_id is not None)
        return [user_id for user_id, count in held.items() if count >= self.max_concurrent_per_user]

    async def _cleanup_events(self) -> None:
        """Delete monitor events past the retention window."""
        try:
            fn = self.db.cleanup_monitor_events
            removed = (
                await fn(self.retention_seconds) if asyncio.iscoroutinefunction(fn) else fn(self.retention_seconds)
            )
            if removed:
                log_info(f"Monitor retention: removed {removed} events older than {self.retention_seconds}s")
        except Exception as exc:
            log_warning(f"Monitor retention sweep failed: {exc}")

    async def _poll_once(self) -> None:
        """Claim all pending monitors in a tight loop and fire them off."""
        while self._running:
            # Enforce concurrency limit
            self._in_flight -= {t for t in self._in_flight if t.done()}
            if len(self._in_flight) >= self.max_concurrent:
                # A persistent monitor never finishes, so it holds its slot for the
                # life of the process: once max_concurrent of them are running,
                # every newer monitor stays pending forever. Say so once, name the
                # knob, and do not repeat it on every tick.
                holding = ", ".join(sorted(m.name or m.id for m in self._running_slots.values())) or "unknown"
                if self._starved_on != holding:
                    log_warning(
                        f"Monitor concurrency limit reached ({self.max_concurrent}); newer monitors "
                        f"stay pending until a slot frees. Holding slots: {holding}. "
                        "Raise MonitorConfig.max_concurrent on AgentOS if this is expected."
                    )
                    self._starved_on = holding
                break
            self._starved_on = None

            try:
                excluded = self._over_cap_owners()
                if asyncio.iscoroutinefunction(getattr(self.db, "claim_pending_monitor", None)):
                    monitor = await self.db.claim_pending_monitor(
                        self.worker_id, self.lock_grace_seconds, excluded_user_ids=excluded or None
                    )
                else:
                    monitor = self.db.claim_pending_monitor(
                        self.worker_id, self.lock_grace_seconds, excluded_user_ids=excluded or None
                    )

                if monitor is None:
                    break

                mon = Monitor.from_dict(monitor) if isinstance(monitor, dict) else monitor
                log_info(f"Claimed monitor: {mon.name or mon.id}")
                task = asyncio.create_task(self._execute_safe(mon))
                self._in_flight.add(task)
                self._running_slots[mon.id] = mon
                task.add_done_callback(self._release_slot(mon.id))
            except Exception as exc:
                log_error(f"Error claiming monitor: {exc}")
                break

    async def _execute_safe(self, monitor: Union[Monitor, Dict[str, Any]]) -> None:
        """Execute a monitor, catching all errors."""
        try:
            await self.executor.execute(monitor, self.db, self.worker_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            mon_id = monitor.id if isinstance(monitor, Monitor) else monitor.get("id")
            log_error(f"Error executing monitor {mon_id}: {exc}")
