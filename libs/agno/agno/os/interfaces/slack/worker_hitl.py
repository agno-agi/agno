"""Resolve Slack worker approvals from durable, participant-scoped Task associations."""

from typing import Any, Dict

from fastapi import HTTPException


async def _worker_run(delivery: Any, app: Any, row: Dict[str, Any], mapping: Dict[str, Any], *, write: bool = False):
    from agno.company.conversation import aget_conversation_tasks
    from agno.company.execution import _call, _executor, _task_run_database
    from agno.run import RunContext

    authority = await delivery._authority(app, row["data"]["user"], row["principal"])
    visible = await aget_conversation_tasks(
        delivery._os,
        RunContext(
            run_id=mapping["origin_run_id"],
            session_id=row["session_id"],
            user_id=row["principal"],
            authorization=authority,
        ),
        origin_run_id=mapping["origin_run_id"],
    )
    if not any(item["task_id"] == mapping["task_id"] for item in visible):
        raise PermissionError("Task does not belong to this participant's originating request")
    task = await _call(delivery._os._company_db, "get_task", mapping["task_id"])
    if (
        task is None
        or task.get("job_id") != mapping["run_id"]
        or any(task.get(key) != mapping[key] for key in ("session_id", "executor_type", "executor_id"))
    ):
        raise PermissionError("Task attempt or executor has changed")
    await authority.arequire(task["executor_type"] + "s", "read", task["executor_id"])
    if write:
        await authority.arequire("tasks", "write")
        await authority.arequire(task["executor_type"] + "s", "run", task["executor_id"])
    database = _task_run_database(delivery._os, task)
    if database is None:
        raise HTTPException(409, "Original Task run database is unavailable")
    run = await _call(database, "get_run", run_id=mapping["run_id"], deserialize=False)
    if not run or run.get("session_id") != mapping["session_id"] or run.get("user_id") != row["principal"]:
        raise PermissionError("Worker run belongs to another participant or session")
    if run.get(task["executor_type"] + "_id") != mapping["executor_id"]:
        raise PermissionError("Worker run belongs to another executor")
    if write and str(run.get("status", "")).upper() == "PAUSED":
        if task["status"] != "in_progress":
            raise PermissionError("Task is no longer running")
        component = _executor(delivery._os.registry, task["executor_type"], task["executor_id"])
        if component is None or getattr(component, "db", None) is not database:
            raise HTTPException(409, "Restore the original Task executor database before continuing")
        worker = getattr(app.state, "queue_worker", None)
        job = await worker.store.get_job(mapping["run_id"]) if worker is not None else None
        if (
            not job
            or job.get("status") not in {"paused", "queued", "running"}
            or (job.get("payload") or {}).get("company_task_id") != task["id"]
        ):
            raise HTTPException(409, "Durable Task continuation is unavailable")
    return {**(run.get("run_data") or {}), **run}


async def _collect_worker_pause(delivery: Any, app: Any, row: Dict[str, Any], task: Dict[str, Any]) -> None:
    import hashlib
    import json

    from agno.company.execution import _call
    from agno.os.interfaces.slack.builders import build_pause_message
    from agno.os.interfaces.slack.types import block_to_dict
    from agno.run.requirement import RunRequirement

    if task["status"] != "in_progress" or not task.get("run_id"):
        return
    stored = await _call(delivery._os._company_db, "get_task", task["task_id"])
    if stored is None or stored.get("job_id") != task["run_id"]:
        return
    mapping = {
        "task_id": stored["id"],
        "run_id": stored["job_id"],
        "session_id": stored["session_id"],
        "executor_type": stored["executor_type"],
        "executor_id": stored["executor_id"],
        "origin_run_id": row["data"]["run_id"],
    }
    try:
        run = await _worker_run(delivery, app, row, mapping)
    except PermissionError:
        # Task readers can see that input is needed without receiving tool arguments.
        worker = getattr(app.state, "queue_worker", None)
        job = await worker.store.get_job(mapping["run_id"]) if worker is not None else None
        if (
            job
            and job.get("status") == "paused"
            and (job.get("payload") or {}).get("company_task_id") == task["task_id"]
        ):
            delivery._intent(
                row,
                "task:" + task["task_id"] + ":input:" + mapping["run_id"],
                "Task " + task["title"] + " needs input in AgentOS: " + delivery.agent_os_url,
            )
        return
    if str(run.get("status", "")).upper() != "PAUSED":
        return
    requirements = [RunRequirement.from_dict(req) for req in run.get("requirements") or []]
    key = (
        "task:"
        + task["task_id"]
        + ":pause:"
        + hashlib.sha256(
            json.dumps([mapping["run_id"], run.get("requirements")], sort_keys=True, default=str).encode()
        ).hexdigest()
    )
    if requirements and mapping["executor_type"] in {"agent", "team"}:
        row["data"].setdefault("worker_runs", {})[mapping["run_id"]] = mapping
        blocks = [block_to_dict(block) for block in build_pause_message(mapping["run_id"], requirements)]
        delivery._intent(row, key, "Task " + task["title"] + " needs your input or tool approval.", blocks=blocks)
        row["data"]["notifications"][key]["worker"] = mapping
    else:
        delivery._intent(row, key, "Task " + task["title"] + " needs input in AgentOS: " + delivery.agent_os_url)
