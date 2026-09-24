"""Monitor executor -- runs a monitor's watch and streams its events."""

import asyncio
import json
import os
import signal
import socket
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple, Union
from uuid import uuid4

from agno.db.schemas.monitor import Monitor, validate_watch_path
from agno.db.schemas.scheduler import RUN_ENDPOINT_RE
from agno.monitor.watch import WatchCommand, normalize_watch_commands
from agno.os.internal_client import build_delivery_headers, build_run_delivery_request
from agno.run import RunStatus
from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    from watchfiles import DefaultFilter, awatch
except ImportError:
    # Both under the one guard: a deployment without watchfiles must still reach
    # the refusal in _watch_path, and a module-level import of either name would
    # instead break the whole executor -- taking the command and run watches,
    # which need nothing from watchfiles, down with it.
    awatch = None  # type: ignore[assignment]
    DefaultFilter = None  # type: ignore[assignment,misc]

# Default timeout (in seconds) for event delivery requests
_DEFAULT_DELIVERY_TIMEOUT = 60

# Slack added to the delivery timeout when draining the streams after exit, so a
# final in-flight delivery is never cancelled out from under the monitor.
_DRAIN_GRACE = 10

# Seconds between checks for stop requests, deletion, and timeouts
_DEFAULT_STOP_CHECK_INTERVAL = 2

# Stdout lines arriving within this window are batched into a single event
_DEFAULT_BATCH_WINDOW = 0.2

# Maximum lines batched into a single event
_MAX_BATCH_LINES = 100

# Maximum stderr characters kept for the error field
_MAX_STDERR_CHARS = 4000

# Maximum bytes per stdout/stderr line read from the subprocess
_STREAM_LIMIT = 2**20

# Seconds between reads of a watched run's status
_RUN_POLL_INTERVAL = 2

# How long a path watch blocks waiting for the filesystem before it wakes up
# anyway, in milliseconds. watchfiles parks in a worker thread until something
# changes, so without a timeout to tick on, a watch on a directory nobody is
# touching would notice a stop request, a deletion, a lost lease or its own
# deadline only when a file happened to change -- which for a quiet directory is
# never. Every tick is a monitor read, so this trades a read per second per path
# watch for a watch that can actually be stopped.
_PATH_TICK_MS = 1000

# Run statuses that end a watch. A paused run is deliberately absent, and this
# is deliberately NOT the scheduler's set (which counts PAUSED as terminal): the
# two answer different questions. A schedule asks "how did this firing end?", and
# paused is a real ending -- cron fires again later. A watch asks "is the work
# done?", where paused is not done, and ending the watch there would mean the
# caller is never told about the completion they asked to be told about. The
# monitor's own deadline bounds the wait, and reports the pause when it expires.
_TERMINAL_RUN_STATUSES = (
    RunStatus.completed.value,
    RunStatus.error.value,
    RunStatus.cancelled.value,
    # A regenerated run was replaced via /continue?regenerate=true. It will
    # never move again, so a watch that keeps waiting burns to its deadline
    # and then reports it as unfinished -- which is the opposite of true.
    RunStatus.regenerated.value,
)

# Maximum characters of a watched run's own content carried into the event
_MAX_RUN_CONTENT_CHARS = 4000

# Consecutive failed deliveries before a monitor gives up. A persistent watch
# with an unlimited event budget delivers as fast as its command prints, so an
# endpoint that is 429ing or 500ing would otherwise be hammered forever -- and
# every attempt that does land starts a real model run.
_MAX_CONSECUTIVE_DELIVERY_FAILURES = 5

# Seconds allowed for the ps probe that identifies an orphaned process
_PROC_PROBE_TIMEOUT = 5


async def _proc_started_at(pid: int) -> Optional[str]:
    """The wall-clock start time of *pid*, as the OS reports it.

    Paired with the pid this is a portable process identity: a recycled pid has a
    different start time, so a record written before a crash can never match a
    live stranger. Returns None when the pid is gone or ps is unavailable, and
    the caller treats that as "do not touch anything".
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ps",
            "-o",
            "lstart=",
            "-p",
            str(pid),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_PROC_PROBE_TIMEOUT)
    except Exception:
        return None
    return out.decode(errors="replace").strip() or None


def _unemitted_outcome(emitted: str, seq: int) -> Tuple[str, str]:
    """Where a monitor comes to rest when one of its events did not make it out.

    Both watch loops ask this and they had already drifted: the run watch filed
    a deletion and an exhausted delivery breaker as storage faults, which sends
    an operator looking at the database for a problem that is in their endpoint
    or in their own DELETE. One answer, one place.
    """
    if emitted == "deleted":
        # The caller's own doing, so it settles the way the watchdog settles a
        # stop request: stopped, not failed.
        return "stopped", "Monitor was deleted"
    if emitted == "undeliverable":
        return "failed", (
            f"Stopped after {_MAX_CONSECUTIVE_DELIVERY_FAILURES} consecutive delivery failures; check the endpoint"
        )
    return "failed", f"Failed to persist event {seq}"


def _build_watch_filter(exclude: Optional[List[str]], use_default_filter: bool) -> Optional[Callable[[Any, str], bool]]:
    """Decide what a path watch is allowed to see. ``None`` means watch everything.

    watchfiles applies its own DefaultFilter when no filter is passed, so this
    has to be built even when nobody excluded anything: handing back ``None``
    for "no preference" would silently turn the defaults OFF, and a watch on a
    checked-out repository would then fire on every .git write.

    Each pattern is matched against the full path AND the basename, because
    ``*.log`` is what an owner writes when they mean "log files anywhere" --
    matched against the absolute path alone it never fires, since the path has
    directory separators the glob does not cover.
    """
    base = DefaultFilter() if use_default_filter else None
    patterns = [p for p in (exclude or []) if p and p.strip()]
    if base is None and not patterns:
        return None

    def _filter(change: Any, path: str) -> bool:
        if base is not None and not base(change, path):
            return False
        name = Path(path).name
        return not any(fnmatch(path, pattern) or fnmatch(name, pattern) for pattern in patterns)

    return _filter


def _holds_lease(row: Dict[str, Any], worker_id: str, attempt: int) -> bool:
    """Whether a freshly read monitor row still belongs to this execution.

    The lock is refreshed elsewhere -- the poller beats every monitor it holds on
    one timer -- so the executor learns it was superseded from the row it already
    reads each tick, rather than from a write of its own. Both halves matter: a
    different worker took over, or this same worker re-claimed the row after a
    crash and the older execution is still alive.
    """
    return row.get("locked_by") == worker_id and (row.get("attempt") or 0) == attempt


def _exc_detail(exc: BaseException) -> str:
    """Readable text for an exception, including ones that stringify to nothing.

    httpx timeout errors carry an empty message, which would otherwise store a
    blank error and leave an operator with no idea why a delivery failed.
    """
    return str(exc) or repr(exc) or type(exc).__name__


async def _db_call(db: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Call a DB method, handling sync/async adapters transparently."""
    fn = getattr(db, method_name, None)
    if fn is None:
        raise NotImplementedError(f"Database does not support {method_name}")
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return fn(*args, **kwargs)


