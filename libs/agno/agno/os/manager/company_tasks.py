"""Super Agent tools for Company Tasks: start accepted work, read its state, and record a person's decisions.

Starting reuses the Company start route's checks, duplicate handling and queue path, under
the calling user's own authority. The decision tools approve a Project, accept Tasks and
review a finished one. Each decision pauses the run until the chatting person confirms it,
runs under that person's permissions, and records that person on the transition.
"""

import json
from typing import Any, Dict, List, Optional
from weakref import ReferenceType, ref

from agno.tools import Toolkit

_STATUS_WORDS = {
    "backlog": "proposed, not accepted",
    "ready": "accepted, not started",
    "in_progress": "started",
    "in_review": "finished, waiting for review",
    "done": "done",
    "cancelled": "cancelled",
}


def _run_context_identity(run_context: Any):
    from agno.tools.company import _authority, _identity

    return _authority(run_context), _identity(run_context)


def _same_name(given: Any, stored: Any) -> bool:
    """Whether the name the person confirmed is the record's name, ignoring case and spacing."""
    return " ".join(str(given or "").split()).casefold() == " ".join(str(stored or "").split()).casefold()


def _same_version(given: Any, stored: Any) -> bool:
    """Whether the updated_at the person confirmed is the Task's. A Task never edited has none."""
    given = None if given in (None, "", "null") else str(given)
    return given == (None if stored is None else str(stored))


def _refusal(authority: Any) -> Optional[str]:
    from agno.company.execution import _automatic_task, _ExecutorAuthorization
    from agno.company.routines import _RoutineAuthorization

    if isinstance(authority, (_RoutineAuthorization, _ExecutorAuthorization)) or _automatic_task.get() is not None:
        return "Task runs are started by people. Automated runs cannot start Tasks."
    return None


