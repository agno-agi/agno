"""Company schedule payloads and bundled Skills; the scheduler owns execution."""

import asyncio
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.company.declarations import Routine
from agno.company.execution import _call, _ExecutorAuthorization, _registered_component, _validate_executor_tools
from agno.company.scheduler import CompanyScheduleExecutor
from agno.db.schemas.scheduler import COMPANY_AUTOMATION_SCHEDULE_ID, RUN_ENDPOINT_RE
from agno.db.schemas.tasks import OPEN_TASK_STATUSES, CancelledProjectError, OpenTaskLimitError
from agno.guardrails.base import BaseGuardrail
from agno.skills import LocalSkills, Skills


def load_routine_skills() -> Skills:
    """Load the editable, packaged Routine templates through the standard loader."""
    return Skills(loaders=[LocalSkills(str(Path(__file__).parent / "skills"))])


async def aload_routine_skills() -> Skills:
    """Load templates without blocking the event loop."""
    return await asyncio.to_thread(load_routine_skills)


def _routine_message(product_id: str, instructions: str) -> str:
    # Run metadata is not automatically visible in the model's messages.
    import json

    return "Operate only on Product " + json.dumps(product_id) + ".\n\n" + instructions


def _recovered_status_conflict(tool: Dict[str, Any], later_tools: List[Dict[str, Any]]) -> bool:
    """Only a later confirmed write to the same Product can recover a status conflict."""
    import json
    import re

    # Persisted tool errors carry text, not the original VersionConflictError.
    # Recognize only the filesystem's conflict messages; permission errors stay fatal.
    result = tool.get("result")
    if not isinstance(result, str) or not (
        re.fullmatch(r"version conflict on status\.md: expected \d+, actual (?:\d+|None)", result)
        or result == "file already exists: status.md"
    ):
        return False
    product_id = (tool.get("tool_args") or {}).get("product_id")
    if not product_id:
        return False
    for later in later_tools:
        args = later.get("tool_args") or {}
        if (
            later.get("tool_name") != "update_product_status"
            or later.get("tool_call_error")
            or args.get("product_id") != product_id
            or not isinstance(args.get("expected_version"), int)
        ):
            continue
        try:
            metadata = json.loads(later.get("result") or "")
        except (ValueError, TypeError):
            continue
        if (
            isinstance(metadata, dict)
            and metadata.get("path") == "status.md"
            and metadata.get("version") == args["expected_version"] + 1
        ):
            return True
    return False


def _routine_failure(output: Any) -> Optional[str]:
    """Read structured execution results, never infer success from model prose."""
    if hasattr(output, "to_dict"):
        output = output.to_dict()
    if isinstance(output, list):
        for child in output:
            error = _routine_failure(child)
            if error:
                return error
    elif isinstance(output, dict):
        tools = output.get("tools") or []
        for index, tool in enumerate(tools):
            if tool.get("tool_call_error") and tool.get("tool_name") in {
                "create_company_product",
                "create_product_routine",
                "add_product_source",
                "read_product_source",
                "intake_product_source",
                "propose_company_task",
                "update_product_status",
                "write_company_file",
                "summarize_company_product",
                "refresh_company_product",
            }:
                if tool["tool_name"] == "update_product_status" and _recovered_status_conflict(
                    tool, tools[index + 1 :]
                ):
                    continue
                return str(tool["tool_name"]) + " failed: " + str(tool.get("result") or "Company operation failed")
            if tool.get("tool_name") in {"run_agent", "run_team", "run_workflow"}:
                # Studio dispatch returns a structured child result rather than
                # adding it to native Team member_responses.
                import json

                result = tool.get("result")
                if isinstance(result, str):
                    try:
                        result = json.loads(result)
                    except (ValueError, TypeError):
                        result = None
                if tool.get("tool_call_error") or (
                    isinstance(result, dict)
                    and (
                        result.get("error") or str(result.get("status", "")).upper() in {"ERROR", "FAILED", "CANCELLED"}
                    )
                ):
                    return str(tool["tool_name"]) + " failed: " + str(result or "Routine delegation failed")
        # A call past the run's tool call limit is answered with an error and never run, and the run
        # still completes. A Routine that was cut off did not finish its work.
        skipped = [
            str(message.get("tool_name"))
            for message in output.get("messages") or []
            if message.get("role") == "tool"
            and message.get("tool_call_error")
            and not message.get("from_history")
            and str(message.get("content") or "").startswith("Tool call limit reached.")
        ]
        if skipped:
            return (
                f"Routine incomplete: it stopped at its limit of {len(tools)} tool calls before it finished. "
                f"Not run: {', '.join(dict.fromkeys(skipped))}. What it did before the limit is saved."
            )
        if output.get("success") is False:
            return str(output.get("error") or "Routine step failed")
        for key in ("member_responses", "step_results", "steps"):
            error = _routine_failure(output.get(key))
            if error:
                return error
        # Native delegation can return a failed child as a successful tool call.
        # Its structured terminal status remains authoritative even without tools.
        status = str(output.get("status", "")).upper()
        if status in {"ERROR", "FAILED", "CANCELLED"}:
            return str(output.get("error") or output.get("content") or "Routine execution failed with status " + status)
    return None


class _RoutineResultGuardrail(BaseGuardrail):
    """Use the runtime's blocking output-check path for failed Company operations."""

    def check(self, run_input: Any = None, run_output: Any = None) -> None:
        from agno.exceptions import OutputCheckError
        from agno.run.authorization import current_authorization

        if isinstance(current_authorization(), _RoutineAuthorization):
            error = _routine_failure(run_output)
            if error:
                run_output.content = error
                raise OutputCheckError(error)

    async def async_check(self, run_input: Any = None, run_output: Any = None) -> None:
        self.check(run_input, run_output)


def _run_kind(run_context: Any = None) -> Optional[str]:
    """ "routine" for a Routine run, "task" for a run that executes an accepted Task, None for every other run."""
    from agno.run.authorization import current_authorization

    authority = current_authorization() or getattr(run_context, "authorization", None)
    if isinstance(authority, _RoutineAuthorization):
        return "routine"
    if isinstance(authority, _ExecutorAuthorization) and authority.task_id:
        return "task"
    return None


