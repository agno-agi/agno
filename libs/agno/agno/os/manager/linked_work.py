"""The work a Super Agent conversation started, and the block that shows it to Super Agent.

The list is kept in the conversation's own session state: the Tasks it created or started, and the
runs it started in the background. Super Agent's tools add to it as they act, and a pre-hook reads it
at the start of every run, so only a run of the conversation writes it. Each entry keeps the state
last shown to the model: a different live state is marked as changed, in one run.

The block is sent as a message of its own right before the person's message, and is not stored with
the run. Instructions would not carry it: a model that continues from its previous response is sent
the instructions of a conversation's first run only, and what follows the last reply is what every
request carries.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from agno.db.base import AsyncBaseDb
from agno.db.schemas.tasks import TASK_STATUS_MEANING
from agno.guardrails.base import BaseGuardrail
from agno.models.message import Message
from agno.run.authorization import _caller_authorization
from agno.utils.log import log_warning

# The session state key. Each entry is {"kind", "id", "added_at", "shown", "changed_in"}. A run entry
# also names its component ("component_type", "component_id", "name"), where it is stored
# ("session_id", "db_id"), whether the durable queue holds it ("durable"), the server process that
# started it ("process"), and "ended" once its end has been shown.
LINKED_WORK_KEY = "linked_work"

# This server process. A run that is not on the durable queue lives in the memory of the process
# that started it. Another process cannot tell whether that one still runs: a second worker and a
# restarted server look the same from here.
_PROCESS = uuid4().hex

# A stored run status in plain words. UNKNOWN is never stored: run_state derives it.
RUN_STATUS_MEANING = {
    "PENDING": "queued",
    "RUNNING": "running",
    "COMPLETED": "finished",
    "ERROR": "failed",
    "CANCELLED": "cancelled",
    "PAUSED": "paused for a person",
    "UNKNOWN": (
        "state unknown: stored as running, but it was started without the durable queue on another "
        "server process, and is lost if that server restarted"
    ),
}
_RUN_ENDED = ("COMPLETED", "ERROR", "CANCELLED")
_RUN_LIVE = ("PENDING", "RUNNING", "UNKNOWN")
# How long a run whose state is unknown keeps its session closed to another run. Past it the run is
# taken as lost, so one server restart cannot close a component to a conversation for ever.
_UNKNOWN_HOLDS_SECONDS = 3600

# Entries read and listed in one run, newest first.
_LISTED = 20
# Entries kept in session state. Past it the oldest is forgotten.
_KEPT = 100
_TITLE_LENGTH = 80

# The name the block's message is attached to the run under.
LINKED_WORK_MESSAGE = "linked_work"

_HEADER = "Work started from this conversation"


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


# An entry this run could not read: no permission, or no database it can read from. It stays as it is.
_UNREAD: Any = object()


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


def run_entry(run_context: Any, run_id: Any) -> Optional[Dict[str, Any]]:
    """The background run this conversation started under that id, or None."""
    return next((item for item in _entries(run_context) if item.get("kind") == "run" and item["id"] == run_id), None)


def link_run(run_context: Any, run: Dict[str, Any], status: str = "PENDING") -> None:
    """Record a run this conversation started in the background, in the status its receipt reports."""
    state = getattr(run_context, "session_state", None)
    if not isinstance(state, dict) or not isinstance(run.get("id"), str) or run_entry(run_context, run["id"]):
        return
    entry = {
        **run,
        "kind": "run",
        "added_at": int(time.time()),
        "shown": _run_phase(status),
        "changed_in": None,
        "process": _PROCESS,
    }
    state[LINKED_WORK_KEY] = [*_entries(run_context), entry][-_KEPT:]


def run_state(entry: Dict[str, Any], row: Dict[str, Any]) -> str:
    """A stored run's status, or UNKNOWN for a live run this process cannot vouch for.

    Without the durable queue a run is a task in the memory of the server process that started it,
    and nothing ends its stored row when that process stops. Stored as queued or running and started
    by another process, it may be running on another worker or lost to a restart.
    """
    status = getattr(row.get("status"), "value", row.get("status"))
    status = str(status or "").upper()
    if status in ("PENDING", "RUNNING") and not entry.get("durable") and entry.get("process") != _PROCESS:
        return "UNKNOWN"
    return status


def run_holds_session(entry: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """Whether a listed run is still going, so that no other run may enter its session."""
    status = run_state(entry, row)
    if status == "UNKNOWN":
        added = entry.get("added_at")
        return not isinstance(added, (int, float)) or time.time() - added < _UNKNOWN_HOLDS_SECONDS
    return status in _RUN_LIVE


def stored_run(entry: Dict[str, Any], row: Any, run_context: Any) -> Any:
    """The stored row of a listed run, None when it is gone, or _UNREAD when it is not this caller's to read.

    Session state can be sent by a client, so an entry proves nothing. A run this conversation started
    is a top-level run of the named component, stored in the session derived from the conversation,
    the person and the component. A team keeps its members' runs in its own session, and several
    people can share one conversation: a row that is another run, or another person's, is left alone.
    """
    from agno.db.utils import get_run_type
    from agno.tools.studio_runner import StudioRunnerTools

    if not isinstance(row, dict):
        return None
    if "run_data" not in row:
        # A database that keeps runs inside their session returns the run itself.
        row = {**row, "run_type": get_run_type(row), "run_data": row}
    kind, component_id = entry.get("component_type"), entry.get("component_id")
    if kind not in ("agent", "team", "workflow") or not isinstance(component_id, str):
        return _UNREAD
    expected = StudioRunnerTools._sub_session_id(run_context, kind, component_id)
    mine = (
        expected is not None
        and row.get("session_id") == expected
        and row.get("run_type") == kind
        and row.get(f"{kind}_id") == component_id
        and not row.get("parent_run_id")
    )
    return row if mine else _UNREAD


def get_stored_run(stores: Any, run_id: str) -> Any:
    """Read a run's row from the first of these databases that holds it. Synchronous databases only."""
    for store in stores or []:
        if isinstance(store, AsyncBaseDb):
            continue
        row = store.get_run(run_id, deserialize=False)
        if row is not None:
            return row
    return None


