"""Super Agent tools to start accepted Company Tasks and read their state without waiting.

Starting reuses the Company start route's checks, duplicate handling and queue path, under
the calling user's own authority. Neither tool accepts work: a person accepts a Task with
an executor first, through AgentOS or the API.
"""

import json
from typing import Any, Dict, Optional
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


def _refusal(authority: Any) -> Optional[str]:
    from agno.company.execution import _automatic_task, _ExecutorAuthorization
    from agno.company.routines import _RoutineAuthorization

    if isinstance(authority, (_RoutineAuthorization, _ExecutorAuthorization)) or _automatic_task.get() is not None:
        return "Task runs are started by people. Automated runs cannot start Tasks."
    return None


class CompanyTaskTools(Toolkit):
    """Start an accepted Task in the background and check on it later."""

    def __init__(self, agent_os: Any):
        self._agent_os: ReferenceType[Any] = ref(agent_os)
        super().__init__(
            name="company_tasks",
            tools=[self.start_company_task, self.get_company_task_status],
            async_tools=[
                (self.astart_company_task, "start_company_task"),
                (self.aget_company_task_status, "get_company_task_status"),
            ],
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
                return f"'{title}' is waiting for review. A person starts a revision from the Task."
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
        return json.dumps(state, ensure_ascii=False, default=str)
