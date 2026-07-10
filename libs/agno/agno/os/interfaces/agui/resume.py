from typing import List, Union

from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent import Agent
from agno.run.base import RunContext, RunStatus
from agno.run.requirement import RunRequirement
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team.team import Team


def apply_tool_results_to_requirements(
    requirements: List[RunRequirement],
    tool_messages: List[AGUIToolMessage],
) -> List[RunRequirement]:
    """Apply frontend tool results to requirements awaiting external execution."""
    results_map = {tm.tool_call_id: (tm.content, getattr(tm, "error", None)) for tm in tool_messages}

    for req in requirements:
        # set_external_execution_result raises ValueError for requirements not awaiting
        # external execution (already resolved, or HITL confirmation/input types)
        if not req.needs_external_execution or not req.tool_execution:
            continue

        tool_call_id = req.tool_execution.tool_call_id
        if tool_call_id and tool_call_id in results_map:
            content, error = results_map[tool_call_id]
            if error:
                req.set_external_execution_result(str(error))
                req.tool_execution.tool_call_error = True
            else:
                req.set_external_execution_result(content)

    return requirements


async def resume_paused_run(
    entity: Union[Agent, Team],
    session_id: str,
    tool_messages: list,
    run_context: RunContext,
    run_kwargs: dict,
):
    """Resume a paused run by applying frontend tool results and continuing."""
    # Remote entities don't support client_tools resume (no aget_session)
    if not getattr(entity, "db", None):
        raise ValueError(
            "Frontend tool resume requires a database. Set db=SqliteDb(...) or db=PgDb(...) on your Agent/Team."
        )

    session = await entity.aget_session(session_id=session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    if not isinstance(session, (AgentSession, TeamSession)):
        raise ValueError(f"Session {session_id} is not a valid session type")

    # Find the paused run (AG-UI sends new run_id on resume, so we find by status)
    # Match on tool_call_ids: the session may hold multiple paused runs (e.g. one the
    # user abandoned), and the incoming results identify which run is being resumed
    incoming_tool_call_ids = {tm.tool_call_id for tm in tool_messages}
    paused_run = next(
        (
            r
            for r in (session.runs or [])
            if r.status == RunStatus.paused
            and any(
                req.tool_execution and req.tool_execution.tool_call_id in incoming_tool_call_ids
                for req in (r.requirements or [])
            )
        ),
        None,
    )
    if not paused_run:
        raise ValueError(f"No paused run matching the provided tool results found in session {session_id}")

    if not paused_run.requirements:
        raise ValueError(f"Run {paused_run.run_id} has no requirements to resume")

    # Apply tool results from frontend into stored requirements
    requirements = apply_tool_results_to_requirements(paused_run.requirements, tool_messages)

    # Continue under the original run_id, not the new one AG-UI generated for this resume request
    paused_run_id = paused_run.run_id or run_context.run_id
    run_context.run_id = paused_run_id
    return entity.acontinue_run(  # type: ignore
        run_id=paused_run_id,
        session_id=session_id,
        requirements=requirements,
        stream=True,
        stream_events=True,
        run_context=run_context,
        **run_kwargs,
    )
