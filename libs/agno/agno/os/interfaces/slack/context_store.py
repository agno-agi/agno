from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ThreadContext:
    # What the user is looking at, as reported by app_context_changed (agent
    # messaging) or assistant_thread_context_changed (assistant experience)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    # The last title this interface set, so a title_changed echo is not re-applied
    last_title: Optional[str] = None
    # Agno session ids this thread has already named after their first message
    named_sessions: List[str] = field(default_factory=list)


class ThreadContextStore:
    """Per-thread scratch state that Slack does not persist for us."""

    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max_entries
        self._threads: "OrderedDict[Tuple[str, str], ThreadContext]" = OrderedDict()

    def _get_or_create(self, channel: str, thread_ts: str) -> ThreadContext:
        key = (channel, thread_ts)
        ctx = self._threads.get(key)
        if ctx is None:
            ctx = ThreadContext()
            self._threads[key] = ctx
            while len(self._threads) > self._max_entries:
                self._threads.popitem(last=False)
        return ctx

    def get(self, channel: str, thread_ts: str) -> Optional[ThreadContext]:
        return self._threads.get((channel, thread_ts))

    def set_entities(self, channel: str, thread_ts: str, context: Optional[Dict[str, Any]]) -> None:
        ctx = self._get_or_create(channel, thread_ts)
        context = context or {}
        entities = context.get("entities")
        if isinstance(entities, list):
            ctx.entities = [e for e in entities if isinstance(e, dict)]
        elif context.get("channel_id"):
            # Assistant experience reports a single channel instead of an entity list
            ctx.entities = [{"type": "slack#/types/channel_id", "value": context["channel_id"]}]
        else:
            ctx.entities = []

    def set_last_title(self, channel: str, thread_ts: str, title: str) -> None:
        self._get_or_create(channel, thread_ts).last_title = title

    def mark_session_named(self, channel: str, thread_ts: str, session_id: str) -> bool:
        """Record that ``session_id`` was named; returns False if it already was."""
        ctx = self._get_or_create(channel, thread_ts)
        if session_id in ctx.named_sessions:
            return False
        ctx.named_sessions.append(session_id)
        return True

    def entities_for(self, channel: str, thread_ts: str) -> List[Dict[str, Any]]:
        ctx = self.get(channel, thread_ts)
        return list(ctx.entities) if ctx else []