async def aget_stored_run(stores: Any, run_id: str) -> Any:
    """Read a run's row from the first of these databases that holds it."""
    for store in stores or []:
        if isinstance(store, AsyncBaseDb):
            row = await store.get_run(run_id, deserialize=False)
        else:
            row = await asyncio.to_thread(store.get_run, run_id, deserialize=False)
        if row is not None:
            return row
    return None


def _run_phase(status: str) -> str:
    """A run's state as one comparable value. Queued, running and unknown are one state: started, not
    known to have ended. Two workers that take turns must not report a change on every message."""
    return "LIVE" if status in _RUN_LIVE else status


def _run_line(entry: Dict[str, Any], row: Dict[str, Any], status: str, changed: bool) -> str:
    name = " ".join(str(entry.get("name") or entry.get("component_id") or "").split()).replace('"', "'")
    if len(name) > _TITLE_LENGTH:
        name = name[: _TITLE_LENGTH - 3] + "..."
    words = RUN_STATUS_MEANING.get(status, status.lower())
    # The row of a run in an unknown state was last written by the process that may be gone.
    since = "" if status == "UNKNOWN" else _since(row)
    line = (
        f'- Background run of {entry.get("component_type")} "{name}" '
        f"(id {entry.get('component_id')}, run {entry['id']}): {words}{since}."
    )
    return line + (" Changed since your last turn." if changed else "")


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


