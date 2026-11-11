"""Super Agent tools to start or continue Company Tasks and read their state without waiting.

Starting and continuing reuse the Company routes' checks, duplicate handling and queue path,
under the calling user's own authority. No tool accepts work: a person accepts a Task with an
executor first, through AgentOS or the API.
"""

import json
from typing import Any, Dict, Optional, Tuple
from weakref import ReferenceType, ref

from agno.company.details import _remember_task
from agno.tools import Toolkit


def _run_context_identity(run_context: Any):
    from agno.tools.company import _authority, _identity

    return _authority(run_context), _identity(run_context)


def _refusal(authority: Any) -> Optional[str]:
    from agno.company.execution import _automatic_task, _ExecutorAuthorization
    from agno.company.routines import _RoutineAuthorization

    if isinstance(authority, (_RoutineAuthorization, _ExecutorAuthorization)) or _automatic_task.get() is not None:
        return "Task runs are started by people. Automated runs cannot start or continue Tasks."
    return None


def _requested_from(run_context: Any) -> Dict[str, str]:
    conversation = {
        "session_id": getattr(run_context, "session_id", None),
        "run_id": getattr(run_context, "run_id", None),
        "team_id": "superagent",
    }
    return {key: item for key, item in conversation.items() if isinstance(item, str)}


class CompanyTaskTools(Toolkit):
    """Start an accepted Task in the background, continue it from a reply, and check on it."""

    def __init__(self, agent_os: Any):
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        super().__init__(
            name="company_tasks",
            tools=[self.start_company_task, self.continue_company_task, self.get_company_task_status],
            async_tools=[
                (self.astart_company_task, "start_company_task"),
                (self.acontinue_company_task, "continue_company_task"),
                (self.aget_company_task_status, "get_company_task_status"),
            ],
            # The receipt is the reply: the coordinator turn ends once the run is queued.
            stop_after_tool_call_tools=["start_company_task", "continue_company_task"],
            show_result_tools=["start_company_task", "continue_company_task"],
        )

    def _caller_context(self, run_context: Any) -> Tuple[Any, Any, Any, Optional[str], Optional[str]]:
        """The OS, its app, the caller's authority and identity, and a refusal when they cannot act."""
        agent_os = self._agent_os()
        app = getattr(agent_os, "_company_app", None)
        authority, user_id = _run_context_identity(run_context)
        if agent_os is None or app is None:
            return agent_os, app, authority, user_id, "Company execution is not running here. Use AgentOS instead."
        refusal = _refusal(authority)
        if refusal is None and getattr(agent_os, "user_isolation", False) and not user_id:
            refusal = "A signed-in person is required."
        return agent_os, app, authority, user_id, refusal

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
        from agno.os.routers.company.runs import _STATUS_MEANING, _StartCaller, _TaskStarter

        agent_os, app, authority, user_id, refusal = self._caller_context(_agno_run_context)
        if refusal is not None:
            return refusal
        starter = _TaskStarter(agent_os)
        try:
            value = await starter.task(task_id)
            title = value.get("title") or task_id
            if value["status"] == "backlog":
                return f"'{title}' is still a proposal. A person must accept it with an executor before it can start."
            if value["status"] == "in_review":
                return f"'{title}' is waiting for review. Continue it with the person's reply instead of starting it."
            if value["status"] != "ready" and _pending_task_attempt(value) is None:
                meaning = _STATUS_MEANING.get(value["status"], value["status"])
                return f"'{title}' is {meaning}; only accepted work can start."
            if authority is not None:
                # The start route's own requirements, beyond running the executor.
                await authority.arequire("tasks", "write")
                await authority.arequire("wiki", "read")
            caller = _StartCaller.for_authority(app, authority, user_id, _requested_from(_agno_run_context))
            response = await starter.submit(task_id, caller, None, value, None)
        except PermissionError as exc:
            return f"Not started: {exc}"
        except HTTPException as exc:
            return f"Not started: {exc.detail}"
        except (_TaskRunConflict, _TaskRunUnavailable) as exc:
            return f"Not started: {exc}"
        if response.status_code == 202:
            _remember_task(_agno_run_context, task_id)
        return _receipt("Queued", title, task_id, response)

    def continue_company_task(self, task_id: str, message: str, _agno_run_context: Optional[Any] = None) -> str:
        """Continue a Company Task from a person's reply to its latest attempt.

        Args:
            task_id: The Task to continue.
            message: The person's reply in their own words: an answer, a decision or a revised instruction.
        """
        return "Continuing a Task needs an asynchronous run. Reply from AgentOS instead."

    async def acontinue_company_task(self, task_id: str, message: str, _agno_run_context: Optional[Any] = None) -> str:
        """Continue a Company Task from a person's reply to its latest attempt.

        Use this when a person answers a Task's question, decides between its options or revises
        its instruction after it finished. The next attempt runs on the same worker session with
        the reply and the previous result. Pass the person's words; do not answer for them. Call
        this tool on its own, then tell the person the Task continues.

        Args:
            task_id: The Task to continue.
            message: The person's reply in their own words: an answer, a decision or a revised instruction.
        """
        from fastapi import HTTPException

        from agno.company.execution import _TaskRunConflict, _TaskRunUnavailable
        from agno.os.routers.company.runs import _StartCaller, _TaskStarter

        agent_os, app, authority, user_id, refusal = self._caller_context(_agno_run_context)
        if refusal is not None:
            return refusal
        starter = _TaskStarter(agent_os)
        try:
            value = await starter.task(task_id)
            title = value.get("title") or task_id
            if authority is not None:
                await authority.arequire("tasks", "write")
                await authority.arequire("wiki", "read")
            caller = _StartCaller.for_authority(app, authority, user_id, _requested_from(_agno_run_context))
            response = await starter.continue_task(task_id, caller, message)
        except PermissionError as exc:
            return f"Not continued: {exc}"
        except HTTPException as exc:
            return f"Not continued: {exc.detail}"
        except (_TaskRunConflict, _TaskRunUnavailable) as exc:
            return f"Not continued: {exc}"
        if response.status_code == 202:
            _remember_task(_agno_run_context, task_id)
        return _receipt("Continued", title, task_id, response)

    def get_company_task_status(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Company Task's saved state, latest run and recorded evidence without waiting for it.

        Args:
            task_id: The Task to inspect.
        """
        return "Reading Task status needs an asynchronous run. Open the Task in AgentOS instead."

    async def aget_company_task_status(self, task_id: str, _agno_run_context: Optional[Any] = None) -> str:
        """Read a Company Task's saved state, latest run and recorded evidence without waiting for it.

        Reports what is recorded: the Task status, the latest attempt and its run, the reply it
        continues from, and the saved result with the commands and tools the worker actually ran.
        Report the recorded evidence, and say when there is none. A finished run is not proof the
        outcome was achieved.

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
        return json.dumps(state, ensure_ascii=False, default=str)


def _receipt(verb: str, title: str, task_id: str, response: Any) -> str:
    body = json.loads(bytes(response.body)) if response.body else {}
    if response.status_code != 202:
        return f"Not {verb.lower()}: {body.get('detail') or 'the run was refused'}"
    status = body.get("status")
    run = f"(Task {task_id}, run {body.get('run_id')})"
    if status in ("PENDING", "QUEUED", None):
        return f"{verb} '{title}' {run}. It runs in its own session; ask for its status at any time."
    if status == "RUNNING":
        return f"'{title}' is already running {run}."
    return f"'{title}' already has this attempt, now {status} {run}."
