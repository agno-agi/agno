from __future__ import annotations

import json
from time import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from uuid import uuid4

from agno.models.message import Message
from agno.run import RunContext, RunStatus
from agno.run.team import TeamRunOutput
from agno.team.autonomy.models import JobPhase, JobStatus, TeamExecutionMode
from agno.team.autonomy.session_store import (
    get_job_snapshot_from_session_state,
    get_latest_job_id_from_session_state,
    put_job_snapshot_in_session_state,
)
from agno.team.autonomy.snapshot_ops import pause_job_snapshot, resume_job_snapshot

if TYPE_CHECKING:
    from agno.session.team import TeamSession
    from agno.team.team import Team


def _now_ts() -> int:
    return int(time())


def _coerce_mode(mode: Optional[object]) -> Optional[TeamExecutionMode]:
    if mode is None:
        return None
    if isinstance(mode, TeamExecutionMode):
        return mode
    if isinstance(mode, str):
        try:
            return TeamExecutionMode(mode)
        except ValueError:
            return None
    return None


def _build_default_plan(goal: str) -> List[Dict[str, Any]]:
    return [
        {
            "title": "Execute the goal",
            "instructions": goal,
            "requires_approval": False,
        }
    ]


def _plan_steps_sync(team: "Team", goal: str) -> List[Dict[str, Any]]:
    roster = team.get_members_system_message_content(indent=0)

    system = Message(
        role="system",
        content=(
            "You are a project planner for a multi-agent team.\n"
            "Return ONLY valid JSON with this shape:\n"
            "{\n"
            '  "steps": [\n'
            '    {"title": string, "instructions": string, "requires_approval": boolean}\n'
            "  ]\n"
            "}\n"
            "Guidelines:\n"
            "- Keep steps minimal and concrete.\n"
            "- Set requires_approval=true for steps that are destructive, irreversible, or have external side effects.\n"
        ),
    )
    user = Message(
        role="user",
        content=f"GOAL:\n{goal}\n\nTEAM MEMBERS:\n{roster}\n\nPlan the steps.",
    )

    model = team.model
    if model is None:
        return _build_default_plan(goal)

    resp = model.response(messages=[system, user], tools=None)
    content = resp.content
    if not isinstance(content, str):
        content = str(content) if content is not None else ""

    try:
        data = json.loads(content)
        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            return _build_default_plan(goal)
        planned: List[Dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            title = step.get("title")
            instructions = step.get("instructions")
            if not isinstance(title, str) or not isinstance(instructions, str):
                continue
            planned.append(
                {
                    "title": title.strip(),
                    "instructions": instructions.strip(),
                    "requires_approval": bool(step.get("requires_approval", False)),
                }
            )
        return planned or _build_default_plan(goal)
    except Exception:
        return _build_default_plan(goal)


async def _plan_steps_async(team: "Team", goal: str) -> List[Dict[str, Any]]:
    roster = team.get_members_system_message_content(indent=0)

    system = Message(
        role="system",
        content=(
            "You are a project planner for a multi-agent team.\n"
            "Return ONLY valid JSON with this shape:\n"
            "{\n"
            '  "steps": [\n'
            '    {"title": string, "instructions": string, "requires_approval": boolean}\n'
            "  ]\n"
            "}\n"
            "Guidelines:\n"
            "- Keep steps minimal and concrete.\n"
            "- Set requires_approval=true for steps that are destructive, irreversible, or have external side effects.\n"
        ),
    )
    user = Message(
        role="user",
        content=f"GOAL:\n{goal}\n\nTEAM MEMBERS:\n{roster}\n\nPlan the steps.",
    )

    model = team.model
    if model is None:
        return _build_default_plan(goal)

    resp = await model.aresponse(messages=[system, user], tools=None)
    content = resp.content
    if not isinstance(content, str):
        content = str(content) if content is not None else ""

    try:
        data = json.loads(content)
        steps = data.get("steps")
        if not isinstance(steps, list) or not steps:
            return _build_default_plan(goal)
        planned: List[Dict[str, Any]] = []
        for step in steps:
            if not isinstance(step, dict):
                continue
            title = step.get("title")
            instructions = step.get("instructions")
            if not isinstance(title, str) or not isinstance(instructions, str):
                continue
            planned.append(
                {
                    "title": title.strip(),
                    "instructions": instructions.strip(),
                    "requires_approval": bool(step.get("requires_approval", False)),
                }
            )
        return planned or _build_default_plan(goal)
    except Exception:
        return _build_default_plan(goal)


def _render_plan_for_user(snapshot: Dict[str, Any]) -> str:
    steps = snapshot.get("steps") or []
    lines = ["Planned steps:"]
    for idx, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            continue
        title = step.get("title") or f"Step {idx}"
        approval = " (approval required)" if step.get("requires_approval") else ""
        lines.append(f"{idx}. {title}{approval}")
    return "\n".join(lines)


def _checkpoint(session_state: Dict[str, Any], snapshot: Dict[str, Any]) -> None:
    snapshot["updated_at"] = _now_ts()
    snapshot["checkpoint_seq"] = int(snapshot.get("checkpoint_seq", 0) or 0) + 1
    put_job_snapshot_in_session_state(session_state, snapshot)


def _load_or_create_snapshot(
    *,
    team: "Team",
    session_state: Dict[str, Any],
    session_id: str,
    user_id: Optional[str],
    mode: TeamExecutionMode,
    goal_input: str,
    job_id: Optional[str],
    resume: bool,
) -> Tuple[str, Dict[str, Any], bool]:
    if job_id is None and resume:
        job_id = get_latest_job_id_from_session_state(session_state)

    created = False
    if job_id is not None:
        existing = get_job_snapshot_from_session_state(session_state, job_id)
        if existing is not None:
            return job_id, existing, created

    job_id = job_id or str(uuid4())
    created = True
    snapshot: Dict[str, Any] = {
        "job_id": job_id,
        "team_id": team.id,
        "session_id": session_id,
        "user_id": user_id,
        "goal": goal_input,
        "mode": mode.value,
        "status": JobStatus.PENDING.value,
        "phase": JobPhase.PLAN.value,
        "pause": None,
        "steps": [],
        "cursor": 0,
        "budgets": None,
        "context_digest": None,
        "checkpoint_seq": 0,
        "created_at": _now_ts(),
        "updated_at": None,
    }
    put_job_snapshot_in_session_state(session_state, snapshot)
    return job_id, snapshot, created


def run_autonomy_sync(
    *,
    team: "Team",
    mode: TeamExecutionMode,
    run_response: TeamRunOutput,
    run_context: RunContext,
    session: "TeamSession",
    user_id: Optional[str],
    job_id: Optional[str],
    resume: bool,
    pause: bool,
    approval: Optional[bool],
) -> TeamRunOutput:
    session_state = run_context.session_state or {}
    run_context.session_state = session_state

    goal_input = run_response.input.input_content_string() if run_response.input is not None else ""

    job_id, snapshot, _created = _load_or_create_snapshot(
        team=team,
        session_state=session_state,
        session_id=session.session_id,
        user_id=user_id,
        mode=mode,
        goal_input=goal_input,
        job_id=job_id,
        resume=resume,
    )

    run_response.metadata = run_response.metadata or {}
    run_response.metadata["job_id"] = job_id

    if pause:
        pause_job_snapshot(snapshot, reason="manual_pause", gate_type="manual", message="Paused by user request.")
        _checkpoint(session_state, snapshot)
        team.save_session(session=session)
        run_response.status = RunStatus.paused
        run_response.content = "Job paused."
        return run_response

    if snapshot.get("status") == JobStatus.PAUSED.value:
        if not resume:
            run_response.status = RunStatus.paused
            pause_state = snapshot.get("pause") or {}
            run_response.content = pause_state.get("message") if isinstance(pause_state, dict) else None
            run_response.content = run_response.content or "Job is paused."
            return run_response

        if approval is None:
            run_response.status = RunStatus.paused
            pause_state = snapshot.get("pause") or {}
            run_response.content = pause_state.get("message") if isinstance(pause_state, dict) else None
            run_response.content = run_response.content or "Job is paused and needs approval."
            return run_response

        if approval is False:
            snapshot["status"] = JobStatus.CANCELLED.value
            snapshot["pause"] = None
            _checkpoint(session_state, snapshot)
            team.save_session(session=session)
            run_response.status = RunStatus.cancelled
            run_response.content = "Job cancelled."
            return run_response

        gate = snapshot.get("pause") or {}
        gate_type = gate.get("gate_type") if isinstance(gate, dict) else None
        payload = gate.get("payload") if isinstance(gate, dict) else None

        if gate_type == "plan_approval":
            snapshot["plan_approved"] = True
            resume_job_snapshot(snapshot)
            _checkpoint(session_state, snapshot)
            team.save_session(session=session)

        elif gate_type == "step_approval":
            cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if (
                isinstance(cursor, int)
                and isinstance(snapshot.get("steps"), list)
                and 0 <= cursor < len(snapshot["steps"])
            ):
                step = snapshot["steps"][cursor]
                if isinstance(step, dict):
                    step["approved"] = True
            resume_job_snapshot(snapshot)
            _checkpoint(session_state, snapshot)
            team.save_session(session=session)

        elif gate_type == "tool_confirmation":
            from agno.run.requirement import RunRequirement

            paused_run_id = payload.get("run_id") if isinstance(payload, dict) else None
            cursor = payload.get("cursor") if isinstance(payload, dict) else None
            requirements_raw = payload.get("requirements") if isinstance(payload, dict) else None
            requirements: List[RunRequirement] = []
            for item in requirements_raw or []:
                if isinstance(item, RunRequirement):
                    requirements.append(item)
                elif isinstance(item, dict):
                    requirements.append(RunRequirement.from_dict(item))

            # Auto-confirm confirmation requirements when the user approves the gate.
            for req in requirements:
                if req.needs_confirmation:
                    req.confirm()

            # If we still need user input or external execution, stay paused.
            if any(req.needs_user_input or req.needs_external_execution for req in requirements):
                run_response.status = RunStatus.paused
                run_response.requirements = requirements
                run_response.content = "Job is paused and needs user input or external execution to continue."
                return run_response

            if not isinstance(paused_run_id, str) or not paused_run_id:
                run_response.status = RunStatus.paused
                run_response.content = "Job is paused, but missing paused run_id to continue."
                return run_response

            resumed = team.continue_run(
                run_id=paused_run_id,
                requirements=requirements,
                session_id=session.session_id,
                user_id=user_id,
                stream=False,
            )

            if resumed.status == RunStatus.paused:
                pause_job_snapshot(
                    snapshot,
                    reason="hitl",
                    gate_type="tool_confirmation",
                    message=str(resumed.content) if resumed.content is not None else "Run is paused.",
                    payload={
                        "run_id": resumed.run_id,
                        "cursor": cursor,
                        "requirements": [req.to_dict() for req in (resumed.requirements or [])],
                    },
                )
                _checkpoint(session_state, snapshot)
                team.save_session(session=session)
                run_response.status = RunStatus.paused
                run_response.content = resumed.content
                run_response.requirements = resumed.requirements
                return run_response

            if resumed.status in {RunStatus.error, RunStatus.cancelled}:
                if isinstance(cursor, int) and isinstance(snapshot.get("steps"), list) and 0 <= cursor < len(snapshot["steps"]):
                    step = snapshot["steps"][cursor]
                    if isinstance(step, dict):
                        step["status"] = "failed"
                        step["run_id"] = resumed.run_id
                        step["result_summary"] = str(resumed.content) if resumed.content is not None else resumed.status.value
                snapshot["status"] = JobStatus.ERROR.value
                snapshot["phase"] = JobPhase.DONE.value
                snapshot["pause"] = None
                _checkpoint(session_state, snapshot)
                team.save_session(session=session)
                run_response.status = resumed.status
                run_response.content = "Job failed while continuing a paused tool call."
                return run_response

            # Tool call resumed successfully; finalize the step and continue the job loop.
            if isinstance(cursor, int) and isinstance(snapshot.get("steps"), list) and 0 <= cursor < len(snapshot["steps"]):
                step = snapshot["steps"][cursor]
                if isinstance(step, dict):
                    step["status"] = "completed"
                    step["run_id"] = resumed.run_id
                    result_str = str(resumed.content) if resumed.content is not None else ""
                    step["result_summary"] = result_str[:4000] if len(result_str) > 4000 else result_str
                snapshot["cursor"] = cursor + 1

            resume_job_snapshot(snapshot)
            _checkpoint(session_state, snapshot)
            team.save_session(session=session)

    if snapshot.get("status") in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value, JobStatus.ERROR.value}:
        run_response.status = RunStatus.completed
        run_response.content = snapshot.get("final_output") or f"Job already {snapshot.get('status')}."
        return run_response

    snapshot["status"] = JobStatus.RUNNING.value
    _checkpoint(session_state, snapshot)
    team.save_session(session=session)

    if not snapshot.get("steps"):
        planned_steps = _plan_steps_sync(team, snapshot.get("goal") or goal_input)
        steps: List[Dict[str, Any]] = []
        for idx, step in enumerate(planned_steps, 1):
            steps.append(
                {
                    "step_id": str(uuid4()),
                    "title": step["title"],
                    "instructions": step["instructions"],
                    "requires_approval": bool(step.get("requires_approval", False)),
                    "status": "pending",
                    "attempt": 0,
                    "max_attempts": 1,
                    "run_id": None,
                    "result_summary": None,
                }
            )
        snapshot["steps"] = steps
        snapshot["cursor"] = 0
        snapshot["phase"] = JobPhase.EXECUTE.value

        if mode == TeamExecutionMode.SUPERVISED and not snapshot.get("plan_approved"):
            pause_job_snapshot(
                snapshot,
                reason="hitl",
                gate_type="plan_approval",
                message=_render_plan_for_user(snapshot)
                + "\n\nTo continue, re-run with resume=True and approval=True.",
                payload={"steps": steps},
            )
            _checkpoint(session_state, snapshot)
            team.save_session(session=session)
            run_response.status = RunStatus.paused
            run_response.content = snapshot["pause"]["message"]
            return run_response

        _checkpoint(session_state, snapshot)
        team.save_session(session=session)

    original_cache_session = team.cache_session
    team.cache_session = True
    setattr(team, "_cached_session", session)

    try:
        steps = snapshot.get("steps") or []
        cursor = int(snapshot.get("cursor", 0) or 0)
        while cursor < len(steps):
            step = steps[cursor]
            if not isinstance(step, dict):
                cursor += 1
                continue

            if step.get("status") in {"completed", "skipped"}:
                cursor += 1
                snapshot["cursor"] = cursor
                continue

            if (
                mode == TeamExecutionMode.SUPERVISED
                and step.get("requires_approval")
                and step.get("status") == "pending"
                and not step.get("approved")
            ):
                pause_job_snapshot(
                    snapshot,
                    reason="hitl",
                    gate_type="step_approval",
                    message=f"Approval required before executing: {step.get('title')}\n\nTo continue, re-run with resume=True and approval=True.",
                    payload={"step_id": step.get("step_id"), "cursor": cursor},
                )
                _checkpoint(session_state, snapshot)
                team.save_session(session=session)
                run_response.status = RunStatus.paused
                run_response.content = snapshot["pause"]["message"]
                return run_response

            step["status"] = "running"
            step["attempt"] = int(step.get("attempt", 0) or 0) + 1
            _checkpoint(session_state, snapshot)
            team.save_session(session=session)

            step_prompt = (
                f"GOAL:\n{snapshot.get('goal')}\n\n"
                f"STEP {cursor + 1}: {step.get('title')}\n"
                f"INSTRUCTIONS:\n{step.get('instructions')}\n\n"
                "Return the result for this step."
            )

            step_run = team.run(
                step_prompt,
                session_id=session.session_id,
                user_id=user_id,
                stream=False,
                mode=TeamExecutionMode.COORDINATE,
                metadata={"job_id": job_id, "step_id": step.get("step_id")},
            )

            step["run_id"] = step_run.run_id
            if step_run.status == RunStatus.paused:
                pause_job_snapshot(
                    snapshot,
                    reason="hitl",
                    gate_type="tool_confirmation",
                    message=str(step_run.content) if step_run.content is not None else "Step paused waiting for tool confirmation.",
                    payload={
                        "run_id": step_run.run_id,
                        "cursor": cursor,
                        "requirements": [req.to_dict() for req in (step_run.requirements or [])],
                    },
                )
                _checkpoint(session_state, snapshot)
                team.save_session(session=session)
                run_response.status = RunStatus.paused
                run_response.content = step_run.content
                run_response.requirements = step_run.requirements
                return run_response

            if step_run.status in {RunStatus.error, RunStatus.cancelled}:
                step["status"] = "failed"
                step["result_summary"] = str(step_run.content) if step_run.content is not None else step_run.status.value
                _checkpoint(session_state, snapshot)
                team.save_session(session=session)
                snapshot["status"] = JobStatus.ERROR.value
                snapshot["phase"] = JobPhase.DONE.value
                _checkpoint(session_state, snapshot)
                team.save_session(session=session)
                run_response.status = RunStatus.error
                run_response.content = "Job failed during step execution."
                return run_response

            step["status"] = "completed"
            result_str = str(step_run.content) if step_run.content is not None else ""
            step["result_summary"] = result_str[:4000] if len(result_str) > 4000 else result_str

            cursor += 1
            snapshot["cursor"] = cursor
            _checkpoint(session_state, snapshot)
            team.save_session(session=session)

        snapshot["phase"] = JobPhase.SYNTHESIZE.value
        summaries = []
        for idx, step in enumerate(snapshot.get("steps") or [], 1):
            if not isinstance(step, dict):
                continue
            summaries.append(f"{idx}. {step.get('title')}\n{step.get('result_summary') or ''}".strip())

        system = Message(role="system", content="Synthesize a final answer for the user from the completed step results.")
        user = Message(
            role="user",
            content=f"GOAL:\n{snapshot.get('goal')}\n\nSTEP RESULTS:\n" + "\n\n".join(summaries),
        )
        model = team.model
        final = None
        if model is not None:
            final_resp = model.response(messages=[system, user], tools=None)
            final = final_resp.content

        snapshot["final_output"] = final if final is not None else "\n\n".join(summaries)
        snapshot["status"] = JobStatus.COMPLETED.value
        snapshot["phase"] = JobPhase.DONE.value
        _checkpoint(session_state, snapshot)
        team.save_session(session=session)

        run_response.status = RunStatus.completed
        run_response.content = snapshot["final_output"]
        return run_response
    finally:
        team.cache_session = original_cache_session