class _RoutineBoundary(BaseGuardrail):
    """Keep unattended Company runs on Mini Agent, and every other run off it.

    A Routine runs on untrusted Sources with proposal-only authority. With routine=True the component
    accepts only Routine runs and runs that execute an accepted Task. With routine=False it refuses
    Routine runs.
    """

    def __init__(self, routine: bool):
        self.routine = routine

    def check(self, run_input: Any = None) -> None:
        from agno.exceptions import InputCheckError

        kind = _run_kind()
        if self.routine and kind is None:
            raise InputCheckError("Mini Agent runs Company Routines and Tasks only")
        if not self.routine and kind == "routine":
            raise InputCheckError("Company Routines run on Mini Agent")

    async def async_check(self, run_input: Any = None) -> None:
        self.check(run_input)


def _failed_routines(db: Any, products: Any) -> int:
    from agno.scheduler import ScheduleManager

    schedules = ScheduleManager(db)
    failed = 0
    for product in products:
        for routine_id in (product.get("metadata") or {}).get("routine_ids", []):
            schedule = schedules.get(routine_id)
            # Archived Routines are hidden from counts.
            if (
                schedule is None
                or schedule.managed_by != "company"
                or (schedule.payload or {}).get("metadata", {}).get("deleted_at") is not None
            ):
                continue
            runs = schedules.get_runs(routine_id, limit=1)
            failed += bool(runs and runs[0].status == "failed")
    return failed


async def _afailed_routines(db: Any, products: Any) -> int:
    from agno.scheduler import ScheduleManager

    schedules = ScheduleManager(db)
    failed = 0
    for product in products:
        for routine_id in (product.get("metadata") or {}).get("routine_ids", []):
            schedule = await schedules.aget(routine_id)
            # Archived Routines are hidden from counts.
            if (
                schedule is None
                or schedule.managed_by != "company"
                or (schedule.payload or {}).get("metadata", {}).get("deleted_at") is not None
            ):
                continue
            runs = await schedules.aget_runs(routine_id, limit=1)
            failed += bool(runs and runs[0].status == "failed")
    return failed


def _routine_executor_endpoint(executor_type: str, executor_id: str, registry: Any, *, agent_os: Any = None) -> str:
    from agno.registry._reserved import MINI_AGENT_ID, RESERVED_MANAGER_IDS

    if executor_id == MINI_AGENT_ID:
        if executor_type != "agent":
            raise ValueError("Mini Agent Routine executor_type must be 'agent'")
        component = getattr(agent_os, "_mini_agent", None)
        if component is None:
            reason = getattr(agent_os, "_mini_agent_unavailable_reason", None)
            raise ValueError(reason or "Mini Agent unavailable: configure CompanyConfig on the owning AgentOS")
    elif executor_id in RESERVED_MANAGER_IDS:
        # Super Agent and Platform Builder can edit the platform; Routines run unattended on untrusted Sources.
        raise ValueError(
            f"Among framework agents, only Mini Agent runs Routines: name agent '{MINI_AGENT_ID}' or leave the executor out"
        )
    else:
        component = _registered_component(registry, executor_type, executor_id)
        if component is None:
            raise ValueError("Routine executor is missing from the registry")
    _validate_executor_tools(component)
    endpoint = f"/{executor_type}s/{executor_id}/runs"
    if RUN_ENDPOINT_RE.fullmatch(endpoint) is None:
        raise ValueError("Invalid Routine executor id")
    return endpoint


def _schedule_fields(product_id: str, routine: Routine, registry: Any, *, agent_os: Any = None) -> Dict[str, Any]:
    endpoint = _routine_executor_endpoint(routine.executor_type, routine.executor_id, registry, agent_os=agent_os)
    instructions = routine.instructions
    if instructions is None and routine.template is not None:
        skill = load_routine_skills().get_skill(routine.template)
        if skill is None:
            raise ValueError("Routine template is unavailable")
        instructions = skill.instructions
    if not instructions or not instructions.strip():
        raise ValueError("Routine instructions are required")
    fields = dict(
        name=product_id + "." + routine.name,
        cron_expr=routine.cron_expr or "",
        endpoint=endpoint,
        timezone=routine.timezone,
        payload={
            "message": _routine_message(product_id, instructions),
            "metadata": {"product_id": product_id, "template": routine.template, "auto_accept": False},
        },
    )

    # Reuse scheduler validation for the composed identity on every creation path.
    from agno.os.routers.schedules.schema import ScheduleCreate

    ScheduleCreate.model_validate(fields)
    return fields


# The grant of a policy declared in code or YAML. Only the startup declaration path writes it.
_DECLARED = {"declared": True}


def _executor_kind(registry: Any, executor_id: str) -> str:
    """The kind of the one registered component with this id. A policy names executors by id only.

    Studio components cannot share an id across kinds. Code-defined ones can, and such an id is
    refused here: the kind is never guessed.
    """
    from agno.registry._reserved import MINI_AGENT_ID

    if executor_id == MINI_AGENT_ID:
        return "agent"
    kinds = []
    for kind in ("agent", "team", "workflow"):
        try:
            if _registered_component(registry, kind, executor_id) is not None:
                kinds.append(kind)
        except ValueError:
            continue
    if len(kinds) > 1:
        raise ValueError(f"Executor ID '{executor_id}' is shared by {' and '.join(kinds)}. Give each its own ID")
    if not kinds:
        raise ValueError(f"Executor '{executor_id}' is not a registered agent, team or workflow")
    return kinds[0]


def _require_sent_executor_type(registry: Any, policy: Any) -> None:
    """Refuse a policy sent with an executor_type that is not the kind of its default executor."""
    sent = policy._sent_executor_type
    if sent is None:
        return
    if sent not in ("agent", "team", "workflow"):
        raise ValueError("executor_type is agent, team or workflow")
    kind = _executor_kind(registry, policy.default_executor)
    if kind != sent:
        raise ValueError(f"executor_type '{sent}' does not match {kind} '{policy.default_executor}'")


def _may_suggest(registry: Any, policy: Any, suggested: Any) -> bool:
    """Whether a proposal may name this executor: any, unless the policy lists executors."""
    from agno.registry._reserved import MINI_AGENT_ID

    if policy.executors is None:
        return True
    try:
        return (
            suggested[1] in {*policy.executors, MINI_AGENT_ID}
            and _executor_kind(registry, suggested[1]) == suggested[0]
        )
    except ValueError:
        return False


def _policy_executors(registry: Any, policy: Any) -> List[str]:
    """The run endpoints of a policy's default and listed executors, after the executor checks."""
    endpoints = []
    for executor_id in dict.fromkeys([policy.default_executor, *(policy.executors or [])]):
        kind = _executor_kind(registry, executor_id)
        _automatic_executor(registry, kind, executor_id)
        endpoints.append(f"/{kind}s/{executor_id}/runs")
    return endpoints


