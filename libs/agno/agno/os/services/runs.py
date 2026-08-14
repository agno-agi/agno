"""Run-lifecycle operations (continue, cancel) shared by REST and MCP surfaces.

The continue payloads mirror what the surfaces hand the client when a run
pauses: agents/teams ship ``RunRequirement`` dicts, workflows ship
``StepRequirement`` dicts. The client resolves them (confirmation, input,
selection) and passes them back verbatim.
"""

from typing import Any, Dict, List, Optional, Union

from agno.agent.agent import Agent
from agno.remote.base import BaseRemote
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.team.team import Team
from agno.workflow.workflow import Workflow

AnyRunOutput = Union[RunOutput, TeamRunOutput, WorkflowRunOutput]


class RemoteContinuationUnsupported(Exception):
    """Raised when continue is attempted on a remote component over a surface that
    cannot forward HITL requirements to it (mirrors the REST 400 guard)."""


def parse_run_requirements(requirements: Optional[List[Dict[str, Any]]]) -> Optional[List[RunRequirement]]:
    if not requirements:
        return None
    return [RunRequirement.from_dict(req) if isinstance(req, dict) else req for req in requirements]


def parse_step_requirements(requirements: Optional[List[Dict[str, Any]]]) -> Optional[List[Any]]:
    from agno.workflow.types import StepRequirement

    if not requirements:
        return None
    return [StepRequirement.from_dict(req) if isinstance(req, dict) else req for req in requirements]


async def continue_paused_run(
    component: Union[Agent, Team, Workflow],
    *,
    run_id: str,
    session_id: Optional[str],
    user_id: Optional[str] = None,
    requirements: Optional[List[Dict[str, Any]]] = None,
) -> AnyRunOutput:
    """Resume a paused run on any local component with the client's resolved requirements.

    Remote components are rejected: their ``acontinue_run`` cannot carry resolved
    requirements (the REST surface 400s the same case), so failing clearly beats the
    opaque downstream TypeError that forwarding them would raise.

    ``stream=False`` is pinned: run-option resolution is call-site > component.stream >
    False, so a component configured with ``stream=True`` would otherwise return an
    async iterator instead of the final run output.
    """
    if isinstance(component, BaseRemote):
        raise RemoteContinuationUnsupported(
            "Continuing paused runs on remote components is not supported over this interface."
        )
    # Inline-door admission gate: a paused/queued/running durable ticket OWNS
    # this run's continuation, and that holds for EVERY public interface -
    # this service backs the MCP continue_run tool, which must not execute a
    # ticketed run inline while an HTTP durable continue CASes the ticket
    # (the cross-door double-execution race). 409/503 HTTPException raises.
    from agno.os.job_queue import araise_if_ticket_owns_continue, get_active_queue_worker

    component_type = (
        "workflow" if isinstance(component, Workflow) else ("team" if isinstance(component, Team) else "agent")
    )
    await araise_if_ticket_owns_continue(
        get_active_queue_worker(), run_id, component_type=component_type, component_id=getattr(component, "id", None)
    )
    if isinstance(component, Workflow):
        result: AnyRunOutput = await component.acontinue_run(
            run_id=run_id,
            session_id=session_id,
            step_requirements=parse_step_requirements(requirements),
            stream=False,
        )
    else:
        result = await component.acontinue_run(  # type: ignore[misc]
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            requirements=parse_run_requirements(requirements),
            stream=False,
        )
    # Status-only stream sync (parity with the REST non-stream continue
    # door): a formerly-queued/streamed run's stream view must stop saying
    # PAUSED once the continue settles - otherwise every later /resume
    # replays the stale paused snapshot, and on Redis the pausing replica's
    # TTL refresher keeps those keys alive indefinitely. only_if_tracked
    # leaves never-streamed runs alone; a re-paused continue re-parks the
    # stream as PAUSED.
    from agno.os.utils import acomplete_continue_stream

    await acomplete_continue_stream(
        component,
        run_id,
        session_id,
        only_if_tracked=True,
        final_status=getattr(result, "status", None),
    )
    return result


async def cancel_component_run(component: Union[Agent, Team, Workflow], run_id: str) -> None:
    """Request cancellation of ``run_id`` on the component that owns it.

    Local agent/team/workflow cancellation all delegate to one process-global
    cancellation manager that records an intent even for a not-yet-registered run, so
    it always succeeds -- ownership is enforced by the caller before we get here
    (mirroring the REST cancel endpoints), which is also what keeps a bogus id from
    leaking an entry. (Its False return means "intent stored for an unregistered run",
    which is cancel-before-start, not failure.) Remote components forward the cancel
    over HTTP and return False when the call fails; that must surface, not read as
    success.
    """
    # Tombstone a still-queued durable ticket first (parity with the REST
    # cancel routes): intent alone does not stop a job no task is executing
    # yet - without this, a worker claims the waiting ticket, starts the leg,
    # and the leg only dies at its first cancellation checkpoint, burning an
    # attempt and stamping a spurious execution start on the run row.
    # acancel_queued is a no-op for unticketed or already-executing runs.
    from agno.os.job_queue import get_active_queue_worker

    queue_worker = get_active_queue_worker()
    if queue_worker is not None:
        await queue_worker.acancel_queued(run_id)
    cancelled = await component.acancel_run(run_id=run_id)
    if cancelled is False and isinstance(component, BaseRemote):
        raise Exception(f"Cancellation of run {run_id} could not be delivered to the remote component.")
