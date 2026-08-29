"""Per-run compaction state and the process-wide in-flight fold registry.

CompactionRunState is created per run and never stored on the Compaction config object, never
serialized: sharing the config across agents and runs stays safe because nothing mutable lives on
it. The one deliberate process-global structure is the in-flight registry, which caps background
folds at one per (session, owner) and lets a later run see a still-flying post-run fold.
"""

import threading
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from agno.compaction._notice import NoticeInputs
from agno.compaction._tokens import ContextGauge
from agno.compaction.compaction import Compaction, CompactionRecord, EffectiveLimits

if TYPE_CHECKING:
    from agno.compaction.compaction import PassPlan


@dataclass
class FoldHandle:
    """A background fold in flight: a thread (sync paths) or an asyncio task (async paths).

    The fold is pure — its input segment was frozen at pass start — so an abandoned handle loses
    nothing but the spent tokens.
    """

    plan: "PassPlan"
    thread: Optional[threading.Thread] = None
    task: Any = None  # asyncio.Task on async paths
    record: Optional[CompactionRecord] = None  # set by the worker on success
    error: Optional[BaseException] = None  # set by the worker on failure

    def done(self) -> bool:
        if self.thread is not None:
            return not self.thread.is_alive()
        if self.task is not None:
            return bool(self.task.done())
        return True

    def join(self, timeout: Optional[float] = None) -> Optional[CompactionRecord]:
        """Wait for a thread-backed fold and return its record (None on failure)."""
        if self.thread is not None:
            self.thread.join(timeout)
            if self.thread.is_alive():
                return None
        return self.record

    async def ajoin(self) -> Optional[CompactionRecord]:
        """Wait for a task-backed fold and return its record (None on failure)."""
        if self.task is not None:
            try:
                await self.task
            except Exception:
                pass
        elif self.thread is not None:
            import asyncio

            await asyncio.to_thread(self.thread.join)
        return self.record


_IN_FLIGHT: Dict[Tuple[str, str], FoldHandle] = {}
_IN_FLIGHT_LOCK = threading.Lock()

# Run states by run_id, weakly held (the strong reference rides the run output object), so the
# compact_status / compact_run tools can reach their run's state from an injected run_context.
_RUN_STATES: "weakref.WeakValueDictionary[str, CompactionRunState]" = weakref.WeakValueDictionary()


def register_run_state(run_id: str, state: "CompactionRunState") -> None:
    _RUN_STATES[run_id] = state


def get_run_state(run_id: Optional[str]) -> Optional["CompactionRunState"]:
    if not run_id:
        return None
    return _RUN_STATES.get(run_id)


def register_fold(session_id: str, owner_id: str, handle: FoldHandle) -> bool:
    """Claim the single in-flight slot for this (session, owner); False when already taken."""
    key = (session_id, owner_id)
    with _IN_FLIGHT_LOCK:
        existing = _IN_FLIGHT.get(key)
        if existing is not None and not existing.done():
            return False
        _IN_FLIGHT[key] = handle
        return True


def in_flight_fold(session_id: str, owner_id: str) -> Optional[FoldHandle]:
    with _IN_FLIGHT_LOCK:
        handle = _IN_FLIGHT.get((session_id, owner_id))
        return handle if handle is not None and not handle.done() else handle


def clear_fold(session_id: str, owner_id: str, handle: FoldHandle) -> None:
    key = (session_id, owner_id)
    with _IN_FLIGHT_LOCK:
        if _IN_FLIGHT.get(key) is handle:
            del _IN_FLIGHT[key]


@dataclass
class CompactionRunState:
    """Everything the model loop needs in and out for one run. Created per run, never persisted."""

    config: Compaction
    limits: EffectiveLimits
    gauge: ContextGauge
    session_id: str
    owner_id: str
    run_id: Optional[str] = None
    # The record governing views right now; seeded at build time, replaced at loop-tops.
    active_record: Optional[CompactionRecord] = None
    # The owner's committed chain as loaded at build time, oldest first (for walk-back and fold
    # provenance); in-run records are appended here on activation.
    chain: List[CompactionRecord] = field(default_factory=list)
    # In-run records awaiting the commit-on-COMPLETED persist; drained merge-by-id at terminal persist.
    pending_records: List[CompactionRecord] = field(default_factory=list)
    # A compact_run() tool request waiting for the next loop-top; at most one.
    scheduled: bool = False
    scheduled_instructions: Optional[str] = None
    # The in-flight background fold, if this run started one.
    fold_future: Optional[FoldHandle] = None
    # Probes for the survival notice, built at agent level so the model loop imports nothing new.
    notice_sources: Optional[Callable[[], NoticeInputs]] = None
    # Strip response-chaining provider_data from every outgoing payload while compaction is set.
    strip_provider_chaining: bool = False
    # First index in the canonical list that belongs to the current run (in-run cuts land at or
    # after it, so a record's boundary run is simply the current run).
    first_own_message_index: int = 0
    # Set when a pass completed but the view is still over trigger; warn once, never loop.
    still_over_trigger: bool = False
    # One compact-and-retry per successful provider call: set on an overflow pass, cleared when a
    # provider call succeeds; a second overflow with this set propagates.
    overflow_attempted: bool = False
    # False when store_tool_messages is off: scrub deletes assistant batch heads, so they cannot anchor.
    allow_tool_batch_heads: bool = True
    # Pass observability: {"type": "started"/"completed", ...numbers...} appended by the loop
    # helpers; stream loops drain these into marker events, non-stream callers convert what
    # remains after the call returns. Payloads carry numbers only, never summary text.
    event_buffer: List[Dict[str, Any]] = field(default_factory=list)
