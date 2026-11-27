"""The work a Super Agent conversation started, and the block that shows it to Super Agent.

Super Agent's tools add Tasks, and the runs it starts in the background, to the conversation's
session state. When the Team builds a fresh run's messages, it reads what is listed and marks changes
since the last state shown to the model.

The Team sends the block as a user message of its own right before the person's input, and does
not store it: the stored run holds the person's message as they sent it. It sits after the last
assistant message, so a provider that continues from its previous response is still sent it. The
model's provider has to accept two user messages in a row, or merge them in its own formatter.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from agno.db.base import AsyncBaseDb
from agno.db.schemas.tasks import TASK_STATUS_MEANING
from agno.run.authorization import _caller_authorization
from agno.utils.log import log_warning

# Each entry records the phase shown and which run received its change notice or tool receipt. A run
# entry also names its component ("component_type", "component_id", "name"), where it is stored
# ("session_id", "db_id"), whether the durable queue holds it ("durable"), the server process that
# started it ("process"), and "ended" once its end has been shown.
LINKED_WORK_KEY = "linked_work"

# This server process. A run that is not on the durable queue lives in the memory of the process
# that started it. Another process cannot tell whether that one still runs: a second worker and a
# restarted server look the same from here.
_PROCESS = uuid4().hex

# A stored run status in plain words. UNKNOWN and LOST are never stored: run_state derives them.
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
    "LOST": (
        "taken as lost: still stored as running an hour after it was started without the durable "
        "queue on another server process"
    ),
}
_RUN_ENDED = ("COMPLETED", "ERROR", "CANCELLED", "LOST")
_RUN_LIVE = ("PENDING", "RUNNING", "UNKNOWN")
# How long a run whose state is unknown is waited for. Past it the run is taken as lost, so one
# server restart cannot keep a line in a conversation, or close a component to it, for ever.
_UNKNOWN_SECONDS = 3600

# An entry this run could not read: no permission, or no database it can read from. It stays as it is.
_UNREAD: Any = object()

# Entries read and listed in one run, newest first.
_LISTED = 20
# Entries kept in session state. Past it the oldest is forgotten.
_KEPT = 100
_TITLE_LENGTH = 80

_HEADER = "Work started from this conversation"

# The block is a second user message right before the person's. It is sent only to a model whose
# provider is known to take two user messages in a row; for every other model nothing is sent, so
# the request is what it would be without linked work. Matched by the model's own class, never a
# base class: many adapters for other endpoints subclass the OpenAI classes, and some of those
# endpoints refuse the second message.
_DELIVERED_TO = frozenset(
    {
        # OpenAI accepts consecutive user messages.
        ("agno.models.openai.chat", "OpenAIChat"),
        ("agno.models.openai.responses", "OpenAIResponses"),
        # Azure OpenAI serves the same API and models. Expected to behave the same; not run live.
        ("agno.models.azure.openai_chat", "AzureOpenAI"),
        ("agno.models.azure.openai_responses", "AzureOpenAIResponses"),
        # The Claude formatter, shared by these four, merges consecutive user messages.
        ("agno.models.anthropic.claude", "Claude"),
        ("agno.models.aws.claude", "Claude"),
        ("agno.models.azure.claude", "Claude"),
        ("agno.models.vertexai.claude", "Claude"),
        # Gemini's generateContent formatter merges them. The Interactions API class is not listed.
        ("agno.models.google.gemini", "Gemini"),
        # xAI documents that messages may come in any role order.
        ("agno.models.xai.xai", "xAI"),
        ("agno.models.xai.responses", "xAIResponses"),
        # AwsBedrock (the Converse API) refuses two user messages in a row and its formatter does not
        # merge them, so it is not listed.
    }
)


# These classes send both user messages as they are, and are listed because the provider's own endpoint
# accepts them. The same class pointed at another endpoint may reach a server that refuses the second
# message, so for these the block is sent only on the class's default endpoint. The Claude and Gemini
# formatters merge the two messages before sending, so they are safe on any endpoint.
_SENT_AS_TWO_MESSAGES = frozenset(
    {
        ("agno.models.openai.chat", "OpenAIChat"),
        ("agno.models.openai.responses", "OpenAIResponses"),
        ("agno.models.azure.openai_chat", "AzureOpenAI"),
        ("agno.models.azure.openai_responses", "AzureOpenAIResponses"),
        ("agno.models.xai.xai", "xAI"),
        ("agno.models.xai.responses", "xAIResponses"),
    }
)


def _default_endpoint(model: Any) -> bool:
    kind = type(model)
    if getattr(model, "base_url", None) != getattr(kind, "base_url", None):
        return False
    # The OpenAI client reads this variable when the model names no base URL.
    return not (kind.__module__.startswith("agno.models.openai.") and os.getenv("OPENAI_BASE_URL"))


def _delivers(model: Any) -> bool:
    """Whether the block is sent to this model: its exact class is one of the listed providers, and a
    class that sends two user messages as they are is on its default endpoint."""
    kind = type(model)
    name = (kind.__module__, kind.__qualname__)
    if name not in _DELIVERED_TO:
        return False
    return _default_endpoint(model) if name in _SENT_AS_TWO_MESSAGES else True


def _result_status(value: Dict[str, Any]) -> Optional[str]:
    result = value.get("result") or {}
    return result.get("status") if result.get("run_id") == value.get("job_id") else None


def _task_phase(value: Dict[str, Any], paused: bool = False) -> str:
    run_status = "PAUSED" if paused else _result_status(value)
    return f"{value.get('status')}:{value.get('job_id') or ''}:{run_status or ''}"


def _task_words(value: Dict[str, Any]) -> str:
    """A Task's state in plain words."""
    status = value.get("status")
    words = TASK_STATUS_MEANING.get(str(status), str(status))
    if status == "in_progress":
        ended = _result_status(value)
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


def link_task(run_context: Any, value: Any, add: bool = True, *, paused: bool = False) -> None:
    """Record a Task this conversation created or acted on, in the state its tool result reports.

    A Task already listed takes the new state as shown, so what this conversation did itself is not
    reported back to it as a change, and moves to the newest place: only the newest entries are read,
    and the Task just acted on must be among them. With add false, the call refreshes a listed Task
    where it is and leaves an unlisted one out.
    """
    state = getattr(run_context, "session_state", None)
    if not isinstance(state, dict) or not isinstance(value, dict) or not isinstance(value.get("id"), str):
        return
    entries = _entries(run_context)
    entry = next((item for item in entries if item.get("kind") == "task" and item["id"] == value["id"]), None)
    if entry is None:
        if not add:
            return
        entry = {"kind": "task", "id": value["id"], "added_at": int(time.time())}
        entries.append(entry)
    elif add:
        entries.remove(entry)
        entries.append(entry)
    entry["shown"] = _task_phase(value, paused)
    entry["changed_in"] = None
    entry["receipt_in"] = getattr(run_context, "run_id", None)
    state[LINKED_WORK_KEY] = entries[-_KEPT:]


def run_entry(run_context: Any, run_id: Any) -> Optional[Dict[str, Any]]:
    """The background run this conversation started under that id, or None."""
    return next((item for item in _entries(run_context) if item.get("kind") == "run" and item["id"] == run_id), None)


def link_run(run_context: Any, run: Dict[str, Any], status: str = "PENDING") -> None:
    """Record a run this conversation started in the background, in the status its receipt reports.

    It takes the newest place, as a Task the conversation acts on does: only the newest entries are read.
    """
    state = getattr(run_context, "session_state", None)
    if not isinstance(state, dict) or not isinstance(run.get("id"), str) or run_entry(run_context, run["id"]):
        return
    entry = {
        **run,
        "kind": "run",
        "added_at": int(time.time()),
        "shown": _run_phase(status),
        "changed_in": None,
        "receipt_in": getattr(run_context, "run_id", None),
        "process": _PROCESS,
    }
    state[LINKED_WORK_KEY] = [*_entries(run_context), entry][-_KEPT:]


def read_run(run_context: Any, entry: Dict[str, Any], status: str) -> None:
    """Record that this run was told a listed run's state by a tool, so it is not reported as a change."""
    entry["shown"] = _run_phase(status)
    entry["changed_in"] = None
    entry["receipt_in"] = getattr(run_context, "run_id", None)


def run_state(entry: Dict[str, Any], row: Dict[str, Any]) -> str:
    """A stored run's status, or UNKNOWN or LOST for a live run this process cannot vouch for.

    Without the durable queue a run is a task in the memory of the server process that started it,
    and nothing ends its stored row when that process stops. Stored as queued or running and started
    by another process, it may be running on another worker or lost to a restart: UNKNOWN. An hour
    after its start it is taken as LOST, which ends it for this conversation.
    """
    status = getattr(row.get("status"), "value", row.get("status"))
    status = str(status or "").upper()
    if status in ("PENDING", "RUNNING") and not entry.get("durable") and entry.get("process") != _PROCESS:
        added = entry.get("added_at")
        waited = isinstance(added, (int, float)) and time.time() - added >= _UNKNOWN_SECONDS
        return "LOST" if waited else "UNKNOWN"
    return status


def run_holds_session(entry: Dict[str, Any], row: Dict[str, Any]) -> bool:
    """Whether a listed run is still going, so that no other run may enter its session."""
    return run_state(entry, row) in _RUN_LIVE


def stored_run(entry: Dict[str, Any], row: Any, run_context: Any) -> Any:
    """The stored row of a listed run, None when it is gone, or _UNREAD when it is not this caller's to read.

    Session state can be sent by a client, so an entry proves nothing. A run this conversation started
    is a top-level run of the named component, stored in the session derived from the conversation,
    the person and the component. A team keeps its members' runs in its own session, and several
    people can share one conversation: a row that is another run, or another person's, is left alone.
    """
    from agno.db.utils import get_run_type
    from agno.tools.studio_runner import StudioRunnerTools

    if row is _UNREAD:
        return _UNREAD
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
    """Read a run's row from the first of these databases that holds it, in a synchronous run.

    An asynchronous database cannot be read here. When the run is in none of the others it may be in
    that one, so it is reported as _UNREAD, not as gone.
    """
    skipped = False
    for store in stores or []:
        if isinstance(store, AsyncBaseDb):
            skipped = True
            continue
        row = store.get_run(run_id, deserialize=False)
        if row is not None:
            return row
    return _UNREAD if skipped else None


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


def _run_since(row: Dict[str, Any]) -> str:
    """When a run's stored row was last written, which is when it entered the state it is stored in."""
    at = row.get("updated_at") or row.get("created_at")
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return ""
    moment = datetime.fromtimestamp(at, timezone.utc)
    today = datetime.now(timezone.utc).date() == moment.date()
    return " since " + moment.strftime("%H:%M UTC" if today else "%Y-%m-%d %H:%M UTC")


def _run_line(entry: Dict[str, Any], row: Dict[str, Any], status: str, changed: bool) -> str:
    name = _one_line(entry.get("name") or entry.get("component_id"))
    words = RUN_STATUS_MEANING.get(status, status.lower())
    # The row of a run in an unknown state was last written by the process that may be gone.
    since = "" if status in ("UNKNOWN", "LOST") else _run_since(row)
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
    """When the Task entered the state its line describes, or '' when no record says.

    The time of the step into its stage: an edit, a move to another Project and an archive are not
    steps. A proposal is dated by its creation. A run's failure or cancellation is not dated.
    """
    status = value.get("status")
    if status == "in_progress" and _result_status(value) in ("ERROR", "CANCELLED"):
        return ""
    steps = [
        step.get("created_at")
        for step in value.get("transitions") or []
        if isinstance(step, dict) and not step.get("action") and step.get("target") == status
    ]
    at = steps[-1] if steps else (value.get("created_at") if status == "backlog" else None)
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return ""
    moment = datetime.fromtimestamp(at, timezone.utc)
    today = datetime.now(timezone.utc).date() == moment.date()
    return " since " + moment.strftime("%H:%M UTC" if today else "%Y-%m-%d %H:%M UTC")


def _one_line(text: Any) -> str:
    """Text written by people and agents, made safe for a line of the block: one line, cut, and never
    able to close the quotes around it."""
    cleaned = " ".join(str(text or "").split()).replace('"', "'")
    return cleaned if len(cleaned) <= _TITLE_LENGTH else cleaned[: _TITLE_LENGTH - 3] + "..."


def _line(value: Dict[str, Any], changed: bool, paused: bool) -> str:
    title = _one_line(value.get("title"))
    # A proposal can name any text as its executor.
    executor = f", {_one_line(value['executor_id'])}" if value.get("executor_id") else ""
    # The Task's start transition predates its pause.
    state = "waiting for a person to approve or answer" if paused else _task_words(value) + _since(value)
    line = f'- Task "{title}" (id {value["id"]}{executor}): {state}.'
    return line + (" Changed since your last turn." if changed else "")


def _active_jobs(values: List[Any]) -> List[str]:
    return [
        task["job_id"]
        for task in values
        if task and task.get("status") == "in_progress" and task.get("job_id") and not _result_status(task)
    ]


def _ticket_paused(ticket: Optional[Dict[str, Any]]) -> Optional[bool]:
    return None if ticket is None else ticket["status"] == "paused"


async def _get_ticket_pauses(store: Any, job_ids: List[str]) -> Dict[str, Optional[bool]]:
    async def paused(job_id: str) -> Optional[bool]:
        try:
            return _ticket_paused(await store.get_job(job_id, strict=True))
        except Exception as exc:
            log_warning(f"Linked work could not read ticket {job_id}: {exc}")
            return None

    return dict(zip(job_ids, await asyncio.gather(*(paused(job_id) for job_id in job_ids))))


async def _aread_pauses(queue: Any, job_ids: List[str]) -> Dict[str, Optional[bool]]:
    if not job_ids:
        return {}
    from agno.os.job_queue import _SyncStoreAdapter

    worker_loop = getattr(queue, "_loop", None)
    if (
        worker_loop is not None
        and worker_loop is not asyncio.get_running_loop()
        and worker_loop.is_running()
        and not isinstance(queue.store, _SyncStoreAdapter)
    ):
        # Async stores can have locks or connections bound to the worker's loop.
        future = asyncio.run_coroutine_threadsafe(_get_ticket_pauses(queue.store, job_ids), worker_loop)
        return await asyncio.wrap_future(future)
    return await _get_ticket_pauses(queue.store, job_ids)


def _read_pauses(queue: Any, job_ids: List[str]) -> Dict[str, Optional[bool]]:
    if not job_ids:
        return {}
    from agno.os.job_queue import _SyncStoreAdapter

    if isinstance(queue.store, _SyncStoreAdapter):
        pauses: Dict[str, Optional[bool]] = {}
        for job_id in job_ids:
            try:
                pauses[job_id] = _ticket_paused(queue.store._store.get_job(job_id, strict=True))
            except Exception as exc:
                log_warning(f"Linked work could not read ticket {job_id}: {exc}")
                pauses[job_id] = None
        return pauses
    try:
        caller_loop = asyncio.get_running_loop()
    except RuntimeError:
        caller_loop = None
    worker_loop = queue._loop
    if worker_loop is not None and worker_loop.is_running() and worker_loop is not caller_loop:
        return asyncio.run_coroutine_threadsafe(_get_ticket_pauses(queue.store, job_ids), worker_loop).result()
    if caller_loop is None:
        return asyncio.run(_get_ticket_pauses(queue.store, job_ids))
    # A synchronous call on the async store's own event loop cannot wait for that store.
    return dict.fromkeys(job_ids)


