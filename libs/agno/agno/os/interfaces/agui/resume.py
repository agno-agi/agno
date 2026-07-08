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
    # Frontend executed the tools; ToolMessages carry the results the paused run is waiting on
    results_map = {tm.tool_call_id: (tm.content, getattr(tm, "error", None)) for tm in tool_messages}

    for req in requirements:
        if not req.tool_execution or not req.tool_execution.tool_call_id:
            continue
        tool_call_id = req.tool_execution.tool_call_id
        if tool_call_id not in results_map:
            continue

        content, error = results_map[tool_call_id]
        if error:
            # Use SDK method then mark as error
            req.set_external_execution_result(str(error))
            if req.tool_execution:
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
    paused_run = next(
        (r for r in (session.runs or []) if r.status == RunStatus.paused),
        None,
    )
    if not paused_run:
        raise ValueError(f"No paused run found in session {session_id}")

    if not paused_run.requirements:
        raise ValueError(f"Run {paused_run.run_id} has no requirements to resume")

    # Apply tool results from frontend into stored requirements
    requirements = apply_tool_results_to_requirements(paused_run.requirements, tool_messages)

    # Resume the run using the original paused run's ID
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