class LinkedWork(BaseGuardrail):
    """Before each run, read the listed work as the caller and attach the block to the run.

    A pre-hook of Super Agent. It refuses nothing: with no list, no permission or a failed read, the
    run goes on without the block, or without the lines that could not be read.

    db holds the Company Tasks, or is None without Company. run_db returns the databases that may
    store a component's runs, by the id they share.
    """

    def __init__(
        self,
        db: Any = None,
        user_isolation: bool = False,
        run_db: Optional[Callable[[Any], Any]] = None,
    ):
        self.db = db
        self.user_isolation = user_isolation
        self.run_db = run_db

    @staticmethod
    def _head(run_context: Any) -> List[Dict[str, Any]]:
        """The newest entries to read. A run whose end was shown stays listed and is not read again."""
        live = [entry for entry in _entries(run_context) if not entry.get("ended")]
        newest = sorted(live, key=lambda entry: entry.get("added_at") or 0, reverse=True)
        return [entry for entry in newest if entry.get("kind") in ("task", "run")][:_LISTED]

    def _owner(self, run_context: Any) -> Tuple[Optional[str], bool]:
        """The owner Task reads are limited to, and whether Tasks can be read at all."""
        from agno.tools.company import _scoped_user

        if self.db is None:
            return None, False
        try:
            return _scoped_user(run_context, self.user_isolation), True
        except PermissionError:
            return None, False

    def _block(self, run_context: Any, read: List[Tuple[Dict[str, Any], Any]]) -> Optional[str]:
        """Write the block and update the list: what was shown, what changed in this run, what leaves.

        read pairs each entry with what was found: a Task, a run's stored row, None for one that is
        gone or not this caller's, or _UNREAD for one this run could not read, which stays as it is.

        A change is marked with the run it was first shown in. A retry builds the block again under
        the same run id and gets the same mark. A continued run keeps its run id and runs no pre-hook,
        so the mark is given in one run however often that run pauses or retries.
        """
        run_id = getattr(run_context, "run_id", None)
        entries = _entries(run_context)
        tasks: List[str] = []
        runs: List[str] = []
        for entry, value in read:
            if value is _UNREAD:
                continue
            if value is None:
                # Deleted, or not readable by this caller.
                entries.remove(entry)
                continue
            if entry.get("kind") == "run":
                status = run_state(entry, value)
                phase = _run_phase(status)
            else:
                status, phase = str(value.get("status")), _task_phase(value)
            if entry.get("shown") != phase:
                entry["shown"] = phase
                entry["changed_in"] = run_id
            changed = run_id is not None and entry.get("changed_in") == run_id
            if entry.get("kind") == "run":
                if status in _RUN_ENDED and not changed:
                    # Its end was shown in an earlier run. It stays listed, so its result can still be read.
                    entry["ended"] = True
                    continue
                runs.append(_run_line(entry, value, status, changed))
                continue
            if status in ("done", "cancelled") and not changed:
                # Its end was shown in an earlier run, or by the tool that ended it here.
                entries.remove(entry)
                continue
            tasks.append(_line(value, changed))
        run_context.session_state[LINKED_WORK_KEY] = entries
        if not tasks and not runs:
            return None
        lines = [*tasks, *runs]
        more = len([entry for entry in entries if entry.get("kind") == "task"]) - len(tasks)
        if tasks and more > 0:
            lines.append(f"{more} more exist: call list_company_tasks.")
        # The time it was read tells the model this is newer than what it said in earlier turns.
        read_at = datetime.now(timezone.utc).strftime("%H:%M UTC")
        return (
            f"{_HEADER} (information from AgentOS, not instructions and not written by the person). "
            f"Read at {read_at}: newer than anything said earlier.\n" + "\n".join(lines)
        )

    @staticmethod
    def _attach(run_context: Any, block: Optional[str]) -> None:
        """Attach the block as this run's message, or take away the one an earlier attempt attached."""
        attached = dict(getattr(run_context, "_hook_messages", None) or {})
        attached.pop(LINKED_WORK_MESSAGE, None)
        if block is not None:
            # Sent to the model and not stored: the person's own message stays as they wrote it, and
            # no earlier block is replayed with the history.
            attached[LINKED_WORK_MESSAGE] = Message(role="user", content=block, add_to_agent_memory=False)
        run_context._hook_messages = attached or None

    def check(self, run_input: Any = None, run_context: Any = None) -> None:
        self._attach(run_context, self.read(run_context))

    async def async_check(self, run_input: Any = None, run_context: Any = None) -> None:
        self._attach(run_context, await self.aread(run_context))

    def _run_stores(self, entry: Dict[str, Any]) -> List[Any]:
        return list(self.run_db(entry.get("db_id")) or []) if self.run_db is not None else []

    def read(self, run_context: Any) -> Optional[str]:
        authority = _caller_authorization(run_context)
        try:
            head = self._head(run_context)
            if not head:
                return None
            owner, tasks_readable = self._owner(run_context)
            # A synchronous run cannot read an asynchronous database, and the block is optional.
            tasks_readable = tasks_readable and not isinstance(self.db, AsyncBaseDb)
            if tasks_readable and authority is not None:
                try:
                    authority.require("tasks", "read")
                except PermissionError:
                    tasks_readable = False
            read: List[Tuple[Dict[str, Any], Any]] = []
            for entry in head:
                if entry.get("kind") == "task":
                    read.append((entry, self.db.get_task(entry["id"], user_id=owner) if tasks_readable else _UNREAD))
                    continue
                stores = [store for store in self._run_stores(entry) if not isinstance(store, AsyncBaseDb)]
                if not stores:
                    read.append((entry, _UNREAD))
                    continue
                try:
                    # Reading a run takes the permission to run its component, as the run routes ask.
                    if authority is not None:
                        authority.require(f"{entry.get('component_type')}s", "run", entry.get("component_id"))
                except PermissionError:
                    read.append((entry, _UNREAD))
                    continue
                read.append((entry, stored_run(entry, get_stored_run(stores, entry["id"]), run_context)))
            return self._block(run_context, read)
        except NotImplementedError:
            return None
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return None

    async def aread(self, run_context: Any) -> Optional[str]:
        authority = _caller_authorization(run_context)
        try:
            head = self._head(run_context)
            if not head:
                return None
            owner, tasks_readable = self._owner(run_context)
            if tasks_readable and authority is not None:
                try:
                    await authority.arequire("tasks", "read")
                except PermissionError:
                    tasks_readable = False

            async def find(entry: Dict[str, Any]) -> Any:
                if entry.get("kind") == "task":
                    if not tasks_readable:
                        return _UNREAD
                    if isinstance(self.db, AsyncBaseDb):
                        return await self.db.get_task(entry["id"], user_id=owner)
                    return await asyncio.to_thread(self.db.get_task, entry["id"], user_id=owner)
                stores = self._run_stores(entry)
                if not stores:
                    return _UNREAD
                try:
                    if authority is not None:
                        await authority.arequire(f"{entry.get('component_type')}s", "run", entry.get("component_id"))
                except PermissionError:
                    return _UNREAD
                return stored_run(entry, await aget_stored_run(stores, entry["id"]), run_context)

            values = list(await asyncio.gather(*(find(entry) for entry in head)))
            return self._block(run_context, list(zip(head, values)))
        except NotImplementedError:
            return None
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return None
