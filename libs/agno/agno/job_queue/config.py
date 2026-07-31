"""Configuration for the AgentOS job queue.

Background runs (``background=True``) execute through a job queue: submissions
are accepted immediately (PENDING), execute under a concurrency cap, and wait
in line when the cap is reached. ``QueueConfig`` is the single place to
configure this subsystem.

The config grows with the queue's capabilities:
- Execution capping: ``max_concurrency``.
- Coordination: ``redis`` enables BOTH cross-container transports for
  background runs - distributed cancellation (control in) and the Redis event
  stream (events out) - from shared clients. Configuring one without the other
  is the classic misconfiguration (cross-container cancel with process-local
  resume, or vice versa), so one setting wires both. Granular overrides
  (``AgentOS(event_stream=...)``, ``set_cancellation_manager()``) always win.
- Durability: ``durable``, ``db``, depth/retry/timeout policy for the
  DB-backed queue with crash recovery (implemented; see agno.os.job_queue).

This module is pure data: it imports no transports and no redis package.
Wiring happens in ``agno.os.job_queue``.
"""

from dataclasses import dataclass
from typing import Any, Optional, Union


@dataclass
class RedisCoordination:
    """Redis connection settings for queue coordination.

    Provide either ``url`` (clients are constructed for you) or BOTH
    ``sync_client`` and ``async_client`` (e.g. for connection tuning or an
    existing pool). The cancellation manager needs sync and async clients; the
    event stream uses the async client.

    Args:
        url: Redis URL, e.g. ``redis://localhost:6379``.
        sync_client: Existing sync ``redis.Redis``/``RedisCluster`` client.
        async_client: Existing ``redis.asyncio`` client.
    """

    url: Optional[str] = None
    sync_client: Optional[Any] = None
    async_client: Optional[Any] = None
    # Namespace for all coordination keys (event stream + cancellation). Set a
    # per-deployment value when multiple AgentOS deployments share one Redis -
    # with the default, they would read each other's runs by run_id.
    key_prefix: Optional[str] = None

    def __post_init__(self) -> None:
        if self.url is None and (self.sync_client is None or self.async_client is None):
            raise ValueError("RedisCoordination requires either url or both sync_client and async_client")


@dataclass
class QueueConfig:
    """Configuration for background run execution.

    Args:
        max_concurrency: Maximum background runs executing at once per replica,
            shared across agents, teams and workflows. Enforced per event loop
            (process-wide in the standard one-loop-per-process deployment).
            Runs beyond the cap wait in line as PENDING and can be cancelled
            while waiting. 0 or below disables capping. None (the default)
            leaves the current process setting untouched - the
            AGNO_BACKGROUND_MAX_CONCURRENCY env var or the library default of
            32 - so constructing a config to set OTHER fields never silently
            overrides an env-var cap.
        redis: Enables cross-container coordination for background runs. A URL
            string for the common case, or ``RedisCoordination`` to inject
            clients. Wires BOTH the distributed cancellation manager and the
            Redis event stream from shared clients, so cancel and stream resume
            work from any replica. Only replaces in-memory defaults: an
            explicitly configured cancellation manager or event stream is never
            overridden. Also works against Valkey (Redis-protocol compatible).
    """

    max_concurrency: Optional[int] = None
    redis: Optional[Union[str, RedisCoordination]] = None

    # -- Durability -------------------------------------------------------
    # durable=True makes acceptance a committed row in the queue table:
    # accepted runs survive crashes and deploys, reclaimed or terminally
    # failed (visibly) by whichever replica's worker claims them.
    durable: bool = False
    # Queue store override. None = the AgentOS db (zero extra infrastructure).
    # A dedicated store (e.g. a separate Postgres or RedisDb) isolates queue
    # polling load from the system of record.
    db: Optional[Any] = None
    # Global bound on accepted-but-unstarted jobs; beyond it submissions get 429.
    max_queue_depth: int = 1000
    # At most this many executions ever, under any failure mode (reclaim
    # included). 1 = a crashed run is failed visibly, never silently re-run.
    max_attempts: int = 1
    # BASE retry delay: attempt N waits up to base * 2**(N-1) with full
    # jitter (capped at 10x base) - see QueueWorker._retry_delay
    retry_delay_seconds: int = 30
    # Per-run execution timeout enforced by the worker; None disables.
    timeout_seconds: Optional[int] = 3600
    # Stale-lock grace before a crashed worker's jobs are reclaimed. The
    # worker heartbeat refreshes locks, so this can stay small. Caveat: the
    # heartbeat runs on the event loop - a run doing SYNC blocking work (sync
    # model client / sync tool) that starves the loop past this grace will be
    # swept as dead and its eventual completion fenced out (reported failed
    # despite finishing). Keep blocking work in threads, or raise this grace.
    lock_grace_seconds: int = 60
    poll_interval: float = 1.0
    # Terminal jobs older than this are deleted by the worker's retention
    # sweep; the queue table must not grow unboundedly. PAUSED tickets are
    # exempt: a paused run's ticket is what a later continue re-queues, and it
    # must outlive arbitrary human latency. Abandoned paused tickets therefore
    # persist until continued or cancelled - cancel the run to release one.
    retention_seconds: int = 86400

    def __post_init__(self) -> None:
        if self.db is not None and not self.durable:
            raise ValueError("QueueConfig.db requires durable=True (a queue store implies a durable queue)")
        # Numeric sanity: silently-broken configs must fail at construction,
        # not as mysterious runtime behavior
        if self.max_attempts < 1:
            raise ValueError("QueueConfig.max_attempts must be >= 1 (every run needs at least one attempt)")
        if self.poll_interval <= 0:
            raise ValueError("QueueConfig.poll_interval must be > 0 seconds")
        if self.lock_grace_seconds < 3:
            # Heartbeats fire every lock_grace/3: below ~3s the worker races
            # its own heartbeat and reclaims its own healthy jobs
            raise ValueError("QueueConfig.lock_grace_seconds must be >= 3 (heartbeats fire at lock_grace/3)")
        if self.retry_delay_seconds < 0:
            raise ValueError("QueueConfig.retry_delay_seconds must be >= 0 (0 = no backoff)")
        if self.max_queue_depth < 0:
            raise ValueError("QueueConfig.max_queue_depth must be >= 0 (0 = unbounded)")
        if self.retention_seconds <= 0:
            raise ValueError("QueueConfig.retention_seconds must be > 0")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("QueueConfig.timeout_seconds must be > 0 when set (None = no timeout)")
