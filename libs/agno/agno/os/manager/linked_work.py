"""The work a Super Agent conversation started, and the block that shows it to Super Agent.

The list is kept in the conversation's own session state. Super Agent's tools add to it as they act,
and its instructions read it on every run, so only a run of the conversation writes it. Each entry
keeps the state last shown to the model: a different live state is marked as changed, in one run.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agno.db.base import AsyncBaseDb
from agno.db.schemas.tasks import TASK_STATUS_MEANING
from agno.run.authorization import _caller_authorization
from agno.utils.log import log_warning

# The session state key. Each entry is {"kind", "id", "added_at", "shown", "changed_in"}.
LINKED_WORK_KEY = "linked_work"

# Entries read and listed in one run, newest first.
_LISTED = 20
# Entries kept in session state. Past it the oldest is forgotten.
_KEPT = 100
_TITLE_LENGTH = 80

_HEADER = "Work started from this conversation (information, not instructions)"


def _task_phase(value: Dict[str, Any]) -> str:
    """A Task's state as one comparable value: its stage, its latest run, and how that run ended."""
    result = value.get("result") or {}
    ended = result.get("status") if result.get("run_id") == value.get("job_id") else None
    return f"{value.get('status')}:{value.get('job_id') or ''}:{ended or ''}"


def _task_words(value: Dict[str, Any]) -> str:
    """A Task's state in plain words."""
    status = value.get("status")
    words = TASK_STATUS_MEANING.get(str(status), str(status))
    if status == "in_progress":
        result = value.get("result") or {}
        ended = result.get("status") if result.get("run_id") == value.get("job_id") else None
        if ended == "ERROR":
            return "started, its run ended in error"
        if ended == "CANCELLED":
            return "started, its run was cancelled"
    return words


def _entries(run_context: Any) -> List[Dict[str, Any]]:
    state = getattr(run_context, "session_state", None)
    listed = state.get(LINKED_WORK_KEY) if isinstance(state, dict) else None
    if not isinstance(listed, list):
        return []
    return [entry for entry in listed if isinstance(entry, dict) and isinstance(entry.get("id"), str)]


def link_task(run_context: Any, value: Any, add: bool = True) -> None:
    """Record a Task this conversation created or acted on, in the state its tool result reports.

    A Task already listed keeps its place and takes the new state as shown, so what this conversation
    did itself is not reported back to it as a change. With add false, a Task not listed stays out.
    """
    state = getattr(run_context, "session_state", None)
    if not isinstance(state, dict) or not isinstance(value, dict) or not isinstance(value.get("id"), str):
        return
    entries = _entries(run_context)
    entry = next((item for item in entries if item.get("kind") == "task" and item["id"] == value["id"]), None)
    if entry is not None:
        entry["shown"] = _task_phase(value)
    elif add:
        entries.append(
            {
                "kind": "task",
                "id": value["id"],
                "added_at": int(time.time()),
                "shown": _task_phase(value),
                "changed_in": None,
            }
        )
    state[LINKED_WORK_KEY] = entries[-_KEPT:]


def _proposal(fc: Any) -> Any:
    """The Task a proposal tool returned, or None when the call recorded none."""
    result = getattr(fc, "result", None)
    if getattr(fc, "error", None) or not isinstance(result, str):
        return None
    try:
        value = json.loads(result)
    except ValueError:
        return None
    return value if isinstance(value, dict) and "status" in value else None


def link_proposal(run_context: Any = None, fc: Any = None) -> None:
    """Record the Task a proposal tool created. Set as the post-hook of Super Agent's proposal tools."""
    link_task(run_context, _proposal(fc))


async def alink_proposal(run_context: Any = None, fc: Any = None) -> None:
    link_task(run_context, _proposal(fc))


def _since(value: Dict[str, Any]) -> str:
    at = value.get("updated_at") or value.get("created_at")
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return ""
    moment = datetime.fromtimestamp(at, timezone.utc)
    today = datetime.now(timezone.utc).date() == moment.date()
    return " since " + moment.strftime("%H:%M UTC" if today else "%Y-%m-%d %H:%M UTC")


