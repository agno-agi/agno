from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from agno.utils.dttm import now_epoch_s, to_epoch_s

# Statuses a monitor can be restarted from. Shared so the manager and the router
# cannot drift on what "finished" means.
TERMINAL_STATUSES = ("completed", "failed", "timeout", "stopped")

# Every status a monitor row can hold, and every delivery outcome an event can
# hold. These exist so the filter parameters on the list routes can refuse a
# value that is not one of them: a filter that answers 200-with-nothing for a
# typo reports "there are none" when it means "I did not understand you", and
# for delivery_status that is the difference between "no deliveries were lost"
# and "you misspelled pending". They are also the single source of truth for the
# values documented on Monitor.status and MonitorEvent.delivery_status, which
# drifted from the code once already.
MONITOR_STATUSES = ("pending", "running", "stopping", *TERMINAL_STATUSES)
DELIVERY_STATUSES = ("pending", "delivered", "failed")

# What a monitor's owner may change: what it is called, where it delivers, and
# how long it is allowed to watch. Ownership and identity are absent on purpose:
# user_id stays a WHERE filter in the adapters, never a SET column, so a monitor
# can never be re-owned through an update.
MONITOR_USER_MUTABLE_COLUMNS = frozenset(
    {
        "name",
        "description",
        "endpoint",
        "method",
        "payload",
        "timeout_seconds",
        "persistent",
        "max_events",
        # How much of what it watches becomes an event. Editable for the same
        # reason the deadline is: it tunes an existing watch rather than
        # repointing it, and a watch that turns out to be too noisy is the most
        # likely thing an owner wants to change without recreating the monitor.
        "exclude",
        "use_default_filter",
    }
)

# Lifecycle state. Unlike a schedule, a monitor's status, lock, counters, exit and
# process identity are written by the poller and executor through this same
# ``update_monitor`` call rather than dedicated APIs, so they are mutable here --
# but they are theirs alone. A request that sets them races the worker that owns
# the row, and the fenced write the worker relies on cannot see an unfenced one
# coming.
MONITOR_WORKER_MUTABLE_COLUMNS = frozenset(
    {
        "status",
        "exit_code",
        "error",
        "event_count",
        "started_at",
        "finished_at",
        "locked_by",
        "locked_at",
        "worker_host",
        "proc_pid",
        "proc_pgid",
        "proc_started_at",
    }
)

# The watch target belongs to neither. It selects the executor's whole code path
# -- watch a path, run a declared command, or follow a run -- and nothing
# rewrites it after creation: restart re-arms status and clears the lock, it
# never repoints the watch. Writable at the DB layer, so a caller assembling a
# row column by column still can, but never through an owner-facing edit: an
# executor snapshots the row when it claims it, so repointing a live watch has
# no defined behaviour.
MONITOR_WATCH_TARGET_COLUMNS = frozenset({"watch_path", "watch_command", "watch_run_id"})

# Everything ``update_monitor`` accepts, which is the union: the executor writes
# worker columns through the same call an owner's edit uses.
MONITOR_MUTABLE_COLUMNS = MONITOR_USER_MUTABLE_COLUMNS | MONITOR_WORKER_MUTABLE_COLUMNS | MONITOR_WATCH_TARGET_COLUMNS


def validate_monitor_update(kwargs: dict) -> None:
    """Refuse update_monitor writes outside the mutable column set."""
    rejected = sorted(set(kwargs) - MONITOR_MUTABLE_COLUMNS)
    if rejected:
        raise ValueError(
            f"update_monitor cannot modify {rejected}: only {sorted(MONITOR_MUTABLE_COLUMNS)} are mutable; "
            "ownership and identity are fixed at creation"
        )


def validate_watch_target(
    watch_command: Optional[str],
    watch_run_id: Optional[str],
    watch_path: Optional[Union[str, List[str]]] = None,
) -> None:
    """Require exactly one watch target: a path, a declared command, or a run.

    The three are alternatives, not a set -- the executor picks its whole code
    path from which one is set, so a monitor carrying two (or none) has no
    defined behaviour and must never reach the database. Several PATHS are still
    one target: they are handed to a single watcher together.
    """
    paths = [watch_path] if isinstance(watch_path, str) else list(watch_path or [])
    targets = {
        "watch_path": any(p and p.strip() for p in paths),
        "watch_command": bool(watch_command and watch_command.strip()),
        "watch_run_id": bool(watch_run_id and watch_run_id.strip()),
    }
    set_targets = sorted(name for name, is_set in targets.items() if is_set)
    if len(set_targets) > 1:
        raise ValueError(f"A monitor watches one thing, but {set_targets} were all set")
    if not set_targets:
        raise ValueError(
            "A monitor needs a watch target: watch_path to watch files, "
            "watch_command to run a declared command, or watch_run_id to follow a run"
        )


def validate_watch_path(
    watch_path: Optional[Union[str, List[str]]], base_dir: Optional[Any], must_exist: bool = False
) -> Optional[List[str]]:
    """Contain the watched path(s) inside the deployment's root, or refuse them.

    Accepts one path or several and always returns a LIST of resolved absolute
    paths, so a caller that has already validated does not resolve twice and
    everything downstream sees one shape. ``None`` in, ``None`` out.

    Several paths are one watch rather than several monitors because the
    underlying watcher takes them together -- ``awatch(*paths)`` -- so one row
    still means one watcher with one lifecycle, and the row's single status,
    exit code and event count stay honest. That is exactly what mixing target
    KINDS could not preserve: a row watching a path and a command has no true
    answer for ``status`` when the command exits non-zero while the path watch
    is healthy.

    A path is data, not a command, which is why this target needs no operator
    declaration the way ``watch_command`` does -- there is nothing to inject
    into. What it does need is a root, because "watch a file" would otherwise
    read any path the server process can reach: an event's content names the
    files that changed, so an uncontained watch on a secrets directory leaks
    those names to whoever can read the monitor's events.

    The containment itself is delegated rather than reimplemented. Traversal,
    absolute paths, symlinks pointing out of the root, control characters and
    Windows device names are all already handled by the shared helper the file
    toolkits use, and a second implementation of that would be a second thing
    to get wrong.

    Raised as ValueError, not PathSecurityError, because creation has three
    doors -- the route, MonitorManager and MonitorTools -- and all three already
    turn ValueError into their own refusal shape (422, the exception, a JSON
    error handed back to the model).
    """
    if watch_path is None:
        return None

    from pathlib import Path

    from agno.exceptions import PathSecurityError
    from agno.utils.path_safety import safe_join_relative_path

    raw = [watch_path] if isinstance(watch_path, str) else list(watch_path)
    candidates = [p for p in raw if p and p.strip()]
    if not candidates:
        return None

    root = Path(base_dir) if base_dir is not None else Path.cwd()
    resolved: List[str] = []
    for candidate in candidates:
        try:
            resolved.append(str(safe_join_relative_path(root, candidate)))
        except PathSecurityError as exc:
            # Named individually: with several paths, "one of them is outside the
            # root" leaves the caller checking each by hand.
            raise ValueError(f"watch_path {candidate!r} is not allowed: {exc}") from None
    # De-duplicated but order-preserving. Two names for one directory would have
    # the watcher report every change under it twice, and each duplicate event
    # starts a real run when an endpoint is set.
    deduped = list(dict.fromkeys(resolved))

    # Creation checks that the path is actually there; the executor does not.
    # A watch on a path that does not exist cannot ever fire, and without this
    # the caller is told the watch started -- id and all -- and only the poller
    # finds out, seconds later, in a log nobody is reading. That is the same
    # accepted-but-doomed shape an archived delivery target is already refused
    # for. A model asked to "watch the reports folder" invents the path most
    # readily of all, which is exactly when a confident false success is worst.
    if must_exist:
        missing = [p for p in deduped if not Path(p).exists()]
        if missing:
            raise ValueError(
                f"watch_path does not exist: {', '.join(repr(p) for p in missing)}. "
                "Create it before starting the watch."
            )
    return deduped


def resolve_watch_description(
    description: Optional[str],
    watch_command: Optional[str],
    watch_commands: Optional[Any],
) -> Optional[str]:
    """Fall back to the declaration's own description when the caller gave none.

    A monitor row stores the NAME of a declared command, never the command, so
    ``watch_command="db_check"`` is all anyone reading the row months later
    gets -- and a name is not a description. The declaration already carries
    one; nothing was copying it onto the row.

    The command string itself stays off the row and out of every response on
    purpose. It is operator-authored and can hold anything that was to hand --
    ``psql postgres://admin:hunter2@prod/db`` is an ordinary thing to declare --
    and ``monitors:read`` is a READ scope handed to people who are not the
    operator. The description is the operator's own sentence about the same
    command, which is the part that is safe to publish and the part that
    actually answers "what does this monitor do".

    An explicit description always wins: the caller is describing this monitor,
    the declaration describes the command every monitor using it shares.
    """
    if description is not None and description.strip():
        return description
    if not watch_command or not watch_commands:
        return description
    declared = watch_commands.get(watch_command)
    if declared is None:
        return description
    # Both declaration shapes: a WatchCommand carries .description, and the
    # bare-string form has none to inherit.
    inherited = getattr(declared, "description", None)
    return inherited or description


