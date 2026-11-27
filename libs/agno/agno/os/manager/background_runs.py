"""Super Agent's run tools: the ordinary ones, plus starting a run in the background and reading it.

A background run does not go through the component directly. The tool makes every check a run in
the turn makes, then enters the component's own run route in process with background on, under the
person's authority. The route puts the run on the durable queue when it is on, and starts it as a
task in the server's memory when it is not. The tool returns a receipt and the turn goes on.

The run is recorded in the conversation's linked work, and stores which conversation asked for it.
While it is going, no other run of that component may start from the conversation, in the turn or in
the background: nothing else stops two runs from writing one session at once.

An agent that works in a sandbox changes a checkout the AgentOS host does not hold. read_sandbox_changes
reads what such an agent changed, from the checkout its sandbox saved when its last run completed.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote
from weakref import ReferenceType, ref

from agno.db.base import AsyncBaseDb
from agno.db.schemas.scheduler import REQUESTED_FROM_METADATA_KEY
from agno.os.manager import linked_work
from agno.os.manager.linked_work import (
    _RUN_LIVE,
    _UNREAD,
    RUN_STATUS_MEANING,
    _entries,
    aget_stored_run,
    get_stored_run,
    link_run,
    read_run,
    run_entry,
    run_holds_session,
    run_state,
    stored_run,
)
from agno.registry._reserved import RESERVED_MANAGER_IDS
from agno.run.authorization import requires_permission
from agno.tools.studio_runner import StudioRunnerError, StudioRunnerTools
from agno.utils.log import logger

# The most of a run's result the check tool returns. A longer result is cut, and says so.
RESULT_LENGTH = 6000

_KINDS = ("agent", "team", "workflow")
_ASYNC_ONLY = "Starting a background run needs an asynchronous run. Run the component in the turn instead."

# The most of a sandbox checkout's diff the read tool returns in one call, and the most changed files it
# lists. More is cut, the result says so, and offset reads on from the cut. Together they keep a result
# under the 16,000 characters past which Super Agent is shown only the start of a tool result.
DIFF_LENGTH = 8000
_FILES_LISTED = 50
# The newest runs of a session that are looked through for a saved checkout.
_NEWEST_RUNS: Dict[str, Any] = {"limit": 30, "sort_by": "run_index", "sort_order": "desc", "deserialize": False}
# The longest one git command may take on a restored checkout.
_GIT_SECONDS = 60
_CHANGE = {"A": "added", "M": "modified", "D": "deleted", "T": "type changed"}


class _Unreadable(Exception):
    """Why a sandbox's changes cannot be read: the one sentence the tool returns."""