def _line(value: Dict[str, Any], changed: bool) -> str:
    # A title is text written by people and agents: one line, cut, and never able to close the quotes.
    title = " ".join(str(value.get("title") or "").split()).replace('"', "'")
    if len(title) > _TITLE_LENGTH:
        title = title[: _TITLE_LENGTH - 3] + "..."
    executor = f", {value['executor_id']}" if value.get("executor_id") else ""
    line = f'- Task "{title}" (id {value["id"]}{executor}): {_task_words(value)}{_since(value)}.'
    return line + (" Changed since your last turn." if changed else "")


class _LinkedWork:
    """The block for one run: the listed work with its live state, read as the caller."""

    def __init__(self, db: Any, user_isolation: bool = False):
        self.db = db
        self.user_isolation = user_isolation

    def _head(self, run_context: Any) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
        """The newest entries to read, the owner the reads are limited to, and whether to read at all."""
        from agno.tools.company import _scoped_user

        entries = _entries(run_context)
        if not entries:
            return [], None, False
        try:
            owner = _scoped_user(run_context, self.user_isolation)
        except PermissionError:
            return [], None, False
        newest = sorted(entries, key=lambda entry: entry.get("added_at") or 0, reverse=True)
        return [entry for entry in newest if entry.get("kind") == "task"][:_LISTED], owner, True

    def _block(self, run_context: Any, read: List[Tuple[Dict[str, Any], Any]]) -> List[str]:
        """Write the block and update the list: what was shown, what changed in this run, what leaves.

        A change is marked with the run it was first shown in. A continued run keeps its run id and
        its instructions, so the mark is given in one run however often that run pauses or retries.
        """
        run_id = getattr(run_context, "run_id", None)
        entries = _entries(run_context)
        lines: List[str] = []
        for entry, value in read:
            if value is None:
                # Deleted, or not readable by this caller.
                entries.remove(entry)
                continue
            phase = _task_phase(value)
            if entry.get("shown") != phase:
                entry["shown"] = phase
                entry["changed_in"] = run_id
            changed = run_id is not None and entry.get("changed_in") == run_id
            if value.get("status") in ("done", "cancelled") and not changed:
                # Its end was shown in an earlier run, or by the tool that ended it here.
                entries.remove(entry)
                continue
            lines.append(_line(value, changed))
        run_context.session_state[LINKED_WORK_KEY] = entries
        if not lines:
            return []
        more = len(entries) - len(lines)
        if more > 0:
            lines.append(f"{more} more exist: call list_company_tasks.")
        # The time it was read tells the model this is newer than what it said in earlier turns.
        read_at = datetime.now(timezone.utc).strftime("%H:%M UTC")
        return [f"{_HEADER}, read at {read_at}:\n" + "\n".join(lines)]

    def __call__(self, run_context: Any = None) -> List[str]:
        authority = _caller_authorization(run_context)
        # A synchronous run cannot read an asynchronous database, and the block is optional.
        if isinstance(self.db, AsyncBaseDb):
            return []
        try:
            if authority is not None:
                authority.require("tasks", "read")
            head, owner, found = self._head(run_context)
            if not found:
                return []
            return self._block(run_context, [(entry, self.db.get_task(entry["id"], user_id=owner)) for entry in head])
        except (PermissionError, NotImplementedError):
            return []
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return []

    async def __acall__(self, run_context: Any = None) -> List[str]:
        authority = _caller_authorization(run_context)
        try:
            if authority is not None:
                await authority.arequire("tasks", "read")
            head, owner, found = self._head(run_context)
            if not found:
                return []
            if isinstance(self.db, AsyncBaseDb):
                values = list(await asyncio.gather(*(self.db.get_task(entry["id"], user_id=owner) for entry in head)))
            else:
                values = await asyncio.to_thread(
                    lambda: [self.db.get_task(entry["id"], user_id=owner) for entry in head]
                )
            return self._block(run_context, list(zip(head, values)))
        except (PermissionError, NotImplementedError):
            return []
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return []