def _declared_schedule_fields(
    product_id: str, routine: Routine, registry: Any, *, agent_os: Any = None, trusted: bool = False
) -> Dict[str, Any]:
    """Schedule fields for a declared Routine.

    Only the deployment's own declarations (trusted=True) may carry auto_accept. A Routine declared
    through a request or a chat tool needs the Routine API's authorization for it.
    """
    if routine.auto_accept and not trusted:
        raise ValueError("Authorize automatic acceptance through the Routine API")
    fields = _schedule_fields(product_id, routine, registry, agent_os=agent_os)
    if routine.auto_accept:
        policy = routine.auto_accept
        _require_sent_executor_type(registry, policy)
        _policy_executors(registry, policy)
        if agent_os is not None and any(name not in _acceptance_checks(agent_os) for name in policy.required_checks):
            raise ValueError("Unknown automatic acceptance check")
        fields["payload"]["metadata"]["auto_accept"] = policy.model_dump()
    return fields


class _RoutineAuthorization(_ExecutorAuthorization):
    """Routine authority permits proposals, never acceptance or schedule edits."""

    def __init__(self, original: Any, routine_id: Optional[str] = None, product_id: Optional[str] = None):
        super().__init__(original)
        self.routine_id = routine_id
        self.product_id = product_id

    def snapshot(self) -> Dict[str, Any]:
        return {
            **super().snapshot(),
            "company_routine": True,
            "company_routine_unscoped": self.original is None,
            "company_routine_id": self.routine_id,
            "company_product_id": self.product_id,
        }


async def _authorize_auto_accept(request, policy, agent_os=None):
    import time

    from fastapi import HTTPException

    from agno.company.declarations import AutoAccept
    from agno.company.execution import _ExecutorAuthorization
    from agno.os.routers.run_permissions import _require_endpoint_permission
    from agno.run.authorization import current_authorization

    authority = current_authorization()
    if (
        isinstance(authority, _ExecutorAuthorization)
        or (authority is not None and authority.service_account)
        or getattr(request.state, "is_internal_service", False)
    ):
        raise HTTPException(403, "Only a human may authorize automatic acceptance")
    if authority is not None:
        try:
            await authority.arequire("schedules", "write")
            if policy:
                await authority.arequire("tasks", "write")
                await authority.arequire("wiki", "read")
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
    if policy:
        try:
            parsed = AutoAccept.model_validate(policy)
            if parsed.limits is not None and parsed.limits.expires_at <= int(time.time()):
                raise ValueError("Automatic acceptance expiry must be in the future")
            endpoints = _policy_executors(getattr(agent_os, "registry", None), parsed)
            if agent_os is not None:
                if any(name not in _acceptance_checks(agent_os) for name in parsed.required_checks):
                    raise ValueError("Unknown automatic acceptance check")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if (parsed.complete_projects or parsed.approve_projects) and authority is not None:
            try:
                await authority.arequire("projects", "write")
            except PermissionError as exc:
                raise HTTPException(403, str(exc))
        # The author must be allowed to run the default executor and each listed one themselves.
        for endpoint in endpoints:
            await _require_endpoint_permission(request, endpoint, "POST", action="accept")


def _only_turns_auto_accept_off(stored, payload):
    """Whether a Routine payload differs from the stored one only by having no auto_accept policy."""

    def rest(value):
        value = {key: item for key, item in (value or {}).items() if key != "_agno_company_acceptance"}
        metadata = value.get("metadata") or {}
        return {**value, "metadata": {key: item for key, item in metadata.items() if key != "auto_accept"}}

    return not ((payload or {}).get("metadata") or {}).get("auto_accept") and rest(stored) == rest(payload)


async def _stamp_auto_accept(request, payload, agent_os=None, stored=None):
    """Give a Routine payload the grant its auto_accept policy runs under.

    stored is the Routine's payload before this edit. A payload that carries the stored declared
    marker and the stored policy comes from an edit that does not set auto_accept. Where
    authorization is on, that policy has no person behind it, and it stays that way.
    """
    from agno.run.authorization import AUTHORIZATION_KEY, authorization_snapshot

    payload = dict(payload or {})
    metadata = dict(payload.get("metadata") or {})
    carried = payload.pop("_agno_company_acceptance", None)
    policy = metadata.get("auto_accept")
    if policy:
        stored = stored or {}
        if (
            getattr(agent_os, "authorization", None)
            and carried == _DECLARED
            and stored.get("_agno_company_acceptance") == _DECLARED
            and policy == (stored.get("metadata") or {}).get("auto_accept")
        ):
            payload["_agno_company_acceptance"] = dict(_DECLARED)
        else:
            await _authorize_auto_accept(request, policy, agent_os)
            # Even in an unauthenticated local deployment this grant is generated
            # here, never copied from a supplied payload. Executor snapshots cannot
            # pass the human boundary above.
            payload["_agno_company_acceptance"] = {
                AUTHORIZATION_KEY: authorization_snapshot(),
                "user_id": getattr(request.state, "user_id", None),
            }
    payload["metadata"] = metadata
    return payload


def _stored_policy(raw):
    """A stored policy, and whether it was saved before this form (it names executor_type and executor_id).

    Such a policy allows that one executor and uses it by default. It keeps the rest of what it was
    saved under: it approves no Project, and its lifetime count and expiry are its only limits.
    """
    from agno.company.declarations import AutoAccept

    return AutoAccept.model_validate(raw), "executor_type" in raw and "default_executor" not in raw


def _policy_fingerprint(schedule):
    import hashlib
    import json

    policy = ((schedule.get("payload") or {}).get("metadata") or {}).get("auto_accept")
    content: Any = False
    if policy:
        parsed, legacy = _stored_policy(policy)
        content = parsed.model_dump()
        if legacy:
            # The version it was saved with, so its budget does not change.
            kept = ("source_ids", "work_scope", "required_checks", "limits", "complete_projects")
            saved = {"executor_type": policy["executor_type"], "executor_id": policy["executor_id"]}
            content = {**saved, **{key: content[key] for key in kept}}
        if not content["complete_projects"]:
            content.pop("complete_projects")
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


_OPEN_STATUSES = OPEN_TASK_STATUSES


