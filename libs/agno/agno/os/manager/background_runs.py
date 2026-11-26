"""Super Agent's run tools: the ordinary ones, plus starting a run in the background and reading it.

A background run does not go through the component directly. The tool makes every check a run in
the turn makes, then enters the component's own run route in process with background on, under the
person's authority. The route puts the run on the durable queue when it is on, and starts it as a
task in the server's memory when it is not. The tool returns a receipt and the turn goes on.

The run is recorded in the conversation's linked work, and stores which conversation asked for it.
While it is going, no other run of that component may start from the conversation, in the turn or in
the background: nothing else stops two runs from writing one session at once.
"""

import asyncio
import json
from threading import Lock
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote
from weakref import ReferenceType, ref

from agno.db.base import AsyncBaseDb
from agno.db.schemas.scheduler import REQUESTED_FROM_METADATA_KEY
from agno.os.manager.linked_work import (
    _RUN_LIVE,
    _UNREAD,
    RUN_STATUS_MEANING,
    _entries,
    _run_phase,
    aget_stored_run,
    get_stored_run,
    link_run,
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
    """StudioRunnerTools for Super Agent, with start_background_run and check_background_run."""

    def __init__(self, agent_os: Any, **kwargs: Any):
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

    def _enter(self, kind: str, identifier: str, run_context: Any) -> Tuple[Optional[str], Optional[str]]:
        """Reserve the session of a run in the turn. Returns the session to release, or a refusal."""
        session_id, name = self._session_of(kind, identifier, run_context)
        if session_id is None:
            return None, None
        refusal = self._reserve(session_id, name)
        if refusal is None:
            for entry in self._going(run_context, session_id):
                row = get_stored_run(self._run_stores(entry.get("db_id")), entry["id"])
                refusal = self._held_by(run_context, entry, row)
                if refusal is not None:
                    self._release(session_id)
                    break
        return (None, json.dumps({"error": refusal})) if refusal is not None else (session_id, None)

    async def _aenter(self, kind: str, identifier: str, run_context: Any) -> Tuple[Optional[str], Optional[str]]:
        session_id, name = await asyncio.to_thread(self._session_of, kind, identifier, run_context)
        if session_id is None:
            return None, None
        refusal = self._reserve(session_id, name)
        if refusal is None:
            refusal = await self._aheld(run_context, session_id)
            if refusal is not None:
                self._release(session_id)
        return (None, json.dumps({"error": refusal})) if refusal is not None else (session_id, None)

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
        finished. Its state is shown to you on every turn, and check_background_run reads its
        result once it has one. A later run of the same component from this conversation continues
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
            return await self._start(app, authority, run_context, component, run, message, user_id, metadata)
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
    ) -> str:
        """Enter the component's run route with background on, and record the run it accepted."""
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
            entry["shown"] = _run_phase(status)
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


# The model is shown the base tools' descriptions: the guard adds nothing to what they say.
for _name in ("run_agent", "run_team", "run_workflow", "arun_agent", "arun_team", "arun_workflow"):
    getattr(BackgroundRunTools, _name).__doc__ = getattr(StudioRunnerTools, _name).__doc__
