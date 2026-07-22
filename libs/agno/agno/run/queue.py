"""Configuration for the AgentOS run queue.

Background runs (``background=True``) execute through a run queue: submissions
are accepted immediately (PENDING), execute under a concurrency cap, and wait
in line when the cap is reached. ``RunQueueConfig`` is the single place to
configure this subsystem.

The config grows with the queue's capabilities:
- Execution capping (this release): ``max_concurrency``.
- Coordination: a ``redis`` field enabling the cross-container transports
  (cancellation in, events out) ships with the pluggable event stream.
- Durability (planned): ``durable``, ``db``, depth/retry/timeout policy for the
  DB-backed queue with crash recovery.
"""

from dataclasses import dataclass

# Default mirrors agno.run.concurrency.DEFAULT_BACKGROUND_MAX_CONCURRENCY;
# duplicated as a literal so this module stays a pure-data import.
_DEFAULT_MAX_CONCURRENCY = 32


@dataclass
class RunQueueConfig:
    """Configuration for background run execution.

    Args:
        max_concurrency: Maximum background runs executing at once per replica,
            shared across agents, teams and workflows. Enforced per event loop
            (process-wide in the standard one-loop-per-process deployment).
            Runs beyond the cap wait in line as PENDING and can be cancelled
            while waiting. 0 or below disables capping.
    """

    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY
