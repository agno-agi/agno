"""Finished-work reports: Super Agent tells a conversation that work it started has ended, without being asked.

When a Company Task run or a background run ends, the conversation that started it gets one run of
Super Agent. That run is a finished-work report. Nobody is present in it, so it reads and reports and changes
nothing.

Three things live here:

- FinishedWorkReports is told when work ends. It starts the finished-work report, only when the conversation is idle,
  as the person who asked and with the authority saved when the work was started.
- FinishedWorkBoundary is a pre-hook of Super Agent. For a finished-work report it offers the model the tools
  that read and no member, and puts finished_work_gate on that run's own copy of the Team. For every
  run it records that the conversation has a run going in this process, which is how a turn the
  person is waiting on is seen before it is stored.
- finished_work_gate is a tool hook. In a finished-work report it lets a tool that reads execute and answers
  for every other tool with one sentence. It is never on the Team that serves the person's turns:
  a Team's hooks replace each tool's own.
- A finished-work report saves the conversation's state as it is stored at that moment, with its own marks,
  so it does not undo what a turn of the person stored while it ran.
"""

import asyncio
import time
from collections import OrderedDict
from hashlib import sha256
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote
from weakref import ReferenceType, WeakValueDictionary, ref

from agno.db.base import AsyncBaseDb, SessionType
from agno.db.schemas.scheduler import FINISHED_WORK_REPORT_METADATA_KEY
from agno.guardrails.base import BaseGuardrail
from agno.os.manager.linked_work import LINKED_WORK_KEY, RUN_STATUS_MEANING
from agno.run.authorization import FINISHED_WORK_REPORT_REFUSAL, in_finished_work_report
from agno.utils.log import log_debug, log_warning

# The first words of every finished-work report's input. The input is stored with the user role, so these
# words are what tells a reader, and the model on later turns, that the person did not write it.
FINISHED_WORK_LABEL = "Finished work report from AgentOS"

# Finished-work reports a conversation is given in a row. Each is a model run nobody asked for, so after this
# many with no message from the person the next ended work starts none. The person's next message
# shows everything that changed. Three covers a Task and two runs started in one turn and ending apart.
FINISHED_WORK_REPORT_LIMIT = 3

# Seconds between the end of work and the finished-work report. Work that ends together is then reported by
# one finished-work report: the first notice starts it and the others find it going.
SETTLE_SECONDS = 3.0

# A stored run still queued or running after this long was lost by its server. It does not keep the
# conversation busy for ever.
_LOST_AFTER_SECONDS = 3600

# How long a notice waits for a finished-work report that is going, and how often it looks. A finished-work report
# takes seconds; one still stored as going after this long is not waited for.
_REPORT_WAIT_SECONDS = 120.0
_REPORT_POLL_SECONDS = 0.5

# The newest stored runs of the conversation that are read to decide.
_RUNS_READ = 30

# The tools a finished-work report may call: reads of what AgentOS stores. Every other tool is refused,
# whatever it is and whoever added it. A tool added to Super Agent later is refused until named here.
READ_TOOLS = frozenset(
    {
        # The work the report is about
        "check_background_run",
        "get_company_task_status",
        # The checkout a sandbox saved when that work's run completed: a stored record, not the sandbox
        "read_sandbox_changes",
        # Company records
        "list_company_goals",
        "get_company_goal",
        "list_company_projects",
        "list_company_tasks",
        "list_goal_sources",
        # Company files and notes
        "list_company_files",
        "read_company_file",
        "search_company_files",
        # The platform's own records
        "list_agents",
        "list_teams",
        "list_workflows",
        "get_run_activity",
        "list_schedules",
        # The source files OSManager.root exposes
        "read_file",
        "list_files",
        "search_content",
        # The conversation's own history and results
        "get_chat_history",
        "search_chat_history",
        "search_past_sessions",
        "read_past_session",
        "read_result",
        "search_result",
        "search_compacted_history",
        "search_knowledge_base",
    }
)

_IN_FLIGHT = ("PENDING", "RUNNING", "PAUSED")

# The run each conversation last started in this process, by session id, and whether it is a finished-work
# report. A run still registered with the cancellation manager is going. Held in this process only.
_latest_run: "OrderedDict[str, Tuple[str, bool]]" = OrderedDict()
_LATEST_KEPT = 4096


def _record_run(run_context: Any) -> None:
    session_id, run_id = getattr(run_context, "session_id", None), getattr(run_context, "run_id", None)
    if not isinstance(session_id, str) or not isinstance(run_id, str):
        return
    _latest_run[session_id] = (run_id, in_finished_work_report(run_context))
    _latest_run.move_to_end(session_id)
    while len(_latest_run) > _LATEST_KEPT:
        _latest_run.popitem(last=False)


async def _going_here(session_id: str) -> Optional[str]:
    """The run of this conversation executing in this process: "turn", "report" or None."""
    from agno.run.cancel import aget_active_runs

    latest = _latest_run.get(session_id)
    if latest is None or latest[0] not in await aget_active_runs():
        return None
    return "report" if latest[1] else "turn"


def finished_work_gate(function_name: str, function_call: Callable, arguments: Dict[str, Any], run_context: Any = None):
    """Refuse every tool that does not read, in a finished-work report. Every other run is untouched."""
    if in_finished_work_report(run_context) and function_name not in READ_TOOLS:
        return FINISHED_WORK_REPORT_REFUSAL
    return function_call(**arguments)


class FinishedWorkBoundary(BaseGuardrail):
    """Before each run of Super Agent: record the run, and offer a finished-work report only what reads.

    A pre-hook. It refuses nothing itself. A finished-work report is offered the tools named in READ_TOOLS and
    no member, so no tool that asks for a confirmation and no delegation can be called in it:
    nobody is there to confirm. finished_work_gate refuses whatever else could still execute, such as
    the memory tools a Team adds by itself.

    The gate is put on the Team object of the finished-work report's own run. AgentOS runs each request and
    each queued run on a copy of the served Team, and a finished-work report is only ever started that way.
    The served Team itself never gets it: a Team's tool hooks replace the hooks of every tool it
    holds, so on the served Team the gate would switch off the hooks an application put on its tools.
    """

    def __init__(self) -> None:
        # The Team AgentOS serves, set once it is built. Kept weakly, so a copy of this hook made
        # with a copy of the Team still names the served one.
        self.served: Optional[ReferenceType[Any]] = None

    @staticmethod
    def _reads(team: Any, async_mode: bool) -> List[Any]:
        """The read tools of the toolkits AgentOS itself gives Super Agent.

        READ_TOOLS names tools, and a name says nothing about a tool an application wrote. A tool
        passed in OSManager.tools is not offered in a finished-work report, whatever it is called.
        """
        from agno.os.manager.company_tasks import CompanyTaskTools
        from agno.tools.agentos import AgentOSTools
        from agno.tools.company import CompanyTools
        from agno.tools.company_files import CompanyFileTools
        from agno.tools.studio_runner import StudioRunnerTools
        from agno.tools.workspace import Workspace

        own = (StudioRunnerTools, AgentOSTools, CompanyTools, CompanyTaskTools, CompanyFileTools, Workspace)
        reads: List[Any] = []
        for tool in getattr(team, "tools", None) or []:
            if isinstance(tool, own):
                functions = tool.get_async_functions() if async_mode else tool.get_functions()
                for name, function in functions.items():
                    # Nobody is there to confirm, answer or run anything: a tool set up to wait for
                    # a person is left out, or the finished-work report would pause on it.
                    waits = (
                        function.requires_confirmation or function.requires_user_input or function.external_execution
                    )
                    if name in READ_TOOLS and not waits:
                        reads.append(function)
        return reads

    def _enter(self, run_context: Any, team: Any, async_mode: bool) -> None:
        _record_run(run_context)
        if in_finished_work_report(run_context):
            run_context.tools = self._reads(team, async_mode)
            run_context.members = []
            if team is not None and (self.served is None or self.served() is not team):
                team.tool_hooks = [finished_work_gate]
                _save_over_stored_state(team, run_context)

    def check(self, run_input: Any = None, run_context: Any = None, team: Any = None) -> None:
        self._enter(run_context, team, False)

    async def async_check(self, run_input: Any = None, run_context: Any = None, team: Any = None) -> None:
        self._enter(run_context, team, True)


def _keep_stored_state(session: Any, stored: Any, run_id: Any, marks: Optional[Dict[Any, Any]] = None) -> None:
    """Make the state a finished-work report is about to save the stored one, with this run's own marks.

    A run saves the whole session state it loaded when it started. The person cannot see that a finished-work
    report is going, so they may send a message while it runs, and that turn may store work it
    started. Saved as loaded, the finished-work report would undo that. Only what this run showed is carried
    over: an entry it did not mark keeps what the conversation stored, so a finish a turn of the
    person already reported is not put back to unreported. And only once the run has replied: a finished-work
    report that failed or was cancelled told the person nothing, so what it would have shown stays
    unreported. Whatever else the conversation stored meanwhile, such as a new name, is kept too.

    marks holds what this run marked, across its saves. A run that saves before it has ended has its
    state replaced by the stored one here, without its marks, so they are kept aside until it replies.
    """
    data = getattr(session, "session_data", None)
    stored_data = stored.get("session_data") if isinstance(stored, dict) else None
    if isinstance(data, dict) and isinstance(stored_data, dict):
        for key, value in stored_data.items():
            # The state is merged below, and the totals are this run's own to add to.
            if key not in ("session_state", "session_metrics"):
                data[key] = value
    state = stored_data.get("session_state") if isinstance(stored_data, dict) else None
    loaded = data.get("session_state") if isinstance(data, dict) else None
    if not isinstance(state, dict) or not isinstance(loaded, dict):
        return
    run = session.get_run(run_id) if run_id is not None and callable(getattr(session, "get_run", None)) else None
    replied = str(getattr(getattr(run, "status", None), "value", getattr(run, "status", None))) == "COMPLETED"
    marks = marks if marks is not None else {}
    for entry in loaded.get(LINKED_WORK_KEY) or []:
        # This run marked an entry when the block showed it as changed, or when one of its tools
        # read the entry's state, which linked work records as a receipt.
        if (
            isinstance(entry, dict)
            and run_id is not None
            and run_id in (entry.get("changed_in"), entry.get("receipt_in"))
        ):
            marks[(entry.get("kind"), entry.get("id"))] = dict(entry)
    mine = marks if replied else {}
    listed = []
    for entry in state.get(LINKED_WORK_KEY) or []:
        own = mine.get((entry.get("kind"), entry.get("id"))) if isinstance(entry, dict) else None
        if own is not None:
            entry = {key: value for key, value in entry.items() if key != "receipt_in"}
            entry.update({key: own[key] for key in ("shown", "changed_in", "receipt_in") if key in own})
        listed.append(entry)
    # Changed in place: the run and its session object hold this same dictionary.
    merged = {**state, LINKED_WORK_KEY: listed}
    loaded.clear()
    loaded.update(merged)


def _save_over_stored_state(team: Any, run_context: Any) -> None:
    """Have this run's own Team read the stored state again each time it saves the session.

    Done at the save, not before: a run saves when it ends, when it fails and when it is cancelled,
    and it can wait on other work between its last step and the save. What is stored between the
    read here and the write right after it can still be lost.

    A conversation that is no longer stored was deleted while the finished-work report ran. It is not saved:
    saving it would bring it back.
    """
    session_id, run_id = getattr(run_context, "session_id", None), getattr(run_context, "run_id", None)
    if not isinstance(session_id, str):
        return
    save, asave = team.save_session, team.asave_session
    marks: Dict[Any, Any] = {}

    def read() -> Any:
        return team.db.get_session(session_id, session_type=SessionType.TEAM, deserialize=False)

    def save_session(session: Any) -> Any:
        try:
            if not isinstance(team.db, AsyncBaseDb):
                stored = read()
                if stored is None:
                    return None
                _keep_stored_state(session, stored, run_id, marks)
        except Exception as exc:
            log_warning(f"Finished-work report could not read the conversation's stored state before saving: {exc}")
        return save(session=session)

    async def asave_session(session: Any) -> Any:
        try:
            if isinstance(team.db, AsyncBaseDb):
                stored = await team.db.get_session(session_id, session_type=SessionType.TEAM, deserialize=False)
            else:
                stored = await asyncio.to_thread(read)
            if stored is None:
                return None
            _keep_stored_state(session, stored, run_id, marks)
        except Exception as exc:
            log_warning(f"Finished-work report could not read the conversation's stored state before saving: {exc}")
        return await asave(session=session)

    team.save_session = save_session
    team.asave_session = asave_session


def _status(row: Dict[str, Any]) -> str:
    status = row.get("status")
    return str(getattr(status, "value", status) or "").upper()


def _is_report(row: Dict[str, Any]) -> bool:
    """Whether a stored run is a finished-work report.

    A run that has executed carries the mark. One still queued has no metadata stored yet, and one
    cancelled before it ran never gets any, so the label on its input counts too.
    """
    data = row.get("run_data") or {}
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and metadata.get(FINISHED_WORK_REPORT_METADATA_KEY):
        return True
    run_input = data.get("input")
    content = run_input.get("input_content") if isinstance(run_input, dict) else run_input
    return isinstance(content, str) and content.startswith(FINISHED_WORK_LABEL)


def _going(rows: List[Dict[str, Any]], now: float) -> List[Dict[str, Any]]:
    """The stored runs of the conversation that are queued, running or paused for a person.

    rows are newest first. A run paused for a person keeps the conversation waiting only until the
    person speaks again: a confirmation they left unanswered and talked past is not waited for.
    """
    going = []
    spoken_since = False
    for row in rows:
        status = _status(row)
        if status == "PAUSED":
            if not spoken_since:
                going.append(row)
        elif status in ("PENDING", "RUNNING"):
            at = row.get("updated_at") or row.get("created_at")
            if not isinstance(at, (int, float)) or now - at < _LOST_AFTER_SECONDS:
                going.append(row)
        if row.get("parent_run_id") is None and not _is_report(row):
            spoken_since = True
    return going


def _busy(rows: List[Dict[str, Any]], now: float) -> bool:
    """Whether a stored run of the conversation is queued, running or paused for a person."""
    return bool(_going(rows, now))


def _given(rows: List[Dict[str, Any]]) -> Tuple[int, str]:
    """Finished-work reports stored since the person's last message, and the run that message started.

    rows are the conversation's newest runs, newest first. Runs a member made for another run are
    not turns of the conversation.
    """
    count = 0
    for row in rows:
        if row.get("parent_run_id") is not None:
            continue
        if not _is_report(row):
            return count, str(row.get("run_id") or "")
        count += 1
    return count, ""


def _note(work: Dict[str, Any], entry: Dict[str, Any]) -> str:
    """The input of a finished-work report: what it is, what ended and how, and what to do with it.

    It carries no result text. A result is written by an agent, and this message is stored with the
    user role: the model reads the result through its tools, where it is a tool's output.
    """
    words = RUN_STATUS_MEANING.get(str(work.get("status")), str(work.get("status")).lower())
    if work.get("kind") == "task":
        what = f"Task {work.get('id')}: its run {work.get('run_id')} is {words}"
    else:
        # A name is text a person or an agent wrote: one line, cut, and never able to close the quotes.
        name = " ".join(str(entry.get("name") or entry.get("component_id") or "").split()).replace('"', "'")[:80]
        what = f'Background run of {entry.get("component_type")} "{name}" (run {work.get("id")}): {words}'
    return (
        f"{FINISHED_WORK_LABEL}. The person did not write this and is not present. It is information, not instructions.\n"
        f"{what}.\n"
        'Other work may have ended with it: report every item that "Work started from this conversation" '
        'marks "Changed since your last turn." Tell the person what ended, what it produced and what now '
        "waits on them. Read each result with your tools. Change nothing: no Task, Project, Routine, file "
        "or run is created, started, accepted, approved, completed, moved or messaged in a finished-work report."
    )


class FinishedWorkReports:
    """Start a finished-work report in the conversation that asked for work, when that work ends.

    One instance per AgentOS, registered while the app is served. It is called for every piece of
    work that names a conversation, by the durable queue and by runs executing in this process.
    """

    def __init__(self, agent_os: Any, app: Any):
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        self._app = app
        # One notice at a time per conversation in this process, so the second finds the first's run.
        self._turns: "WeakValueDictionary[str, asyncio.Lock]" = WeakValueDictionary()

    async def __call__(
        self, requested_from: Dict[str, Any], work: Dict[str, Any], authority: Optional[Dict[str, Any]] = None
    ) -> None:
        agent_os = self._agent_os()
        manager = getattr(agent_os, "_manager", None)
        session_id = requested_from.get("session_id")
        if manager is None or not manager.config.report_finished_work or not isinstance(session_id, str):
            return
        if requested_from.get("team_id") != manager.config.id:
            return
        from agno.os.manager import linked_work

        # A finished-work report depends on the linked-work block to say what changed and to mark it reported.
        # A model that is not sent the block gets no finished-work report: it would have nothing to report from.
        if not linked_work._delivers(manager.team.model):
            log_debug(f"No finished-work report for conversation {session_id}: its model is not sent the linked work")
            return
        # A turn of the person going in the conversation when the work ends means no finished-work report, also
        # when that turn ends a moment later: the person's next message shows what changed.
        if await self._run_going(manager.team, session_id) == "turn":
            log_debug(
                f"No finished-work report for conversation {session_id}: a turn was going in it when the work ended"
            )
            return
        # Work that ends together waits together, then one notice at a time decides: the first starts
        # the finished-work report and the others find it stored.
        await asyncio.sleep(SETTLE_SECONDS)
        turn = self._turns.get(session_id)
        if turn is None:
            turn = self._turns[session_id] = asyncio.Lock()
        async with turn:
            # A finished-work report that is going read the work before this piece ended, and has told the
            # person it is still running. Wait for it to end. What it did show is then stored, and
            # an end it did not show gets a finished-work report of its own.
            waited = 0.0
            while (going := await self._run_going(manager.team, session_id)) == "report":
                if waited >= _REPORT_WAIT_SECONDS:
                    return
                await asyncio.sleep(_REPORT_POLL_SECONDS)
                waited += _REPORT_POLL_SECONDS
            if going == "turn":
                return
            await self._start(agent_os, manager.team, requested_from, work, authority)

    async def _run_going(self, team: Any, session_id: str) -> Optional[str]:
        """What is going in the conversation: "turn", "report" when only finished-work reports are, or None.

        Read from this process, where a turn the person is waiting on is known before it is stored,
        and from the conversation's stored runs.
        """
        here = await _going_here(session_id)
        if here == "turn":
            return "turn"
        _, rows = await self._read(team.db, session_id)
        stored = _going(rows, time.time())
        if any(not _is_report(row) for row in stored):
            return "turn"
        return "report" if stored or here == "report" else None

    @staticmethod
    async def _read(db: Any, session_id: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
        """The conversation's stored session and its newest runs, newest first."""

        def read() -> Tuple[Any, Any]:
            session = db.get_session(session_id, session_type=SessionType.TEAM, deserialize=False)
            found = db.get_runs(
                session_id=session_id, limit=_RUNS_READ, sort_by="run_index", sort_order="desc", deserialize=False
            )
            return session, found

        if isinstance(db, AsyncBaseDb):
            session = await db.get_session(session_id, session_type=SessionType.TEAM, deserialize=False)
            found = await db.get_runs(
                session_id=session_id, limit=_RUNS_READ, sort_by="run_index", sort_order="desc", deserialize=False
            )
        else:
            session, found = await asyncio.to_thread(read)
        rows = [row for row in (found[0] if isinstance(found, tuple) else found) or [] if isinstance(row, dict)]
        # Newest first whatever the store returned: a turn's place in the conversation, then its time.
        rows.sort(key=lambda row: (row.get("run_index") or 0, row.get("created_at") or 0), reverse=True)
        return (session if isinstance(session, dict) else None), rows

    @staticmethod
    def _listed(session: Dict[str, Any], work: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The conversation's own record of this work, or None when it holds none.

        A run names the conversation that asked for it, and only the conversation's stored list says
        the conversation did. An end the conversation was already shown is not reported again: the
        entry holds the state last shown to the model, in a turn of the person or an earlier finished-work report.
        """
        state = (session.get("session_data") or {}).get("session_state")
        listed = state.get(LINKED_WORK_KEY) if isinstance(state, dict) else None
        for entry in listed if isinstance(listed, list) else []:
            if isinstance(entry, dict) and entry.get("kind") == work.get("kind") and entry.get("id") == work.get("id"):
                shown, status = str(entry.get("shown") or ""), str(work.get("status"))
                if work.get("kind") == "task":
                    # A Task's shown state ends with its latest run and how that run ended.
                    seen = shown.endswith(f":{work.get('run_id')}:{status}")
                else:
                    # A run paused again after it was continued waits on something new.
                    seen = shown == status and not (status == "PAUSED" and work.get("continued"))
                return None if entry.get("ended") or seen else entry
        return None

    def _authority(self, agent_os: Any, snapshot: Optional[Dict[str, Any]], user_id: Optional[str]) -> Tuple[Any, bool]:
        """The authority a finished-work report runs under, and whether it may run at all.

        It is the authority saved when the person started the work, and nothing else. Where the
        deployment checks permissions or isolates users, work with no saved authority of that person
        starts no finished-work report: a run without it would act as a service account.
        """
        from agno.os.auth import _authorization_enforced
        from agno.os.authz.run_context import restore_authorization
        from agno.os.manager.company_tasks import _user_isolation

        enforced = bool(getattr(agent_os, "authorization", None)) or _authorization_enforced(self._app)
        if _user_isolation(agent_os) and not user_id:
            return None, False
        if snapshot is None:
            return None, not enforced
        if any(snapshot.get(key) for key in ("service_account", "scheduled", "company_routine", "company_executor")):
            return None, False
        principal = (snapshot.get("context") or {}).get("principal_id")
        if principal is not None and user_id is not None and principal != user_id:
            return None, False
        return restore_authorization(self._app, snapshot), True

    async def _start(
        self,
        agent_os: Any,
        team: Any,
        requested_from: Dict[str, Any],
        work: Dict[str, Any],
        snapshot: Optional[Dict[str, Any]],
    ) -> None:
        from agno.os.utils import enter_run_route

        session_id = requested_from["session_id"]
        session, rows = await self._read(team.db, session_id)
        if session is None or session.get("team_id") != team.id:
            return
        entry = self._listed(session, work)
        if entry is None:
            return
        user_id = session.get("user_id")
        asked_by = requested_from.get("user_id")
        if asked_by is not None and asked_by != user_id:
            return
        # Only when the conversation is idle: a run stored as going, or one going in this process.
        if _busy(rows, time.time()) or await _going_here(session_id) is not None:
            log_debug(f"No finished-work report for conversation {session_id}: a run is going in it")
            return
        given, since = _given(rows)
        if given >= FINISHED_WORK_REPORT_LIMIT:
            log_debug(
                f"No finished-work report for conversation {session_id}: {given} given since the person last spoke"
            )
            return
        authority, allowed = self._authority(agent_os, snapshot, user_id)
        if not allowed:
            log_debug(f"No finished-work report for conversation {session_id}: no saved authority of the person")
            return
        response = await enter_run_route(
            self._app,
            authority,
            "POST",
            f"/teams/{quote(team.id, safe='')}/runs",
            owner=user_id,
            form={
                "message": _note(work, entry),
                "stream": "false",
                "background": "true",
                "session_id": session_id,
                **({"user_id": user_id} if user_id is not None else {}),
            },
            # The same place in the conversation gives the same key, so the durable queue accepts one
            # finished-work report for it however many servers were told that work ended.
            key="finished-work-report:" + sha256(f"{session_id}:{since}:{given}".encode()).hexdigest(),
            run_metadata={
                FINISHED_WORK_REPORT_METADATA_KEY: {
                    "kind": work.get("kind"),
                    "id": work.get("id"),
                    "status": work.get("status"),
                }
            },
        )
        if response.status_code != 202:
            log_warning(f"Finished-work report for conversation {session_id} was not started: {response.text[:200]}")