class MonitorExecutor:
    """Execute a monitor: watch what it points at and emit the result as events.

    A monitor watches one of three things. With a ``watch_path`` it watches a
    file or directory and each batch of filesystem changes becomes an event
    naming what changed. With a ``watch_command`` it runs the command the
    operator declared under that name, as a subprocess in its own process group,
    and each batch of stdout lines becomes an event. With a ``watch_run_id`` it
    follows an existing run in the runs table and emits a single event once that
    run settles -- the shape a background run (or anything else already executing
    inside AgentOS) is waited on.

    Whichever it is, the event is persisted as a MonitorEvent and, when the
    monitor has an endpoint, delivered to it. Run endpoints (``/agents/*/runs``
    etc.) receive the event as a background run; other endpoints receive a JSON
    body.

    ``base_url`` and ``internal_service_token`` are only needed for delivery -- a
    watch-and-read monitor (no endpoint) can run with neither configured.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        internal_service_token: Optional[str] = None,
        timeout: int = _DEFAULT_DELIVERY_TIMEOUT,
        watch_commands: Optional[Mapping[str, Union[str, WatchCommand]]] = None,
        base_dir: Optional[str] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.internal_service_token = internal_service_token
        self.timeout = timeout
        # Root a ``watch_path`` is contained to, defaulting to the process's
        # working directory. Kept here rather than trusted from the row, because
        # the row outlives the configuration that produced it: a path validated
        # against yesterday's root is re-validated against this one when it is
        # claimed, so narrowing the root retires the watches it no longer covers
        # instead of leaving them running outside it.
        self.base_dir = base_dir
        # Named commands the operator declared. A monitor row carries only the
        # key, so nothing a caller sends can become a shell string. Normalised
        # here so everything downstream sees one shape, whichever form the
        # operator used to declare it.
        self.watch_commands = normalize_watch_commands(watch_commands)
        # Consecutive delivery failures per monitor, for the circuit breaker.
        self._delivery_failures: Dict[str, int] = {}
        self._client: Optional[Any] = None

    def _can_deliver(self) -> bool:
        """Whether this executor is configured to deliver events."""
        return self.base_url is not None and self.internal_service_token is not None

    async def _get_client(self) -> Any:
        """Get or create the shared httpx.AsyncClient."""
        if httpx is None:
            raise ImportError("`httpx` not installed. Please install it using `pip install httpx`")
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self.timeout))
        return self._client

    async def close(self) -> None:
        """Close the shared httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    async def execute(self, monitor: Union[Monitor, Dict[str, Any]], db: Any, worker_id: str) -> None:
        """Run *monitor* to completion, persisting its events and final status.

        Args:
            monitor: Monitor object or dict (from the claim).
            db: The DB adapter instance (must have monitor methods).
            worker_id: The claiming worker, used to refresh the lock heartbeat.
        """
        mon = Monitor.from_dict(monitor) if isinstance(monitor, dict) else monitor
        try:
            await self._execute(mon, db, worker_id)
        finally:
            # The breaker counts CONSECUTIVE failures within one execution, so the
            # count means nothing once that execution is over. Dropped here rather
            # than on a successful delivery alone: an executor lives as long as the
            # process, so a monitor that failed a delivery and then finished, was
            # stopped, or was deleted would otherwise leave its entry behind for
            # good, and the dict would grow with every monitor that ever failed one.
            self._delivery_failures.pop(mon.id, None)

    async def _execute(self, monitor: Union[Monitor, Dict[str, Any]], db: Any, worker_id: str) -> None:
        """Run *monitor* to completion, persisting its events and final status.

        Args:
            monitor: Monitor object or dict (from the claim).
            db: The DB adapter instance (must have monitor methods).
            worker_id: The claiming worker, used to refresh the lock heartbeat.
        """
        mon = Monitor.from_dict(monitor) if isinstance(monitor, dict) else monitor

        # Fail fast on a static misconfiguration: a monitor that wants its events
        # delivered but has no way to deliver them. Running the command would
        # produce events that silently never reach the endpoint, and the monitor
        # would still report success -- the worst failure shape for a watcher.
        if mon.endpoint and not self._can_deliver():
            await _db_call(
                db,
                "update_monitor",
                mon.id,
                expected_lease=(worker_id, mon.attempt),
                status="failed",
                error="Monitor has an endpoint but the executor has no base_url/token to deliver events",
                finished_at=int(time.time()),
                locked_by=None,
                locked_at=None,
            )
            log_error(f"Monitor {mon.id} has an endpoint but delivery is not configured; marking failed")
            return

        # The claim only takes the lock, it does not change the status, so a stop
        # landing between the claim and here is invisible in the claimed snapshot.
        # Re-read before spawning anything: running a command the caller was told
        # was stopped is the one outcome a shell runner must never produce.
        current = await _db_call(db, "get_monitor", mon.id)
        status_now = current.get("status") if current else None

        # A stop was requested -- either just now, in the claim window, or before a
        # previous worker died without finalizing it. Honor it instead of running.
        if status_now in ("stopping", "stopped"):
            await _db_call(
                db,
                "update_monitor",
                mon.id,
                expected_lease=(worker_id, mon.attempt),
                status="stopped",
                finished_at=int(time.time()),
                locked_by=None,
                locked_at=None,
            )
            log_info(f"Monitor {mon.id} was stopped before it started; not running the watch")
            return

        # Any other terminal status means someone else finished it. Release the
        # lock rather than re-running a command that already completed -- fenced,
        # so a worker that lost the claim cannot release the live holder's lock.
        if status_now in ("completed", "failed", "timeout"):
            await _db_call(
                db,
                "update_monitor",
                mon.id,
                expected_lease=(worker_id, mon.attempt),
                locked_by=None,
                locked_at=None,
            )
            log_debug(f"Monitor {mon.id} is already {status_now}; releasing the claim without running")
            return

        try:
            await self._run(mon, db, worker_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_error(f"Error running monitor {mon.id}: {exc}")
            try:
                await _db_call(
                    db,
                    "update_monitor",
                    mon.id,
                    expected_lease=(worker_id, mon.attempt),
                    status="failed",
                    error=str(exc),
                    finished_at=int(time.time()),
                    locked_by=None,
                    locked_at=None,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    async def _run(self, monitor: Monitor, db: Any, worker_id: str) -> None:
        """Start the monitor's watch: a path, a declared command, or a run to follow."""
        started_at = int(time.time())
        # Fenced: if the claim was already taken over between the poller's claim
        # and here, this worker must not start a second copy of the work.
        claimed = await _db_call(
            db,
            "update_monitor",
            monitor.id,
            expected_lease=(worker_id, monitor.attempt),
            status="running",
            started_at=started_at,
            finished_at=None,
            exit_code=None,
            error=None,
        )
        if claimed is None:
            log_warning(f"Monitor {monitor.id} is held by another worker; not starting it here")
            return

        if monitor.watch_run_id:
            try:
                await self._watch_run(monitor, db, worker_id, started_at)
            except asyncio.CancelledError:
                # Shutdown. There is no subprocess to kill here, but the row must
                # still be re-armed or it reads as running -- with this worker's
                # lock on it -- for the whole grace after the process is gone.
                await self._rearm_after_cancel(monitor, db, worker_id)
                raise
            return

        if monitor.watch_path:
            try:
                await self._watch_path(monitor, db, worker_id, started_at)
            except asyncio.CancelledError:
                # Same as a run watch: nothing to kill, but a row left running
                # under the lock of a worker that is gone reads as live work to
                # everyone asking, for the whole lease grace.
                await self._rearm_after_cancel(monitor, db, worker_id)
                raise
            return

        await self._run_command(monitor, db, worker_id, started_at)

    @staticmethod
    async def _rearm_after_cancel(monitor: Monitor, db: Any, worker_id: str) -> None:
        """Put a watch cancelled by shutdown back to pending, and drop its lock.

        Best effort: the process is on its way out, and a re-arm that cannot be
        written is still recovered when the lease expires -- just slower, with
        the row reading as running until it does.
        """
        try:
            await _db_call(
                db,
                "update_monitor",
                monitor.id,
                expected_lease=(worker_id, monitor.attempt),
                status="pending",
                locked_by=None,
                locked_at=None,
            )
        except Exception:
            pass

    async def _reap_orphan(self, monitor: Monitor) -> None:
        """Kill a leftover subprocess from a worker that died holding this row.

        start_new_session detaches the command's process group, so it outlives the
        worker and no lease can reach it -- an orphan holds no lease to lose. The
        row carries where it ran and which process it was; this kills it only when
        the host matches AND pid+start-time still identify the same process. Any
        other answer is reported and left alone: killing a recycled pid would take
        out something unrelated, which is worse than the orphan it would clean up.
        """
        if not monitor.proc_pgid or not monitor.proc_pid:
            return
        if monitor.worker_host != socket.gethostname():
            log_warning(
                f"Monitor {monitor.id} may have a subprocess still running on {monitor.worker_host} "
                f"(pid {monitor.proc_pid}, pgid {monitor.proc_pgid}); this worker is on a different "
                "host and cannot reach it. Kill it there if it is still alive."
            )
            return

        live = await _proc_started_at(monitor.proc_pid)
        if live is None:
            log_debug(f"Monitor {monitor.id}: previous process {monitor.proc_pid} is already gone")
            return
        if live != monitor.proc_started_at:
            log_warning(
                f"Monitor {monitor.id}: pid {monitor.proc_pid} is alive but started at {live!r}, "
                f"not {monitor.proc_started_at!r} -- the pid was recycled and now belongs to something "
                "else. Not killing it. If the original is still running, find it by pgid "
                f"{monitor.proc_pgid} and stop it manually."
            )
            return

        log_warning(
            f"Monitor {monitor.id}: killing an orphaned process group {monitor.proc_pgid} "
            f"left by a worker that died while running it"
        )
        try:
            os.killpg(monitor.proc_pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError) as exc:
            log_warning(f"Monitor {monitor.id}: could not signal orphaned group {monitor.proc_pgid}: {exc}")

    async def _run_command(self, monitor: Monitor, db: Any, worker_id: str, started_at: int) -> None:
        """Spawn the monitor's declared command and stream its stdout lines as events."""
        # Resolve the declared watch. A key that is not declared on this
        # deployment fails loudly rather than running nothing: the operator may
        # have removed it, or the monitor may have been created against a
        # different deployment's declarations.
        watch = self.watch_commands.get(monitor.watch_command or "")
        if watch is None or not watch.command:
            declared = ", ".join(sorted(self.watch_commands)) or "none"
            await _db_call(
                db,
                "update_monitor",
                monitor.id,
                expected_lease=(worker_id, monitor.attempt),
                status="failed",
                error=(
                    f"Watch '{monitor.watch_command}' is not declared on this deployment. Declared watches: {declared}"
                ),
                finished_at=int(time.time()),
                locked_by=None,
                locked_at=None,
            )
            log_error(f"Monitor {monitor.id} names an undeclared watch {monitor.watch_command!r}; marking failed")
            return

        # Whatever the previous holder of this row left running has to go before a
        # second copy starts; that is the one duplicate-execution path the lease
        # cannot close.
        await self._reap_orphan(monitor)

        # Extra variables are layered over the server's environment rather than
        # replacing it: a command that needs PATH must keep working, and these
        # declarations are the operator's own.
        env = {**os.environ, **watch.env} if watch.env else None

        # Run in its own process group so pipelines (e.g. tail | grep) are
        # terminated as a whole; killing only the shell would leave children
        # holding the stdout pipe and proc.wait() would never return.
        try:
            proc = await asyncio.create_subprocess_shell(
                watch.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT,
                start_new_session=True,
                cwd=watch.cwd,
                env=env,
            )
        except (OSError, ValueError) as exc:
            # A cwd that does not exist raises here, before there is any process
            # to supervise. Uncaught it would leave the row running with a lock
            # nothing ever clears, so the failure has to land on the row.
            await _db_call(
                db,
                "update_monitor",
                monitor.id,
                expected_lease=(worker_id, monitor.attempt),
                status="failed",
                error=f"Could not start watch '{monitor.watch_command}': {_exc_detail(exc)}",
                finished_at=int(time.time()),
                locked_by=None,
                locked_at=None,
            )
            log_error(f"Monitor {monitor.id}: could not start watch {monitor.watch_command!r}: {exc}")
            return

        # Record what we just spawned, so a worker inheriting this row after a crash
        # can find and identify it. Written before any output is consumed: a crash
        # one millisecond later must still leave a findable process.
        await _db_call(
            db,
            "update_monitor",
            monitor.id,
            expected_lease=(worker_id, monitor.attempt),
            worker_host=socket.gethostname(),
            proc_pid=proc.pid,
            proc_pgid=os.getpgid(proc.pid),
            proc_started_at=await _proc_started_at(proc.pid),
        )

        # Set by the watchdog or the event consumer when the process is
        # terminated early; overrides the exit-code based status.
        outcome: Dict[str, Optional[str]] = {"status": None, "error": None}
        stderr_tail: List[str] = []

        stdout_task = asyncio.create_task(self._consume_stdout(proc, monitor, outcome, db, worker_id))
        stderr_task = asyncio.create_task(self._consume_stderr(proc, stderr_tail))
        watchdog_task = asyncio.create_task(self._watchdog(proc, monitor, started_at, outcome, db, worker_id))

        try:
            await proc.wait()
        except asyncio.CancelledError:
            # Shutdown: kill the process group (escalating to SIGKILL if it
            # lingers) and re-arm the monitor so it is claimed again when a
            # worker comes back up. Without the SIGKILL escalation a pipeline
            # that is slow to die on SIGTERM would be orphaned when the process
            # exits.
            self._terminate(proc)
            await self._ensure_killed(proc)
            for task in (stdout_task, stderr_task, watchdog_task):
                task.cancel()
            try:
                await _db_call(
                    db,
                    "update_monitor",
                    monitor.id,
                    expected_lease=(worker_id, monitor.attempt),
                    status="pending",
                    locked_by=None,
                    locked_at=None,
                )
            except Exception:
                pass
            raise
        finally:
            watchdog_task.cancel()

        # Let the stream consumers drain any remaining output. The budget must
        # outlast a delivery in flight: the final batch is usually still being
        # delivered here, and cancelling it mid-request drops the alert while the
        # monitor goes on to report a clean exit.
        try:
            await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task, return_exceptions=True),
                timeout=_DRAIN_GRACE + self.timeout,
            )
        except asyncio.TimeoutError:
            log_warning(f"Monitor {monitor.id}: stream drain timed out; a final event may not have been delivered")
            stdout_task.cancel()
            stderr_task.cancel()

        # The watchdog found the claim taken over and killed our subprocess. The
        # row belongs to the new holder now, so writing a terminal status here
        # would overwrite a run that is still going.
        if outcome.get("fenced"):
            log_warning(f"Monitor {monitor.id}: superseded while running; leaving the final status to the new holder")
            return

        if outcome["status"] is not None:
            status = outcome["status"]
            error = outcome["error"]
        elif proc.returncode == 0:
            status = "completed"
            error = None
        else:
            status = "failed"
            error = "".join(stderr_tail)[-_MAX_STDERR_CHARS:] or f"Command exited with code {proc.returncode}"

        await _db_call(
            db,
            "update_monitor",
            monitor.id,
            expected_lease=(worker_id, monitor.attempt),
            status=status,
            exit_code=proc.returncode,
            error=error,
            finished_at=int(time.time()),
            locked_by=None,
            locked_at=None,
            # The process is gone; leaving its coordinates would have the next
            # worker probe a pid that is not ours any more.
            worker_host=None,
            proc_pid=None,
            proc_pgid=None,
            proc_started_at=None,
        )
        log_info(f"Monitor {monitor.name or monitor.id} finished (status={status}, exit_code={proc.returncode})")

    # ------------------------------------------------------------------
    async def _watch_run(self, monitor: Monitor, db: Any, worker_id: str, started_at: int) -> None:
        """Follow an existing run and emit one event when it reaches a terminal state.

        The run's status is read from the runs table rather than over HTTP, so a
        watch needs no delivery credentials of its own and works on the adapters
        the durable job queue does not support -- SQLite in particular.

        Intermediate transitions (queued -> running) are not emitted: a watch
        exists to say the work is over, and one event per watch keeps a single
        ping per finished run. ``GET /monitors/{id}`` is where the in-flight
        condition is read from.
        """
        watched_run_id = monitor.watch_run_id or ""
        status = "completed"
        error: Optional[str] = None
        exit_code: Optional[int] = None
        # Terminal status of the watched run, once it settles
        settled: Optional[str] = None
        run_row: Dict[str, Any] = {}
        # Whether the run's row was ever visible, so a deadline can say which of
        # the two very different things went wrong.
        seen = False
        # Completed reads of the runs table. A deadline that expires before the
        # first one must not report the run as missing: nothing looked for it.
        polls = 0
        # Last status observed, so a deadline can name a paused run as paused
        last_seen: Optional[str] = None

        while True:
            # Sleeping first keeps every path through the loop bounded: a `continue`
            # that skipped the sleep would turn a not-yet-visible run into a spin.
            await asyncio.sleep(_RUN_POLL_INTERVAL)
            now = int(time.time())

            # There is no process to kill here, so the deadline is the only bound
            # on a run that never settles. Persistent skips it, as with a command.
            if not monitor.persistent and monitor.timeout_seconds and now - started_at >= monitor.timeout_seconds:
                status = "timeout"
                # "never showed up" and "showed up but never finished" have
                # different causes -- a wrong run id, versus work still running --
                # so the deadline must not report them with the same sentence.
                if last_seen == RunStatus.paused.value:
                    # Nothing is wrong with the run: it is parked waiting on a
                    # human. Saying "had not finished" hides the one fact that
                    # would tell the caller what to do about it.
                    error = (
                        f"Run {watched_run_id} is paused waiting for human input; "
                        f"gave up watching after {monitor.timeout_seconds}s"
                    )
                elif seen:
                    error = f"Run {watched_run_id} had not finished after {monitor.timeout_seconds}s"
                elif polls == 0:
                    # The deadline expired before the first poll came round, so the
                    # run was never looked for. Reporting "never found" here would
                    # blame the run id for what is really a deadline shorter than
                    # the poll interval.
                    error = (
                        f"Monitor timed out after {monitor.timeout_seconds}s without checking run "
                        f"{watched_run_id} even once; the deadline is shorter than the "
                        f"{_RUN_POLL_INTERVAL}s poll interval"
                    )
                else:
                    error = (
                        f"Run {watched_run_id} was never found in the runs table "
                        f"after {monitor.timeout_seconds}s; check the run id"
                    )
                break

            try:
                own = await _db_call(db, "get_monitor", monitor.id)
            except Exception as exc:
                # A transient read failure must not be read as deletion, which
                # would end a watch the caller never asked to stop.
                log_warning(f"Monitor {monitor.id}: watch DB check failed: {exc}")
                continue

            if own is None:
                status = "stopped"
                error = "Monitor was deleted"
                break
            if own.get("status") == "stopping":
                status = "stopped"
                error = None
                break

            # The lock itself is refreshed by the poller's batched heartbeat; this
            # read is what tells us we lost it. Losing it means a peer is watching
            # the same run, and two watchers would deliver the same completion
            # twice -- so stand down rather than race for the delivery.
            if not _holds_lease(own, worker_id, monitor.attempt):
                log_warning(
                    f"Monitor {monitor.id} was reclaimed by another worker; "
                    "stopping this watch and leaving the row to the new holder"
                )
                return

            try:
                row = await _db_call(db, "get_run", watched_run_id, deserialize=False)
            except Exception as exc:
                log_warning(f"Monitor {monitor.id}: reading run {watched_run_id} failed: {exc}")
                continue
            # A completed read. "Absent" is only a claim we have earned once one
            # of these has happened.
            polls += 1

            # A background run's row can lag the 202 that accepted it, so a
            # missing row means "not yet", not "never" -- the deadline bounds it.
            if row is None:
                continue

            # An owned monitor may only watch its owner's run. A run belonging to
            # someone else is treated as absent rather than refused: answering
            # "not yours" instead of "not found" would confirm the id exists, and
            # the create route already scopes its component probe for exactly
            # that reason. So this watch simply never settles.
            if monitor.user_id is not None and row.get("user_id") != monitor.user_id:
                continue
            seen = True

            run_status = str(row.get("status") or "").upper()
            last_seen = run_status
            if run_status in _TERMINAL_RUN_STATUSES:
                settled = run_status
                run_row = row
                break

        if settled is not None:
            seq = (monitor.event_count or 0) + 1
            emitted = await self._emit_event(
                monitor, self._run_event_content(settled, watched_run_id, run_row), seq, db, worker_id
            )
            if emitted == "emitted":
                succeeded = settled == RunStatus.completed.value
                status = "completed" if succeeded else "failed"
                exit_code = 0 if succeeded else 1
                # The watch itself worked; the error says the watched run is what
                # ended badly, so the two are never confused on the monitor row.
                error = None if succeeded else f"Watched run {watched_run_id} ended with status {settled}"
            else:
                status, error = _unemitted_outcome(emitted, seq)

        await _db_call(
            db,
            "update_monitor",
            monitor.id,
            expected_lease=(worker_id, monitor.attempt),
            status=status,
            exit_code=exit_code,
            error=error,
            finished_at=int(time.time()),
            locked_by=None,
            locked_at=None,
        )
        log_info(f"Monitor {monitor.name or monitor.id} finished watching run {watched_run_id} (status={status})")

    @staticmethod
    def _run_event_content(run_status: str, run_id: str, row: Dict[str, Any]) -> str:
        """Build the single event a settled run produces: its outcome and output."""
        header = f"Run {run_id} finished with status {run_status}."

        run_data = row.get("run_data")
        if isinstance(run_data, str):
            # Adapters differ on whether the JSON column arrives parsed
            try:
                run_data = json.loads(run_data)
            except (ValueError, TypeError):
                run_data = None
        if not isinstance(run_data, dict):
            return header

        content = run_data.get("content")
        if not isinstance(content, str) or not content.strip():
            return header
        return f"{header}\n\n{content.strip()[:_MAX_RUN_CONTENT_CHARS]}"

    # ------------------------------------------------------------------
    @staticmethod
    async def _fail_monitor(monitor: Monitor, db: Any, worker_id: str, error: str) -> None:
        """Land a failure that happened before the watch loop, and drop the lock.

        A watch that never starts has no loop to report through, so without this
        the row keeps this worker's lock and reads as running until the lease
        expires -- at which point it is claimed again, to fail the same way.
        """
        await _db_call(
            db,
            "update_monitor",
            monitor.id,
            expected_lease=(worker_id, monitor.attempt),
            status="failed",
            error=error,
            finished_at=int(time.time()),
            locked_by=None,
            locked_at=None,
        )
        log_error(f"Monitor {monitor.id}: {error}")

    async def _watch_path(self, monitor: Monitor, db: Any, worker_id: str, started_at: int) -> None:
        """Watch the monitor's paths and emit one event per batch of changes.

        Several paths are one watch here, not one per path: the row has a single
        status, exit code and event count, so a second watcher writing into it
        would have nowhere honest to report from.

        There is no subprocess and no stdout here: watchfiles parks in a worker
        thread and hands back the set of paths that changed. The loop is woken by
        a short timeout as well as by a change, because everything that ends a
        watch -- a stop request, a deletion, a lost lease, the deadline -- is a
        database fact, and a loop that only woke on filesystem activity would sit
        through all four on a directory nobody is touching.
        """
        if awatch is None:
            await self._fail_monitor(
                monitor,
                db,
                worker_id,
                "Watching a path needs the `watchfiles` package. Install it with `pip install watchfiles`",
            )
            return

        # Re-validated rather than trusted from the row: the stored path was
        # contained against whatever root the deployment had when the monitor was
        # created, and a root narrowed since then has to retire the watches it no
        # longer covers instead of leaving them reading outside it.
        try:
            resolved = validate_watch_path(monitor.watch_path, self.base_dir)
        except ValueError as exc:
            await self._fail_monitor(monitor, db, worker_id, str(exc))
            return
        if resolved is None:
            await self._fail_monitor(monitor, db, worker_id, "Monitor has no watch_path to watch")
            return
        # watchfiles raises on a path that is not there, which would reach the
        # row as an unexplained failure. Naming the path is what tells the caller
        # whether they mistyped it or it has been removed since -- and with
        # several watched together, every missing one is named, or the caller
        # fixes one typo just to be told about the next.
        missing = [path for path in resolved if not Path(path).exists()]
        if missing:
            names = ", ".join(missing)
            await self._fail_monitor(monitor, db, worker_id, f"Watched path {names} does not exist")
            return

        status = "completed"
        error: Optional[str] = None
        # A LIFETIME budget, counted exactly as a command watch counts one: seq
        # continues from event_count, so a restart resumes the budget instead of
        # being handed a fresh one.
        seq = monitor.event_count or 0
        unlimited = (monitor.max_events or 0) <= 0

        watcher = awatch(
            *resolved,
            watch_filter=_build_watch_filter(monitor.exclude, monitor.use_default_filter),
            rust_timeout=_PATH_TICK_MS,
            yield_on_timeout=True,
        )
        try:
            async for changes in watcher:
                now = int(time.time())

                # Nothing else bounds a path watch: a directory can stay quiet for
                # as long as the process lives. Persistent skips it, as elsewhere.
                if not monitor.persistent and monitor.timeout_seconds and now - started_at >= monitor.timeout_seconds:
                    status = "timeout"
                    error = f"Monitor timed out after {monitor.timeout_seconds}s"
                    break

                try:
                    own = await _db_call(db, "get_monitor", monitor.id)
                except Exception as exc:
                    # A transient read failure must not be read as deletion, which
                    # would end a watch the caller never asked to stop.
                    log_warning(f"Monitor {monitor.id}: watch DB check failed: {exc}")
                    continue

                if own is None:
                    status = "stopped"
                    error = "Monitor was deleted"
                    break
                if own.get("status") == "stopping":
                    status = "stopped"
                    error = None
                    break

                # The lock itself is refreshed by the poller's batched heartbeat;
                # this read is what tells us we lost it. A peer is watching the
                # same path now, and two watchers turn one edit into two events --
                # each of which starts a real run when an endpoint is set.
                if not _holds_lease(own, worker_id, monitor.attempt):
                    log_warning(
                        f"Monitor {monitor.id} was reclaimed by another worker; "
                        "stopping this watch and leaving the row to the new holder"
                    )
                    return

                # An empty batch is the timeout tick, not a change. Everything
                # above it had to run; nothing below it may.
                if not changes:
                    continue

                seq += 1
                emitted = await self._emit_event(monitor, self._path_event_content(changes), seq, db, worker_id)
                if emitted != "emitted":
                    status, error = _unemitted_outcome(emitted, seq)
                    break

                if not unlimited and seq >= monitor.max_events:
                    status = "stopped"
                    error = f"Stopped after reaching max_events ({monitor.max_events})"
                    break
        finally:
            # Leaving the loop parks the generator on its yield, so the watcher
            # thread would live on until the garbage collector reached it.
            await watcher.aclose()

        await _db_call(
            db,
            "update_monitor",
            monitor.id,
            expected_lease=(worker_id, monitor.attempt),
            status=status,
            error=error,
            finished_at=int(time.time()),
            locked_by=None,
            locked_at=None,
        )
        log_info(f"Monitor {monitor.name or monitor.id} finished watching {', '.join(resolved)} (status={status})")

    @staticmethod
    def _path_event_content(changes: Iterable[Tuple[Any, str]]) -> str:
        """One line per change -- ``added``, ``modified`` or ``deleted``, then the path.

        watchfiles hands back a set, so without the sort the same batch of
        changes reads differently every time it is emitted, and two events for
        the same edit cannot be compared.
        """
        return "\n".join(sorted(f"{change.raw_str()} {path}" for change, path in changes))

    async def _consume_stdout(
        self, proc: Any, monitor: Monitor, outcome: Dict[str, Optional[str]], db: Any, worker_id: str
    ) -> None:
        """Read stdout lines, batch them, and emit one event per batch."""
        assert proc.stdout is not None
        seq = monitor.event_count or 0
        unlimited = (monitor.max_events or 0) <= 0

        while True:
            try:
                line = await proc.stdout.readline()
            except (ValueError, asyncio.LimitOverrunError) as exc:
                # The stream cannot be resynchronised past an over-long line. Nothing
                # would drain stdout after this, so the command would block on write
                # and a persistent monitor would sit "running" with no events and no
                # error forever -- fail it loudly and stop the command instead.
                log_error(f"Monitor {monitor.id}: stdout line exceeded the read limit; failing the monitor: {exc}")
                outcome["status"] = "failed"
                outcome["error"] = (
                    f"A stdout line exceeded the {_STREAM_LIMIT}-byte read limit; "
                    "the event stream cannot continue. Filter the command's output."
                )
                self._terminate(proc)
                await self._ensure_killed(proc)
                break
            if not line:
                break

            # Batch lines arriving within the batch window into one event
            lines = [line]
            while len(lines) < _MAX_BATCH_LINES:
                try:
                    more = await asyncio.wait_for(proc.stdout.readline(), timeout=_DEFAULT_BATCH_WINDOW)
                except asyncio.TimeoutError:
                    break
                except (ValueError, asyncio.LimitOverrunError):
                    break
                if not more:
                    break
                lines.append(more)

            content = b"".join(lines).decode("utf-8", errors="replace").rstrip("\n")
            seq += 1
            # The event is the monitor's product: a persist failure must surface as a
            # failed monitor, never be swallowed into a clean completion.
            emitted = await self._emit_event(monitor, content, seq, db, worker_id)
            if emitted != "emitted":
                outcome["status"], outcome["error"] = _unemitted_outcome(emitted, seq)
                self._terminate(proc)
                await self._ensure_killed(proc)
                break

            # A LIFETIME budget, not a per-execution one: seq continues from
            # event_count, so this counts every event the monitor has ever
            # emitted. Measuring the execution instead would hand a fresh budget
            # out on every restart, and with an endpoint set each event starts a
            # real model run -- so monitors:write alone would buy unlimited spend
            # by restarting.
            if not unlimited and seq >= monitor.max_events:
                outcome["status"] = "stopped"
                outcome["error"] = f"Stopped after reaching max_events ({monitor.max_events})"
                self._terminate(proc)
                await self._ensure_killed(proc)
                break

    async def _emit_event(self, monitor: Monitor, content: str, seq: int, db: Any, worker_id: str) -> str:
        """Persist an event, deliver it to the endpoint, and bump the counter.

        Returns ``"emitted"``, ``"deleted"`` (the monitor was removed underneath
        us, so there is nothing left to fail) or ``"failed"``. The caller needs
        the three apart: a persist failure must fail the monitor rather than
        report success with the event silently dropped, while a deletion is the
        caller getting what they asked for.
        """
        event_id = str(uuid4())
        event_dict: Dict[str, Any] = {
            "id": event_id,
            "monitor_id": monitor.id,
            "seq": seq,
            "content": content,
            "delivery_status": "pending" if monitor.endpoint else None,
            "status_code": None,
            "run_id": None,
            "session_id": None,
            "error": None,
            # Denormalised from the parent so an event read scopes by owner
            # without reading the monitor back.
            "user_id": monitor.user_id,
            "created_at": int(time.time()),
        }
        try:
            await _db_call(db, "create_monitor_event", event_dict)
        except Exception as exc:
            # A monitor deleted mid-run takes its events with it (FK cascade), so
            # the insert losing its parent is the delete working, not a fault.
            # The probe is guarded: if the read fails too, the persist error is
            # still what the caller needs to hear, and this handler must not
            # raise where it used to return.
            try:
                deleted = await _db_call(db, "get_monitor", monitor.id) is None
            except Exception as probe_exc:
                log_debug(f"Monitor {monitor.id}: could not check for deletion after a persist failure: {probe_exc}")
                deleted = False
            if deleted:
                log_debug(f"Monitor {monitor.id} was deleted while emitting event {seq}; dropping it")
                return "deleted"
            log_error(f"Failed to persist event {seq} for monitor {monitor.id}: {exc}")
            return "failed"

        # Bump the counter as soon as the row exists, before delivery. Delivery can
        # be cancelled (shutdown, drain deadline); if the counter were bumped after
        # it, the count would understate the rows on disk and a restart would reuse
        # a seq that is already taken.
        try:
            await _db_call(
                db, "update_monitor", monitor.id, expected_lease=(worker_id, monitor.attempt), event_count=seq
            )
        except Exception as exc:
            log_warning(f"Failed to update event count for monitor {monitor.id}: {exc}")

        if monitor.endpoint:
            # A delivery failure must be recorded on the event, never swallowed --
            # a monitor that drops its alerts while reporting success is the worst
            # failure shape for a watcher.
            try:
                result = await self._deliver(monitor, content, seq)
            except Exception as exc:
                log_error(f"Failed to deliver event {seq} for monitor {monitor.id}: {exc}")
                result = {
                    "delivery_status": "failed",
                    "status_code": None,
                    "run_id": None,
                    "session_id": None,
                    "error": _exc_detail(exc),
                }
            try:
                await _db_call(db, "update_monitor_event", event_id, **result)
            except Exception as exc:
                log_warning(f"Failed to update event {seq} for monitor {monitor.id}: {exc}")

            # Recording the failure on the event is not enough on its own: nothing
            # reads it back, so a monitor whose endpoint is down would keep firing
            # for as long as its command keeps printing.
            if result.get("delivery_status") == "delivered":
                self._delivery_failures.pop(monitor.id, None)
            else:
                failures = self._delivery_failures.get(monitor.id, 0) + 1
                self._delivery_failures[monitor.id] = failures
                if failures >= _MAX_CONSECUTIVE_DELIVERY_FAILURES:
                    log_error(
                        f"Monitor {monitor.id}: {failures} consecutive delivery failures "
                        f"(last: {result.get('status_code')} {str(result.get('error'))[:120]}); giving up"
                    )
                    return "undeliverable"

        return "emitted"

    async def _consume_stderr(self, proc: Any, stderr_tail: List[str]) -> None:
        """Collect the tail of stderr for the error field."""
        assert proc.stderr is not None
        total = 0
        while True:
            try:
                line = await proc.stderr.readline()
            except (ValueError, asyncio.LimitOverrunError):
                break
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            stderr_tail.append(text)
            total += len(text)
            while total > _MAX_STDERR_CHARS and len(stderr_tail) > 1:
                total -= len(stderr_tail.pop(0))

    async def _watchdog(
        self,
        proc: Any,
        monitor: Monitor,
        started_at: int,
        outcome: Dict[str, Optional[str]],
        db: Any,
        worker_id: str,
    ) -> None:
        """Heartbeat the lock and honor stop requests, deletion, and timeouts."""
        while proc.returncode is None:
            await asyncio.sleep(_DEFAULT_STOP_CHECK_INTERVAL)

            now = int(time.time())
            if not monitor.persistent and monitor.timeout_seconds and now - started_at >= monitor.timeout_seconds:
                outcome["status"] = "timeout"
                outcome["error"] = f"Monitor timed out after {monitor.timeout_seconds}s"
                self._terminate(proc)
                await self._ensure_killed(proc)
                return

            try:
                current = await _db_call(db, "get_monitor", monitor.id)
            except Exception as exc:
                log_warning(f"Monitor {monitor.id}: watchdog DB check failed: {exc}")
                continue

            if current is None:
                outcome["status"] = "stopped"
                outcome["error"] = "Monitor was deleted"
                self._terminate(proc)
                await self._ensure_killed(proc)
                return

            if current.get("status") == "stopping":
                outcome["status"] = "stopped"
                outcome["error"] = None
                self._terminate(proc)
                await self._ensure_killed(proc)
                return

            # The lock itself is refreshed by the poller's batched heartbeat; this
            # read is what tells us we lost it. If the lock has been taken over,
            # the peer is running its own subprocess, so carrying on would leave
            # two copies of the command alive. Stand down and kill ours instead.
            if not _holds_lease(current, worker_id, monitor.attempt):
                outcome["fenced"] = "yes"
                log_warning(
                    f"Monitor {monitor.id} was reclaimed by another worker; "
                    "stopping this copy and leaving the row to the new holder"
                )
                self._terminate(proc)
                await self._ensure_killed(proc)
                return

    # ------------------------------------------------------------------
    async def _deliver(self, monitor: Monitor, content: str, seq: int) -> Dict[str, Any]:
        """Deliver a single event to the monitor's endpoint."""
        endpoint = monitor.endpoint or ""
        method = (monitor.method or "POST").upper()
        payload = monitor.payload or {}
        url = f"{self.base_url}{endpoint}"

        match = RUN_ENDPOINT_RE.match(endpoint)
        is_run_endpoint = match is not None and method == "POST"

        # (monitor, sequence number) identifies an event for its whole life, so a
        # repeated delivery is recognisable as the same submission rather than a
        # second real run. Honoured only where the durable job queue is enabled --
        # see build_delivery_headers for what this does and does not buy.
        headers = build_delivery_headers(
            self.internal_service_token or "",
            monitor.user_id,
            idempotency_key=f"{monitor.id}:{seq}",
        )

        client = await self._get_client()

        if is_run_endpoint:
            return await self._run_request(client, url, headers, monitor, payload, content, seq)
        headers["Content-Type"] = "application/json"
        return await self._simple_request(client, method, url, headers, monitor, payload, content, seq)

    async def _run_request(
        self,
        client: Any,
        url: str,
        headers: Dict[str, str],
        monitor: Monitor,
        payload: Dict[str, Any],
        content: str,
        seq: int,
    ) -> Dict[str, Any]:
        """Submit a background run carrying the event as the message."""
        base_message = payload.get("message") or f"Monitor '{monitor.name}' emitted an event."
        message = f"{base_message}\n\nEvent {seq}:\n{content}"

        form_payload = build_run_delivery_request(
            payload,
            monitor.user_id,
            source=f"Monitor {monitor.id}",
            # The monitor composes its own message from the event; the payload's
            # is only the prefix, so it must not also ride along as a form field.
            drop_fields=("message",),
        )
        form_payload["message"] = message

        resp = await client.request("POST", url, headers=headers, data=form_payload)

        if resp.status_code >= 400:
            return {
                "delivery_status": "failed",
                "status_code": resp.status_code,
                "run_id": None,
                "session_id": None,
                "error": resp.text,
            }

        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError):
            # A run endpoint always answers JSON carrying the run id. A 2xx that
            # is not JSON came from something else on the path (a gateway, a
            # misrouted URL), so no run was started -- do not report it delivered.
            return {
                "delivery_status": "failed",
                "status_code": resp.status_code,
                "run_id": None,
                "session_id": None,
                "error": "Run endpoint returned a non-JSON body; no run was started",
            }

        return {
            "delivery_status": "delivered",
            "status_code": resp.status_code,
            "run_id": body.get("run_id"),
            "session_id": body.get("session_id"),
            "error": None,
        }

    async def _simple_request(
        self,
        client: Any,
        method: str,
        url: str,
        headers: Dict[str, str],
        monitor: Monitor,
        payload: Dict[str, Any],
        content: str,
        seq: int,
    ) -> Dict[str, Any]:
        """Non-streaming request/response carrying the event as JSON."""
        body = dict(payload)
        body["monitor_id"] = monitor.id
        body["monitor_name"] = monitor.name
        body["event"] = content
        body["seq"] = seq

        resp = await client.request(method, url, headers=headers, json=body)

        delivered = 200 <= resp.status_code < 300
        return {
            "delivery_status": "delivered" if delivered else "failed",
            "status_code": resp.status_code,
            "run_id": None,
            "session_id": None,
            "error": None if delivered else resp.text,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _terminate(proc: Any) -> None:
        """Terminate the subprocess and its whole process group."""
        if proc.returncode is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass

    @staticmethod
    async def _ensure_killed(proc: Any, grace: int = 5) -> None:
        """Escalate to SIGKILL if the process group survives the grace period.

        After the kill the process is reaped (awaited) so it does not linger as a
        zombie -- on the shutdown path the main ``proc.wait()`` was cancelled, so
        nothing else collects it.
        """
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace)
            return
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=grace)
        except asyncio.TimeoutError:
            pass