def _run_data(row: Dict[str, Any]) -> Dict[str, Any]:
    data = row.get("run_data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    return data if isinstance(data, dict) else {}


def _saved_checkout(
    rows: List[Any], agent_id: Any
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The newest run of a session that saved its checkout, the agent's runs after it, and those before it.

    A sandbox saves its files only when a run completes, so a run that failed, was cancelled or is still
    going has no checkout of its own: the files are as the last completed run left them.
    """
    runs = [row for row in rows if isinstance(row, dict) and row.get("agent_id") == agent_id]
    # Newest first whatever the store returned: a run's place in its session, then its time.
    runs.sort(key=lambda row: (row.get("run_index") or 0, row.get("created_at") or 0), reverse=True)
    for index, row in enumerate(runs):
        sandbox = (_run_data(row).get("metadata") or {}).get("sandbox") or {}
        if str(row.get("status") or "").upper() == "COMPLETED" and isinstance(sandbox.get("checkpoint"), dict):
            return row, runs[:index], runs[index + 1 :]
    return None, runs, []


def _checkout_changes(archive: Path, commit: str, path: Optional[str] = None, offset: int = 0) -> Dict[str, Any]:
    """What a saved sandbox checkout changed since a commit: every changed file, and the diff from offset on.

    The archive is restored into a temporary directory on this host and compared there with git, which
    must be installed. Everything the agent did since the commit counts, committed or not; new files its
    .gitignore excludes do not. git runs on a new, empty repository directory that borrows only the
    objects of the saved checkout, so no configuration, hook, filter or diff driver written inside the
    sandbox is read or run. Nothing is written outside the temporary directory, which is removed.
    """
    if shutil.which("git") is None:
        raise _Unreadable("Reading a sandbox checkout needs git on the AgentOS host, and it is not installed.")
    from agno.sandbox.checkpoint import CheckpointArchive

    with tempfile.TemporaryDirectory(prefix="agno-sandbox-changes-") as scratch:
        root = Path(scratch)
        CheckpointArchive().restore(archive, root / "restored")
        checkout = root / "restored" / "workspace" / "repository"
        objects = checkout / ".git" / "objects"
        if not objects.is_dir():
            raise _Unreadable("The saved sandbox holds no repository checkout.")
        # The saved object store must not lead git to objects anywhere else on this host.
        (objects / "info" / "alternates").unlink(missing_ok=True)
        gitdir = root / "git"
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": scratch,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }

        def run(command: List[str], output: Optional[Path] = None) -> str:
            try:
                if output is None:
                    done = subprocess.run(command, cwd=scratch, env=env, capture_output=True, timeout=_GIT_SECONDS)
                else:
                    with output.open("wb") as sink:
                        done = subprocess.run(
                            command, cwd=scratch, env=env, stdout=sink, stderr=subprocess.PIPE, timeout=_GIT_SECONDS
                        )
            except subprocess.TimeoutExpired:
                raise _Unreadable(f"Comparing the saved checkout took over {_GIT_SECONDS} seconds and was stopped.")
            if done.returncode:
                detail = done.stderr.decode("utf-8", errors="replace").strip()[:300]
                raise _Unreadable(f"git could not compare the saved checkout: {detail or 'no reason given'}")
            return (done.stdout or b"").decode("utf-8", errors="replace") if output is None else ""

        def git(*args: str, output: Optional[Path] = None) -> str:
            prefix = ["git", "--git-dir", str(gitdir), "--work-tree", str(checkout), "--literal-pathspecs"]
            return run([*prefix, *args], output)

        run(["git", "init", "--quiet", "--bare", "--template=", str(gitdir)])
        (gitdir / "objects" / "info").mkdir(parents=True, exist_ok=True)
        (gitdir / "objects" / "info" / "alternates").write_text(str(objects) + "\n")
        # Attachments are staged under the checkout's .agno/, which the sandbox keeps out of git too.
        (gitdir / "info").mkdir(exist_ok=True)
        (gitdir / "info" / "exclude").write_text("/.agno/\n")
        try:
            git("cat-file", "-e", commit + "^{commit}")
        except _Unreadable:
            raise _Unreadable(
                f"The saved checkout does not hold commit {commit[:12]}, the one its sandbox started from, "
                "so there is nothing to compare it with."
            )
        # The new repository's index starts as the commit, so what git tracks stays tracked: a tracked file
        # that .gitignore also matches, or a submodule the sandbox never fetched, is not taken for a deleted
        # one. It then takes the checkout as it is; the saved checkout is not written.
        git("read-tree", commit)
        git("add", "--all")
        compare = ["diff", "--cached", "--no-renames", "--no-ext-diff", "--no-textconv", "--no-color"]
        files: Dict[str, Dict[str, Any]] = {}
        for line in git(*compare, "--raw", "--numstat", commit).splitlines():
            if line.startswith(":"):
                meta, _, name = line.partition("\t")
                files[name] = {"path": name, "change": _CHANGE.get(meta.split()[-1][:1], "changed")}
            elif line.count("\t") >= 2:
                added, removed, name = line.split("\t", 2)
                entry = files.setdefault(name, {"path": name, "change": "changed"})
                if added.isdigit() and removed.isdigit():
                    entry.update(lines_added=int(added), lines_removed=int(removed))
                else:
                    entry["binary"] = True
        patch = root / "patch"
        git(*compare, commit, *(["--", path] if path else []), output=patch)
        with patch.open(encoding="utf-8", errors="replace") as stream:
            # Where the returned part starts: offset, or the end of a diff that is shorter than it.
            start = 0
            while start < offset and (chunk := stream.read(min(offset - start, 1 << 20))):
                start += len(chunk)
            diff = stream.read(DIFF_LENGTH)
            length = start + len(diff) + sum(len(chunk) for chunk in iter(lambda: stream.read(1 << 20), ""))
        return {"files": list(files.values()), "diff": diff, "diff_offset": start, "diff_length": length}


def _requested_from(run_context: Any, team: Any) -> Dict[str, str]:
    """The conversation a background run reports to: the chat's session, run, team and user ids."""
    conversation = {
        "session_id": getattr(run_context, "session_id", None),
        "run_id": getattr(run_context, "run_id", None),
        "team_id": getattr(team, "id", None),
        "user_id": getattr(run_context, "user_id", None),
    }
    return {key: item for key, item in conversation.items() if isinstance(item, str)}


class BackgroundRunTools(StudioRunnerTools):
    """StudioRunnerTools for Super Agent, with start_background_run and check_background_run.

    With sandbox_changes on, read_sandbox_changes is added: only an AgentOS with a sandbox has a
    checkout to read.
    """

    def __init__(self, agent_os: Any, sandbox_changes: bool = False, **kwargs: Any):
        super().__init__(**kwargs)
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        # Sessions a run tool of this toolkit is entering or running in, in the turn or as a start. Two
        # calls of one model step run at once, and neither is in the linked work yet.
        self._entering: Set[str] = set()
        self._entering_lock = Lock()
        self.register(self.start_background_run)
        self.register(self.astart_background_run, name="start_background_run")
        self.register(self.check_background_run)
        self.register(self.acheck_background_run, name="check_background_run")
        if sandbox_changes:
            self.register(self.read_sandbox_changes)
            self.register(self.aread_sandbox_changes, name="read_sandbox_changes")

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def _app(self) -> Any:
        return getattr(self._agent_os(), "_manager_app", None)

    def _run_stores(self, db_id: Any) -> List[Any]:
        """The databases that may store a component's runs, or the OS database when none is served.

        AgentOS groups its databases by id, and two handles on one database with different run tables
        share an id, so a run is looked for in each.
        """
        agent_os = self._agent_os()
        stores = (getattr(agent_os, "dbs", None) or {}).get(db_id) if db_id else None
        fallback = getattr(agent_os, "db", None)
        return list(stores) if stores else ([fallback] if fallback is not None else [])

    def _person(self, run_context: Any, app: Any) -> Tuple[Any, Optional[str]]:
        """The chatting person's authority and identity. Raises PermissionError for every other caller."""
        from agno.os.auth import _authorization_enforced
        from agno.os.manager.company_tasks import _user_isolation
        from agno.tools.company import _authority, _identity, _require_human_creation

        _require_human_creation(run_context, "start background runs")
        authority, user_id = _authority(run_context), _identity(run_context)
        agent_os = self._agent_os()
        enforced = bool(getattr(agent_os, "authorization", None)) or _authorization_enforced(app)
        if (authority is None and enforced) or (_user_isolation(agent_os) and not user_id):
            raise PermissionError("A signed-in person is required to start background runs")
        return authority, user_id

    def _resolve(self, component_type: str, component_id: str, actor: Optional[str]) -> Any:
        find = {"agent": self._agent_for_run, "team": self._team_for_run, "workflow": self._workflow_for_run}
        return find[component_type](component_id, actor=actor)

    @staticmethod
    def _going(run_context: Any, session_id: str) -> List[Dict[str, Any]]:
        """This conversation's background runs in that session that have not been seen to end."""
        return [
            entry
            for entry in _entries(run_context)
            if entry.get("kind") == "run" and not entry.get("ended") and entry.get("session_id") == session_id
        ]

    def _held_by(self, run_context: Any, entry: Dict[str, Any], row: Any) -> Optional[str]:
        """The refusal for a session a listed run still holds, or None.

        Only runs this conversation started in the background are counted, read from the store: a run
        in the turn ends with its turn, and a run the server lost is stored as running for ever.
        """
        row = stored_run(entry, row, run_context)
        if row is None or row is _UNREAD or not run_holds_session(entry, row):
            return None
        name = entry.get("name") or entry.get("component_id")
        if run_state(entry, row) == "UNKNOWN":
            return (
                f"Not started: the state of {name}'s background run {entry['id']} is unknown. It was started "
                "without the durable queue on another server process. Its session takes one run at a time, "
                "and is free again an hour after that run started."
            )
        return (
            f"Not started: {name} still has background run {entry['id']} going in this conversation, "
            "and its session takes one run at a time. Wait for it to end."
        )

    def _reserve(self, session_id: str, name: str) -> Optional[str]:
        """Take the session for one run tool call, or say that another call of this turn has it."""
        with self._entering_lock:
            if session_id in self._entering:
                return f"Not started: another run of {name} is being started in this conversation right now."
            self._entering.add(session_id)
        return None

    def _release(self, session_id: Optional[str]) -> None:
        if session_id is not None:
            with self._entering_lock:
                self._entering.discard(session_id)

    def _session_of(self, kind: str, identifier: str, run_context: Any) -> Tuple[Optional[str], str]:
        """The session a run of that component enters from this conversation, and the component's name.

        The component is found the way the run tools find it, so an id, a display name or a slug names
        the same session. One that does not resolve gives no session: the run tool reports why.
        """
        find = {"agent": self._find_agent, "team": self._find_team, "workflow": self._find_workflow}[kind]
        try:
            component = find(identifier, for_dispatch=True, actor=getattr(run_context, "user_id", None))
        except Exception:
            return None, identifier
        if component is None:
            return None, identifier
        component_id = getattr(component, "id", None) or identifier
        return self._sub_session_id(run_context, kind, component_id), getattr(component, "name", None) or component_id

    def _entered(self, session_id: str, name: str, refusal: Optional[str], error: Optional[BaseException]) -> Any:
        """Keep the reservation only for a run that goes ahead. A read of the store that failed or was
        cancelled must give the session back, or the component stays closed to the conversation."""
        if refusal is None and error is None:
            return session_id, None
        self._release(session_id)
        if error is not None and not isinstance(error, Exception):
            raise error
        if error is not None:
            refusal = (
                f"Not started: could not check whether {name} has a run going: {str(error) or type(error).__name__}"
            )
        return None, json.dumps({"error": refusal})

    def _enter(self, kind: str, identifier: str, run_context: Any) -> Tuple[Optional[str], Optional[str]]:
        """Reserve the session of a run in the turn. Returns the session to release, or a refusal."""
        session_id, name = self._session_of(kind, identifier, run_context)
        if session_id is None:
            return None, None
        refusal = self._reserve(session_id, name)
        if refusal is not None:
            return None, json.dumps({"error": refusal})
        error: Optional[BaseException] = None
        try:
            for entry in self._going(run_context, session_id):
                row = get_stored_run(self._run_stores(entry.get("db_id")), entry["id"])
                refusal = self._held_by(run_context, entry, row)
                if refusal is not None:
                    break
        except BaseException as exc:
            error = exc
        return self._entered(session_id, name, refusal, error)

    async def _aenter(self, kind: str, identifier: str, run_context: Any) -> Tuple[Optional[str], Optional[str]]:
        session_id, name = await asyncio.to_thread(self._session_of, kind, identifier, run_context)
        if session_id is None:
            return None, None
        refusal = self._reserve(session_id, name)
        if refusal is not None:
            return None, json.dumps({"error": refusal})
        error: Optional[BaseException] = None
        try:
            refusal = await self._aheld(run_context, session_id)
        except BaseException as exc:
            error = exc
        return self._entered(session_id, name, refusal, error)

    async def _aheld(self, run_context: Any, session_id: str) -> Optional[str]:
        for entry in self._going(run_context, session_id):
            row = await aget_stored_run(self._run_stores(entry.get("db_id")), entry["id"])
            refusal = self._held_by(run_context, entry, row)
            if refusal is not None:
                return refusal
        return None

    # The run tools of the turn. Each holds its component's session while it runs, and is refused
    # while a background run of that component is going: both enter the same session.

    @requires_permission()
    def run_agent(self, agent_id: str, message: str, _agno_run_context=None, _agno_agent=None, _agno_team=None) -> str:
        session_id, refusal = self._enter("agent", agent_id, _agno_run_context)
        if refusal is not None:
            return refusal
        try:
            return super().run_agent(
                agent_id, message, _agno_run_context=_agno_run_context, _agno_agent=_agno_agent, _agno_team=_agno_team
            )
        finally:
            self._release(session_id)

    @requires_permission()
    def run_team(self, team_id: str, message: str, _agno_run_context=None, _agno_agent=None, _agno_team=None) -> str:
        session_id, refusal = self._enter("team", team_id, _agno_run_context)
        if refusal is not None:
            return refusal
        try:
            return super().run_team(
                team_id, message, _agno_run_context=_agno_run_context, _agno_agent=_agno_agent, _agno_team=_agno_team
            )
        finally:
            self._release(session_id)

    @requires_permission()
    def run_workflow(
        self, workflow_id: str, message: str, _agno_run_context=None, _agno_agent=None, _agno_team=None
    ) -> str:
        session_id, refusal = self._enter("workflow", workflow_id, _agno_run_context)
        if refusal is not None:
            return refusal
        try:
            return super().run_workflow(
                workflow_id,
                message,
                _agno_run_context=_agno_run_context,
                _agno_agent=_agno_agent,
                _agno_team=_agno_team,
            )
        finally:
            self._release(session_id)

    @requires_permission()
    async def arun_agent(
        self, agent_id: str, message: str, _agno_run_context=None, _agno_agent=None, _agno_team=None
    ) -> str:
        session_id, refusal = await self._aenter("agent", agent_id, _agno_run_context)
        if refusal is not None:
            return refusal
        try:
            return await super().arun_agent(
                agent_id, message, _agno_run_context=_agno_run_context, _agno_agent=_agno_agent, _agno_team=_agno_team
            )
        finally:
            self._release(session_id)

    @requires_permission()
    async def arun_team(
        self, team_id: str, message: str, _agno_run_context=None, _agno_agent=None, _agno_team=None
    ) -> str:
        session_id, refusal = await self._aenter("team", team_id, _agno_run_context)
        if refusal is not None:
            return refusal
        try:
            return await super().arun_team(
                team_id, message, _agno_run_context=_agno_run_context, _agno_agent=_agno_agent, _agno_team=_agno_team
            )
        finally:
            self._release(session_id)

    @requires_permission()
    async def arun_workflow(
        self, workflow_id: str, message: str, _agno_run_context=None, _agno_agent=None, _agno_team=None
    ) -> str:
        session_id, refusal = await self._aenter("workflow", workflow_id, _agno_run_context)
        if refusal is not None:
            return refusal
        try:
            return await super().arun_workflow(
                workflow_id,
                message,
                _agno_run_context=_agno_run_context,
                _agno_agent=_agno_agent,
                _agno_team=_agno_team,
            )
        finally:
            self._release(session_id)

    async def _aget_run(self, entry: Dict[str, Any]) -> Any:
        return await aget_stored_run(self._run_stores(entry.get("db_id")), entry["id"])

    @requires_permission()
    def start_background_run(
        self,
        component_type: str,
        component_id: str,
        message: str,
        _agno_run_context: Optional[Any] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Start an agent, team or workflow run in the background and return at once with a receipt.

        Args:
            component_type (str): agent, team or workflow.
            component_id (str): Id of the component to run (a display name or its slug also resolves).
            message (str): The message to send.
        """
        return json.dumps({"error": _ASYNC_ONLY})

    @requires_permission()
    async def astart_background_run(
        self,
        component_type: str,
        component_id: str,
        message: str,
        _agno_run_context: Optional[Any] = None,
        _agno_agent: Optional[Any] = None,
        _agno_team: Optional[Any] = None,
    ) -> str:
        """Start an agent, team or workflow run in the background and return at once with a receipt.

        Use it when the person says not to wait, or the work is long. The run goes on in its own
        session while this conversation continues: the turn does not end, so start each run the
        person asked for, then answer. The result is a receipt, not the work: the run is not
        finished. check_background_run reads its state, and its result once it has one. A later run of the same component from this conversation continues
        the same session, so a follow-up is another run of it. A component with a run still going
        here is refused until that run ends, in the turn and in the background.

        Args:
            component_type (str): agent, team or workflow.
            component_id (str): Id of the component to run (a display name or its slug also resolves).
            message (str): The message to send.

        Returns:
            str: JSON object with 'started', 'component_type', 'component_id', 'name', 'run_id',
                'session_id', 'status' and a 'note', or an 'error' saying why it did not start.
        """
        kind = str(component_type or "").strip().lower()
        if kind not in _KINDS or not getattr(self, f"enable_{kind}s"):
            return json.dumps({"error": f"component_type must be one of: {', '.join(_KINDS)}"})
        app = self._app()
        if app is None:
            return json.dumps({"error": "Background runs need a running AgentOS. Run the component in the turn."})
        run_context = _agno_run_context
        if not getattr(run_context, "session_id", None):
            return json.dumps({"error": "A background run belongs to a conversation, and this run has none."})
        actor = getattr(run_context, "user_id", None)
        try:
            authority, _ = self._person(run_context, app)
            # The same order as a run in the turn: depth, resolution with its refusals, permission, cycle.
            inherited, depth = self._inherited_dispatch_state(run_context)
            self._require_dispatch_budget(depth, kind, component_id)
            if inherited or depth:
                # A run another component started has no conversation with the person to report to.
                return json.dumps({"error": "Not started: only a conversation with the person starts background runs."})
            component = await asyncio.to_thread(self._resolve, kind, component_id, actor)
            if component is None:
                missing = await asyncio.to_thread(self._not_found_message, kind, component_id, actor=actor)
                return json.dumps({"error": missing})
            resolved_id = getattr(component, "id", None) or component_id
            if resolved_id in RESERVED_MANAGER_IDS or resolved_id == getattr(_agno_team, "id", None):
                return json.dumps({"error": "Super Agent does not run itself in the background."})
            if authority is not None:
                await authority.arequire(f"{kind}s", "run", resolved_id)
            running = self._dedup([*inherited, *self._caller_tokens(_agno_agent, _agno_team)])
            target = self._require_no_cycle(running, inherited, kind, resolved_id)
            user_id = self._caller_user_id(run_context, component)
        except (StudioRunnerError, PermissionError) as exc:
            return json.dumps({"error": f"Not started: {exc}"})
        except Exception as exc:
            logger.exception(f"Failed to resolve {kind}")
            return json.dumps({"error": f"Failed to resolve {kind} '{component_id}': {str(exc) or type(exc).__name__}"})

        session_id = self._sub_session_id(run_context, kind, resolved_id)
        assert session_id is not None  # the caller has a session
        name = getattr(component, "name", None) or resolved_id
        taken = self._reserve(session_id, name)
        if taken is not None:
            return json.dumps({"error": taken})
        try:
            held = await self._aheld(run_context, session_id)
            if held is not None:
                return json.dumps({"error": held})
            metadata = self._outgoing_metadata(run_context, running, depth, target)
            metadata[REQUESTED_FROM_METADATA_KEY] = _requested_from(run_context, _agno_team)
            run = {"component_type": kind, "component_id": resolved_id, "name": name, "session_id": session_id}
            shown = linked_work._delivers(getattr(_agno_team, "model", None))
            return await self._start(app, authority, run_context, component, run, message, user_id, metadata, shown)
        except Exception as exc:
            logger.exception(f"Failed to start {kind} in the background")
            return json.dumps({"error": f"Not started: {str(exc) or type(exc).__name__}"})
        finally:
            self._release(session_id)

    async def _start(
        self,
        app: Any,
        authority: Any,
        run_context: Any,
        component: Any,
        run: Dict[str, Any],
        message: str,
        user_id: Optional[str],
        metadata: Dict[str, Any],
        shown: bool,
    ) -> str:
        """Enter the component's run route with background on, and record the run it accepted.

        shown says whether Super Agent's model is sent the linked-work block: the receipt must not
        promise a state it will not be shown.
        """
        from agno.os.utils import enter_run_route

        response = await enter_run_route(
            app,
            # The authority Super Agent's tools run under, as a run in the turn carries it: the person's
            # permissions are checked on the component's own tools too.
            authority,
            "POST",
            f"/{run['component_type']}s/{quote(run['component_id'], safe='')}/runs",
            owner=user_id,
            form={
                "message": message,
                "stream": "false",
                "background": "true",
                "session_id": run["session_id"],
                **({"user_id": user_id} if user_id is not None else {}),
            },
            run_metadata=metadata,
        )
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 202 or not isinstance(body, dict) or not isinstance(body.get("run_id"), str):
            detail = body.get("detail") if isinstance(body, dict) else None
            return json.dumps({"error": f"Not started: {detail or 'the run was refused'}"})
        status = str(body.get("status") or "PENDING")
        run = {
            **run,
            "id": body["run_id"],
            "session_id": body.get("session_id") or run["session_id"],
            "db_id": getattr(getattr(component, "db", None), "id", None),
            "durable": False,
        }
        # The run is accepted: it is listed before anything else is awaited, so a turn cancelled or a
        # queue that cannot be asked leaves no run going that the conversation does not know.
        link_run(run_context, run, status)
        worker = getattr(app.state, "queue_worker", None)
        try:
            durable = worker is not None and await worker.store.get_job(run["id"]) is not None
        except Exception:
            # Unconfirmed, it is not called durable.
            durable = False
        entry = run_entry(run_context, run["id"])
        if durable and entry is not None:
            entry["durable"] = True
        note = "Started, not finished. check_background_run reads its state and, once it has ended, its result."
        if shown:
            note = "Started, not finished. Its state is shown to you each turn; check_background_run reads its result."
        if not durable:
            note += " It runs in the server's memory: if the server restarts before it ends, the run is lost."
        return json.dumps(
            {
                "started": True,
                "component_type": run["component_type"],
                "component_id": run["component_id"],
                "name": run["name"],
                "run_id": run["id"],
                "session_id": run["session_id"],
                "status": status,
                "note": note,
            }
        )

    # ------------------------------------------------------------------
    # Check
    # ------------------------------------------------------------------

    def _checked(self, run_context: Any, run_id: str, row: Any) -> str:
        """What check_background_run returns for a listed run and its stored row."""
        from agno.db.utils import deserialize_run

        entry = run_entry(run_context, run_id)
        assert entry is not None
        row = stored_run(entry, row, run_context)
        if row is None or row is _UNREAD:
            return json.dumps({"error": f"Run {run_id} is not a run you started in this conversation."})
        status = run_state(entry, row)
        kind, component_id = entry["component_type"], entry["component_id"]
        if status not in _RUN_LIVE:
            # Its end is read here, so the next turn does not report it as a change.
            read_run(run_context, entry, status)
        if status in _RUN_LIVE or status == "LOST":
            # Nothing a run wrote before it ended is its result.
            payload: Dict[str, Any] = {
                f"{kind}_id": component_id,
                "run_id": run_id,
                "session_id": row.get("session_id"),
                "status": status,
            }
        else:
            run_output = deserialize_run(row.get("run_type"), row["run_data"])
            payload = json.loads(self._run_payload(f"{kind}_id", component_id, run_output))
            payload["status"] = status
        payload["meaning"] = RUN_STATUS_MEANING.get(status, status.lower())
        content = payload.get("content")
        if isinstance(content, str) and len(content) > RESULT_LENGTH:
            payload["content"] = content[:RESULT_LENGTH]
            payload["note"] = f"The result is cut to its first {RESULT_LENGTH} of {len(content)} characters."
        return json.dumps(payload, default=str)

    def _check_refusal(self, run_context: Any, run_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        entry = run_entry(run_context, run_id)
        if entry is None:
            return None, json.dumps(
                {"error": f"Run {run_id} was not started from this conversation. Only runs started here can be read."}
            )
        return entry, None

    @requires_permission()
    def check_background_run(self, run_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a run this conversation started in the background: its status, and its result when it has one.

        A PAUSED run waits for a person: the result carries what it asks for. It is resumed through
        the platform, never by running the component again.

        Args:
            run_id (str): The run id from the start_background_run receipt.

        Returns:
            str: JSON object with the component id, 'run_id', 'session_id', 'status', 'meaning' and,
                once the run has ended, 'content'; 'requirements' when it is paused.
        """
        from agno.tools.company import _authority

        entry, refusal = self._check_refusal(_agno_run_context, run_id)
        if entry is None:
            return str(refusal)
        try:
            authority = _authority(_agno_run_context)
            if authority is not None:
                authority.require(f"{entry.get('component_type')}s", "run", entry.get("component_id"))
            stores = self._run_stores(entry.get("db_id"))
            if not stores or all(isinstance(store, AsyncBaseDb) for store in stores):
                return json.dumps({"error": "Reading this run needs an asynchronous run."})
            row = get_stored_run(stores, run_id)
            if row is _UNREAD:
                return json.dumps({"error": "Reading this run needs an asynchronous run."})
            return self._checked(_agno_run_context, run_id, row)
        except PermissionError as exc:
            return json.dumps({"error": f"Cannot read the run: {exc}"})
        except Exception as exc:
            logger.exception("Failed to read a background run")
            return json.dumps({"error": f"Cannot read the run: {str(exc) or type(exc).__name__}"})

    @requires_permission()
    async def acheck_background_run(self, run_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a run this conversation started in the background: its status, and its result when it has one.

        A PAUSED run waits for a person: the result carries what it asks for. It is resumed through
        the platform, never by running the component again.

        Args:
            run_id (str): The run id from the start_background_run receipt.

        Returns:
            str: JSON object with the component id, 'run_id', 'session_id', 'status', 'meaning' and,
                once the run has ended, 'content'; 'requirements' when it is paused.
        """
        from agno.tools.company import _authority

        entry, refusal = self._check_refusal(_agno_run_context, run_id)
        if entry is None:
            return str(refusal)
        try:
            authority = _authority(_agno_run_context)
            if authority is not None:
                await authority.arequire(f"{entry.get('component_type')}s", "run", entry.get("component_id"))
            return self._checked(_agno_run_context, run_id, await self._aget_run(entry))
        except PermissionError as exc:
            return json.dumps({"error": f"Cannot read the run: {exc}"})
        except Exception as exc:
            logger.exception("Failed to read a background run")
            return json.dumps({"error": f"Cannot read the run: {str(exc) or type(exc).__name__}"})

    # ------------------------------------------------------------------
    # Sandbox changes
    # ------------------------------------------------------------------

    def _conversation_agent(self, agent_id: str, run_context: Any) -> Tuple[Any, str, str]:
        """The agent named, its id, and the session this conversation's runs of it enter."""
        actor = getattr(run_context, "user_id", None)
        try:
            agent = self._find_agent(agent_id, for_dispatch=True, actor=actor)
        except StudioRunnerError as exc:
            raise _Unreadable(str(exc))
        if agent is None:
            raise _Unreadable(self._not_found_message("agent", agent_id, actor=actor))
        resolved_id = getattr(agent, "id", None) or agent_id
        session_id = self._sub_session_id(run_context, "agent", resolved_id)
        if session_id is None:
            raise _Unreadable("Only a conversation reads what an agent it ran changed, and this run has none.")
        return agent, resolved_id, session_id

    async def _atask_agent(self, task_id: str, run_context: Any) -> Tuple[Any, Any, str]:
        """A Task's executor, the database its runs are stored in, and the Task's session.

        The Task is read under the same permission as its status.
        """
        from fastapi import HTTPException

        from agno.os.routers.company.runs import _TaskStarter
        from agno.tools.company import _authority

        agent_os = self._agent_os()
        if agent_os is None or getattr(agent_os, "_company_db", None) is None:
            raise _Unreadable("Company is not running here, so there is no Task to read.")
        authority = _authority(run_context)
        if authority is not None:
            await authority.arequire("tasks", "read")
        starter = _TaskStarter(agent_os)
        try:
            value = await starter.task(task_id)
            if value.get("executor_type") != "agent" or not value.get("executor_id"):
                raise _Unreadable("This Task's executor is not an agent that works in a sandbox: no checkout to read.")
            agent = starter.executor(value)
            self._sandboxed(agent)
            if not value.get("job_id") or not value.get("session_id"):
                raise _Unreadable("This Task has not run yet, so its sandbox has saved no checkout.")
            return agent, starter.run_database(value), value["session_id"]
        except HTTPException as exc:
            raise _Unreadable(f"Cannot read the Task: {exc.detail}")
        except ValueError as exc:
            raise _Unreadable(f"Cannot read the Task's run: {exc}")

    @staticmethod
    def _sandboxed(agent: Any) -> str:
        """The agent's name. Raises when it has no sandbox checkout of a repository."""
        from agno.company.sandbox import _is_sandboxed

        name = getattr(agent, "name", None) or getattr(agent, "id", None) or "The agent"
        if not _is_sandboxed(agent):
            raise _Unreadable(f"{name} does not work in a sandbox, so it has no checkout of its own to read.")
        if getattr(agent, "repository", None) is None:
            raise _Unreadable(f"{name}'s sandbox has no repository, so there is no checkout to compare.")
        return name

    @staticmethod
    def _saved_run(
        rows: Any, agent: Any, user_id: Optional[str], where: str
    ) -> Tuple[Dict[str, Any], str, List[Any], List[Any]]:
        """The run whose saved checkout is read, the commit it is compared with, and the runs after and before it."""
        name = getattr(agent, "name", None) or agent.get_id()
        found = rows[0] if isinstance(rows, tuple) else rows
        # A conversation reads its own person's runs only.
        mine = [
            row for row in found or [] if user_id is None or (isinstance(row, dict) and row.get("user_id") == user_id)
        ]
        row, later, earlier = _saved_checkout(mine, agent.get_id())
        if row is None and later:
            status = str(later[0].get("status") or "unknown").lower()
            raise _Unreadable(
                f"{name} has no completed run {where}: its latest run is {status}. A sandbox saves its "
                "checkout only when a run completes, so there are no changes to read yet."
            )
        if row is None:
            raise _Unreadable(f"{name} has not run {where}, so there are no changes to read.")
        repository = ((_run_data(row).get("metadata") or {}).get("sandbox") or {}).get("repository") or {}
        commit = repository.get("commit")
        # The commit is passed to git, and the run recorded it from inside the sandbox.
        if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
            raise _Unreadable(
                f"Run {row.get('run_id')} recorded no commit its sandbox started from, so there is nothing "
                "to compare its checkout with."
            )
        return row, commit, later, earlier

    @staticmethod
    def _changes(
        agent: Any,
        row: Dict[str, Any],
        later: List[Any],
        earlier: List[Any],
        changes: Dict[str, Any],
        path: Optional[str],
        task_id: Any,
    ) -> str:
        """What read_sandbox_changes returns. Everything left out is said in the note, before the diff."""
        repository = (_run_data(row)["metadata"]["sandbox"]).get("repository") or {}
        run_id = row.get("run_id")
        payload: Dict[str, Any] = {
            **({"task_id": task_id} if task_id else {}),
            "agent_id": agent.get_id(),
            "run_id": run_id,
            "session_id": row.get("session_id"),
            "repository": repository.get("url"),
            "branch": repository.get("branch"),
            "base_commit": repository.get("commit"),
            "read_from": (
                "The checkout the sandbox saved when this run completed, compared with base_commit, the commit "
                "the sandbox started from. Committed and uncommitted changes both count."
            ),
        }
        files, diff, length = changes["files"], changes["diff"], changes["diff_length"]
        # The part of the whole diff this result holds.
        start = changes["diff_offset"]
        end = start + len(diff)
        notes: List[str] = []
        if later:
            status = str(later[0].get("status") or "unknown").lower()
            notes.append(
                f"A later run ({later[0].get('run_id')}) is {status} and saved no checkout: these are the files "
                f"as run {run_id} left them."
            )
        if not files:
            notes.append("No file differs from base_commit: this agent changed nothing in its checkout.")
        elif earlier:
            # The sandbox keeps one checkout for the whole session, and base_commit never moves.
            notes.append(
                f"Run {run_id} is not the first run of this session: the diff is everything changed since "
                f"base_commit, earlier runs' changes included, not only what run {run_id} changed."
            )
        if files and path and not length:
            notes.append(f"{path} is not among the changed files.")
        if len(files) > _FILES_LISTED:
            notes.append(
                f"changed_files shows the first {_FILES_LISTED} of {len(files)} changed files: "
                f"{len(files) - _FILES_LISTED} more are not listed."
            )
        if length > end:
            shown = f"characters {start} to {end}" if start else f"the first {end}"
            if path:
                again = f"Call again with the same path and offset={end} to read on from there."
            else:
                again = f"Call again with offset={end} to read on from there, or with path to read one file's diff."
            # Said only when it is so: a long list of files is cut too, and says that itself.
            listed = " changed_files lists every changed file." if len(files) <= _FILES_LISTED else ""
            notes.append(
                f"The diff is cut. It shows {shown} of {length} characters: {length - end} more are not shown, "
                f"so this is not the whole change. {again}{listed}"
            )
            diff += (
                f"\n[The diff is cut here: {length - end} more characters are not shown. Read on with offset={end}.]"
            )
        elif start and diff:
            notes.append(f"This is the rest of the diff, from character {start} of {length}.")
        elif start and length:
            notes.append(f"Nothing is left to read at offset {start}: the diff is {length} characters long.")
        payload["changed_files"] = files[:_FILES_LISTED]
        if notes:
            payload["note"] = " ".join(notes)
        payload["diff"] = diff
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _changes_error(exc: BaseException, run_id: Any = None) -> str:
        from agno.sandbox.checkpoint import CheckpointObjectNotFound

        if isinstance(exc, _Unreadable):
            return json.dumps({"error": str(exc)})
        if isinstance(exc, CheckpointObjectNotFound):
            return json.dumps(
                {
                    "error": f"The checkout saved by run {run_id} is no longer in checkpoint storage, so its "
                    "changes cannot be read. A sandbox keeps the checkouts of its last few runs only."
                }
            )
        if not isinstance(exc, PermissionError):
            logger.exception("Failed to read sandbox changes")
        return json.dumps({"error": f"Cannot read the changes: {str(exc) or type(exc).__name__}"})

    @requires_permission()
    def read_sandbox_changes(
        self,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        path: Optional[str] = None,
        offset: Optional[int] = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Read what an agent that works in a sandbox changed in its checkout: the changed files and the diff.

        Args:
            task_id (Optional[str]): A Company Task a sandboxed agent executed.
            agent_id (Optional[str]): A sandboxed agent this conversation ran (a display name also resolves).
            path (Optional[str]): One changed file, to read only its diff.
            offset (Optional[int]): Characters of the diff to skip, to read on from where a cut diff stopped.
        """
        from agno.tools.company import _authority

        run_id = None
        try:
            if bool(task_id) == bool(agent_id):
                return json.dumps({"error": "Give a task_id or an agent_id, one of the two."})
            if task_id:
                return json.dumps({"error": "Reading a Task's sandbox needs an asynchronous run."})
            agent, resolved_id, session_id = self._conversation_agent(str(agent_id), _agno_run_context)
            authority = _authority(_agno_run_context)
            if authority is not None:
                authority.require("agents", "run", resolved_id)
            self._sandboxed(agent)
            db = getattr(agent, "db", None)
            if db is None or isinstance(db, AsyncBaseDb):
                return json.dumps({"error": "Reading this agent's sandbox needs an asynchronous run."})
            rows = db.get_runs(session_id=session_id, **_NEWEST_RUNS)
            user_id = getattr(_agno_run_context, "user_id", None)
            row, commit, later, earlier = self._saved_run(rows, agent, user_id, "in this conversation")
            run_id = row["run_id"]
            with agent.open_run_checkpoint(run_id) as archive:
                changes = _checkout_changes(archive, commit, path or None, max(0, int(offset or 0)))
            return self._changes(agent, row, later, earlier, changes, path or None, None)
        except Exception as exc:
            return self._changes_error(exc, run_id)

    @requires_permission()
    async def aread_sandbox_changes(
        self,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        path: Optional[str] = None,
        offset: Optional[int] = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Read what an agent that works in a sandbox changed in its checkout: the changed files and the diff.

        A sandboxed agent edits its own checkout of the repository, which read_file does not read. Use
        this to check or quote what it changed. It reads the checkout the sandbox saved when the
        agent's last completed run ended, compared with the commit the sandbox started from, so it still
        works after the sandbox is gone, and it shows nothing of a run that failed or is still going.
        When the agent ran more than once in the session, the diff holds every run's changes, not only
        the last run's. It only reads. Give exactly one of task_id and agent_id.

        Args:
            task_id (Optional[str]): A Company Task a sandboxed agent executed.
            agent_id (Optional[str]): A sandboxed agent this conversation ran, in the turn or in the
                background (a display name also resolves).
            path (Optional[str]): One changed file, to read only its diff. Leave it out for every change.
            offset (Optional[int]): Characters of the diff to skip, to read on from where a cut diff
                stopped: the result of a cut diff names the offset to give. Leave it out to read from the start.

        Returns:
            str: JSON object with 'changed_files' (every changed file), 'diff', the 'run_id' that was
                read and 'base_commit'; a 'note' when the diff is cut, holds earlier runs' changes or
                is empty; or an 'error' saying why the changes cannot be read.
        """
        from agno.tools.company import _authority

        run_id = None
        try:
            if bool(task_id) == bool(agent_id):
                return json.dumps({"error": "Give a task_id or an agent_id, one of the two."})
            user_id = None
            if task_id:
                agent, db, session_id = await self._atask_agent(str(task_id), _agno_run_context)
                where = "for this Task"
            else:
                agent, resolved_id, session_id = await asyncio.to_thread(
                    self._conversation_agent, str(agent_id), _agno_run_context
                )
                authority = _authority(_agno_run_context)
                if authority is not None:
                    await authority.arequire("agents", "run", resolved_id)
                self._sandboxed(agent)
                db, where = getattr(agent, "db", None), "in this conversation"
                user_id = getattr(_agno_run_context, "user_id", None)
            if db is None:
                raise _Unreadable("This agent stores no runs, so there is no saved checkout to read.")
            if isinstance(db, AsyncBaseDb):
                rows = await db.get_runs(session_id=session_id, **_NEWEST_RUNS)
            else:
                rows = await asyncio.to_thread(lambda: db.get_runs(session_id=session_id, **_NEWEST_RUNS))
            row, commit, later, earlier = self._saved_run(rows, agent, user_id, where)
            run_id = row["run_id"]
            async with agent.aopen_run_checkpoint(run_id) as archive:
                changes = await asyncio.to_thread(
                    _checkout_changes, archive, commit, path or None, max(0, int(offset or 0))
                )
            return self._changes(agent, row, later, earlier, changes, path or None, task_id or None)
        except Exception as exc:
            return self._changes_error(exc, run_id)


# The model is shown the base tools' descriptions: the guard adds nothing to what they say.
for _name in ("run_agent", "run_team", "run_workflow", "arun_agent", "arun_team", "arun_workflow"):
    getattr(BackgroundRunTools, _name).__doc__ = getattr(StudioRunnerTools, _name).__doc__
# A synchronous run is told the same about the tool as an asynchronous one.
BackgroundRunTools.read_sandbox_changes.__doc__ = BackgroundRunTools.aread_sandbox_changes.__doc__