def _open_tasks(tasks, routine_id):
    """How many of a Routine's Tasks are accepted and not yet Done or Cancelled.

    A Task whose run failed stays In progress, so it counts until a person retries, returns or cancels it.
    """
    return sum(1 for task in tasks if task.get("routine_id") == routine_id and task["status"] in _OPEN_STATUSES)


async def _check_automatic_policy(schedule_db, task):
    receipts = [
        entry["auto_accept"]
        for entry in task.get("transitions", [])
        if entry.get("target") == "ready" and entry.get("auto_accept")
    ]
    # Only the most recent acceptance owns this attempt. A later human
    # acceptance supersedes a Routine's old receipt.
    acceptances = [entry for entry in task.get("transitions", []) if entry.get("target") == "ready"]
    if not receipts or not acceptances[-1].get("auto_accept"):
        return
    receipt = acceptances[-1]["auto_accept"]
    schedule = await _call(schedule_db, "get_schedule", receipt["routine_id"]) if schedule_db else None
    if (
        schedule is None
        or not schedule["enabled"]
        or schedule.get("managed_by") != "company"
        or ((schedule.get("payload") or {}).get("metadata") or {}).get("product_id") != task["product_id"]
        or _policy_fingerprint(schedule) != receipt["policy"]
        # A declared policy that a person has since replaced no longer runs as the deployment.
        or (receipt.get("declared") and schedule["payload"].get("_agno_company_acceptance") != _DECLARED)
    ):
        raise ValueError("Routine automatic acceptance was changed or revoked")
    import time

    policy, _ = _stored_policy(schedule["payload"]["metadata"]["auto_accept"])
    if policy.limits is not None and int(time.time()) >= policy.limits.expires_at:
        raise ValueError("Routine automatic acceptance expired")


async def _manager_call(manager, method, *args, **kwargs):
    import inspect

    fn = getattr(manager, method)
    return (
        await fn(*args, **kwargs) if inspect.iscoroutinefunction(fn) else await asyncio.to_thread(fn, *args, **kwargs)
    )


async def _project_active(task, manager):
    project = await _manager_call(manager, "get_project", task["project_id"]) if task.get("project_id") else None
    return bool(project and project["product_id"] == task["product_id"] and project["status"] == "active")


async def _has_source_evidence(task, manager):
    evidence = task.get("evidence") or []
    if not evidence:
        return False
    for item in evidence:
        _check_automation_deadline()
        if not isinstance(item, dict) or not all(
            item.get(key) for key in ("source_id", "content_hash", "link", "run_id")
        ):
            return False
        source = await _manager_call(manager, "get_source", item["source_id"])
        if not source or source["product_id"] != task["product_id"]:
            return False
        _check_automation_deadline()
        current = await _manager_call(manager, "read_source", item["source_id"], item["run_id"], links=[item["link"]])
        _check_automation_deadline()
        if not any(row["content_hash"] == item["content_hash"] and row["link"] == item["link"] for row in current):
            return False
    return True


async def _executor_registered(task, manager):
    from agno.company.execution import _executor

    _executor(manager.registry, task.get("executor_type"), task.get("executor_id"), accepting=True)
    return True


def _automatic_executor(registry, executor_type, executor_id):
    from agno.company.execution import _executor

    component = _executor(registry, executor_type, executor_id)
    if getattr(component, "db", None) is None:
        raise ValueError("Automatic Task executor requires a database for durable runs")
    return component


def _acceptance_checks(agent_os):
    checks = {
        "project_active": _project_active,
        "has_source_evidence": _has_source_evidence,
        "executor_registered": _executor_registered,
    }
    custom = agent_os.company.acceptance_checks
    if set(checks).intersection(custom):
        raise ValueError("Application acceptance checks cannot replace built-in checks")
    return {**checks, **custom}


_AUTOMATION_SCHEDULE_ID = COMPANY_AUTOMATION_SCHEDULE_ID
_AUTOMATION_CRON = "0 * * * *"
_AUTOMATION_TICK_SECONDS = 240
_automation_deadline: ContextVar[Optional[float]] = ContextVar("company_tick_deadline", default=None)


def _check_automation_deadline():
    import time

    deadline = _automation_deadline.get()
    if deadline is not None and time.time() >= deadline:
        raise TimeoutError("Company automation tick exhausted its claim budget")


async def _ensure_automation_schedule(db, *, enabled=True, cron_expr=_AUTOMATION_CRON):
    """Reconcile the runtime-owned schedule with the deployment configuration."""
    import time

    from agno.db.schemas.scheduler import Schedule
    from agno.db.utils import is_unique_violation
    from agno.scheduler.cron import is_on_demand, next_run_for, validate_cron_expr

    if is_on_demand(cron_expr) or not validate_cron_expr(cron_expr):
        raise ValueError(f"Invalid cron expression: {cron_expr}")
    existing = await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID)
    if existing is None:
        if not enabled:
            return None
        row = Schedule(
            id=_AUTOMATION_SCHEDULE_ID,
            name="Company automation",
            cron_expr=cron_expr,
            endpoint="/company/attention",
            method="GET",
            managed_by="company",
            next_run_at=int(time.time()),
            created_at=int(time.time()),
        ).to_dict()
        try:
            await _call(db, "create_schedule", row)
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
        existing = await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID)
    if (
        existing is None
        or existing.get("managed_by") != "company"
        or existing["endpoint"] != "/company/attention"
        or existing["method"] != "GET"
    ):
        raise ValueError("Company automation schedule identity is already in use")
    if existing["cron_expr"] != cron_expr:
        next_run_at = next_run_for(cron_expr, existing.get("timezone") or "UTC")
        existing = await _call(
            db, "update_schedule", _AUTOMATION_SCHEDULE_ID, cron_expr=cron_expr, next_run_at=next_run_at
        )
    if enabled and not existing["enabled"] and existing.get("disabled_reason") == "company_off":
        existing = await _call(db, "update_schedule", _AUTOMATION_SCHEDULE_ID, enabled=True, disabled_reason=None)
    elif not enabled and existing["enabled"]:
        existing = await _call(
            db, "update_schedule", _AUTOMATION_SCHEDULE_ID, enabled=False, disabled_reason="company_off"
        )
    return existing


class _AutomationSkip(ValueError):
    """An expected policy refusal or concurrent change with no work to record."""


