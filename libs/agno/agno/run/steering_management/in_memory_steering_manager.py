"""In-memory run steering."""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from agno.models.message import Message
from agno.run.steering_management.base import BaseRunSteeringManager


@dataclass
class _Inbox:
    accepting: bool = True
    pending: List[Message] = field(default_factory=list)
    # Only a released inbox holding undelivered input expires; an open inbox
    # belongs to a model loop that is still running.
    expires_at: float = float("inf")


class InMemoryRunSteeringManager(BaseRunSteeringManager):
    """Single-process steering: the steering caller and the run share one process.

    One threading lock guards both the sync and the async methods. A sync run
    executes in a worker thread while steer() may be called from an event loop
    (or the reverse), so the two paths must exclude each other; every critical
    section is a few list operations and never awaits.

    Args:
        ttl_seconds: How long a released inbox keeps undelivered input for a
            later leg of its run (a continuation after a pause, or a retry).
            Defaults to 86400 (1 day). None keeps it until that leg opens it.
    """

    DEFAULT_TTL_SECONDS = 60 * 60 * 24

    def __init__(self, ttl_seconds: Optional[float] = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._inboxes: Dict[str, _Inbox] = {}
        self._lock = threading.Lock()
        self._clock = time.monotonic

    def _purge_expired(self) -> None:
        """Drop released inboxes past their TTL. Must be called with the lock held."""
        now = self._clock()
        expired = [run_id for run_id, inbox in self._inboxes.items() if inbox.expires_at <= now]
        for run_id in expired:
            del self._inboxes[run_id]

    def open_run(self, run_id: str) -> None:
        with self._lock:
            self._purge_expired()
            inbox = self._inboxes.get(run_id)
            if inbox is None:
                self._inboxes[run_id] = _Inbox()
            else:
                inbox.accepting = True
                inbox.expires_at = float("inf")

    def steer(self, run_id: str, messages: List[Message]) -> bool:
        with self._lock:
            inbox = self._inboxes.get(run_id)
            if inbox is None or not inbox.accepting:
                return False
            inbox.pending.extend(messages)
            return True

    def take(self, run_id: str) -> List[Message]:
        with self._lock:
            inbox = self._inboxes.get(run_id)
            if inbox is None or not inbox.pending:
                return []
            taken, inbox.pending = inbox.pending, []
            return taken

    def take_or_close(self, run_id: str) -> List[Message]:
        # The check and the close share one critical section: a steer() landing between
        # "nothing pending" and "closed" would be accepted and never read.
        with self._lock:
            inbox = self._inboxes.get(run_id)
            if inbox is None:
                return []
            if inbox.pending:
                taken, inbox.pending = inbox.pending, []
                return taken
            del self._inboxes[run_id]
            return []

    def release_run(self, run_id: str) -> None:
        with self._lock:
            inbox = self._inboxes.get(run_id)
            if inbox is None:
                return
            if not inbox.pending:
                del self._inboxes[run_id]
                return
            inbox.accepting = False
            inbox.expires_at = float("inf") if self.ttl_seconds is None else self._clock() + self.ttl_seconds
