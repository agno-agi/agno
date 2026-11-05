"""Durable storage for the messages a compaction replaced.

The archive is what makes compaction non-lossy. A summary alone is a guess about what mattered;
with the originals still readable the summary becomes an index over ground truth, and a detail it
dropped can still be recovered - by a developer reading the row, or by the agent itself when
``search_compacted_messages`` is on.

Records live in the ``agno_compactions`` table, one row per fold, written once and never updated.
Rows rather than files because a fold is a fact about a run: two containers writing different runs
never collide, retention is an ordinary DELETE, and every database Agno supports can store a row -
where the filesystem backend is implemented for SQLite and PostgreSQL only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from agno.models.message import Message
from agno.utils.log import log_debug, log_warning

# Tool results dominate the byte count of a transcript and are the least useful part to read back
# verbatim. Clip each one so a single enormous result cannot bloat one row.
MAX_ARCHIVED_TOOL_RESULT_CHARS = 20_000


def render_message(message: Message) -> str:
    """Render one message as a markdown block. Tool results are clipped to MAX_ARCHIVED_TOOL_RESULT_CHARS."""
    heading = message.role
    if message.tool_name:
        heading = f"{message.role} ({message.tool_name})"
    parts: List[str] = [f"## {heading}"]

    content = message.get_content_string()
    if content:
        parts.append(_clip(content, MAX_ARCHIVED_TOOL_RESULT_CHARS) if message.role == "tool" else content)

    for tool_call in message.tool_calls or []:
        function = tool_call.get("function") if isinstance(tool_call, dict) else None
        if isinstance(function, dict):
            parts.append(f"**calls** `{function.get('name')}`: {function.get('arguments')}")

    return "\n\n".join(parts)


def render_messages(messages: List[Message]) -> str:
    """Render messages as readable markdown.

    Written for a human, or an agent searching the archive, so the role is a heading and tool calls
    name the tool: a search for a tool name or a phrase from an old answer should land on the turn
    that produced it.
    """
    return "\n\n".join(render_message(message) for message in messages)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [clipped, {len(text) - limit} more characters]"


# The most alternatives one search may carry.
MAX_SEARCH_TERMS = 20


def search_terms(pattern: str) -> List[str]:
    """The literal terms of a search: the pattern split on "|"."""
    return [term.strip() for term in pattern.split("|") if term.strip()][:MAX_SEARCH_TERMS]


def stores_compaction_records(db: Any) -> bool:
    """Whether ``db`` can store compaction records - SqliteDb and PostgresDb.

    The sync BaseDb declares the record methods as stubs that raise, so only a db that overrides
    them stores rows; async dbs do not declare them at all.
    """
    method = getattr(type(db), "upsert_compaction", None)
    if method is None:
        return False
    from agno.db.base import BaseDb

    return method is not getattr(BaseDb, "upsert_compaction", None)


class CompactionArchive:
    """Reads and writes one session's compaction records."""

    def __init__(self, db: Any, session_id: str, user_id: Optional[str] = None) -> None:
        self.db = db
        self.session_id = session_id
        self.user_id = user_id

    def _row(self, record: Any, messages: List[Message]) -> Dict[str, Any]:
        return {
            "compaction_id": record.id or uuid4().hex,
            "session_id": self.session_id,
            "run_id": record.run_id,
            "user_id": self.user_id,
            "first_kept_message_id": record.first_kept_message_id,
            "summary": record.summary,
            "archived_messages": render_messages(messages) if messages else None,
            "messages_compacted": record.messages_compacted,
            "tokens_before": record.tokens_before,
            "tokens_after": record.tokens_after,
            "created_at": record.created_at,
        }

    def _method(self, name: str) -> Any:
        """The db's implementation of one record method.

        Only the sync BaseDb declares the record contract, as stubs that raise. A db without the
        method at all - every async db - raises the same way, so it takes the same path.
        """
        method = getattr(self.db, name, None)
        if method is None:
            raise NotImplementedError(name)
        return method

    def write(self, record: Any, messages: List[Message]) -> bool:
        """Persist one record. A failure here loses recoverability, never the run."""
        try:
            self._method("upsert_compaction")(self._row(record, messages))
            log_debug(f"Stored compaction {record.id} with {len(messages)} archived messages")
            return True
        except NotImplementedError:
            log_warning(
                "This database does not implement compaction records; the summary still applies "
                "but the folded messages are not recoverable."
            )
        except Exception as e:  # noqa: BLE001 - persistence must never fail a run
            log_warning(f"Could not store compaction record: {e}")
        return False

    def latest(self, up_to_run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The record in force, as of ``up_to_run_id`` when one is given.

        Resuming or forking an earlier run must use the fold *that run saw*. A later record
        summarizes turns the earlier run never had, and its anchor sits ahead of where that run
        was, so applying it would show the resumed run a summary of its own future.
        """
        try:
            rows = self._method("get_compactions_for_session")(self.session_id)
        except NotImplementedError:
            return None
        except Exception as e:  # noqa: BLE001
            log_warning(f"Could not read compaction records: {e}")
            return None
        if not rows:
            return None
        if up_to_run_id is None:
            return rows[0]
        # Rows are newest first, so the first at or before the target run is the one it saw.
        seen_target = False
        for row in rows:
            if row.get("run_id") == up_to_run_id:
                seen_target = True
            if seen_target:
                return row
        return None

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Candidate rows for a search: every fold containing any of its terms, newest first.

        All terms go to SQL as one substring filter. LIKE wildcards in a term can only widen the
        match, and the caller matches exactly afterwards, so no fold that holds a term is dropped -
        however old it is.
        """
        terms = search_terms(query)
        if not terms:
            return []
        try:
            return self._method("search_compactions")(self.session_id, terms, limit)
        except NotImplementedError:
            return []
        except Exception as e:  # noqa: BLE001
            log_warning(f"Could not search compaction records: {e}")
            return []


__all__ = [
    "CompactionArchive",
    "render_message",
    "render_messages",
    "search_terms",
    "MAX_ARCHIVED_TOOL_RESULT_CHARS",
]
