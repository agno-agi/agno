"""A message of the person that a stopped server cut before Super Agent replied, and what the next turn is told.

Super Agent stores each turn as running when it starts. A server that is killed in the middle of one
leaves that row behind: the conversation holds what was asked, and nothing ended the run. The next
turn of the conversation finds the row, stores it as failed with INTERRUPTED_REPLY as its reply, and
tells Super Agent what was asked and which work the turn is recorded to have started. The turn is
never run again here: it may have started work.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from agno.db.base import AsyncBaseDb
from agno.db.schemas.scheduler import FINISHED_WORK_REPORT_METADATA_KEY
from agno.os.manager.linked_work import _entries
from agno.run._checkpoint_owner import checkpoint_owner, checkpoint_owner_exited
from agno.run.authorization import in_finished_work_report
from agno.run.base import RunStatus
from agno.utils.log import log_warning

# The stored reply of a cut turn. It is also how a later turn recognizes one already stored as failed.
INTERRUPTED_REPLY = (
    "This message was not answered: the server stopped or restarted while Super Agent was working on it."
)

# Cut turns named in one note, newest first. Older ones are stored as failed and not named.
_NAMED = 3
_INPUT_LENGTH = 1500


def _status(run: Any) -> str:
    status = getattr(run, "status", None)
    return str(getattr(status, "value", status) or "").upper()


def _input_text(run: Any) -> Optional[str]:
    run_input = getattr(run, "input", None)
    content = getattr(run_input, "input_content", run_input)
    return content if isinstance(content, str) else None


def _is_report(run: Any) -> bool:
    """Whether a stored run is a finished-work report: AgentOS wrote its input, not the person."""
    from agno.os.manager.finished_work import FINISHED_WORK_LABEL

    metadata = getattr(run, "metadata", None)
    if isinstance(metadata, dict) and metadata.get(FINISHED_WORK_REPORT_METADATA_KEY):
        return True
    return (_input_text(run) or "").startswith(FINISHED_WORK_LABEL)


def _cut_turns(session: Any, run_context: Any, team_id: Any, active: Set[str]) -> List[Tuple[Any, bool]]:
    """The person's turns at the end of the conversation that were cut, newest first, each with
    whether it is still stored as running.

    Only classify a foreground run when its recorded worker has exited. An absent registry
    entry alone can also mean the run belongs to another API worker.
    """
    current = getattr(run_context, "run_id", None)
    found: List[Tuple[Any, bool]] = []
    for run in reversed(getattr(session, "runs", None) or []):
        if getattr(run, "parent_run_id", None) is not None or getattr(run, "team_id", None) != team_id:
            continue
        if getattr(run, "run_id", None) == current or _is_report(run):
            continue
        status = _status(run)
        if status in ("PENDING", "RUNNING"):
            if (
                status == "RUNNING"
                and getattr(run, "queue_attempt", None) is None
                and run.run_id not in active
                and checkpoint_owner_exited(getattr(run, "checkpoint_owner", None))
            ):
                found.append((run, True))
            continue
        if status == "ERROR" and getattr(run, "content", None) == INTERRUPTED_REPLY:
            found.append((run, False))
            continue
        break
    return found


def _one_line(text: str) -> str:
    cleaned = " ".join(text.split()).replace('"', "'")
    return cleaned if len(cleaned) <= _INPUT_LENGTH else cleaned[: _INPUT_LENGTH - 3] + "..."


def _started(run_context: Any, run_id: Any) -> List[str]:
    """The Tasks and background runs a tool of that turn returned a result for: the turn added,
    started, acted on or only read each one. The state does not record which."""
    named = []
    for entry in _entries(run_context):
        if entry.get("receipt_in") != run_id:
            continue
        if entry.get("kind") == "task":
            named.append(f"Task {entry['id']}")
        elif entry.get("kind") == "run":
            name = _one_line(str(entry.get("name") or entry.get("component_id") or ""))[:80]
            named.append(f'background run {entry["id"]} of {entry.get("component_type")} "{name}"')
    return named


def _note(run_context: Any, runs: List[Any]) -> Optional[str]:
    lines = []
    for run in runs[:_NAMED]:
        text = _input_text(run)
        said = f'"{_one_line(text)}"' if text else "a message that was not text"
        at = getattr(run, "created_at", None)
        when = (
            datetime.fromtimestamp(at, timezone.utc).strftime(" at %H:%M UTC on %Y-%m-%d")
            if isinstance(at, (int, float)) and not isinstance(at, bool)
            else ""
        )
        started = _started(run_context, run.run_id)
        work = (
            "Recorded as added, started or read by it before it was cut: "
            + "; ".join(started)
            + '. Their state now is under "Work started from this conversation".'
            if started
            else "No Task or background run is recorded as added, started or read by it."
        )
        lines.append(f"- Sent{when}: {said}\n  {work}")
    if not lines:
        return None
    one = len(lines) == 1
    return (
        f"{'A message' if one else 'Messages'} from the person that got no reply (from AgentOS, not written by "
        "the person): the server stopped or restarted while you were working on "
        f"{'it' if one else 'them'}. The person saw an error and no answer. Nothing was run again.\n"
        + "\n".join(lines)
        + "\nAnything else that turn was doing when it was cut, such as an agent it was waiting for, stopped with "
        "the server and is not recorded. Start your reply by telling the person that this message was cut off by "
        "a restart, what it asked for and what is recorded as added, started or read by it. Do not ask them what "
        "it was. Do not do it again unless they ask you to here: offer to."
    )


class InterruptedTurns:
    """Find the person's turns a stopped server cut, store each as failed, and write the note for
    the next turn. team returns Super Agent's Team, whose database holds the conversation."""

    def __init__(self, team: Callable[[], Any]):
        self.team = team

    def _find(self, run_context: Any, session: Any, active: Set[str]) -> List[Tuple[Any, bool]]:
        # Nobody is present in a finished-work report: the person's next message is told.
        if session is None or in_finished_work_report(run_context):
            return []
        run_context._checkpoint_owner = checkpoint_owner()
        return _cut_turns(session, run_context, getattr(self.team(), "id", None), active)

    @staticmethod
    def _end(run: Any) -> None:
        run.checkpoint_owner = None
        run.status = RunStatus.error
        run.content = INTERRUPTED_REPLY

    @staticmethod
    def _update(session: Any, run: Any) -> Dict[str, Any]:
        return dict(
            run_id=run.run_id,
            session_id=session.session_id,
            user_id=session.user_id,
            expected={
                "status": RunStatus.running.value,
                "checkpoint_owner": run.checkpoint_owner,
                "queue_attempt": None,
            },
            fields={"status": RunStatus.error.value, "content": INTERRUPTED_REPLY, "checkpoint_owner": None},
        )

    def read(self, run_context: Any, session: Any = None) -> Optional[str]:
        try:
            from agno.run.cancel import get_active_runs

            found = self._find(run_context, session, set(get_active_runs()))
            db = self.team().db
            update = getattr(db, "update_run_if_matches", None)
            cut = []
            for run, running in found:
                if running:
                    if isinstance(db, AsyncBaseDb) or not callable(update) or not update(**self._update(session, run)):
                        continue
                    self._end(run)
                cut.append(run)
            return _note(run_context, cut)
        except Exception as exc:
            log_warning(f"Could not read the turns a restart cut in this conversation: {exc}")
            return None

    async def aread(self, run_context: Any, session: Any = None) -> Optional[str]:
        try:
            from agno.run.cancel import aget_active_runs

            found = self._find(run_context, session, set(await aget_active_runs()))
            db = self.team().db
            update = getattr(db, "update_run_if_matches", None)
            cut = []
            for run, running in found:
                if running:
                    if not callable(update):
                        continue
                    result = update(**self._update(session, run))
                    if not (await result if isinstance(db, AsyncBaseDb) else result):
                        continue
                    self._end(run)
                cut.append(run)
            return _note(run_context, cut)
        except Exception as exc:
            log_warning(f"Could not read the turns a restart cut in this conversation: {exc}")
            return None
