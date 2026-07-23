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
from typing import Optional


@dataclass
class RunQueueConfig:
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
    """

    max_concurrency: Optional[int] = None