def validate_run_watch_is_bounded(watch_run_id: Optional[str], persistent: bool) -> None:
    """A run watch must keep its deadline.

    ``persistent`` means "no timeout, run until stopped", which suits a command
    that keeps printing. A run settles exactly once, so there is nothing for a
    run watch to persist for -- and the combination is a slot held for as long as
    the process lives. A run id that never appears (a typo, a deleted run) then
    occupies a worker slot forever, doing nothing, with no deadline to end it.
    """
    if watch_run_id and persistent:
        raise ValueError(
            "A run watch cannot be persistent: a run settles once, so the watch needs a "
            "timeout_seconds deadline to bound how long it waits"
        )


def validate_restart_budget(max_events: Optional[int], event_count: Optional[int]) -> None:
    """Refuse a restart that has no events left to emit.

    ``max_events`` is a lifetime budget, so a monitor that has spent it comes
    straight back to stopped without emitting anything -- a restart that quietly
    does nothing. Saying so is also what stops restart being a way to buy more
    model runs: with an endpoint set every event starts one, and restart needs
    only ``monitors:write``.
    """
    if (max_events or 0) > 0 and (event_count or 0) >= (max_events or 0):
        raise ValueError(
            f"Monitor has already emitted its {max_events} allotted events. "
            "Raise max_events before restarting, or create a new monitor."
        )


def validate_event_budget(persistent: bool, max_events: Optional[int], endpoint: Optional[str]) -> None:
    """Refuse a persistent delivering monitor with no cap on how much it delivers.

    Its rate is whatever its command prints, and every event it delivers starts
    a real model run -- so the three together are an unbounded run generator.
    Capping any one of them is enough.

    This lives here rather than in the HTTP request model because it is a
    property of a monitor, not of a request: creation has three doors (the
    route, MonitorManager, and MonitorTools, whose caller is a model), and a
    check on only the first is a check the other two walk past.
    """
    if persistent and (max_events or 0) == 0 and endpoint is not None:
        raise ValueError(
            "A persistent monitor that delivers to an endpoint needs a max_events cap; "
            "otherwise it starts runs for as long as its command keeps printing"
        )