class _CompanyScheduleExecutor(CompanyScheduleExecutor):
    """Run the existing scheduler's claimed Company tick, without another loop."""

    def __init__(self, agent_os, app, **kwargs):
        kwargs.setdefault("company_db", agent_os._company_db)
        kwargs.setdefault("schedule_db", agent_os.db)
        super().__init__(**kwargs)
        self.agent_os = agent_os
        self.app = app

    async def execute(self, schedule, db, release_schedule=True):
        """Persist automation history only after work or an execution failure."""
        import time

        from agno.db.schemas.scheduler import Schedule, ScheduleRun
        from agno.scheduler.cron import next_run_for
        from agno.scheduler.run_id import new_schedule_run_id
        from agno.utils.log import log_error, log_warning

        sched = Schedule.from_dict(schedule) if isinstance(schedule, dict) else schedule
        if sched.id != _AUTOMATION_SCHEDULE_ID:
            return await super().execute(schedule, db, release_schedule=release_schedule)
        schedule_id = sched.id
        started_at = int(time.time())
        try:
            try:
                result = await self._call_endpoint(sched)
            except asyncio.CancelledError:
                await _call(
                    db,
                    "create_schedule_run",
                    ScheduleRun(
                        id=new_schedule_run_id(),
                        schedule_id=schedule_id,
                        triggered_at=started_at,
                        completed_at=int(time.time()),
                        status="cancelled",
                        error="Execution cancelled during shutdown",
                        user_id=sched.user_id,
                    ).to_dict(),
                )
                raise
            except Exception as exc:
                result = {"status": "failed", "error": str(exc)}
            outcomes = (result.get("output") or {}).get("tasks", [])
            from agno.company.automation_history import _record_task_failures

            await _record_task_failures(db, self.agent_os._company_db, outcomes)
            active = any(
                item.get("status") in {"accepted", "done"} or item.get("action") in {"submitted", "reconciled"}
                for item in outcomes
            )
            other_failure = result["status"] == "failed" and (
                not outcomes or any(item.get("status") == "failed" and not item.get("task_id") for item in outcomes)
            )
            task_failures = any(item.get("status") == "failed" and item.get("task_id") for item in outcomes)
            if other_failure or active:
                history_outcomes = [
                    item for item in outcomes if not (item.get("status") == "failed" and item.get("task_id"))
                ]
                history_error = (
                    "; ".join(item["reason"] for item in history_outcomes if item.get("status") == "failed")
                    if outcomes
                    else result.get("error")
                )
                run = ScheduleRun(
                    id=new_schedule_run_id(),
                    schedule_id=schedule_id,
                    triggered_at=started_at,
                    completed_at=int(time.time()),
                    status="failed" if other_failure else "success",
                    error=history_error if other_failure else None,
                    output={"tasks": history_outcomes} if outcomes else result.get("output"),
                    user_id=sched.user_id,
                ).to_dict()
                await _call(db, "create_schedule_run", run)
                return result if task_failures else run
            return result
        finally:
            # Always release the schedule lock so it doesn't stay stuck
            if release_schedule and schedule_id is not None:
                try:
                    next_run_at = next_run_for(
                        sched.cron_expr,
                        sched.timezone or "UTC",
                    )
                except Exception as e:
                    log_warning(
                        f"Failed to compute next_run_at for schedule {schedule_id}; "
                        f"disabling schedule to prevent it from becoming stuck: {e}",
                    )

                    next_run_at = None
                    try:
                        if asyncio.iscoroutinefunction(getattr(db, "update_schedule", None)):
                            await db.update_schedule(schedule_id, enabled=False)
                        else:
                            db.update_schedule(schedule_id, enabled=False)
                    except Exception as exc:
                        log_error(f"Failed to disable schedule {schedule_id} after cron failure: {exc}")

                try:
                    from inspect import signature

                    release_kwargs: Dict[str, Any] = {"next_run_at": next_run_at}
                    # An expired worker must not release a newer worker's claim.
                    parameters = signature(db.release_schedule).parameters
                    if sched.locked_by is not None and "worker_id" in parameters:
                        release_kwargs["worker_id"] = sched.locked_by
                    if sched.locked_at is not None and "locked_at" in parameters:
                        release_kwargs["locked_at"] = sched.locked_at
                    if asyncio.iscoroutinefunction(getattr(db, "release_schedule", None)):
                        await db.release_schedule(schedule_id, **release_kwargs)
                    else:
                        db.release_schedule(schedule_id, **release_kwargs)
                except Exception as exc:
                    log_error(f"Failed to release schedule {schedule_id}: {exc}")

    async def _call_endpoint(self, schedule):
        import time

        if schedule.id != _AUTOMATION_SCHEDULE_ID:
            return await super()._call_endpoint(schedule)
        if schedule.managed_by != "company" or schedule.endpoint != "/company/attention" or schedule.method != "GET":
            raise ValueError("Company automation schedule was repointed")
        # Stop admitting work before the scheduler's 300-second stale-claim
        # threshold. Check again after IO; never cancel a database transaction.
        token = _automation_deadline.set((schedule.locked_at or time.time()) + _AUTOMATION_TICK_SECONDS)
        try:
            _check_automation_deadline()
            outcomes = await self._tick()
            failures = [item["reason"] for item in outcomes if item.get("status") == "failed"]
            return {
                "status": "failed" if failures else "success",
                "output": {"tasks": outcomes},
                **({"error": "; ".join(failures)} if failures else {}),
            }
        finally:
            _automation_deadline.reset(token)

    async def _tick(self):
        db = self.agent_os._company_db
        # Snapshot the candidate ids before mutation so paging cannot skip work.
        tasks: List[Dict[str, Any]] = []
        seen = set()
        for status in ("backlog", "ready", "in_progress"):
            page = 1
            while True:
                _check_automation_deadline()
                rows, total = await _call(db, "get_tasks", status=status, limit=100, page=page)
                for row in rows:
                    if row["id"] not in seen:
                        tasks.append(row)
                        seen.add(row["id"])
                if page * 100 >= total:
                    break
                page += 1
        outcomes = []
        for candidate in tasks:
            _check_automation_deadline()
            task = None
            try:
                task = await _call(db, "get_task", candidate["id"])
                if task is None:
                    raise _AutomationSkip("Task was deleted")
                from agno.company.execution import _recover_task

                queue = getattr(self.app.state, "queue_worker", None)
                if task.get("job_id") and queue is not None:
                    recovered = await _recover_task(self.agent_os, queue, task)
                    if recovered is not None:
                        outcomes.append({"task_id": task["id"], **recovered})
                        continue
                if task["status"] == "backlog":
                    if task.get("origin") != "routine" or not task.get("routine_id"):
                        continue
                    task = await self._accept(task)
                    outcomes.append({"task_id": task["id"], "status": "accepted"})
                if task["status"] != "ready":
                    continue
                result = await self._dispatch(task)
                outcomes.append({"task_id": task["id"], **result})
            except Exception as exc:
                from fastapi import HTTPException

                reason = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                denied = isinstance(exc, PermissionError) or (isinstance(exc, HTTPException) and exc.status_code == 403)
                cancelled_project = False
                if denied and task is not None and task["status"] == "ready":
                    # A revoked accepting identity needs human attention, not a
                    # fresh failed dispatch on every tick. Never withdraw a run.
                    try:
                        await _call(
                            db,
                            "transition_task",
                            task["id"],
                            "backlog",
                            reason,
                            expected_updated_at=task["updated_at"],
                        )
                    except CancelledProjectError:
                        cancelled_project = True
                expected = (
                    isinstance(exc, _AutomationSkip)
                    or (denied and task is not None and task["status"] == "backlog")
                    or isinstance(exc, CancelledProjectError)
                    or cancelled_project
                )
                outcomes.append(
                    {"task_id": candidate["id"], "status": "skipped" if expected else "failed", "reason": reason}
                )
        outcomes.extend(await self._complete_projects())
        return outcomes

    async def _complete_projects(self):
        from agno.company.manager import AsyncCompanyManager, CompanyManager
        from agno.company.refresh import _records
        from agno.db.base import AsyncBaseDb

        os = self.agent_os
        manager = (
            AsyncCompanyManager(os._company_db, os.registry)
            if isinstance(os._company_db, AsyncBaseDb)
            else CompanyManager(os._company_db, os.registry)
        )
        outcomes = []
        for product in await _records(manager, "list"):
            for routine_id in (product.get("metadata") or {}).get("routine_ids", []):
                schedule = await _call(os.db, "get_schedule", routine_id)
                metadata = ((schedule or {}).get("payload") or {}).get("metadata") or {}
                policy = metadata.get("auto_accept")
                if (
                    metadata.get("template") != "refresh"
                    or metadata.get("deleted_at") is not None
                    or not isinstance(policy, dict)
                    or not policy.get("complete_projects")
                ):
                    continue
                for project in await _records(manager, "list_projects", product_id=product["id"], status="active"):
                    _check_automation_deadline()
                    try:
                        proposal = await self._completion_candidate(manager, project, routine_id)
                        if proposal is None:
                            continue
                        await self._accept(proposal, completing=True)
                        outcomes.append({"project_id": project["id"], "status": "done"})
                    except Exception as exc:
                        from fastapi import HTTPException

                        expected = isinstance(exc, (_AutomationSkip, PermissionError)) or (
                            isinstance(exc, HTTPException) and exc.status_code == 403
                        )
                        reason = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                        outcomes.append(
                            {
                                "project_id": project["id"],
                                "status": "skipped" if expected else "failed",
                                "reason": reason,
                            }
                        )
        return outcomes

    async def _completion_candidate(self, manager, project, routine_id):
        from agno.company.refresh import _completion_proposal, _records

        tasks = await _records(manager, "list_tasks", project_id=project["id"], include_deleted=True)
        if not tasks or any(
            task["status"] not in {"done", "cancelled"} for task in tasks if task.get("deleted_at") is None
        ):
            return None
        path, content = _completion_proposal(project, tasks)
        wiki = await _manager_call(manager, "get_wiki", project["product_id"])
        page = await wiki.backend.filesystem.aread_with_meta(path)
        if page is None or page.content != content:
            return None
        return {
            **project,
            "project_id": project["id"],
            "routine_id": routine_id,
            "evidence": [item for task in tasks for item in (task.get("evidence") or [])],
        }

    async def _accept(self, task, *, completing=False):
        import copy
        import inspect
        import time

        from agno.company.manager import AsyncCompanyManager, CompanyManager, _routine_project_id
        from agno.company.refresh import _records
        from agno.db.base import AsyncBaseDb
        from agno.os.authz.run_context import restore_authorization
        from agno.run.authorization import AUTHORIZATION_KEY, authorization_scope

        if not completing and any(entry.get("target") == "ready" for entry in task.get("transitions", [])):
            raise _AutomationSkip("Previously accepted Task requires fresh human acceptance after return to Backlog")
        os = self.agent_os
        schedule = await _call(os.db, "get_schedule", task["routine_id"])
        if not schedule or not schedule["enabled"] or schedule.get("managed_by") != "company":
            raise _AutomationSkip("Routine was disabled or deleted")
        payload = schedule.get("payload") or {}
        metadata = payload.get("metadata") or {}
        grant = payload.get("_agno_company_acceptance")
        if not metadata.get("auto_accept") or grant is None:
            raise _AutomationSkip("Routine has no human automatic acceptance authorization")
        policy, legacy = _stored_policy(metadata["auto_accept"])
        # A policy declared in code has no person behind it, and code cannot give a Routine a caller's
        # grant. It acts only where authorization is off, where every caller is a trusted operator.
        declared = grant == _DECLARED
        if declared and os.authorization:
            raise _AutomationSkip(
                "A declared auto_accept acts only where authorization is off. "
                "A person turns it on for this Routine from the UI, the API or chat"
            )
        if completing and (not policy.complete_projects or metadata.get("template") != "refresh"):
            raise _AutomationSkip("Routine is not authorized to complete Projects")
        acceptance_resource = "projects" if completing else "tasks"
        if metadata.get("product_id") != task["product_id"]:
            raise _AutomationSkip("Proposal is outside the Routine Product")
        # A Task runs on the executor its proposal suggests, or on the default when it suggests none.
        suggested = (task.get("executor_type"), task.get("executor_id"))

        def default():
            # Read from the registry only for a Task that needs it: a default that was removed, or
            # whose ID two kinds now share, does not stop a proposal that names another executor.
            saved_kind = metadata["auto_accept"]["executor_type"] if legacy else None
            return (saved_kind or _executor_kind(os.registry, policy.default_executor), policy.default_executor)

        if suggested == (None, None):
            executor, chosen_by = default(), "default"
        elif (not (completing or legacy) and _may_suggest(os.registry, policy, suggested)) or (
            suggested[1] == policy.default_executor and suggested == default()
        ):
            executor, chosen_by = suggested, "proposal"
        else:
            raise _AutomationSkip("Proposed executor is outside automatic acceptance authorization")
        scope = policy.work_scope
        if scope and (
            (scope.product_ids is not None and task["product_id"] not in scope.product_ids)
            or (scope.project_ids is not None and task.get("project_id") not in scope.project_ids)
        ):
            raise _AutomationSkip("Proposal is outside the authorized work scope")
        if policy.limits is not None and int(time.time()) >= policy.limits.expires_at:
            raise _AutomationSkip("Routine automatic acceptance expired")
        if policy.source_ids is not None:
            evidence = task.get("evidence") or []
            if not evidence or any(
                not isinstance(item, dict) or item.get("source_id") not in policy.source_ids for item in evidence
            ):
                raise _AutomationSkip("Proposal is outside the authorized Sources")
        try:
            _automatic_executor(os.registry, *executor)
        except ValueError as exc:
            if chosen_by != "proposal":
                raise
            raise _AutomationSkip(f"The proposal's executor cannot run this Task: {exc}") from exc
        checked_task = {**task, "executor_type": executor[0], "executor_id": executor[1]}
        authority = restore_authorization(self.app, grant.get(AUTHORIZATION_KEY))
        if isinstance(authority, _ExecutorAuthorization) or (authority is not None and authority.service_account):
            raise _AutomationSkip("Automatic acceptance requires human authority")
        if authority is None and os.authorization:
            raise _AutomationSkip("Automatic acceptance has no saved human authority")
        user_store = getattr(self.app.state, "user_store", None)
        if user_store is not None and grant.get("user_id") is not None:
            try:
                disabled = await user_store.ais_disabled(grant["user_id"])
            except Exception:
                if getattr(self.app.state, "user_directory_fail_closed", False):
                    raise _AutomationSkip("Automatic acceptance user directory is unavailable")
                disabled = False
            if disabled:
                raise _AutomationSkip("Automatic acceptance author is disabled")
        if authority is not None:
            for resource, action, resource_id in (
                ("schedules", "write", None),
                (acceptance_resource, "write", None),
                ("wiki", "read", None),
                (executor[0] + "s", "run", executor[1]),
            ):
                await authority.arequire(resource, action, resource_id)
        manager = (
            AsyncCompanyManager(os._company_db, os.registry)
            if isinstance(os._company_db, AsyncBaseDb)
            else CompanyManager(os._company_db, os.registry)
        )
        approving = None
        if not completing:
            project = await _manager_call(manager, "get_project", task["project_id"])
            if project and project["status"] == "cancelled":
                raise _AutomationSkip("Cannot accept Task work in a cancelled Project")
            if project and project["status"] == "proposed":
                # A Routine's Project takes its id from the Product, the Routine and the name. A Project a
                # person or another Routine proposed, or one renamed since, waits for a person.
                own = project["id"] == _routine_project_id(task["product_id"], schedule["id"], project["name"])
                if not (policy.approve_projects and own):
                    raise _AutomationSkip("Project approval is required before automatic Task acceptance")
                if authority is not None:
                    await authority.arequire("projects", "write")
                approving = project
        if policy.limits is None:
            if not completing:
                # The review queue is the brake: a person finishing a Task makes room for the next.
                open_now = 0
                for status in _OPEN_STATUSES:
                    rows = await _records(manager, "list_tasks", product_id=task["product_id"], status=status)
                    open_now += _open_tasks(rows, schedule["id"])
                if open_now >= policy.max_open:
                    raise _AutomationSkip(
                        f"Routine has {open_now} Tasks open, its limit. Complete or cancel one for it to accept more"
                    )
        # Avoid Source IO for exhausted policies. The transaction repeats this
        # check under the Product lock, so concurrent acceptances remain bounded.
        elif (
            await _call(
                os._company_db,
                "count_company_acceptances",
                schedule["id"],
                _policy_fingerprint(schedule),
                "" if completing else task["id"],
            )
            >= policy.limits.max_acceptances
        ):
            raise _AutomationSkip("Routine acceptance limit reached")
        checks = _acceptance_checks(os)
        with authorization_scope(lambda: authority):
            # Reject unknown checks and cheap local failures before any Source IO.
            names = list(dict.fromkeys(policy.required_checks))
            if any(name not in checks for name in names):
                raise _AutomationSkip("Unknown automatic acceptance check")
            names.sort(key=lambda name: 0 if name in {"executor_registered", "project_active"} else 1)
            if approving is not None:
                # The Project becomes active with this acceptance.
                names = [name for name in names if name != "project_active"]
            for name in (name for name in names if name != "has_source_evidence"):
                check = checks.get(name)
                if check is None:
                    raise _AutomationSkip("Unknown automatic acceptance check: " + name)
                result = (
                    await check(copy.deepcopy(checked_task), manager)
                    if inspect.iscoroutinefunction(check)
                    else await asyncio.to_thread(check, copy.deepcopy(checked_task), manager)
                )
                if inspect.isawaitable(result):
                    result = await result
                if result is not True:
                    raise _AutomationSkip("Required automatic acceptance check failed: " + name)
            if policy.source_ids is not None or "has_source_evidence" in names:
                if not await _has_source_evidence(task, manager):
                    raise _AutomationSkip("Required automatic acceptance check failed: has_source_evidence")
            if authority is not None:
                await authority.arequire("schedules", "write")
                await authority.arequire(acceptance_resource, "write")
                if approving is not None:
                    await authority.arequire("projects", "write")
                await authority.arequire("wiki", "read")
                await authority.arequire(executor[0] + "s", "run", executor[1])
            # Re-read after all checks and proposal IO. Product/template bindings
            # are separate from the content-only policy fingerprint.
            current = await _call(os.db, "get_schedule", schedule["id"])
            current_metadata = ((current or {}).get("payload") or {}).get("metadata") or {}
            if (
                not current
                or not current["enabled"]
                or current.get("managed_by") != "company"
                or current_metadata.get("product_id") != task["product_id"]
                or (completing and current_metadata.get("template") != "refresh")
                or _policy_fingerprint(current) != _policy_fingerprint(schedule)
            ):
                raise _AutomationSkip("Routine automatic acceptance changed during checks")
            if policy.limits is not None and int(time.time()) >= policy.limits.expires_at:
                raise _AutomationSkip("Routine automatic acceptance expired during checks")
            receipt = {"routine_id": schedule["id"], "policy": _policy_fingerprint(schedule)}
            if policy.limits is not None:
                receipt["max_acceptances"] = policy.limits.max_acceptances
            if declared:
                receipt["declared"] = True
            # The record says whether the executor came from the Routine's proposal or the default.
            task_receipt = {**receipt, "executor_chosen_by": chosen_by}
            if policy.limits is None:
                # The store enforces each bound in the acceptance's own transaction, under the Product lock.
                task_receipt["max_open"] = policy.max_open
            _check_automation_deadline()
            if completing:
                accepted = await _manager_call(
                    manager,
                    "transition_project",
                    project_id=task["id"],
                    target="done",
                    reason="Authorized Refresh completion proposal",
                    accepted_by=grant.get("user_id"),
                    expected_updated_at=task["updated_at"],
                    auto_accept=receipt,
                )
            else:
                if approving is not None:
                    approved = await _manager_call(
                        manager,
                        "transition_project",
                        project_id=approving["id"],
                        target="active",
                        reason="Approved with the Routine's Task",
                        accepted_by=grant.get("user_id"),
                        expected_updated_at=approving["updated_at"],
                        auto_accept=receipt,
                    )
                    if approved is None:
                        raise _AutomationSkip("Project changed during automatic approval")
                try:
                    accepted = await _manager_call(
                        manager,
                        "transition_task",
                        task_id=task["id"],
                        target="ready",
                        reason="Authorized Routine proposal",
                        accepted_by=grant.get("user_id"),
                        executor_type=executor[0],
                        executor_id=executor[1],
                        expected_updated_at=task["updated_at"],
                        auto_accept=task_receipt,
                    )
                except OpenTaskLimitError as exc:
                    raise _AutomationSkip(str(exc)) from exc
        if accepted is None:
            raise _AutomationSkip("Proposal changed during automatic acceptance")
        return accepted

    async def _dispatch(self, task):
        import json
        from urllib.parse import quote

        import httpx

        from agno.company.execution import _automatic_task, _executor
        from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
        from agno.os.authz.run_context import restore_authorization
        from agno.run.authorization import AUTHORIZATION_HEADER, AUTHORIZATION_KEY

        os = self.agent_os
        from agno.company.execution import _recover_task

        queue = getattr(self.app.state, "queue_worker", None)
        if task.get("job_id") and queue is not None:
            recovered = await _recover_task(os, queue, task)
            if recovered is not None:
                return recovered
        if task["status"] != "ready":
            raise _AutomationSkip("Only Ready Tasks can be dispatched")
        acceptances = [entry for entry in task["transitions"] if entry.get("target") == "ready"]
        if not acceptances or AUTHORIZATION_KEY not in acceptances[-1]:
            raise ValueError("Task needs a fresh acceptance before automatic pickup")
        snapshot = acceptances[-1][AUTHORIZATION_KEY]
        authority = restore_authorization(self.app, snapshot)
        if authority is None and os.authorization:
            raise PermissionError("Task acceptance has no saved caller authority")
        if task.get("executor_type") == "engineering":
            raise _AutomationSkip("Engineering executors cannot be started yet")
        _executor(os.registry, task.get("executor_type"), task.get("executor_id"))
        if authority is not None:
            await authority.arequire(task["executor_type"] + "s", "run", task["executor_id"])
            await authority.arequire("tasks", "write")
            await authority.arequire("wiki", "read")
        try:
            await _check_automatic_policy(os.db, task)
        except ValueError as exc:
            if task["status"] == "ready":
                # Withdraw only the unchanged, unstarted acceptance. Backlog and
                # its transition reason expose the work for human attention.
                try:
                    await _call(
                        os._company_db,
                        "transition_task",
                        task["id"],
                        "backlog",
                        str(exc),
                        expected_updated_at=task["updated_at"],
                    )
                except CancelledProjectError:
                    pass
            raise
        if task["status"] == "ready" and task.get("job_id"):
            queue = getattr(self.app.state, "queue_worker", None)
            prior_job = await queue.store.get_job(task["job_id"]) if queue is not None else None
            if prior_job is not None and prior_job["status"] in {"queued", "running"}:
                raise _AutomationSkip("The previous Task run is still active")
        attempts = [entry["attempt"] for entry in task["transitions"] if entry.get("attempt")]
        attempt = max(attempts, default=0) + (1 if task["status"] == "ready" else 0)
        if attempt < 1:
            raise ValueError("Only Ready Tasks or pending submissions can be picked up")
        # This is the ordinary manual Task route, which reserves the attempt,
        # checks the registry and run scope, and enters the executor's run route.
        headers = {"Authorization": "Bearer " + self.internal_service_token, AUTHORIZATION_HEADER: json.dumps(snapshot)}
        if task.get("accepted_by") is not None:
            headers[SCHEDULE_OWNER_HEADER] = quote(task["accepted_by"], safe="")
        current = await _call(os._company_db, "get_task", task["id"])
        observed = {key: task[key] for key in ("id", "status", "updated_at")}
        if current is None or any(current[key] != value for key, value in observed.items()):
            raise ValueError("Task acceptance changed before automatic dispatch")
        token = _automatic_task.set(observed)
        try:
            _check_automation_deadline()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=self.base_url) as client:
                response = await client.post(
                    f"/company/tasks/{task['id']}/runs", json={"attempt": attempt}, headers=headers
                )
            if response.status_code != 202:
                from fastapi import HTTPException

                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text
                if response.status_code == 409 and detail in {
                    "The previous Task run is still active",
                    "Cannot start Task work in a cancelled Project",
                }:
                    raise _AutomationSkip(detail)
                raise HTTPException(response.status_code, detail)
            result = response.json()
            return {**result, "action": "submitted" if result.get("status") == "PENDING" else "observed"}
        finally:
            _automatic_task.reset(token)


def _require_routine_product(product_id: Optional[str], authority: Any = None) -> None:
    from agno.run.authorization import current_authorization

    authority = authority or current_authorization()
    if (
        isinstance(authority, _ExecutorAuthorization)
        and authority.product_id is not None
        and authority.product_id != product_id
    ):
        if isinstance(authority, _RoutineAuthorization):
            raise PermissionError("Routine authority is restricted to its configured Product")
        raise PermissionError("A Task run is restricted to its Task's Product")


async def _require_active_routine_product(db: Any, product_id: Optional[str]) -> None:
    from agno.company.execution import _call

    if db is None or not product_id or await _call(db, "get_product", product_id) is None:
        raise ValueError("Routine Product is missing or archived")