async def run_autonomy_async(
    *,
    team: "Team",
    mode: TeamExecutionMode,
    run_response: TeamRunOutput,
    run_context: RunContext,
    session: "TeamSession",
    user_id: Optional[str],
    job_id: Optional[str],
    resume: bool,
    pause: bool,
    approval: Optional[bool],
) -> TeamRunOutput:
    session_state = run_context.session_state or {}
    run_context.session_state = session_state

    goal_input = run_response.input.input_content_string() if run_response.input is not None else ""

    job_id, snapshot, _created = _load_or_create_snapshot(
        team=team,
        session_state=session_state,
        session_id=session.session_id,
        user_id=user_id,
        mode=mode,
        goal_input=goal_input,
        job_id=job_id,
        resume=resume,
    )

    run_response.metadata = run_response.metadata or {}
    run_response.metadata["job_id"] = job_id

    if pause:
        pause_job_snapshot(snapshot, reason="manual_pause", gate_type="manual", message="Paused by user request.")
        _checkpoint(session_state, snapshot)
        await team.asave_session(session=session)
        run_response.status = RunStatus.paused
        run_response.content = "Job paused."
        return run_response

    if snapshot.get("status") == JobStatus.PAUSED.value:
        if not resume:
            run_response.status = RunStatus.paused
            pause_state = snapshot.get("pause") or {}
            run_response.content = pause_state.get("message") if isinstance(pause_state, dict) else None
            run_response.content = run_response.content or "Job is paused."
            return run_response

        if approval is None:
            run_response.status = RunStatus.paused
            pause_state = snapshot.get("pause") or {}
            run_response.content = pause_state.get("message") if isinstance(pause_state, dict) else None
            run_response.content = run_response.content or "Job is paused and needs approval."
            return run_response

        if approval is False:
            snapshot["status"] = JobStatus.CANCELLED.value
            snapshot["pause"] = None
            _checkpoint(session_state, snapshot)
            await team.asave_session(session=session)
            run_response.status = RunStatus.cancelled
            run_response.content = "Job cancelled."
            return run_response

        gate = snapshot.get("pause") or {}
        gate_type = gate.get("gate_type") if isinstance(gate, dict) else None
        payload = gate.get("payload") if isinstance(gate, dict) else None

        if gate_type == "plan_approval":
            snapshot["plan_approved"] = True
            resume_job_snapshot(snapshot)
            _checkpoint(session_state, snapshot)
            await team.asave_session(session=session)

        elif gate_type == "step_approval":
            cursor = payload.get("cursor") if isinstance(payload, dict) else None
            if (
                isinstance(cursor, int)
                and isinstance(snapshot.get("steps"), list)
                and 0 <= cursor < len(snapshot["steps"])
            ):
                step = snapshot["steps"][cursor]
                if isinstance(step, dict):
                    step["approved"] = True
            resume_job_snapshot(snapshot)
            _checkpoint(session_state, snapshot)
            await team.asave_session(session=session)

        elif gate_type == "tool_confirmation":
            from agno.run.requirement import RunRequirement

            paused_run_id = payload.get("run_id") if isinstance(payload, dict) else None
            cursor = payload.get("cursor") if isinstance(payload, dict) else None
            requirements_raw = payload.get("requirements") if isinstance(payload, dict) else None
            requirements: List[RunRequirement] = []
            for item in requirements_raw or []:
                if isinstance(item, RunRequirement):
                    requirements.append(item)
                elif isinstance(item, dict):
                    requirements.append(RunRequirement.from_dict(item))

            for req in requirements:
                if req.needs_confirmation:
                    req.confirm()

            if any(req.needs_user_input or req.needs_external_execution for req in requirements):
                run_response.status = RunStatus.paused
                run_response.requirements = requirements
                run_response.content = "Job is paused and needs user input or external execution to continue."
                return run_response

            if not isinstance(paused_run_id, str) or not paused_run_id:
                run_response.status = RunStatus.paused
                run_response.content = "Job is paused, but missing paused run_id to continue."
                return run_response

            resumed = await team.acontinue_run(
                run_id=paused_run_id,
                requirements=requirements,
                session_id=session.session_id,
                user_id=user_id,
                stream=False,
            )

            if resumed.status == RunStatus.paused:
                pause_job_snapshot(
                    snapshot,
                    reason="hitl",
                    gate_type="tool_confirmation",
                    message=str(resumed.content) if resumed.content is not None else "Run is paused.",
                    payload={
                        "run_id": resumed.run_id,
                        "cursor": cursor,
                        "requirements": [req.to_dict() for req in (resumed.requirements or [])],
                    },
                )
                _checkpoint(session_state, snapshot)
                await team.asave_session(session=session)
                run_response.status = RunStatus.paused
                run_response.content = resumed.content
                run_response.requirements = resumed.requirements
                return run_response

            if resumed.status in {RunStatus.error, RunStatus.cancelled}:
                if (
                    isinstance(cursor, int)
                    and isinstance(snapshot.get("steps"), list)
                    and 0 <= cursor < len(snapshot["steps"])
                ):
                    step = snapshot["steps"][cursor]
                    if isinstance(step, dict):
                        step["status"] = "failed"
                        step["run_id"] = resumed.run_id
                        step["result_summary"] = str(resumed.content) if resumed.content is not None else resumed.status.value
                snapshot["status"] = JobStatus.ERROR.value
                snapshot["phase"] = JobPhase.DONE.value
                snapshot["pause"] = None
                _checkpoint(session_state, snapshot)
                await team.asave_session(session=session)
                run_response.status = resumed.status
                run_response.content = "Job failed while continuing a paused tool call."
                return run_response

            if (
                isinstance(cursor, int)
                and isinstance(snapshot.get("steps"), list)
                and 0 <= cursor < len(snapshot["steps"])
            ):
                step = snapshot["steps"][cursor]
                if isinstance(step, dict):
                    step["status"] = "completed"
                    step["run_id"] = resumed.run_id
                    result_str = str(resumed.content) if resumed.content is not None else ""
                    step["result_summary"] = result_str[:4000] if len(result_str) > 4000 else result_str
                snapshot["cursor"] = cursor + 1

            resume_job_snapshot(snapshot)
            _checkpoint(session_state, snapshot)
            await team.asave_session(session=session)

    if snapshot.get("status") in {JobStatus.COMPLETED.value, JobStatus.CANCELLED.value, JobStatus.ERROR.value}:
        run_response.status = RunStatus.completed
        run_response.content = snapshot.get("final_output") or f"Job already {snapshot.get('status')}."
        return run_response

    snapshot["status"] = JobStatus.RUNNING.value
    _checkpoint(session_state, snapshot)
    await team.asave_session(session=session)

    if not snapshot.get("steps"):
        planned_steps = await _plan_steps_async(team, snapshot.get("goal") or goal_input)
        steps: List[Dict[str, Any]] = []
        for idx, step in enumerate(planned_steps, 1):
            steps.append(
                {
                    "step_id": str(uuid4()),
                    "title": step["title"],
                    "instructions": step["instructions"],
                    "requires_approval": bool(step.get("requires_approval", False)),
                    "status": "pending",
                    "attempt": 0,
                    "max_attempts": 1,
                    "run_id": None,
                    "result_summary": None,
                }
            )
        snapshot["steps"] = steps
        snapshot["cursor"] = 0
        snapshot["phase"] = JobPhase.EXECUTE.value

        if mode == TeamExecutionMode.SUPERVISED and not snapshot.get("plan_approved"):
            pause_job_snapshot(
                snapshot,
                reason="hitl",
                gate_type="plan_approval",
                message=_render_plan_for_user(snapshot)
                + "\n\nTo continue, re-run with resume=True and approval=True.",
                payload={"steps": steps},
            )
            _checkpoint(session_state, snapshot)
            await team.asave_session(session=session)
            run_response.status = RunStatus.paused
            run_response.content = snapshot["pause"]["message"]
            return run_response

        _checkpoint(session_state, snapshot)
        await team.asave_session(session=session)

    original_cache_session = team.cache_session
    team.cache_session = True
    setattr(team, "_cached_session", session)

    try:
        steps = snapshot.get("steps") or []
        cursor = int(snapshot.get("cursor", 0) or 0)
        while cursor < len(steps):
            step = steps[cursor]
            if not isinstance(step, dict):
                cursor += 1
                continue

            if step.get("status") in {"completed", "skipped"}:
                cursor += 1
                snapshot["cursor"] = cursor
                continue

            if (
                mode == TeamExecutionMode.SUPERVISED
                and step.get("requires_approval")
                and step.get("status") == "pending"
                and not step.get("approved")
            ):
                pause_job_snapshot(
                    snapshot,
                    reason="hitl",
                    gate_type="step_approval",
                    message=f"Approval required before executing: {step.get('title')}\n\nTo continue, re-run with resume=True and approval=True.",
                    payload={"step_id": step.get("step_id"), "cursor": cursor},
                )
                _checkpoint(session_state, snapshot)
                await team.asave_session(session=session)
                run_response.status = RunStatus.paused
                run_response.content = snapshot["pause"]["message"]
                return run_response

            step["status"] = "running"
            step["attempt"] = int(step.get("attempt", 0) or 0) + 1
            _checkpoint(session_state, snapshot)
            await team.asave_session(session=session)

            step_prompt = (
                f"GOAL:\n{snapshot.get('goal')}\n\n"
                f"STEP {cursor + 1}: {step.get('title')}\n"
                f"INSTRUCTIONS:\n{step.get('instructions')}\n\n"
                "Return the result for this step."
            )

            step_run = await team.arun(
                step_prompt,
                session_id=session.session_id,
                user_id=user_id,
                stream=False,
                mode=TeamExecutionMode.COORDINATE,
                metadata={"job_id": job_id, "step_id": step.get("step_id")},
            )

            step["run_id"] = step_run.run_id
            if step_run.status == RunStatus.paused:
                pause_job_snapshot(
                    snapshot,
                    reason="hitl",
                    gate_type="tool_confirmation",
                    message=str(step_run.content) if step_run.content is not None else "Step paused waiting for tool confirmation.",
                    payload={
                        "run_id": step_run.run_id,
                        "cursor": cursor,
                        "requirements": [req.to_dict() for req in (step_run.requirements or [])],
                    },
                )
                _checkpoint(session_state, snapshot)
                await team.asave_session(session=session)
                run_response.status = RunStatus.paused
                run_response.content = step_run.content
                run_response.requirements = step_run.requirements
                return run_response

            if step_run.status in {RunStatus.error, RunStatus.cancelled}:
                step["status"] = "failed"
                step["result_summary"] = str(step_run.content) if step_run.content is not None else step_run.status.value
                _checkpoint(session_state, snapshot)
                await team.asave_session(session=session)
                snapshot["status"] = JobStatus.ERROR.value
                snapshot["phase"] = JobPhase.DONE.value
                _checkpoint(session_state, snapshot)
                await team.asave_session(session=session)
                run_response.status = RunStatus.error
                run_response.content = "Job failed during step execution."
                return run_response

            step["status"] = "completed"
            result_str = str(step_run.content) if step_run.content is not None else ""
            step["result_summary"] = result_str[:4000] if len(result_str) > 4000 else result_str

            cursor += 1
            snapshot["cursor"] = cursor
            _checkpoint(session_state, snapshot)
            await team.asave_session(session=session)

        snapshot["phase"] = JobPhase.SYNTHESIZE.value
        summaries = []
        for idx, step in enumerate(snapshot.get("steps") or [], 1):
            if not isinstance(step, dict):
                continue
            summaries.append(f"{idx}. {step.get('title')}\n{step.get('result_summary') or ''}".strip())

        system = Message(role="system", content="Synthesize a final answer for the user from the completed step results.")
        user = Message(
            role="user",
            content=f"GOAL:\n{snapshot.get('goal')}\n\nSTEP RESULTS:\n" + "\n\n".join(summaries),
        )
        model = team.model
        final = None
        if model is not None:
            final_resp = await model.aresponse(messages=[system, user], tools=None)
            final = final_resp.content

        snapshot["final_output"] = final if final is not None else "\n\n".join(summaries)
        snapshot["status"] = JobStatus.COMPLETED.value
        snapshot["phase"] = JobPhase.DONE.value
        _checkpoint(session_state, snapshot)
        await team.asave_session(session=session)

        run_response.status = RunStatus.completed
        run_response.content = snapshot["final_output"]
        return run_response
    finally:
        team.cache_session = original_cache_session
