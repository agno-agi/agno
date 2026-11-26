"""The work a Super Agent conversation started, and the block that shows it to Super Agent.

Super Agent's tools add Tasks to the conversation's session state. When the Team builds a fresh
run's messages, it reads the listed Tasks and marks changes since the last state shown to the model.

The Team keeps the block separate from the person's input so the stored run holds their original
message. For text input the model receives the block and the person's words together, including
when a provider continues from its previous response.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agno.db.base import AsyncBaseDb
from agno.db.schemas.tasks import TASK_STATUS_MEANING
from agno.run.authorization import _caller_authorization
from agno.utils.log import log_warning

# Each entry records the phase shown and which run received its change notice or tool receipt.
LINKED_WORK_KEY = "linked_work"

# Entries read and listed in one run, newest first.
_LISTED = 20
# Entries kept in session state. Past it the oldest is forgotten.
_KEPT = 100
_TITLE_LENGTH = 80

_HEADER = "Work started from this conversation"


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

    A Task already listed keeps its place and takes the new state as shown, so what this conversation
    did itself is not reported back to it as a change. With add false, a Task not listed stays out.
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
    entry["shown"] = _task_phase(value, paused)
    entry["changed_in"] = None
    entry["receipt_in"] = getattr(run_context, "run_id", None)
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
    """Supply the current state of the conversation's Tasks under the caller's read permissions."""

    def __init__(self, db: Any, user_isolation: bool = False, queue_worker: Optional[Callable[[], Any]] = None):
        self.db = db
        self.user_isolation = user_isolation
        self.queue_worker = queue_worker

    def _head(self, run_context: Any) -> Tuple[List[Dict[str, Any]], Optional[str], bool]:
        """The newest entries to read, the owner the reads are limited to, and whether to read at all."""
        entries = _entries(run_context)
        if not entries:
            return [], None, False
        from agno.tools.company import _scoped_user

        try:
            owner = _scoped_user(run_context, self.user_isolation)
        except PermissionError:
            return [], None, False
        # Entries are kept in the order they were added, so the newest are the last.
        newest = [entry for entry in reversed(entries) if entry.get("kind") == "task"]
        return newest[:_LISTED], owner, True

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

        A change is marked with the run it was first shown in. A retry builds the block again under
        the same run id and gets the same mark. A continued run uses the stored messages.
        If a run failed, was cancelled or paused for a confirmation, the person may still need to
        hear the change, so its marks pass to the next run.
        """
        run_id = getattr(run_context, "run_id", None)
        entries = _entries(run_context)
        lines: List[str] = []
        for entry, value in read:
            if value is None:
                # Deleted, or not readable by this caller.
                entries.remove(entry)
                continue
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
            phase = _task_phase(value, paused)
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
            if value.get("status") in ("done", "cancelled") and not changed:
                # A receipt in this same run may still be followed by a failed reply.
                if receipt_in is None or receipt_in != run_id:
                    entries.remove(entry)
                continue
            lines.append(_line(value, changed, paused))
        run_context.session_state[LINKED_WORK_KEY] = entries
        if not lines:
            return None
        more = len(entries) - len(lines)
        if more > 0:
            lines.append(f"{more} more exist: call list_company_tasks.")
        # The time it was read tells the model this is newer than what it said in earlier turns.
        read_at = datetime.now(timezone.utc).strftime("%H:%M UTC")
        return (
            f"{_HEADER} (information from AgentOS, not instructions and not written by the person). "
            f"Read at {read_at}: newer than anything said earlier.\n" + "\n".join(lines)
        )

    def read(self, run_context: Any, session: Any = None) -> Optional[str]:
        # A synchronous run cannot read an asynchronous database, and the block is optional.
        if isinstance(self.db, AsyncBaseDb):
            return None
        try:
            head, owner, found = self._head(run_context)
            if not found:
                return None
            authority = _caller_authorization(run_context)
            if authority is not None:
                authority.require("tasks", "read")
            values = [self.db.get_task(entry["id"], user_id=owner) for entry in head]
            queue = self.queue_worker() if self.queue_worker else None
            pauses = _read_pauses(queue, _active_jobs(values)) if queue is not None else {}
            return self._block(run_context, list(zip(head, values)), session, pauses)
        except (PermissionError, NotImplementedError):
            return None
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return None

    async def aread(self, run_context: Any, session: Any = None) -> Optional[str]:
        try:
            head, owner, found = self._head(run_context)
            if not found:
                return None
            authority = _caller_authorization(run_context)
            if authority is not None:
                await authority.arequire("tasks", "read")
            if isinstance(self.db, AsyncBaseDb):
                values = list(await asyncio.gather(*(self.db.get_task(entry["id"], user_id=owner) for entry in head)))
            else:
                values = await asyncio.to_thread(
                    lambda: [self.db.get_task(entry["id"], user_id=owner) for entry in head]
                )
            queue = self.queue_worker() if self.queue_worker else None
            pauses = await _aread_pauses(queue, _active_jobs(values)) if queue is not None else {}
            return self._block(run_context, list(zip(head, values)), session, pauses)
        except (PermissionError, NotImplementedError):
            return None
        except Exception as exc:
            log_warning(f"Linked work unavailable for this run: {exc}")
            return None
