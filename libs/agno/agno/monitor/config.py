"""Configuration for the AgentOS monitor subsystem.

A monitor is a background watch: it watches a path, runs a command the operator
declared, or follows a run, and turns what it sees into events. With an endpoint
set, every one of those events starts a real model run -- so a monitor is a
process, a slot on a worker, a row that outlives the request that made it, and a
run generator all at once. ``MonitorConfig`` is the single place to bound all of
that, passed as ``AgentOS(monitors=MonitorConfig(...))``.

The fields fall into three groups:
- Containment: ``base_dir`` and ``watch_commands`` decide what a monitor is
  allowed to watch at all -- a root for paths, an allowlist for commands. An
  undeclared command is refused outright, but an unset root is only as narrow as
  the directory the process happened to start in, which is why it is the one
  field worth setting explicitly in production.
- Capacity: ``max_concurrent``, ``max_concurrent_per_user`` and ``max_per_user``
  decide how many watches exist and how many run at once. Persistent watches
  never finish, so without these one tenant holds every slot forever.
- Timing and housekeeping: ``poll_interval``, ``lock_grace_seconds`` and
  ``retention_seconds`` decide how quickly work is picked up, when a dead
  worker's claims are reclaimed, and when spent events are swept.

This module is pure data: it starts no poller and opens no database. Wiring
happens in ``agno.os.app``. The watch declarations are imported from the leaf
module rather than the ``agno.monitor`` package, which pulls in the executor and
imports back into ``agno.os``.
"""

from dataclasses import dataclass
from typing import Mapping, Optional, Union

from agno.monitor.watch import WatchCommand, normalize_watch_commands


@dataclass
class MonitorConfig:
    """Configuration for the background monitor poller.

    Args:
        base_dir: The root a path watch is contained to (default: the process
            working directory). A monitor watching a path names the files that
            changed in every event it emits, so an uncontained watch reads any
            path the server process can reach -- one pointed at a secrets
            directory leaks those names to anyone who can read the monitor's
            events. Paths are given relative to this root, the same contract
            ``FileTools(base_dir=...)`` has. One monitor may watch several paths
            at once, and each is contained to this same root separately -- a list
            is not a way past it, and one path outside the root refuses the whole
            create rather than being quietly dropped from the watch.
        watch_commands: Named shell commands monitors may run, e.g.
            ``{"error_log": "tail -F app.log | grep --line-buffered ERROR"}``. A
            monitor stores only the name, so creating one never carries a shell
            string over the wire and ``monitors:write`` is not equivalent to
            shell access -- a command nobody declared here is refused at create
            rather than failing later on a worker. Use a ``WatchCommand`` instead
            of a bare string to say where it runs and what it is for:
            ``WatchCommand(command="tail -F app.log", cwd="/srv/app",
            description="new lines in the app log")``. Without a cwd the command
            inherits the server's working directory, and it always inherits the
            server's environment -- including whatever credentials are in it.
        poll_interval: Seconds between poll cycles (default: 5). This is the
            delay between a monitor being created and a worker claiming it, so a
            long interval makes creation feel unanswered; a very short one is a
            claim query per replica per tick against the monitors table for as
            long as the process lives.
        max_concurrent: How many monitors one worker runs at once (default: 10).
            Persistent monitors hold their slot until stopped, so this is also
            the cap on concurrent persistent watches per replica. Without it
            every claimable pending row would spawn a subprocess at once, and a
            deployment's capacity would be whatever its users happened to create.
        max_concurrent_per_user: How many of those slots one owner may hold
            (default: a quarter of ``max_concurrent``, minimum 1; 0 disables).
            Persistent watches never finish, so without this the tenant who
            creates monitors first keeps every slot and later tenants wait
            indefinitely. Monitors with no owner are exempt -- with user
            isolation off there is no tenant boundary to enforce.
        max_per_user: How many unfinished monitors one owner may have (default:
            20; 0 disables the limit). Creating past it answers 429, the way a
            full job queue does. This bounds how many a user can create; what
            stops one owner occupying every execution slot is
            ``max_concurrent_per_user``.
        retention_seconds: How long monitor events are kept (default: 7 days; 0
            disables the sweep). Events accrue under live persistent watches, so
            without this the events table grows for as long as a watch runs.
        lock_grace_seconds: Seconds a claim may go unrefreshed before a peer may
            reclaim it (default: 30). Also the window in which a dead worker's
            monitors still read as running: too long strands work nobody is
            doing, and too short expires a healthy monitor's lock between
            heartbeats so the poller reclaims what it is already running (refused
            at startup below the poller's floor).

    Multi-replica uniformity: ``lock_grace_seconds`` and ``retention_seconds``
    must be configured UNIFORMLY across every replica sharing one monitors table.
    Each is applied by whichever replica performs the action -- the claimer's
    grace sets its heartbeat cadence while a peer's grace judges staleness, and
    the smallest ``retention_seconds`` in the fleet wins the sweep -- so
    divergent values (including transiently, during a rolling deploy) reclaim a
    healthy peer's monitors or delete events early. The capacity fields are
    per-replica by definition and need no such agreement.
    """

    base_dir: Optional[str] = None
    watch_commands: Optional[Mapping[str, Union[str, WatchCommand]]] = None

    # -- Timing -----------------------------------------------------------
    poll_interval: int = 5

    # -- Capacity ---------------------------------------------------------
    max_concurrent: int = 10
    max_concurrent_per_user: Optional[int] = None
    max_per_user: int = 20

    # -- Housekeeping -----------------------------------------------------
    retention_seconds: int = 7 * 24 * 3600
    lock_grace_seconds: int = 30

    def __post_init__(self) -> None:
        # Settled to the full form once, here, so everything reading this config
        # sees one shape. The empty mapping matters as much as the contents: it
        # is the difference between "this deployment declares no commands, so
        # refuse every watch_command" and "no declarations were configured", and
        # ``None`` reaching the create route reads as the latter -- which would
        # let a monitor name a command no operator ever declared.
        self.watch_commands = normalize_watch_commands(self.watch_commands)
