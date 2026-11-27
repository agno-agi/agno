"""Super Agent tools for Company Tasks: add work a person asked for, start accepted work, read its
state, and record a person's decisions.

Work a person asks for in chat is created accepted, with that person recorded as the accepter:
the ask is the acceptance. A message to a Task that has run returns it to Ready and starts its next
attempt in one step, on the same ground. Starting reuses the Company start route's checks, duplicate
handling and queue path, under the calling user's own authority. The decision tools approve a Project,
accept Tasks and review a finished one. Each decision pauses the run until the chatting person
confirms it, runs under that person's permissions, and records that person on the transition.
Two more tools turn a Routine's auto-accept on, with the same confirmation, or off.
"""

import json
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from weakref import ReferenceType, ref

from pydantic import BaseModel, ConfigDict, Field

from agno.db.schemas.tasks import TASK_STATUS_MEANING
from agno.os.manager.linked_work import link_task
from agno.tools import Toolkit
from agno.tools.company import _CONTEXT_KINDS, _OptionalContext, _OptionalInt, _OptionalString


def _run_context_identity(run_context: Any):
    from agno.tools.company import _authority, _identity

    return _authority(run_context), _identity(run_context)


def _same_name(given: Any, stored: Any) -> bool:
    """Whether the name the person confirmed is the record's name, ignoring case and spacing."""
    return " ".join(str(given or "").split()).casefold() == " ".join(str(stored or "").split()).casefold()