class CompanyTaskTools(Toolkit):
    """Start an accepted Task in the background, check on it later, and record a person's decisions."""

    def __init__(self, agent_os: Any):
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        names = [
            "start_company_task",
            "get_company_task_status",
            "approve_company_project",
            "accept_company_task",
            "review_company_task",
        ]
        super().__init__(
            name="company_tasks",
            tools=[getattr(self, name) for name in names],
            async_tools=[(getattr(self, "a" + name), name) for name in names],
            # A decision is the person's: the run pauses until they confirm the record and the change.
            requires_confirmation_tools=["approve_company_project", "accept_company_task", "review_company_task"],
            # The receipt is the reply: the coordinator turn ends once the run is queued.
            stop_after_tool_call_tools=["start_company_task"],
            show_result_tools=["start_company_task"],
        )

    def start_company_task(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Start an accepted Company Task in the background and return its run.

        Args:
            task_id: The accepted (Ready) Task to start.
        """
        return "Starting a Task needs an asynchronous run. Start it from AgentOS instead."

    async def astart_company_task(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Start an accepted Company Task in the background and return its run.

        The Task runs in its own session; this conversation continues. Call this tool on its
        own, then tell the person the run is queued. Use get_company_task_status for progress.

        Args:
            task_id: The accepted (Ready) Task to start.
        """
        from fastapi import HTTPException

        from agno.company.execution import _pending_task_attempt, _TaskRunConflict, _TaskRunUnavailable
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter

        agent_os = self._agent_os()
        app = getattr(agent_os, "_company_app", None)
        if agent_os is None or app is None:
            return "Company execution is not running here. Start the Task from AgentOS."
        authority, user_id = _run_context_identity(_agno_run_context)
        refusal = _refusal(authority)
        if refusal is not None:
            return refusal
        if getattr(agent_os, "user_isolation", False) and not user_id:
            return "A signed-in person is required to start a Task."

        starter = _TaskStarter(agent_os)
        try:
            value = await starter.task(task_id)
            title = value.get("title") or task_id
            if value["status"] == "backlog":
                return f"'{title}' is still a proposal. A person must accept it with an executor before it can start."
            if value["status"] == "in_review":
                return f"'{title}' is waiting for review. The person completes it or sends it back."
            if value["status"] != "ready" and _pending_task_attempt(value) is None:
                return (
                    f"'{title}' is {_STATUS_WORDS.get(value['status'], value['status'])}; only accepted work can start."
                )
            if authority is not None:
                # The start route's own requirements, beyond running the executor.
                await authority.arequire("tasks", "write")
                await authority.arequire("wiki", "read")
            conversation = {
                "session_id": getattr(_agno_run_context, "session_id", None),
                "run_id": getattr(_agno_run_context, "run_id", None),
                "team_id": "superagent",
            }
            requested_from = {key: item for key, item in conversation.items() if isinstance(item, str)}
            caller = _StartCaller.for_authority(app, authority, user_id, requested_from)
            response = await starter.submit(task_id, caller, None, value, None)
        except PermissionError as exc:
            return f"Not started: {exc}"
        except HTTPException as exc:
            return f"Not started: {exc.detail}"
        except (_TaskRunConflict, _TaskRunUnavailable) as exc:
            return f"Not started: {exc}"

        body = json.loads(bytes(response.body)) if response.body else {}
        if response.status_code != 202:
            return f"Not started: {body.get('detail') or 'the run was refused'}"
        status = body.get("status")
        run = f"(Task {task_id}, run {body.get('run_id')})"
        if status in ("PENDING", "QUEUED", None):
            return f"Queued '{title}' {run}. It runs in its own session; ask for its status at any time."
        if status == "RUNNING":
            return f"'{title}' is already running {run}."
        return f"'{title}' already has this attempt, now {status} {run}."

    def get_company_task_status(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Company Task's saved state and latest run without waiting for it.

        Args:
            task_id: The Task to inspect.
        """
        return "Reading Task status needs an asynchronous run. Open the Task in AgentOS instead."

    async def aget_company_task_status(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Company Task's saved state and latest run without waiting for it.

        Reports what is recorded: the Task status, the latest attempt and its run, and the
        saved result once there is one. A finished run is not proof the outcome was achieved.

        Args:
            task_id: The Task to inspect.
        """
        from fastapi import HTTPException

        from agno.os.job_queue import ticket_status_to_api
        from agno.os.routers.company.runs import _TaskStarter

        agent_os = self._agent_os()
        if agent_os is None:
            return "Company is not running here."
        authority, _ = _run_context_identity(_agno_run_context)
        try:
            if authority is not None:
                await authority.arequire("tasks", "read")
            value = await _TaskStarter(agent_os).task(task_id)
        except PermissionError as exc:
            return f"Cannot read the Task: {exc}"
        except HTTPException as exc:
            return f"Cannot read the Task: {exc.detail}"

        attempts = [entry for entry in value.get("transitions") or [] if entry.get("attempt")]
        latest: Dict[str, Any] = attempts[-1] if attempts else {}
        state: Dict[str, Any] = {
            "task_id": value["id"],
            "title": value.get("title"),
            "status": value["status"],
            "meaning": _STATUS_WORDS.get(value["status"], value["status"]),
            "executor": value.get("executor_id"),
            "attempt": latest.get("attempt"),
            "run_id": value.get("job_id"),
            "started_by": latest.get("started_by"),
            "requested_from": latest.get("requested_from"),
        }
        app = getattr(agent_os, "_company_app", None)
        queue = getattr(getattr(app, "state", None), "queue_worker", None)
        if value.get("job_id") and queue is not None:
            job = await queue.store.get_job(value["job_id"])
            if job is not None:
                state["run_status"] = ticket_status_to_api(job["status"])
        result = value.get("result") or {}
        if result.get("run_id") == value.get("job_id") and result:
            state["run_status"] = result.get("status") or state.get("run_status")
            content = result.get("content")
            state["result"] = content[:1500] if isinstance(content, str) else content
            if result.get("invoked"):
                state["invoked"] = result["invoked"]
        return json.dumps(state, ensure_ascii=False, default=str)

    def _person(self, agent_os: Any, run_context: Any) -> Any:
        """The chatting person's authority and identity. Raises PermissionError for every other caller."""
        from agno.tools.company import _require_human_creation

        _require_human_creation(run_context, "decide Company work")
        authority, user_id = _run_context_identity(run_context)
        if getattr(agent_os, "user_isolation", False) and not user_id:
            raise PermissionError("A signed-in person is required to decide Company work")
        return authority, user_id

    async def _decide(self, call: Any) -> str:
        """Run one decision, returning each refusal as text and leaving the record as it was."""
        from fastapi import HTTPException

        agent_os = self._agent_os()
        if agent_os is None or getattr(agent_os, "_company_db", None) is None:
            return "Company is not running here."
        try:
            return await call(agent_os)
        except HTTPException as exc:
            return f"Not done: {exc.detail}"
        except (PermissionError, LookupError, ValueError) as exc:
            return f"Not done: {exc}"
        except NotImplementedError:
            return "Not done: the configured database does not support Company work."

    def approve_company_project(
        self, project_name: str, project_id: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Approve a proposed Company Project. The run pauses for the person to confirm.

        Args:
            project_name: The Project's name, as stored.
            project_id: The proposed Project to approve.
        """
        return "Approving a Project needs an asynchronous run. Approve it from AgentOS instead."

    async def aapprove_company_project(
        self, project_name: str, project_id: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Approve a proposed Company Project. It becomes active. The run pauses for the person to
        confirm the Project by name and ID.

        Call this only when the person asked, in this conversation, to approve this Project. A request
        to plan, list or summarize work is not a request to approve it. The person who confirms is
        recorded as the one who approved.

        Args:
            project_name: The Project's name, as stored. The person confirms this name.
            project_id: The proposed Project to approve.
        """
        from dataclasses import replace

        from agno.company.routines import _manager_call
        from agno.os.routers.company.runs import _TaskStarter
        from agno.run.authorization import authorization_scope

        async def call(agent_os: Any) -> str:
            authority, user_id = self._person(agent_os, _agno_run_context)
            if authority is not None:
                await authority.arequire("projects", "write")
            manager = _TaskStarter(agent_os).manager
            project = await _manager_call(manager, "get_project", project_id)
            if project is None:
                return "Not done: Project not found"
            if not _same_name(project_name, project["name"]):
                return f"Not done: Project {project_id} is named '{project['name']}'. Call again with that name."
            if project["status"] != "proposed":
                return f"'{project['name']}' is {project['status']}; only a proposed Project can be approved."
            saved = replace(authority, enforce_tools=False) if authority is not None else None
            with authorization_scope(lambda: saved):
                record = await _manager_call(
                    manager,
                    "transition_project",
                    project_id=project_id,
                    target="active",
                    reason="Approved in chat",
                    accepted_by=user_id,
                    expected_updated_at=project["updated_at"],
                )
            if record is None:
                return f"Not done: '{project['name']}' changed while it was being approved. Read it again."
            return f"Approved Project '{project['name']}' ({project_id}). Its Tasks can now be accepted."

        return await self._decide(call)

    def accept_company_task(
        self,
        tasks: List[Dict[str, Any]],
        executor_type: Optional[str],
        executor_id: Optional[str],
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Accept Backlog Company Tasks with one executor. The run pauses for the person to confirm.

        Args:
            tasks: The Tasks to accept, each as {"title": the stored title, "task_id": the id,
                "updated_at": the Task's updated_at as the person saw it}.
            executor_type: agent, team or workflow. With no executor named, pass agent.
            executor_id: ID of that component. With no executor named, pass miniagent.
        """
        return "Accepting a Task needs an asynchronous run. Accept it from AgentOS instead."

    async def aaccept_company_task(
        self,
        tasks: List[Dict[str, Any]],
        executor_type: Optional[str],
        executor_id: Optional[str],
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Accept Backlog Company Tasks with one executor. They become Ready. The run pauses for the
        person to confirm each Task by title, ID and version, and the executor.

        Call this only when the person asked, in this conversation, to accept these Tasks. A request to
        plan, list or summarize work is not a request to accept it. Pass every Task the person named in
        one call, so they confirm once. Each Task's Project must be active. Name the executor the person
        named. With none named, pass agent and miniagent: Mini Agent does the work itself or runs the
        components the person may run. Accepting does not start a Task; use start_company_task when the
        person asks.

        Args:
            tasks: The Tasks to accept, each as {"title": the stored title, "task_id": the id,
                "updated_at": the Task's updated_at as the person saw it}. A Task edited after that is
                not accepted: show it again first.
            executor_type: agent, team or workflow. With no executor named, pass agent.
            executor_id: ID of that component. With no executor named, pass miniagent.
        """
        from dataclasses import replace

        from agno.company.routines import _manager_call
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter
        from agno.registry._reserved import MINI_AGENT_ID
        from agno.run.authorization import authorization_scope

        async def call(agent_os: Any) -> str:
            from fastapi import HTTPException

            authority, user_id = self._person(agent_os, _agno_run_context)
            kind, name = executor_type or None, executor_id or None
            if (kind is None) != (name is None):
                return "Not done: give executor_type and executor_id together, or leave both out to use Mini Agent."
            if kind is None:
                kind, name = "agent", MINI_AGENT_ID
            if kind not in ("agent", "team", "workflow"):
                return "Not done: executor_type is agent, team or workflow."
            if not tasks:
                return "Not done: name at least one Task."
            if authority is not None:
                await authority.arequire("tasks", "write")
            starter = _TaskStarter(agent_os)
            # Nothing is accepted unless every Task is the version the person confirmed, and still a proposal.
            values = []
            for item in tasks:
                value = await starter.task(str(item.get("task_id") or ""))
                title = value.get("title") or value["id"]
                if not _same_name(item.get("title"), title):
                    return f"Not done: Task {value['id']} is titled '{title}'. Call again with that title."
                if value["status"] != "backlog":
                    words = _STATUS_WORDS.get(value["status"], value["status"])
                    return f"Not done: '{title}' is {words}; only a proposal can be accepted."
                if not _same_version(item.get("updated_at"), value["updated_at"]):
                    return (
                        f"Not done: '{title}' (Task {value['id']}) changed since the person saw it. "
                        "Show it to them again, then call with its updated_at."
                    )
                values.append(value)
            # The transition route's decision: the person must be allowed to run the executor themselves.
            caller = _StartCaller.for_authority(getattr(agent_os, "_company_app", None), authority, user_id)
            await caller.require_accept(starter.endpoint({"executor_type": kind, "executor_id": name}))
            saved = replace(authority, enforce_tools=False) if authority is not None else None
            lines, accepted = [], False
            for value in values:
                title = value.get("title") or value["id"]
                try:
                    with authorization_scope(lambda: saved):
                        record = await _manager_call(
                            starter.manager,
                            "transition_task",
                            task_id=value["id"],
                            target="ready",
                            reason="Accepted in chat",
                            accepted_by=user_id,
                            executor_type=kind,
                            executor_id=name,
                            expected_updated_at=value["updated_at"],
                        )
                except HTTPException as exc:
                    lines.append(f"Not done: '{title}' (Task {value['id']}): {exc.detail}")
                except (PermissionError, LookupError, ValueError) as exc:
                    lines.append(f"Not done: '{title}' (Task {value['id']}): {exc}")
                else:
                    if record is None:
                        lines.append(f"Not done: '{title}' (Task {value['id']}) changed while it was being accepted.")
                    else:
                        accepted = True
                        lines.append(f"Accepted '{title}' (Task {value['id']}) for {kind} {name}.")
            return " ".join(lines) + (" Accepted Tasks are Ready and not started." if accepted else "")

        return await self._decide(call)

    def review_company_task(
        self,
        task_title: str,
        outcome: str,
        reason: str,
        task_id: str,
        reviewed_run_id: str,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Complete a Company Task in review, or send it back. The run pauses for the person to confirm.

        Args:
            task_title: The Task's title, as stored.
            outcome: complete or send_back.
            reason: The person's reason, in their words.
            task_id: The Task in review.
            reviewed_run_id: The run_id returned by get_company_task_status for the result being reviewed.
        """
        return "Reviewing a Task needs an asynchronous run. Review it from AgentOS instead."

    async def areview_company_task(
        self,
        task_title: str,
        outcome: str,
        reason: str,
        task_id: str,
        reviewed_run_id: str,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Complete a Company Task in review, or send it back. The run pauses for the person to confirm
        the Task by title and ID, the reviewed run, the outcome and the reason.

        Call this only when the person asked, in this conversation, to complete this Task or send it
        back. Show them the saved result first when they have not seen it. complete moves the Task to
        Done. send_back returns it to Ready with the same executor; the reason is given to the executor
        on its next attempt, which starts when the person asks, with start_company_task.

        Args:
            task_title: The Task's title, as stored. The person confirms this title.
            outcome: complete or send_back.
            reason: The person's reason, in their words. Required to send a Task back.
            task_id: The Task in review.
            reviewed_run_id: The run_id returned by get_company_task_status for the result being reviewed.
        """
        from dataclasses import replace

        from agno.company.routines import _manager_call
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter
        from agno.run.authorization import authorization_scope

        async def call(agent_os: Any) -> str:
            authority, user_id = self._person(agent_os, _agno_run_context)
            if outcome not in ("complete", "send_back"):
                return "Not done: outcome is complete or send_back."
            if outcome == "send_back" and not (reason or "").strip():
                return "Not done: sending a Task back needs the person's reason."
            if authority is not None:
                await authority.arequire("tasks", "write")
            starter = _TaskStarter(agent_os)
            value = await starter.task(task_id)
            title = value.get("title") or task_id
            if not _same_name(task_title, title):
                return f"Not done: Task {task_id} is titled '{title}'. Call again with that title."
            if value["status"] != "in_review":
                words = _STATUS_WORDS.get(value["status"], value["status"])
                return f"'{title}' is {words}; only a Task in review can be completed or sent back."
            if not reviewed_run_id or value.get("job_id") != reviewed_run_id:
                return "Not done: the Task's attempt changed. Read its latest result and request a new confirmation."
            executor: Dict[str, Any] = {}
            if outcome == "send_back":
                # A return to Ready is a fresh acceptance of the same executor.
                executor = {"executor_type": value["executor_type"], "executor_id": value["executor_id"]}
                caller = _StartCaller.for_authority(getattr(agent_os, "_company_app", None), authority, user_id)
                await caller.require_accept(starter.endpoint(executor))
            saved = replace(authority, enforce_tools=False) if authority is not None else None
            with authorization_scope(lambda: saved):
                record = await _manager_call(
                    starter.manager,
                    "transition_task",
                    task_id=task_id,
                    target="done" if outcome == "complete" else "ready",
                    reason=(reason or "").strip() or "Completed in chat",
                    accepted_by=user_id,
                    expected_updated_at=value["updated_at"],
                    # Seconds cannot tell two writes in one second apart. The stage and the run can.
                    expected_status="in_review",
                    expected_job_id=reviewed_run_id,
                    **executor,
                )
            if record is None:
                return f"Not done: '{title}' changed while it was being reviewed. Read it again."
            if outcome == "complete":
                return f"Completed '{title}' (Task {task_id}). It is Done."
            return f"Sent '{title}' (Task {task_id}) back to Ready for {value['executor_type']} {value['executor_id']}. It is not started."

        return await self._decide(call)