@dataclass
class Monitor:
    """Model for a background monitor watching a declared command or a run."""

    id: str
    name: str
    # Exactly one watch target is set, and it selects the executor's whole code
    # path.
    #
    # ``watch_path`` watches a file or directory and emits one event per change,
    # naming what changed. It is the only target that needs nothing declared
    # ahead of time -- a path is data, not code -- so it is the one a caller (or
    # a model holding MonitorTools) can name freely. Stored resolved and already
    # contained inside the deployment's root.
    #
    # ``watch_command`` names a command the operator declared on AgentOS via
    # ``watch_commands``; the executor resolves it and turns the subprocess's
    # stdout into events. Storing the name rather than the command is what keeps
    # a shell string out of the request body, so creating a monitor is never a
    # way to run arbitrary code.
    #
    # ``watch_run_id`` follows an existing run's status in the runs table and
    # emits one event when it reaches a terminal state.
    watch_path: Optional[List[str]] = None
    watch_command: Optional[str] = None
    watch_run_id: Optional[str] = None
    # Extra glob patterns excluded from a path watch, on top of whatever
    # ``use_default_filter`` leaves in place.
    exclude: Optional[List[str]] = None
    # Whether the watcher's own default exclusions apply. They drop the noise
    # nobody wants to spend a model run on -- .git, .venv, __pycache__,
    # node_modules, editor swap files, compiled Python -- which is right often
    # enough to be the default and wrong often enough to be a choice: a watch
    # that looks inert is usually watching something on that list, and turning
    # this off is how an owner sees it.
    use_default_filter: bool = True
    description: Optional[str] = None
    endpoint: Optional[str] = None
    method: str = "POST"
    payload: Optional[Dict[str, Any]] = None
    timeout_seconds: int = 300
    persistent: bool = False
    max_events: int = 100
    status: str = "pending"  # pending | running | stopping | completed | failed | timeout | stopped
    exit_code: Optional[int] = None
    error: Optional[str] = None
    event_count: int = 0
    started_at: Optional[int] = None
    finished_at: Optional[int] = None
    locked_by: Optional[str] = None
    locked_at: Optional[int] = None
    # Where the command is running, and proof of which process it is. Set when a
    # subprocess is spawned, cleared when it ends. A worker that inherits an
    # orphaned row uses these to kill the leftover before starting its own copy --
    # but only when the host matches AND pid+start-time still identify the same
    # process, because pids are recycled.
    worker_host: Optional[str] = None
    proc_pid: Optional[int] = None
    proc_pgid: Optional[int] = None
    proc_started_at: Optional[str] = None
    # Lease generation, bumped by every claim. Writes are fenced on
    # (locked_by, attempt) so a reclaim invalidates the previous execution's
    # writes instead of racing them.
    attempt: int = 0
    # Owner. NULL means system-created: migrations, legacy rows.
    user_id: Optional[str] = None
    created_at: Optional[int] = None
    updated_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)
        if self.updated_at is not None:
            self.updated_at = to_epoch_s(self.updated_at)
        if self.started_at is not None:
            self.started_at = int(self.started_at)
        if self.finished_at is not None:
            self.finished_at = int(self.finished_at)
        if self.locked_at is not None:
            self.locked_at = int(self.locked_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values (important for DB updates)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "watch_path": self.watch_path,
            "watch_command": self.watch_command,
            "watch_run_id": self.watch_run_id,
            "exclude": self.exclude,
            "use_default_filter": self.use_default_filter,
            "endpoint": self.endpoint,
            "method": self.method,
            "payload": self.payload,
            "timeout_seconds": self.timeout_seconds,
            "persistent": self.persistent,
            "max_events": self.max_events,
            "status": self.status,
            "exit_code": self.exit_code,
            "error": self.error,
            "event_count": self.event_count,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "attempt": self.attempt,
            "worker_host": self.worker_host,
            "proc_pid": self.proc_pid,
            "proc_pgid": self.proc_pgid,
            "proc_started_at": self.proc_started_at,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Monitor":
        data = dict(data)
        valid_keys = {
            "id",
            "name",
            "description",
            "watch_path",
            "watch_command",
            "watch_run_id",
            "exclude",
            "use_default_filter",
            "endpoint",
            "method",
            "payload",
            "timeout_seconds",
            "persistent",
            "max_events",
            "status",
            "exit_code",
            "error",
            "event_count",
            "started_at",
            "finished_at",
            "locked_by",
            "locked_at",
            "attempt",
            "worker_host",
            "proc_pid",
            "proc_pgid",
            "proc_started_at",
            "user_id",
            "created_at",
            "updated_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class MonitorEvent:
    """Model for a single event emitted by a monitor."""

    id: str
    monitor_id: str
    seq: int = 1
    content: str = ""
    # None (the monitor has no endpoint, so nothing was ever sent) | pending |
    # delivered | failed. "pending" is written before the event is sent and is
    # normally replaced within milliseconds -- but it can also be a resting
    # state: the event counter is bumped BEFORE delivery, so a worker that dies
    # mid-delivery leaves the row at "pending" and the re-claimed execution
    # resumes past that sequence number rather than re-sending it. That is the
    # deliberate trade -- a lost delivery rather than a duplicated one, because
    # every duplicate here is a real model run -- and this column is where it
    # shows. Nothing retries these.
    delivery_status: Optional[str] = None
    status_code: Optional[int] = None
    run_id: Optional[str] = None
    session_id: Optional[str] = None
    error: Optional[str] = None
    # Denormalised from the parent ``Monitor.user_id`` so the events router can
    # scope by owner without reading the monitor back.
    user_id: Optional[str] = None
    created_at: Optional[int] = None

    def __post_init__(self) -> None:
        self.created_at = now_epoch_s() if self.created_at is None else to_epoch_s(self.created_at)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict. Preserves None values."""
        return {
            "id": self.id,
            "monitor_id": self.monitor_id,
            "seq": self.seq,
            "content": self.content,
            "delivery_status": self.delivery_status,
            "status_code": self.status_code,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "error": self.error,
            "user_id": self.user_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonitorEvent":
        data = dict(data)
        valid_keys = {
            "id",
            "monitor_id",
            "seq",
            "content",
            "delivery_status",
            "status_code",
            "run_id",
            "session_id",
            "error",
            "user_id",
            "created_at",
        }
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)