class TaskToAccept(BaseModel):
    """One Task on an accept_company_task call, as the person confirms it."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(description="The Task's title, as stored.")
    task_id: str = Field(description="The Task's ID.")
    updated_at: _OptionalInt = Field(description="The Task's updated_at as the person saw it; null when it has none.")


def _same_version(given: Any, record: Dict[str, Any]) -> bool:
    """Whether the updated_at the person confirmed is the record's.

    A record never edited has none, and no record has the version 0. Null, an empty value, 0 and the
    record's own created_at all name a record that was never edited: an edit gives it an updated_at.
    """
    stored = record.get("updated_at")
    given = None if given in (None, "", "null", 0, "0") else str(given)
    if stored is None:
        return given is None or given == str(record.get("created_at"))
    return given == str(stored)


# What a model writes in an optional argument it means to leave empty, without its punctuation.
_NOTHING = {"", "none", "null", "omitplaceholder"}


def _named(value: Any) -> Optional[str]:
    """An optional name as the model gave it. A value with no letter or digit, such as "" or ",", names
    nothing, and neither does a placeholder such as "__NONE__" or "[null]"."""
    if not isinstance(value, str):
        return None
    return None if "".join(character for character in value if character.isalnum()).lower() in _NOTHING else value


def _user_isolation(agent_os: Any) -> bool:
    """Whether per-user isolation is on, set on AgentOS or on its AuthorizationConfig."""
    config = getattr(agent_os, "authorization_config", None)
    return bool(
        getattr(agent_os, "user_isolation", False)
        or (getattr(agent_os, "authorization", False) and config is not None and config.user_isolation)
    )


def _unsigned(agent_os: Any, authority: Any, user_id: Any) -> bool:
    """Whether nobody stands behind this run: it carries no permissions where the deployment checks
    them, or names no person where the deployment isolates users."""
    from agno.os.auth import _authorization_enforced

    # An authorization middleware on the app checks permissions just as AgentOS(authorization=...) does
    app = getattr(agent_os, "_company_app", None)
    authorization = bool(getattr(agent_os, "authorization", None)) or (app is not None and _authorization_enforced(app))
    return (authority is None and authorization) or (_user_isolation(agent_os) and not user_id)


def _policy_line(policy: Any) -> str:
    """A Routine's stored auto-accept policy on one line, for the person to confirm before it is kept."""
    from datetime import datetime, timezone

    parts = [
        f"default executor {policy.default_executor}",
        "proposals may name "
        + ("any executor" if policy.executors is None else ", ".join(policy.executors) or "no other executor"),
        "approves its Projects" if policy.approve_projects else "a person approves its Projects",
    ]
    if policy.limits is None:
        parts.append(f"at most {policy.max_open} Tasks open")
    else:
        expires = datetime.fromtimestamp(policy.limits.expires_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts.append(f"at most {policy.limits.max_acceptances} acceptances, expires {expires}")
    if policy.source_ids is not None:
        parts.append("Sources " + (", ".join(policy.source_ids) or "none"))
    scope = policy.work_scope
    if scope is not None and scope.goal_ids is not None:
        parts.append("Goals " + (", ".join(scope.goal_ids) or "none"))
    if scope is not None and scope.project_ids is not None:
        parts.append("Projects " + (", ".join(str(item) for item in scope.project_ids) or "none"))
    if policy.required_checks != ["executor_registered"]:
        parts.append("checks " + ", ".join(policy.required_checks))
    if policy.complete_projects:
        parts.append("completes Projects")
    return "; ".join(parts)


def _refusal(authority: Any) -> Optional[str]:
    from agno.company.execution import _automatic_task, _ExecutorAuthorization
    from agno.company.routines import _RoutineAuthorization

    automated = isinstance(authority, (_RoutineAuthorization, _ExecutorAuthorization))
    if automated or _automatic_task.get() is not None or getattr(authority, "scheduled", False):
        return "Task runs are started by people. Automated runs cannot start Tasks."
    return None


def _requested_from(run_context: Any) -> Dict[str, str]:
    conversation = {
        "session_id": getattr(run_context, "session_id", None),
        "run_id": getattr(run_context, "run_id", None),
        "team_id": "superagent",
    }
    return {key: item for key, item in conversation.items() if isinstance(item, str)}


# The most Tasks one chat run creates already accepted. Past it a Task is recorded as a proposal,
# which the person accepts through accept_company_task and its confirmation.
ACCEPTED_TASKS_PER_RUN = 5

# Accepted Tasks created by each recent chat run, by run id. A continued run keeps its id, so a
# confirmation pause does not reset its count. Held in this process only.
_accepted_in_run: "OrderedDict[str, int]" = OrderedDict()


def _take_acceptance(run_id: Any) -> bool:
    """Take one of a run's places for accepted work. False once the run has used them all."""
    key = run_id if isinstance(run_id, str) else ""
    used = _accepted_in_run.get(key, 0)
    if used >= ACCEPTED_TASKS_PER_RUN:
        return False
    _accepted_in_run[key] = used + 1
    _accepted_in_run.move_to_end(key)
    while len(_accepted_in_run) > 1024:
        _accepted_in_run.popitem(last=False)
    return True


def _return_acceptance(run_id: Any) -> None:
    """Give back a place taken for a Task that was not created."""
    key = run_id if isinstance(run_id, str) else ""
    if _accepted_in_run.get(key, 0) > 0:
        _accepted_in_run[key] -= 1


class CompanyTaskTools(Toolkit):
    """Add work a person asked for, start an accepted Task in the background, check on it later, and
    record a person's decisions."""

    def __init__(self, agent_os: Any):
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        names = [
            "add_company_task",
            "move_company_task",
            "start_company_task",
            "message_company_task",
            "get_company_task_status",
            "approve_company_project",
            "accept_company_task",
            "review_company_task",
            "turn_on_routine_auto_accept",
            "turn_off_routine_auto_accept",
        ]
        super().__init__(
            name="company_tasks",
            tools=[getattr(self, name) for name in names],
            async_tools=[(getattr(self, "a" + name), name) for name in names],
            # A decision is the person's: the run pauses until they confirm the record and the change.
            # Auto-accept lets a Routine's work run with no person, so turning it on is confirmed too.
            requires_confirmation_tools=[
                "approve_company_project",
                "accept_company_task",
                "review_company_task",
                "turn_on_routine_auto_accept",
            ],
        )

    def _caller_context(self, run_context: Any) -> Tuple[Any, Any, Any, Optional[str], Optional[str]]:
        """The OS, its app, the caller's authority and identity, and a refusal when they cannot act."""
        agent_os = self._agent_os()
        app = getattr(agent_os, "_company_app", None)
        authority, user_id = _run_context_identity(run_context)
        if agent_os is None or app is None:
            return agent_os, app, authority, user_id, "Company execution is not running here. Use AgentOS instead."
        refusal = _refusal(authority)
        if refusal is None and _unsigned(agent_os, authority, user_id):
            refusal = "A signed-in person is required."
        return agent_os, app, authority, user_id, refusal

    def add_company_task(
        self,
        title: str,
        brief: str,
        start: bool,
        project_id: _OptionalString = None,
        goal_id: _OptionalString = None,
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        context: _OptionalContext = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Add a Company Task the person asked for, already accepted, and start it when they asked for it to be done.

        Args:
            title: The Task's title.
            brief: The Task brief, written for the executor.
            start: True when the person asked for the work to be done; false when they asked to add it.
            project_id: The active Project this Task is part of; null puts it in the Default Project.
            goal_id: The Goal this Task belongs to; null for none.
            executor_type: agent, team or workflow; null with a null executor_id uses Mini Agent.
            executor_id: ID of that component; null with a null executor_type.
            context: What the run is given beside the brief; null attaches nothing.
        """
        return "Adding accepted work needs an asynchronous run. Add the Task from AgentOS instead."

    async def aadd_company_task(
        self,
        title: str,
        brief: str,
        start: bool,
        project_id: _OptionalString = None,
        goal_id: _OptionalString = None,
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        context: _OptionalContext = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Add a Company Task the person asked for, already accepted, and start it when they asked for it
        to be done. The person's request is the acceptance: the Task is Ready, with that person recorded
        as the one who accepted it, and the run does not pause.

        Call this only for work the person asked for in this conversation, in their words: to add a
        Task, or to do a task. When they ask you to do a task and no Task records it yet, call this
        with start true instead of doing the work in the conversation or running a component. Work
        you suggest yourself is a proposal: use propose_company_task.
        When the work sends, publishes, pushes or spends, say what it involves and ask the person before
        calling this. For work a Task already covers, start that Task instead of adding another.

        Some Tasks are recorded as proposals instead, and the result says so: a Task for an executor
        that pushes code, and every Task after the fifth accepted in one run. Call accept_company_task
        for those in the same turn: it pauses for the person's confirmation.

        Args:
            title: The Task's title.
            brief: The Task brief. A brief the person dictated is saved in their words. Otherwise write
                it for the executor: the outcome, the deliverable, how it is checked and any restrictions
                the person gave.
            start: True when the person asked for the work to be done, which queues its run now. False
                when they asked to add a Task: it stays Ready until someone starts it.
            project_id: The active Project this Task is part of: check list_company_projects for the one
                it serves. Null when none fits, which puts the Task in the Default Project. A proposed
                Project cannot hold accepted work.
            goal_id: The Goal this Task belongs to; null for none. In a Project, null takes the
                Project's Goal and another Goal is refused.
            executor_type: agent, team or workflow, only when the person named a component. Null with a
                null executor_id runs it on Mini Agent, which does the work itself or runs the components
                the person may run.
            executor_id: ID of the component the person named; null when they named none.
            context: What the run is given beside the brief; null attaches nothing. With start true the
                run is queued by this call, so attach here: there is no later moment. CONTEXT_KINDS
        """
        from dataclasses import replace

        from agno.company.context import read_permissions
        from agno.company.routines import _manager_call
        from agno.company.sandbox import _is_sandboxed
        from agno.db.schemas.projects import is_default_project
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter
        from agno.registry._reserved import MINI_AGENT_ID
        from agno.run.authorization import authorization_scope

        async def call(agent_os: Any) -> str:
            authority, user_id = self._person(agent_os, _agno_run_context, "add accepted Company work")
            kind, name = _named(executor_type), _named(executor_id)
            if (kind is None) != (name is None):
                return "Not done: give executor_type and executor_id together, or neither to use Mini Agent."
            if kind is None:
                kind, name = "agent", MINI_AGENT_ID
            if kind not in ("agent", "team", "workflow"):
                return "Not done: executor_type is agent, team or workflow."
            if authority is not None:
                await authority.arequire("tasks", "write")
                # Attaching a reference asks for the permission that reads it.
                for resource, action in read_permissions(context):
                    await authority.arequire(resource, action)
            starter = _TaskStarter(agent_os)
            project = _named(project_id)
            if project is not None and not is_default_project(project):
                stored = await _manager_call(starter.manager, "get_project", project)
                if stored is None:
                    return "Not done: Project not found"
                if stored["status"] == "proposed":
                    return (
                        f"Not done: Project '{stored['name']}' is proposed, and accepted work needs an active "
                        "Project. Approve the Project first, or leave the Project out to put this Task in the "
                        "Default Project."
                    )
            # The acceptance route's decision: the person must be allowed to run the executor themselves.
            app = getattr(agent_os, "_company_app", None)
            caller = _StartCaller.for_authority(app, authority, user_id)
            executor = {"executor_type": kind, "executor_id": name}
            await caller.require_accept(starter.endpoint(executor))
            # What the person confirms before it is accepted: an executor that pushes code, and more
            # Tasks in one run than a person reads in one request.
            run_id = getattr(_agno_run_context, "run_id", None)
            waits = None
            if _is_sandboxed(starter.executor(executor)):
                waits = f"{kind} {name} runs in a sandbox and can push code"
            elif not _take_acceptance(run_id):
                waits = f"this run already added {ACCEPTED_TASKS_PER_RUN} accepted Tasks"
            # Asked only to add it, the Task is held for a person to start: the tick leaves it alone.
            # A Task that waits for the person's confirmation keeps the hold for the acceptance that follows.
            accepted: Dict[str, Any] = {"start_on_request": not start}
            if not waits:
                accepted.update(status="ready", accepted_by=user_id)
            saved = replace(authority, enforce_tools=False) if authority is not None else None
            try:
                with authorization_scope(lambda: saved):
                    task = await _manager_call(
                        starter.manager,
                        "create_task",
                        title=title,
                        brief=brief,
                        goal_id=_named(goal_id),
                        project_id=project,
                        user_id=user_id,
                        origin="human",
                        # Stored whether the Task is accepted or held back for confirmation.
                        context=context,
                        **executor,
                        **accepted,
                    )
            except BaseException:
                if not waits:
                    _return_acceptance(run_id)
                raise
            link_task(_agno_run_context, task)
            named = f"'{task['title']}' (Task {task['id']})"
            if waits:
                then = " Then start it with start_company_task." if start else ""
                return (
                    f"Recorded {named} as a proposal, not accepted: {waits}, so the person confirms it. "
                    f"Now call accept_company_task with this Task, updated_at null, executor {kind} {name}, "
                    f"which pauses for their confirmation; pass every waiting Task that takes this executor "
                    f"in one call.{then}"
                )
            added = f"Added {named}, accepted for {kind} {name}."
            if not start:
                return f"{added} It is Ready and not started."
            if app is None:
                return f"{added} Not started: Company execution is not running here. Start it from AgentOS."
            return f"{added} " + await self._start(agent_os, app, authority, user_id, _agno_run_context, task["id"])

        return await self._decide(call)

    def move_company_task(
        self, task_id: str, project_id: _OptionalString, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Move a Company Task into another Project.

        Args:
            task_id: The Task to move.
            project_id: The Project it moves into; null moves it to the Default Project.
        """
        return "Moving a Task needs an asynchronous run. Move it from AgentOS instead."

    async def amove_company_task(
        self, task_id: str, project_id: _OptionalString, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Move a Company Task into another Project. The move is the person's and is recorded on the
        Task's history with their name. It does not pause.

        Call this only when the person asked to move this Task. A Task moves while it is Backlog,
        Ready, In review or Done, and not while it is In progress or once it is cancelled. An
        accepted Task moves only into an active Project. A Task with a Goal moves only into a
        Project of that Goal or the Default Project; a Task with no Goal takes the Goal of the
        Project it moves into. Nothing else about the Task changes: its brief, executor and
        acceptance stay as they are.

        Args:
            task_id: The Task to move.
            project_id: The Project it moves into: check list_company_projects. Null moves it to the
                Default Project.
        """
        from dataclasses import replace

        from agno.company.routines import _manager_call
        from agno.os.routers.company.runs import _TaskStarter
        from agno.run.authorization import authorization_scope

        async def call(agent_os: Any) -> str:
            authority, user_id = self._person(agent_os, _agno_run_context, "move Company work")
            if authority is not None:
                await authority.arequire("tasks", "write")
            starter = _TaskStarter(agent_os)
            value = await starter.task(task_id)
            title = value.get("title") or task_id
            saved = replace(authority, enforce_tools=False) if authority is not None else None
            with authorization_scope(lambda: saved):
                moved = await _manager_call(
                    starter.manager,
                    "update_task",
                    task_id,
                    user_id=None,
                    moved_by=user_id,
                    project_id=_named(project_id),
                )
            if moved is None:
                return f"Not done: '{title}' changed while it was being moved. Read it again."
            if moved["project_id"] == value["project_id"]:
                return f"'{title}' (Task {task_id}) is already in that Project."
            project = await _manager_call(starter.manager, "get_project", moved["project_id"])
            name = (project or {}).get("name") or moved["project_id"]
            return f"Moved '{title}' (Task {task_id}) into Project '{name}'. Nothing else about it changed."

        return await self._decide(call)

    def start_company_task(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Start an accepted Company Task in the background and return its run.

        Args:
            task_id: The accepted (Ready) Task to start.
        """
        return "Starting a Task needs an asynchronous run. Start it from AgentOS instead."

    async def astart_company_task(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Start an accepted Company Task in the background and return its run.

        The Task runs in its own session; this conversation continues, and the turn does not end:
        start each Task the person asked for, then answer. The result is a receipt, not the work.
        A Task whose last run failed or was cancelled is started again the same way.

        Args:
            task_id: The accepted (Ready) Task to start, or the Task to retry after a failed run.
        """
        agent_os, app, authority, user_id, refusal = self._caller_context(_agno_run_context)
        if refusal is not None:
            return refusal
        return await self._start(agent_os, app, authority, user_id, _agno_run_context, task_id)

    async def _start(
        self, agent_os: Any, app: Any, authority: Any, user_id: Any, run_context: Any, task_id: str
    ) -> str:
        """Queue an accepted Task's run through the start route's own path, as a caller already checked."""
        return (await self._queue(agent_os, app, authority, user_id, run_context, task_id))[1]

    async def _queue(
        self,
        agent_os: Any,
        app: Any,
        authority: Any,
        user_id: Any,
        run_context: Any,
        task_id: str,
        attempt: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Queue a Task's run and say whether the queue holds it, with the receipt or the refusal.

        With an attempt, only that attempt is queued or joined: a Task that moved on is refused.
        """
        from fastapi import HTTPException

        from agno.company.execution import _pending_task_attempt, _TaskRunConflict, _TaskRunUnavailable
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter

        starter = _TaskStarter(agent_os)
        try:
            value = await starter.task(task_id)
            title = value.get("title") or task_id
            if value["status"] == "backlog":
                return (
                    False,
                    f"'{title}' is still a proposal. A person must accept it with an executor before it can start.",
                )
            if value["status"] == "in_review":
                return False, f"'{title}' is waiting for review. The person completes it or sends it back."
            # A Task whose last attempt failed or was cancelled stays In progress. Starting it is a retry,
            # and the start route decides whether the earlier run has ended.
            ended = value["status"] == "in_progress" and (value.get("result") or {}).get("status") in (
                "ERROR",
                "CANCELLED",
            )
            if value["status"] != "ready" and _pending_task_attempt(value) is None and not ended:
                meaning = TASK_STATUS_MEANING.get(value["status"], value["status"])
                return False, f"'{title}' is {meaning}; only accepted work can start."
            if authority is not None:
                # The start route's own requirements, beyond running the executor.
                await authority.arequire("tasks", "write")
                await authority.arequire("wiki", "read")
            caller = _StartCaller.for_authority(app, authority, user_id, _requested_from(run_context))
            response = await starter.submit(task_id, caller, attempt, value, None)
            if response.status_code == 202:
                link_task(run_context, await starter.task(task_id))
        except PermissionError as exc:
            return False, f"Not started: {exc}"
        except HTTPException as exc:
            return False, f"Not started: {exc.detail}"
        except (_TaskRunConflict, _TaskRunUnavailable) as exc:
            return False, f"Not started: {exc}"
        return response.status_code == 202, _receipt("Queued", title, task_id, response)

    def message_company_task(
        self, task_id: str, message: str, context: _OptionalContext = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Send the person's message to a Company Task that has run, and start its next attempt with it.

        Args:
            task_id: The Task to message: one waiting for review, or one whose last run failed or was cancelled.
            message: What the person asked for, in their words.
            context: More for the run to read beside the brief; null attaches nothing.
        """
        return "Messaging a Task needs an asynchronous run. Send the Task back from AgentOS instead."

    async def amessage_company_task(
        self, task_id: str, message: str, context: _OptionalContext = None, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Send the person's message to a Company Task that has run, and start its next attempt with it.
        The Task continues in its own session with its earlier work in view, and its executor receives
        the message as the person's reply to its last result. The run does not pause: the person's
        request in this conversation is the decision.

        Call this when the person answers a finished Task's question, picks one of its options, or
        asks it for changes or additions, such as "tell it to add a section" or "have it drop that
        restriction". It takes a Task waiting for review, and one whose last run failed or was
        cancelled. A Task that is still running is refused and nothing is queued or kept for later:
        tell the person, who asks again when its run has ended. To complete a Task use
        review_company_task; to retry a failed run unchanged use start_company_task. A Task that a
        Routine's policy accepted, or whose executor pushes code, is refused too: the person confirms
        those through review_company_task. The turn does not end: the result is a receipt, not the work.

        Args:
            task_id: The Task to message.
            message: What the person asked for, in their words, addressed to the Task's executor.
            context: More for the run to read beside the brief; null attaches nothing. CONTEXT_KINDS
        """
        from dataclasses import replace

        from agno.company.context import read_permissions
        from agno.company.execution import _call, _project_run_block
        from agno.company.routines import _manager_call
        from agno.company.sandbox import _is_sandboxed
        from agno.db.schemas.tasks import task_next_attempt
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter
        from agno.registry._reserved import MINI_AGENT_ID
        from agno.run.authorization import authorization_scope
        from agno.tools.company import _scoped_user

        async def call(agent_os: Any) -> str:
            authority, user_id = self._person(agent_os, _agno_run_context, "message a Company Task")
            text = (message or "").strip()
            if not text:
                return "Not sent: the message is empty."
            app = getattr(agent_os, "_company_app", None)
            if app is None:
                return "Not sent: Company execution is not running here."
            if authority is not None:
                await authority.arequire("tasks", "write")
                # The start route's own requirement, checked before anything is recorded.
                await authority.arequire("wiki", "read")
                # Attaching a reference asks for the permission that reads it.
                for resource, action in read_permissions(context):
                    await authority.arequire(resource, action)
            starter = _TaskStarter(agent_os)
            # Where users are isolated a person reaches only their own Tasks.
            owner = _scoped_user(_agno_run_context, _user_isolation(agent_os))
            value = await _call(starter.db, "get_task", task_id, user_id=owner)
            if value is None:
                return "Not sent: Task not found"
            title = value.get("title") or task_id
            status = value["status"]
            ended = status == "in_progress" and (value.get("result") or {}).get("status") in ("ERROR", "CANCELLED")
            if status == "in_progress" and not ended:
                if (await starter.state(value, app)).get("waiting_on"):
                    # A paused run does not end on its own: the person answers it, they do not wait for it.
                    return (
                        f"Not sent: '{title}' is paused, not running: its run waits for a person to approve or "
                        "answer it, and continues once they do. Nothing was sent or queued."
                    )
                return (
                    f"Not sent: '{title}' is still running. Nothing was interrupted and nothing is queued: "
                    "the person asks again when its run has ended."
                )
            if status == "backlog":
                return f"Not sent: '{title}' is a proposal that has not run. Edit its brief instead."
            if status == "ready":
                return (
                    f"Not sent: '{title}' is accepted and not started. Start it with start_company_task: "
                    "a reply already recorded on it goes with that run."
                )
            if status != "in_review" and not ended:
                return f"Not sent: '{title}' is {status}, and a message does not reopen a closed Task."
            # The return to Ready is a fresh acceptance of the same executor, or of Mini Agent when the
            # Task names none: the person must be allowed to run that executor themselves.
            kind, name = value.get("executor_type"), value.get("executor_id")
            if name is None:
                kind, name = "agent", MINI_AGENT_ID
            executor = {"executor_type": kind, "executor_id": name}
            await _StartCaller.for_authority(app, authority, user_id).require_accept(starter.endpoint(executor))
            confirmed = (
                "send it back with review_company_task, which pauses for their confirmation, then start it"
                if status == "in_review"
                else "retry it unchanged with start_company_task, or send it back from the Company pages"
            )
            if _is_sandboxed(starter.executor(executor)):
                # Work for an executor that pushes code is confirmed by the person, as when it is added.
                return (
                    f"Not sent: {kind} {name} runs in a sandbox and can push code, so the person confirms "
                    f"what '{title}' is asked to do: {confirmed}."
                )
            acceptances = [entry for entry in value.get("transitions") or [] if entry.get("target") == "ready"]
            if acceptances and acceptances[-1].get("auto_accept"):
                # A return to Ready is the person's own acceptance, and it lifts the limits of the policy
                # that accepted the Task. The person confirms that, as when they send it back from review.
                return (
                    f"Not sent: a Routine's policy accepted '{title}', and a message would put it under the "
                    f"person's own acceptance, so the person confirms it: {confirmed}."
                )
            # What the start would refuse is refused before the Task leaves its stage.
            starter.worker(app)
            blocked = await _project_run_block(starter.db, value)
            if blocked:
                return f"Not sent: {blocked}"
            # The run this message answers. A Task that moves on to another run is not returned to Ready.
            answered = value.get("job_id")
            saved = replace(authority, enforce_tools=False) if authority is not None else None
            with authorization_scope(lambda: saved):
                if context:
                    # A reference that names nothing is refused here, before the Task changes.
                    value = await _manager_call(
                        starter.manager, "change_task_context", task_id, add=context, user_id=user_id
                    )
                    if (value["status"], value.get("job_id")) != (status, answered):
                        return (
                            f"Not sent: '{title}' changed while the message was being sent. "
                            "The context was attached. Read it again."
                        )
                record = await _manager_call(
                    starter.manager,
                    "transition_task",
                    task_id=task_id,
                    target="ready",
                    # The reason of a return to Ready is what the next attempt is given as the person's reply.
                    reason=text,
                    user_id=owner,
                    accepted_by=user_id,
                    expected_updated_at=value["updated_at"],
                    # Seconds cannot tell two writes in one second apart. The stage and the run can.
                    expected_status=status,
                    expected_job_id=answered,
                    **executor,
                )
            if record is None:
                attached = " The context was attached." if context else ""
                return f"Not sent: '{title}' changed while the message was being sent.{attached} Read it again."
            link_task(_agno_run_context, record)
            # Only the attempt that follows this return carries the message as its reply.
            attempt = task_next_attempt(record)
            try:
                queued, receipt = await self._queue(
                    agent_os, app, authority, user_id, _agno_run_context, task_id, attempt
                )
            except Exception as exc:
                queued, receipt = False, f"Not started: {exc}"
            if queued:
                return f"Sent the message to '{title}' as attempt {attempt}, in the Task's own session. {receipt}"
            now = await _call(starter.db, "get_task", task_id) or {}
            if now.get("status") == "ready":
                then = "It is Ready: start it with start_company_task and the message goes with it."
            else:
                then = f"It is now {TASK_STATUS_MEANING.get(str(now.get('status')), now.get('status'))}."
            return f"The message is recorded on '{title}' (Task {task_id}), but its run did not start. {receipt} {then}"

        return await self._decide(call)

    def get_company_task_status(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Company Task's saved state, latest run and recorded evidence without waiting for it.

        Args:
            task_id: The Task to inspect.
        """
        return "Reading Task status needs an asynchronous run. Open the Task in AgentOS instead."

    async def aget_company_task_status(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Company Task's saved state, latest run and recorded evidence without waiting for it.

        Reports what is recorded: the Task status, the latest attempt and its run, the reviewer's
        feedback when it was sent back, the saved result, and the commands and tools the worker
        actually ran, read from the run. Report that evidence, and say when there is none. A finished run is not proof
        the outcome was achieved.

        Args:
            task_id: The Task to inspect.
        """
        from fastapi import HTTPException

        from agno.os.routers.company.runs import _task_state, _TaskStarter

        agent_os = self._agent_os()
        if agent_os is None:
            return "Company is not running here."
        authority, _ = _run_context_identity(_agno_run_context)
        try:
            if authority is not None:
                await authority.arequire("tasks", "read")
            starter = _TaskStarter(agent_os)
            value = await starter.task(task_id)
        except PermissionError as exc:
            return f"Cannot read the Task: {exc}"
        except HTTPException as exc:
            return f"Cannot read the Task: {exc.detail}"
        app = getattr(agent_os, "_company_app", None)
        state = await starter.state(value, app) if app is not None else _task_state(value)
        state.update(await starter.run_evidence(value))
        return json.dumps(state, ensure_ascii=False, default=str)

    def _person(self, agent_os: Any, run_context: Any, operation: str = "decide Company work") -> Any:
        """The chatting person's authority and identity. Raises PermissionError for every other caller."""
        from agno.tools.company import _require_human_creation

        _require_human_creation(run_context, operation)
        authority, user_id = _run_context_identity(run_context)
        if _unsigned(agent_os, authority, user_id):
            raise PermissionError(f"A signed-in person is required to {operation}")
        return authority, user_id

    def _routine_request(self, agent_os: Any, authority: Any, user_id: Any, method: str, routine_id: str) -> Any:
        """A Routine API request from the chatting person, as the API's middleware would describe it."""
        from agno.company.routines import _person_routine_request

        return _person_routine_request(agent_os, authority, user_id, method, routine_id)

    async def _named_routine(
        self, agent_os: Any, authority: Any, user_id: Any, routine_id: str, routine_name: str, goal_name: Any
    ) -> Any:
        """Check that the names the person confirmed are the stored Routine's and its Goal's.

        The person's permissions are checked before anything is read, and the Routine is read as the
        Routine API reads it, so a refusal names nothing the API would not show this person.
        Returns the Routine's name and its stored payload.
        """
        from fastapi import HTTPException

        from agno.company.execution import _call

        request = self._routine_request(agent_os, authority, user_id, "GET", routine_id)
        if authority is not None:
            await authority.arequire("routines", "write")
            if goal_name is not None:
                await authority.arequire("goals", "read")
        try:
            row = await agent_os._routine_api_read(routine_id, request)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise LookupError("Routine not found") from exc
            raise
        metadata = row["payload"]["metadata"]
        stored = row["name"].removeprefix(metadata["goal_id"] + ".")
        # Its schedule is stored under the Goal's ID and this name; a listing may show either.
        if not (_same_name(routine_name, stored) or _same_name(routine_name, row["name"])):
            raise ValueError(f"Routine {routine_id} is named '{stored}'. Call again with that name.")
        if goal_name is not None:
            goal = await _call(agent_os._company_db, "get_goal", metadata["goal_id"])
            if goal is None:
                raise LookupError("The Routine's Goal was not found")
            if not _same_name(goal_name, goal["name"]):
                raise ValueError(f"Routine '{stored}' belongs to Goal '{goal['name']}'. Call again with that name.")
        return stored, row["payload"]

    async def _patch_routine(
        self, agent_os: Any, authority: Any, user_id: Any, routine_id: str, auto_accept: Any
    ) -> Any:
        """Change a Routine's auto_accept through the Routine API's own PATCH handler, as the chatting person."""
        from agno.company.routines import _set_auto_accept_as

        return await _set_auto_accept_as(agent_os, authority, user_id, routine_id, auto_accept)

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
        self, project_name: str, project_id: str, updated_at: _OptionalInt, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Approve a proposed Company Project. The run pauses for the person to confirm.

        Args:
            project_name: The Project's name, as stored.
            project_id: The proposed Project to approve.
            updated_at: The Project's updated_at as the person saw it; null when it has none.
        """
        return "Approving a Project needs an asynchronous run. Approve it from AgentOS instead."

    async def aapprove_company_project(
        self, project_name: str, project_id: str, updated_at: _OptionalInt, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Approve a proposed Company Project. It becomes active. The run pauses for the person to
        confirm the Project by name, ID and version.

        Call this only when the person asked, in this conversation, to approve this Project. A request
        to plan, list or summarize work is not a request to approve it. The person who confirms is
        recorded as the one who approved.

        Args:
            project_name: The Project's name, as stored. The person confirms this name.
            project_id: The proposed Project to approve.
            updated_at: The Project's updated_at as the person saw it; null when it has none. A Project
                edited after that is not approved: show it again first.
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
            if not _same_version(updated_at, project):
                return (
                    f"Not done: '{project['name']}' (Project {project_id}) changed since the person saw it. "
                    "Show it to them again, then call with its updated_at."
                )
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
        tasks: List[TaskToAccept],
        executor_type: _OptionalString,
        executor_id: _OptionalString,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Accept Backlog Company Tasks with one executor. The run pauses for the person to confirm.

        Args:
            tasks: The Tasks to accept, each as {"title": the stored title, "task_id": the id,
                "updated_at": the Task's updated_at as the person saw it, null when it has none}.
            executor_type: agent, team or workflow.
            executor_id: ID of that component.
        """
        return "Accepting a Task needs an asynchronous run. Accept it from AgentOS instead."

    async def aaccept_company_task(
        self,
        tasks: List[TaskToAccept],
        executor_type: _OptionalString,
        executor_id: _OptionalString,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Accept Backlog Company Tasks with one executor. They become Ready. The run pauses for the
        person to confirm each Task by title, ID and version, and the executor.

        Call this only when the person asked, in this conversation, to accept these Tasks. A request to
        plan, list or summarize work is not a request to accept it. Pass every Task the person named in
        one call, so they confirm once. Each Task's Project must be active. Name the executor the person
        named. With none named, pass the executor the Task's proposal suggests, which is the Task's own
        executor_type and executor_id. When it suggests none, pass agent and miniagent: Mini Agent does
        the work itself or runs the components the person may run. Tasks that take different executors
        need one call each. Accepting does not start a Task; use start_company_task when the person asks.

        Args:
            tasks: The Tasks to accept, each as {"title": the stored title, "task_id": the id,
                "updated_at": the Task's updated_at as the person saw it, null when it has none}. A Task
                edited after that is not accepted: show it again first.
            executor_type: agent, team or workflow.
            executor_id: ID of that component.
        """
        from dataclasses import replace

        from agno.company.routines import _manager_call
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter
        from agno.registry._reserved import MINI_AGENT_ID
        from agno.run.authorization import authorization_scope

        async def call(agent_os: Any) -> str:
            from fastapi import HTTPException

            authority, user_id = self._person(agent_os, _agno_run_context)
            kind, name = _named(executor_type), _named(executor_id)
            if kind is not None and kind not in ("agent", "team", "workflow"):
                return "Not done: executor_type is agent, team or workflow."
            if not tasks:
                return "Not done: name at least one Task."
            named = [item if isinstance(item, TaskToAccept) else TaskToAccept.model_validate(item) for item in tasks]
            if authority is not None:
                await authority.arequire("tasks", "write")
            starter = _TaskStarter(agent_os)
            # Nothing is accepted unless every Task is the version the person confirmed, and still a proposal.
            values = []
            for item in named:
                value = await starter.task(item.task_id)
                title = value.get("title") or value["id"]
                if not _same_name(item.title, title):
                    return f"Not done: Task {value['id']} is titled '{title}'. Call again with that title."
                if value["status"] != "backlog":
                    words = TASK_STATUS_MEANING.get(value["status"], value["status"])
                    return f"Not done: '{title}' is {words}; only a proposal can be accepted."
                if not _same_version(item.updated_at, value):
                    return (
                        f"Not done: '{title}' (Task {value['id']}) changed since the person saw it. "
                        "Show it to them again, then call with its updated_at."
                    )
                values.append(value)
            if kind is None or name is None:
                # The person confirms the executor, so the call names it.
                suggested = [
                    f"'{value.get('title') or value['id']}' suggests "
                    + (f"{value['executor_type']} {value['executor_id']}" if value.get("executor_id") else "none")
                    for value in values
                ]
                return (
                    "Not done: the call names no executor, and the person confirms the executor. Call again with "
                    f"the executor the Task suggests, or agent {MINI_AGENT_ID} when it suggests none: "
                    + "; ".join(suggested)
                    + "."
                )
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
                        link_task(_agno_run_context, record)
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
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Complete a Company Task in review, or send it back. The run pauses for the person to confirm.

        Args:
            task_title: The Task's title, as stored.
            outcome: complete or send_back.
            reason: The person's reason, in their words.
            task_id: The Task in review.
            reviewed_run_id: The run_id returned by get_company_task_status for the result being reviewed.
            executor_type: Null. Pass agent only to send back a Task that names no executor.
            executor_id: Null. Pass miniagent only to send back a Task that names no executor.
        """
        return "Reviewing a Task needs an asynchronous run. Review it from AgentOS instead."

    async def areview_company_task(
        self,
        task_title: str,
        outcome: str,
        reason: str,
        task_id: str,
        reviewed_run_id: str,
        executor_type: _OptionalString = None,
        executor_id: _OptionalString = None,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Complete a Company Task in review, or send it back. The run pauses for the person to confirm
        the Task by title and ID, the reviewed run, the outcome and the reason.

        Call this only when the person asked, in this conversation, to complete this Task or send it
        back. Show them the saved result first when they have not seen it. complete moves the Task to
        Done. send_back returns it to Ready with the same executor; the reason is given to the executor
        on its next attempt, which starts when the person asks, with start_company_task. A Task that
        names no executor is sent back to Mini Agent: pass agent and miniagent, so the person confirms it.

        Args:
            task_title: The Task's title, as stored. The person confirms this title.
            outcome: complete or send_back.
            reason: The person's reason, in their words. Required to send a Task back.
            task_id: The Task in review.
            reviewed_run_id: The run_id returned by get_company_task_status for the result being reviewed.
            executor_type: Null. Pass agent only to send back a Task that names no executor.
            executor_id: Null. Pass miniagent only to send back a Task that names no executor.
        """
        from dataclasses import replace

        from agno.company.routines import _manager_call
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter
        from agno.registry._reserved import MINI_AGENT_ID
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
                words = TASK_STATUS_MEANING.get(value["status"], value["status"])
                return f"'{title}' is {words}; only a Task in review can be completed or sent back."
            if not reviewed_run_id or value.get("job_id") != reviewed_run_id:
                return "Not done: the Task's attempt changed. Read its latest result and request a new confirmation."
            executor: Dict[str, Any] = {}
            if outcome == "send_back":
                # A return to Ready is a fresh acceptance of the same executor, or of Mini Agent when the
                # Task names none. The person confirms the executor, so the call names Mini Agent.
                kept = (value.get("executor_type"), value.get("executor_id"))
                named = (_named(executor_type), _named(executor_id))
                if kept[1] is None:
                    kept = ("agent", MINI_AGENT_ID)
                    if named != kept:
                        return (
                            f"Not done: '{title}' names no executor, and the person confirms the executor. "
                            f"Call again with executor_type agent and executor_id {MINI_AGENT_ID}."
                        )
                elif named not in ((None, None), kept):
                    return (
                        f"Not done: send_back returns '{title}' to its executor, {kept[0]} {kept[1]}. "
                        "Call again with no executor."
                    )
                executor = {"executor_type": kept[0], "executor_id": kept[1]}
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
            link_task(_agno_run_context, record, add=False)
            if outcome == "complete":
                return f"Completed '{title}' (Task {task_id}). It is Done."
            return (
                f"Sent '{title}' (Task {task_id}) back to Ready for {executor['executor_type']} "
                f"{executor['executor_id']}. It is not started."
            )

        return await self._decide(call)

    def turn_on_routine_auto_accept(
        self,
        routine_name: str,
        goal_name: str,
        default_executor: _OptionalString,
        kept_policy: _OptionalString,
        routine_id: str,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Turn auto-accept on for a Company Routine. The run pauses for the person to confirm.

        Args:
            routine_name: The Routine's name, as stored.
            goal_name: The name of the Routine's Goal, as stored.
            default_executor: ID of the agent, team or workflow. Null unless the person names one.
            kept_policy: Null, unless the Routine already has a policy a person set.
            routine_id: The Routine.
        """
        return "Turning auto-accept on needs an asynchronous run. Change the Routine from AgentOS instead."

    async def aturn_on_routine_auto_accept(
        self,
        routine_name: str,
        goal_name: str,
        default_executor: _OptionalString,
        kept_policy: _OptionalString,
        routine_id: str,
        _agno_run_context: Optional[Any] = None,
    ) -> str:
        """Turn auto-accept on for a Company Routine. The run pauses for the person to confirm the
        Routine by name, its Goal by name, the default executor, and the policy that is kept.

        With auto-accept on, the Projects this Routine proposes are approved and its Tasks are accepted
        and run with no person, and finished work waits In review. A Task runs on the executor its
        proposal suggests, or on the default executor when it suggests none. Call this only when the
        person asked to turn auto-accept on for this Routine.

        A Routine that already has a policy keeps it: one its code declares, or one a person set. Only
        its default executor changes, and only when the person names one. From then on the Routine and
        its policy run under this person's permissions.

        Args:
            routine_name: The Routine's name, as stored. The person confirms this name.
            goal_name: The name of the Routine's Goal, as stored. The person confirms this name.
            default_executor: ID of the agent, team or workflow that runs a Task whose proposal
                suggests no executor. Null unless the person names one: the Routine's policy is then
                kept as it is, or Mini Agent is used when it has none.
            kept_policy: Null, unless the Routine already has a policy a person set. Then that policy
                on one line, as this tool gives it when it is left out, so the person confirms what is kept.
            routine_id: The Routine.
        """
        from agno.company.declarations import AutoAccept
        from agno.company.routines import _DECLARED, _stored_policy

        async def call(agent_os: Any) -> str:
            authority, user_id = self._person(agent_os, _agno_run_context, "turn a Routine's auto-accept on")
            stored, payload = await self._named_routine(
                agent_os, authority, user_id, routine_id, routine_name, goal_name
            )
            # A Routine that has a policy keeps it. The defaults are for a Routine with none.
            raw = payload["metadata"].get("auto_accept")
            kept = _stored_policy(raw)[0] if raw else None
            declared = kept is not None and payload.get("_agno_company_acceptance") == _DECLARED
            line = _policy_line(kept) if kept is not None else None
            # A policy a person set is shown on the confirmation before it is kept under this person's
            # name. What the confirmation shows is always the stored policy.
            shown = (_named(kept_policy) or "").strip() or None
            if not (_same_name(shown, line) if shown is not None else line is None or declared):
                if line is None:
                    return f"Not done: Routine '{stored}' has no policy to keep. Call again with kept_policy null."
                return (
                    f"Not done: Routine '{stored}' already has a policy, and the person confirms the policy that "
                    f"is kept. Call again with kept_policy set to this line: {line}"
                )
            policy = AutoAccept.model_validate(
                {
                    **(kept.model_dump() if kept else {}),
                    **({"default_executor": default_executor} if _named(default_executor) else {}),
                }
            )
            await self._patch_routine(agent_os, authority, user_id, routine_id, policy)
            projects = (
                "Its Projects are approved and its"
                if policy.approve_projects
                else "A person approves its Projects. Its"
            )
            listed = f" from {', '.join(policy.executors)}" if policy.executors else ""
            bound = (
                f"At most {policy.max_open} of its Tasks are open at once."
                if policy.limits is None
                else f"It accepts at most {policy.limits.max_acceptances} Tasks."
            )
            source = (
                ", with the policy its code declares"
                if declared
                else ", with the policy it already had"
                if kept
                else ""
            )
            return (
                f"Auto-accept is on for Routine '{stored}' ({routine_id}){source}. {projects} Tasks are accepted and "
                f"run on {policy.default_executor}, unless a proposal names another executor{listed}. "
                f"Finished work waits In review. {bound}"
            )

        return await self._decide(call)

    def turn_off_routine_auto_accept(
        self, routine_name: str, routine_id: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Turn auto-accept off for a Company Routine.

        Args:
            routine_name: The Routine's name, as stored.
            routine_id: The Routine.
        """
        return "Turning auto-accept off needs an asynchronous run. Change the Routine from AgentOS instead."

    async def aturn_off_routine_auto_accept(
        self, routine_name: str, routine_id: str, _agno_run_context: Optional[Any] = None
    ) -> str:
        """Turn auto-accept off for a Company Routine. Its proposals then wait for a person.

        Call this when the person asked to turn auto-accept off for this Routine. Work it accepted
        that has not started returns to Backlog.

        Args:
            routine_name: The Routine's name, as stored.
            routine_id: The Routine.
        """

        async def call(agent_os: Any) -> str:
            authority, user_id = self._person(agent_os, _agno_run_context, "turn a Routine's auto-accept off")
            stored, _ = await self._named_routine(agent_os, authority, user_id, routine_id, routine_name, None)
            await self._patch_routine(agent_os, authority, user_id, routine_id, False)
            return f"Auto-accept is off for Routine '{stored}' ({routine_id}). Its proposals now wait for a person."

        return await self._decide(call)


def _receipt(verb: str, title: str, task_id: str, response: Any) -> str:
    body = json.loads(bytes(response.body)) if response.body else {}
    if response.status_code != 202:
        return f"Not {verb.lower()}: {body.get('detail') or 'the run was refused'}"
    status = body.get("status")
    run = f"(Task {task_id}, run {body.get('run_id')})"
    if status in ("PENDING", "QUEUED", None):
        return f"{verb} '{title}' {run}. It runs in its own session and is not done; its state is shown to you on the next turn."
    if status == "RUNNING":
        return f"'{title}' is already running {run}."
    return f"'{title}' already has this attempt, now {status} {run}."


for _tool in (CompanyTaskTools.aadd_company_task, CompanyTaskTools.amessage_company_task):
    _tool.__doc__ = (_tool.__doc__ or "").replace("CONTEXT_KINDS", _CONTEXT_KINDS)