class LinkedWork:
    """Supply the current state of the conversation's Tasks and background runs under the caller's
    read permissions.

    db holds the Company Tasks, or is None without Company. run_db returns the databases that may
    store a component's runs, by the id they share.
    """

    def __init__(
        self,
        db: Any = None,
        user_isolation: bool = False,
        queue_worker: Optional[Callable[[], Any]] = None,
        delivers: Optional[Callable[[], bool]] = None,
        run_db: Optional[Callable[[Any], Any]] = None,
    ):
        self.db = db
        self.user_isolation = user_isolation
        self.queue_worker = queue_worker
        # Whether Super Agent's model is sent the block. When it is not, nothing is read, shown or
        # marked: the list is only kept by the tools, ready for a model that is sent it.
        self.delivers = delivers
        self.run_db = run_db

    @staticmethod
    def _head(run_context: Any) -> List[Dict[str, Any]]:
        """The newest entries to read. A run whose end was shown stays listed and is not read again."""
        # Entries are kept in the order they were added, so the newest are the last.
        newest = [
            entry
            for entry in reversed(_entries(run_context))
            if entry.get("kind") in ("task", "run") and not entry.get("ended")
        ]
        return newest[:_LISTED]

    def _tasks_readable(self, run_context: Any) -> bool:
        """Whether this caller can be shown Tasks at all.

        A Task is company work, read by its ID whoever created it, as the Task tools read it: a
        teammate's Task this conversation messaged or started stays listed. Where users are
        isolated, a caller with no identity is still shown none.
        """
        from agno.tools.company import _scoped_user

        if self.db is None:
            return False
        try:
            _scoped_user(run_context, self.user_isolation)
        except PermissionError:
            return False
        return True

    def _run_stores(self, entry: Dict[str, Any]) -> List[Any]:
        return list(self.run_db(entry.get("db_id")) or []) if self.run_db is not None else []

    @staticmethod
    def _replied(session: Any, run_id: Any, *, tool_receipt: bool = False) -> bool:
        """Whether the run a change was shown in gave the person a reply written with the change in view.

        A run that failed or was cancelled gave none. A run that paused for a confirmation is
        continued from its stored messages, which hold no block, so its reply may not have it either:
        the change is shown again. With no session to look in, the run is taken to have replied.
        """
        if session is None:
            return True
        for run in getattr(session, "runs", None) or []:
            if getattr(run, "run_id", None) == run_id:
                status = getattr(run, "status", None)
                completed = str(getattr(status, "value", status)).upper() == "COMPLETED"
                # The continuation includes its confirmed tool result in the messages used to reply.
                return completed and (tool_receipt or not getattr(run, "requirements", None))
        return False

    def _block(
        self, run_context: Any, read: List[Tuple[Dict[str, Any], Any]], session: Any, pauses: Dict[str, Optional[bool]]
    ) -> Optional[str]:
        """Write the block and update the list: what was shown, what changed in this run, what leaves.

        read pairs each entry with what was found: a Task, a run's stored row, None for one that is
        gone, or _UNREAD for one this run could not read, which stays as it is.

        A change is marked with the run it was first shown in. A retry builds the block again under
        the same run id and gets the same mark. A continued run uses the stored messages.
        If a run failed, was cancelled or paused for a confirmation, the person may still need to
        hear the change, so its marks pass to the next run.
        """
        run_id = getattr(run_context, "run_id", None)
        entries = _entries(run_context)
        tasks: List[str] = []
        runs: List[str] = []
        for entry, value in read:
            if value is _UNREAD:
                continue
            if value is None:
                # Deleted.
                entries.remove(entry)
                continue
            is_run = entry.get("kind") == "run"
            paused: Optional[bool] = False
            if is_run:
                status = run_state(entry, value)
                phase = _run_phase(status)
            else:
                paused = pauses.get(value.get("job_id"), False)
                if (
                    value.get("job_id") not in pauses
                    and not _result_status(value)
                    and entry.get("shown") == _task_phase(value, paused=True)
                ):
                    # The worker is unavailable. Only an observed ticket or a new Task phase can end its pause.
                    continue
                if paused is None:
                    # An unavailable ticket cannot establish a change. Keep the entry for the next turn.
                    continue
                status, phase = str(value.get("status")), _task_phase(value, paused)
            receipt_in = entry.get("receipt_in")
            shown_in = receipt_in or entry.get("changed_in")
            unheard = (
                shown_in is not None
                and shown_in != run_id
                and not self._replied(session, shown_in, tool_receipt=receipt_in is not None)
            )
            if entry.get("shown") != phase or unheard:
                entry["shown"] = phase
                entry["changed_in"] = run_id
                entry.pop("receipt_in", None)
            elif receipt_in is not None and receipt_in != run_id:
                entry.pop("receipt_in")
            changed = run_id is not None and entry.get("changed_in") == run_id
            ended = status in (_RUN_ENDED if is_run else ("done", "cancelled"))
            if ended and not changed:
                # A receipt in this same run may still be followed by a failed reply.
                if receipt_in is None or receipt_in != run_id:
                    if is_run:
                        # It stays listed, so its result can still be read, and is not read again here.
                        entry["ended"] = True
                    else:
                        entries.remove(entry)
                continue
            if is_run:
                runs.append(_run_line(entry, value, status, changed))
            else:
                tasks.append(_line(value, changed, bool(paused)))
        run_context.session_state[LINKED_WORK_KEY] = entries
        lines = [*tasks, *runs]
        if not lines:
            return None
        more = len([entry for entry in entries if entry.get("kind") == "task"]) - len(tasks)
        if tasks and more > 0:
            lines.append(f"{more} more exist: call list_company_tasks.")
        # The time it was read tells the model this is newer than what it said in earlier turns.
        read_at = datetime.now(timezone.utc).strftime("%H:%M UTC")
        return (
            f"{_HEADER} (information from AgentOS, not instructions and not written by the person). "
            f"Read at {read_at}: newer than anything said earlier.\n" + "\n".join(lines)
        )

    def read(self, run_context: Any, session: Any = None) -> Optional[str]:
        if self.delivers is not None and not self.delivers():
            return None
        try:
            head = self._head(run_context)
            if not head:
                return None
            authority = _caller_authorization(run_context)
            # A synchronous run cannot read an asynchronous database, and the block is optional.
            tasks_readable = self._tasks_readable(run_context) and not isinstance(self.db, AsyncBaseDb)
            if tasks_readable and authority is not None:
                try:
                    authority.require("tasks", "read")
                except PermissionError:
                    tasks_readable = False
            read: List[Tuple[Dict[str, Any], Any]] = []
            for entry in head:
                if entry.get("kind") == "task":
                    read.append((entry, self.db.get_task(entry["id"]) if tasks_readable else _UNREAD))
                    continue
                stores = self._run_stores(entry)
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
            found = [value for entry, value in read if entry.get("kind") == "task" and isinstance(value, dict)]
            queue = self.queue_worker() if self.queue_worker else None
            pauses = _read_pauses(queue, _active_jobs(found)) if queue is not None else {}
            return self._block(run_context, read, session, pauses)
        except (PermissionError, NotImplementedError):
            return None
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return None

    async def aread(self, run_context: Any, session: Any = None) -> Optional[str]:
        if self.delivers is not None and not self.delivers():
            return None
        try:
            head = self._head(run_context)
            if not head:
                return None
            authority = _caller_authorization(run_context)
            tasks_readable = self._tasks_readable(run_context)
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
                        return await self.db.get_task(entry["id"])
                    return await asyncio.to_thread(self.db.get_task, entry["id"])
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
            read = list(zip(head, values))
            found = [value for entry, value in read if entry.get("kind") == "task" and isinstance(value, dict)]
            queue = self.queue_worker() if self.queue_worker else None
            pauses = await _aread_pauses(queue, _active_jobs(found)) if queue is not None else {}
            return self._block(run_context, read, session, pauses)
        except (PermissionError, NotImplementedError):
            return None
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return None
